STXTOHTML = rst2html
STXTOHT = rst2ht.py
WEBDIR = ../../htdocs/htdocs/doc-0.8

SOURCE = announcement.txt customizing.txt developers.txt FAQ.txt features.txt \
    glossary.txt implementation.txt index.txt design.txt mysql.txt \
    installation.txt upgrading.txt user_guide.txt admin_guide.txt \
	postgresql.txt tracker_templates.txt whatsnew-0.8.txt

COMPILED := $(SOURCE:.txt=.html)
WEBHT := $(SOURCE:.txt=.ht)

all: ${COMPILED} ${WEBHT}

website: ${WEBHT}
	cp *.ht ${WEBDIR}

%.html: %.txt
	${STXTOHTML} --report=warning -d $< $@

%.ht: %.txt
	${STXTOHT} --report=warning -d $< $@

clean:
	rm -f ${COMPILED}
