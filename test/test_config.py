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

import unittest
import logging

import os, shutil, errno

import pytest
from roundup import configuration

config = configuration.CoreConfig()
config.DATABASE = "db"
config.RDBMS_NAME = "rounduptest"
config.RDBMS_HOST = "localhost"
config.RDBMS_USER = "rounduptest"
config.RDBMS_PASSWORD = "rounduptest"
config.RDBMS_TEMPLATE = "template0"
# these TRACKER_WEB and MAIL_DOMAIN values are used in mailgw tests
config.MAIL_DOMAIN = "your.tracker.email.domain.example"
config.TRACKER_WEB = "http://tracker.example/cgi-bin/roundup.cgi/bugs/"
# uncomment the following to have excessive debug output from test cases
# FIXME: tracker logging level should be increased by -v arguments
#   to 'run_tests.py' script
#config.LOGGING_FILENAME = "/tmp/logfile"
#config.LOGGING_LEVEL = "DEBUG"
config.init_logging()
config.options['FOO'] = "value"

class ConfigTest(unittest.TestCase):

    def test_badConfigKeyword(self):
        """Run configure tests looking for invalid option name
        """
        self.assertRaises(configuration.InvalidOptionError, config._get_option, "BadOptionName")

    def test_validConfigKeyword(self):
        """Run configure tests looking for invalid option name
        """
        self.assertEqual(config._get_option("FOO"), "value")

    def testTrackerWeb(self):
        config = configuration.CoreConfig()

        self.assertEqual(None,
             config._get_option('TRACKER_WEB').set("http://foo.example/bar/"))
        self.assertEqual(None,
             config._get_option('TRACKER_WEB').set("https://foo.example/bar/"))

        self.assertRaises(configuration.OptionValueError,
             config._get_option('TRACKER_WEB').set, "https://foo.example/bar")

        self.assertRaises(configuration.OptionValueError,
             config._get_option('TRACKER_WEB').set, "htt://foo.example/bar/")

        self.assertRaises(configuration.OptionValueError,
             config._get_option('TRACKER_WEB').set, "htt://foo.example/bar")

        self.assertRaises(configuration.OptionValueError,
             config._get_option('TRACKER_WEB').set, "")

    def testLoginAttemptsMin(self):
        config = configuration.CoreConfig()

        self.assertEqual(None,
                   config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set("0"))
        self.assertEqual(None,
                    config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set("200"))

        self.assertRaises(configuration.OptionValueError,
                   config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set, "fred")

        self.assertRaises(configuration.OptionValueError,
                   config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set, "-1")

        self.assertRaises(configuration.OptionValueError,
                   config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set, "")

    def testTimeZone(self):
        config = configuration.CoreConfig()

        self.assertEqual(None,
                config._get_option('TIMEZONE').set("0"))

        # not a valid timezone
        self.assertRaises(configuration.OptionValueError,
                config._get_option('TIMEZONE').set, "Zot")

        # 25 is not a valid UTC offset: -12 - +14 is range
        # possibly +/- 1 for DST. But roundup.date doesn't
        # constrain to this range.
        #self.assertRaises(configuration.OptionValueError,
        #        config._get_option('TIMEZONE').set, "25")

        try:
            import pytz
            self.assertEqual(None,
                    config._get_option('TIMEZONE').set("UTC"))
            self.assertEqual(None,
                    config._get_option('TIMEZONE').set("America/New_York"))

        except ImportError:
            self.assertRaises(configuration.OptionValueError,
                    config._get_option('TIMEZONE').set, "UTC")
            self.assertRaises(configuration.OptionValueError,
                    config._get_option('TIMEZONE').set, "America/New_York")

    def testWebSecretKey(self):
        config = configuration.CoreConfig()

        self.assertEqual(None,
                config._get_option('WEB_SECRET_KEY').set("skskskd"))

        self.assertRaises(configuration.OptionValueError,
                config._get_option('WEB_SECRET_KEY').set, "")


    def testStaticFiles(self):
        config = configuration.CoreConfig()

        self.assertEqual(None,
                config._get_option('STATIC_FILES').set("foo /tmp/bar"))

        self.assertEqual(config.STATIC_FILES,
                         ["./foo", "/tmp/bar"])

        self.assertEqual(config['STATIC_FILES'],
                         ["./foo", "/tmp/bar"])

    def testIsolationLevel(self):
        config = configuration.CoreConfig()

        self.assertEqual(None,
            config._get_option('RDBMS_ISOLATION_LEVEL').set("read uncommitted"))
        self.assertEqual(None,
            config._get_option('RDBMS_ISOLATION_LEVEL').set("read committed"))
        self.assertEqual(None,
            config._get_option('RDBMS_ISOLATION_LEVEL').set("repeatable read"))


        self.assertRaises(configuration.OptionValueError,
            config._get_option('RDBMS_ISOLATION_LEVEL').set, "not a level")

    def testConfigSave(self):

        config = configuration.CoreConfig()
        # make scratch directory to create files in

        self.startdir = os.getcwd()

        self.dirname = os.getcwd() + '_test_config'
        os.mkdir(self.dirname)

        try:
            os.chdir(self.dirname)
            self.assertFalse(os.access("config.ini", os.F_OK))
            self.assertFalse(os.access("config.bak", os.F_OK))
            config.save()
            config.save() # creates .bak file
            self.assertTrue(os.access("config.ini", os.F_OK))
            self.assertTrue(os.access("config.bak", os.F_OK))

            self.assertFalse(os.access("foo.bar", os.F_OK))
            self.assertFalse(os.access("foo.bak", os.F_OK))
            config.save("foo.bar")
            config.save("foo.bar") # creates .bak file
            self.assertTrue(os.access("foo.bar", os.F_OK))
            self.assertTrue(os.access("foo.bak", os.F_OK))

        finally:
            # cleanup scratch directory and files
            try:
                os.chdir(self.startdir)
                shutil.rmtree(self.dirname)
            except OSError as error:
                if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def testFloatAndInt_with_update_option(self):

       config = configuration.CoreConfig()

       # Update existing IntegerNumberGeqZeroOption to IntegerNumberOption
       config.update_option('WEB_LOGIN_ATTEMPTS_MIN',
                            configuration.IntegerNumberOption,
                            "0", description="new desc")

       # -1 is allowed now that it is an int.
       self.assertEqual(None,
                    config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set("-1"))

       # but can't float this
       self.assertRaises(configuration.OptionValueError,
                    config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set, "2.4")

       # but fred is still an issue
       self.assertRaises(configuration.OptionValueError,
                    config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set, "fred")
       
       # Update existing IntegerNumberOption to FloatNumberOption
       config.update_option('WEB_LOGIN_ATTEMPTS_MIN',
                            configuration.FloatNumberOption,
                            "0.0")

       self.assertEqual(config['WEB_LOGIN_ATTEMPTS_MIN'], -1)

       # can float this
       self.assertEqual(None,
                config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set("3.1415926"))

       # but fred is still an issue
       self.assertRaises(configuration.OptionValueError,
                    config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set, "fred")

       self.assertAlmostEqual(config['WEB_LOGIN_ATTEMPTS_MIN'], 3.1415926,
                              places=6)
