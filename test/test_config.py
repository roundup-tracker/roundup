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
import fileinput

import os, shutil, errno, sys

import pytest
from roundup import configuration

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

    def testOriginHeader(self):
        config = configuration.CoreConfig()

        with self.assertRaises(configuration.OptionValueError) as cm:
            config._get_option('WEB_ALLOWED_API_ORIGINS').set("* https://foo.edu")

        config._get_option('WEB_ALLOWED_API_ORIGINS').set("https://foo.edu HTTP://baR.edu")

        self.assertEqual(config['WEB_ALLOWED_API_ORIGINS'][0], 'https://foo.edu')
        self.assertEqual(config['WEB_ALLOWED_API_ORIGINS'][1], 'HTTP://baR.edu')
        


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


class TrackerConfig(unittest.TestCase):

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

    def testCopyConfig(self):

        self.munge_configini(mods=[ ("html_version = ", "xhtml") ])

        config = configuration.CoreConfig()

        # verify config is initalized to defaults
        self.assertEqual(config['HTML_VERSION'], 'html4')

        # load config
        config.load(self.dirname)

        # loaded new option
        self.assertEqual(config['HTML_VERSION'], 'xhtml')

        # copy config
        config_copy = config.copy()

        # this should work
        self.assertEqual(config_copy['HTML_VERSION'], 'xhtml')

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
        self.assertIn("_test_instance/config.ini with section [main] at option admin_email", cm.exception.args[0])


        from roundup.admin import AdminTool
        from .test_admin import captured_output

        admin=AdminTool()
        with captured_output() as (out, err):
            sys.argv=['main', '-i', self.dirname, 'get', 'tile', 'issue1']
            ret = admin.main()

        expected_err = "Error in _test_instance/config.ini with section [main] at option admin_email: '%' must be followed by '%' or '(', found: '% is invalid'"

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
