#!/usr/bin/env python3

import argparse
from enum import Enum
import sqlite3
import subprocess


class ReviewType(Enum):
    WRITING_TO_PRONUNCIATION = 0
    PRONUNCIATION_TO_WRITING = 1
ReviewType.WRITING_TO_PRONUNCIATION.tables_kinds = set((
    ('lemma', ''),
    ('grammar', ''),
    ('pronunciation', 'forward_'),
    ('sound', '')))
ReviewType.PRONUNCIATION_TO_WRITING.tables_kinds = set((
    ('lemma', ''),
    ('grammar', ''),
    ('grapheme', ''),
    ('pronunciation', 'backward_'),
    ('sound', '')))


def create_link_table(cursor, table1, table2):
    cursor.execute(
        f'''
        CREATE TABLE IF NOT EXISTS {table1}_{table2} (
            {table1}_id integer REFERENCES {table1}(id),
            {table2}_id integer REFERENCES {table2}(id),
            UNIQUE ({table1}_id, {table2}_id))
        ''')
    cursor.execute(
        f'''
        CREATE INDEX IF NOT EXISTS {table1}_{table2}_idx
        ON {table1}_{table2} ({table1}_id)
        ''')
    cursor.execute(
        f'''
        CREATE INDEX IF NOT EXISTS {table2}_{table1}_idx
        ON {table1}_{table2} ({table2}_id)
        ''')


def create_tables():
    c = conn.cursor()
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS sentence (
            id integer PRIMARY KEY,
            text text UNIQUE,
            source_database text,
            source_url text,
            source_id text,
            license_url text,
            creator text,
            pronunciation text,
            unknown_factors real,
            unknown_percentage real)
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS lemma (
            id integer PRIMARY KEY,
            text text,
            disambiguator text,
            memory_strength real,
            last_refresh real,
            frequency real,
            UNIQUE (text, disambiguator))
        ''')
    create_link_table(c, 'sentence', 'lemma')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS grammar (
            id integer PRIMARY KEY,
            form text UNIQUE,
            memory_strength real,
            last_refresh real,
            frequency real)
        ''')
    create_link_table(c, 'sentence', 'grammar')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS grapheme (
            id integer PRIMARY KEY,
            text text UNIQUE,
            memory_strength real,
            last_refresh real,
            frequency real)
        ''')
    create_link_table(c, 'sentence', 'grapheme')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS pronunciation (
            id integer PRIMARY KEY,
            word text,
            pronunciation text,
            forward_memory_strength real,
            last_forward_refresh real,
            backward_memory_strength real,
            last_backward_refresh real,
            frequency real,
            UNIQUE (word, pronunciation))
        ''')
    create_link_table(c, 'sentence', 'pronunciation')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS sound (
            id integer PRIMARY KEY,
            text text UNIQUE,
            memory_strength real,
            last_refresh real,
            frequency real)
        ''')
    create_link_table(c, 'sentence', 'sound')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS totals (
            id integer PRIMARY KEY CHECK (id = 0),
            total_lemma_frequency real,
            total_grammar_frequency real,
            total_grapheme_frequency real,
            total_pronunciation_frequency real,
            total_sound_frequency real)
        ''')
    c.execute(
        '''
        INSERT INTO  totals (
            id,
            total_lemma_frequency,
            total_grammar_frequency,
            total_grapheme_frequency,
            total_pronunciation_frequency,
            total_sound_frequency)
        VALUES (0, 0, 0, 0, 0, 0)
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS review (
            sentence_id integer REFERENCES sentence(id),
            type integer,
            summed_inverse_memory_strength real,
            inverse_memory_strength_weighted_last_refresh real)
        ''')


