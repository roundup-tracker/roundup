Scripts in this directory:

add-issue
 Add a single issue, as specified on the command line, to your tracker. The
 initial message for the issue is taken from standard input.

roundup-reminder
 Generate an email that lists outstanding issues. Send in both plain text
 and HTML formats.

schema_diagram.py
 Generate a schema diagram for a roundup tracker. It generates a 'dot file'
 that is then fed into the 'dot' tool (http://www.graphviz.org) to generate
 a graph.

server-ctl
 Control the roundup-server daemon from the command line with start, stop,
 restart, condstart (conditional start - only if server is stopped) and
 status commands.

