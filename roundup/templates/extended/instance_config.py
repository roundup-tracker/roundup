# $Id: instance_config.py,v 1.3 2001-08-02 06:38:17 richard Exp $

MAIL_DOMAIN=MAILHOST=HTTP_HOST=None
HTTP_PORT=0

try:
    from localconfig import *
except ImportError:
    localconfig = None

import os

# roundup home is this package's directory
INSTANCE_HOME=os.path.split(__file__)[0]

# The SMTP mail host that roundup will use to send mail
if not MAILHOST:
    MAILHOST = 'localhost'

# The domain name used for email addresses.
if not MAIL_DOMAIN:
    MAIL_DOMAIN = 'bizarsoftware.com.au'

# the next two are only used for the standalone HTTP server.
if not HTTP_HOST:
    HTTP_HOST = ''
if not HTTP_PORT:
    HTTP_PORT = 9080

# This is the directory that the database is going to be stored in
DATABASE = os.path.join(INSTANCE_HOME, 'db')

# This is the directory that the HTML templates reside in
TEMPLATES = os.path.join(INSTANCE_HOME, 'html')

# The email address that mail to roundup should go to
ISSUE_TRACKER_EMAIL = 'issue_tracker@%s'%MAIL_DOMAIN

# The web address that the instance is viewable at
ISSUE_TRACKER_WEB = 'http://www.bizarsoftware.com.au/cgi-bin/roundup.cgi/issues'

# The email address that roundup will complain to if it runs into trouble
ADMIN_EMAIL = 'roundup-admin@%s'%MAIL_DOMAIN

# Somewhere for roundup to log stuff internally sent to stdout or stderr
LOG = os.path.join(INSTANCE_HOME, 'roundup.log')

#
# $Log: not supported by cvs2svn $
# Revision 1.2  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.1  2001/07/23 04:33:21  anthonybaxter
# split __init__.py into 2. dbinit and instance_config.
#
#
# vim: set filetype=python ts=4 sw=4 et si
