XPOT=xpot
PACKAGES=$(shell find ../roundup -type d|grep -v CVS)
VERSION=$(shell cd .. && python -c 'import roundup; print roundup.__version__')

all: messages

messages:
	xpot -p Roundup -v $(VERSION) -o roundup.pot $(PACKAGES:=/*.py)
