VERSION = 0.1.3
FILES = cgitb.py date.py roundup-mailgw.py roundup_cgi.py server.py \
	config.py hyperdb.py roundup.py roundupdb.py template.py \
	README CHANGES templates roundup.cgi style.css
PACKAGE = roundup-${VERSION}
PACKAGE_DIR = /tmp/roundup-${VERSION}


release:
	rm -rf /tmp/${PACKAGE}
	mkdir /tmp/${PACKAGE}
	cp -r ${FILES} /tmp/${PACKAGE}
	cp dummy_config.py /tmp/${PACKAGE}
	(cd /tmp; tar zcf ${PACKAGE}.tgz ${PACKAGE})
	mv /tmp/${PACKAGE}.tgz .

clean:
	rm -f *.pyc *.tgz
