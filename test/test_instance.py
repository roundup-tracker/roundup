#
# Copyright (C) 2020 John Rouillard
# All rights reserved.
# For license terms see the file COPYING.txt.
#

from __future__ import print_function
import unittest, os, shutil, errno, sys, difflib

from roundup import instance
from roundup.instance import TrackerError

try:
  # python2
  import pathlib2 as pathlib
except ImportError:
  # python3
  import pathlib

from . import db_test_base

class InstanceTest(unittest.TestCase):

    backend = 'anydbm'

    def setUp(self):
        self.dirname = '_test_instance'
        # set up and open a tracker
        self.instance = db_test_base.setupTracker(self.dirname, self.backend)

        # open the database
        self.db = self.instance.open('admin')

        self.db.commit()
        self.db.close()

    def tearDown(self):
        if self.db:
            self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise


    def testOpenOldStyle(self):
        pathlib.Path(os.path.join(self.dirname, "dbinit.py")).touch()
        # no longer support old style tracker configs
        self.assertRaises(TrackerError, instance.open, self.dirname)

