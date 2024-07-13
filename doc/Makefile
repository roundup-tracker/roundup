all:  man_html tracker_config.txt
	cd ..; ./setup.py build_doc

tracker_config.txt: ../roundup/configuration.py
	# generate a current config file
	python3 ../roundup/scripts/roundup_admin.py \
               genconfig _temp_config.txt

	awk -f format_config.awk _temp_config.txt | \
	    cat -s > tracker_config.txt
	rm -f _temp_config.txt

## generate html versions of man pages for inclusion in documentation
# find all man pages and generate output file paths.
MAN_ROFF=$(wildcard ../share/man/man1/*.1)
MAN_HTML=$(patsubst ../share/man/man1/%.1,html_extra/man_pages/%.1.html,$(MAN_ROFF))

man_html: $(MAN_HTML)

html_extra/man_pages/%.1.html: ../share/man/man1/%.1
	man --html=cat $< > $@
	# set max width for paragraphs
	sed -i '/<style/,/<\/style/s/\(p\s* { \)margin/\1max-width: 65ch; margin/' $@
	#man2html $< > $@

clean:
	rm -f _temp_config.txt tracker_config.txt \
	      html_extra/man_pages/*.1.html
