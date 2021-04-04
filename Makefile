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

.PHONY: all setup download-tatoeba download-librivox-index \
	download-aozora-index download-kanjivg kanjivg-gifs

TATOEBA_FILENAMES := sentences_detailed links tags sentences_with_audio user_languages transcriptions
TATOEBA_FILES := $(addprefix data/tatoeba/,$(TATOEBA_FILENAMES))
TATOEBA_TARBALLS := $(addsuffix .tar.bz2,$(TATOEBA_FILES))
TATOEBA_CSVS := $(addsuffix .csv,$(TATOEBA_FILES))

VENV_PY := virtualenv/bin/python
VENV_PIP := $(VENV_PY) -m pip

all:

$(VENV_PY):
	python3 -m venv virtualenv
	$(VENV_PIP) install wheel

setup: $(VENV_PY)
	$(VENV_PIP) install -r requirements.txt

requirements.lock: requirements.txt $(VENV_PY)
	echo > "$@" # empty constraints
	$(VENV_PIP) install --upgrade -r "$<"
	$(VENV_PIP) freeze > "$@"

download-tatoeba:
	wget --timestamping --directory-prefix=data/tatoeba/ \
		$(subst data/tatoeba/,https://downloads.tatoeba.org/exports/,$(TATOEBA_TARBALLS))

data/tatoeba/%.tar.bz2:
	wget --timestamping --directory-prefix=data/tatoeba/ \
		https://downloads.tatoeba.org/exports/$*.tar.bz2

data/tatoeba/%.csv: data/tatoeba/%.tar.bz2
	tar --directory=data/tatoeba/ --extract --bzip2 --touch --file=$<

data/tatoeba.sqlite: tatoeba_data.py $(TATOEBA_CSVS)
	$(VENV_PY) ./tatoeba_data.py build-database --database=$@

data/tatoeba_sentences_%.csv: data/tatoeba.sqlite tatoeba_data.py
	$(VENV_PY) ./tatoeba_data.py filter-language --database=$< \
		--language=$* --minimum-level=5 > $@

data/librivox/:
	mkdir -p $@

download-librivox-index data/librivox/index.xml: data/librivox/
	wget $(foreach i,$(shell seq 0 13), \
		'https://librivox.org/api/feed/audiobooks?fields={language,url_text_source,url_zip_file}&offset='$(i)'000&limit=1000') \
		-O data/librivox/index.xml

data/librivox/download_urls.csv: data/librivox/index.xml librivox_data.py
	$(VENV_PY) ./librivox_data.py find-links --index=$< > $@

data/librivox/audiobooks/: data/aozora/librivox_audiobooks.csv librivox_data.py
	rm -r $@
	$(VENV_PY) ./librivox_data.py download-audiobooks --file-list=$< \
		--output-directory=$@
	touch $@

download-aozora-index:
	wget --timestamping --directory-prefix=data/aozora/ \
		https://www.aozora.gr.jp/index_pages/list_person_all_extended_utf8.zip

data/aozora/list_person_%.zip:
	wget --timestamping --directory-prefix=data/aozora/ \
		https://www.aozora.gr.jp/index_pages/list_person_$*.zip

data/aozora/list_person_%.csv: data/aozora/list_person_%.zip
	unzip -DD $< -d data/aozora/

data/aozora/modern_works.urls: aozora_data.py data/aozora/list_person_all_extended_utf8.csv
	$(VENV_PY) ./aozora_data.py modern-works > $@

data/aozora/librivox_audiobooks.csv: aozora_data.py data/aozora/list_person_all_extended_utf8.csv data/librivox/download_urls.csv
	$(VENV_PY) ./aozora_data.py librivox-audiobooks \
		--librivox-links=data/librivox/download_urls.csv > $@

data/aozora/files: data/aozora/modern_works.urls data/aozora/librivox_audiobooks.csv
	cat $^ | cut -f1 | \
		wget --timestamping --directory-prefix=data/aozora/files/ \
		--input-file=-
	touch $@

data/aozora_sentences.csv: aozora_data.py data/aozora/files
	$(VENV_PY) ./aozora_data.py extract-sentences > $@

data/japanese_sentences.csv: data/tatoeba_sentences_jpn-Hrkt.csv data/aozora_sentences.csv
	cat $^ > $@

kuromoji/target/kuromoji-1.0-jar-with-dependencies.jar: kuromoji/src/main/java/com/yorwba/kuromoji/KuromojiTokenize.java kuromoji/pom.xml
	cd kuromoji; mvn clean compile assembly:single

data/new_japanese_sentences.sqlite: data/japanese_sentences.csv japanese_data.py kuromoji/target/kuromoji-1.0-jar-with-dependencies.jar
	$(VENV_PY) ./japanese_data.py build-database --database=$@ --sentence-table=$<

data/kanjivg/kanjivg-20160426-main.zip:
	wget --timestamping --directory-prefix=data/kanjivg/ \
		https://github.com/KanjiVG/kanjivg/releases/download/r20160426/kanjivg-20160426-main.zip

data/kanjivg/kanji/%.svg: data/kanjivg/kanjivg-20160426-main.zip
	unzip -DD $< -d data/kanjivg/

data/kanjivg/kanji/%.gif: data/kanjivg/kanji/%.svg
	$(VENV_PY) kanjivg-gif.py $<

kanjivg-gifs: data/kanjivg/kanji/26951.svg # any would work here
	$(VENV_PY) find data/kanjivg/kanji -name '*.svg' -exec kanjivg-gif.py '{}' '+'

data/jmdict/JM%:
	wget --timestamping --directory-prefix=data/jmdict/ \
		ftp://ftp.monash.edu.au/pub/nihongo/`basename $@`

data/japanese_dictionary.sqlite: data/japanese_sentences.sqlite data/jmdict/JMdict.gz data/jmdict/JMnedict.xml.gz jmdict_data.py
	$(VENV_PY) ./jmdict_data.py convert \
		--jmdict=data/jmdict/JMdict.gz \
		--jmnedict=data/jmdict/JMnedict.xml.gz \
		--database=$@ --sentence-database=$<
