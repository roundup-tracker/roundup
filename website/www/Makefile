TMP  := _tmp
HTML := html

.PHONY: help clean html linkcheck

# from https://www.thapaliya.com/en/writings/well-documented-makefiles/ via
# https://til.jakelazaroff.com/make/list-all-commands-in-a-makefile/
help:
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[.a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Main Command
# after upgrade to sphinx 1.8.5, search.html is missing load of searchtools.
# fix that in postprocess
# also sed index.html to properly format meta og:... entries.
html: doc_links  ## make standalone HTML files (KEEP_HTML=1 speeds build)
	if [ -z "${KEEP_HTML}" ]; then rm -rf html; fi
	rm -f html/robots.txt  # otherwise sphinx errors
	mkdir -p $(TMP)/doctrees $(HTML)
	sphinx-build -n -W -b html -d $(TMP)/doctrees . $(HTML)
        # install searchtools.js into search page.
	grep 'searchtools.js' html/search.html || sed -i -e '/language_data.js/s#</script>#</script>\n    <script type="text/javascript" src="_static/searchtools.js"></script>#' html/search.html
        # sphinx inserts \: for : in meta tags. Get rid of the \ in
        # opengraph tags
	sed -i -e '/<meta/s/og\\:/og:/' \
             -e '/<meta/s/name="og:/property="og:/' html/index.html
	cp robots.txt html/robots.txt
	mkdir -p html/signatures && cp signatures/*.asc html/signatures
	cp --no-clobber -r docs/html_extra/. html/docs/.
	cp htaccess html/.htaccess
	@echo; \
          l=$$(find html -name '*.orig' -o -name '*~' | tee /dev/tty | wc -l);\
         if [ $$l -ne 0 ]; then echo "Garbage files found" && false; fi
	if [ -e templates.zip ]; then cp templates.zip \
                                   html/CVE-2024-39124-templates.zip; fi

##@ Utilities
clean: ## remove all produced files
	-rm -rf $(TMP) $(HTML) docs COPYING.txt templates.zip

linkcheck: ## check external links for existence
	mkdir -p $(TMP)/linkcheck $(TMP)/doctrees
	sphinx-build -b linkcheck -d $(TMP)/doctrees . $(TMP)/linkcheck
	@echo
	@echo "Link check complete; look for any errors in the above output " \
	      "or in .build/linkcheck/output.txt."

# use to distribute template changes (e.g. for security issues)
# separate from releases
templates.zip:  ## package share/roundup/templates into zip file
	rm -f templates.zip
	(cd ../../share/roundup; hg status -A templates | \
           sed -ne '/^[AMC]/s/^..//p' | sort | zip -@ - ) > templates.zip

##@ Sync/Distribution commands
sourceforge_dev_sync:  ## sync html directory to sourceforce /dev_docs subdir
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
              --exclude '.buildinfo' \
              --backup --backup-dir docs_backup-`date --iso-8601=seconds` \
              html/. \
              web.sourceforge.net:/home/project-web/roundup/htdocs/dev_docs/.

sourceforge_prod_sync: ## sync html directory to sourceforce production website
	read -p "sync to production y/N? " resp; echo "$$resp" | grep -i "^y"
	rsync -av --no-times --delete --exclude 'docs_backup*' \
              --backup --backup-dir docs_backup-`date --iso-8601=seconds` \
              html/. \
              web.sourceforge.net:/home/project-web/roundup/htdocs/.

sourceforge_home_sync:  ## sync html directory to sourceforge:~/roundup_docs

	read -p "sync to home y/N? " resp; echo "$$resp" | grep -i "^y"
	rsync -av --no-times --delete --exclude 'docs_backup*' \
              --backup --backup-dir docs_backup-`date --iso-8601=seconds` \
              html/. \
              web.sourceforge.net:roundup_docs/.

##@ Setup
doc_links: docs COPYING.txt ## recreate links to docs not in this tree

docs:
	ln -s ../../doc ./docs

COPYING.txt:
	ln -s ../../COPYING.txt COPYING.txt
