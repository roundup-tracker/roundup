#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
# 
# $Id: instance_config.py,v 1.18 2002-05-25 07:16:25 rochecompaan Exp $

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
    MAIL_DOMAIN = 'your.tracker.email.domain.example'

# the next two are only used for the standalone HTTP server.
if not HTTP_HOST:
    HTTP_HOST = ''
if not HTTP_PORT:
    HTTP_PORT = 9080

# This is the directory that the database is going to be stored in
DATABASE = os.path.join(INSTANCE_HOME, 'db')

# This is the directory that the HTML templates reside in
TEMPLATES = os.path.join(INSTANCE_HOME, 'html')

# A descriptive name for your roundup instance
INSTANCE_NAME = 'Roundup issue tracker'

# The email address that mail to roundup should go to
ISSUE_TRACKER_EMAIL = 'issue_tracker@%s'%MAIL_DOMAIN

# The web address that the instance is viewable at
ISSUE_TRACKER_WEB = 'http://your.tracker.url.example/'

# The email address that roundup will complain to if it runs into trouble
ADMIN_EMAIL = 'roundup-admin@%s'%MAIL_DOMAIN

# Somewhere for roundup to log stuff internally sent to stdout or stderr
LOG = os.path.join(INSTANCE_HOME, 'roundup.log')

# Where to place the web filtering HTML on the index page
FILTER_POSITION = 'bottom'          # one of 'top', 'bottom', 'top and bottom'

# Deny or allow anonymous access to the web interface
ANONYMOUS_ACCESS = 'deny'           # either 'deny' or 'allow'

# Deny or allow anonymous users to register through the web interface
ANONYMOUS_REGISTER = 'deny'         # either 'deny' or 'allow'

# Deny or allow anonymous users to register through the mail interface
ANONYMOUS_REGISTER_MAIL = 'deny'    # either 'deny' or 'allow'

# Send nosy messages to the author of the message
MESSAGES_TO_AUTHOR = 'no'           # either 'yes' or 'no'

# Does the author of a message get placed on the nosy list automatically?
# If 'new' is used, then the author will only be added when a message
# creates a new issue. If 'yes', then the author will be added on followups
# too. If 'no', they're never added to the nosy.
ADD_AUTHOR_TO_NOSY = 'new'          # one of 'yes', 'no', 'new'

# Do the recipients (To:, Cc:) of a message get placed on the nosy list?
# If 'new' is used, then the recipients will only be added when a message
# creates a new issue. If 'yes', then the recipients will be added on followups
# too. If 'no', they're never added to the nosy.
ADD_RECIPIENTS_TO_NOSY = 'new'      # either 'yes', 'no', 'new'

# Where to place the email signature
EMAIL_SIGNATURE_POSITION = 'bottom' # one of 'top', 'bottom', 'none'

# Keep email citations
EMAIL_KEEP_QUOTED_TEXT = 'no'       # either 'yes' or 'no'

# Preserve the email body as is
EMAIL_LEAVE_BODY_UNCHANGED = 'no'   # either 'yes' or 'no'

# Default class to use in the mailgw if one isn't supplied in email
# subjects. To disable, comment out the variable below or leave it blank.
# Examples:
MAIL_DEFAULT_CLASS = 'issue'   # use "issue" class by default
#MAIL_DEFAULT_CLASS = ''        # disable (or just comment the var out)

# Define what index links are available in the header, and what their
# labels are. Each key is used to look up one of the index specifications
# below - so 'DEFAULT' will use 'DEFAULT_INDEX'.
# Where the FILTERSPEC has 'assignedto' with a value of None, it will be
# replaced by the id of the logged-in user.
HEADER_INDEX_LINKS = ['DEFAULT', 'UNASSIGNED', 'USER']

# list the classes that users are able to add nodes to
HEADER_ADD_LINKS = ['issue']

# list the classes that users can search
HEADER_SEARCH_LINKS = ['issue']

# list search filters per class
SEARCH_FILTERS = ['ISSUE_FILTER', 'SUPPORT_FILTER']

# Now the DEFAULT display specification. TODO: describe format
DEFAULT_INDEX = {
  'LABEL': 'All Issues',
  'CLASS': 'issue',
  'SORT': ['-activity'],
  'GROUP': ['priority'],
  'FILTER': ['status'],
  'COLUMNS': ['id','activity','title','creator','assignedto'],
  'FILTERSPEC': {
    'status': ['-1', '1', '2', '3', '4', '5', '6', '7'],
  },
}

# The "unsassigned issues" index
UNASSIGNED_INDEX = {
  'LABEL': 'Unassigned Issues',
  'CLASS': 'issue',
  'SORT': ['-activity'],
  'GROUP': ['priority'],
  'FILTER': ['status', 'assignedto'],
  'COLUMNS': ['id','activity','title','creator','status'],
  'FILTERSPEC': {
    'status': ['-1', '1', '2', '3', '4', '5', '6', '7'],
    'assignedto': ['-1'],
  },
}

