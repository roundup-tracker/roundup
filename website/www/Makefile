TMP  := _tmp
HTML := html

.PHONY: help clean html linkcheck

help:
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  html      to make standalone HTML files"
	@echo "  linkcheck to check all external links for integrity"
	@echo "  sourceforge_prod_sync sync html directory to sourceforce"
	@echo "      production website"
	@echo "  sourceforge_dev_sync sync html directory to sourceforce"
	@echo "      /dev_docs subdirectory"
	@echo "  sourceforge_home_sync sync html directory to"
        @echo "      sourceforge:~/roundup_docs"
	@echo "  clean remove all produced files"
clean:
	-rm -rf $(TMP) $(HTML) docs COPYING.txt templates.zip

docs:
	ln -s ../../doc ./docs
	ln -s ../../COPYING.txt

# after upgrade to sphinx 1.8.5, search.html is missing load of searchtools.
# fix that in postprocess
# also sed index.html to properly format meta og:... entries.
html: docs
	rm -rf html
	mkdir -p $(TMP)/doctrees $(HTML)
	sphinx-build -n -W -b html -d $(TMP)/doctrees . $(HTML)
	# install searchtools.js into search page.
	grep 'searchtools.js' html/search.html || sed -i -e '/language_data.js/s#</script>#</script>\n    <script type="text/javascript" src="_static/searchtools.js"></script>#' html/search.html
	# sphinx inserts \: for : in meta tags. Get rid of the \ in
	# opengraph tags
	sed -i -e '/<meta/s/og\\:/og:/' \
             -e '/<meta/s/name="og:/property="og:/' html/index.html
	cp robots.txt html/robots.txt
	mkdir html/signatures && cp signatures/*.asc html/signatures
	cp --no-clobber -r docs/html_extra/. html/docs/.
	cp htaccess html/.htaccess
	@echo; \
          l=$$(find html -name '*.orig' -o -name '*~' | tee /dev/tty | wc -l);\
         if [ $$l -ne 0 ]; then echo "Garbage files found" && false; fi
	if [ -e templates.zip ]; then cp templates.zip \
                                   html/CVE-2024-39124-templates.zip; fi

linkcheck:
	mkdir -p $(TMP)/linkcheck $(TMP)/doctrees
	sphinx-build -b linkcheck -d $(TMP)/doctrees . $(TMP)/linkcheck
	@echo
	@echo "Link check complete; look for any errors in the above output " \
	      "or in .build/linkcheck/output.txt."

templates.zip:
	rm -f templates.zip
	(cd ../../share/roundup; hg status -A templates | \
           sed -ne '/^[AMC]/s/^..//p' | sort | zip -@ - ) > templates.zip

sourceforge_dev_sync:
        # --no-times makes _images/* and other files sync over every time
        # so docs_backup-... is complete with all files and can be served
        # as the docs tree. Without --no-times _static, _images and other
        # directories are missing from the backup directory.
	# Exclude docs_backup so it won't be deleted from sourceforge
	# since:
        #   --delete-exclude
        # IS NOT (and must not be) SET
	read -p "sync to dev_docs y/N? " resp; echo "$$resp" | grep -i "^y"
	rsync -av --no-times --delete --exclude 'docs_backup*' \
              --backup --backup-dir docs_backup-`date --iso-8601=seconds` \
              html/. \
              web.sourceforge.net:/home/project-web/roundup/htdocs/dev_docs/.

sourceforge_prod_sync:
	read -p "sync to production y/N? " resp; echo "$$resp" | grep -i "^y"
	rsync -av --no-times --delete --exclude 'docs_backup*' \
              --backup --backup-dir docs_backup-`date --iso-8601=seconds` \
              html/. \
              web.sourceforge.net:/home/project-web/roundup/htdocs/.

sourceforge_home_sync:
	read -p "sync to home y/N? " resp; echo "$$resp" | grep -i "^y"
	rsync -av --no-times --delete --exclude 'docs_backup*' \
              --backup --backup-dir docs_backup-`date --iso-8601=seconds` \
              html/. \
              web.sourceforge.net:roundup_docs/.
