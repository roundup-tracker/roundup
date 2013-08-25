Scripts in this directory:

add-issue
 Add a single issue, as specified on the command line, to your tracker. The
 initial message for the issue is taken from standard input.

roundup-reminder
 Generate an email that lists outstanding issues. Send in both plain text
 and HTML formats.

weekly-report
 Generate a simple report outlining the activity in one tracker for the
 most recent week.

schema_diagram.py
 Generate a schema diagram for a roundup tracker. It generates a 'dot file'
 that is then fed into the 'dot' tool (http://www.graphviz.org) to generate
 a graph.

server-ctl
 Control the roundup-server daemon from the command line with start, stop,
 restart, condstart (conditional start - only if server is stopped) and
 status commands.

roundup.rc-debian
 An control script that may be installed in /etc/init.d on Debian systems.
 Offers start, stop and restart commands and integrates with the Debian
 init process.

imapServer.py
 This IMAP server script that runs in the background and checks for new
 email from a variety of mailboxes.

contributors.py
 Analyzes Mercurial log, filters and compiles list of committers with years
 of contribution. Can be useful for updating COPYING.txt
