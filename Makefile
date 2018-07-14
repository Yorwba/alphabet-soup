.PHONY: all download-tatoeba

TATOEBA_FILENAMES := sentences_detailed links tags sentences_with_audio user_languages
TATOEBA_FILES := $(addprefix data/tatoeba/,$(TATOEBA_FILENAMES))
TATOEBA_TARBALLS := $(addsuffix .tar.bz2,$(TATOEBA_FILES))
TATOEBA_CSVS := $(addsuffix .csv,$(TATOEBA_FILES))

data/tatoeba/%.tar.bz2:
	wget --directory-prefix=data/tatoeba/ \
		http://downloads.tatoeba.org/exports/$*.tar.bz2

data/tatoeba/%.csv: data/tatoeba/%.tar.bz2
	tar --directory=data/tatoeba/ --extract --bzip2 --file=$<

download-tatoeba:
	wget --timestamping --directory-prefix=data/tatoeba/ \
		$(subst data/tatoeba/,http://downloads.tatoeba.org/exports/,$(TATOEBA_TARBALLS))
