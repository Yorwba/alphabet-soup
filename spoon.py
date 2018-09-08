#!/usr/bin/env python3

import argparse
import os
import math
import sqlite3
import subprocess

import PySide2.QtCore as qc
import PySide2.QtGui as qg
import PySide2.QtMultimedia as qm
import PySide2.QtWidgets as qw


def refresh(cursor, table, kinds, ids):
    cursor.executemany(
        f'''
        UPDATE {table} SET
        {','.join(
            f"""
            {kind}memory_strength = IFNULL(
                {kind}memory_strength + julianday("now") - last_{kind}refresh,
                25),
            last_{kind}refresh = julianday("now")
            """ for kind in kinds)}
        WHERE id = ?
        ''',
        ids)


def get_audio(cursor, sentence, source_id):
    for ext in ('wav', 'mp3'):
        path = f'data/audio/{sentence}.{ext}'
        if os.path.isfile(path):
            return path

    try:
        (creator, license, attribution) = next(cursor.execute(
            f'''
            SELECT user, license, attribution
            FROM sentences_with_audio
            WHERE id = ?
            ''',
            (source_id,)))
        url = f'https://audio.tatoeba.org/sentences/jpn/{source_id}.mp3'
        file_path = f'data/audio/{sentence}.mp3'
        import urllib.request
        urllib.request.urlretrieve(url, file_path)
        print(f'Downloaded audio by {creator} ({attribution}), '
              f'licensed under {license}, from {url}')
        return file_path
    except StopIteration:  # no audio on Tatoeba
        pass

    file_path = f'data/audio/{sentence}.wav'
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    subprocess.run(
        ['open_jtalk',
         '-x', '/var/lib/mecab/dic/open-jtalk/naist-jdic/',
         '-m', '/usr/share/hts-voice/nitech-jp-atr503-m001/nitech_jp_atr503_m001.htsvoice',
         '-g', '10',  # volume: 10 dB
         '-ow', file_path],
        input=sentence.encode('utf-8'),
        check=True)
    print('Generated audio using Open JTalk (http://open-jtalk.sourceforge.net)')
    return file_path


def get_sentence_details(cursor, id, only_new=True):
    lemmas = list(cursor.execute(
        f'''
        SELECT lemma.id, lemma.text, lemma.disambiguator
        FROM lemma, sentence_lemma
        WHERE sentence_id = {id}
        AND lemma_id = lemma.id
        {'AND memory_strength IS NULL' if only_new else ''}
        '''))
    grammars = list(cursor.execute(
        f'''
        SELECT grammar.id, grammar.form
        FROM grammar, sentence_grammar
        WHERE sentence_id = {id}
        AND grammar_id = grammar.id
        {'AND memory_strength IS NULL' if only_new else ''}
        '''))
    graphemes = list(cursor.execute(
        f'''
        SELECT grapheme.id, grapheme.text
        FROM grapheme, sentence_grapheme
        WHERE sentence_id = {id}
        AND grapheme_id = grapheme.id
        {'AND memory_strength IS NULL' if only_new else ''}
        '''))
    forward_pronunciations = list(cursor.execute(
        f'''
        SELECT pronunciation.id, pronunciation.word, pronunciation.pronunciation
        FROM pronunciation, sentence_pronunciation
        WHERE sentence_id = {id}
        AND pronunciation_id = pronunciation.id
        {'AND forward_memory_strength IS NULL' if only_new else ''}
        '''))
    backward_pronunciations = list(cursor.execute(
        f'''
        SELECT pronunciation.id, pronunciation.pronunciation, pronunciation.word
        FROM pronunciation, sentence_pronunciation
        WHERE sentence_id = {id}
        AND pronunciation_id = pronunciation.id
        {'AND backward_memory_strength IS NULL' if only_new else ''}
        '''))
    sounds = list(cursor.execute(
        f'''
        SELECT sound.id, sound.text
        FROM sound, sentence_sound
        WHERE sentence_id = {id}
        AND sound_id = sound.id
        {'AND memory_strength IS NULL' if only_new else ''}
        '''))
    return lemmas, grammars, graphemes, forward_pronunciations, backward_pronunciations, sounds


def get_translation(tatoeba_cursor, source_id, translation_language):
    try:
        (translation,) = next(tatoeba_cursor.execute(
            f'''
            SELECT sentences_detailed.text
            FROM sentences_detailed, links
            WHERE sentences_detailed.lang = ?
            AND sentences_detailed.id = links.translation_id
            AND links.sentence_id = ?
            ''',
            (translation_language, source_id)))
        return translation
    except StopIteration:
        return ''