# The "my issues" index -- note that the user's id will replace the
# 'CURRENT USER' value of the "assignedto" filterspec
USER_INDEX = {
  'LABEL': 'My Issues',
  'CLASS': 'issue',
  'SORT': ['-activity'],
  'GROUP': ['priority'],
  'FILTER': ['status', 'assignedto'],
  'COLUMNS': ['id','activity','title','creator','status'],
  'FILTERSPEC': {
    'status': ['-1', '1', '2', '3', '4', '5', '6', '7'],
    'assignedto': 'CURRENT USER',
  },
}

ISSUE_FILTER = {
  'CLASS': 'issue',
  'FILTER': ['status', 'priority', 'assignedto', 'creator']
}

SUPPORT_FILTER = {
  'CLASS': 'issue',
  'FILTER': ['status', 'priority', 'assignedto', 'creator']
}


#
# $Log: not supported by cvs2svn $
# Revision 1.17  2002/05/22 00:32:33  richard
#  . changed the default message list in issues to display the message body
#  . made backends.__init__ be more specific about which ImportErrors it really
#    wants to ignore
#  . fixed the example addresses in the templates to use correct example domains
#  . cleaned out the template stylesheets, removing a bunch of junk that really
#    wasn't necessary (font specs, styles never used) and added a style for
#    message content
#
# Revision 1.16  2002/05/21 06:05:54  richard
#  . #551483 ] assignedto in Client.make_index_link
#
# Revision 1.15  2002/05/02 07:56:34  richard
# . added option to automatically add the authors and recipients of messages
#   to the nosy lists with the options ADD_AUTHOR_TO_NOSY (default 'new') and
#   ADD_RECIPIENTS_TO_NOSY (default 'new'). These settings emulate the current
#   behaviour. Setting them to 'yes' will add the author/recipients to the nosy
#   on messages that create issues and followup messages.
# . added missing documentation for a few of the config option values
#
# Revision 1.14  2002/04/23 15:46:49  rochecompaan
#  . stripping of the email message body can now be controlled through
#    the config variables EMAIL_KEEP_QUOTED_TEST and
#    EMAIL_LEAVE_BODY_UNCHANGED.
#
# Revision 1.13.2.2  2002/05/02 11:49:19  rochecompaan
# Allow customization of the search filters that should be displayed
# on the search page.
#
# Revision 1.13.2.1  2002/04/20 13:23:33  rochecompaan
# We now have a separate search page for nodes.  Search links for
# different classes can be customized in instance_config similar to
# index links.
#
# Revision 1.13  2002/03/14 23:59:24  richard
#  . #517734 ] web header customisation is obscure
#
# Revision 1.12  2002/02/15 00:13:38  richard
#  . #503204 ] mailgw needs a default class
#     - partially done - the setting of additional properties can wait for a
#       better configuration system.
#
# Revision 1.11  2002/02/14 23:46:02  richard
# . #516883 ] mail interface + ANONYMOUS_REGISTER
#
# Revision 1.10  2001/11/26 22:55:56  richard
# Feature:
#  . Added INSTANCE_NAME to configuration - used in web and email to identify
#    the instance.
#  . Added EMAIL_SIGNATURE_POSITION to indicate where to place the roundup
#    signature info in e-mails.
#  . Some more flexibility in the mail gateway and more error handling.
#  . Login now takes you to the page you back to the were denied access to.
#
# Fixed:
#  . Lots of bugs, thanks Roché and others on the devel mailing list!
#
# Revision 1.9  2001/10/30 00:54:45  richard
# Features:
#  . #467129 ] Lossage when username=e-mail-address
#  . #473123 ] Change message generation for author
#  . MailGW now moves 'resolved' to 'chatting' on receiving e-mail for an issue.
#
# Revision 1.8  2001/10/23 01:00:18  richard
# Re-enabled login and registration access after lopping them off via
# disabling access for anonymous users.
# Major re-org of the htmltemplate code, cleaning it up significantly. Fixed
# a couple of bugs while I was there. Probably introduced a couple, but
# things seem to work OK at the moment.
#
# Revision 1.7  2001/10/22 03:25:01  richard
# Added configuration for:
#  . anonymous user access and registration (deny/allow)
#  . filter "widget" location on index page (top, bottom, both)
# Updated some documentation.
#
# Revision 1.6  2001/10/01 06:10:42  richard
# stop people setting up roundup with our addresses as default - need to
# handle this better in the init
#
# Revision 1.5  2001/08/07 00:24:43  richard
# stupid typo
#
# Revision 1.4  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.3  2001/08/02 06:38:17  richard
# Roundupdb now appends "mailing list" information to its messages which
# include the e-mail address and web interface address. Templates may
# override this in their db classes to include specific information (support
# instructions, etc).
#
# Revision 1.2  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.1  2001/07/23 23:28:43  richard
# Adding the classic template
#
# Revision 1.1  2001/07/23 04:33:21  anthonybaxter
# split __init__.py into 2. dbinit and instance_config.
#
#
# vim: set filetype=python ts=4 sw=4 et si
