PYTHON = /usr/bin/python2
STXTOHTML = -c "from docutils.core import publish;publish(writer_name='html')"

SOURCE = announcement.txt customizing.txt developers.txt FAQ.txt features.txt \
    getting_started.txt glossary.txt implementation.txt index.txt \
    installation.txt security.txt upgrading.txt user_guide.txt \
    maintenance.txt

COMPILED := $(SOURCE:.txt=.html)

all: ${COMPILED}

%.html: %.txt
	${PYTHON} ${STXTOHTML} --report=warning -d $< $@

clean:
	rm -f ${COMPILED}
