#!/usr/bin/env python3

import argparse
import lxml.etree
import re


def find_links(args):
    xml_lines = []
    xml_declaration = b'<?xml version="1.0" encoding="utf-8"?>\n'
    with open(args.index, 'rb') as f:
        for line in f.readlines():
            if line != xml_declaration:
                xml_lines.append(line)
    xml_string = xml_declaration+b'<xml>'+b''.join(xml_lines)+b'</xml>'
    xml_tree = lxml.etree.fromstring(xml_string)
    for book in xml_tree.findall('.//book'):
        language = book.find('language').text
        text_source = book.find('url_text_source').text
        zip_file = book.find('url_zip_file').text
        print(language, text_source, zip_file, sep='\t')


def main(argv):
    parser = argparse.ArgumentParser(
        description='LibriVox data file parser')
    parser.add_argument('command', nargs=1, choices={'find-links'})
    parser.add_argument('--index', type=str)
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    import sys
    main(sys.argv)
