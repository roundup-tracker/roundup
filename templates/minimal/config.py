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
# $Id: config.py,v 1.4 2004-02-23 05:29:06 richard Exp $

import os

# roundup home is this package's directory
TRACKER_HOME=os.path.split(__file__)[0]

# The SMTP mail host that roundup will use to send mail
MAILHOST = 'localhost'

# If your SMTP mail host requires a username and password for access, then
# specify them here.
# eg. MAILUSER = ('username', 'password')
MAILUSER = ()

# If your SMTP mail host provides or requires TLS (Transport Layer
# Security) then set MAILHOST_TLS = 'yes'
# Optionallly, you may also set MAILHOST_TLS_KEYFILE to the name of a PEM
# formatted file that contains your private key, and MAILHOST_TLS_CERTFILE
# to the name of a PEM formatted certificate chain file.
MAILHOST_TLS = 'no'
MAILHOST_TLS_KEYFILE = ''
MAILHOST_TLS_CERTFILE = ''

# The domain name used for email addresses.
MAIL_DOMAIN = 'your.tracker.email.domain.example'

# This is the directory that the database is going to be stored in
DATABASE = os.path.join(TRACKER_HOME, 'db')

# This is the directory that the HTML templates reside in
TEMPLATES = os.path.join(TRACKER_HOME, 'html')

# A descriptive name for your roundup instance
TRACKER_NAME = 'Roundup issue tracker'

# The email address that mail to roundup should go to
TRACKER_EMAIL = 'issue_tracker@%s'%MAIL_DOMAIN

# The web address that the tracker is viewable at. This will be included in
# information sent to users of the tracker. The URL MUST include the cgi-bin
# part or anything else that is required to get to the home page of the
# tracker. You MUST include a trailing '/' in the URL.
TRACKER_WEB = 'http://tracker.example/cgi-bin/roundup.cgi/bugs/'

# The email address that roundup will complain to if it runs into trouble
ADMIN_EMAIL = 'roundup-admin@%s'%MAIL_DOMAIN

# Additional text to include in the "name" part of the From: address used
# in nosy messages. If the sending user is "Foo Bar", the From: line is
# usually: "Foo Bar" <issue_tracker@tracker.example>
# the EMAIL_FROM_TAG goes inside the "Foo Bar" quotes like so:
#    "Foo Bar EMAIL_FROM_TAG" <issue_tracker@tracker.example>
EMAIL_FROM_TAG = ""

# 
# SECURITY DEFINITIONS
#
# define the Roles that a user gets when they register with the tracker
# these are a comma-separated string of role names (e.g. 'Admin,User')
NEW_WEB_USER_ROLES = 'User'
NEW_EMAIL_USER_ROLES = 'User'

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

# Keep email citations when accepting messages. Setting this to "no" strips
# out "quoted" text from the message. Signatures are also stripped.
EMAIL_KEEP_QUOTED_TEXT = 'yes'      # either 'yes' or 'no'

# Preserve the email body as is - that is, keep the citations _and_
# signatures.
EMAIL_LEAVE_BODY_UNCHANGED = 'no'   # either 'yes' or 'no'

# Default class to use in the mailgw if one isn't supplied in email
# subjects. To disable, comment out the variable below or leave it blank.
# Examples:
MAIL_DEFAULT_CLASS = 'issue'   # use "issue" class by default
#MAIL_DEFAULT_CLASS = ''        # disable (or just comment the var out)

# HTML version to generate. The templates are html4 by default. If you
# wish to make them xhtml, then you'll need to change this var to 'xhtml'
# too so all auto-generated HTML is compliant.
HTML_VERSION = 'html4'         # either 'html4' or 'xhtml'

# Character set to encode email headers with. We use utf-8 by default, as
# it's the most flexible. Some mail readers (eg. Eudora) can't cope with
# that, so you might need to specify a more limited character set (eg.
# 'iso-8859-1'.
EMAIL_CHARSET = 'utf-8'
#EMAIL_CHARSET = 'iso-8859-1'   # use this instead for Eudora users

# vim: set filetype=python ts=4 sw=4 et si
