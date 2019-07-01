#!/usr/bin/env python3

import argparse
import csv
import re


with open('data/aozora/list_person_all_extended_utf8.csv') as f:
    aozora_list = list(csv.reader(f))
aozora_header = aozora_list[0]
aozora_table = aozora_list[1:]

library_card_url = aozora_header.index('図書カードURL')
author_family_name = aozora_header.index('姓')
author_given_name = aozora_header.index('名')
author_role = aozora_header.index('役割フラグ')
author_birth = aozora_header.index('生年月日')
author_death = aozora_header.index('没年月日')
input_by = aozora_header.index('入力者')
proofread_by = aozora_header.index('校正者')
text_url = aozora_header.index('テキストファイルURL')
html_file_url = aozora_header.index('XHTML/HTMLファイルURL')


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


def librivox_audiobooks(args):
    html_to_text = {
        row[html_file_url].replace('http:', 'https:'): row[text_url]
        for row in aozora_table}
    for line in args.librivox_links.readlines():
        line = line.strip()
        language, aozora_link, archive_link = line.split('\t')
        if language == 'Japanese':
            try:
                text_link = html_to_text[aozora_link.replace('http:', 'https:')]
                print(text_link, archive_link, sep='\t')
            except KeyError:
                pass


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

    filename_to_table_row = {
        row[text_url].split('/')[-1]: row
        for row in aozora_table}
    filedir = 'data/aozora/files'
    for filename in os.listdir(filedir):
        table_row = filename_to_table_row[filename]
        filepath = os.path.join(filedir, filename)
        if zipfile.is_zipfile(filepath):
            try:
                with zipfile.ZipFile(filepath) as z:
                    url = table_row[library_card_url]
                    for n in z.namelist():
                        if n.endswith('.txt'):
                            text = z.read(n).decode('shift-jis')
                            lines = text.split('\r\n')
                            separators = [i for i, l in enumerate(lines)
                                          if set(l) == {'-'}]

                            empty_stretch = 0
                            max_empty_stretch = 0
                            max_empty_stretch_index = None
                            for i, line in enumerate(lines):
                                if line:
                                    empty_stretch = 0
                                else:
                                    empty_stretch += 1
                                    if empty_stretch > max_empty_stretch:
                                        max_empty_stretch = empty_stretch
                                        max_empty_stretch_index = i

                            end = max_empty_stretch_index + 1
                            license = None
                            creators = [
                                (table_row[author_role], table_row[author_family_name]+table_row[author_given_name]),
                                ('入力者', table_row[input_by]),
                                ('校正者', table_row[proofread_by])]
                            for line in lines[end+1:]:
                                # not the correct regex, but good enough:
                                match = re.match('.*(https?://creativecommons.org/licenses/[!-~]*)', line)
                                if match:
                                    license = match.group(1)
                                match = re.match('このファイルは、インターネットの図書館、青空文庫（https?://www.aozora.gr.jp/?）で作られました。入力、校正、制作にあたったのは、ボランティアの皆さんです。', line)
                                if match:
                                    # technically not a license
                                    license = 'https://ja.wikipedia.org/wiki/%E3%83%91%E3%83%96%E3%83%AA%E3%83%83%E3%82%AF%E3%83%89%E3%83%A1%E3%82%A4%E3%83%B3'
                                match = re.match('(.*者)：(.*)$', line)
                                if match:
                                    creators.append(match.group(1, 2))

                            creators = '　'.join(
                                role+'：'+name
                                for role, name in creators
                                if name)

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
                                        creators,
                                        sentence)))
            except zipfile.BadZipFile:
                pass


def main(argv):
    parser = argparse.ArgumentParser(
        description='Aozora data file parser')
    parser.add_argument('command', nargs=1, choices={
        'modern-works',
        'librivox-audiobooks',
        'extract-sentences'})
    parser.add_argument('--aozora-only', type=bool, default=True)
    parser.add_argument('--librivox-links', type=argparse.FileType('r'), default=None)
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    import sys
    main(sys.argv)
