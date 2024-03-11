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
RUN_PYTHON=PYTHONPATH=.. $(PYTHON) -O

all: dist

help:
	@echo "$(MAKE)           - build MO files.  Run this before sdist"
	@echo "$(MAKE) dist      - same as above"
	@echo "$(MAKE) template  - update message template from sources"
	@echo "$(MAKE) merge     - merge template into *.po files"
	@echo "$(MAKE) diff      - see template differences in vi"
	@echo "$(MAKE) potest    - check .po files for errors"
	@echo "$(MAKE) pytest    - create locale files to run pytest"
	@echo "$(MAKE) locale.po - update message file from template"
	@echo "$(MAKE) locale.mo - compile individual message file"
	@echo "$(MAKE) help      - this text"
	@echo ""
	@echo "Running make dist is the same as: make template merge dist"

# This will rebuild all MO files without updating their corresponding PO
# files first.  Run before creating Roundup distribution (hence the name).
# PO files should be updated by their translators only, automatic update
# adds unwanted fuzzy labels.
dist: $(MO_FILES)

template: roundup.pot

pytest local_install:
	for file in $(PO_FILES); do \
           ${MSGFMT} -o `basename $$file .po`.mo $$file; \
	done
	for file in $(MO_FILES); do \
	   lang=`basename $$file .mo`; \
	   mkdir -p locale/$$lang/LC_MESSAGES; \
	   cp $$file locale/$$lang/LC_MESSAGES/roundup.mo; \
	done

# helps to check template file before check in
diff:
	hg cat roundup.pot | diff -u -I '^\#: \.\./roundup.*$$' \
	                             -I '^#:\s*:[0-9]*.*$$' \
                                     - roundup.pot || exit 0
merge: $(PO_FILES)

potest:
	 sh -c 'for file in $(PO_FILES); do \
	   ${MSGFMT} -cv --statistics $$file; \
	done' 2>&1 | sort -k 2,2n

%.po: $(TEMPLATE)
	@echo "Rebuild $@"
	@${MSGMERGE} -U --suffix=.bak $@ $<
	@# update Project-Id-Version to match roundup.pot
	@VER="`sed -ne \"/__version__/s/.*'\(.*\)'.*/\1/p\" \
	      ../roundup/__init__.py`"; \
	sed -i -e \
          "s/^\(\"Project-Id-Version: Roundup\).*/\1 $${VER}\\\\n\"/" $@

%.mo: %.po
	${MSGFMT} -o $@ $<

roundup.pot: $(SOURCES) $(TEMPLATES)
	${XPOT} -n -o $(TEMPLATE) $(SOURCES) 2>&1 | sed -e "/: Unexpected in Python source: #64 \`@'/d"

	${RUN_PYTHON} ../roundup/cgi/TAL/talgettext.py -u $(TEMPLATE) \
	  ../share/roundup/templates/classic/html/*.html \
	  ../share/roundup/templates/devel/html/*.html \
	  ../share/roundup/templates/minimal/html/*.html \
	  ../share/roundup/templates/responsive/html/*.html
	VERSION="`${RUN_PYTHON} -c 'from roundup import __version__; \
	                            print(__version__)';`"; \
	${XGETTEXT} -j -w 80 -F \
	  --add-comments=".Hint " \
	  --package-name=Roundup \
	  --package-version=$$VERSION \
	  --msgid-bugs-address=roundup-devel@lists.sourceforge.net \
	  --copyright-holder="See Roundup README.txt" \
	  -o $(TEMPLATE) $(SOURCES)

