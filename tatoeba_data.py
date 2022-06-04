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
import sqlite3


def read_escaped_lines(filename):
    with open(filename, newline='\n') as file:
        continued_line = ''
        for line in file:
            if line.endswith('\\\n'):
                backslash_count = len(line) - len(line.rstrip('\n').rstrip('\\')) - 1
                if backslash_count % 2:
                    continued_line += line[:-2]+'\n'
                    continue
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
    c.executemany('INSERT OR IGNORE INTO user_languages VALUES (?,?,?,?)',
                  ((lang, level, user, details)
                   for user_list in (
                           'data/tatoeba/user_languages.csv',
                           'CKs_native_speaker_list.csv')
                   for lang, level, user, details
                   in read_tatoeba_tsv(user_list)
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
            sentence_id integer REFERENCES sentences_detailed(id),
            audio_id integer PRIMARY KEY,
            user text REFERENCES sentences_detailed(user),
            license text,
            attribution text)
        ''')
    c.executemany('INSERT OR REPLACE INTO sentences_with_audio VALUES (?,?,?,?,?)',
                  read_tatoeba_tsv('data/tatoeba/sentences_with_audio.csv'))
    conn.commit()


def read_transcriptions():
    c = conn.cursor()
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS transcriptions (
            id integer REFERENCES sentences_detailed(id),
            lang text REFERENCES sentences_detailed(lang),
            script text,
            user text REFERENCES sentences_detailed(user),
            transcription text,
            PRIMARY KEY (id, script))
        ''')
    c.executemany('INSERT OR REPLACE INTO transcriptions VALUES (?,?,?,?,?)',
                  read_tatoeba_tsv('data/tatoeba/transcriptions.csv'))
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
    read_transcriptions()


def filter_language(args):
    lang_tags = args.language.split('-')
    lang = lang_tags[0]
    if len(lang_tags) == 2:
        script = lang_tags[1]
    else:
        script = ''
    global conn
    conn = sqlite3.connect(args.database)
    c = conn.cursor()
    for row in c.execute(
            '''
            SELECT
                s.id,
                s.lang,
                IFNULL(
                    (
                        SELECT t.transcription
                        FROM transcriptions AS t
                        WHERE t.id = s.id
                        AND script = :script
                        AND user != ''
                    ),
                    s.text
                ),
                s.user,
                s.added,
                s.modified
            FROM
                sentences_detailed AS s
            WHERE
                s.lang = :lang
                AND (
                     (s.id IN (SELECT id FROM tags WHERE name = 'OK'))
                     OR (
                        s.user IN (
                            SELECT user
                            FROM user_languages
                            WHERE lang = :lang
                            AND level >= :level)))
            ''',
            dict(
                lang=lang,
                script=script,
                level=args.minimum_level)):
        id, lang, text, user, added, modified = row
        url = 'https://tatoeba.org/eng/sentences/show/'+str(id)
        license = 'https://creativecommons.org/licenses/by/2.0/'
        print('\t'.join(('tatoeba', url, str(id), license, user or 'unknown user', text)))


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
