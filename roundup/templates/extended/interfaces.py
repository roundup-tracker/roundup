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
# $Id: interfaces.py,v 1.16 2002-01-14 02:20:15 richard Exp $

import instance_config
from roundup import cgi_client, mailgw 

class Client(cgi_client.ExtendedClient): 
    ''' derives basic CGI implementation from the standard module, 
        with any specific extensions 
    ''' 
    pass
 
class MailGW(mailgw.MailGW): 
    ''' derives basic mail gateway implementation from the standard module, 
        with any specific extensions 
    ''' 
    pass

#
# $Log: not supported by cvs2svn $
# Revision 1.15  2002/01/02 02:32:38  richard
# ANONYMOUS_ACCESS -> ANONYMOUS_REGISTER
#
# Revision 1.14  2001/12/20 15:43:01  rochecompaan
# Features added:
#  .  Multilink properties are now displayed as comma separated values in
#     a textbox
#  .  The add user link is now only visible to the admin user
#  .  Modified the mail gateway to reject submissions from unknown
#     addresses if ANONYMOUS_ACCESS is denied
#
# Revision 1.13  2001/11/26 23:00:53  richard
# This config stuff is getting to be a real mess...
#
# Revision 1.12  2001/10/22 03:25:01  richard
# Added configuration for:
#  . anonymous user access and registration (deny/allow)
#  . filter "widget" location on index page (top, bottom, both)
# Updated some documentation.
#
# Revision 1.11  2001/10/09 07:38:58  richard
# Pushed the base code for the extended schema CGI interface back into the
# code cgi_client module so that future updates will be less painful.
# Also removed a debugging print statement from cgi_client.
#
# Revision 1.10  2001/10/05 02:23:24  richard
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
# Revision 1.9  2001/08/07 00:24:43  richard
# stupid typo
#
# Revision 1.8  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.7  2001/08/02 00:43:06  richard
# Even better (more useful) headings
#
# Revision 1.6  2001/08/02 00:36:42  richard
# Made all the user-specific link names the same (My Foo)
#
# Revision 1.5  2001/08/01 05:15:09  richard
# Added "My Issues" and "My Support" to extended template.
#
# Revision 1.4  2001/07/30 08:12:17  richard
# Added time logging and file uploading to the templates.
#
# Revision 1.3  2001/07/30 01:26:59  richard
# Big changes:
#  . split off the support priority into its own class
#  . added "new support, new user" to the page head
#  . fixed the display options for the heading links
#
# Revision 1.2  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.1  2001/07/23 23:16:01  richard
# Split off the interfaces (CGI, mailgw) into a separate file from the DB stuff.
#
#
# vim: set filetype=python ts=4 sw=4 et si
