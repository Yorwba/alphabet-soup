#!/usr/bin/python3

import argparse
import sqlite3


def read_escaped_lines(filename):
    with open(filename, newline='\n') as file:
        continued_line = ''
        for line in file:
            if line.endswith('\\\n'):
                continued_line += line[:-2]+'\n'
                continue
            else:
                continued_line += line[:-1]
                yield continued_line
                continued_line = ''
        if continued_line:
            yield continued_line


def split_tsv_line(line):
    splits = []
    current_split = ''
    escaped = False
    for char in line:
        if escaped:
            if char not in {'\\', '\t'}:
                current_split += '\\'
            current_split += char
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == '\t':
            if current_split == '\\N':
                current_split = None
            splits.append(current_split)
            current_split = ''
        else:
            current_split += char
    if current_split == '\\N':
        current_split = None
    splits.append(current_split)
    return splits


def read_tatoeba_tsv(filename):
    for line in read_escaped_lines(filename):
        yield split_tsv_line(line)


def read_user_languages():
    c = conn.cursor()
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS user_languages (
            lang text,
            level integer,
            user text,
            details text,
            PRIMARY KEY (lang, user))
        ''')
    c.execute(
        '''
        CREATE INDEX idx_language_users ON user_languages(lang)
        ''')
    c.executemany('INSERT INTO user_languages VALUES (?,?,?,?)',
                  ((lang, level, user, details)
                   for lang, level, user, details
                   in read_tatoeba_tsv('data/tatoeba/user_languages.csv')
                   if lang and user))
    conn.commit()


def read_sentences():
    c = conn.cursor()
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS sentences_detailed (
            id integer PRIMARY KEY,
            lang text,
            text text,
            user text,
            added date,
            modified date)
        ''')
    c.execute(
        '''
        CREATE INDEX idx_user_sentences ON sentences_detailed(user)
        ''')
    c.executemany('INSERT INTO sentences_detailed VALUES (?,?,?,?,?,?)',
                  read_tatoeba_tsv('data/tatoeba/sentences_detailed.csv'))
    conn.commit()


def read_links():
    c = conn.cursor()
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS links (
            sentence_id integer REFERENCES sentences_detailed(id),
            translation_id integer REFERENCES sentences_detailed(id))
        ''')
    c.execute(
        '''
        CREATE INDEX idx_links_sentence ON links(sentence_id)
        ''')
    c.executemany('INSERT INTO links VALUES (?,?)',
                  read_tatoeba_tsv('data/tatoeba/links.csv'))
    conn.commit()


def read_tags():
    c = conn.cursor()
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS tags (
            id integer REFERENCES sentences_detailed(id),
            name text)
        ''')
    c.executemany('INSERT INTO tags VALUES (?,?)',
                  read_tatoeba_tsv('data/tatoeba/tags.csv'))
    conn.commit()


def read_sentences_with_audio():
    c = conn.cursor()
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS sentences_with_audio (
            id integer PRIMARY KEY REFERENCES sentences_detailed(id),
            user text REFERENCES sentences_detailed(user),
            license text,
            attribution text)
        ''')
    c.executemany('INSERT OR REPLACE INTO sentences_with_audio VALUES (?,?,?,?)',
                  read_tatoeba_tsv('data/tatoeba/sentences_with_audio.csv'))
    conn.commit()


def build_database(args):
    from os import remove
    try:
        remove(args.database)
    except FileNotFoundError:
        pass
    global conn
    conn = sqlite3.connect(args.database)
    read_user_languages()
    read_sentences()
    read_links()
    read_tags()
    read_sentences_with_audio()


def filter_language(args):
    global conn
    conn = sqlite3.connect(args.database)
    c = conn.cursor()
    for row in c.execute(
            '''
            SELECT
                s.id,
                s.lang,
                s.text,
                s.user,
                s.added,
                s.modified
            FROM
                sentences_detailed AS s,
                user_languages AS u
            WHERE
                s.lang = u.lang
                AND u.lang = ?
                AND s.user == u.user
                AND u.level >= ?
            ''',
            (args.language, args.minimum_level)):
        id, lang, text, user, added, modified = row
        url = 'https://tatoeba.org/eng/sentences/show/'+str(id)
        license = 'https://creativecommons.org/licenses/by/2.0/'
        print('\t'.join(('tatoeba', url, str(id), license, user, text)))


def main(argv):
    parser = argparse.ArgumentParser(
        description='Tatoeba data file parser')
    parser.add_argument('command', nargs=1, choices={
        'build-database',
        'filter-language'})
    parser.add_argument('--database', type=str, default='data/tatoeba.sqlite')
    parser.add_argument('--minimum-level', type=int, default=5)
    parser.add_argument('--language', type=str)
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    import sys
    main(sys.argv)
