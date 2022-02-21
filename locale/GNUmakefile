# Extract translatable strings from Roundup sources,
# update and compile all existing translations

# tool locations
XPOT ?= xpot
MSGFMT ?= msgfmt
MSGMERGE ?= msgmerge
XGETTEXT ?= xgettext
PYTHON ?= python3

TEMPLATE=roundup.pot

PACKAGES=$(shell find ../roundup ../share/roundup/templates -name '*.py' \
	 | sed -e 's,/[^/]*$$,,' | sort | uniq)
SOURCES=$(PACKAGES:=/*.py)
PO_FILES=$(wildcard *.po)
MO_FILES=$(PO_FILES:.po=.mo)
PYTHON_BUILD=../build/lib
RUN_PYTHON=PYTHONPATH=$(PYTHON_BUILD) $(PYTHON) -O

all: dist

help:
	@echo "$(MAKE)           - build MO files.  Run this before sdist"
	@echo "$(MAKE) dist      - same as above"
	@echo "$(MAKE) template  - update message template from sources"
	@echo "$(MAKE) diff      - see template differences in vi"
	@echo "$(MAKE) pytest    - create locale files to run pytest"
	@echo "$(MAKE) locale.po - update message file from template"
	@echo "$(MAKE) locale.mo - compile individual message file"
	@echo "$(MAKE) help      - this text"

# This will rebuild all MO files without updating their corresponding PO
# files first.  Run before creating Roundup distribution (hence the name).
# PO files should be updated by their translators only, automatic update
# adds unwanted fuzzy labels.
dist:
	for file in $(PO_FILES); do \
	  ${MSGFMT} -o `basename $$file .po`.mo $$file; \
	done

template:
	test -d $(PYTHON_BUILD) || (echo "Missing build directory $(PYTHON_BUILD). ln -s lib to build library"; exit 1)
	${XPOT} -n -o $(TEMPLATE) $(SOURCES)

	${RUN_PYTHON} ../roundup/cgi/TAL/talgettext.py -u $(TEMPLATE) \
	  ../share/roundup/templates/classic/html/*.html \
	  ../share/roundup/templates/devel/html/*.html \
	  ../share/roundup/templates/minimal/html/*.html \
	  ../share/roundup/templates/responsive/html/*.html
	${XGETTEXT} -j -w 80 -F \
	  --msgid-bugs-address=roundup-devel@lists.sourceforge.net \
	  --copyright-holder="See Roundup README.txt" \
	  -o $(TEMPLATE) $(SOURCES)

pytest local_install: dist
	for file in $(MO_FILES); do \
	   lang=`basename $$file .mo`; \
	   mkdir -p locale/$$lang/LC_MESSAGES; \
	   cp $$file locale/$$lang/LC_MESSAGES/roundup.mo; \
	done

# helps to check template file before check in
diff:
	hg diff roundup.pot|grep -v '^[-+]#'| vi -Rv -

%.po: $(TEMPLATE)
	${MSGMERGE} -U --suffix=.bak $@ $<

%.mo: %.po
	${MSGFMT} --statistics -o $@ $<