def read_sentences(filename):
    with open(filename) as f:
        with subprocess.Popen(
                ['java', '-jar', 'kuromoji/target/kuromoji-1.0-jar-with-dependencies.jar'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                bufsize=1,  # line buffered
                universal_newlines=True
        ) as kuromoji:
            for line in f:
                line = line.rstrip('\n')
                source_database, source_url, source_id, license_url, creator, sentence = line.split('\t')
                kuromoji.stdin.write(sentence+'\n')
                analyzed = ''
                segmented = []
                pronounced = []
                based = []
                grammared = []
                while True:
                    if analyzed == sentence:
                        break
                    row = kuromoji.stdout.readline().rstrip('\n')
                    if not row or row == 'EOS':
                        continue
                    word, analysis = row.split('\t')
                    pos1, pos2, pos3, pos4, conjugation, form, base, pronunciation = analysis.split(',')
                    disambiguator = ','.join(
                        pos for pos in (
                            pos1 if pos1 not in pos2 else '*',
                            pos2, pos3, pos4)
                        if pos != '*')
                    grammar = ','.join(
                        part for part in (
                            pos1 if pos1 not in conjugation else '*',
                            conjugation, form)
                        if part != '*')
                    analyzed += word
                    segmented.append(word)
                    if pronunciation == '*':
                        pronunciation = word
                    pronounced.append(pronunciation)
                    if base == '*':
                        base = word
                    based.append((base, disambiguator))
                    grammared.append(grammar)
                yield (source_database, source_url, source_id, license_url, creator,
                       sentence, segmented, pronounced, based, grammared)


def count_or_create(cursor, table, fields, values, frequency_field='frequency'):
    insert = f'''
        INSERT OR IGNORE INTO {table} ({', '.join(fields+(frequency_field,))})
        VALUES ({', '.join(tuple('?' for f in fields) + ('0',))})
        '''
    update = f'''
        UPDATE {table} SET {frequency_field} = {frequency_field} + 1
        WHERE {' AND '.join(f + ' = ?' for f in fields)}
        '''
    cursor.executemany(insert, values)
    cursor.executemany(update, values)


def create_links(cursor, table1, table2, fields1, fields2, values1, values2):
    from itertools import product
    cursor.executemany(
        f'''
        INSERT OR IGNORE INTO {table1}_{table2}
        SELECT {table1}.id AS {table1}_id, {table2}.id AS {table2}_id
        FROM {table1}, {table2}
        WHERE {' AND '.join(f'{t}.{f} = ?'
                            for (t, fs) in ((table1, fields1),
                                            (table2, fields2))
                            for f in fs)}
        ''',
        (v1 + v2 for v1, v2 in product(values1, values2)))


def update_total_frequency(cursor, table):
    cursor.execute(
        f'''
        UPDATE totals
        SET total_{table}_frequency = (SELECT sum(frequency) FROM {table})
        WHERE id = 0
        ''')


def create_refresh_trigger(cursor, table, kinds):
    for kind in kinds:
        cursor.execute(
            f'''
            CREATE TRIGGER IF NOT EXISTS {table}_{kind}refresh_trigger
            AFTER UPDATE OF {kind}memory_strength ON {table}
            FOR EACH ROW WHEN
                OLD.{kind}memory_strength IS NULL
                AND NEW.{kind}memory_strength IS NOT NULL
            BEGIN
                UPDATE sentence SET
                    unknown_factors = unknown_factors - 1,
                    unknown_percentage = unknown_percentage - NEW.frequency/(
                        SELECT total_{table}_frequency FROM totals)
                WHERE sentence.id IN (
                    SELECT sentence_id
                    FROM sentence_{table}
                    WHERE {table}_id = NEW.id);
            END
            ''')
        cursor.execute(
            f'''
            CREATE TRIGGER IF NOT EXISTS {table}_{kind}refresh_review_trigger
            AFTER UPDATE OF {kind}memory_strength, last_{kind}refresh ON {table}
            FOR EACH ROW WHEN
                OLD.{kind}memory_strength IS NOT NULL
                AND NEW.{kind}memory_strength IS NOT NULL
            BEGIN
                UPDATE review SET
                    summed_inverse_memory_strength =
                        summed_inverse_memory_strength
                        - 1/OLD.{kind}memory_strength
                        + 1/NEW.{kind}memory_strength,
                    inverse_memory_strength_weighted_last_refresh =
                        inverse_memory_strength_weighted_last_refresh
                        - OLD.last_{kind}refresh/OLD.{kind}memory_strength
                        + NEW.last_{kind}refresh/NEW.{kind}memory_strength
                WHERE sentence_id IN (
                    SELECT sentence_id
                    FROM sentence_{table}
                    WHERE {table}_id = NEW.id)
                AND review.type IN ({','.join(
                    str(review_type.value)
                    for review_type in ReviewType
                    if (table, kind) in review_type.tables_kinds)});
            END
            ''')


def build_database(args):
    global conn
    conn = sqlite3.connect(args.database)
    create_tables()
    c = conn.cursor()
    previous_sentence_id = None
    for (source_database, source_url, source_id, license_url, creator,
         sentence, segmented, pronounced, based, grammared
         ) in read_sentences(args.sentence_table):
        joined_segmentation = '\t'.join(segmented)
        joined_pronunciation = '\t'.join(pronounced)
        c.execute(
            '''
            INSERT OR IGNORE INTO sentence (
                text, pronunciation, source_database, source_url, source_id,
                license_url, creator) VALUES (?,?,?,?,?,?,?)
            ''',
            (joined_segmentation, joined_pronunciation, source_database,
             source_url, source_id, license_url, creator))
        sentence_id = [next(c.execute('SELECT last_insert_rowid() FROM sentence'))]
        if sentence_id == previous_sentence_id:
            continue
        previous_sentence_id = sentence_id
        count_or_create(c, 'lemma', ('text', 'disambiguator'),
                        based)
        create_links(c, 'sentence', 'lemma', ('id',), ('text', 'disambiguator'),
                     sentence_id, based)
        count_or_create(c, 'grammar', ('form',),
                        [(g,) for g in grammared])
        create_links(c, 'sentence', 'grammar', ('id',), ('form',),
                     sentence_id, [(g,) for g in grammared])
        count_or_create(c, 'grapheme', ('text',),
                        sentence)
        create_links(c, 'sentence', 'grapheme', ('id',), ('text',),
                     sentence_id, [(w,) for w in sentence])
        count_or_create(c, 'pronunciation', ('word', 'pronunciation'),
                        list(zip(segmented, pronounced)))
        create_links(c, 'sentence', 'pronunciation', ('id',), ('word', 'pronunciation'),
                     sentence_id, list(zip(segmented, pronounced)))
        count_or_create(c, 'sound', ('text',),
                        [(c,) for p in pronounced for c in p])
        create_links(c, 'sentence', 'sound', ('id',), ('text',),
                     sentence_id, [(c,) for p in pronounced for c in p])
    tables = ('lemma', 'grammar', 'grapheme', 'pronunciation', 'sound')
    for table in tables:
        update_total_frequency(c, table)
    kindses = (('',), ('',), ('',), ('forward_', 'backward_'), ('',))
    for table, kinds in zip(tables, kindses):
        create_refresh_trigger(c, table, kinds)
    c.execute(
        f'''
        CREATE TRIGGER IF NOT EXISTS sentence_learned_trigger
        AFTER UPDATE OF unknown_factors ON sentence
        FOR EACH ROW WHEN
            OLD.unknown_factors > 0
            AND NEW.unknown_factors = 0
        BEGIN
            INSERT INTO review (
                sentence_id,
                type,
                summed_inverse_memory_strength,
                inverse_memory_strength_weighted_last_refresh)
            VALUES
            {','.join(
                f"""
                (NEW.id,
                {review_type.value},
                {'+'.join(
                    f'(SELECT sum(1/{table}.{kind}memory_strength)'
                    f' FROM {table}, sentence_{table}'
                    f' WHERE {table}.id = {table}_id'
                    f' AND NEW.id = sentence_id)'
                    for table, kind in review_type.tables_kinds)},
                {'+'.join(
                    f'(SELECT sum({table}.last_{kind}refresh/{table}.{kind}memory_strength)'
                    f' FROM {table}, sentence_{table}'
                    f' WHERE {table}.id = {table}_id'
                    f' AND NEW.id = sentence_id)'
                    for table, kind in review_type.tables_kinds)})
                """ for review_type in ReviewType)};
        END
        ''')
    c.execute(
        f'''
        UPDATE sentence SET
            unknown_factors = {'+'.join(
                f"""(
                    SELECT count(*)
                    FROM sentence_{table}, {table}
                    WHERE sentence_id = sentence.id
                    AND {table}_id = {table}.id
                    AND {table}.{kind}memory_strength IS NULL)
                """ for table, kinds in zip(tables, kindses) for kind in kinds)},
            unknown_percentage = {'+'.join(
                f"""(
                    SELECT sum({table}.frequency)/total_{table}_frequency
                    FROM sentence_{table}, {table}, totals
                    WHERE sentence_id = sentence.id
                    AND {table}_id = {table}.id
                    AND {table}.{kind}memory_strength IS NULL)
                """ for table, kinds in zip(tables, kindses) for kind in kinds)}
        ''')
    conn.commit()


def main(argv):
    parser = argparse.ArgumentParser(
        description='Japanese sentence database')
    parser.add_argument('command', nargs=1, choices={'build-database'})
    parser.add_argument('--database', type=str, default='data/japanese_sentences.sqlite')
    parser.add_argument('--sentence-table', type=str, default='data/japanese_sentences.csv')
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    import sys
    main(sys.argv)
