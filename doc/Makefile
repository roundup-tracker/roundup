all:  man_html tracker_config.txt
	cd ..; ./setup.py build_doc

tracker_config.txt: ../roundup/configuration.py
	# generate a current config file
	python3 ../roundup/scripts/roundup_admin.py \
               genconfig _temp_config.txt

	## format and add directives to config file
	# 1. delete first 8 lines of comments (1,8d)
	# Some sections have a comment block before the section
	#    [main] Put the comment block with the section marker
	#    after the index/code directives. To do this:
	# 2. Store all comment and blank lines in the hold space
	#    (H).  Delete the current line and continue with the
	#    next line (d).
	# 3. When we see a section marker, append the section
	#    marker to the hold space (H). substitute for the
	#    section marker index and code directives
	#    (s/.../.../) using the section name (\1) for the
	#    index. Print the directives (p). Empty (zero) the
	#    pattern space (z). Pull the hold space to the
	#    pattern space (x) (which also empties the hold space
	#    because of (z). Print the new pattern space
	#    [comments and section marker] (p). Delete the patern
	#    space and process next input line (d).
	# 4. For any other line, append the line to the hold
	#    space (H). Zero out the pattern buffer (z). Swap the
	#    hold space and pattern space [comments and setting
	#    line] (x).
	#
	#    Automatically print the pattern space after the last
	#    command because we are not using 'sed -n'.
	#
	# The last sed command indents every line that is not
	#   empty or does not start with '..' (a directive) with
	#   two spaces.
	# The cat -s squeezes adjacent blank lines to 1 blank
	#   line.
	@sed -e '1,8d' \
	     -e '/^\#\|^$$/{H;d}' \
	     -e '/^\[\([a-z]*\)\]/{H; s/^\[\([a-z]*\)\]/\n.. index:: config.ini; sections \1\n\n.. code:: ini/; p; z; x; p; d}' \
	     -e '/./{H;z;x}' \
	   _temp_config.txt | \
	 sed -e '/^\.\.\|^$$/!s/^/  /' | \
	 cat -s > tracker_config.txt
	rm -f _temp_config.txt

## generate html versions of man pages for inclusion in documentation
# find all man pages and generate output file paths.
MAN_ROFF=$(wildcard ../share/man/man1/*.1)
MAN_HTML=$(patsubst ../share/man/man1/%.1,html_extra/man_pages/%.1.html,$(MAN_ROFF))

man_html: $(MAN_HTML)

html_extra/man_pages/%.1.html: ../share/man/man1/%.1
	man --html=cat $< > $@
	#man2html $< > $@

clean:
	rm -f _temp_config.txt tracker_config.txt \
	      html_extra/man_pages/*.1.html
