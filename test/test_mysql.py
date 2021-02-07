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

import unittest, os, shutil, time

import pytest
from roundup.hyperdb import DatabaseError
from roundup.backends import get_backend, have_backend

from .db_test_base import DBTest, ROTest, config, SchemaTest, ClassicInitTest
from .db_test_base import ConcurrentDBTest, HTMLItemTest, FilterCacheTest
from .db_test_base import SpecialActionTest
from .rest_common import TestCase as RestTestCase


class mysqlOpener:
    if have_backend('mysql'):
        module = get_backend('mysql')

    def setUp(self):
        self.module.db_nuke(config)

    def tearDown(self):
        self.db.close()
        self.nuke_database()

    def nuke_database(self):
        self.module.db_nuke(config)


# FIX: workaround for a bug in pytest.mark.skip():
#   https://github.com/pytest-dev/pytest/issues/568
from .pytest_patcher import mark_class

if not have_backend('mysql'):
    skip_mysql = mark_class(pytest.mark.skip(
        reason='Skipping MySQL tests: backend not available'))
else:
    try:
        import MySQLdb
        mysqlOpener.module.db_exists(config)
        skip_mysql = lambda func, *args, **kwargs: func
    except (MySQLdb.MySQLError, DatabaseError) as msg:
        skip_mysql = mark_class(pytest.mark.skip(
            reason='Skipping MySQL tests: %s' % str(msg)))


@skip_mysql
class mysqlDBTest(mysqlOpener, DBTest, unittest.TestCase):
    def setUp(self):
        mysqlOpener.setUp(self)
        DBTest.setUp(self)


@skip_mysql
class mysqlROTest(mysqlOpener, ROTest, unittest.TestCase):
    def setUp(self):
        mysqlOpener.setUp(self)
        ROTest.setUp(self)


@skip_mysql
class mysqlSchemaTest(mysqlOpener, SchemaTest, unittest.TestCase):
    def setUp(self):
        mysqlOpener.setUp(self)
        SchemaTest.setUp(self)


@skip_mysql
class mysqlClassicInitTest(mysqlOpener, ClassicInitTest, unittest.TestCase):
    backend = 'mysql'
    def setUp(self):
        mysqlOpener.setUp(self)
        ClassicInitTest.setUp(self)
    def tearDown(self):
        ClassicInitTest.tearDown(self)
        self.nuke_database()


@skip_mysql
class mysqlConcurrencyTest(mysqlOpener, ConcurrentDBTest, unittest.TestCase):
    backend = 'mysql'
    def setUp(self):
        mysqlOpener.setUp(self)
        ConcurrentDBTest.setUp(self)
    def tearDown(self):
        ConcurrentDBTest.tearDown(self)
        self.nuke_database()


@skip_mysql
class mysqlHTMLItemTest(mysqlOpener, HTMLItemTest, unittest.TestCase):
    backend = 'mysql'
    def setUp(self):
        mysqlOpener.setUp(self)
        HTMLItemTest.setUp(self)
    def tearDown(self):
        HTMLItemTest.tearDown(self)
        self.nuke_database()


@skip_mysql
class mysqlFilterCacheTest(mysqlOpener, FilterCacheTest, unittest.TestCase):
    backend = 'mysql'
    def setUp(self):
        mysqlOpener.setUp(self)
        FilterCacheTest.setUp(self)
    def tearDown(self):
        FilterCacheTest.tearDown(self)
        self.nuke_database()


from .session_common import SessionTest
@skip_mysql
class mysqlSessionTest(mysqlOpener, SessionTest, unittest.TestCase):
    def setUp(self):
        mysqlOpener.setUp(self)
        SessionTest.setUp(self)
    def tearDown(self):
        SessionTest.tearDown(self)
        mysqlOpener.tearDown(self)

@skip_mysql
class mysqlSpecialActionTestCase(mysqlOpener, SpecialActionTest,
                             unittest.TestCase):
    backend = 'mysql'
    def setUp(self):
        mysqlOpener.setUp(self)
        SpecialActionTest.setUp(self)

    def tearDown(self):
        SpecialActionTest.tearDown(self)
        mysqlOpener.tearDown(self)

@skip_mysql
class mysqlRestTest (RestTestCase, unittest.TestCase):
    backend = 'mysql'

# vim: set et sts=4 sw=4 :
