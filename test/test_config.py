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

import configparser
import errno
import fileinput
import logging
import os
import pytest
import re
import shutil
import sys
import unittest

from os.path import normpath
from textwrap import dedent

from roundup import configuration
from roundup.backends import get_backend, have_backend
from roundup.hyperdb import DatabaseError

from .db_test_base import config

if not have_backend('postgresql'):
    # FIX: workaround for a bug in pytest.mark.skip():
    #   https://github.com/pytest-dev/pytest/issues/568
    from .pytest_patcher import mark_class
    skip_postgresql = mark_class(pytest.mark.skip(
        reason='Skipping PostgreSQL tests: backend not available'))
else:
    try:
        from roundup.backends.back_postgresql import psycopg2, db_command,\
            get_database_schema_names
        db_command(config, 'select 1')
        skip_postgresql = lambda func, *args, **kwargs: func
    except( DatabaseError ) as msg:
        from .pytest_patcher import mark_class
        skip_postgresql = mark_class(pytest.mark.skip(
            reason='Skipping PostgreSQL tests: database not available'))


try:
    import xapian
    skip_xapian = lambda func, *args, **kwargs: func
    from .pytest_patcher import mark_class
    include_no_xapian = mark_class(pytest.mark.skip(
        "Skipping missing Xapian indexer tests: 'xapian' is installed"))
except ImportError:
    # FIX: workaround for a bug in pytest.mark.skip():
    #   https://github.com/pytest-dev/pytest/issues/568
    from .pytest_patcher import mark_class
    skip_xapian = mark_class(pytest.mark.skip(
        "Skipping Xapian indexer tests: 'xapian' not installed"))
    include_no_xapian = lambda func, *args, **kwargs: func


try:
    import redis
    skip_redis = lambda func, *args, **kwargs: func
except ImportError:
    # FIX: workaround for a bug in pytest.mark.skip():
    #   https://github.com/pytest-dev/pytest/issues/568
    from .pytest_patcher import mark_class
    skip_redis = mark_class(pytest.mark.skip(
        "Skipping redis tests: 'redis' not installed"))

_py3 = sys.version_info[0] > 2
if _py3:
    skip_py2 = lambda func, *args, **kwargs: func
else:
    # FIX: workaround for a bug in pytest.mark.skip():
    #   https://github.com/pytest-dev/pytest/issues/568
    from .pytest_patcher import mark_class
    skip_py2 = mark_class(pytest.mark.skip(
        reason='Skipping test under python2.'))


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

# for TrackerConfig test class
from roundup import instance
from . import db_test_base

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

    def testRedis_Url(self):
        config = configuration.CoreConfig()

        with self.assertRaises(configuration.OptionValueError) as cm:
            config._get_option('SESSIONDB_REDIS_URL').set(
                "redis://foo.example/bar?decode_responses=False")
        self.assertIn('decode_responses', cm.exception.__str__())

        config._get_option('SESSIONDB_REDIS_URL').set(
            "redis://localhost:6379/0?health_check_interval=2")

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
            self.assertEqual(None,
                    config._get_option('TIMEZONE').set("EST"))
            self.assertRaises(configuration.OptionValueError,
                    config._get_option('TIMEZONE').set, "Zool/Zot")

        except ImportError:
            # UTC is a known offset of 0 coded into roundup.date
            # so it works even without pytz.
            self.assertEqual(None,
                    config._get_option('TIMEZONE').set("UTC"))
            # same with EST known timeone offset of 5
            self.assertEqual(None,
                    config._get_option('TIMEZONE').set("EST"))
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


        if ("/tmp/bar" == normpath("/tmp/bar/")):
            result_list = ["./foo", "/tmp/bar"]
        else:
            result_list = [".\\foo", "\\tmp\\bar"]
        self.assertEqual(None,
                config._get_option('STATIC_FILES').set("foo /tmp/bar"))
        print(config.STATIC_FILES)
        self.assertEqual(config.STATIC_FILES, result_list)

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

        self.dirname = os.getcwd() + '/_test_config'
        os.mkdir(self.dirname)

        try:
            os.chdir(self.dirname)
            self.assertFalse(os.access("config.ini", os.F_OK))
            self.assertFalse(os.access("config.bak", os.F_OK))
            config.save()
            config.save() # creates .bak file
            self.assertTrue(os.access("config.ini", os.F_OK))
            self.assertTrue(os.access("config.bak", os.F_OK))
            config.save() # trigger delete of old .bak file
            # FIXME: this should test to see if a new .bak
            # was created. For now verify .bak still exists
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

       # test removal of .0 on floats that are integers
       self.assertEqual(None,
                config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set("3.0"))

       self.assertEqual("3", 
            config._get_option('WEB_LOGIN_ATTEMPTS_MIN')._value2str(3.00))

    def testIntegerNumberGtZeroOption(self):

       config = configuration.CoreConfig()

       # Update existing IntegerNumberGeqZeroOption to IntegerNumberOption
       config.update_option('WEB_LOGIN_ATTEMPTS_MIN',
                            configuration.IntegerNumberGtZeroOption,
                            "1", description="new desc")

       self.assertEqual(None,
                    config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set("1"))

       # -1 is not allowed
       self.assertRaises(configuration.OptionValueError,
                    config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set, "-1")

       # but can't float this
       self.assertRaises(configuration.OptionValueError,
                    config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set, "2.4")

       # but can't float this
       self.assertRaises(configuration.OptionValueError,
                    config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set, "0.5")


    def testOriginHeader(self):
        config = configuration.CoreConfig()

        with self.assertRaises(configuration.OptionValueError) as cm:
            config._get_option('WEB_ALLOWED_API_ORIGINS').set("https://foo.edu *")

        config._get_option('WEB_ALLOWED_API_ORIGINS').set("* https://foo.edu HTTP://baR.edu")

        self.assertEqual(config['WEB_ALLOWED_API_ORIGINS'][0], '*')
        self.assertEqual(config['WEB_ALLOWED_API_ORIGINS'][1], 'https://foo.edu')
        self.assertEqual(config['WEB_ALLOWED_API_ORIGINS'][2], 'HTTP://baR.edu')
        


    def testOptionAsString(self):

       config = configuration.CoreConfig()

       config._get_option('WEB_LOGIN_ATTEMPTS_MIN').set("2552")

       v = config._get_option('WEB_LOGIN_ATTEMPTS_MIN').__str__()
       print(v)
       self.assertIn("55", v)

       v = config._get_option('WEB_LOGIN_ATTEMPTS_MIN').__repr__()
       print(v)
       self.assertIn("55", v)

    def testBooleanOption(self):

        config = configuration.CoreConfig()

        with self.assertRaises(configuration.OptionValueError) as cm:
            config._get_option('INSTANT_REGISTRATION').set("3")

        # test multiple boolean representations
        for b in [ "yes", "1", "true", "TRUE", "tRue", "on",
                        "oN", 1, True ]:
            self.assertEqual(None,
                 config._get_option('INSTANT_REGISTRATION').set(b))
            self.assertEqual(1,
                 config._get_option('INSTANT_REGISTRATION').get())

            for b in ["no", "0", "false", "FALSE", "fAlse", "off",
                        "oFf", 0, False]:
                self.assertEqual(None,
                     config._get_option('INSTANT_REGISTRATION').set(b))
            self.assertEqual(0,
                 config._get_option('INSTANT_REGISTRATION').get())

    def testOctalNumberOption(self):

        config = configuration.CoreConfig()

        with self.assertRaises(configuration.OptionValueError) as cm:
            config._get_option('UMASK').set("xyzzy")

        print(type(config._get_option('UMASK')))


