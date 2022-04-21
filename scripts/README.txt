Scripts in this directory:

add-issue
 Add a single issue, as specified on the command line, to your tracker. The
 initial message for the issue is taken from standard input.

copy-user.py
 Copy one or more Roundup users from one tracker instance to another. 

dump_dbm_sessions_db.py
 Simple script to dump a session style dbm database e.g. db/otks or
 db/sessions in readable form.
 
imapServer.py
 This IMAP server script that runs in the background and checks for new
 email from a variety of mailboxes.

import_sf.py
 Import tracker data from Sourceforge.NET into a new roundup instance.

roundup-reminder
 Generate an email that lists outstanding issues. Send in both plain text
 and HTML formats.

schema_diagram.py
 Generate a schema diagram for a roundup tracker. It generates a 'dot file'
 that is then fed into the 'dot' tool (http://www.graphviz.org) to generate
 a graph.

schema-dump.py
 Use recently documented XML-RPC API to dump Roundup data schema in
 human readable form.

spam-remover
 Remove file attachment spam from a tracker. (Warning destructive,
 read script well.)

stats.xmlrpc.py
 Script using the xmlrpc interface to retrieve info. Generates report
 on what values are used by the various issues on bugs.python.org.

weekly-report
 Generate a simple report outlining the activity in one tracker for the
 most recent week.

----

server-ctl
 Control the roundup-server daemon from the command line with start, stop,
 restart, condstart (conditional start - only if server is stopped) and
 status commands.

roundup.rc-debian
 An control script that may be installed in /etc/init.d on Debian systems.
 Offers start, stop and restart commands and integrates with the Debian
 init process.


systemd.gunicorn
 A systemd unit file for running roundup under gnuicorn WSGI server.

----

contributors.py
 Analyzes Mercurial log, filters and compiles list of committers with years
 of contribution. Can be useful for updating COPYING.txt

----

Docker
  Directory for docker setup. More info on how to use it is in
  doc/installation.txt.

Docker/Dockerfile - Create roundup docker.

Docker/requirements.txt - Python requirements built into docker.

Docker/roundup-start - Startup script for roundup in docker.

Docker/docker-compose.yml - Manage two docker containers for roundup
      and mysql.
