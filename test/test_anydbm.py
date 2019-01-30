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
from roundup.backends import get_backend

from .db_test_base import DBTest, ROTest, SchemaTest, ClassicInitTest, config
from .db_test_base import HTMLItemTest, SpecialActionTest
from .rest_common import TestCase as RestTestCase

class anydbmOpener:
    module = get_backend('anydbm')

    def nuke_database(self):
        shutil.rmtree(config.DATABASE)


class anydbmDBTest(anydbmOpener, DBTest, unittest.TestCase):
    pass


class anydbmROTest(anydbmOpener, ROTest, unittest.TestCase):
    pass


class anydbmSchemaTest(anydbmOpener, SchemaTest, unittest.TestCase):
    pass


class anydbmClassicInitTest(ClassicInitTest, unittest.TestCase):
    backend = 'anydbm'


class anydbmHTMLItemTest(HTMLItemTest, unittest.TestCase):
    backend = 'anydbm'


from .session_common import SessionTest
class anydbmSessionTest(anydbmOpener, SessionTest, unittest.TestCase):
    pass

class anydbmSpecialActionTestCase(anydbmOpener, SpecialActionTest,
                                  unittest.TestCase):
    backend = 'anydbm'

class anydbmRestTest (RestTestCase, unittest.TestCase):
    backend = 'anydbm'

# vim: set filetype=python ts=4 sw=4 et si
