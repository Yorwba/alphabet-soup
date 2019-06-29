#!/usr/bin/env python3

import argparse
import csv
import re


with open('data/aozora/list_person_all_extended_utf8.csv') as f:
    aozora_list = list(csv.reader(f))
aozora_header = aozora_list[0]
aozora_table = aozora_list[1:]

library_card_url = aozora_header.index('図書カードURL')
author_birth = aozora_header.index('生年月日')
author_death = aozora_header.index('没年月日')
text_url = aozora_header.index('テキストファイルURL')


def modern_works(args):
    modern_files = list(
        row[text_url] for row in aozora_table
        if row[author_birth].startswith('19')
        and not row[author_death]
        and row[text_url].strip().split('.')[-1] in ('zip', 'txt')
        and (not args.aozora_only
             or row[text_url].startswith('https://www.aozora.gr.jp/')))
    for url in modern_files:
        print(url)


def sentences_in_paragraph(paragraph):
    left_brackets = '「『（〈'
    right_brackets = '」』）〉'
    terminators = '。？！'
    boundary_pattern = '(['+left_brackets+right_brackets+terminators+'])'
    parts = re.split(boundary_pattern, paragraph)
    i = 0
    sentence = ''
    character_count = 0
    while i < len(parts):
        if not sentence:
            character_count = sum(map(len, parts[:i]))
        if (parts[i].startswith('と') or parts[i].startswith('って'))\
                and not sentence and i > 0 and parts[i-1] in right_brackets:
            # After quotations of sentences, there might be an awkward
            # "...と言います" or similar hanging around. Skip it.
            i += 2
            continue
        sentence += parts[i]
        if i+1 < len(parts):
            bracket = left_brackets.find(parts[i+1])
            if bracket >= 0 and i+3 < len(parts) and parts[i+3] == right_brackets[bracket]:
                sentence += ''.join(parts[i+1:i+4])
                i += 4
                continue
            if parts[i+1] in terminators:
                sentence += parts[i+1]
                sentence = sentence.strip()
                if len(sentence) > 3:  # XXX how to better handle short sentences?
                    yield (character_count, sentence)
        sentence = ''
        i += 2


def extract_sentences(args):
    import os
    import zipfile
    filedir = 'data/aozora/files'
    for filename in os.listdir(filedir):
        filepath = os.path.join(filedir, filename)
        if zipfile.is_zipfile(filepath):
            try:
                with zipfile.ZipFile(filepath) as z:
                    url, = set(row[library_card_url]
                               for row in aozora_table
                               if row[text_url].endswith(filename))
                    for n in z.namelist():
                        if n.endswith('.txt'):
                            text = z.read(n).decode('shift-jis')
                            lines = text.split('\r\n')
                            separators = list(i for i, l in enumerate(lines)
                                              if set(l) == {'-'})
                            try:
                                end = lines.index('［＃本文終わり］')
                            except ValueError:
                                continue
                            license = None
                            creator = ''
                            for line in lines[end+1:]:
                                match = re.match('.*（(.*creativecommons.org/licenses/.*)）', line)
                                if match:
                                    license = match.group(1)
                                match = re.match('.*者：(.*)$', line)
                                if match:
                                    creator = match.group(1)
                            if not license:
                                continue
                            text_start = separators[1]+1
                            text_lines = lines[text_start:end]
                            for line_number, line in enumerate(text_lines):
                                line = re.sub('［＃[^］]*］', '', line)
                                for (character_count, sentence) in sentences_in_paragraph(line):
                                    print('\t'.join((
                                        'aozora',
                                        url,
                                        ':'.join((filename, n, str(text_start+line_number), str(character_count))),
                                        license,
                                        creator,
                                        sentence)))
            except zipfile.BadZipFile:
                pass


def main(argv):
    parser = argparse.ArgumentParser(
        description='Aozora data file parser')
    parser.add_argument('command', nargs=1, choices={
        'modern-works',
        'extract-sentences'})
    parser.add_argument('--aozora-only', type=bool, default=True)
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    import sys
    main(sys.argv)
