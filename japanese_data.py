#!/usr/bin/env python3

import argparse
from collections import OrderedDict
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
            segmented_text text,
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
            type integer)
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


def transfer_memory(cursor, old_database):
    '''
    To be able to change the database creation process in ways that may affect
    the sentence decomposition *without* clobbering existing learning progress,
    it is necessary to somehow transfer the values of the ``last_refresh`` and
    ``memory_strength`` variables. Ideally, it should be possible to continue
    learning with the rebuilt database, without noticing any change in the
    sentences that are scheduled for review.

    To achieve this, the values are aggregated at the sentence level in the old
    database, then the same sentences are identified in the new database and
    the sentence-level values are attributed to individual details of those
    sentences.

    If there were no changes in analysis, the values from the original database
    should be reconstructed completely.

    To transfer ``last_review``, we can make use of the fact that reviewing a
    sentence updates this value for all details, so
    ``sentence.last_review <= detail.last_review``.
    Hence we can use ``sentence.last_review = min(detail.last_review)`` to
    aggregate and ``detail.last_review = max(sentence.last_review)``` to
    disaggregate this value.

    If there are no changes in the decomposition of sentences into details, this
    reconstruction is lossless, since each detail is assigned the value of the
    sentence where it was most recently reviewed. For the same reason, the result
    will still be sensible, as e.g. newly identified details will be assigned
    the time when they would have been reviewed.

    Transferring ``memory_strength`` is not so simple, since the frequency with
    which a detail appears may matter. E.g. if a single detail `a` in the old
    database is recognized as an instance of `A` in a small number of cases in
    the new database, then `A` may very well have never been reviewed and should
    correspondingly have a low ``memory_strength``, while that of `a` should
    remain essentially unchanged.

    To achieve this, the aggregate is computed as
    ``sentence.memory_strength = sum(detail.memory_strength/detail.frequency)``.
    That way, the sum over all sentences and the sum over all details are equal,
    and disaggregating by solving the corresponding system of linear equations
    also conserves memory strength. However, this requires the frequency to be
    computed only over sentences that match between the two databases! The
    precomputed frequency in the database cannot be used.
    '''

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
            last_{kind}refresh AS last_refresh
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
            PRIMARY KEY (new_id, review_type))
        ''')
    cursor.execute(
        f'''
        INSERT INTO new_old_sentences
        SELECT
            s.id AS new_id,
            o.id AS old_id,
            u.review_type,
            min(u.last_refresh) AS last_refresh
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
    timing()
    num_review_types = len(ReviewType)
    (sentence_dimension,), = cursor.execute(
        f'''
        SELECT max(new_id*{num_review_types}+review_type)+1
        FROM temp.new_old_sentences
        ''')

    detail_dimension = {}
    table_kind_range = {}
    transfer_matrix = {}
    for database in ('old_data.', ''):
        timing()
        table_kind_dimension = {
            (table, kind): next(cursor.execute(f'SELECT max(id)+1 FROM {database}{table}'))[0]
            for review_type in ReviewType
            for table, kind in review_type.tables_kinds}
        timing()
        table_kind_range[database] = OrderedDict()  # need fixed iteration order
        seen = 0
        for table_kind, dimension in table_kind_dimension.items():
            table_kind_range[database][table_kind] = (seen, seen+dimension)
            seen += dimension
        detail_dimension[database] = seen

        detail_union = ' UNION ALL '.join(
            f'''
            SELECT
                {review_type.value} AS review_type,
                sentence_id,
                {table_kind_range[database][(table, kind)][0]}+{table}.id AS detail_index
            FROM {database}sentence_{table}, {database}{table}
            WHERE {table}_id = {table}.id
            '''
            for review_type in ReviewType
            for table, kind in review_type.tables_kinds)

        timing()
        new_or_old = {'':'new', 'old_data.':'old'}[database]
        pairings = cursor.execute(
            f'''
            SELECT
                no.new_id*{num_review_types}+no.review_type AS sentence_index,
                dt.detail_index
            FROM
                temp.new_old_sentences AS no,
                ({detail_union}) AS dt
            WHERE no.{new_or_old}_id = dt.sentence_id
            AND no.review_type = dt.review_type
            ORDER BY sentence_index, detail_index
            ''')
        timing()

        import numpy as np
        import scipy.sparse as sp
        import scipy.sparse.linalg

        indptr = []
        indices = []
        data = []

        timing()
        for (sentence_index, detail_index) in pairings:
            while sentence_index >= len(indptr):
                indptr.append(len(indices))
            indices.append(detail_index)
            data.append(1)
        indptr.append(len(indices))
        timing()

        m = sp.csr_matrix(
            (data, indices, indptr),
            shape=(sentence_dimension, detail_dimension[database]),
            dtype=float)
        m.data /= m.sum(axis=0).flat[m.indices].flat  # normalize by detail frequency
        transfer_matrix[database] = m
    timing()

    input_memory_strengths = np.zeros(detail_dimension['old_data.'])
    detail_union = ' UNION ALL '.join(
        f'''
        SELECT
            {table_kind_range['old_data.'][(table, kind)][0]}+id AS detail_index,
            {kind}memory_strength AS memory_strength
        FROM old_data.{table}
        WHERE {kind}memory_strength IS NOT NULL
        '''
        for review_type in ReviewType
        for table, kind in review_type.tables_kinds)
    for (detail_index, memory_strength) in cursor.execute(detail_union):
        input_memory_strengths[detail_index] = memory_strength
    timing()

    sentence_memory_strengths = transfer_matrix['old_data.'].dot(input_memory_strengths)
    timing()

    output_vector, istop, itn, normr, normar, norma, conda, normx = sp.linalg.lsmr(transfer_matrix[''], sentence_memory_strengths)

    if istop not in (0, 1, 2, 4, 5):
        raise RuntimeError(f'Memory transfer equations could not be solved. istop = {istop}')
    timing()

    for ((table, kind), (start, stop)) in table_kind_range[''].items():
        output_range = output_vector[start:stop]
        cursor.executemany(
            f'''
            UPDATE {table}
            SET {kind}memory_strength = ?
            WHERE id = ?
            ''',
            ((memory_strength, i)
             for (i, memory_strength) in enumerate(output_range)
             if memory_strength > 0))


def build_database(args):
    global conn
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
    import sys
    main(sys.argv)
