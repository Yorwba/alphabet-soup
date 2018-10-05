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
            PRIMARY KEY (ent_seq, variant))
        ''')
    c.execute(
        '''
        CREATE INDEX entry_lemma_pos_index ON entry (lemma, pos)
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
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS disambiguator_to_pos (
            disambiguator text,
            pos text)
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

            # (readings, miscellaneous) by [(kanji, pos)][lang][gloss]
            rm_by_kplg = \
                defaultdict(
                    lambda: defaultdict(
                        lambda: defaultdict(
                            lambda: (set(), set()))))
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
                        if (kanji != reading and
                                'word usually written using kana alone' in miscellanea):
                            lemma_options = [kanji, reading]
                        else:
                            lemma_options = [kanji]
                        for lemma in lemma_options:
                            for pos in parts_of_speech:
                                rm_by_lg = rm_by_kplg[(lemma, pos)]
                                for lang, gloss in glosses.items():
                                    rm_by_g = rm_by_lg[lang]
                                    for glos in gloss:
                                        readings, misc = rm_by_g[glos]
                                        readings.add(reading)
                                        misc.update(miscellanea)

                # gloss by [(kanji, pos)][lang][{reading}][{misc}]
                g_by_kplrm = \
                    defaultdict(
                        lambda: defaultdict(
                            lambda: defaultdict(
                                lambda: defaultdict(
                                    list))))
                for kp, rm_by_lg in rm_by_kplg.items():
                    g_by_lrm = g_by_kplrm[kp]
                    for lang, rm_by_g in rm_by_lg.items():
                        g_by_rm = g_by_lrm[lang]
                        for gloss, (readings, misc) in rm_by_g.items():
                            readings = frozenset(readings)
                            misc = frozenset(misc)
                            g_by_rm[readings][misc].append(gloss)

                # gloss by [(kanji, pos)][lang]
                g_by_kpl = {
                    kp: {
                        lang:
                        '\n\n'.join(
                            '\n'.join(
                                [', '.join(
                                    f'[{reading}]'
                                    for reading in readings)
                                 +':']
                                + ['\n'.join(
                                    [f'\n({", ".join(misc)})' if misc else '']
                                    + gloss)
                                   for misc, gloss in g_by_m.items()])
                            for reading, g_by_m in g_by_rm.items())
                        for lang, g_by_rm in g_by_lrm.items()}
                    for kp, g_by_lrm in g_by_kplrm.items()}

            for variant_number, ((kanji, pos), glosses) in enumerate(g_by_kpl.items()):
                for lang, gloss in glosses.items():
                    yield ent_seq, variant_number, kanji, pos, lang, gloss


def associate_disambiguator_and_pos(args):
    c = conn.cursor()
    c.execute(f'ATTACH DATABASE ? as sentences', (args.sentence_database,))
    while True:
        disambiguator_pos_mappings = [
            (set(disambiguators.split('\t')), set(pos.split('\t')), frequency)
            for disambiguators, pos, frequency
            in c.execute(
            '''
            WITH
                unmatched_disambiguators AS (
                    SELECT
                        sentences.lemma.text as lemma,
                        group_concat(disambiguator, "\t") as disambiguators
                    FROM sentences.lemma
                    WHERE disambiguator NOT IN (
                        SELECT disambiguator
                        FROM disambiguator_to_pos NATURAL JOIN entry
                        WHERE entry.lemma = sentences.lemma.text)
                    GROUP BY sentences.lemma.text),
                possible_pos AS (
                    SELECT
                        lemma,
                        group_concat(pos, "\t") as pos
                    FROM entry
                    GROUP BY lemma)
            SELECT disambiguators, pos, count(*) as frequency
            FROM unmatched_disambiguators NATURAL JOIN possible_pos
            GROUP BY disambiguators, pos
            ORDER BY frequency
            ''')]
        easy_cases = [
            (disambiguator, next(iter(pos)))
            for disambiguators, pos, frequency
            in disambiguator_pos_mappings
            if len(pos) == 1
            for disambiguator in disambiguators]
        c.executemany(
            '''
            INSERT INTO disambiguator_to_pos (disambiguator, pos)
            VALUES (?, ?)
            ''',
            easy_cases)
        if not easy_cases:
            intersections = {}
            for disambiguators, pos, frequency in disambiguator_pos_mappings:
                for disambiguator in disambiguators:
                    if disambiguator in intersections:
                        intersections[disambiguator] =\
                            intersections[disambiguator] & pos
                    else:
                        intersections[disambiguator] = pos
            intersected_cases = [
                (disambiguator, po)
                for disambiguator, pos in intersections.items()
                for po in pos]
            c.executemany(
                '''
                INSERT INTO disambiguator_to_pos (disambiguator, pos)
                VALUES (?, ?)
                ''',
                intersected_cases)
            if not intersected_cases:
                # TODO: maybe solve set cover instead?
                remaining_cases = [
                    (disambiguator, po)
                    for disambiguators, pos, frequency
                    in disambiguator_pos_mappings
                    for disambiguator in disambiguators
                    for po in pos]
                c.executemany(
                    '''
                    INSERT INTO disambiguator_to_pos (disambiguator, pos)
                    VALUES (?, ?)
                    ''',
                    remaining_cases)
                if not remaining_cases:
                    break


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

    associate_disambiguator_and_pos(args)

    conn.commit()


def main(argv):
    parser = argparse.ArgumentParser(
        description='JMdict XML to SQLite converter')
    parser.add_argument('command', nargs=1, choices={'convert'})
    parser.add_argument('--jmdict', type=str, default='data/jmdict/JMdict.gz')
    parser.add_argument('--database', type=str, default='data/japanese_dictionary.sqlite')
    parser.add_argument('--sentence-database', type=str, default='data/japanese_sentences.sqlite')
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    import sys
    main(sys.argv)
