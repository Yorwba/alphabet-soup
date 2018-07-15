.PHONY: all download-tatoeba

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
