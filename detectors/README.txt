This directory has some detector examples that you can use to get
ideas on implementing your own detectors.

These are provides on an as-is basis. When they were added, they
worked for somebody and were considered a useful example.

The roundup team will attempt to keep them up to date with major
changes as they happen, but there are no guarantees that these will
work out of the box. If you find them out of date and have patches to
make them work against newer versions of roundup, please open an issue
at:

   https://issues.roundup-tracker.org

The current inventory is:

creator_resolution.py - only allow the creator of the issue to resolve it

emailauditor.py - Rename .eml files (from email multi-part bodies) to
                  .mht so they can be downloaded/viewed in Internet Explorer.

irker.py - communicate with irkerd to allow roundtup to send announcements
           to an IRC channel.

newissuecopy.py - notify a team email address (hardcoded in the script)
		  when a new issue arrives.

newitemcopy.py - email the DISPATCHER address when new issues, users,
                 keywords etc. are created. Kind of an expanded version
		 of newissuecopy.
