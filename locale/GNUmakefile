# Extract translatable strings from Roundup sources,
# update and compile all existing translations
#
# $Id: GNUmakefile,v 1.3 2004-05-19 17:24:52 a1s Exp $

# tool locations
XPOT ?= xpot
MSGFMT ?= msgfmt
MSGMERGE ?= msgmerge
XGETTEXT ?= xgettext

TEMPLATE=roundup.pot

PACKAGES=$(shell find ../roundup -type d|grep -v CVS)
SOURCES=$(PACKAGES:=/*.py)
PO_FILES=$(wildcard *.po)
MO_FILES=$(PO_FILES:.po=.mo)

.PHONY: $(TEMPLATE)

all: $(TEMPLATE) $(MO_FILES)

$(TEMPLATE):
	${XPOT} -n -o $@ $(SOURCES)
	${XGETTEXT} -j -w 80 -F \
	  --msgid-bugs-address=roundup-devel@lists.sourceforge.net \
	  --copyright-holder="See Roundup README.txt" \
	  -o $@ $(SOURCES)

%.po: $(TEMPLATE)
	${MSGMERGE} -U --suffix=.bak $@ $<

%.mo: %.po
	${MSGFMT} --statistics -o $@ $<
