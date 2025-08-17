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
TEMPLATES=$(wildcard ../share/roundup/templates/*/html/*.html)
PO_FILES=$(wildcard *.po)
MO_FILES=$(PO_FILES:.po=.mo)
RUN_PYTHON=PYTHONPATH=.. $(PYTHON) -O

##@ default target
all: dist  ## build MO files.  Run this before sdist"

# This will rebuild all MO files without updating their corresponding PO
# files first.  Run before creating Roundup distribution (hence the name).
# PO files should be updated by their translators only, automatic update
# adds unwanted fuzzy labels.
dist: $(MO_FILES) ## same as all target

##@ Update files
template: roundup.pot ## extract messages from source into template

merge: $(PO_FILES) ## merge template updates into *.po files

# do the template file update
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

## QA commands
diff: ## see template file (roundup.pot) differences
	hg cat roundup.pot | diff -u -I '^\#: \.\./roundup.*$$' \
	                             -I '^#:\s*:[0-9]*.*$$' \
                                     - roundup.pot || exit 0

potest:  ## check .po files for errors
	 sh -c 'for file in $(PO_FILES); do \
	   ${MSGFMT} -cv --statistics $$file; \
	done' 2>&1 | sort -k 2,2n


##@ Testing
pytest: local_install  ## create locale files to run pytest
local_install:
	for file in $(PO_FILES); do \
           ${MSGFMT} -o `basename $$file .po`.mo $$file; \
	done
	for file in $(MO_FILES); do \
	   lang=`basename $$file .mo`; \
	   mkdir -p locale/$$lang/LC_MESSAGES; \
	   cp $$file locale/$$lang/LC_MESSAGES/roundup.mo; \
	done

### template rules
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

# from https://www.thapaliya.com/en/writings/well-documented-makefiles/ via
# https://til.jakelazaroff.com/make/list-all-commands-in-a-makefile/
help:   ## this text
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[.a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

	@echo ""
	@printf "  \033[36m%-15s\033[0m %s\n" "<locale>.po" "update message file from template"
	@printf "  \033[36m%-15s\033[0m %s\n" "<locale>.mo" "compile individual message file"
	@echo ""
	@echo "Running 'make' is the same as: make template merge dist"
