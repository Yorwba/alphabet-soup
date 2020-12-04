#!/usr/bin/env python3

#   Alphabet Soup gives language learners easily digestible chunks for practice.
#   Copyright 2019-2020 Yorwba

#   Alphabet Soup is free software: you can redistribute it and/or
#   modify it under the terms of the GNU Affero General Public License
#   as published by the Free Software Foundation, either version 3 of
#   the License, or (at your option) any later version.

#   Alphabet Soup is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU Affero General Public License for more details.

#   You should have received a copy of the GNU Affero General Public License
#   along with Alphabet Soup.  If not, see <https://www.gnu.org/licenses/>.

import argparse
import datetime
import os
import math
import sqlite3
import subprocess
import sys
import time
import urllib.parse

import PySide2.QtCore as qc
import PySide2.QtGui as qg
import PySide2.QtMultimedia as qm
import PySide2.QtWidgets as qw

from japanese_data import ReviewType

#: Let's say forgetting 1 in 20 words is okay.
DEFAULT_RETENTION = 0.95

#: Strength which makes retention drop below DEFAULT RETENTION within a day.
MEMORY_STRENGTH_PER_DAY = -1/math.log(DEFAULT_RETENTION)

#: Time (in days) it takes to forget after seeing something once or relearning.
BASELINE_MEMORY_STRENGTH = 20

#: Time (in days) after which "the test" for determining utility is taken.
TEST_DELAY = 20

#: Wait this long (in days) before showing what needs to be relearned.
RELEARN_GRACE_PERIOD = 5/(24*60)  # 5 minutes

#: A SQLite expression to generate a (mostly) uniform random number in (0, 1)
UNIFORM_RANDOM = '(((CAST(RANDOM() AS real)/0x' + 'f'*15 + ')+8)/0x10)'


def refresh(cursor, table, kinds, ids):
    cursor.executemany(
        f'''
        UPDATE {table} SET
        {','.join(
            f"""
            last_{kind}refresh = julianday("now"),
            last_{kind}relearn = IFNULL(last_{kind}relearn, julianday("now"))
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
            last_{kind}refresh = julianday("now"),
            last_{kind}relearn = julianday("now")
            """ for kind in kinds)}
        WHERE id = ?
        ''',
        ids)


def get_audio(cursor, sentence, source_id):
    filename = sentence
    while len(filename.encode('utf-8')) > 100:
        filename = filename[:-2]+'…'
    for ext in ('wav', 'mp3'):
        path = f'data/audio/{filename}.{ext}'
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
        file_path = f'data/audio/{filename}.mp3'
        import urllib.request
        urllib.request.urlretrieve(url, file_path)
        print(f'Downloaded audio by {creator} ({attribution}), '
              f'licensed under {license}, from {url}')
        return file_path
    except StopIteration:  # no audio on Tatoeba
        pass

    file_path = f'data/audio/{filename}.wav'
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


