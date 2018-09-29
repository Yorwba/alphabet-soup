.PHONY: all download-tatoeba download-aozora-index \
	download-kanjivg kanjivg-gifs download-jmdict

TATOEBA_FILENAMES := sentences_detailed links tags sentences_with_audio user_languages
TATOEBA_FILES := $(addprefix data/tatoeba/,$(TATOEBA_FILENAMES))
TATOEBA_TARBALLS := $(addsuffix .tar.bz2,$(TATOEBA_FILES))
TATOEBA_CSVS := $(addsuffix .csv,$(TATOEBA_FILES))

all:

download-tatoeba:
	wget --timestamping --directory-prefix=data/tatoeba/ \
		$(subst data/tatoeba/,http://downloads.tatoeba.org/exports/,$(TATOEBA_TARBALLS))

data/tatoeba/%.tar.bz2:
	wget --directory-prefix=data/tatoeba/ \
		http://downloads.tatoeba.org/exports/$*.tar.bz2

data/tatoeba/%.csv: data/tatoeba/%.tar.bz2
	tar --directory=data/tatoeba/ --extract --bzip2 --touch --file=$<

data/tatoeba.sqlite: tatoeba_data.py $(TATOEBA_CSVS)
	./tatoeba_data.py build-database --database=$@

data/tatoeba_sentences_%.csv: data/tatoeba.sqlite tatoeba_data.py
	./tatoeba_data.py filter-language --database=$< \
		--language=$* --minimum-level=5 > $@

download-aozora-index:
	wget --timestamping --directory-prefix=data/aozora/ \
		https://www.aozora.gr.jp/index_pages/list_person_all_extended_utf8.zip

data/aozora/list_person_%.zip:
	wget --directory-prefix=data/aozora/
		https://www.aozora.gr.jp/index_pages/list_person_$*.zip

data/aozora/list_person_%.csv: data/aozora/list_person_%.zip
	unzip -DD $< -d data/aozora/

data/aozora/modern_works.urls: aozora_data.py data/aozora/list_person_all_extended_utf8.csv
	./aozora_data.py modern-works > $@

data/aozora/files: data/aozora/modern_works.urls
	wget --timestamping --directory-prefix=data/aozora/files/ \
		--input-file=$<
	touch data/aozora/files

data/aozora_sentences.csv: aozora_data.py data/aozora/files
	./aozora_data.py extract-sentences > $@

data/japanese_sentences.csv: data/tatoeba_sentences_jpn.csv data/aozora_sentences.csv
	cat $^ > $@

kuromoji/target/kuromoji-1.0-jar-with-dependencies.jar: kuromoji/src/main/java/com/yorwba/kuromoji/KuromojiTokenize.java kuromoji/pom.xml
	cd kuromoji; mvn clean compile assembly:single

data/japanese_sentences.sqlite: data/japanese_sentences.csv japanese_data.py kuromoji/target/kuromoji-1.0-jar-with-dependencies.jar
	./japanese_data.py build-database --database=$@ --sentence-table=$<

download-kanjivg:
	wget --timestamping --directory-prefix=data/kanjivg/ \
		https://github.com/KanjiVG/kanjivg/releases/download/r20160426/kanjivg-20160426-main.zip

data/kanjivg/kanji/%.svg: data/kanjivg/kanjivg-20160426-main.zip
	unzip -DD $< -d data/kanjivg/

data/kanjivg/kanji/%.gif: data/kanjivg/kanji/%.svg
	kanjivg-gif.py $<

kanjivg-gifs: download-kanjivg
	find data/kanjivg/kanji -name '*.svg' -exec kanjivg-gif.py '{}' '+'

download-jmdict:
	wget --timestamping --directory-prefix=data/jmdict/ \
		ftp://ftp.monash.edu.au/pub/nihongo/JMdict.gz
