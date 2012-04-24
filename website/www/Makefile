TMP  := _tmp
HTML := html

.PHONY: help clean html linkcheck

help:
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  html      to make standalone HTML files"
	@echo "  linkcheck to check all external links for integrity"

clean:
	-rm -rf $(TMP)

docs:
	ln -s ../../doc ./docs

html: docs
	mkdir -p $(TMP)/doctrees $(HTML)
	sphinx-build -b html -d $(TMP)/doctrees . $(HTML)

linkcheck:
	mkdir -p $(TMP)/linkcheck $(TMP)/doctrees
	sphinx-build -b linkcheck -d $(TMP)/doctrees . $(TMP)/linkcheck
	@echo
	@echo "Link check complete; look for any errors in the above output " \
	      "or in .build/linkcheck/output.txt."
