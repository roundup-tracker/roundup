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
# $Id: roundup_admin.py,v 1.3 2002-03-14 23:59:24 richard Exp $

# python version check
from roundup import version_check

# import the admin tool guts and make it go
from roundup.admin import AdminTool
from roundup.i18n import _

import sys

def run():
    tool = AdminTool()
    sys.exit(tool.main())

if __name__ == '__main__':
    run()

#
# $Log: not supported by cvs2svn $
# Revision 1.2  2002/01/29 20:07:15  jhermann
# Conversion to generated script stubs
#
# Revision 1.1  2002/01/29 19:53:08  jhermann
# Moved scripts from top-level dir to roundup.scripts subpackage
#
# Revision 1.61  2002/01/05 02:21:21  richard
# fixes
#
# Revision 1.60  2002/01/05 02:11:22  richard
# I18N'ed roundup admin - and split the code off into a module so it can be used
# elsewhere.
# Big issue with this is the doc strings - that's the help. We're probably going to
# have to switch to not use docstrings, which will suck a little :(
#
# Revision 1.59  2001/12/31 05:20:34  richard
#  . #496360 ] table width does not work
#
# Revision 1.58  2001/12/31 05:12:52  richard
# actually handle the advertised <cr> response to "commit y/N?"
#
# Revision 1.57  2001/12/31 05:12:01  richard
# added some quoting instructions to roundup-admin
#
# Revision 1.56  2001/12/31 05:09:20  richard
# Added better tokenising to roundup-admin - handles spaces and stuff. Can
# use quoting or backslashes. See the roundup.token pydoc.
#
# Revision 1.55  2001/12/17 03:52:47  richard
# Implemented file store rollback. As a bonus, the hyperdb is now capable of
# storing more than one file per node - if a property name is supplied,
# the file is called designator.property.
# I decided not to migrate the existing files stored over to the new naming
# scheme - the FileClass just doesn't specify the property name.
#
# Revision 1.54  2001/12/15 23:09:23  richard
# Some cleanups in roundup-admin, also made it work again...
#
# Revision 1.53  2001/12/13 00:20:00  richard
#  . Centralised the python version check code, bumped version to 2.1.1 (really
#    needs to be 2.1.2, but that isn't released yet :)
#
# Revision 1.52  2001/12/12 21:47:45  richard
#  . Message author's name appears in From: instead of roundup instance name
#    (which still appears in the Reply-To:)
#  . envelope-from is now set to the roundup-admin and not roundup itself so
#    delivery reports aren't sent to roundup (thanks Patrick Ohly)
#
# Revision 1.51  2001/12/10 00:57:38  richard
# From CHANGES:
#  . Added the "display" command to the admin tool - displays a node's values
#  . #489760 ] [issue] only subject
#  . fixed the doc/index.html to include the quoting in the mail alias.
#
# Also:
#  . fixed roundup-admin so it works with transactions
#  . disabled the back_anydbm module if anydbm tries to use dumbdbm
#
# Revision 1.50  2001/12/02 05:06:16  richard
# . We now use weakrefs in the Classes to keep the database reference, so
#   the close() method on the database is no longer needed.
#   I bumped the minimum python requirement up to 2.1 accordingly.
# . #487480 ] roundup-server
# . #487476 ] INSTALL.txt
#
# I also cleaned up the change message / post-edit stuff in the cgi client.
# There's now a clearly marked "TODO: append the change note" where I believe
# the change note should be added there. The "changes" list will obviously
# have to be modified to be a dict of the changes, or somesuch.
#
# More testing needed.
#
# Revision 1.49  2001/12/01 07:17:50  richard
# . We now have basic transaction support! Information is only written to
#   the database when the commit() method is called. Only the anydbm
#   backend is modified in this way - neither of the bsddb backends have been.
#   The mail, admin and cgi interfaces all use commit (except the admin tool
#   doesn't have a commit command, so interactive users can't commit...)
# . Fixed login/registration forwarding the user to the right page (or not,
#   on a failure)
#
# Revision 1.48  2001/11/27 22:32:03  richard
# typo
#
# Revision 1.47  2001/11/26 22:55:56  richard
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
# Revision 1.46  2001/11/21 03:40:54  richard
# more new property handling
#
# Revision 1.45  2001/11/12 22:51:59  jhermann
# Fixed option & associated error handling
#
# Revision 1.44  2001/11/12 22:01:06  richard
# Fixed issues with nosy reaction and author copies.
#
# Revision 1.43  2001/11/09 22:33:28  richard
# More error handling fixes.
#
# Revision 1.42  2001/11/09 10:11:08  richard
#  . roundup-admin now handles all hyperdb exceptions
#
# Revision 1.41  2001/11/09 01:25:40  richard
# Should parse with python 1.5.2 now.
#
# Revision 1.40  2001/11/08 04:42:00  richard
# Expanded the already-abbreviated "initialise" and "specification" commands,
# and added a comment to the command help about the abbreviation.
#
# Revision 1.39  2001/11/08 04:29:59  richard
# roundup-admin now accepts abbreviated commands (eg. l = li = lis = list)
# [thanks Engelbert Gruber for the inspiration]
#
# Revision 1.38  2001/11/05 23:45:40  richard
# Fixed newuser_action so it sets the cookie with the unencrypted password.
# Also made it present nicer error messages (not tracebacks).
#
# Revision 1.37  2001/10/23 01:00:18  richard
# Re-enabled login and registration access after lopping them off via
# disabling access for anonymous users.
# Major re-org of the htmltemplate code, cleaning it up significantly. Fixed
# a couple of bugs while I was there. Probably introduced a couple, but
# things seem to work OK at the moment.
#
# Revision 1.36  2001/10/21 00:45:15  richard
# Added author identification to e-mail messages from roundup.
#
# Revision 1.35  2001/10/20 11:58:48  richard
# Catch errors in login - no username or password supplied.
# Fixed editing of password (Password property type) thanks Roch'e Compaan.
#
# Revision 1.34  2001/10/18 02:16:42  richard
# Oops, committed the admin script with the wierd #! line.
# Also, made the thing into a class to reduce parameter passing.
# Nuked the leading whitespace from the help __doc__ displays too.
#
# Revision 1.33  2001/10/17 23:13:19  richard
# Did a fair bit of work on the admin tool. Now has an extra command "table"
# which displays node information in a tabular format. Also fixed import and
# export so they work. Removed freshen.
# Fixed quopri usage in mailgw from bug reports.
#
# Revision 1.32  2001/10/17 06:57:29  richard
# Interactive startup blurb - need to figure how to get the version in there.
#
# Revision 1.31  2001/10/17 06:17:26  richard
# Now with readline support :)
#
# Revision 1.30  2001/10/17 06:04:00  richard
# Beginnings of an interactive mode for roundup-admin
#
# Revision 1.29  2001/10/16 03:48:01  richard
# admin tool now complains if a "find" is attempted with a non-link property.
#
# Revision 1.28  2001/10/13 00:07:39  richard
# More help in admin tool.
#
# Revision 1.27  2001/10/11 23:43:04  richard
# Implemented the comma-separated printing option in the admin tool.
# Fixed a typo (more of a vim-o actually :) in mailgw.
#
# Revision 1.26  2001/10/11 05:03:51  richard
# Marked the roundup-admin import/export as experimental since they're not fully
# operational.
#
# Revision 1.25  2001/10/10 04:12:32  richard
# The setup.cfg file is just causing pain. Away it goes.
#
# Revision 1.24  2001/10/10 03:54:57  richard
# Added database importing and exporting through CSV files.
# Uses the csv module from object-craft for exporting if it's available.
# Requires the csv module for importing.
#
# Revision 1.23  2001/10/09 23:36:25  richard
# Spit out command help if roundup-admin command doesn't get an argument.
#
# Revision 1.22  2001/10/09 07:25:59  richard
# Added the Password property type. See "pydoc roundup.password" for
# implementation details. Have updated some of the documentation too.
#
# Revision 1.21  2001/10/05 02:23:24  richard
#  . roundup-admin create now prompts for property info if none is supplied
#    on the command-line.
#  . hyperdb Class getprops() method may now return only the mutable
#    properties.
#  . Login now uses cookies, which makes it a whole lot more flexible. We can
#    now support anonymous user access (read-only, unless there's an
#    "anonymous" user, in which case write access is permitted). Login
#    handling has been moved into cgi_client.Client.main()
#  . The "extended" schema is now the default in roundup init.
#  . The schemas have had their page headings modified to cope with the new
#    login handling. Existing installations should copy the interfaces.py
#    file from the roundup lib directory to their instance home.
#  . Incorrectly had a Bizar Software copyright on the cgitb.py module from
#    Ping - has been removed.
#  . Fixed a whole bunch of places in the CGI interface where we should have
#    been returning Not Found instead of throwing an exception.
#  . Fixed a deviation from the spec: trying to modify the 'id' property of
#    an item now throws an exception.
#
# Revision 1.20  2001/10/04 02:12:42  richard
# Added nicer command-line item adding: passing no arguments will enter an
# interactive more which asks for each property in turn. While I was at it, I
# fixed an implementation problem WRT the spec - I wasn't raising a
# ValueError if the key property was missing from a create(). Also added a
# protected=boolean argument to getprops() so we can list only the mutable
# properties (defaults to yes, which lists the immutables).
#
# Revision 1.19  2001/10/01 06:40:43  richard
# made do_get have the args in the correct order
#
# Revision 1.18  2001/09/18 22:58:37  richard
#
# Added some more help to roundu-admin
#
# Revision 1.17  2001/08/28 05:58:33  anthonybaxter
# added missing 'import' statements.
#
# Revision 1.16  2001/08/12 06:32:36  richard
# using isinstance(blah, Foo) now instead of isFooType
#
# Revision 1.15  2001/08/07 00:24:42  richard
# stupid typo
#
# Revision 1.14  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.13  2001/08/05 07:44:13  richard
# Instances are now opened by a special function that generates a unique
# module name for the instances on import time.
#
# Revision 1.12  2001/08/03 01:28:33  richard
# Used the much nicer load_package, pointed out by Steve Majewski.
#
# Revision 1.11  2001/08/03 00:59:34  richard
# Instance import now imports the instance using imp.load_module so that
# we can have instance homes of "roundup" or other existing python package
# names.
#
# Revision 1.10  2001/07/30 08:12:17  richard
# Added time logging and file uploading to the templates.
#
# Revision 1.9  2001/07/30 03:52:55  richard
# init help now lists templates and backends
#
# Revision 1.8  2001/07/30 02:37:07  richard
# Freshen is really broken. Commented out.
#
# Revision 1.7  2001/07/30 01:28:46  richard
# Bugfixes
#
# Revision 1.6  2001/07/30 00:57:51  richard
# Now uses getopt, much improved command-line parsing. Much fuller help. Much
# better internal structure. It's just BETTER. :)
#
# Revision 1.5  2001/07/30 00:04:48  richard
# Made the "init" prompting more friendly.
#
# Revision 1.4  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.3  2001/07/23 08:45:28  richard
# ok, so now "./roundup-admin init" will ask questions in an attempt to get a
# workable instance_home set up :)
# _and_ anydbm has had its first test :)
#
# Revision 1.2  2001/07/23 08:20:44  richard
# Moved over to using marshal in the bsddb and anydbm backends.
# roundup-admin now has a "freshen" command that'll load/save all nodes (not
#  retired - mod hyperdb.Class.list() so it lists retired nodes)
#
# Revision 1.1  2001/07/23 03:46:48  richard
# moving the bin files to facilitate out-of-the-boxness
#
# Revision 1.1  2001/07/22 11:15:45  richard
# More Grande Splite stuff
#
#
# vim: set filetype=python ts=4 sw=4 et si