def show_sentence_detail_dialog(
        text,
        pronunciation,
        translation,
        source_url,
        creator,
        license_url,
        lemmas,
        grammars,
        graphemes,
        forward_pronunciations,
        backward_pronunciations,
        sounds,
        audio_file,
        callback):
    dialog = qw.QDialog()
    possible_fonts = qg.QFontDatabase().families(qg.QFontDatabase.Japanese)
    japanese_fonts = [font for font in possible_fonts if 'jp' in font.lower()]
    font = qg.QFont(japanese_fonts[0])
    dialog.setFont(font)
    big_font = qg.QFont(font)
    big_font.setPointSize(font.pointSize()*1.5)
    rows = (row.split('\t') for row in (text, pronunciation))
    dialog.text_pronunciation_table = qw.QLabel(
        f'''<table><tr>{
            '</tr/><tr>'.join(
                ''.join(f'<td>{part}</td>' for part in row)
                for row in rows)
                }</tr></table>''')
    dialog.text_pronunciation_table.setFont(big_font)
    dialog.text_pronunciation_table.setTextInteractionFlags(qc.Qt.TextSelectableByMouse)
    dialog.translation = qw.QLabel(translation)
    dialog.translation.setFont(big_font)
    dialog.translation.setTextInteractionFlags(qc.Qt.TextSelectableByMouse)
    dialog.attribution =  qw.QLabel(
        f'Example from <a href="{source_url}">{source_url}</a> '
        f'by {creator}, '
        f'licensed under <a href="{license_url}">{license_url}</a>')
    dialog.attribution.setOpenExternalLinks(True)
    dialog.learn_button = qw.QPushButton('Learn')
    dialog.learn_button.setDefault(True)

    hlayout = qw.QHBoxLayout()
    lemma_checkboxes = []
    grammar_checkboxes = []
    grapheme_checkboxes = []
    forward_pronunciation_checkboxes = []
    backward_pronunciation_checkboxes = []
    sound_checkboxes = []
    for memory_items, checkboxes, template in (
            (lemmas, lemma_checkboxes, 'the meaning of %s (%s)'),
            (grammars, grammar_checkboxes, 'the form %s'),
            (graphemes, grapheme_checkboxes, 'writing %s'),
            (forward_pronunciations, forward_pronunciation_checkboxes, '%s pronounced as %s'),
            (backward_pronunciations, backward_pronunciation_checkboxes, '%s written as %s'),
            (sounds, sound_checkboxes, 'pronouncing %s')):
        vlayout = qw.QVBoxLayout()
        for item in memory_items:
            checkbox = qw.QCheckBox(template % item[1:])
            checkbox.setCheckState(qc.Qt.CheckState.Checked)
            checkboxes.append(checkbox)
            vlayout.addWidget(checkbox)
        hlayout.addLayout(vlayout)

    def learn():
        dialog.media_player.stop()
        dialog.accept()
        callback(**{
            table+'_selected': [
                item[0]
                for item, checkbox in zip(memory_items, checkboxes)
                if checkbox.isChecked()]
            for table, memory_items, checkboxes in (
                ('lemma', lemmas, lemma_checkboxes),
                ('grammar', grammars, grammar_checkboxes),
                ('grapheme', graphemes, grapheme_checkboxes),
                ('forward_pronunciation', forward_pronunciations, forward_pronunciation_checkboxes),
                ('backward_pronunciation', backward_pronunciations, backward_pronunciation_checkboxes),
                ('sound', sounds, sound_checkboxes))})

    dialog.learn_button.clicked.connect(learn)

    vlayout = qw.QVBoxLayout()
    vlayout.addWidget(dialog.text_pronunciation_table)
    vlayout.addWidget(dialog.translation)
    vlayout.addLayout(hlayout)
    vlayout.addWidget(dialog.attribution)
    vlayout.addWidget(dialog.learn_button)
    dialog.setLayout(vlayout)

    dialog.playlist = qm.QMediaPlaylist()
    dialog.playlist.addMedia(qc.QUrl.fromLocalFile(os.path.abspath(audio_file)))
    dialog.playlist.setPlaybackMode(qm.QMediaPlaylist.Loop)
    dialog.media_player = qm.QMediaPlayer()
    dialog.media_player.setPlaylist(dialog.playlist)
    dialog.media_player.play()

    dialog.show()

    return dialog


