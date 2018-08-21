#!/usr/bin/python3

import argparse
from enum import Enum
import sqlite3
import subprocess


class ReviewType(Enum):
    WRITING_TO_PRONUNCIATION = 0
    PRONUNCIATION_TO_WRITING = 1


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
        CREATE TABLE IF NOT EXISTS base_word (
            id integer PRIMARY KEY,
            text text,
            disambiguator text,
            memory_strength real,
            frequency real,
            UNIQUE (text, disambiguator))
        ''')
    create_link_table(c, 'sentence', 'base_word')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS grammar (
            id integer PRIMARY KEY,
            form text UNIQUE,
            memory_strength real,
            frequency real)
        ''')
    create_link_table(c, 'sentence', 'grammar')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS writing_component (
            id integer PRIMARY KEY,
            text text UNIQUE,
            memory_strength real,
            frequency real)
        ''')
    create_link_table(c, 'sentence', 'writing_component')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS pronunciation (
            id integer PRIMARY KEY,
            word text,
            pronunciation text,
            forward_memory_strength real,
            backward_memory_strength real,
            frequency real,
            UNIQUE (word, pronunciation))
        ''')
    create_link_table(c, 'sentence', 'pronunciation')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS pronunciation_component (
            id integer PRIMARY KEY,
            text text UNIQUE,
            memory_strength real,
            frequency real)
        ''')
    create_link_table(c, 'sentence', 'pronunciation_component')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS review (
            sentence_id REFERENCES sentence(id),
            type integer,
            next_time real,
            desired_log_retention real,
            summed_inverse_memory_strength real,
            inverse_memory_strength_weighted_previous_time real)
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
                    disambiguator = ','.join((pos1, pos2, pos3, pos4))
                    grammar = ','.join((pos1, conjugation, form))
                    analyzed += word
                    segmented.append(word)
                    if pronunciation == '*':
                        pronunciation = word
                    pronounced.append(pronunciation)
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


def total_frequency(cursor, table):
    return next(cursor.execute(f'SELECT sum(frequency) FROM {table}'))[0]


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
        count_or_create(c, 'base_word', ('text', 'disambiguator'),
                        based)
        create_links(c, 'sentence', 'base_word', ('id',), ('text', 'disambiguator'),
                     sentence_id, based)
        count_or_create(c, 'grammar', ('form',),
                        [(g,) for g in grammared])
        create_links(c, 'sentence', 'grammar', ('id',), ('form',),
                     sentence_id, [(g,) for g in grammared])
        count_or_create(c, 'writing_component', ('text',),
                        sentence)
        create_links(c, 'sentence', 'writing_component', ('id',), ('text',),
                     sentence_id, [(w,) for w in sentence])
        count_or_create(c, 'pronunciation', ('word', 'pronunciation'),
                        list(zip(segmented, pronounced)))
        create_links(c, 'sentence', 'pronunciation', ('id',), ('word', 'pronunciation'),
                     sentence_id, list(zip(segmented, pronounced)))
        count_or_create(c, 'pronunciation_component', ('text',),
                        [(c,) for p in pronounced for c in p])
        create_links(c, 'sentence', 'pronunciation_component', ('id',), ('text',),
                     sentence_id, [(c,) for p in pronounced for c in p])
    tables = ('base_word', 'grammar', 'writing_component', 'pronunciation', 'pronunciation_component')
    c.execute(
        f'''
        UPDATE sentence SET
            unknown_factors = {'+'.join(
                f"""(
                    SELECT count(*)
                    FROM sentence_{table}, {table}
                    WHERE sentence_id = sentence.id
                    AND {table}_id = {table}.id)
                """ for table in tables)},
            unknown_percentage = {'+'.join(
                f"""(
                    SELECT sum({table}.frequency)/?
                    FROM sentence_{table}, {table}
                    WHERE sentence_id = sentence.id
                    AND {table}_id = {table}.id)
                """ for table in tables)}
        ''', tuple(total_frequency(c, table) for table in tables))
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
