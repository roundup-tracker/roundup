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
from roundup.backends import get_backend, have_backend

from db_test_base import DBTest, ROTest, SchemaTest, ClassicInitTest, config
from db_test_base import ConcurrentDBTest, FilterCacheTest

class sqliteOpener:
    if have_backend('sqlite'):
        module = get_backend('sqlite')

    def nuke_database(self):
        shutil.rmtree(config.DATABASE)


class sqliteDBTest(sqliteOpener, DBTest, unittest.TestCase):
    pass


class sqliteROTest(sqliteOpener, ROTest, unittest.TestCase):
    pass


class sqliteSchemaTest(sqliteOpener, SchemaTest, unittest.TestCase):
    pass


class sqliteClassicInitTest(ClassicInitTest, unittest.TestCase):
    backend = 'sqlite'


class sqliteConcurrencyTest(ConcurrentDBTest, unittest.TestCase):
    backend = 'sqlite'


class sqliteFilterCacheTest(sqliteOpener, FilterCacheTest, unittest.TestCase):
    backend = 'sqlite'


from session_common import RDBMSTest
class sqliteSessionTest(sqliteOpener, RDBMSTest, unittest.TestCase):
    pass