def recommend_sentence(args):
    conn = sqlite3.connect(args.database)
    c = conn.cursor()
    c.execute('PRAGMA synchronous = off')
    (id, text, source_url, source_id, license_url, creator, pronunciation,
     payoff_effort_ratio) = next(c.execute(
        f'''
        SELECT id, text, source_url, source_id, license_url, creator, pronunciation,
            unknown_percentage/unknown_factors as payoff_effort_ratio
        FROM sentence
        WHERE source_database = 'tatoeba'
        ORDER BY payoff_effort_ratio DESC
        LIMIT 1
    '''))
    lemmas, grammars, graphemes, forward_pronunciations, backward_pronunciations, sounds = get_sentence_details(c, id)
    tatoeba_conn = sqlite3.connect(args.tatoeba_database)
    tc = tatoeba_conn.cursor()
    translation = get_translation(tc, source_id, args.translation_language)
    audio_file = get_audio(tc, text.replace('\t', ''), source_id)

    app = qw.QApplication()

    def refresh_callback(
            lemma_selected, grammar_selected, grapheme_selected,
            forward_pronunciation_selected, backward_pronunciation_selected,
            sound_selected):
        for table, kinds, selected in (
                ('lemma', ('',), lemma_selected),
                ('grammar', ('',), grammar_selected),
                ('grapheme', ('',), grapheme_selected),
                ('pronunciation', ('forward_',), forward_pronunciation_selected),
                ('pronunciation', ('backward_',), backward_pronunciation_selected),
                ('sound', ('',), sound_selected)):
            refresh(c, table, kinds, [(selection,) for selection in selected])
        conn.commit()

    dialog = show_sentence_detail_dialog(
        text, pronunciation, translation,
        source_url, creator, license_url,
        lemmas, grammars, graphemes,
        forward_pronunciations, backward_pronunciations, sounds,
        audio_file, refresh_callback)

    app.exec_()


def review(args):
    conn = sqlite3.connect(args.database)
    c = conn.cursor()
    c.execute('PRAGMA synchronous = off')
    app = qw.QApplication()

    scheduled_reviews = list(c.execute(
        f'''
        SELECT id, text, source_url, source_id, license_url, creator, pronunciation,
            inverse_memory_strength_weighted_last_refresh
            - julianday('now')*summed_inverse_memory_strength AS log_retention
        FROM sentence, review
        WHERE sentence.id = sentence_id
        AND log_retention < ?
        ORDER BY log_retention ASC
        ''',
        (math.log(args.desired_retention),)))

    def generate_reviews():
        for (id, text, source_url, source_id, license_url, creator, pronunciation,
             log_retention) in scheduled_reviews:
            print(log_retention, math.exp(log_retention))
            lemmas, grammars, graphemes, forward_pronunciations, backward_pronunciations, sounds = get_sentence_details(c, id, only_new=False)
            tatoeba_conn = sqlite3.connect(args.tatoeba_database)
            tc = tatoeba_conn.cursor()
            translation = get_translation(tc, source_id, args.translation_language)
            audio_file = get_audio(tc, text.replace('\t', ''), source_id)

            def review_callback(
                    lemma_selected, grammar_selected, grapheme_selected,
                    forward_pronunciation_selected, backward_pronunciation_selected,
                    sound_selected):
                for table, kinds, selected in (
                        ('lemma', ('',), lemma_selected),
                        ('grammar', ('',), grammar_selected),
                        ('grapheme', ('',), grapheme_selected),
                        ('pronunciation', ('forward_',), forward_pronunciation_selected),
                        ('pronunciation', ('backward_',), backward_pronunciation_selected),
                        ('sound', ('',), sound_selected)):
                    refresh(c, table, kinds, [(selection,) for selection in selected])
                conn.commit()

                try:
                    next(review_generator)
                except StopIteration:
                    pass

            dialog = show_sentence_detail_dialog(
                text, pronunciation, translation,
                source_url, creator, license_url,
                lemmas, grammars, graphemes,
                forward_pronunciations, backward_pronunciations, sounds,
                audio_file, review_callback)
            yield

    review_generator = generate_reviews()
    next(review_generator)

    app.exec_()


def main(argv):
    parser = argparse.ArgumentParser(
        description='Example sentence recommender')
    parser.add_argument('command', nargs=1, choices={'recommend-sentence', 'review'})
    parser.add_argument('--database', type=str, default='data/japanese_sentences.sqlite')
    parser.add_argument('--tatoeba-database', type=str, default='data/tatoeba.sqlite')
    parser.add_argument('--translation-language', type=str, default='eng')
    parser.add_argument('--desired-retention', type=float, default=0.95)
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    import sys
    main(sys.argv)
