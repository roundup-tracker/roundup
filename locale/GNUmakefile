# Extract translatable strings from Roundup sources,
# update and compile all existing translations
#
# $Id: GNUmakefile,v 1.6 2004-05-29 04:50:46 a1s Exp $

# tool locations
XPOT ?= xpot
MSGFMT ?= msgfmt
MSGMERGE ?= msgmerge
XGETTEXT ?= xgettext
PYTHON ?= python

TEMPLATE=roundup.pot

PACKAGES=$(shell find ../roundup -name '*.py'|sed -e 's,/[^/]*$$,,'|sort|uniq)
SOURCES=$(PACKAGES:=/*.py)
PO_FILES=$(wildcard *.po)
MO_FILES=$(PO_FILES:.po=.mo)
RUN_PYTHON=PYTHONPATH=../build/lib $(PYTHON) -O

.PHONY: $(TEMPLATE)

all: $(TEMPLATE) $(MO_FILES)

$(TEMPLATE):
	${XPOT} -n -o $@ $(SOURCES)
	${RUN_PYTHON} ../roundup/cgi/TAL/talgettext.py -u $@ \
	  ../templates/classic/html/*.html ../templates/minimal/html/*.html
	${XGETTEXT} -j -w 80 -F \
	  --msgid-bugs-address=roundup-devel@lists.sourceforge.net \
	  --copyright-holder="See Roundup README.txt" \
	  -o $@ $(SOURCES)

%.po: $(TEMPLATE)
	${MSGMERGE} -U --suffix=.bak $@ $<

%.mo: %.po
	${MSGFMT} --statistics -o $@ $<