@pytest.mark.usefixtures("save_restore_logging")
class TrackerConfig(unittest.TestCase):

    @pytest.fixture(autouse=True)
    def inject_fixtures(self, caplog):
        self._caplog = caplog

    @pytest.fixture(autouse=True)
    def save_restore_logging(self):
        """Save logger state and try to restore it after each test
           has finished.

           The primary test is testDictLoggerConfigViaJson which
           can change the loggers and break tests that depend on caplog
        """
        # Save logger state for root and roundup top level logger
        loggernames = ("", "roundup")

        # The state attributes to save. Lists are shallow copied
        state_to_save = ("filters", "handlers", "level", "propagate")

        logger_state = {}
        for name in loggernames:
            logger_state[name] = {}
            roundup_logger = logging.getLogger(name)

            for i in state_to_save:
                attr = getattr(roundup_logger, i)
                if isinstance(attr, list):
                    logger_state[name][i] = attr.copy()
                else:
                    logger_state[name][i] = getattr(roundup_logger, i)

        # run all class tests here
        yield

        # rip down all the loggers leaving the root logger reporting
        # to stdout.
        # otherwise logger config is leaking to other tests
        roundup_loggers = [logging.getLogger(name) for name in
                           logging.root.manager.loggerDict
                   if name.startswith("roundup")]

        # cribbed from configuration.py:init_loggers
        hdlr = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s %(trace_id)s %(levelname)s %(message)s')
        hdlr.setFormatter(formatter)

        for logger in roundup_loggers:
            # no logging API to remove all existing handlers!?!
            for h in logger.handlers:
                h.close()
                logger.removeHandler(h)
            logger.handlers = [hdlr]
            logger.setLevel("WARNING")
            logger.propagate = True  # important as caplog requires this

        # Restore the info we stored before running tests
        for name in loggernames:
            local_logger = logging.getLogger(name)
            for attr in logger_state[name]:
                setattr(local_logger, attr, logger_state[name][attr])

        # reset logging as well
        from importlib import reload
        logging.shutdown()
        reload(logging)

    def reset_logging(self):
        """https://til.tafkas.net/posts/-resetting-python-logging-before-running-tests/"""
        loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
        loggers.append(logging.getLogger())
        for logger in loggers:
            handlers = logger.handlers[:]
            for handler in handlers:
                logger.removeHandler(handler)
                handler.close()
            logger.setLevel(logging.NOTSET)
            logger.propagate = True
        
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

    def munge_configini(self, mods = None, section=None):
        """ modify config.ini to meet testing requirements

            mods is a list of tuples:
               [ ( "a = ", "b" ), ("c = ", None), ("d = ", "b", "z = ") ]
            Match line with first tuple element e.g. "a = ". Note specify
            trailing "=" and space to delimit keyword and properly format
            replacement line. If there are two elements in the tuple,
            and the first element matches, the line is
            replaced with the concatenation of the first and second elements.
            If second element is None ("" doesn't work), the line will be
            deleted. If there are three elements in the tuple, the line
            is replaced with the contcatentation of the third and second
            elements (used to replace commented out parameters).

            Note if the key/first element of tuple is not unique in
            config.ini, you must set the section to match the bracketed
            section name.
        """

        if mods is None:
            return

        # if section is defined, the tests in the loop will turn
        # it off on [main] if section != '[main]'.
        in_section = True 

        for line in fileinput.input(os.path.join(self.dirname, "config.ini"),
                                    inplace=True):
            if section:
                if line.startswith('['):
                    in_section = False

                if line.startswith(section):
                    in_section = True

            if in_section:
                for rule in mods:
                    if len(rule) == 3:
                        match, value, repl = rule
                    else:
                        match, value = rule
                        repl = None

                    if line.startswith(match):
                        if value is not None:
                            if repl:
                                print(repl + value)
                            else:
                                print(match + value)
                        break
                else:
                    print(line[:-1]) # remove trailing \n
            else:
                print(line[:-1]) # remove trailing \n

    def testNoDBInConfig(self):
        """Arguably this should be tested in test_instance since it is
           triggered by instance.open. But it raises an error in the
           configuration module with a missing required param in
           config.ini.
        """

        # remove the backend key in config.ini
        self.munge_configini(mods=[ ("backend = ", None) ])

        # this should fail as backend isn't defined.
        with self.assertRaises(configuration.OptionUnsetError) as cm:
            instance.open(self.dirname)

        self.assertEqual("RDBMS_BACKEND is not set"
                      " and has no default", cm.exception.__str__())

    def testUnsetMailPassword_with_set_username(self):
        """ Set [mail] username but don't set the 
            [mail] password. Should get an OptionValueError. 
        """
        # SETUP: set mail username
        self.munge_configini(mods=[ ("username = ", "foo"), ],
                             section="[mail]")

        config = configuration.CoreConfig()

        with self.assertRaises(configuration.OptionValueError) as cm:
            config.load(self.dirname)

        print(cm.exception)
        # test repr. The type is right since it passed assertRaises.
        self.assertIn("OptionValueError", repr(cm.exception))
        # look for 'not defined'
        self.assertEqual("not defined", cm.exception.args[1])


    def testUnsetMailPassword_with_unset_username(self):
        """ Set [mail] username but don't set the 
            [mail] password. Should get an OptionValueError. 
        """
        config = configuration.CoreConfig()

        config.load(self.dirname)

        self.assertEqual(config['MAIL_USERNAME'], '')

        with self.assertRaises(configuration.OptionUnsetError) as cm:
            self.assertEqual(config['MAIL_PASSWORD'], 'NO DEFAULT')

    def testSecretMandatory_missing_file(self):

        # SETUP: 
        self.munge_configini(mods=[ ("secret_key = ", "file://secret_key"), ])

        config = configuration.CoreConfig()

        with self.assertRaises(configuration.OptionValueError) as cm:
            config.load(self.dirname)

        print(cm.exception)
        self.assertEqual(cm.exception.args[0].setting, "secret_key")

    def testSecretMandatory_load_from_file(self):

        # SETUP: 
        self.munge_configini(mods=[ ("secret_key = ", "file://secret_key"), ])

        secret = "ASDQWEZXCRFVBGTYHNMJU"
        with open(self.dirname + "/secret_key", "w") as f:
            f.write(secret + "\n")

        config = configuration.CoreConfig()

        config.load(self.dirname)

        self.assertEqual(config['WEB_SECRET_KEY'], secret)


    def testSecretMandatory_load_from_abs_file(self):

        abs_file = "/tmp/secret_key.%s"%os.getpid()

        # SETUP: 
        self.munge_configini(mods=[ ("secret_key = ", "file://%s"%abs_file), ])

        secret = "ASDQWEZXCRFVBGTYHNMJU"
        with open(abs_file, "w") as f:
            f.write(secret + "\n")

        config = configuration.CoreConfig()

        config.load(self.dirname)

        self.assertEqual(config['WEB_SECRET_KEY'], secret)

        os.remove(abs_file)

    def testSecretMandatory_empty_file(self):

        self.munge_configini(mods=[ ("secret_key = ", "file:// secret_key"), ])

        # file with no value just newline.
        with open(self.dirname + "/secret_key", "w") as f:
            f.write("\n")

        config = configuration.CoreConfig()

        with self.assertRaises(configuration.OptionValueError) as cm:
            config.load(self.dirname)

        print(cm.exception.args)
        self.assertEqual(cm.exception.args[2],"Value must not be empty.")

    def testNullableSecret_empty_file(self):

        self.munge_configini(mods=[ ("password = ", "file://db_password"), ])

        # file with no value just newline.
        with open(self.dirname + "/db_password", "w") as f:
            f.write("\n")

        config = configuration.CoreConfig()

        config.load(self.dirname)

        v = config['RDBMS_PASSWORD']

        self.assertEqual(v, None)

    def testNullableSecret_with_file_value(self):

        self.munge_configini(mods=[ ("password = ", "file://db_password"), ])

        # file with no value just newline.
        with open(self.dirname + "/db_password", "w") as f:
            f.write("test\n")

        config = configuration.CoreConfig()

        config.load(self.dirname)

        v = config['RDBMS_PASSWORD']

        self.assertEqual(v, "test")

    def testNullableSecret_with_value(self):

        self.munge_configini(mods=[ ("password = ", "test"), ])

        config = configuration.CoreConfig()

        config.load(self.dirname)

        v = config['RDBMS_PASSWORD']

        self.assertEqual(v, "test")

    def testListSecret_for_jwt_invalid_secret(self):
        """A jwt_secret is made of ',' separated strings.
           If the first string is < 32 characters (like the default
           value of disabled) then jwt is disabled and no harm done.
           If any other secrets are <32 characters we raise a red flag
           on startup to prevent them from being used.
        """
        self.munge_configini(mods=[ ("jwt_secret = ", "disable, test"), ])

        config = configuration.CoreConfig()

        with self.assertRaises(configuration.OptionValueError) as cm:
            config.load(self.dirname)

        print(cm.exception.args)
        self.assertEqual(
            cm.exception.args[2],
            "One or more secrets less then 32 characters in length\nfound: test")

    def testSetMailPassword_with_set_username(self):
        """ Set [mail] username and set the password.
            Should have both values set.
        """
        # SETUP: set mail username
        self.munge_configini(mods=[ ("username = ", "foo"),
                                    ("#password = ", "passwordfoo",
                                    "password = ") ],
                             section="[mail]")

        config = configuration.CoreConfig()

        config.load(self.dirname)

        self.assertEqual(config['MAIL_USERNAME'], 'foo')
        self.assertEqual(config['MAIL_PASSWORD'], 'passwordfoo')

    def testSetMailPassword_from_file(self):
        """ Set [mail] username and set the password.
            Should have both values set.
        """
        # SETUP: set mail username
        self.munge_configini(mods=[ ("username = ", "foo"),
                                    ("#password = ", "file://password",
                                     "password = ") ],
                             section="[mail]")
        with open(self.dirname + "/password", "w") as f:
            f.write("passwordfoo\n")

        config = configuration.CoreConfig()

        config.load(self.dirname)

        self.assertEqual(config['MAIL_USERNAME'], 'foo')
        self.assertEqual(config['MAIL_PASSWORD'], 'passwordfoo')

    @skip_xapian
    def testInvalidIndexerLanguage_w_empty(self):
        """ make sure we have a reasonable error message if
            invalid indexer language is specified. This uses
            default search path for indexers.
        """

        # SETUP: set indexer_language value to an invalid value.
        self.munge_configini(mods=[ ("indexer = ", ""),
            ("indexer_language = ", "NO_LANG") ])

        config = configuration.CoreConfig()

        with self.assertRaises(configuration.OptionValueError) as cm:
            config.load(self.dirname)

        print(cm.exception)
        # test repr. The type is right since it passed assertRaises.
        self.assertIn("OptionValueError", repr(cm.exception))
        # look for failing language
        self.assertIn("NO_LANG", cm.exception.args[1])
        # look for supported language
        self.assertIn("english", cm.exception.args[2])

    @include_no_xapian
    def testInvalidIndexerLanguage_w_empty_no_xapian(self):
        """ Test case for empty indexer if xapian really isn't installed

            This should behave like testInvalidIndexerLanguage_xapian_missing
            but without all the sys.modules mangling.
        """
        print("Testing when xapian is not installed")

        # SETUP: set indexer_language value to an invalid value.
        self.munge_configini(mods=[ ("indexer = ", ""),
            ("indexer_language = ", "NO_LANG") ])

        config = configuration.CoreConfig()

        config.load(self.dirname)

        self.assertEqual(config['INDEXER_LANGUAGE'], 'NO_LANG')

    def testInvalidIndexerLanguage_xapian_missing(self):
        """Using default path for indexers, make import of xapian
           fail and prevent exception from happening even though
           the indexer_language would be invalid for xapian.
        """

        print("Testing xapian not loadable")

        # SETUP: same as testInvalidIndexerLanguage_w_empty
        self.munge_configini(mods=[ ("indexer = ", ""),
            ("indexer_language = ", "NO_LANG") ])

        import sys
        # Set module to Non to prevent xapian from loading
        sys.modules['xapian'] = None
        config.load(self.dirname)

        # need to delete both to make python2 not error finding _xapian
        del(sys.modules['xapian'])
        if 'xapian._xapian' in sys.modules:
            del(sys.modules['xapian._xapian'])

        self.assertEqual(config['INDEXER_LANGUAGE'], 'NO_LANG')

        # do a reset here to test reset rather than wasting cycles
        # to do setup in a different test
        config.reset()
        self.assertEqual(config['INDEXER_LANGUAGE'], 'english')

    def testInvalidIndexerLanguage_w_native(self):
        """indexer_language is invalid but indexer is not "" or xapian
           Config load should succeed without exception.
        """

        print("Testing indexer = native")

        self.munge_configini(mods = [ ("indexer = ", "native"),
            ("indexer_language = ", "NO_LANG") ])

        config.load(self.dirname)

        self.assertEqual(config['HTML_VERSION'], 'html4')
        self.assertEqual(config['INDEXER_LANGUAGE'], 'NO_LANG')

    @skip_xapian
    def testInvalidIndexerLanguage_w_xapian(self):
        """ Use explicit xapian indexer. Verify exception is
            generated.
        """

        print("Testing explicit xapian")

        self.munge_configini(mods=[ ("indexer = ", "xapian"),
            ("indexer_language = ", "NO_LANG") ])

        with self.assertRaises(configuration.OptionValueError) as cm:
            config.load(self.dirname)
        # don't test exception content. Done in
        # testInvalidIndexerLanguage_w_empty
        # if exception not generated assertRaises
        # will generate failure.

    def testInvalidIndexerLanguage_w_native_fts(self):
        """ Use explicit native-fts indexer. Verify exception is
            generated.
        """

        self.munge_configini(mods=[ ("indexer = ", "native-fts"),
            ("indexer_language = ", "NO_LANG") ])

        with self.assertRaises(configuration.OptionValueError) as cm:
            config.load(self.dirname)

        # test repr. The type is right since it passed assertRaises.
        self.assertIn("OptionValueError", repr(cm.exception))
        # look for failing language
        self.assertIn("NO_LANG", cm.exception.args[1])
        # look for supported language
        self.assertIn("basque", cm.exception.args[2])

    @skip_redis
    def testLoadSessionDbRedisCompatible(self):
        """ run load to validate config """

        config = configuration.CoreConfig()

        # compatible pair
        config.RDBMS_BACKEND = "sqlite"
        config.SESSIONDB_BACKEND = "redis"

        config.validator(config.options)

        # compatible pair
        config.RDBMS_BACKEND = "anydbm"
        config.SESSIONDB_BACKEND = "redis"

        config.validator(config.options)

    @skip_redis
    @skip_postgresql
    def testLoadSessionDbRedisIncompatible(self):
        """ run load to validate config """
        # incompatible pair
        config.RDBMS_BACKEND = "postgresql"
        config.SESSIONDB_BACKEND = "redis"

        with self.assertRaises(configuration.OptionValueError) as cm:
            config.validator(config.options)

        self.assertIn(" db type: redis with postgresql",
                      cm.exception.__str__())

    def testLoadSessionDb(self):
        """ run load to validate config """

        config = configuration.CoreConfig()

        # incompatible pair
        config.RDBMS_BACKEND = "sqlite"
        config.SESSIONDB_BACKEND = "foo"

        with self.assertRaises(configuration.OptionValueError) as cm:
            config.validator(config.options)

        self.assertIn(" db type: foo with sqlite",
                      cm.exception.__str__())

        # compatible pair
        config.RDBMS_BACKEND = "sqlite"
        config.SESSIONDB_BACKEND = ""

        config.validator(config.options) # any exception will fail test

        config.RDBMS_BACKEND = "sqlite"
        config.SESSIONDB_BACKEND = "anydbm"

        config.validator(config.options) # any exception will fail test

        config.RDBMS_BACKEND = "anydbm"
        config.SESSIONDB_BACKEND = "redis"

        # make it looks like redis is not available
        try:
            del(sys.modules['redis'])
        except KeyError:
            # redis is not available anyway.
            pass

        sys.modules['redis'] = None
        with self.assertRaises(configuration.OptionValueError) as cm:
            config.validator(config.options)
        del(sys.modules['redis'])

        self.assertIn("Unable to load redis module",
                      cm.exception.__str__())

    def testLoadConfig(self):
        """ run load to validate config """

        config = configuration.CoreConfig()
        
        config.load(self.dirname)

        # test various ways of accessing config data
        with self.assertRaises(configuration.InvalidOptionError) as cm:
            # using lower case name fails
            c = config['indexer_language']
        print(cm.exception)
        self.assertIn("indexer_language", repr(cm.exception))

        # uppercase name passes as does tuple index for setting in main
        self.assertEqual(config['HTML_VERSION'], 'html4')
        self.assertEqual(config[('main', 'html_version')], 'html4')

        # uppercase name passes as does tuple index for setting in web
        self.assertEqual(config['WEB_COOKIE_TAKES_PRECEDENCE'], 0)
        self.assertEqual(config[('web','cookie_takes_precedence')], 0)


    def testLoadConfigNoConfig(self):
        """ run load on a directory missing config.ini """

        c = os.path.join(self.dirname, configuration.Config.INI_FILE)
        if os.path.exists(c):
            os.remove(c)
        else:
            self.assertFalse("setup failed missing config.ini")

        config = configuration.CoreConfig()
        
        with self.assertRaises(configuration.NoConfigError) as cm:
            config.load(self.dirname)

        print(cm.exception)
        self.assertEqual(cm.exception.args[0], self.dirname)

    def testFormattedLogging(self):
        """Depends on using default logging format with %(trace_id)"""

        def find_file_occurances(string):
            return len(re.findall(r'\bFile\b', string))

        config = configuration.CoreConfig(settings={"LOGGING_LEVEL": "DEBUG"})

        # format the record and verify the logformat/trace_id.
        config._logging_test(None, msg="message")
        tuple = self._caplog.record_tuples[0]
        self.assertEqual(tuple[1], 20)
        self.assertEqual("message", tuple[2])
        logger = logging.getLogger('roundup')
        hdlr = logger.handlers[0]
        log = hdlr.format(self._caplog.records[0])
        # verify that %(trace_id) was set and substituted
        # Note: trace_id is not initialized in this test case
        log_parts = log.split()
        # testing len(shorten_int_uuid(uuid.uuid4().int))
        # for 20000 tests gives range [19,22]
        self.assertRegex(log_parts[2], r'^[A-Za-z0-9]{19,22}')
        self._caplog.clear()

        # the rest check various values of sinfo and msg formating.
        
        # sinfo = 1 - one line of stack starting with log call
        config._logging_test(1)
        tuple = self._caplog.record_tuples[0]
        self.assertEqual(tuple[1], 20)
        self.assertIn("test a_var\n  File", tuple[2])
        self.assertIn("in _logging_test", tuple[2])
        self.assertIn("logger.info(msg, extra=", tuple[2])
        self.assertEqual(find_file_occurances(tuple[2]), 1)
        self._caplog.clear()
        
        # sinfo = None - 5 lines of stack starting with log call
        config._logging_test(None)
        tuple = self._caplog.record_tuples[0]
        self.assertEqual(tuple[1], 20)
        self.assertIn("test a_var\n  File", tuple[2])
        self.assertIn("in _logging_test", tuple[2])
        self.assertIn("logger.info(msg, extra=", tuple[2])
        self.assertEqual(find_file_occurances(tuple[2]), 5)
        self._caplog.clear()

        # sinfo = 0 - whole stack starting with log call
        config._logging_test(0)
        tuple = self._caplog.record_tuples[0]
        self.assertEqual(tuple[1], 20)
        self.assertIn("test a_var\n  File", tuple[2])
        self.assertIn("in _logging_test", tuple[2])
        self.assertIn("logger.info(msg, extra=", tuple[2])
        # A file in 'pytest' directory should be at the top of stack.
        self.assertIn("pytest", tuple[2])
        # no idea how deep the actual stack is, could change with python
        # versions, but 3.12 is 33 so ....
        self.assertTrue(find_file_occurances(tuple[2]) > 10)
        self._caplog.clear()

        # sinfo = -1 - one line of stack starting with extract_stack()
        config._logging_test(-1)
        tuple = self._caplog.record_tuples[0]
        self.assertEqual(tuple[1], 20)
        self.assertIn("test a_var\n  File", tuple[2])
        # The call to extract_stack should be included as the frame
        # at bottom of stack.
        self.assertIn("extract_stack()", tuple[2])
        # only one frame included
        self.assertEqual(find_file_occurances(tuple[2]), 1)
        self._caplog.clear()

        # sinfo = 1000 - whole stack starting with log call 1000>stack size
        config._logging_test(1000)
        tuple = self._caplog.record_tuples[0]
        self.assertEqual(tuple[1], 20)
        self.assertIn("test a_var\n  File", tuple[2])
        self.assertIn("in _logging_test", tuple[2])
        self.assertIn("logger.info(msg, extra=", tuple[2])
        # A file in 'pytest' directory should be at the top of stack.
        self.assertIn("pytest", tuple[2])
        # no idea how deep the actual stack is, could change with python
        # versions, but 3.12 is 33 so ....
        self.assertTrue(find_file_occurances(tuple[2]) > 10)
        self._caplog.clear()

        # sinfo = -1000 - whole stack starting with extract_stack
        config._logging_test(-1000)
        tuple = self._caplog.record_tuples[0]
        self.assertEqual(tuple[1], 20)
        self.assertIn("test a_var\n  File", tuple[2])
        self.assertIn("in _logging_test", tuple[2])
        self.assertIn("logger.info(msg, extra=", tuple[2])
        # The call to extract_stack should be included as the frame
        # at bottom of stack.
        self.assertIn("extract_stack()", tuple[2])
        # A file in 'pytest' directory should be at the top of stack.
        # no idea how deep the actual stack is, could change with python
        # versions, but 3.12 is 33 so ....
        self.assertTrue(find_file_occurances(tuple[2]) > 10)
        self.assertIn("pytest", tuple[2])
        self._caplog.clear()

        # pass args and compatible message
        config._logging_test(None, args=(1,2,3),
                             msg="one: %s, two: %s, three: %s"
                             )
        tuple = self._caplog.record_tuples[0]
        self.assertEqual(tuple[1], 20)
        self.assertEqual('one: 1, two: 2, three: 3', tuple[2])
        self._caplog.clear()

        # error case for incorrect placeholder
        config._logging_test(None, msg="%(a)")
        tuple = self._caplog.record_tuples[0]
        self.assertEqual(tuple[1], 20)
        self.assertEqual("%(a)", tuple[2])
        self._caplog.clear()

        # error case for incompatible format record is the first argument
        # and it can't be turned into floating point.
        config._logging_test(None, msg="%f")
        tuple = self._caplog.record_tuples[0]
        self.assertEqual(tuple[1], 20)
        self.assertEqual("%f", tuple[2])
        self._caplog.clear()
        
        
    def testXhtmlRaisesOptionError(self):
        self.munge_configini(mods=[ ("html_version = ", "xhtml") ])

        config = configuration.CoreConfig()

        # verify config is initalized to defaults
        self.assertEqual(config['HTML_VERSION'], 'html4')


        with self.assertRaises(configuration.OptionValueError) as cm:
            # load config
            config.load(self.dirname)

        print(cm.exception)
        self.assertEqual(str(cm.exception),
                         "Invalid value for HTML_VERSION: 'xhtml'\n"
                         "Allowed values: html4")

    def testCopyConfig(self):

        self.munge_configini(mods=[ ("static_files = ", "html2") ])

        config = configuration.CoreConfig()

        # verify config is initalized to defaults
        self.assertEqual(config['STATIC_FILES'], None)

        # load config
        STATIC_FILES = os.path.join(self.dirname, "html2")
        config.load(self.dirname)
        self.assertEqual(config['STATIC_FILES'], [ STATIC_FILES ])

        # copy config
        config_copy = config.copy()

        # this should work
        self.assertEqual(config_copy['STATIC_FILES'], [STATIC_FILES])

    @skip_py2
    def testConfigValueInterpolateError(self):
        ''' error is not raised using ConfigParser under Python 2.
            Unknown cause, so skip it if running python 2.
        '''

        self.munge_configini(mods=[ ("admin_email = ", "a bare % is invalid") ])

        config = configuration.CoreConfig()

        # load config generates:
        '''
E           roundup.configuration.ParsingOptionError: Error in _test_instance/config.ini with section [main] at option admin_email: '%' must be followed by '%' or '(', found: '% is invalid'
        '''

        with self.assertRaises(configuration.ParsingOptionError) as cm:
            config.load(self.dirname)

        print(cm.exception)
        self.assertIn("'%' must be followed by '%' or '(', found: '% is invalid'", cm.exception.args[0])
        self.assertIn(normpath("_test_instance/config.ini") + " with section [main] at option admin_email", cm.exception.args[0])


        from roundup.admin import AdminTool
        from .test_admin import captured_output

        admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'get', 'tile', 'issue1']
            ret = admin.main()

        expected_err = ("Error in " +
                        normpath("_test_instance/config.ini") +
                        " with section [main] at option admin_email: '%' "
                        "must be followed by '%' or '(', found: "
                        "'% is invalid'")

        self.assertEqual(ret, 1)
        out = out.getvalue().strip()
        self.assertEqual(out, expected_err)

    def testInvalidIndexerValue(self):
        """ Mistype native indexer. Verify exception is
            generated.
        """

        print("Testing indexer nati")

        self.munge_configini(mods=[ ("indexer = ", "nati") ])

        with self.assertRaises(configuration.OptionValueError) as cm:
            config.load(self.dirname)

        self.assertIn("OptionValueError", repr(cm.exception))
        # look for failing value
        self.assertEqual("nati", cm.exception.args[1])
        # look for supported values
        self.assertIn("'whoosh'", cm.exception.args[2])

        # verify that args show up in string representaton
        string_rep = cm.exception.__str__()
        print(string_rep)
        self.assertIn("nati", string_rep)
        self.assertIn("'whoosh'", string_rep)

    def testLoggerFormat(self):
        config = configuration.CoreConfig()

        # verify config is initalized to defaults
        self.assertEqual(config['LOGGING_FORMAT'],
                         '%(asctime)s %(trace_id)s %(levelname)s %(message)s')

        # load config
        config.load(self.dirname)
        self.assertEqual(config['LOGGING_FORMAT'],
                         '%(asctime)s %(trace_id)s %(levelname)s %(message)s')

        # break config using an incomplete format specifier (no trailing 's')
        self.munge_configini(mods=[ ("format = ", "%%(asctime)s %%(trace_id)s %%(levelname) %%(message)s") ], section="[logging]")

        # load config
        with self.assertRaises(configuration.OptionValueError) as cm:
            config.load(self.dirname)
            
        self.assertIn('Unrecognized use of %(...) in:   %(levelname)',
                      cm.exception.args[2])

        # break config by not doubling % sign to quote it from configparser
        self.munge_configini(mods=[ ("format = ", "%(asctime)s %%(trace_id)s %%(levelname) %%(message)s") ], section="[logging]")

        with self.assertRaises(
                configuration.ParsingOptionError) as cm:
            config.load(self.dirname)

        ini_path = os.path.join(self.dirname, "config.ini")
        self.assertEqual(cm.exception.args[0],(
                         f"Error in {ini_path} with section "
                         "[logging] at option format: Bad value substitution: "
                         "option 'format' in section 'logging' contains an "
                         "interpolation key 'asctime' which is not a valid "
                         "option name. Raw value: '%(asctime)s %%(trace_id)s "
                         "%%(levelname) %%(message)s'"))

    def testDictLoggerConfigViaJson(self):

        # good base test case
        config1 = dedent("""
           {
              "version": 1,   // only supported version
              "disable_existing_loggers": false,      // keep the wsgi loggers

              "formatters": {
                // standard Roundup formatter including context id.
                  "standard": {
                    "format": "%(asctime)s %(levelname)s %(name)s:%(module)s %(msg)s"
                },
                // used for waitress wsgi server to produce httpd style logs
                "http": {
                  "format": "%(message)s"
                }
              },
              "handlers": {
                // create an access.log style http log file
                "access": {
                  "level": "INFO",
                  "formatter": "http",
                  "class": "logging.FileHandler",
                  "filename": "_test_instance/access.log"
                },
                // logging for roundup.* loggers
                "roundup": {
                  "level": "DEBUG",
                  "formatter": "standard",
                  "class": "logging.FileHandler",
                  "filename": "_test_instance/roundup.log"
                },
                // print to stdout - fall through for other logging
                "default": {
                  "level": "DEBUG",
                  "formatter": "standard",
                  "class": "logging.StreamHandler",
                  "stream": "ext://sys.stdout"
                }
            },
              "loggers": {
                "": {
                  "handlers": [
                    "default"     // used by wsgi/usgi
                  ],
                  "level": "DEBUG",
                  "propagate": false
                },
                // used by roundup.* loggers
                "roundup": {
                  "handlers": [
                    "roundup"
                  ],
                  "level": "DEBUG",
                  "propagate": false   // note pytest testing with caplog requires
                                       // this to be true
                },
                "roundup.hyperdb": {
                  "handlers": [
                    "roundup"
                  ],
                  "level": "INFO",    // can be a little noisy INFO for production
                  "propagate": false
                },
               "roundup.wsgi": {    // using the waitress framework
                  "handlers": [
                    "roundup"
                  ],
                  "level": "DEBUG",
                  "propagate": false
                },
               "roundup.wsgi.translogger": {   // httpd style logging
                  "handlers": [
                    "access"
                  ],
                  "level": "DEBUG",
                  "propagate": false
                },
               "root": {
                  "handlers": [
                    "default"
                  ],
                  "level": "DEBUG",
                  "propagate": false
                }
              }
            }
        """)

        log_config_filename = os.path.join(self.instance.tracker_home,
                                           "_test_log_config.json")

        # happy path
        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(config1)
            
        config = self.db.config.load_config_dict_from_json_file(
            log_config_filename)
        self.assertIn("version", config)
        self.assertEqual(config['version'], 1)

        # broken inline comment misformatted
        test_config = config1.replace(": 1,   //", ": 1, //")
        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(test_config)

        with self.assertRaises(configuration.LoggingConfigError) as cm:
            config = self.db.config.load_config_dict_from_json_file(
                log_config_filename)
        self.assertEqual(
            cm.exception.args[0],
            ('Error parsing json logging dict '
             '(%s) near \n\n     '
             '"version": 1, // only supported version\n\nExpecting '
             'property name enclosed in double quotes: line 3 column 18.\n'
             'Maybe bad inline comment, 3 spaces needed before //.' %
             log_config_filename)
        )

        # broken trailing , on last dict element
        test_config = config1.replace(' "ext://sys.stdout"',
                                      ' "ext://sys.stdout",'
                                      )
        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(test_config)
            
        with self.assertRaises(configuration.LoggingConfigError) as cm:
            config = self.db.config.load_config_dict_from_json_file(
                log_config_filename)
        #pre 3.12??
        # FIXME check/remove when 3.13. is min supported version
        if "property name" in cm.exception.args[0]:
            self.assertEqual(
                cm.exception.args[0],
                ('Error parsing json logging dict '
                 '(%s) near \n\n'
                 '       }\n\n'
                 'Expecting property name enclosed in double '
                 'quotes: line 37 column 6.' % log_config_filename)
            )

        # 3.13+ diags FIXME
        print('FINDME')
        print(cm.exception.args[0])
        _junk = '''
        if "property name" not in cm.exception.args[0]:
            self.assertEqual(
                cm.exception.args[0],
                ('Error parsing json logging dict '
                 '(%s) near \n\n'
                 '       "stream": "ext://sys.stdout"\n\n'
                 'Expecting property name enclosed in double '
                 'quotes: line 37 column 6.' % log_config_filename)
            )
        '''
        # happy path for init_logging()

        # verify preconditions
        logger = logging.getLogger("roundup")
        self.assertEqual(logger.level, 40) # error default from config.ini
        self.assertEqual(logger.filters, [])

        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(config1)

        # file is made relative to tracker dir.
        self.db.config["LOGGING_CONFIG"] = '_test_log_config.json'
        config = self.db.config.init_logging()
        self.assertIs(config, None)

        logger = logging.getLogger("roundup")
        self.assertEqual(logger.level, 10) # debug
        self.assertEqual(logger.filters, [])
        
        # broken invalid format type (int not str)
        test_config = config1.replace('"format": "%(message)s"',
                                      '"format": 1234',)
        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(test_config)

        # file is made relative to tracker dir.
        self.db.config["LOGGING_CONFIG"] = '_test_log_config.json'


        # different versions of python have different errors
        # (or no error for this case in 3.7)
        # FIXME remove version check post 3.7 as minimum version
        if sys.version_info >= (3, 8, 0):
            with self.assertRaises(configuration.LoggingConfigError) as cm:
                config = self.db.config.init_logging()

                # mangle args[0] to add got 'int'
                # FIXME: remove mangle after 3.12 min version
                self.assertEqual(
                    cm.exception.args[0].replace(
                        "object\n", "object, got 'int'\n"),
                    ('Error loading logging dict from '
                     '%s.\n'
                     "ValueError: Unable to configure formatter 'http'\n"
                     "expected string or bytes-like object, got 'int'\n" %
                     log_config_filename)
                )

        # broken invalid level MANGO
        test_config = config1.replace(
            ': "INFO",    // can',
            ': "MANGO",    // can')
        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(test_config)

        # file is made relative to tracker dir.
        self.db.config["LOGGING_CONFIG"] = '_test_log_config.json'
        with self.assertRaises(configuration.LoggingConfigError) as cm:
            config = self.db.config.init_logging()
        self.assertEqual(
            cm.exception.args[0],
            ("Error loading logging dict from "
             "%s.\nValueError: "
             "Unable to configure logger 'roundup.hyperdb'\nUnknown level: "
             "'MANGO'\n" % log_config_filename)

        )

        # broken invalid output directory
        test_config = config1.replace(
            ' "_test_instance/access.log"',
            ' "not_a_test_instance/access.log"')
        access_filename = os.path.join("not_a_test_instance", "access.log")

        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(test_config)

        # file is made relative to tracker dir.
        self.db.config["LOGGING_CONFIG"] = '_test_log_config.json'
        with self.assertRaises(configuration.LoggingConfigError) as cm:
            config = self.db.config.init_logging()

        # error includes full path which is different on different
        # CI and dev platforms. So munge the path using re.sub and
        # replace. Windows needs replace as the full path for windows
        # to the file has '\\\\' not '\\' when taken from __context__.
        # E.G.
        # ("Error loading logging dict from '
        # '_test_instance\\_test_log_config.json.\nValueError: '
        # "Unable to configure handler 'access'\n[Errno 2] No such file "
        # "or directory: "
        # "'C:\\\\tracker\\\\path\\\\not_a_test_instance\\\\access.log'\n")
        # sigh.....
        output = re.sub("directory: \'.*not_a", 'directory: not_a' ,
                   cm.exception.args[0].replace(r'\\','\\'))
        target = ("Error loading logging dict from "
                  "%s.\n"
                  "ValueError: Unable to configure handler 'access'\n"
                  "[Errno 2] No such file or directory: "
                  "%s'\n" % (log_config_filename, access_filename))
        self.assertEqual(output, target)

        # mess up '}' so json file block isn't properly closed.
        test_config = config1.replace(
            ' }',
            ' ')

        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(test_config)

        # file is made relative to tracker dir.
        self.db.config["LOGGING_CONFIG"] = '_test_log_config.json'
        with self.assertRaises(configuration.LoggingConfigError) as cm:
            config = self.db.config.init_logging()

        output = cm.exception.args[0].replace(r'\\','\\')
        target = ("Error parsing json logging dict "
                  "(%s) near \n\n"
                  "  Error found at end of file. Maybe missing a "
                  "block closing '}'.\n\n"
                  "Expecting ',' delimiter: line 86 column 1." %
                  (log_config_filename,))
        self.assertEqual(output, target)

    def testIniFileLoggerConfig(self):

        # good base test case
        config1 = dedent("""
        [loggers]
        keys=root,roundup,roundup.http,roundup.hyperdb,actions,schema,extension,detector

        [logger_root]
        #DEBUG, INFO, WARNING, ERROR, CRITICAL
        #also for root only NOTSET (all)
        level=DEBUG
        handlers=basic

        [logger_roundup]
        #DEBUG, INFO, WARNING, ERROR, CRITICAL
        #also for root only NOTSET (all)
        level=DEBUG
        handlers=rotate
        qualname=roundup
        propagate=0

        [logger_roundup.http]
        level=INFO
        handlers=rotate_weblog
        qualname=roundup.http
        propagate=0

        [logger_roundup.hyperdb]
        level=WARNING
        handlers=rotate
        qualname=roundup.hyperdb
        propagate=0

        [logger_actions]
        #DEBUG, INFO, WARNING, ERROR, CRITICAL
        #also for root only NOTSET (all)
        level=DEBUG
        handlers=rotate
        qualname=actions
        propagate=0

        [logger_detector]
        #DEBUG, INFO, WARNING, ERROR, CRITICAL
        #also for root only NOTSET (all)
        level=DEBUG
        handlers=rotate
        qualname=detector
        propagate=0

        [logger_schema]
        level=DEBUG
        handlers=rotate
        qualname=schema
        propagate=0

        [logger_extension]
        level=DEBUG
        handlers=rotate
        qualname=extension
        propagate=0

        [handlers]
        keys=basic,rotate,rotate_weblog

        [handler_basic]
        class=StreamHandler
        args=(sys.stderr,)
        formatter=basic

        [handler_rotate]
        class=logging.handlers.RotatingFileHandler
        args=('roundup.log','a', 512000, 2)
        formatter=basic

        [handler_rotate_weblog]
        class=logging.handlers.RotatingFileHandler
        args=('httpd.log','a', 512000, 2)
        formatter=plain

        [formatters]
        keys=basic,plain

        [formatter_basic]
        format=%(asctime)s %(name)s:%(module)s.%(funcName)s,%(levelname)s: %(message)s
        datefmt=%Y-%m-%d %H:%M:%S

        [formatter_plain]
        format=%(message)s
        """)

        log_config_filename = os.path.join(self.instance.tracker_home,
                                           "_test_log_config.ini")

        # happy path
        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(config1)

        self.db.config.LOGGING_CONFIG = "_test_log_config.ini"

        # verify we have a clean environment
        self.assertEqual(len(logging.getLogger('roundup.http').handlers), 0)
        
        # always returns None
        self.db.config.init_logging()

        # verify that logging loaded and handler is set
        # default log config doesn't define handlers for roundup.http
        self.assertEqual(len(logging.getLogger('roundup.http').handlers), 1)
        self.reset_logging()

        # use undefined enumeration
        test_config = config1.replace("=DEBUG\n", "=DEBUF\n")
        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(test_config)

        with self.assertRaises(configuration.LoggingConfigError) as cm:
            config = self.db.config.init_logging()
 
        # verify that logging was reset
        # default log config doesn't define handlers for roundup.http
        self.assertEqual(len(logging.getLogger('roundup.http').handlers), 0)
        
        self.assertEqual(
            cm.exception.args[0].replace(r'\\','\\'),
            ('Error loading logging config from %s.\n\n'
             "   ValueError: Unknown level: 'DEBUF'\n\n"
             'Inappropriate argument value (of correct type).\n' %
             log_config_filename)
        )
        self.reset_logging()


        # add a syntax error "= foo"
        test_config = config1.replace("=DEBUG\n", "=DEBUG\n=foo\n", 1)
        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(test_config)

        with self.assertRaises(configuration.LoggingConfigError) as cm:
            config = self.db.config.init_logging()
 
        # verify that logging was reset
        # default log config doesn't define handlers for roundup.http
        self.assertEqual(len(logging.getLogger('roundup.http').handlers), 0)

        output = cm.exception.args[0].replace(r'\\','\\')

        if sys.version_info >= (3, 12, 0):
            expected = (
                "Error loading logging config from %(filename)s.\n\n"
                "   RuntimeError: %(filename)s is invalid: Source contains parsing errors: "
                "'%(filename)s'\n\t[line  9]: '=foo\\n'\n\n"
                "Source contains parsing errors: '%(filename)s'\n"
                "\t[line  9]: '=foo\\n' Unspecified run-time error.\n" %
                {"filename": log_config_filename})

        else: # 3.7 <= x < 3.12.0

            expected = (
                "Error loading logging config from %(filename)s.\n\n"
                "   ParsingError: Source contains parsing errors: "
                "'%(filename)s'\n"
                "\t[line  9]: '=foo\\n'\n\n"
                "Raised when a configuration file does not follow legal "
                "syntax.\n" % {"filename": log_config_filename})

        self.assertEqual(output, expected)
        self.reset_logging()
        
        # handler = basic to handler = basi
        test_config = config1.replace("handlers=basic\n", "handlers=basi\n", 1)
        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(test_config)

        with self.assertRaises(configuration.LoggingConfigError) as cm:
            config = self.db.config.init_logging()
 
        # verify that logging was reset
        # default log config doesn't define handlers for roundup.http
        self.assertEqual(len(logging.getLogger('roundup.http').handlers), 0)
        
        self.assertEqual(
            cm.exception.args[0].replace(r'\\','\\'),
            ("Error loading logging config from %(filename)s.\n\n"
             "   KeyError: 'basi'\n\n"
             "Mapping key not found. No section found with this name.\n" %
             {"filename": log_config_filename})
        )
        self.reset_logging()

        # Change class to missing class
        test_config = config1.replace("class=StreamHandler\n",
                                      "class=SHAndler\n", 1)
        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(test_config)

        with self.assertRaises(configuration.LoggingConfigError) as cm:
            config = self.db.config.init_logging()
 
        # verify that logging was reset
        # default log config doesn't define handlers for roundup.http
        self.assertEqual(len(logging.getLogger('roundup.http').handlers), 0)
        
        self.assertEqual(
            cm.exception.args[0].replace(r'\\','\\'),
            ("Error loading logging config from %(filename)s.\n\n"
             "   ModuleNotFoundError: No module named 'SHAndler'\n\n"
             "name 'SHAndler' is not defined Module not found.\n" %
             {"filename": log_config_filename})
        )
        self.reset_logging()

        # remove section to cause duplicate option definition
        test_config = config1.replace("[logger_roundup.http]\n",
                                      "\n", 1)
        with open(log_config_filename, "w") as log_config_file:
            log_config_file.write(test_config)

        with self.assertRaises(configparser.DuplicateOptionError) as cm:
            config = self.db.config.init_logging()
 
        # verify that logging was reset
        # default log config doesn't define handlers for roundup.http
        self.assertEqual(len(logging.getLogger('roundup.http').handlers), 0)
        
        self.assertEqual(
            str(cm.exception).replace(r'\\','\\'),
            ("While reading from '%(filename)s' [line 20]: "
             "option 'level' in section 'logger_roundup' already exists" %
             {"filename": log_config_filename})
        )
        self.reset_logging()
                
    def test_missing_logging_config_file(self):
        saved_config = self.db.config['LOGGING_CONFIG']

        for logging_file in ["logging.json", "logging.ini", "logging.foobar"]:
            self.db.config['LOGGING_CONFIG'] = logging_file
        
            with self.assertRaises(configuration.OptionValueError) as cm:
                self.db.config.init_logging()

                logging_configfile = os.path.join(self.dirname, logging_file)
                self.assertEqual(cm.exception.args[1], logging_configfile)
                self.assertEqual(cm.exception.args[2],
                                 "Unable to find logging config file.")

        self.db.config['LOGGING_CONFIG'] = saved_config
        
    def test_unknown_logging_config_file_type(self):
        saved_config = self.db.config['LOGGING_CONFIG']

        self.db.config['LOGGING_CONFIG'] = 'schema.py'


        with self.assertRaises(configuration.OptionValueError) as cm:
            self.db.config.init_logging()

        logging_configfile = os.path.join(self.dirname, "schema.py")
        self.assertEqual(cm.exception.args[1], logging_configfile)
        self.assertEqual(cm.exception.args[2],
                         "Unable to load logging config file. "
                         "File extension must be '.ini' or '.json'.\n")

        self.db.config['LOGGING_CONFIG'] = saved_config
