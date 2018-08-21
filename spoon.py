#!/usr/bin/python3

import argparse
import sqlite3


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
    print(text)
    print(pronunciation)
    print(translation)


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
