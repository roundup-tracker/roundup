#! /bin/awk

# delete first 8 lines
NR < 9 {next}

# When we see a section [label]:
#  emit section index marker,
#  emit section anchor
#  set up for code formating
#  emit any comments/blank line that are accumulated before the
#     section marker
#  print the indented section marker
#
# zero the accumulator and the variable that prevents large blocks
#   of empty lines.
/^\[([a-z]*)\]/ { match($0, /^\[([a-z]*)\].*/, section_match);
                  section = section_match[1];
                  print("\n\n.. index:: config.ini; sections " section);
                  print(".. _`config-ini-section-" section "`:");
                  print(".. code:: ini\n");
		  if (accumulate) {
		      print("  " accumulate "\n");
		  }
		  print("  " $0);
		  accumulate = "";
		  prev_line_is_blank = 0;
	        }

# if the line is a setting line (even if commented out)
#  print the accumulated comments/blank lines and the setting line
#  zero the accumulator and the variable that prevents blocks of blank lines
# get the next input line
/^#?[a-z0-9_-]* =/ { print accumulate "\n  " $0;
                     accumulate = "";
		     prev_line_is_blank = 0;
		     next;
                   }

# accumulate comment lines and indent them
/^#/ { accumulate = accumulate "\n  " $0; prev_line_is_blank =  0;}

# accumulate a blank line only if the previous line was not blank.
/^$/ { if (! prev_line_is_blank) {accumulate = accumulate $0};
       prev_line_is_blank = 1;
     }
