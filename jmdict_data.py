#!/usr/bin/env python3

import argparse
from collections import defaultdict
import lxml.etree as etree
import gzip
import sqlite3


def create_tables():
    c = conn.cursor()
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS entry (
            ent_seq integer,
            variant integer,
            lemma text,
            pos text,
            PRIMARY KEY (lemma, pos),
            UNIQUE (ent_seq, variant))
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS gloss (
            ent_seq integer,
            variant integer,
            lang text,
            gloss text,
            PRIMARY KEY (ent_seq, variant, lang))
        ''')


def read_dictionary(args):
    with gzip.open(args.jmdict) as f:
        for event, node in etree.iterparse(f, tag='entry'):
            children = node.getchildren()
            ent_seq, = (child.text for child in children if child.tag == 'ent_seq')
            kanji_elements = [child for child in children if child.tag == 'k_ele']
            reading_elements = [child for child in children if child.tag == 'r_ele']
            senses = [child for child in children if child.tag == 'sense']

            kanjis = [child.text
                     for k_ele in kanji_elements
                     for child in k_ele.iterchildren()
                     if child.tag == 'keb']
            if not kanjis:
                kanjis = [None]

            kanji_readings = []
            for r_ele in reading_elements:
                restrictions = set()
                for child in r_ele.iterchildren():
                    if child.tag == 're_restr':
                        restrictions.add(child.text)
                    elif child.tag == 'reb':
                        reading = child.text
                for kanji in kanjis:
                    if not kanji:
                        kanji = reading
                    if not restrictions or kanji in restrictions:
                        kanji_readings.append((kanji, reading))

            kanji_pos_glosses = defaultdict(lambda: defaultdict(list))
            parts_of_speech = frozenset()
            miscellanea = frozenset()
            for sense in senses:
                kanji_restrictions = set()
                reading_restrictions = set()
                current_parts_of_speech = set()
                current_miscellanea = set()
                glosses = defaultdict(list)
                for child in sense.iterchildren():
                    if child.tag == 'stagk':
                        kanji_restrictions.add(child.text)
                    elif child.tag == 'stagr':
                        reading_restrictions.add(child.text)
                    elif child.tag == 'pos':
                        current_parts_of_speech.add(child.text)
                    elif child.tag == 'misc':
                        current_miscellanea.add(child.text)
                    elif child.tag == 'gloss':
                        language = child.get('{http://www.w3.org/XML/1998/namespace}lang')
                        if not language:
                            language = 'eng'
                        if child.text:  # XXX who adds a gloss without text???
                            glosses[language].append(child.text)
                if current_parts_of_speech:
                    parts_of_speech = frozenset(current_parts_of_speech)
                if current_miscellanea:
                    miscellanea = frozenset(current_miscellanea)
                for kanji, reading in kanji_readings:
                    if ((not kanji_restrictions
                         or kanji in kanji_restrictions)
                        and
                        (not reading_restrictions
                         or reading in reading_restrictions)):
                        for pos in parts_of_speech:
                            for lang, gloss in glosses.items():
                                kanji_pos_gloss = kanji_pos_glosses[(kanji, pos)][lang]
                                kanji_pos_gloss.append(f'[{reading}]:')
                                if miscellanea:
                                    kanji_pos_gloss.append(f'({", ".join(miscellanea)})')
                                kanji_pos_gloss.extend(gloss)

            for variant_number, ((kanji, pos), glosses) in enumerate(kanji_pos_glosses.items()):
                for lang, gloss in glosses.items():
                    yield ent_seq, variant_number, kanji, pos, lang, '\n'.join(gloss)


def convert(args):
    global conn
    conn = sqlite3.connect(args.database)
    create_tables()
    c = conn.cursor()
    for (ent_seq, variant, kanji, pos, lang, gloss) in read_dictionary(args):
        c.execute(
            '''
            INSERT OR IGNORE INTO entry (ent_seq, variant, lemma, pos)
            VALUES (?, ?, ?, ?)
            ''',
            (ent_seq, variant, kanji, pos))
        c.execute(
            '''
            INSERT OR IGNORE INTO gloss (ent_seq, variant, lang, gloss)
            VALUES (?, ?, ?, ?)
            ''',
            (ent_seq, variant, lang, gloss))

    conn.commit()


def main(argv):
    parser = argparse.ArgumentParser(
        description='JMdict XML to SQLite converter')
    parser.add_argument('command', nargs=1, choices={'convert'})
    parser.add_argument('--jmdict', type=str, default='data/jmdict/JMdict.gz')
    parser.add_argument('--database', type=str, default='data/japanese_dictionary.sqlite')
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    import sys
    main(sys.argv)
