# $Id: __init__.py,v 1.4 2001-08-03 07:18:22 richard Exp $

import unittest

import test_dates, test_schema, test_db, test_multipart, test_mailsplit

def go():
    suite = unittest.TestSuite((
        test_dates.suite(),
        test_schema.suite(),
        test_db.suite(),
        test_multipart.suite(),
        test_mailsplit.suite(),
    ))
    runner = unittest.TextTestRunner()
    runner.run(suite)

#
# $Log: not supported by cvs2svn $
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
