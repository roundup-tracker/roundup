TMP  := _tmp
HTML := html

.PHONY: help clean html linkcheck

help:
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  html      to make standalone HTML files"
	@echo "  linkcheck to check all external links for integrity"

clean:
	-rm -rf $(TMP) $(HTML) docs COPYING.txt

docs:
	ln -s ../../doc ./docs
	ln -s ../../COPYING.txt

# after upgrade to sphinx 1.8.5, search.html is missing load of searchtools.
# fix that in postprocess
html: docs
	mkdir -p $(TMP)/doctrees $(HTML)
	sphinx-build -n -W -b html -d $(TMP)/doctrees . $(HTML)
	grep 'searchtools.js' html/search.html || sed -i -e '/language_data.js/s#</script>#</script>\n    <script type="text/javascript" src="_static/searchtools.js"></script>#' html/search.html

linkcheck:
	mkdir -p $(TMP)/linkcheck $(TMP)/doctrees
	sphinx-build -b linkcheck -d $(TMP)/doctrees . $(TMP)/linkcheck
	@echo
	@echo "Link check complete; look for any errors in the above output " \
	      "or in .build/linkcheck/output.txt."
