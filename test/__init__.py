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
# $Id: __init__.py,v 1.14 2002-01-22 00:12:06 richard Exp $

import unittest
import os, tempfile
os.environ['SENDMAILDEBUG'] = tempfile.mktemp()

import test_dates, test_schema, test_db, test_multipart, test_mailsplit
import test_init, test_token, test_mailgw, test_htmltemplate

def go():
    suite = unittest.TestSuite((
#        test_dates.suite(),
#        test_schema.suite(),
#        test_db.suite(),
#        test_init.suite(),
#        test_multipart.suite(),
#        test_mailsplit.suite(),
#        test_mailgw.suite(),
#        test_token.suite(),
        test_htmltemplate.suite(),
    ))
    runner = unittest.TextTestRunner()
    result = runner.run(suite)
    return result.wasSuccessful()

#
# $Log: not supported by cvs2svn $
# Revision 1.13  2002/01/21 11:05:48  richard
# New tests for htmltemplate (well, it's a beginning)
#
# Revision 1.12  2002/01/14 06:53:28  richard
# had commented out some tests
#
# Revision 1.11  2002/01/14 02:20:15  richard
#  . changed all config accesses so they access either the instance or the
#    config attriubute on the db. This means that all config is obtained from
#    instance_config instead of the mish-mash of classes. This will make
#    switching to a ConfigParser setup easier too, I hope.
#
# At a minimum, this makes migration a _little_ easier (a lot easier in the
# 0.5.0 switch, I hope!)
#
# Revision 1.10  2002/01/05 02:09:46  richard
# make setup abort if tests fail
#
# Revision 1.9  2002/01/02 02:31:38  richard
# Sorry for the huge checkin message - I was only intending to implement #496356
# but I found a number of places where things had been broken by transactions:
#  . modified ROUNDUPDBSENDMAILDEBUG to be SENDMAILDEBUG and hold a filename
#    for _all_ roundup-generated smtp messages to be sent to.
#  . the transaction cache had broken the roundupdb.Class set() reactors
#  . newly-created author users in the mailgw weren't being committed to the db
#
# Stuff that made it into CHANGES.txt (ie. the stuff I was actually working
# on when I found that stuff :):
#  . #496356 ] Use threading in messages
#  . detectors were being registered multiple times
#  . added tests for mailgw
#  . much better attaching of erroneous messages in the mail gateway
#
# Revision 1.8  2001/12/31 05:09:20  richard
# Added better tokenising to roundup-admin - handles spaces and stuff. Can
# use quoting or backslashes. See the roundup.token pydoc.
#
# Revision 1.7  2001/08/07 00:24:43  richard
# stupid typo
#
# Revision 1.6  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.5  2001/08/05 07:45:27  richard
# Added tests for instance initialisation
#
# Revision 1.4  2001/08/03 07:18:22  richard
# Implemented correct mail splitting (was taking a shortcut). Added unit
# tests. Also snips signatures now too.
#
# Revision 1.3  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.2  2001/07/28 06:43:02  richard
# Multipart message class has the getPart method now. Added some tests for it.
#
# Revision 1.1  2001/07/27 06:55:07  richard
# moving tests -> test
#
# Revision 1.3  2001/07/25 04:34:31  richard
# Added id and log to tests files...
#
#
# vim: set filetype=python ts=4 sw=4 et si
