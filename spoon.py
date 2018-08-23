#!/usr/bin/env python3

import argparse
import os
import sqlite3
import subprocess


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
        import urllib
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
         '-ow', file_path],
        input=sentence.encode('utf-8'),
        check=True)
    print('Generated audio using Open JTalk (http://open-jtalk.sourceforge.net)')
    return file_path


def recommend_sentence(args):
    conn = sqlite3.connect(args.database)
    c = conn.cursor()
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
    base_words = list(c.execute(
        f'''
        SELECT base_word.id, base_word.text
        FROM base_word, sentence_base_word
        WHERE sentence_id = {id}
        AND base_word_id = base_word.id
        '''))
    grammars = list(c.execute(
        f'''
        SELECT grammar.id, grammar.form
        FROM grammar, sentence_grammar
        WHERE sentence_id = {id}
        AND grammar_id = grammar.id
        '''))
    writing_components = list(c.execute(
        f'''
        SELECT writing_component.id, writing_component.text
        FROM writing_component, sentence_writing_component
        WHERE sentence_id = {id}
        AND writing_component_id = writing_component.id
        '''))
    pronunciations = list(c.execute(
        f'''
        SELECT pronunciation.id, pronunciation.word, pronunciation.pronunciation
        FROM pronunciation, sentence_pronunciation
        WHERE sentence_id = {id}
        AND pronunciation_id = pronunciation.id
        '''))
    pronunciation_components = list(c.execute(
        f'''
        SELECT pronunciation_component.id, pronunciation_component.text
        FROM pronunciation_component, sentence_pronunciation_component
        WHERE sentence_id = {id}
        AND pronunciation_component_id = pronunciation_component.id
        '''))
    tatoeba_conn = sqlite3.connect(args.tatoeba_database)
    tc = tatoeba_conn.cursor()
    (translation,) = next(tc.execute(
        f'''
        SELECT sentences_detailed.text
        FROM sentences_detailed, links
        WHERE sentences_detailed.lang = ?
        AND sentences_detailed.id = links.translation_id
        AND links.sentence_id = ?
        ''',
        (args.translation_language, source_id)))
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
    dialog.text = qw.QLabel(text)
    dialog.text.setFont(big_font)
    dialog.pronunciation = qw.QLabel(pronunciation)
    dialog.pronunciation.setFont(big_font)
    dialog.translation = qw.QLabel(translation)
    dialog.translation.setFont(big_font)
    dialog.attribution =  qw.QLabel(
        f'Example from <a href="{source_url}">{source_url}</a> '
        f'by {creator}, '
        f'licensed under <a href="{license_url}">{license_url}</a>')
    dialog.attribution.setOpenExternalLinks(True)
    dialog.learn_button = qw.QPushButton('Learn')
    dialog.learn_button.setDefault(True)

    hlayout = qw.QHBoxLayout()
    base_word_checkboxes = []
    grammar_checkboxes = []
    writing_component_checkboxes = []
    pronunciation_checkboxes = []
    pronunciation_component_checkboxes = []
    for memory_items, checkboxes, template in (
            (base_words, base_word_checkboxes, 'the meaning of %s'),
            (grammars, grammar_checkboxes, 'the form %s'),
            (writing_components, writing_component_checkboxes, 'writing %s'),
            (pronunciations, pronunciation_checkboxes, '%s pronounced as %s'),
            (pronunciation_components, pronunciation_component_checkboxes, 'pronouncing %s')):
        vlayout = qw.QVBoxLayout()
        for item in memory_items:
            checkbox = qw.QCheckBox(template % item[1:])
            checkbox.setCheckState(qc.Qt.CheckState.Checked)
            checkboxes.append(checkbox)
            vlayout.addWidget(checkbox)
        hlayout.addLayout(vlayout)

    def learn():
        for memory_items, checkboxes in (
                (base_words, base_word_checkboxes),
                (grammars, grammar_checkboxes),
                (writing_components, writing_component_checkboxes),
                (pronunciations, pronunciation_checkboxes),
                (pronunciation_components, pronunciation_component_checkboxes)):
            for item, checkbox in zip(memory_items, checkboxes):
                if checkbox.isChecked():
                    print(f'Going to learn {item}')
        dialog.accept()

    dialog.learn_button.clicked.connect(learn)

    vlayout = qw.QVBoxLayout()
    vlayout.addWidget(dialog.text)
    vlayout.addWidget(dialog.pronunciation)
    vlayout.addWidget(dialog.translation)
    vlayout.addLayout(hlayout)
    vlayout.addWidget(dialog.attribution)
    vlayout.addWidget(dialog.learn_button)
    dialog.setLayout(vlayout)
    dialog.show()
    qm.QSound.play(audio_file)
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
