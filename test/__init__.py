# $Id: __init__.py,v 1.1 2001-07-27 06:55:07 richard Exp $

import unittest

import test_dates, test_schema, test_db

def go():
    suite = unittest.TestSuite((
        test_dates.suite(),
        test_schema.suite(),
        test_db.suite(),
    ))
    runner = unittest.TextTestRunner()
    runner.run(suite)

#
# $Log: not supported by cvs2svn $
# Revision 1.3  2001/07/25 04:34:31  richard
# Added id and log to tests files...
#
#