def get_sentence_details(cursor, id, only_new=True, translation_languages=['eng']):
    lemmas = list(cursor.execute(
        f'''
        SELECT lemma.id, lemma.text, lemma.disambiguator
        FROM lemma, sentence_lemma
        WHERE sentence_id = {id}
        AND lemma_id = lemma.id
        {'AND last_relearn IS NULL' if only_new else ''}
        '''))
    lemmas = [
        (id,
         text,
         disambiguator,
         get_dictionary_gloss(cursor, text, disambiguator, translation_languages))
        for (id, text, disambiguator)
        in lemmas]
    grammars = list(cursor.execute(
        f'''
        SELECT grammar.id, grammar.form
        FROM grammar, sentence_grammar
        WHERE sentence_id = {id}
        AND grammar_id = grammar.id
        {'AND last_relearn IS NULL' if only_new else ''}
        '''))
    graphemes = list(cursor.execute(
        f'''
        SELECT grapheme.id, grapheme.text
        FROM grapheme, sentence_grapheme
        WHERE sentence_id = {id}
        AND grapheme_id = grapheme.id
        {'AND last_relearn IS NULL' if only_new else ''}
        '''))
    forward_pronunciations = list(cursor.execute(
        f'''
        SELECT pronunciation.id, pronunciation.word, pronunciation.pronunciation
        FROM pronunciation, sentence_pronunciation
        WHERE sentence_id = {id}
        AND pronunciation_id = pronunciation.id
        {'AND last_forward_relearn IS NULL' if only_new else ''}
        '''))
    backward_pronunciations = list(cursor.execute(
        f'''
        SELECT pronunciation.id, pronunciation.word, pronunciation.pronunciation
        FROM pronunciation, sentence_pronunciation
        WHERE sentence_id = {id}
        AND pronunciation_id = pronunciation.id
        {'AND last_backward_relearn IS NULL' if only_new else ''}
        '''))
    sounds = list(cursor.execute(
        f'''
        SELECT sound.id, sound.text
        FROM sound, sentence_sound
        WHERE sentence_id = {id}
        AND sound_id = sound.id
        {'AND last_relearn IS NULL' if only_new else ''}
        '''))

    # Record this sentence as seen
    cursor.execute(
        f'''
        UPDATE sentence
        SET last_seen = julianday('now')
        WHERE id = ?
        ''',
        (id,))
    return lemmas, grammars, graphemes, forward_pronunciations, backward_pronunciations, sounds


def get_translation(tatoeba_cursor, source_id, translation_languages):
    for lang in translation_languages:
        try:
            (translation,) = next(tatoeba_cursor.execute(
                f'''
                SELECT sentences_detailed.text
                FROM sentences_detailed, links
                WHERE sentences_detailed.lang = ?
                AND sentences_detailed.id = links.translation_id
                AND links.sentence_id = ?
                ''',
                (lang, source_id)))
            return translation
        except StopIteration:
            pass
    return ''


def get_dictionary_gloss(cursor, lemma, disambiguator, translation_languages):
    lemma = lemma.split('-')[0]
    glosses = set(
        gloss
        for lang in translation_languages
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
            (lemma, disambiguator, lang)))
    return '\n\n'.join(glosses)


def get_scheduled_reviews(cursor, desired_retention):
    cursor.connection.create_function('exp', 1, math.exp, deterministic=True)
    while True:
        try:
            query_by_review_type = {
                review_type:
                    ' UNION '.join(
                        f'''
                                    SELECT
                                        '{table}' AS t,
                                        '{kind}' AS k,
                                        {table}.id,
                                        frequency * (
                                            1 - frequency/total_sentences
                                        ) * (
                                            exp(
                                                -(julianday('now') - {table}.last_{kind}refresh)
                                                    /({BASELINE_MEMORY_STRENGTH} + {table}.last_{kind}refresh - {table}.last_{kind}relearn)
                                            )*(
                                                (
                                                    exp(-{TEST_DELAY}/({BASELINE_MEMORY_STRENGTH} +  julianday('now') - {table}.last_{kind}relearn))
                                                    - exp(-{TEST_DELAY}/({BASELINE_MEMORY_STRENGTH} + {table}.last_{kind}refresh - {table}.last_{kind}relearn))
                                                )/exp(-{TEST_DELAY}/{BASELINE_MEMORY_STRENGTH})
                                                - 1
                                            )
                                            + 1
                                        )
                                        AS utility
                                    FROM {table}, totals
                                    WHERE {table}.last_{kind}refresh IS NOT NULL
                                    AND (julianday('now') - {table}.last_{kind}refresh)
                                        >= {RELEARN_GRACE_PERIOD}
                        '''
                        for table, kind in review_type.tables_kinds
                    )
                for review_type in ReviewType
            }
            combined_query = ' UNION '.join(
                f'''
                    SELECT
                        t,
                        k,
                        id,
                        utility
                    FROM ({query_by_review_type[review_type]})
                '''
                for review_type in ReviewType
            )
            prev_time = time.time()
            scheduled_table, scheduled_kind, scheduled_id, scheduled_utility = next(cursor.execute(
                f'''
                    SELECT
                        t,
                        k,
                        id,
                        utility
                    FROM ({combined_query})
                    ORDER BY utility DESC
                    LIMIT 1
                '''
            ))
            print(f"Took {time.time()-prev_time} seconds to find detail.")
            print(f"Utility: {scheduled_utility}")
            scheduled_review_types = ','.join((
                f'({review_type.value})'
                for review_type in ReviewType
                if (scheduled_table, scheduled_kind) in review_type.tables_kinds
            ))
            scheduled = next(cursor.execute(
                f'''
                SELECT id, segmented_text, source_url, source_id, license_url, creator, pronunciation,
                    review_type.column1
                FROM
                    sentence,
                    sentence_{scheduled_table} AS st,
                    (VALUES {scheduled_review_types}) AS review_type
                WHERE sentence.id = st.sentence_id
                AND st.{scheduled_table}_id = :scheduled_id
                AND sentence.minimum_unknown_frequency IS NULL
                ORDER BY
                    ifnull(
                        1. + 1./(julianday('now') - last_seen),
                        0.
                    ) + 1./7.*{UNIFORM_RANDOM}
                    ASC
                LIMIT 1
                ''',
                dict(scheduled_id=scheduled_id)))
            next_time = time.time()
            print(f"Took {next_time-prev_time} seconds to schedule.")
            yield scheduled
        except StopIteration:
            break

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

    def __del__(self):
        self.movie().deleteLater()


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


