# Extract translatable strings from Roundup sources,
# update and compile all existing translations
#
# $Id: GNUmakefile,v 1.11 2006-11-16 14:14:42 a1s Exp $

# tool locations
XPOT ?= xpot
MSGFMT ?= msgfmt
MSGMERGE ?= msgmerge
XGETTEXT ?= xgettext
PYTHON ?= python

TEMPLATE=roundup.pot

PACKAGES=$(shell find ../roundup ../share/roundup/templates -name '*.py' \
	 | sed -e 's,/[^/]*$$,,' | sort | uniq)
SOURCES=$(PACKAGES:=/*.py)
PO_FILES=$(wildcard *.po)
MO_FILES=$(PO_FILES:.po=.mo)
RUN_PYTHON=PYTHONPATH=../build/lib $(PYTHON) -O

all: dist

help:
	@echo "$(MAKE)           - build MO files.  Run this before sdist"
	@echo "$(MAKE) template  - update message template from sources"
	@echo "$(MAKE) locale.po - update message file from template"
	@echo "$(MAKE) locale.mo - compile individual message file"
	@echo "$(MAKE) help      - this text"\

# This will rebuild all MO files without updating their corresponding PO
# files first.  Run before creating Roundup distribution (hence the name).
# PO files should be updated by their translators only, automatic update
# adds unwanted fuzzy labels.
dist:
	for file in $(PO_FILES); do \
	  ${MSGFMT} -o `basename $$file .po`.mo $$file; \
	done

template:
	${XPOT} -n -o $(TEMPLATE) $(SOURCES)
	${RUN_PYTHON} ../roundup/cgi/TAL/talgettext.py -u $(TEMPLATE) \
	  ../share/roundup/templates/classic/html/*.html \
	  ../share/roundup/templates/minimal/html/*.html
	${XGETTEXT} -j -w 80 -F \
	  --msgid-bugs-address=roundup-devel@lists.sourceforge.net \
	  --copyright-holder="See Roundup README.txt" \
	  -o $(TEMPLATE) $(SOURCES)

# helps to check template file before check in
diff:
	svn diff roundup.pot|grep -v '^[-+]#'|vim -Rv -

%.po: $(TEMPLATE)
	${MSGMERGE} -U --suffix=.bak $@ $<

%.mo: %.po
	${MSGFMT} --statistics -o $@ $<
