PYTHON = /usr/bin/python2
STXTOHTML = rst2html

SOURCE = announcement.txt customizing.txt developers.txt FAQ.txt features.txt \
    glossary.txt implementation.txt index.txt design.txt \
    installation.txt upgrading.txt user_guide.txt maintenance.txt

COMPILED := $(SOURCE:.txt=.html)

all: ${COMPILED}

%.html: %.txt
	${STXTOHTML} --report=warning -d $< $@

clean:
	rm -f ${COMPILED}
