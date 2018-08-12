#!/usr/bin/python3

import argparse
from enum import Enum
import sqlite3
import subprocess


class ReviewType(Enum):
    WRITING_TO_PRONUNCIATION = 0
    PRONUNCIATION_TO_WRITING = 1


def create_tables():
    c = conn.cursor()
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS sentence (
            id integer PRIMARY KEY,
            text text UNIQUE,
            meaning text,
            pronunciation text)
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
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS sentence_base_word (
            sentence_id REFERENCES sentence(id),
            base_word_id REFERENCES base_word(id))
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS grammar (
            id integer PRIMARY KEY,
            form text UNIQUE,
            memory_strength real,
            frequency real)
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS sentence_grammar (
            sentence_id REFERENCES sentence(id),
            grammar_id REFERENCES grammar(id))
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS writing_component (
            id integer PRIMARY KEY,
            text text UNIQUE,
            memory_strength real,
            frequency real)
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS sentence_writing_component (
            sentence_id REFERENCES sentence(id),
            writing_component_id REFERENCES writing_component(id))
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS pronunciation (
            pronunciation_id integer PRIMARY KEY,
            word text,
            pronunciation text,
            forward_memory_strength real,
            backward_memory_strength real,
            frequency real,
            UNIQUE (word, pronunciation))
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS sentence_pronunciation (
            sentence_id REFERENCES sentence(id),
            pronunciation_id REFERENCES pronunciation(id))
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS pronunciation_component (
            id integer PRIMARY KEY,
            text text UNIQUE,
            memory_strength real,
            frequency real)
        ''')
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS sentence_pronunciation_component (
            sentence_id REFERENCES sentence(id),
            pronunciation_component_id REFERENCES pronunciation_component(id))
        ''')
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
        for line in f:
            line = line[:-1]  # get rid of newline
            source, sentence_id, sentence = line.split('\t')
            analyzed = subprocess.run(
                ['mecab'],
                input=sentence.encode('utf-8'),
                stdout=subprocess.PIPE
            ).stdout.decode('utf-8')
            segmented = []
            pronounced = []
            based = []
            grammared = []
            for row in analyzed.split('\n'):
                if not row or row == 'EOS':
                    continue
                word, analysis = row.split('\t')
                category, subcategory, conjugation, form, base, pronunciation, details = analysis.split(',')
                disambiguator = category+','+subcategory
                grammar = conjugation+','+form
                segmented.append(word)
                pronounced.append(pronunciation)
                based.append((base, disambiguator))
                grammared.append(grammar)
            yield sentence, segmented, pronounced, based, grammared



def build_database(args):
    global conn
    conn = sqlite3.connect(args.database)
    create_tables()
    c = conn.cursor()
    for (sentence, segmented, pronounced, based, grammared) in read_sentences(args.sentence_table):
        c.execute(
            '''
            INSERT OR IGNORE INTO sentence (text, pronunciation) VALUES (?,?)
            ''',
            (' '.join(segmented), ' '.join(pronounced)))
        c.executemany(
            '''
            INSERT OR IGNORE INTO base_word (text, disambiguator, frequency) VALUES (?,?,0)
            ''',
            based)
        c.executemany(
            '''
            UPDATE base_word SET frequency = frequency + 1
            WHERE text = ? AND disambiguator = ?
            ''',
            based)
        c.executemany(
            '''
            INSERT INTO sentence_base_word
            SELECT sentence.id AS sentence_id, base_word.id AS base_word_id
            FROM sentence, base_word
            WHERE sentence.text = ?
            AND base_word.text = ?
            AND base_word.disambiguator = ?
            ''',
            [(' '.join(segmented), text, disambiguator) for text, disambiguator in based])
        c.executemany(
            '''
            INSERT OR IGNORE INTO grammar (form, frequency) VALUES (?,0)
            ''',
            [(g,) for g in grammared])
        c.executemany(
            '''
            UPDATE grammar SET frequency = frequency + 1
            WHERE form = ?
            ''',
            [(g,) for g in grammared])
        c.executemany(
            '''
            INSERT OR IGNORE INTO writing_component (text, frequency) VALUES (?,0)
            ''',
            sentence)
        c.executemany(
            '''
            UPDATE writing_component SET frequency = frequency + 1
            WHERE text = ?
            ''',
            sentence)
        c.executemany(
            '''
            INSERT OR IGNORE INTO pronunciation (word, pronunciation, frequency) VALUES (?,?,0)
            ''',
            zip(segmented, pronounced))
        c.executemany(
            '''
            UPDATE pronunciation SET frequency = frequency + 1
            WHERE word = ? AND pronunciation = ?
            ''',
            zip(segmented, pronounced))
        c.executemany(
            '''
            INSERT OR IGNORE INTO pronunciation_component (text, frequency) VALUES (?,0)
            ''',
            ((c,) for p in pronounced for c in p))
        c.executemany(
            '''
            UPDATE pronunciation_component SET frequency = frequency + 1
            WHERE text = ?
            ''',
            ((c,) for p in pronounced for c in p))
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
