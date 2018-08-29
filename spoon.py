#!/usr/bin/env python3

import argparse
import os
import sqlite3
import subprocess


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
    lemmas = list(c.execute(
        f'''
        SELECT lemma.id, lemma.text, lemma.disambiguator
        FROM lemma, sentence_lemma
        WHERE sentence_id = {id}
        AND lemma_id = lemma.id
        AND memory_strength IS NULL
        '''))
    grammars = list(c.execute(
        f'''
        SELECT grammar.id, grammar.form
        FROM grammar, sentence_grammar
        WHERE sentence_id = {id}
        AND grammar_id = grammar.id
        AND memory_strength IS NULL
        '''))
    graphemes = list(c.execute(
        f'''
        SELECT grapheme.id, grapheme.text
        FROM grapheme, sentence_grapheme
        WHERE sentence_id = {id}
        AND grapheme_id = grapheme.id
        AND memory_strength IS NULL
        '''))
    pronunciations = list(c.execute(
        f'''
        SELECT pronunciation.id, pronunciation.word, pronunciation.pronunciation
        FROM pronunciation, sentence_pronunciation
        WHERE sentence_id = {id}
        AND pronunciation_id = pronunciation.id
        AND (forward_memory_strength IS NULL OR backward_memory_strength IS NULL)
        '''))
    sounds = list(c.execute(
        f'''
        SELECT sound.id, sound.text
        FROM sound, sentence_sound
        WHERE sentence_id = {id}
        AND sound_id = sound.id
        AND memory_strength IS NULL
        '''))
    tatoeba_conn = sqlite3.connect(args.tatoeba_database)
    tc = tatoeba_conn.cursor()
    try:
        (translation,) = next(tc.execute(
            f'''
            SELECT sentences_detailed.text
            FROM sentences_detailed, links
            WHERE sentences_detailed.lang = ?
            AND sentences_detailed.id = links.translation_id
            AND links.sentence_id = ?
            ''',
            (args.translation_language, source_id)))
    except StopIteration:
        translation = ''
    audio_file = get_audio(tc, text.replace('\t', ''), source_id)

    import PySide2.QtCore as qc
    import PySide2.QtGui as qg
    import PySide2.QtMultimedia as qm
    import PySide2.QtWidgets as qw
    app = qw.QApplication()
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
    pronunciation_checkboxes = []
    sound_checkboxes = []
    for memory_items, checkboxes, template in (
            (lemmas, lemma_checkboxes, 'the meaning of %s (%s)'),
            (grammars, grammar_checkboxes, 'the form %s'),
            (graphemes, grapheme_checkboxes, 'writing %s'),
            (pronunciations, pronunciation_checkboxes, '%s pronounced as %s'),
            (sounds, sound_checkboxes, 'pronouncing %s')):
        vlayout = qw.QVBoxLayout()
        for item in memory_items:
            checkbox = qw.QCheckBox(template % item[1:])
            checkbox.setCheckState(qc.Qt.CheckState.Checked)
            checkboxes.append(checkbox)
            vlayout.addWidget(checkbox)
        hlayout.addLayout(vlayout)

    def learn():
        for table, kinds, memory_items, checkboxes in (
                ('lemma', ('',), lemmas, lemma_checkboxes),
                ('grammar', ('',), grammars, grammar_checkboxes),
                ('grapheme', ('',), graphemes, grapheme_checkboxes),
                ('pronunciation', ('forward_', 'backward_'), pronunciations, pronunciation_checkboxes),
                ('sound', ('',), sounds, sound_checkboxes)):
            refresh(c, table, kinds, [
                (item[0],)
                for item, checkbox in zip(memory_items, checkboxes)
                if checkbox.isChecked()])
        conn.commit()
        dialog.accept()

    dialog.learn_button.clicked.connect(learn)

    vlayout = qw.QVBoxLayout()
    vlayout.addWidget(dialog.text_pronunciation_table)
    vlayout.addWidget(dialog.translation)
    vlayout.addLayout(hlayout)
    vlayout.addWidget(dialog.attribution)
    vlayout.addWidget(dialog.learn_button)
    dialog.setLayout(vlayout)
    dialog.show()
    playlist = qm.QMediaPlaylist()
    playlist.addMedia(qc.QUrl.fromLocalFile(os.path.abspath(audio_file)))
    playlist.setPlaybackMode(qm.QMediaPlaylist.Loop)
    media_player = qm.QMediaPlayer()
    media_player.setPlaylist(playlist)
    media_player.play()
    app.exec_()


def main(argv):
    parser = argparse.ArgumentParser(
        description='Example sentence recommender')
    parser.add_argument('command', nargs=1, choices={'recommend-sentence'})
    parser.add_argument('--database', type=str, default='data/japanese_sentences.sqlite')
    parser.add_argument('--tatoeba-database', type=str, default='data/tatoeba.sqlite')
    parser.add_argument('--translation-language', type=str, default='eng')
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    import sys
    main(sys.argv)
