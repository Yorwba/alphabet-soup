#!/usr/bin/env python3

import argparse
import contextlib
import ffmpeg
import lxml.etree
import re
import requests
import os
import os.path
import tempfile

ARCHIVE_URL_PATTERN = re.compile(r'https?://(?:www\.)?archive\.org/(?:compress|download)//?([^/]+)/')

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
        if zip_file:
            archive_id = ARCHIVE_URL_PATTERN.match(zip_file).group(1)
            print(language, text_source, archive_id, sep='\t')


def download_audiobooks(args):
    with open(args.file_list, 'r') as file_list:
        os.makedirs(args.output_directory, exist_ok=True)
        for line in file_list.readlines():
            line = line.strip()
            archive_id = line.split('\t')[-1]
            m3u_link = f'https://archive.org/download/{archive_id}/{archive_id}_64kb.m3u'
            output_file = os.path.join(args.output_directory, archive_id+'.mp3')

            # Get the list of files. This is nonstandard, not handled by m3u8.
            # Let's hope the format doesn't get upgraded to #EXTM3U later...
            playlist = requests.get(m3u_link).text.split('\n')
            parts = []
            with contextlib.ExitStack() as exit_stack:
                for uri in playlist:
                    if uri:
                        part = exit_stack.enter_context(
                            tempfile.NamedTemporaryFile(
                                suffix='.mp3'
                            )
                        )
                        parts.append(part)
                        # Downloading all at once leads to truncation somehow?
                        # So download each part to temporary storage first.
                        ffmpeg.input(uri).output(part.name).overwrite_output().run()
                ffmpeg.concat(
                    *(ffmpeg.input(part.name).audio for part in parts),
                    v=0,
                    a=1,
                ).output(output_file).run()


def main(argv):
    parser = argparse.ArgumentParser(
        description='LibriVox data file parser')
    parser.add_argument('command', nargs=1, choices={
        'find-links',
        'download-audiobooks'})
    parser.add_argument('--index', type=str)
    parser.add_argument('--file-list', type=str)
    parser.add_argument('--output-directory', type=str)
    args = parser.parse_args(argv[1:])

    globals()[args.command[0].replace('-', '_')](args)


if __name__ == '__main__':
    import sys
    main(sys.argv)