def EphemeralDialog():
    """Creates a dialog that deletes itself when closed."""
    dialog = qw.QDialog()
    dialog.setAttribute(qc.Qt.WA_DeleteOnClose)
    return dialog


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

    def position_in(text):
        def position_in_text(detail):
            if isinstance(text, tuple):
                return tuple(
                    position_in(t)(d)
                    for t, d in zip(text, detail[1:]))
            try:
                return text.index(detail)
            except ValueError:
                return len(text)
        return position_in_text

    lemmas = sorted(lemmas, key=position_in((text,)))
    graphemes = sorted(graphemes, key=position_in((text,)))
    forward_pronunciations = sorted(
        forward_pronunciations,
        key=position_in((text, pronunciation)))
    backward_pronunciations = sorted(
        backward_pronunciations,
        key=position_in((text, pronunciation)))
    sounds = sorted(sounds, key=position_in((pronunciation,)))
    dialog = EphemeralDialog()
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
        f'Example from <a href="{source_url}">{urllib.parse.unquote(source_url)}</a> '
        f'by {creator}, '
        f'licensed under <a href="{license_url}">{urllib.parse.unquote(license_url)}</a>')
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
        return lambda *args: (template.format(*args), None, None)

    for memory_items, checkboxes, template in (
            (lemmas, lemma_checkboxes, lemma_template),
            (grammars, grammar_checkboxes, format_template('the form {}')),
            (graphemes, grapheme_checkboxes, writing_template),
            (forward_pronunciations, forward_pronunciation_checkboxes, format_template('{} pronounced as {}')),
            (backward_pronunciations, backward_pronunciation_checkboxes, format_template('{1} written as {0}')),
            (sounds, sound_checkboxes, format_template('pronouncing {}'))):
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
    dialog = EphemeralDialog()
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
    dialog = EphemeralDialog()
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
    if os.path.isfile(args.dictionary_database):
        c.execute('ATTACH DATABASE ? AS dictionary', (args.dictionary_database,))
    else:
        print(
            f'Could not find the dictionary at {args.dictionary_database}',
            file=sys.stderr)
        sys.exit(1)
    (id_for_minimum_unknown_frequency, frequency, count) = next(c.execute(
        f'''
        SELECT
            id_for_minimum_unknown_frequency,
            minimum_unknown_frequency as f,
            count(*) as c
        FROM sentence
        GROUP BY id_for_minimum_unknown_frequency
        ORDER BY f*c DESC
        LIMIT 1
    '''))
    (id, text, source_url, source_id, license_url, creator, pronunciation) = next(c.execute(
        f'''
        SELECT id, segmented_text, source_url, source_id, license_url, creator, pronunciation
        FROM sentence
        WHERE id_for_minimum_unknown_frequency = ?
        ORDER BY (source_database = 'tatoeba') DESC
        LIMIT 1
        ''',
        (id_for_minimum_unknown_frequency,)))
    lemmas, grammars, graphemes, forward_pronunciations, backward_pronunciations, sounds = get_sentence_details(c, id)
    tatoeba_conn = sqlite3.connect(args.tatoeba_database)
    tc = tatoeba_conn.cursor()
    translation = get_translation(tc, source_id, args.translation_languages)
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
    if os.path.isfile(args.dictionary_database):
        c.execute('ATTACH DATABASE ? AS dictionary', (args.dictionary_database,))
    else:
        print(
            f'Could not find the dictionary at {args.dictionary_database}',
            file=sys.stderr)
        sys.exit(1)
    app = qw.QApplication()

    def generate_reviews():
        num_reviews = 0
        for (id, text, source_url, source_id, license_url, creator, pronunciation,
             review_type) in get_scheduled_reviews(c, args.desired_retention):
            if time.time() - review_start_time > args.review_time_seconds:
                break
            num_reviews += 1
            lemmas, grammars, graphemes, forward_pronunciations, backward_pronunciations, sounds = get_sentence_details(c, id, only_new=False)
            for table_kind in ('lemmas', 'grammars', 'graphemes', 'forward_pronunciations', 'backward_pronunciations', 'sounds'):
                if not any(table_kind == kind+table+'s'
                           for table, kind
                           in ReviewType(review_type).tables_kinds):
                    locals()[table_kind].clear()
            tatoeba_conn = sqlite3.connect(args.tatoeba_database)
            tc = tatoeba_conn.cursor()
            translation = get_translation(tc, source_id, args.translation_languages)
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

        dialog = qw.QMessageBox()

        def refresh_dialog():
            (next_review,), = c.execute(
                f'''
                SELECT min(next_review) - julianday('now')
                FROM ({' UNION '.join(
                    f"""
                        SELECT
                            min(last_{kind}refresh - ({RELEARN_GRACE_PERIOD} + last_{kind}refresh - last_{kind}relearn) * :log_retention)
                            AS next_review
                        FROM {table}
                    """
                    for review_type in ReviewType
                    for table, kind in review_type.tables_kinds
                    )})
                ''',
                dict(log_retention=MEMORY_STRENGTH_PER_DAY * math.log(args.desired_retention)*4))

            next_review = str(datetime.timedelta(next_review)).split('.')[0]

            (possible_sentences,), = c.execute(
                f'''
                SELECT count(*)
                FROM sentence
                WHERE id in (SELECT sentence_id FROM review)
                ''')

            learned_tables = dict()
            for review_type in ReviewType:
                for table, kind in review_type.tables_kinds:
                    (learned_count,), = c.execute(
                        f'''
                        SELECT count(*)
                        FROM {table}
                        WHERE last_{kind}relearn IS NOT NULL
                        ''')
                    if table in learned_tables:
                        learned_tables[table] = max(
                            learned_tables[table],
                            learned_count)
                    else:
                        learned_tables[table] = learned_count

            dialog.setText(
                f'You reviewed {num_reviews} sentences.\n'
                f'''You know {", ".join(
                    f"{count} {table}s"
                    for table, count in sorted(learned_tables.items()))}.'''
                f'\nThey cover {possible_sentences} different sentences.\n'
                f'Next review in {next_review}.')

        refresh_dialog()
        timer = qc.QTimer()
        timer.setInterval(1000)
        timer.timeout.connect(refresh_dialog)
        timer.start()
        dialog.show()

        yield

    review_start_time = time.time()
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
    parser.add_argument('--translation-languages', type=str, nargs='+', default=['eng'])
    parser.add_argument('--desired-retention', type=float, default=DEFAULT_RETENTION)
    parser.add_argument('--review-time-seconds', type=float, default=600.)
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    main(sys.argv)
