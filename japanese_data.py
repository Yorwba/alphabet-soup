#!/usr/bin/env python3

import argparse
from collections import OrderedDict
from enum import Enum
import re
import sqlite3
import subprocess
import sys


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


ALL_TABLES_KINDS = sorted(set(
    tk
    for review_type in ReviewType
    for tk in review_type.tables_kinds))


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
            segmented_text text,
            pronunciation text,
            minimum_unknown_frequency real,
            id_for_minimum_unknown_frequency integer,
            last_seen real)
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS lemma (
            id integer PRIMARY KEY,
            text text,
            disambiguator text,
            last_refresh real,
            last_relearn real,
            frequency real,
            UNIQUE (text, disambiguator))
        ''')
    create_link_table(c, 'sentence', 'lemma')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS grammar (
            id integer PRIMARY KEY,
            form text UNIQUE,
            last_refresh real,
            last_relearn real,
            frequency real)
        ''')
    create_link_table(c, 'sentence', 'grammar')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS grapheme (
            id integer PRIMARY KEY,
            text text UNIQUE,
            last_refresh real,
            last_relearn real,
            frequency real)
        ''')
    create_link_table(c, 'sentence', 'grapheme')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS pronunciation (
            id integer PRIMARY KEY,
            word text,
            pronunciation text,
            last_forward_refresh real,
            last_forward_relearn real,
            last_backward_refresh real,
            last_backward_relearn real,
            frequency real,
            UNIQUE (word, pronunciation))
        ''')
    create_link_table(c, 'sentence', 'pronunciation')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS sound (
            id integer PRIMARY KEY,
            text text UNIQUE,
            last_refresh real,
            last_relearn real,
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
            type integer)
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS log (
            table_kind text,
            frequency real,
            time_since_last_refresh real,
            time_since_last_relearn real,
            remembered integer)
        ''')


FURIGANA_PATTERN = re.compile(r'\[([^|]+)\|([^\]]+)\]')


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
                sentence = FURIGANA_PATTERN.sub('\\1', sentence)
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


def create_learn_trigger(cursor, table, kinds):
    for kind in kinds:
        add_or_remove = f'(1 - 2 * (NEW.last_{kind}relearn IS NULL))'
        cursor.execute(
            f'''
            CREATE TRIGGER IF NOT EXISTS {table}_{kind}learn_trigger
            AFTER UPDATE OF last_{kind}relearn ON {table}
            FOR EACH ROW WHEN
                (OLD.last_{kind}relearn IS NULL)
                <> (NEW.last_{kind}relearn IS NULL)
            BEGIN
                UPDATE sentence SET
                    (minimum_unknown_frequency, id_for_minimum_unknown_frequency) = (
                        SELECT frequency, id_for_minimum_unknown_frequency
                        FROM ({' UNION ALL '.join(
                            f"""
                            SELECT
                                t.frequency,
                                (
                                    t.id * {len(ALL_TABLES_KINDS)}
                                    + {ALL_TABLES_KINDS.index((table, kind))}
                                ) AS id_for_minimum_unknown_frequency
                            FROM sentence_{table} AS st, {table} AS t
                            WHERE st.{table}_id = t.id
                            AND t.last_{kind}relearn IS NULL
                            AND st.sentence_id = sentence.id
                            """
                            for table, kind in ALL_TABLES_KINDS)})
                        ORDER BY frequency ASC
                        LIMIT 1)
                WHERE sentence.id IN (
                    SELECT sentence_id
                    FROM sentence_{table}
                    WHERE {table}_id = NEW.id)
                AND (NEW.last_{kind}relearn IS NOT NULL) IS
                    (NEW.frequency IS sentence.minimum_unknown_frequency);
                -- Two cases:
                -- Learning something new:
                --   Changes the minimum unknown frequency if it was the minimum
                -- Unlearning something:
                --   Changes the minimum unknown frequency if it's less frequent
            END
            ''')


def create_log_trigger(cursor, table, kinds):
    for kind in kinds:
        cursor.execute(
            f'''
            CREATE TRIGGER IF NOT EXISTS {table}_{kind}log_trigger
            BEFORE UPDATE OF last_{kind}refresh ON {table}
            FOR EACH ROW WHEN
                OLD.last_{kind}relearn IS NOT NULL
                AND NEW.last_{kind}relearn IS NOT NULL
            BEGIN
                INSERT INTO log (
                    table_kind,
                    frequency,
                    time_since_last_refresh,
                    time_since_last_relearn,
                    remembered)
                VALUES (
                    "{table}_{kind}",
                    OLD.frequency,
                    julianday("now") - OLD.last_{kind}refresh,
                    julianday("now") - OLD.last_{kind}relearn,
                    (NEW.last_{kind}relearn == OLD.last_{kind}relearn));
            END
            ''')


def transfer_memory(cursor, old_database):
    '''
    To be able to change the database creation process in ways that may affect
    the sentence decomposition *without* clobbering existing learning progress,
    it is necessary to somehow transfer the values of the ``last_refresh`` and
    ``last_relearn`` variables. Ideally, it should be possible to continue
    learning with the rebuilt database, without noticing any change in the
    sentences that are scheduled for review.

    To achieve this, the values are aggregated at the sentence level in the old
    database, then the same sentences are identified in the new database and
    the sentence-level values are attributed to individual details of those
    sentences.

    If there were no changes in analysis, the values from the original database
    should be reconstructed completely.

    To transfer ``last_refresh``, we can make use of the fact that reviewing a
    sentence updates this value for all details, so
    ``sentence.last_refresh <= detail.last_refresh``.
    Hence we can use ``sentence.last_refresh = min(detail.last_refresh)`` to
    aggregate and ``detail.last_refresh = max(sentence.last_refresh)``` to
    disaggregate this value.

    If there are no changes in the decomposition of sentences into details, this
    reconstruction is lossless, since each detail is assigned the value of the
    sentence where it was most recently reviewed. For the same reason, the result
    will still be sensible, as e.g. newly identified details will be assigned
    the time when they would have been reviewed.

    The ``last_relearn`` can be transferred similarly by using the same
    relationship for the time of the *next* review:
    (This is fake, but more robust than using ``last_relearn`` directly.)
    A review is scheduled when ``(last_refresh - now)/(last_refresh - last_relearn)``
    falls below the desired level ``log(desired_retention)``. Therefore,
    ``next_refresh = last_refresh - log(desired_retention)*(last_refresh - last_relearn)``.
    Then the same min-max technique can be used to obtain a sentence-level value
    ``sentence.next_refresh = min(detail.next_refresh)``
    and to disaggregate it into the detail-level again by
    ``detail.next_refresh = max(sentence.next_refresh)``,
    from which the new ``last_relearn`` can be computed as
    ``last_relearn = last_refresh - (last_refresh - next_refresh)/log(desired_retention)``
    '''
    from spoon import DEFAULT_RETENTION
    import math

    log_retention = math.log(DEFAULT_RETENTION)

    from time import time
    previous_time = None
    previous_line = None
    def timing():
        nonlocal previous_time, previous_line
        from inspect import currentframe as cf
        new_time = time()
        new_line = cf().f_back.f_lineno
        if previous_time is not None:
            print(f'Took {new_time-previous_time:.3f}s from {previous_line} to {new_line}')
        previous_time = new_time
        previous_line = new_line

    timing()
    cursor.execute(f'ATTACH DATABASE ? AS old_data', (old_database,))
    timing()
    detail_union = ' UNION ALL '.join(
        f'''
        SELECT
            {review_type.value} AS review_type,
            sentence_id,
            last_{kind}refresh AS last_refresh,
            last_{kind}refresh - (last_{kind}refresh - last_{kind}relearn) * :log_retention AS next_refresh
        FROM old_data.sentence_{table}, old_data.{table}
        WHERE {table}_id = {table}.id
        '''
        for review_type in ReviewType
        for table, kind in review_type.tables_kinds)
    timing()
    cursor.execute(
        '''
        CREATE TEMPORARY TABLE new_old_sentences (
            new_id integer,
            old_id integer,
            review_type integer,
            last_refresh real,
            next_refresh real,
            PRIMARY KEY (new_id, review_type))
        ''')
    cursor.execute(
        f'''
        INSERT INTO new_old_sentences
        SELECT
            s.id AS new_id,
            o.id AS old_id,
            u.review_type,
            min(u.last_refresh) AS last_refresh,
            min(u.next_refresh) AS next_refresh
        FROM
            sentence AS s,
            old_data.sentence AS o,
            old_data.review as r,
            ({detail_union}) AS u
        WHERE s.text = o.text
        AND o.id = u.sentence_id
        AND o.id = r.sentence_id
        AND u.review_type = r.type
        GROUP BY s.id, o.id, u.review_type
        ''',
        dict(log_retention=log_retention))
    timing()
    cursor.execute(
        f'''
        UPDATE sentence
        SET last_seen = (
                SELECT o.last_seen
                FROM
                    old_data.sentence as o,
                    new_old_sentences as no
                WHERE o.id = no.old_id
                AND no.new_id = sentence.id
            )
        ''')
    timing()
    for review_type in ReviewType:
        for table, kind in review_type.tables_kinds:
            cursor.execute(
                f'''
                UPDATE {table}
                SET
                    last_{kind}refresh = max(
                        ifnull(last_{kind}refresh, 0),
                        (
                            SELECT max(last_refresh)
                            FROM
                                temp.new_old_sentences AS no,
                                sentence_{table} AS st
                            WHERE no.new_id = st.sentence_id
                            AND st.{table}_id = {table}.id
                            AND no.review_type = {review_type.value}))
                ''')
            cursor.execute(
                f'''
                UPDATE {table}
                SET
                    last_{kind}relearn = min(
                        ifnull(last_{kind}relearn, 1e100),
                        (
                            SELECT
                                last_{kind}refresh -
                                (
                                    {table}.last_{kind}refresh - max(next_refresh)
                                )/:log_retention
                            FROM
                                temp.new_old_sentences AS no,
                                sentence_{table} AS st
                            WHERE no.new_id = st.sentence_id
                            AND st.{table}_id = {table}.id
                            AND no.review_type = {review_type.value}))
                ''',
                dict(log_retention=log_retention))
    timing()

    cursor.execute('INSERT INTO log SELECT * from old_data.log')


def build_database(args):
    global conn
    # First check for bugs
    if sqlite3.sqlite_version_info < (3, 30, 0):
        has_bug = sqlite3.sqlite_version_info <= (3, 27, 2)
        if not has_bug:
            # needs testing
            conn = sqlite3.connect('')
            c = conn.cursor()
            c.execute('create table tta as select 1 as x')
            c.execute('create table ttb as select 2 as y, 3 as z')
            c.execute('update ttb set (y, z) = (select x, 4 from (select x from tta where x = 1 union all select 1 as x from tta where x = 1) order by x limit 1)')
            has_bug = [(1, 4)] != list(c.execute('select * from ttb'))

        if has_bug:
            print(
                f'Your version of SQLite has a bug. Try upgrading to version 3.30 or newer.',
                file=sys.stderr)
            sys.exit(1)

    conn = sqlite3.connect(args.database)
    create_tables()
    c = conn.cursor()
    previous_sentence_id = None
    for (source_database, source_url, source_id, license_url, creator,
         sentence, segmented, pronounced, based, grammared
         ) in read_sentences(args.sentence_table):
        unsegmented_text = ''.join(segmented)
        joined_segmentation = '\t'.join(segmented)
        joined_pronunciation = '\t'.join(pronounced)
        c.execute(
            '''
            INSERT OR IGNORE INTO sentence (
                text, segmented_text, pronunciation, source_database, source_url,
                source_id, license_url, creator) VALUES (?,?,?,?,?,?,?,?)
            ''',
            (unsegmented_text, joined_segmentation, joined_pronunciation,
             source_database, source_url, source_id, license_url, creator))
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
        create_learn_trigger(c, table, kinds)
        create_log_trigger(c, table, kinds)
    c.execute(
        f'''
        CREATE TRIGGER IF NOT EXISTS sentence_learned_trigger
        AFTER UPDATE OF minimum_unknown_frequency ON sentence
        FOR EACH ROW WHEN
            OLD.minimum_unknown_frequency IS NOT NULL
            AND NEW.minimum_unknown_frequency IS NULL
        BEGIN
            INSERT INTO review (
                sentence_id,
                type)
            VALUES
            {','.join(
                f"""
                (NEW.id,
                {review_type.value})
                """ for review_type in ReviewType)};
        END
        ''')
    c.execute(
        f'''
        CREATE TRIGGER IF NOT EXISTS sentence_unlearned_trigger
        AFTER UPDATE OF minimum_unknown_frequency ON sentence
        FOR EACH ROW WHEN
            OLD.minimum_unknown_frequency IS NULL
            AND NEW.minimum_unknown_frequency IS NOT NULL
        BEGIN
            DELETE FROM review
            WHERE sentence_id = NEW.id;
        END
        ''')
    c.execute(
        f'''
        UPDATE sentence SET
            (minimum_unknown_frequency, id_for_minimum_unknown_frequency) = (
                SELECT frequency, id_for_minimum_unknown_frequency
                FROM ({' UNION ALL '.join(
                    f"""
                    SELECT
                        t.frequency,
                        (
                            t.id * {len(ALL_TABLES_KINDS)}
                            + {ALL_TABLES_KINDS.index((table, kind))}
                        ) AS id_for_minimum_unknown_frequency
                    FROM sentence_{table} AS st, {table} AS t
                    WHERE st.{table}_id = t.id
                    AND t.last_{kind}relearn IS NULL
                    AND st.sentence_id = sentence.id
                    """
                    for table, kind in ALL_TABLES_KINDS)})
                ORDER BY frequency ASC
                LIMIT 1)
        ''')
    transfer_memory(c, args.old_database)
    conn.commit()


def main(argv):
    parser = argparse.ArgumentParser(
        description='Japanese sentence database')
    parser.add_argument('command', nargs=1, choices={'build-database'})
    parser.add_argument('--database', type=str, default='data/new_japanese_sentences.sqlite')
    parser.add_argument('--old-database', type=str, default='data/japanese_sentences.sqlite')
    parser.add_argument('--sentence-table', type=str, default='data/japanese_sentences.csv')
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    main(sys.argv)
