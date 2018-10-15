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

from japanese_data import ReviewType

#: Let's say 1 in 20 reviewed sentences containing a forgotten word is okay.
DEFAULT_RETENTION = 0.95

#: Strength which makes retention drop below DEFAULT RETENTION within a day.
#: (Assuming 3 details are learned at once [word, to/from pronunciation].)
MEMORY_STRENGTH_PER_DAY = -3/math.log(DEFAULT_RETENTION)


def refresh(cursor, table, kinds, ids):
    cursor.executemany(
        f'''
        UPDATE {table} SET
        {','.join(
            f"""
            {kind}memory_strength = IFNULL(
                {kind}memory_strength
                + {MEMORY_STRENGTH_PER_DAY}*(
                    julianday("now") - last_{kind}refresh) ,
                {MEMORY_STRENGTH_PER_DAY}),
            last_{kind}refresh = julianday("now")
            """ for kind in kinds)}
        WHERE id = ?
        ''',
        ids)


def relearn(cursor, table, kinds, ids):
    cursor.executemany(
        f'''
        UPDATE {table} SET
        {','.join(
            f"""
            {kind}memory_strength = {MEMORY_STRENGTH_PER_DAY}
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


def get_sentence_details(cursor, id, only_new=True, translation_language='eng'):
    lemmas = list(cursor.execute(
        f'''
        SELECT lemma.id, lemma.text, lemma.disambiguator
        FROM lemma, sentence_lemma
        WHERE sentence_id = {id}
        AND lemma_id = lemma.id
        {'AND memory_strength IS NULL' if only_new else ''}
        '''))
    lemmas = [
        (id,
         text,
         disambiguator,
         get_dictionary_gloss(cursor, text, disambiguator, translation_language))
        for (id, text, disambiguator)
        in lemmas]
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


def get_dictionary_gloss(cursor, lemma, disambiguator, translation_language):
    lemma = lemma.split('-')[0]
    glosses = set(
        gloss
        for (gloss,) in cursor.execute(
            '''
            SELECT gloss
            FROM dictionary.disambiguator_to_pos
                NATURAL JOIN dictionary.entry
                NATURAL JOIN dictionary.gloss
            WHERE lemma = ?
                AND disambiguator = ?
                AND lang = ?
            ''',
            (lemma, disambiguator, translation_language)))
    return '\n\n'.join(glosses)


class MovieLabel(qw.QLabel):

    def __init__(self, movie, size, hover_size=None):
        super(MovieLabel, self).__init__()
        if hover_size is None:
            hover_size = size
        self.size = size
        self.hover_size = hover_size
        movie = qg.QMovie(movie)
        movie.setScaledSize(size)
        movie.start()
        self.setMovie(movie)

    def enterEvent(self, event):
        self.movie().setScaledSize(self.hover_size)

    def leaveEvent(self, event):
        self.movie().setScaledSize(self.size)


class VerticalScrollFrame(qw.QFrame):

    def __init__(self):
        super(VerticalScrollFrame, self).__init__()
        scrollarea = qw.QScrollArea()
        scrollarea.setWidgetResizable(True)
        scrollarea.setHorizontalScrollBarPolicy(qc.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scrollarea.setWidget(self)
        self.scrollarea = scrollarea

    def resizeEvent(self, event):
        self.scrollarea.setMinimumWidth(
            self.sizeHint().width()
            + self.scrollarea.verticalScrollBar().sizeHint().width())


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
    graphemes = sorted(graphemes, key=lambda grapheme: text.index(grapheme[1]))
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

    def lemma_template(lemma, disambiguator, gloss):
        text = 'the meaning of %s (%s)' % (lemma, disambiguator)
        movie = None
        tooltip = gloss
        return text, movie, tooltip

    def writing_template(grapheme):
        relative_path = f'data/kanjivg/kanji/{ord(grapheme):05x}.gif'
        gif_path = os.path.join(os.path.dirname(__file__), relative_path)
        text = 'writing '
        movie = os.path.abspath(gif_path)
        tooltip = grapheme
        return text, movie, tooltip

    def format_template(template):
        return lambda *args: (template % args, None, None)

    for memory_items, checkboxes, template in (
            (lemmas, lemma_checkboxes, lemma_template),
            (grammars, grammar_checkboxes, format_template('the form %s')),
            (graphemes, grapheme_checkboxes, writing_template),
            (forward_pronunciations, forward_pronunciation_checkboxes, format_template('%s pronounced as %s')),
            (backward_pronunciations, backward_pronunciation_checkboxes, format_template('%s written as %s')),
            (sounds, sound_checkboxes, format_template('pronouncing %s'))):
        if not memory_items:
            continue
        vlayout = qw.QVBoxLayout()
        for item in memory_items:
            boxlabel, movie, tooltip = template(*item[1:])
            checkbox = qw.QCheckBox(boxlabel)
            checkbox.setCheckState(qc.Qt.CheckState.Checked)
            if tooltip:
                checkbox.setToolTip(tooltip)
            checkboxes.append(checkbox)
            if movie:
                boxlayout = qw.QHBoxLayout()
                label = MovieLabel(
                    movie,
                    size=qc.QSize(font.pointSize()*2, font.pointSize()*2),
                    hover_size=qc.QSize(-1, -1))
                boxlayout.addWidget(checkbox)
                boxlayout.addWidget(label)
                vlayout.addLayout(boxlayout)
            else:
                vlayout.addWidget(checkbox)
        scrollframe = VerticalScrollFrame()
        scrollframe.setLayout(vlayout)
        hlayout.addWidget(scrollframe.scrollarea)

    def learn():
        dialog.media_player.stop()
        dialog.accept()
        callback(**{
            table+'_selection': [
                (item[0], checkbox.isChecked())
                for item, checkbox in zip(memory_items, checkboxes)]
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


def show_writing_to_pronunciation_dialog(
        text,
        callback):
    dialog = qw.QDialog()
    possible_fonts = qg.QFontDatabase().families(qg.QFontDatabase.Japanese)
    japanese_fonts = [font for font in possible_fonts if 'jp' in font.lower()]
    font = qg.QFont(japanese_fonts[0])
    dialog.setFont(font)
    big_font = qg.QFont(font)
    big_font.setPointSize(font.pointSize()*1.5)
    dialog.text = qw.QLabel(text.replace('\t', ''))
    dialog.text.setFont(big_font)
    dialog.text.setTextInteractionFlags(qc.Qt.TextSelectableByMouse)
    dialog.pronunciation_button = qw.QPushButton('Check pronunciation')
    dialog.pronunciation_button.setDefault(True)

    def check():
        dialog.accept()
        callback()

    dialog.pronunciation_button.clicked.connect(check)

    vlayout = qw.QVBoxLayout()
    vlayout.addWidget(dialog.text)
    vlayout.addWidget(dialog.pronunciation_button)
    dialog.setLayout(vlayout)

    dialog.show()

    return dialog


def show_pronunciation_to_writing_dialog(
        pronunciation,
        audio_file,
        callback):
    dialog = qw.QDialog()
    possible_fonts = qg.QFontDatabase().families(qg.QFontDatabase.Japanese)
    japanese_fonts = [font for font in possible_fonts if 'jp' in font.lower()]
    font = qg.QFont(japanese_fonts[0])
    dialog.setFont(font)
    big_font = qg.QFont(font)
    big_font.setPointSize(font.pointSize()*1.5)
    dialog.pronunciation = qw.QLabel(pronunciation.replace('\t', ''))
    dialog.pronunciation.setFont(big_font)
    dialog.pronunciation.setTextInteractionFlags(qc.Qt.TextSelectableByMouse)
    dialog.writing_button = qw.QPushButton('Check writing')
    dialog.writing_button.setDefault(True)

    def check():
        dialog.media_player.stop()
        dialog.accept()
        callback()

    dialog.writing_button.clicked.connect(check)

    vlayout = qw.QVBoxLayout()
    vlayout.addWidget(dialog.pronunciation)
    vlayout.addWidget(dialog.writing_button)
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
    c.execute('ATTACH DATABASE ? AS dictionary', (args.dictionary_database,))
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
            lemma_selection, grammar_selection, grapheme_selection,
            forward_pronunciation_selection, backward_pronunciation_selection,
            sound_selection):
        for table, kinds, selection in (
                ('lemma', ('',), lemma_selection),
                ('grammar', ('',), grammar_selection),
                ('grapheme', ('',), grapheme_selection),
                ('pronunciation', ('forward_',), forward_pronunciation_selection),
                ('pronunciation', ('backward_',), backward_pronunciation_selection),
                ('sound', ('',), sound_selection)):
            refresh(c, table, kinds, [
                (id,) for id, selected in selection if selected])
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
    c.execute('ATTACH DATABASE ? AS dictionary', (args.dictionary_database,))
    app = qw.QApplication()

    scheduled_reviews = list(c.execute(
        f'''
        SELECT id, text, source_url, source_id, license_url, creator, pronunciation,
            inverse_memory_strength_weighted_last_refresh
            - julianday('now')*summed_inverse_memory_strength AS log_retention,
            review.type
        FROM sentence, review
        WHERE sentence.id = sentence_id
        AND log_retention < ?
        ORDER BY log_retention ASC
        ''',
        (math.log(args.desired_retention),)))

    def generate_reviews():
        for (id, text, source_url, source_id, license_url, creator, pronunciation,
             log_retention, review_type) in scheduled_reviews:
            print(log_retention, math.exp(log_retention))
            (log_retention,), = list(c.execute(
                f'''
                SELECT
                    inverse_memory_strength_weighted_last_refresh
                    - julianday('now')*summed_inverse_memory_strength AS log_retention
                FROM review
                WHERE sentence_id = ?
                AND review.type = ?
                LIMIT 1
                ''',
                (id, review_type)))
            print(log_retention, math.exp(log_retention))
            if log_retention > math.log(args.desired_retention):
                continue
            lemmas, grammars, graphemes, forward_pronunciations, backward_pronunciations, sounds = get_sentence_details(c, id, only_new=False)
            for table_kind in ('lemmas', 'grammars', 'graphemes', 'forward_pronunciations', 'backward_pronunciations', 'sounds'):
                if not any(table_kind == kind+table+'s'
                           for table, kind
                           in ReviewType(review_type).tables_kinds):
                    locals()[table_kind].clear()
            tatoeba_conn = sqlite3.connect(args.tatoeba_database)
            tc = tatoeba_conn.cursor()
            translation = get_translation(tc, source_id, args.translation_language)
            audio_file = get_audio(tc, text.replace('\t', ''), source_id)

            def review_callback(
                    lemma_selection, grammar_selection, grapheme_selection,
                    forward_pronunciation_selection, backward_pronunciation_selection,
                    sound_selection):
                for table, kinds, selection in (
                        ('lemma', ('',), lemma_selection),
                        ('grammar', ('',), grammar_selection),
                        ('grapheme', ('',), grapheme_selection),
                        ('pronunciation', ('forward_',), forward_pronunciation_selection),
                        ('pronunciation', ('backward_',), backward_pronunciation_selection),
                        ('sound', ('',), sound_selection)):
                    refresh(c, table, kinds, [
                        (id,) for id, selected in selection if selected])
                    relearn(c, table, kinds, [
                        (id,) for id, selected in selection if not selected])
                conn.commit()

                try:
                    next(review_generator)
                except StopIteration:
                    pass

            def check_callback():
                dialog = show_sentence_detail_dialog(
                    text, pronunciation, translation,
                    source_url, creator, license_url,
                    lemmas, grammars, graphemes,
                    forward_pronunciations, backward_pronunciations, sounds,
                    audio_file, review_callback)

            if review_type == ReviewType.WRITING_TO_PRONUNCIATION.value:
                dialog = show_writing_to_pronunciation_dialog(
                    text,
                    check_callback)
            elif review_type == ReviewType.PRONUNCIATION_TO_WRITING.value:
                dialog = show_pronunciation_to_writing_dialog(
                    pronunciation,
                    audio_file,
                    check_callback)
            yield

        (next_review,), = c.execute(
            f'''
            SELECT min(
                    (inverse_memory_strength_weighted_last_refresh - ?)/
                    summed_inverse_memory_strength)
                - julianday('now')
            FROM review
            LIMIT 1
            ''',
            (math.log(args.desired_retention),))

        dialog = qw.QMessageBox()
        dialog.setText(f'Next review in {next_review} days')
        dialog.show()

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
    parser.add_argument('--dictionary-database', type=str, default='data/japanese_dictionary.sqlite')
    parser.add_argument('--translation-language', type=str, default='eng')
    parser.add_argument('--desired-retention', type=float, default=DEFAULT_RETENTION)
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    import sys
    main(sys.argv)
