#
# Copyright (C) 2020 John Rouillard
# All rights reserved.
# For license terms see the file COPYING.txt.
#

import unittest, os, shutil, errno, sys, difflib

from pathlib import Path
from textwrap import dedent

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

    def test_registerUtilConflicts(self):
      """Check for registration conflicts in registerUtil and 
         registerUtilMethod.

         Note none of these utilites are useful until the tracker
         gets a Client instance.

         Also this only tests the un-optimized path.
      """

      base_extension = dedent("""\
         def dummy_util_func():
             return "1"

         def dummy_util_method(self):
             return self

         class UtilClass:

            stuff = "stuff"

            def util_instance_method(self):
               return self.stuff

            @classmethod
            def util_classmethod(cls):
               return f"class {self.stuff}"

         def init(instance):
             instance.registerUtil("dummy_util_func", dummy_util_func)
 
             instance.registerUtil("util_instance_method",
                                   UtilClass().util_instance_method)

             instance.registerUtil("util_classmethod",
                                   UtilClass.util_classmethod)

             instance.registerUtilMethod("dummy_util_method",
                                         dummy_util_method)
      """)

      bad_func = dedent("""
         def dummy_util_func():
             return "1"

         def init(instance):
             instance.registerUtil("dummy_util_func", dummy_util_func)
      """)

      bad_instance_method = dedent("""
         class UtilClass:

            stuff = "stuff"

            def util_instance_method(self):
               return self.stuff

            @classmethod
            def util_classmethod(cls):
               return f"class {self.stuff}"

         def init(instance):
             instance.registerUtil("util_instance_method",
                                   UtilClass().util_instance_method)
      """)

      bad_classmethod = dedent("""\
         class UtilClass:

            stuff = "stuff"

            def util_instance_method(self):
               return self.stuff

            @classmethod
            def util_classmethod(cls):
               return f"class {self.stuff}"

         def init(instance):
             instance.registerUtil("util_classmethod",
                                   UtilClass().util_classmethod)
      """)

      bad_util_method = dedent("""\
         def dummy_util_method(self):
             return self

         def init(instance):
             instance.registerUtilMethod("dummy_util_method",
                                         dummy_util_method)
      """)

      fn = Path(self.dirname) / "extensions" / "base_extension.py"
      with fn.open("w") as be:
        be.write(base_extension)

      # ("test name", string to write, [ strings to verify ])
      parameters = [
        ( "bad_func",
          bad_func,
          [
            "'dummy_util_func' already exists",
            "base_extension.py:19",
            str(Path("_test_instance/extensions/bad.py:6"))
          ],
        ),
        ( "bad_instance_method",
          bad_instance_method,
          [
            "'util_instance_method' already exists",
            "base_extension.py:21",
            str(Path("_test_instance/extensions/bad.py:14"))
          ]
        ),
        ( "bad_classmethod",
          bad_classmethod,
          [
            "'util_classmethod' already exists",
            "base_extension.py:24",
            str(Path("_test_instance/extensions/bad.py:13"))
          ]
         ),
        ( "bad_util_method",
          bad_util_method,
          [
            "'dummy_util_method' already exists",
            "base_extension.py:27",
            str(Path("_test_instance/extensions/bad.py:5"))
          ]
         )
      ]

      fn = Path(self.dirname) / "extensions" / "bad.py"

      for t in parameters:
        with self.subTest(name=t[0]):
          with fn.open("w") as be:
            be.write(t[1])

          with self.assertRaises(ValueError) as e:
            tr = self.instance.open('admin')

          for check_valid in t[2]:
              self.assertIn(check_valid, e.exception.args[0])
