# Roundup Issue Tracker configuration support
#
__docformat__ = "restructuredtext"

# Some systems have a backport of the Python 3 configparser module to
# Python 2: <https://pypi.org/project/configparser/>.  That breaks
# Roundup if used with Python 2 because it generates unicode objects
# where not expected by the Python code.  Thus, a version check is
# used here instead of try/except.
import binascii
import errno
import getopt
import logging
import logging.config
import os
import re
import smtplib
import sys
import time

import roundup.date
from roundup.anypy import random_
from roundup.anypy.strings import b2s
from roundup.backends import list_backends
from roundup.i18n import _

if sys.version_info[0] > 2:
    import configparser  # Python 3
else:
    import ConfigParser as configparser  # Python 2

from roundup.exceptions import RoundupException

# Exceptions


class ConfigurationError(RoundupException):
    pass


class ParsingOptionError(ConfigurationError):
    def __str__(self):
        return self.args[0]


class NoConfigError(ConfigurationError):

    """Raised when configuration loading fails

    Constructor parameters: path to the directory that was used as HOME

    """

    def __str__(self):
        return "No valid configuration files found in directory %s" \
            % self.args[0]


class InvalidOptionError(ConfigurationError, KeyError, AttributeError):

    """Attempted access to non-existing configuration option

    Configuration options may be accessed as configuration object
    attributes or items.  So this exception instances also are
    instances of KeyError (invalid item access) and AttributeError
    (invalid attribute access).

    Constructor parameter: option name

    """

    def __str__(self):
        return "Unsupported configuration option: %s" % self.args[0]


class OptionValueError(ConfigurationError, ValueError):

    """Raised upon attempt to assign an invalid value to config option

    Constructor parameters: Option instance, offending value
    and optional info string.

    """

    def __str__(self):
        _args = self.args
        _rv = "Invalid value for %(option)s: %(value)r" % {
            "option": _args[0].name, "value": _args[1]}
        if len(_args) > 2:
            _rv += "\n".join(("",) + _args[2:])
        return _rv


class OptionUnsetError(ConfigurationError):

    """Raised when no Option value is available - neither set, nor default

    Constructor parameters: Option instance.

    """

    def __str__(self):
        return "%s is not set and has no default" % self.args[0].name


class UnsetDefaultValue:

    """Special object meaning that default value for Option is not specified"""

    def __str__(self):
        return "NO DEFAULT"


NODEFAULT = UnsetDefaultValue()


def create_token(size=32):
    return b2s(binascii.b2a_base64(random_.token_bytes(size)).strip())

# Option classes


class Option:

    """Single configuration option.

    Options have following attributes:

        config
            reference to the containing Config object
        section
            name of the section in the tracker .ini file
        setting
            option name in the tracker .ini file
        default
            default option value
        description
            option description.  Makes a comment in the tracker .ini file
        name
            "canonical name" of the configuration option.
            For items in the 'main' section this is uppercased
            'setting' name.  For other sections, the name is
            composed of the section name and the setting name,
            joined with underscore.
        aliases
            list of "also known as" names.  Used to access the settings
            by old names used in previous Roundup versions.
            "Canonical name" is also included.

    The name and aliases are forced to be uppercase.
    The setting name is forced to lowercase.

    """

    class_description = None

    def __init__(self, config, section, setting,
                 default=NODEFAULT, description=None, aliases=None):
        self.config = config
        self.section = section
        self.setting = setting.lower()
        self.default = default
        self.description = description
        self.name = setting.upper()
        if section != "main":
            self.name = "_".join((section.upper(), self.name))
        if aliases:
            self.aliases = [alias.upper() for alias in list(aliases)]
        else:
            self.aliases = []
        self.aliases.insert(0, self.name)
        # convert default to internal representation
        _value = default if default is NODEFAULT else self.str2value(default)

        # value is private.  use get() and set() to access
        self._value = self._default_value = _value

    def str2value(self, value):
        """Return 'value' argument converted to internal representation"""
        return value

    def _value2str(self, value):
        """Return 'value' argument converted to external representation

        This is actual conversion method called only when value
        is not NODEFAULT.  Heirs with different conversion rules
        override this method, not the public .value2str().

        """
        return str(value)

    def value2str(self, value=NODEFAULT, current=0):
        """Return 'value' argument converted to external representation

        If 'current' is True, use current option value.

        """
        if current:
            value = self._value
        if value is NODEFAULT:
            return str(value)
        else:
            return self._value2str(value)

    def get(self):
        """Return current option value"""
        if self._value is NODEFAULT:
            raise OptionUnsetError(self)
        return self._value

    def set(self, value):
        """Update the value"""
        self._value = self.str2value(value)

    def reset(self):
        """Reset the value to default"""
        self._value = self._default_value

    def isdefault(self):
        """Return True if current value is the default one"""
        return self._value == self._default_value

    def isset(self):
        """Return True if the value is available (either set or default)"""
        return self._value != NODEFAULT

    def __str__(self):
        return self.value2str(self._value)

    def __repr__(self):
        if self.isdefault():
            _format = "<%(class)s %(name)s (default): %(value)s>"
        else:
            _format = "<%(class)s %(name)s (default: %(default)s): %(value)s>"
        return _format % {
            "class": self.__class__.__name__,
            "name": self.name,
            "default": self.value2str(self._default_value),
            "value": self.value2str(self._value),
        }

    def format(self):
        """Return .ini file fragment for this option"""
        _desc_lines = []
        for _description in (self.description, self.class_description):
            if _description:
                _desc_lines.extend(_description.split("\n"))
        # comment out the setting line if there is no value
        _is_set = "" if self.isset() else "#"

        _rv = "# %(description)s\n# Default: %(default)s\n" \
            "%(is_set)s%(name)s = %(value)s\n" % {
                "description": "\n# ".join(_desc_lines),
                "default": self.value2str(self._default_value),
                "name": self.setting,
                "value": self.value2str(self._value),
                "is_set": _is_set,
            }
        return _rv

    def load_ini(self, config):
        """Load value from ConfigParser object"""
        try:
            if config.has_option(self.section, self.setting):
                self.set(config.get(self.section, self.setting))
        except configparser.InterpolationSyntaxError as e:
            raise ParsingOptionError(
                _("Error in %(filepath)s with section [%(section)s] at "
                  "option %(option)s: %(message)s") % {
                      "filepath": self.config.filepath,
                      "section": e.section,
                      "option": e.option,
                      "message": str(e)})


class BooleanOption(Option):

    """Boolean option: yes or no"""

    class_description = "Allowed values: yes, no"

    def _value2str(self, value):
        if value:
            return "yes"
        else:
            return "no"

    def str2value(self, value):
        if isinstance(value, type("")):
            _val = value.lower()
            if _val in ("yes", "true", "on", "1"):
                _val = 1
            elif _val in ("no", "false", "off", "0"):
                _val = 0
            else:
                raise OptionValueError(self, value, self.class_description)
        else:
            _val = value and 1 or 0
        return _val


class WordListOption(Option):

    """List of strings"""

    class_description = "Allowed values: comma-separated list of words"

    def _value2str(self, value):
        return ','.join(value)

    def str2value(self, value):
        return value.split(',')


class RunDetectorOption(Option):

    """When a detector is run: always, never or for new items only"""

    class_description = "Allowed values: yes, no, new"

    def str2value(self, value):
        _val = value.lower()
        if _val in ("yes", "no", "new"):
            return _val
        else:
            raise OptionValueError(self, value, self.class_description)


class CsrfSettingOption(Option):

    """How should a csrf measure be enforced: required, yes, logfailure, no"""

    class_description = "Allowed values: required, yes, logfailure, no"

    def str2value(self, value):
        _val = value.lower()
        if _val in ("required", "yes", "logfailure", "no"):
            return _val
        else:
            raise OptionValueError(self, value, self.class_description)


class SameSiteSettingOption(Option):

    """How should the SameSite cookie setting be set: strict, lax
or should it not be added (none)"""

    class_description = "Allowed values: Strict, Lax, None"

    def str2value(self, value):
        _val = value.lower()
        if _val in ("strict", "lax", "none"):
            return _val.capitalize()
        else:
            raise OptionValueError(self, value, self.class_description)


class DatabaseBackend(Option):
    """handle exact text of backend and make sure it's available"""
    class_description = "Available backends: %s" % ", ".join(list_backends())

    def str2value(self, value):
        _val = value.lower()
        if _val in list_backends():
            return _val
        else:
            raise OptionValueError(self, value, self.class_description)


class HtmlToTextOption(Option):

    """What module should be used to convert emails with only text/html
    parts into text for display in roundup. Choose from beautifulsoup
    4, dehtml - the internal code or none to disable html to text
    conversion. If beautifulsoup chosen but not available, dehtml will
    be used.

    """

    class_description = "Allowed values: beautifulsoup, dehtml, none"

    def str2value(self, value):
        _val = value.lower()
        if _val in ("beautifulsoup", "dehtml", "none"):
            return _val
        else:
            raise OptionValueError(self, value, self.class_description)


class HtmlVersionOption(Option):
    """Accept html4 only for now. Raise error for xhtml which is not
       supported in roundup 2.4 and newer."""

    class_description = "Allowed values: html4"

    def str2value(self, value):
        _val = value.lower()
        if _val in ("html4"):
            return _val
        else:
            raise OptionValueError(self, value, self.class_description)

class EmailBodyOption(Option):

    """When to replace message body or strip quoting: always, never
    or for new items only"""

    class_description = "Allowed values: yes, no, new"

    def str2value(self, value):
        _val = value.lower()
        if _val in ("yes", "no", "new"):
            return _val
        else:
            raise OptionValueError(self, value, self.class_description)


class IsolationOption(Option):
    """Database isolation levels"""

    allowed = ('read uncommitted', 'read committed', 'repeatable read',
               'serializable')
    class_description = "Allowed values: %s" % ', '.join("'%s'" % a
                                                         for a in allowed)

    def str2value(self, value):
        _val = value.lower()
        if _val in self.allowed:
            return _val
        raise OptionValueError(self, value, self.class_description)


class IndexerOption(Option):
    """Valid options for indexer"""

    allowed = ('', 'xapian', 'whoosh', 'native', 'native-fts')
    class_description = "Allowed values: %s" % ', '.join("'%s'" % a
                                                         for a in allowed)

    # FIXME this is the result of running:
    #    SELECT cfgname FROM pg_ts_config;
    # on a postgresql 14.1 server.
    # So the best we can do is hardcode this.
    valid_langs = ("simple",
                   "custom1",
                   "custom2",
                   "custom3",
                   "custom4",
                   "custom5",
                   "arabic",
                   "armenian",
                   "basque",
                   "catalan",
                   "danish",
                   "dutch",
                   "english",
                   "finnish",
                   "french",
                   "german",
                   "greek",
                   "hindi",
                   "hungarian",
                   "indonesian",
                   "irish",
                   "italian",
                   "lithuanian",
                   "nepali",
                   "norwegian",
                   "portuguese",
                   "romanian",
                   "russian",
                   "serbian",
                   "spanish",
                   "swedish",
                   "tamil",
                   "turkish",
                   "yiddish")

    def str2value(self, value):
        _val = value.lower()
        if _val in self.allowed:
            return _val
        raise OptionValueError(self, value, self.class_description)

    def validate(self, options):

        if self._value in ("", "xapian"):
            try:
                import xapian
            except ImportError:
                # indexer is probably '' and xapian isn't present
                # so just return at end of method
                pass
            else:
                try:
                    lang = options["INDEXER_LANGUAGE"]._value
                    xapian.Stem(lang)
                except xapian.InvalidArgumentError:
                    import textwrap
                    lang_avail = b2s(xapian.Stem.get_available_languages())
                    languages = textwrap.fill(_("Valid languages: ") +
                                              lang_avail, 75,
                                              subsequent_indent="   ")
                    raise OptionValueError(options["INDEXER_LANGUAGE"],
                                           lang, languages)

        if self._value == "native-fts":
            lang = options["INDEXER_LANGUAGE"]._value
            if lang not in self.valid_langs:
                import textwrap
                languages = textwrap.fill(_("Expected languages: ") +
                                          " ".join(self.valid_langs), 75,
                                          subsequent_indent="   ")
                raise OptionValueError(options["INDEXER_LANGUAGE"],
                                       lang, languages)


class MailAddressOption(Option):

    """Email address

    Email addresses may be either fully qualified or local.
    In the latter case MAIL_DOMAIN is automatically added.

    """

    def get(self):
        _val = Option.get(self)
        if "@" not in _val:
            _val = "@".join((_val, self.config["MAIL_DOMAIN"]))
        return _val


class FilePathOption(Option):

    """File or directory path name

    Paths may be either absolute or relative to the HOME.

    """

    class_description = "The path may be either absolute or relative\n" \
        "to the directory containing this config file."

    def get(self):
        _val = Option.get(self)
        if _val and not os.path.isabs(_val):
            _val = os.path.join(self.config["HOME"], _val)
        return _val


class SpaceSeparatedListOption(Option):

    """List of space seperated elements.
    """

    class_description = "A list of space separated elements."

    def get(self):
        _val = Option.get(self)
        pathlist = list(_val.split())
        if pathlist:
            return pathlist
        else:
            return None


class OriginHeadersListOption(Option):

    """List of space seperated origin header values.
    """

    class_description = "A list of space separated case sensitive\norigin headers 'scheme://host'."

    def set(self, _val):
        pathlist = list(_val.split())
        if '*' in pathlist and pathlist[0] != '*':
            raise OptionValueError(
                self, _val,
                "If using '*' it must be the first element.")
        self._value = pathlist

    def _value2str(self, value):
        return ','.join(value)


class MultiFilePathOption(Option):

    """List of space seperated File or directory path name

    Paths may be either absolute or relative to the HOME. None
    is returned if there are no elements.

    """

    class_description = "The space separated paths may be either absolute\n" \
        "or relative to the directory containing this config file."

    def get(self):
        pathlist = []
        _val = Option.get(self)
        for elem in _val.split():
            if elem and not os.path.isabs(elem):
                pathlist.append(os.path.join(self.config["HOME"], elem))
            else:
                pathlist.append(os.path.normpath(elem))
        if pathlist:
            return pathlist
        else:
            return None


class FloatNumberOption(Option):

    """Floating point numbers"""

    def str2value(self, value):
        try:
            return float(value)
        except ValueError:
            raise OptionValueError(self, value,
                                   "Floating point number required")

    def _value2str(self, value):
        _val = str(value)
        # strip fraction part from integer numbers
        if _val.endswith(".0"):
            _val = _val[:-2]
        return _val


class IntegerNumberOption(Option):

    """Integer numbers"""

    def str2value(self, value):
        try:
            return int(value)
        except ValueError:
            raise OptionValueError(self, value, "Integer number required")


class IntegerNumberGeqZeroOption(Option):

    """Integer numbers greater than or equal to zero."""

    def str2value(self, value):
        try:
            v = int(value)
            if v < 0:
                raise OptionValueError(self, value,
                      "Integer number greater than or equal to zero required")
            return v
        except OptionValueError:
            raise  # pass through subclass
        except ValueError:
            raise OptionValueError(self, value, "Integer number required")


class IntegerNumberGtZeroOption(Option):

    """Integer numbers greater than zero."""

    def str2value(self, value):
        try:
            v = int(value)
            if v < 1:
                raise OptionValueError(self, value,
                      "Integer number greater than zero required")
            return v
        except OptionValueError:
            raise  # pass through subclass
        except ValueError:
            raise OptionValueError(self, value, "Integer number required")


class OctalNumberOption(Option):

    """Octal Integer numbers"""

    def str2value(self, value):
        try:
            return int(value, 8)
        except ValueError:
            raise OptionValueError(self, value,
                                   "Octal Integer number required")

    def _value2str(self, value):
        return oct(value)


class MandatoryOption(Option):
    """Option must not be empty"""
    def str2value(self, value):
        if not value:
            raise OptionValueError(self, value, "Value must not be empty.")
        else:
            return value


class SecretOption(Option):
    """A string not beginning with file:// or a file starting with file://

    Paths may be either absolute or relative to the HOME.
    Value for option is the first line in the file.
    It is mean to store secret information in the config file but
    allow the config file to be stored in version control without
    storing the secret there.

    """

    class_description = (
        "A string that starts with 'file://' is interpreted\n"
        "as a file path relative to the tracker home. Using\n"
        "'file:///' defines an absolute path. The first\n"
        "line of the file will be used as the value. Any\n"
        "string that does not start with 'file://' is used\n"
        "as is. It removes any whitespace at the end of the\n"
        "line, so a newline can be put in the file.\n")

    def get(self):
        _val = Option.get(self)
        if isinstance(_val, str) and _val.startswith('file://'):
            filepath = _val[7:]
            if filepath and not os.path.isabs(filepath):
                filepath = os.path.join(self.config["HOME"], filepath.strip())
            try:
                with open(filepath) as f:
                    _val = f.readline().rstrip()
            # except FileNotFoundError: py2/py3
            # compatible version
            except EnvironmentError as e:
                if e.errno != errno.ENOENT:
                    raise
                else:
                    raise OptionValueError(
                        self, _val,
                        "Unable to read value for %s. Error opening "
                        "%s: %s." % (self.name, e.filename, e.args[1]))
        return self.str2value(_val)

    def validate(self, options):
        if self.name == 'MAIL_PASSWORD':
            if options['MAIL_USERNAME']._value:
                # MAIL_PASSWORD is an exception. It is mandatory only
                # if MAIL_USERNAME is set. So check only if username
                # is set.
                try:
                    self.get()
                except OptionUnsetError:
                    # provide error message with link to MAIL_USERNAME
                    raise OptionValueError(
                        options["MAIL_PASSWORD"],
                        "not defined",
                        "Mail username is set, so this must be defined.")
        else:
            self.get()


class WebUrlOption(Option):
    """URL MUST start with http/https scheme and end with '/'"""

    def str2value(self, value):
        if not value:
            raise OptionValueError(self, value, "Value must not be empty.")

        error_msg = ''
        if not value.startswith(('http://', 'https://')):
            error_msg = "Value must start with http:// or https://.\n"

        if not value.endswith('/'):
            error_msg += "Value must end with /."

        if error_msg:
            raise OptionValueError(self, value, error_msg)
        else:
            return value


class NullableOption(Option):

    """Option that is set to None if its string value is one of NULL strings

    Default nullable strings list contains empty string only.
    There is constructor parameter allowing to specify different nullables.

    Conversion to external representation returns the first of the NULL
    strings list when the value is None.

    """

    NULL_STRINGS = ("",)

    def __init__(self, config, section, setting,
                 default=NODEFAULT, description=None, aliases=None,
                 null_strings=NULL_STRINGS):
        self.null_strings = list(null_strings)
        Option.__init__(self, config, section, setting, default,
                        description, aliases)

    def str2value(self, value):
        if value in self.null_strings:
            return None
        else:
            return value

    def _value2str(self, value):
        if value is None:
            return self.null_strings[0]
        else:
            return value


class NullableFilePathOption(NullableOption, FilePathOption):

    # .get() and class_description are from FilePathOption,
    get = FilePathOption.get
    class_description = FilePathOption.class_description
    # everything else taken from NullableOption (inheritance order)


class SecretMandatoryOption(MandatoryOption, SecretOption):
    # use get from SecretOption and rest from MandatoryOption
    get = SecretOption.get
    class_description = SecretOption.class_description


class SecretNullableOption(NullableOption, SecretOption):
    # use get from SecretOption and rest from NullableOption
    get = SecretOption.get
    class_description = SecretOption.class_description


class ListSecretOption(SecretOption):
    # use get from SecretOption
    def get(self):
        value = SecretOption.get(self)
        return [x.lstrip() for x in value.split(',')]

    class_description = SecretOption.class_description

    def validate(self, options):  # noqa: ARG002  --  options unused
        if self.name == "WEB_JWT_SECRET":
            secrets = self.get()
            invalid_secrets = [x for x in secrets[1:] if len(x) < 32]
            if invalid_secrets:
                raise OptionValueError(
                    self, ", ".join(secrets),
                    "One or more secrets less then 32 characters in length\n"
                    "found: %s" % ', '.join(invalid_secrets))
        else:
            self.get()


class RedisUrlOption(SecretNullableOption):
    """Do required check to make sure known bad parameters are not
       put in the url.

       Should I do more URL validation? Validate schema:
       redis, rediss, unix? How many cycles to invest
       to keep users from their own mistakes?
    """

    class_description = SecretNullableOption.class_description

    def str2value(self, value):
        if value and value.find("decode_responses") != -1:
            raise OptionValueError(self, value, "URL must not include "
                                   "decode_responses. Please remove "
                                   "the option.")
        return value


class SessiondbBackendOption(Option):
    """Make sure that sessiondb is compatible with the primary db.
       Fail with error and suggestions if they are incompatible.
    """

    compatibility_matrix = (
        ('anydbm', 'anydbm'),
        ('anydbm', 'redis'),
        ('sqlite', 'anydbm'),
        ('sqlite', 'sqlite'),
        ('sqlite', 'redis'),
        ('mysql', 'mysql'),
        ('postgresql', 'postgresql'),
        )

    def validate(self, options):
        ''' make sure session db is compatible with primary db.
            also if redis is specified make sure it's available.
            suggest valid session db backends include redis if
            available.
        '''

        if self.name == 'SESSIONDB_BACKEND':
            rdbms_backend = options['RDBMS_BACKEND']._value
            sessiondb_backend = self._value

            if not sessiondb_backend:
                # unset will choose default
                return

            redis_available = False
            try:
                import redis  # noqa: F401
                redis_available = True
            except ImportError:
                if sessiondb_backend == 'redis':
                    valid_session_backends = ', '.join(sorted(
                        [x[1] for x in self.compatibility_matrix
                         if x[0] == rdbms_backend and x[1] != 'redis']))
                    raise OptionValueError(
                        self, sessiondb_backend,
                        "Unable to load redis module. Please install "
                        "a redis library or choose\n an alternate "
                        "session db: %(valid_session_backends)s" % locals())

            if ((rdbms_backend, sessiondb_backend) not in
                    self.compatibility_matrix):
                valid_session_backends = ', '.join(sorted(
                    {x[1] for x in self.compatibility_matrix
                         if x[0] == rdbms_backend and
                         (redis_available or x[1] != 'redis')}))

                raise OptionValueError(
                    self, sessiondb_backend,
                    "You can not use session db type: %(sessiondb_backend)s "
                    "with %(rdbms_backend)s.\n  Valid session db types: "
                    "%(valid_session_backends)s." % locals())


class TimezoneOption(Option):

    class_description = \
        "If pytz module is installed, value may be any valid\n" \
        "timezone specification (e.g. EET or Europe/Warsaw).\n" \
        "If pytz is not installed, value must be integer number\n" \
        "giving local timezone offset from UTC in hours."

    # fix issue2551030, default value for timezone
    # Must be 0 if no pytz can be UTC if pytz.
    try:
        import pytz
        defaulttz = "UTC"
    except ImportError:
        defaulttz = "0"

    def str2value(self, value):
        try:
            roundup.date.get_timezone(value)
        except KeyError:
            raise OptionValueError(
                self, value,
                "Timezone name or numeric hour offset required")
        return value


class HttpVersionOption(Option):
    """Used by roundup-server to verify http version is set to valid
       string."""

    def str2value(self, value):
        if value not in ["HTTP/1.0", "HTTP/1.1"]:
            raise OptionValueError(
                self, value,
                "Valid vaues for -V or --http_version are: HTTP/1.0, HTTP/1.1")
        return value


class RegExpOption(Option):

    """Regular Expression option (value is Regular Expression Object)"""

    class_description = "Value is Python Regular Expression (UTF8-encoded)."

    RE_TYPE = type(re.compile(""))

    def __init__(self, config, section, setting,
                 default=NODEFAULT, description=None, aliases=None,
                 flags=0):
        self.flags = flags
        Option.__init__(self, config, section, setting, default,
                        description, aliases)

    def _value2str(self, value):
        assert isinstance(value, self.RE_TYPE)  # noqa: S101  -- assert is ok
        return value.pattern

    def str2value(self, value):
        if not isinstance(value, type(u'')):
            value = str(value)
        if not isinstance(value, type(u'')):
            # if it is 7-bit ascii, use it as string,
            # otherwise convert to unicode.
            try:
                value.decode("ascii")
            except UnicodeError:
                value = value.decode("utf-8")
        return re.compile(value, self.flags)


class LogLevelOption(Option):
    """A log level, one of none, debug, info, warning, error, critical"""

    values = "none debug info warning error critical".split()
    class_description = "Allowed values: %s" % (', '.join(values))

    def str2value(self, value):
        _val = value.lower()
        if _val in self.values:
            return _val
        else:
            raise OptionValueError(self, value, self.class_description)


try:
    import jinja2  # noqa: F401
    jinja2_avail = "Available found"
except ImportError:
    jinja2_avail = "Unavailable needs"

# Main configuration layout.
# Config is described as a sequence of sections,
# where each section name is followed by a sequence
# of Option definitions.  Each Option definition
# is a sequence containing class name and constructor
# parameters, starting from the setting name:
# setting, default, [description, [aliases]]
# Note: aliases should only exist in historical options for backwards
# compatibility - new options should *not* have aliases!


SETTINGS = (
    ("main", (
        (FilePathOption, "database", "db", "Database directory path."),
        (Option, "template_engine", "zopetal",
            "Templating engine to use.\n"
            "Possible values are:\n"
            "   'zopetal' for the old TAL engine ported from Zope,\n"
            "   'chameleon' for Chameleon,\n"
            "   'jinja2' for jinja2 templating.\n"
            "      %s jinja2 module." % jinja2_avail),
        (FilePathOption, "templates", "html",
            "Path to the HTML templates directory."),
        (MultiFilePathOption, "static_files", "",
            "A list of space separated directory paths (or a single\n"
            "directory).  These directories hold additional public\n"
            "static files available via Web UI.  These directories\n"
            "may contain sitewide images, CSS stylesheets etc. If a\n"
            "'-' is included, the list processing ends and the\n"
            "TEMPLATES directory is not searched after the specified\n"
            "directories.  If this option is not set, all static\n"
            "files are taken from the TEMPLATES directory. Access to\n"
            "these files is public, it is not checked against\n"
            "registered users. So do not put any sensitive data in\n"
            "the files in these directories."),
        (MailAddressOption, "admin_email", "roundup-admin",
            "Email address that roundup will complain to if it runs\n"
            "into trouble.\n"
            "If no domain is specified then the config item\n"
            "mail -> domain is added."),
        (MailAddressOption, "dispatcher_email", "roundup-admin",
            "The 'dispatcher' is a role that can get notified\n"
            "when errors occur while sending email to a user.\n"
            "It is used by the ERROR_MESSAGES_TO config setting.\n"
            "If no domain is specified then the config item\n"
            "mail -> domain is added."),
        (Option, "email_from_tag", "",
            'Additional text to include in the "name" part\n'
            "of the From: address used in nosy messages.\n"
            'If the sending user is "Foo Bar", the From: line\n'
            'is usually: "Foo Bar" <issue_tracker@tracker.example>\n'
            'the EMAIL_FROM_TAG goes inside the "Foo Bar" quotes like so:\n'
            '"Foo Bar EMAIL_FROM_TAG" <issue_tracker@tracker.example>'),
        (Option, "new_web_user_roles", "User",
            "Roles that a user gets when they register\n"
            "with Web User Interface.\n"
            "This is a comma-separated string of role names\n"
            " (e.g. 'Admin,User')."),
        (Option, "new_email_user_roles", "User",
            "Roles that a user gets when they register\n"
            "with Email Gateway.\n"
            "This is a comma-separated string of role names\n"
            " (e.g. 'Admin,User')."),
        (Option, "obsolete_history_roles", "Admin",
            "On schema changes, properties or classes in the history may\n"
            "become obsolete.  Since normal access permissions do not apply\n"
            "(we don't know if a user should see such a property or class)\n"
            "a list of roles is specified here that are allowed to see\n"
            "these obsolete properties in the history. By default only the\n"
            "admin role may see these history entries, you can make them\n"
            "visible to all users by adding, e.g., the 'User' role here."),
        (Option, "error_messages_to", "user",
            'Send error message emails to the "dispatcher", "user", \n'
            'or "both" (these are the three allowed values).\n'
            'The dispatcher is configured using the DISPATCHER_EMAIL\n'
            ' setting.'),
        (HtmlVersionOption, "html_version", "html4",
            "This setting should be left at the default value of html4.\n"
            "Support for xhtml has been disabled.\n"
            "HTML version to generate. The templates are html4 by default."),
        (TimezoneOption, "timezone", TimezoneOption.defaulttz,
            "Default timezone offset,\n"
            "applied when user's timezone is not set.",
            ["DEFAULT_TIMEZONE"]),
        (BooleanOption, "instant_registration", "no",
            "Register new users instantly, or require confirmation via\n"
            "email?"),
        (BooleanOption, "email_registration_confirmation", "yes",
            "Offer registration confirmation by email or only\n"
            "through the web?"),
        (IndexerOption, "indexer", "",
            "Force Roundup to use a particular text indexer.\n"
            "If no indexer is supplied, the first available indexer\n"
            "will be used in the following order:\n"
            "Possible values: xapian, whoosh, native (internal), "
            "native-fts.\nNote 'native-fts' will only be used if set."),
        (Option, "indexer_language", "english",
            "Used to determine what language should be used by the\n"
            "indexer above. Applies to Xapian and PostgreSQL native-fts\n"
            "indexer. It sets the language for the stemmer, and PostgreSQL\n"
            "native-fts stopwords and other dictionaries.\n"
            "Possible values: must be a valid language for the indexer,\n"
            "see indexer documentation for details."),
        (WordListOption, "indexer_stopwords", "",
            "Additional stop-words for the full-text indexer specific to\n"
            "your tracker. See the indexer source for the default list of\n"
            "stop-words (eg. A,AND,ARE,AS,AT,BE,BUT,BY, ...). This is\n"
            "not used by the postgres native-fts indexer. But is used to\n"
            "filter search terms with the sqlite native-fts indexer."),
        (OctalNumberOption, "umask", "0o002",
            "Defines the file creation mode mask."),
        (IntegerNumberGeqZeroOption, 'csv_field_size', '131072',
            "Maximum size of a csv-field during import. Roundups export\n"
            "format is a csv (comma separated values) variant. The csv\n"
            "reader has a limit on the size of individual fields\n"
            "starting with python 2.5. Set this to a higher value if you\n"
            "get the error 'Error: field larger than field limit' during\n"
            "import."),
        (IntegerNumberGeqZeroOption, 'password_pbkdf2_default_rounds',
         '250000',
            "Sets the default number of rounds used when encoding passwords\n"
            "using any PBKDF2 scheme. Set this to a higher value on faster\n"
            "systems which want more security. Use a minimum of 250000\n"
            "for PBKDF2-SHA512 which is the default hash in Roundup 2.5.\n"
            "PBKDF2 (Password-Based Key Derivation Function) is a\n"
            "password hashing mechanism that derives hash from the\n"
            "password and a random salt. For authentication this process\n"
            "is repeated with the same salt as in the stored hash.\n"
            "If both hashes match, the authentication succeeds.\n"
            "PBKDF2 supports a variable 'rounds' parameter which varies\n"
            "the time-cost of calculating the hash - doubling the number\n"
            "of rounds doubles the cpu time required to calculate it. The\n"
            "purpose of this is to periodically adjust the rounds as CPUs\n"
            "become faster. The currently enforced minimum number of\n"
            "rounds is 1000.\n"
            "See: http://en.wikipedia.org/wiki/PBKDF2 and RFC2898"),
    )),
    ("tracker", (
        (Option, "name", "Roundup issue tracker",
            "A descriptive name for your roundup instance."),
        (WebUrlOption, "web", NODEFAULT,
            "The web address that the tracker is viewable at.\n"
            "This will be included in information\n"
            "sent to users of the tracker.\n"
            "The URL MUST include the cgi-bin part or anything else\n"
            "that is required to get to the home page of the tracker.\n"
            "URL MUST start with http/https scheme and end with '/'"),
        (MailAddressOption, "email", "issue_tracker",
            "Email address that mail to roundup should go to.\n"
            "If no domain is specified then mail_domain is added."),
        (Option, "replyto_address", "",
            "Controls the reply-to header address used when sending\n"
            "nosy messages.\n"
            "If the value is unset (default) the roundup tracker's\n"
            "email address (above) is used.\n"
            'If set to "AUTHOR" then the primary email address of the\n'
            "author of the change will be used as the reply-to\n"
            "address. This allows email exchanges to occur outside of\n"
            "the view of roundup and exposes the address of the person\n"
            "who updated the issue, but it could be useful in some\n"
            "unusual circumstances.\n"
            "If set to some other value, the value is used as the reply-to\n"
            "address. It must be a valid RFC2822 address or people will not\n"
            "be able to reply."),
        (NullableOption, "language", "",
            "Default locale name for this tracker.\n"
            "If this option is not set, the language is determined\n"
            "by OS environment variable LANGUAGE, LC_ALL, LC_MESSAGES,\n"
            "or LANG, in that order of preference."),
    )),
    ("web", (
        (BooleanOption, "allow_html_file", "no",
            "Setting this option enables Roundup to serve uploaded HTML\n"
            "file content *as HTML*. This is a potential security risk\n"
            "and is therefore disabled by default. Set to 'yes' if you\n"
            "trust *all* users uploading content to your tracker."),
        (BooleanOption, 'http_auth', "yes",
            "Whether to use HTTP Basic Authentication, if present.\n"
            "Roundup will use either the REMOTE_USER (the value set \n"
            "by http_auth_header) or HTTP_AUTHORIZATION\n"
            "variables supplied by your web server (in that order).\n"
            "Set this option to 'no' if you do not wish to use HTTP Basic\n"
            "Authentication in your web interface."),
        (Option, "http_auth_header", "",
            "The HTTP header that holds the user authentication information.\n"
            "If empty (default) the REMOTE_USER header is used.\n"
            "This is used when the upstream HTTP server authenticates\n"
            "the user and passes the username using this HTTP header."),
        (BooleanOption, "dynamic_compression", "yes",
            "Setting this option makes roundup look at the Accept-Encoding\n"
            "header supplied by the client. It will compress the response\n"
            "on the fly using a common encoding. Disable it if your\n"
            "upstream server does compression of dynamic data."),
        (BooleanOption, "use_precompressed_files", "no",
            "Setting this option enables Roundup to serve precompressed\n"
            "static files. The admin must create the compressed files with\n"
            "proper extension (.gzip, .br, .zstd) in the same directory as\n"
            "the uncompressed file. If a precompressed file doesn't\n"
            "exist, the uncompressed file will be served possibly with\n"
            "dynamic compression."),
        (BooleanOption, 'http_auth_convert_realm_to_lowercase', "no",
            "If usernames consist of a name and a domain/realm part of\n"
            "the form user@realm and we're using REMOTE_USER for\n"
            "authentication (e.g. via Kerberos), convert the realm part\n"
            "of the incoming REMOTE_USER to lowercase before matching\n"
            "against the roundup username. This allows roundup usernames\n"
            "to be lowercase (including the realm) and still follow the\n"
            "Kerberos convention of using an uppercase realm. In\n"
            "addition this is compatible with Active Directory which\n"
            "stores the username with realm as UserPrincipalName in\n"
            "lowercase."),
        (BooleanOption, 'cookie_takes_precedence', "no",
            "If the http_auth option is in effect (see above)\n"
            "we're accepting a REMOTE_USER variable resulting from\n"
            "an authentication mechanism implemented in the web-server,\n"
            "e.g., Kerberos login or similar. To override the mechanism\n"
            "provided by the web-server (e.g. for enabling sub-login as\n"
            "another user) we tell roundup that the cookie takes\n"
            "precedence over a REMOTE_USER or HTTP_AUTHORIZATION\n"
            "variable. So if both, a cookie and a REMOTE_USER is\n"
            "present, the cookie wins.\n"),
        (IntegerNumberGeqZeroOption, 'login_attempts_min', "3",
            "Limit login attempts per user per minute to this number.\n"
            "By default the 4th login attempt in a minute will notify\n"
            "the user that they need to wait 20 seconds before trying to\n"
            "log in again. This limits password guessing attacks and\n"
            "shouldn't need to be changed. Rate limiting on login can\n"
            "be disabled by setting the value to 0."),
        (IntegerNumberGeqZeroOption, 'registration_delay', "4",
            "The number of seconds needed to complete the new user\n"
            "registration form. This limits the rate at which bots\n"
            "can attempt to sign up. Limit can be disabled by setting\n"
            "the value to 0."),
        (BooleanOption, 'registration_prevalidate_username', "no",
            "When registering a user, check that the username\n"
            "is available before sending confirmation email.\n"
            "Usually a username conflict is detected when\n"
            "confirming the registration. Disabled by default as\n"
            "it can be used for guessing existing usernames.\n"),
        (SameSiteSettingOption, 'samesite_cookie_setting', "Lax",
            """Set the mode of the SameSite cookie option for
the session cookie. Choices are 'Lax' or
'Strict'. 'None' can be used to suppress the
option. Strict mode provides additional security
against CSRF attacks, but may confuse users who
are logged into roundup and open a roundup link
from a source other than roundup (e.g. link in
email)."""),
        (BooleanOption, 'enable_xmlrpc', "yes",
            """Whether to enable the XMLRPC API in the roundup web
interface. By default the XMLRPC endpoint is the string
'xmlrpc' after the roundup web url configured in the
'tracker' section. If this variable is set to 'no', the
xmlrpc path has no special meaning and will yield an
error message."""),
        (BooleanOption, 'translate_xmlrpc', 'no',
            """Whether to enable i18n for the xmlrpc endpoint. Enable it if
you want to enable translation based on browsers lang
(if enabled), trackers lang (if set) or environment."""),
        (BooleanOption, 'enable_rest', "yes",
            """Whether to enable the REST API in the roundup web
interface. By default the REST endpoint is the string
'rest' plus any additional REST-API parameters after the
roundup web url configured in the tracker section. If this
variable is set to 'no', the rest path has no special meaning
and will yield an error message."""),
        (BooleanOption, 'translate_rest', 'no',
            """Whether to enable i18n for the rest endpoint. Enable it if
you want to enable translation based on browsers lang
(if enabled), trackers lang (if set) or environment."""),
        (LogLevelOption, 'rest_logging', 'none',
            "Log-Level for REST errors."),
        (IntegerNumberGeqZeroOption, 'api_calls_per_interval', "0",
         "Limit API calls per api_interval_in_sec seconds to\n"
         "this number.\n"
         "Determines the burst rate and the rate that new api\n"
         "calls will be made available. If set to 360 and\n"
         "api_intervals_in_sec is set to 3600, the 361st call in\n"
         "10 seconds results in a 429 error to the caller. It\n"
         "tells them to wait 10 seconds (3600/360) before making\n"
         "another api request. A value of 0 turns off rate\n"
         "limiting in the API. Tune this as needed. See rest\n"
         "documentation for more info.\n"),
        (IntegerNumberGtZeroOption, 'api_interval_in_sec', "3600",
         "Defines the interval in seconds over which an api client can\n"
         "make api_calls_per_interval api calls. Tune this as needed.\n"),
        (IntegerNumberGeqZeroOption, 'api_failed_login_limit', "4",
         "Limit login failure to the API per api_failed_login_interval_in_sec\n"
         "seconds.\n"
         "A value of 0 turns off failed login rate\n"
         "limiting in the API. You should not disable this. See rest\n"
         "documentation for more info.\n"),
        (IntegerNumberGtZeroOption, 'api_failed_login_interval_in_sec', "600",
         "Defines the interval in seconds over which api login failures\n"
         "are recorded. It allows api_failed_login_limit login failures\n"
         "in this time interval. Tune this as needed.\n"),
        (CsrfSettingOption, 'csrf_enforce_token', "yes",
            """How do we deal with @csrf fields in posted forms.
Set this to 'required' to block the post and notify
    the user if the field is missing or invalid.
Set this to 'yes' to block the post and notify the user
    if the token is invalid, but accept the form if
    the field is missing.
Set this to 'logfailure' to log a notice to the roundup
    log if the field is invalid or missing, but accept
    the post.
Set this to 'no' to ignore the field and accept the post.
            """),
        (IntegerNumberGeqZeroOption, 'csrf_token_lifetime', "20160",
            """csrf_tokens have a limited lifetime. If they are not
used they are purged from the database after this
number of minutes. Default (20160) is 2 weeks."""),
        (CsrfSettingOption, 'csrf_enforce_header_X-REQUESTED-WITH', "yes",
            """This is only used for xmlrpc and rest requests. This test is
done after Origin and Referer headers are checked. It only
verifies that the X-Requested-With header exists. The value
is ignored.
Set this to 'required' to block the post and notify
    the user if the header is missing or invalid.
Set this to 'yes' is the same as required.
Set this to 'logfailure' is the same as 'no'.
Set this to 'no' to ignore the header and accept the post."""),
        (CsrfSettingOption, 'csrf_enforce_header_referer', "yes",
            """Verify that the Referer http header matches the
tracker.web setting in config.ini.
Set this to 'required' to block the post and notify
    the user if the header is missing or invalid.
Set this to 'yes' to block the post and notify the user
    if the header is invalid, but accept the form if
    the header is missing.
Set this to 'logfailure' to log a notice to the roundup
    log if the header is invalid or missing, but accept
    the post.
Set this to 'no' to ignore the header and accept the post."""),
        (CsrfSettingOption, 'csrf_enforce_header_origin', "yes",
            """Verify that the Origin http header matches the
tracker.web setting in config.ini.
Set this to 'required' to block the post and notify
    the user if the header is missing or invalid.
Set this to 'yes' to block the post and notify the user
    if the header is invalid, but accept the form if
    the header is missing.
Set this to 'logfailure' to log a notice to the roundup
    log if the header is invalid or missing, but accept
    the post.
Set this to 'no' to ignore the header and accept the post."""),
        (OriginHeadersListOption, 'allowed_api_origins', "",
            """A comma separated list of additonal valid Origin header
values used when enforcing the header origin. They are used
only for the api URL's (/rest and /xmlrpc). They are not
used for the usual html URL's. These strings must match the
value of the Origin header exactly. So 'https://bar.edu' and
'https://Bar.edu' are two different Origin values. Note that
the origin value is scheme://host. There is no path
component. So 'https://bar.edu/' would never be valid.
The value '*' can be used to match any origin. It must be
first in the list if used. Note that this value allows
any web page on the internet to make anonymous requests
against your Roundup tracker.

You need to set these if you have a web application on a
different origin accessing your Roundup instance.

(The origin from the tracker.web setting in config.ini is
always valid and does not need to be specified.)"""),
        (CsrfSettingOption, 'csrf_enforce_header_x-forwarded-host', "yes",
            """Verify that the X-Forwarded-Host http header matches
the host part of the tracker.web setting in config.ini.
Set this to 'required' to block the post and notify
    the user if the header is missing or invalid.
Set this to 'yes' to block the post and notify the user
    if the header is invalid, but accept the form if
    the header is missing.
Set this to 'logfailure' to log a notice to the roundup
    log if the header is invalid or missing, but accept
    the post.
Set this to 'no' to ignore the header and accept the post."""),
        (CsrfSettingOption, 'csrf_enforce_header_host', "yes",
            """"If there is no X-Forward-Host header, verify that
the Host http header matches the host part of the
tracker.web setting in config.ini.
Set this to 'required' to block the post and notify
    the user if the header is missing or invalid.
Set this to 'yes' to block the post and notify the user
    if the header is invalid, but accept the form if
    the header is missing.
Set this to 'logfailure' to log a notice to the roundup
    log if the header is invalid or missing, but accept
    the post.
Set this to 'no' to ignore the header and accept the post."""),
        (IntegerNumberGeqZeroOption, 'csrf_header_min_count', "1",
            """Minimum number of header checks that must pass
to accept the request. Set to 0 to accept post
even if no header checks pass. Usually the Host header check
always passes, so setting it less than 1 is not recommended."""),
        (BooleanOption, 'use_browser_language', "yes",
            "Whether to use HTTP Accept-Language, if present.\n"
            "Browsers send a language-region preference list.\n"
            "It's usually set in the client's browser or in their\n"
            "Operating System.\n"
            "Set this option to 'no' if you want to ignore it."),
        (BooleanOption, "debug", "no",
            "Setting this option makes Roundup display error tracebacks\n"
            "in the user's browser rather than emailing them to the\n"
            "tracker admin."),
        (BooleanOption, "login_empty_passwords", "no",
            "Setting this option to yes/true allows users with\n"
            "an empty/blank password to login to the\n"
            "web/http interfaces."),
        (BooleanOption, "migrate_passwords", "yes",
            "Setting this option makes Roundup migrate passwords with\n"
            "an insecure password-scheme to a more secure scheme\n"
            "when the user logs in via the web-interface."),
        (SecretMandatoryOption, "secret_key", create_token(),
            "A per tracker secret used in etag calculations for\n"
            "an object. It must not be empty.\n"
            "It prevents reverse engineering hidden data in an object\n"
            "by calculating the etag for a sample object. Then modifying\n"
            "hidden properties until the sample object's etag matches\n"
            "the one returned by roundup.\n"
            "Changing this changes the etag and invalidates updates by\n"
            "clients. It must be persistent across application restarts.\n"
            "(Note the default value changes every time\n"
            "     roundup-admin updateconfig\n"
            "is run, so it must be explicitly set to a non-empty string.\n"),
        (ListSecretOption, "jwt_secret", "disabled",
            "This is used to sign/validate json web tokens\n"
            "(JWT). Even if you don't use JWTs it must not be\n"
            "empty. You can use multiple secrets separated by a\n"
            "comma ','. This allows for secret rotation. The newest\n"
            "secret should be placed first and used for signing. The\n"
            "rest of the secrets are used for validating an old JWT.\n"
            "If the first secret is less than 256 bits (32\n"
            "characters) in length JWTs are disabled. If other secrets\n"
            "are less than 32 chars, the application will exit. Removing\n"
            "a secret from this list invalidates all JWTs signed with\n"
            "the secret. JWT support is experimental and disabled by\n"
            "default. The secrets must be persistent across\n"
            "application restarts.\n"),
        (BooleanOption, "use_browser_date_input", "no",
            "HTML input elements for Date properties: This determines\n"
            "if we use the input type 'datetime-local' (or 'date') for\n"
            "date input fields. If the option is turned off (the default),\n"
            "the type is set to 'text'. Since the widgets generated by\n"
            "browsers determine the date format from the language\n"
            "setting (it is currently not possible to force the\n"
            "international date format server-side) and some browsers\n"
            "ignore the date format set by the operating system, the\n"
            "default is 'no'."),
        (BooleanOption, "use_browser_number_input", "no",
            "HTML input elements for Number properties: This determines\n"
            "if we use the input type 'number' for Number (and Integer)\n"
            "properties. If set to 'no' we use input type 'text'."),
    )),
    ("rdbms", (
        (DatabaseBackend, 'backend', NODEFAULT,
            "Database backend."),
        (BooleanOption, "debug_filter", "no",
	    "Filter debugging: Permissions can define additional filter\n"
            "functions that are used when checking permissions on results\n"
            "returned by the database. This is done to improve\n"
            "performance since the filtering is done in the database\n"
            "backend, not in python (at least for the SQL backends). The\n"
            "user is responsible for making the filter return the same\n"
            "set of results as the check function for a permission. So it\n"
            "makes sense to aid in debugging (and performance\n"
            "measurements) to allow turning off the usage of filter\n"
            "functions using only the check functions."),
        (Option, 'name', 'roundup',
            "Name of the database to use. For Postgresql, this can\n"
            "be database.schema to use a specific schema within\n"
            "a Postgres database.",
            ['MYSQL_DBNAME']),
        (NullableOption, 'host', 'localhost',
            "Database server host.",
            ['MYSQL_DBHOST']),
        (NullableOption, 'port', '',
            "TCP port number of the database server.\n"
            "Postgresql usually resides on port 5432 (if any),\n"
            "for MySQL default port number is 3306.\n"
            "Leave this option empty to use backend default"),
        (NullableOption, 'user', 'roundup',
            "Database user name that Roundup should use.",
            ['MYSQL_DBUSER']),
        (SecretNullableOption, 'password', 'roundup',
            "Database user password.",
            ['MYSQL_DBPASSWORD']),
        (NullableOption, 'service', '',
            "Name of the PostgreSQL connection service for this Roundup\n"
            "instance. Only used in Postgresql connections. You need to set\n"
            "up a pg_service.conf file usable by psql use this option."),
        (NullableOption, 'read_default_file', '~/.my.cnf',
            "Name of the MySQL defaults file.\n"
            "Only used in MySQL connections."),
        (NullableOption, 'read_default_group', 'roundup',
            "Name of the group to use in the MySQL defaults file (.my.cnf).\n"
            "Only used in MySQL connections."),
        (Option, 'mysql_charset', 'utf8mb4',
            "Charset to use for mysql connection and databases.\n"
            "If set to 'default', no charset option is used when\n"
            "creating the db connection and utf8mb4 is used for the\n"
            "database charset.\n"
            "Otherwise any permissible mysql charset is allowed here.\n"
            "Only used in MySQL connections."),
        (Option, 'mysql_collation', 'utf8mb4_unicode_ci',
            "Comparison/order to use for mysql database/table collations.\n"
            "When upgrading, you can use 'utf8' to match the\n"
            "depricated 'utf8mb3'. This must be compatible with the\n"
            "mysql_charset setting above. Only used by MySQL."),
        (Option, 'mysql_binary_collation', 'utf8mb4_0900_bin',
            "Comparison/order to use for mysql database/table collations\n"
            "when matching case. When upgrading, you can use 'utf8_bin'\n"
            "to match the depricated 'utf8mb3_bin' collation. This must\n"
            "be compatible with the mysql_collation above. Only used\n"
            "by MySQL."),
        (IntegerNumberGeqZeroOption, 'sqlite_timeout', '30',
            "Number of seconds to wait when the SQLite database is locked\n"
            "Default: use a 30 second timeout (extraordinarily generous)\n"
            "Only used in SQLite connections."),
        (IntegerNumberGeqZeroOption, 'cache_size', '100',
            "Size of the node cache (in elements). Used to keep the\n"
            "most recently used data in memory."),
        (BooleanOption, "allow_create", "yes",
            "Setting this option to 'no' protects the database against\n"
            "table creations."),
        (BooleanOption, "allow_alter", "yes",
            "Setting this option to 'no' protects the database against\n"
            "table alterations."),
        (BooleanOption, "allow_drop", "yes",
            "Setting this option to 'no' protects the database against\n"
            "table drops."),
        (NullableOption, 'template', '',
            "Name of the PostgreSQL template for database creation.\n"
            "For database creation the template used has to match\n"
            "the character encoding used (UTF8), there are different\n"
            "PostgreSQL installations using different templates with\n"
            "different encodings. If you get an error:\n"
            "  new encoding (UTF8) is incompatible with the encoding of\n"
            "  the template database (SQL_ASCII)\n"
            "  HINT:  Use the same encoding as in the template database,\n"
            "  or use template0 as template.\n"
            "then set this option to the template name given in the\n"
            "error message."),
        (IsolationOption, 'isolation_level', 'read committed',
            "Database isolation level, currently supported for\n"
            "PostgreSQL and mysql. See, e.g.,\n"
            "http://www.postgresql.org/docs/9.1/static/transaction-iso.html"),
        (BooleanOption, "serverside_cursor", "yes",
            "Set the database cursor for filter queries to serverside\n"
            "cursor, this avoids caching large amounts of data in the\n"
            "client. This option only applies for the postgresql backend."),
    ), "Most settings in this section (except for backend and debug_filter)\n"
       "are used by RDBMS backends only.",
    ),
    ("sessiondb", (
        (SessiondbBackendOption, "backend", "",
            "Set backend for storing one time key (otk) and session data.\n"
            "Values have to be compatible with main backend.\n"
            "main\\/ session>| anydbm | sqlite | redis | mysql | postgresql |\n"
            " anydbm        |    D   |        |   X   |       |            |\n"
            " sqlite        |    X   |    D   |   X   |       |            |\n"
            " mysql         |        |        |       |   D   |            |\n"
            " postgresql    |        |        |       |       |      D     |\n"
            " -------------------------------------------------------------+\n"
            "          D - default if unset,   X - compatible choice"),
        (RedisUrlOption, "redis_url",
            "redis://localhost:6379/0?health_check_interval=2",
            "URL used to connect to redis. Default uses unauthenticated\n"
            "redis database 0 running on localhost with default port.\n"),
    ), "Choose configuration for session and one time key storage."),
    ("logging", (
        (FilePathOption, "config", "",
            "Path to configuration file for standard Python logging module.\n"
            "If this option is set, logging configuration is loaded\n"
            "from specified file; options 'filename' and 'level'\n"
            "in this section are ignored."),
        (FilePathOption, "filename", "",
            "Log file name for minimal logging facility built into Roundup.\n"
            "If no file name specified, log messages are written on stderr.\n"
            "If above 'config' option is set, this option has no effect."),
        (Option, "level", "ERROR",
            "Minimal severity level of messages written to log file.\n"
            "If above 'config' option is set, this option has no effect.\n"
            "Allowed values: DEBUG, INFO, WARNING, ERROR"),
        (BooleanOption, "disable_loggers", "no",
            "If set to yes, only the loggers configured in this section will\n"
            "be used. Yes will disable gunicorn's --access-logfile.\n"),
    )),
    ("mail", (
        (Option, "domain", NODEFAULT,
            "The email domain that admin_email, issue_tracker and\n"
            "dispatcher_email belong to.\n"
            "This domain is added to those config items if they don't\n"
            "explicitly include a domain.\n"
            "Do not include the '@' symbol."),
        (Option, "host", NODEFAULT,
            "SMTP mail host that roundup will use to send mail",
            ["MAILHOST"]),
        (Option, "username", "", "SMTP login name.\n"
            "Set this if your mail host requires authenticated access.\n"
            "If username is not empty, password (below) MUST be set!"),
        (SecretMandatoryOption, "password", NODEFAULT, "SMTP login password.\n"
            "Set this if your mail host requires authenticated access."),
        (IntegerNumberGeqZeroOption, "port", smtplib.SMTP_PORT,
            "Default port to send SMTP on.\n"
            "Set this if your mail server runs on a different port."),
        (NullableOption, "local_hostname", '',
            "The (fully qualified) host/ domain name (FQDN) to use during\n"
            "SMTP sessions. If left blank, the underlying SMTP library will\n"
            "attempt to detect your FQDN. Set this if your mail server\n"
            "requires something specific.\n"),
        (BooleanOption, "tls", "no",
            "If your SMTP mail host provides or requires TLS\n"
            "(Transport Layer Security) then set this option to 'yes'."),
        (NullableFilePathOption, "tls_keyfile", "",
            "If TLS is used, you may set this option to the name\n"
            "of a PEM formatted file that contains your private key."),
        (NullableFilePathOption, "tls_certfile", "",
            "If TLS is used, you may set this option to the name\n"
            "of a PEM formatted certificate chain file."),
        (Option, "charset", "utf-8",
            "Character set to encode email headers with.\n"
            "We use utf-8 by default, as it's the most flexible.\n"
            "Some mail readers (eg. Eudora) can't cope with that,\n"
            "so you might need to specify a more limited character set\n"
            "(eg. iso-8859-1).",
            ["EMAIL_CHARSET"]),
        (FilePathOption, "debug", "",
            "Setting this option makes Roundup write all outgoing email\n"
            "messages to this file *instead* of sending them.\n"
            "This option has the same effect as the environment variable\n"
            "SENDMAILDEBUG.\nEnvironment variable takes precedence."),
        (BooleanOption, "add_authorinfo", "yes",
            "Add a line with author information at top of all messages\n"
            "sent by roundup"),
        (BooleanOption, "add_authoremail", "yes",
            "Add the mail address of the author to the author information\n"
            "at the top of all messages.\n"
            "If this is false but add_authorinfo is true, only the name\n"
            "of the actor is added which protects the mail address of the\n"
            "actor from being exposed at mail archives, etc."),
    ), "Outgoing email options.\n"
     "Used for nosy messages, password reset and registration approval\n"
     "requests."),
    ("mailgw", (
        (EmailBodyOption, "keep_quoted_text", "yes",
            "Keep email citations when accepting messages.\n"
            'Setting this to "no" strips out "quoted" text\n'
            'from the message. Setting this to "new" keeps quoted\n'
            "text only if a new issue is being created.\n"
            "Signatures are also stripped.",
            ["EMAIL_KEEP_QUOTED_TEXT"]),
        (EmailBodyOption, "leave_body_unchanged", "no",
            'Setting this to "yes" preserves the email body\n'
            "as is - that is, keep the citations _and_ signatures.\n"
            'Setting this to "new" keeps the body only if we are\n'
            "creating a new issue.",
            ["EMAIL_LEAVE_BODY_UNCHANGED"]),
        (Option, "default_class", "issue",
            "Default class to use in the mailgw\n"
            "if one isn't supplied in email subjects.\n"
            "To disable, leave the value blank.",
            ["MAIL_DEFAULT_CLASS"]),
        (NullableOption, "language", "",
            "Default locale name for the tracker mail gateway.\n"
            "If this option is not set, mail gateway will use\n"
            "the language of the tracker instance."),
        (Option, "subject_prefix_parsing", "strict",
            "Controls the parsing of the [prefix] on subject\n"
            'lines in incoming emails. "strict" will return an\n'
            "error to the sender if the [prefix] is not recognised.\n"
            '"loose" will attempt to parse the [prefix] but just\n'
            "pass it through as part of the issue title if not\n"
            'recognised. "none" will always pass any [prefix]\n'
            "through as part of the issue title."),
        (Option, "subject_suffix_parsing", "strict",
            "Controls the parsing of the [suffix] on subject\n"
            'lines in incoming emails. "strict" will return an\n'
            "error to the sender if the [suffix] is not recognised.\n"
            '"loose" will attempt to parse the [suffix] but just\n'
            "pass it through as part of the issue title if not\n"
            'recognised. "none" will always pass any [suffix]\n'
            "through as part of the issue title."),
        (Option, "subject_suffix_delimiters", "[]",
            "Defines the brackets used for delimiting the prefix and \n"
            'suffix in a subject line. The presence of "suffix" in\n'
            "the config option name is a historical artifact and may\n"
            "be ignored."),
        (Option, "subject_content_match", "always",
            "Controls matching of the incoming email subject line\n"
            "against issue titles in the case where there is no\n"
            'designator [prefix]. "never" turns off matching.\n'
            '"creation + interval" or "activity + interval"\n'
            "will match an issue for the interval after the issue's\n"
            "creation or last activity. The interval is a standard\n"
            "Roundup interval."),
        (BooleanOption, "subject_updates_title", "yes",
            "Update issue title if incoming subject of email is different.\n"
            'Setting this to "no" will ignore the title part of'
            " the subject\nof incoming email messages.\n"),
        (RegExpOption, "refwd_re", r"(\s*\W?\s*(fw|fwd|re|aw|sv|ang)\W)+",
            "Regular expression matching a single reply or forward\n"
            "prefix prepended by the mailer. This is explicitly\n"
            "stripped from the subject during parsing."),
        (RegExpOption, "origmsg_re",
            r"^[>|\s]*-----\s?Original Message\s?-----$",
            "Regular expression matching start of an original message\n"
            "if quoted the in body."),
        (RegExpOption, "sign_re", r"^[>|\s]*-- ?$",
            "Regular expression matching the start of a signature\n"
            "in the message body."),
        (RegExpOption, "eol_re", r"[\r\n]+",
            "Regular expression matching end of line."),
        (RegExpOption, "blankline_re", r"[\r\n]+\s*[\r\n]+",
            "Regular expression matching a blank line."),
        (BooleanOption, "unpack_rfc822", "no",
            "Unpack attached messages (encoded as message/rfc822 in MIME)\n"
            "as multiple parts attached as files to the issue, if not\n"
            "set we handle message/rfc822 attachments as a single file."),
        (BooleanOption, "ignore_alternatives", "no",
            "When parsing incoming mails, roundup uses the first\n"
            "text/plain part it finds. If this part is inside a\n"
            "multipart/alternative, and this option is set, all other\n"
            "parts of the multipart/alternative are ignored. The default\n"
            "is to keep all parts and attach them to the issue."),
        (HtmlToTextOption, "convert_htmltotext", "none",
            "If an email has only text/html parts, use this module\n"
            "to convert the html to text. Choose from beautifulsoup 4,\n"
            "dehtml - (internal code), or none to disable conversion.\n"
            "If 'none' is selected, email without a text/plain part\n"
            "will be returned to the user with a message. If\n"
            "beautifulsoup is selected but not installed dehtml will\n"
            "be used instead."),
        (BooleanOption, "keep_real_from", "no",
            "When handling emails ignore the Resent-From:-header\n"
            "and use the original senders From:-header instead.\n"
            "(This might be desirable in some situations where a moderator\n"
            "reads incoming messages first before bouncing them to Roundup)",
            ["EMAIL_KEEP_REAL_FROM"]),
     ), "Roundup Mail Gateway options"),
    ("pgp", (
        (BooleanOption, "enable", "no",
            "Enable PGP processing. Requires gpg. If you're planning\n"
            "to send encrypted PGP mail to the tracker, you should also\n"
            "enable the encrypt-option below, otherwise mail received\n"
            "encrypted might be sent unencrypted to another user."),
        (NullableOption, "roles", "",
            "If specified, a comma-separated list of roles to perform\n"
            "PGP processing on. If not specified, it happens for all\n"
            "users. Note that received PGP messages (signed and/or\n"
            "encrypted) will be processed with PGP even if the user\n"
            "doesn't have one of the PGP roles, you can use this to make\n"
            "PGP processing completely optional by defining a role here\n"
            "and not assigning any users to that role."),
        (NullableOption, "homedir", "",
            "Location of PGP directory. Defaults to $HOME/.gnupg if\n"
            "not specified."),
        (BooleanOption, "encrypt", "no",
            "Enable PGP encryption. All outgoing mails are encrypted.\n"
            "This requires that keys for all users (with one of the gpg\n"
            "roles above or all users if empty) are available. Note that\n"
            "it makes sense to educate users to also send mails encrypted\n"
            "to the tracker, to enforce this, set 'require_incoming'\n"
            "option below (but see the note)."),
        (Option, "require_incoming", "signed",
            "Require that pgp messages received by roundup are either\n"
            "'signed', 'encrypted' or 'both'. If encryption is required\n"
            "we do not return the message (in clear) to the user but just\n"
            "send an informational message that the message was rejected.\n"
            "Note that this still presents known-plaintext to an attacker\n"
            "when the users sends the mail a second time with encryption\n"
            "turned on."),
    ), "OpenPGP mail processing options"),
    ("nosy", (
        (Option, "messages_to_author", "no",
            "Send nosy messages to the author of the message.\n"
            "Allowed values: yes, no, new, nosy -- if yes, messages\n"
            "are sent to the author even if not on the nosy list, same\n"
            "for new (but only for new messages). When set to nosy,\n"
            "the nosy list controls sending messages to the author.",
            ["MESSAGES_TO_AUTHOR"]),
        (Option, "signature_position", "bottom",
            "Where to place the email signature.\n"
            "Allowed values: top, bottom, none",
            ["EMAIL_SIGNATURE_POSITION"]),
        (RunDetectorOption, "add_author", "new",
            "Does the author of a message get placed on the nosy list\n"
            "automatically?  If 'new' is used, then the author will\n"
            "only be added when a message creates a new issue.\n"
            "If 'yes', then the author will be added on followups too.\n"
            "If 'no', they're never added to the nosy.\n",
            ["ADD_AUTHOR_TO_NOSY"]),
        (RunDetectorOption, "add_recipients", "new",
            "Do the recipients (To:, Cc:) of a message get placed on the\n"
            "nosy list?  If 'new' is used, then the recipients will\n"
            "only be added when a message creates a new issue.\n"
            "If 'yes', then the recipients will be added on followups too.\n"
            "If 'no', they're never added to the nosy.\n",
            ["ADD_RECIPIENTS_TO_NOSY"]),
        (Option, "email_sending", "single",
            "Controls the email sending from the nosy reactor. If\n"
            '"multiple" then a separate email is sent to each\n'
            'recipient. If "single" then a single email is sent with\n'
            "each recipient as a CC address."),
        (IntegerNumberGeqZeroOption, "max_attachment_size", sys.maxsize,
            "Attachments larger than the given number of bytes\n"
            "won't be attached to nosy mails. They will be replaced by\n"
            "a link to the tracker's download page for the file."),
    ), "Nosy messages sending"),
    ("markdown", (
        (BooleanOption, "break_on_newline", "no",
            "If yes/true, render single new line characters in markdown\n"
            "text with <br>. Set true if you want GitHub Flavored Markdown\n"
            "(GFM) handling of embedded newlines."),
    ), "Markdown rendering options."),
)

# Configuration classes


class Config:

    """Base class for configuration objects.

    Configuration options may be accessed as attributes or items
    of instances of this class.  All option names are uppercased.

    """

    # Config file name
    INI_FILE = "config.ini"

    # Object attributes that should not be taken as common configuration
    # options in __setattr__ (most of them are initialized in constructor):
    # builtin pseudo-option - package home directory
    HOME = "."
    # names of .ini file sections, in order
    sections = None
    # section comments
    section_descriptions = None
    # lists of option names for each section, in order
    section_options = None
    # mapping from option names and aliases to Option instances
    options = None
    # actual name of the config file.  set on load.
    filepath = os.path.join(HOME, INI_FILE)

    # List of option names that need additional validation after
    # all options are loaded.
    option_validators = None

    def __init__(self, config_path=None, layout=None, settings=None):
        """Initialize confing instance

        Parameters:
            config_path:
                optional directory or file name of the config file.
                If passed, load the config after processing layout (if any).
                If config_path is a directory name, use default base name
                of the config file.
            layout:
                optional configuration layout, a sequence of
                section definitions suitable for .add_section()
            settings:
                optional setting overrides (dictionary).
                The overrides are applied after loading config file.

        """
        if settings is None:
            settings = {}
        # initialize option containers:
        self.sections = []
        self.section_descriptions = {}
        self.section_options = {}
        self.options = {}
        self.option_validators = []
        # add options from the layout structure
        if layout:
            for section in layout:
                self.add_section(*section)
        if config_path is not None:
            self.load(config_path)
        for (name, value) in settings.items():
            self[name.upper()] = value

    def add_section(self, section, options, description=None):
        """Define new config section

        Parameters:
            section - name of the config.ini section
            options - a sequence of Option definitions.
                Each Option definition is a sequence
                containing class object and constructor
                parameters, starting from the setting name:
                setting, default, [description, [aliases]]
            description - optional section comment

        Note: aliases should only exist in historical options
        for backwards compatibility - new options should
        *not* have aliases!

        """
        if description or (section not in self.section_descriptions):
            self.section_descriptions[section] = description
        for option_def in options:
            klass = option_def[0]
            args = option_def[1:]
            option = klass(self, section, *args)
            self.add_option(option)

    def add_option(self, option):
        """Adopt a new Option object"""
        _section = option.section
        _name = option.setting
        if _section not in self.sections:
            self.sections.append(_section)
        _options = self._get_section_options(_section)
        if _name not in _options:
            _options.append(_name)
        # (section, name) key is used for writing .ini file
        self.options[(_section, _name)] = option
        # make the option known under all of its A.K.A.s
        for _name in option.aliases:
            self.options[_name] = option

        if hasattr(option, 'validate'):
            self.option_validators.append(option.name)

    def update_option(self, name, klass,
                      default=NODEFAULT, description=None):
        """Override behaviour of early created option.

        Parameters:
            name:
                option name
            klass:
                one of the Option classes
            default:
                optional default value for the option
            description:
                optional new description for the option

        Conversion from current option value to new class value
        is done via string representation.

        This method may be used to attach some brains
        to options autocreated by UserConfig.

        """
        # fetch current option
        option = self._get_option(name)
        # compute constructor parameters
        if default is NODEFAULT:
            default = option.default
        if description is None:
            description = option.description
        value = option.value2str(current=1)
        # resurrect the option
        option = klass(self, option.section, option.setting,
                       default=default, description=description)
        # apply the value
        option.set(value)
        # incorporate new option
        del self[name]
        self.add_option(option)

    def reset(self):
        """Set all options to their default values"""
        for _option in self.items():
            _option.reset()

    # Meant for commandline tools.
    # Allows automatic creation of configuration files like this:
    #  roundup-server -p 8017 -u roundup --save-config
    def getopt(self, args, short_options="", long_options=(),
               config_load_options=("C", "config"), **options):
        """Apply options specified in command line arguments.

        Parameters:
            args:
                command line to parse (sys.argv[1:])
            short_options:
                optional string of letters for command line options
                that are not config options
            long_options:
                optional list of names for long options
                that are not config options
            config_load_options:
                two-element sequence (letter, long_option) defining
                the options for config file.  If unset, don't load
                config file; otherwise config file is read prior
                to applying other options.  Short option letter
                must not have a colon and long_option name must
                not have an equal sign or '--' prefix.
            options:
                mapping from option names to command line option specs.
                e.g. server_port="p:", server_user="u:"
                Names are forced to lower case for commandline parsing
                (long options) and to upper case to find config options.
                Command line options accepting no value are assumed
                to be binary and receive value 'yes'.

        Return value: same as for python standard getopt(), except that
        processed options are removed from returned option list.

        """
        # take a copy of long_options
        long_options = list(long_options)
        # build option lists
        cfg_names = {}
        booleans = []
        for (name, letter) in options.items():
            cfg_name = name.upper()
            short_opt = "-" + letter[0]
            name = name.lower().replace("_", "-")  # noqa: PLW2901 change name
            cfg_names.update({short_opt: cfg_name, "--" + name: cfg_name})

            short_options += letter
            if letter[-1] == ":":
                long_options.append(name + "=")
            else:
                booleans.append(short_opt)
                long_options.append(name)

        if config_load_options:
            short_options += config_load_options[0] + ":"
            long_options.append(config_load_options[1] + "=")
            # compute names that will be searched in getopt return value
            config_load_options = (
                "-" + config_load_options[0],
                "--" + config_load_options[1],
            )
        # parse command line arguments
        optlist, args = getopt.getopt(args, short_options, long_options)
        # load config file if requested
        if config_load_options:
            for option in optlist:
                if option[0] in config_load_options:
                    self.load_ini(option[1])
                    optlist.remove(option)
                    break
        # apply options
        extra_options = []
        for (opt, arg) in optlist:
            if (opt in booleans):  # and not arg
                arg = "yes"  # noqa: PLW2901 -- change arg
            try:
                name = cfg_names[opt]
            except KeyError:
                extra_options.append((opt, arg))
            else:
                self[name] = arg
        return (extra_options, args)

    # option and section locators (used in option access methods)

    def _get_option(self, name):
        try:
            return self.options[name]
        except KeyError:
            raise InvalidOptionError(name)

    def _get_section_options(self, name):
        return self.section_options.setdefault(name, [])

    def _get_unset_options(self):
        """Return options that need manual adjustments

        Return value is a dictionary where keys are section
        names and values are lists of option names as they
        appear in the config file.

        """
        need_set = {}
        for option in self.items():
            if not option.isset():
                need_set.setdefault(option.section, []).append(option.setting)
        return need_set

    def _adjust_options(self, config):
        """Load ad-hoc option definitions from ConfigParser instance."""
        pass

    def _get_name(self):
        """Return the service name for config file heading"""
        return ""

    # file operations

    def load_ini(self, config_path, defaults=None):
        """Set options from config.ini file in given home_dir

        Parameters:
            config_path:
                directory or file name of the config file.
                If config_path is a directory name, use default
                base name of the config file
            defaults:
                optional dictionary of defaults for ConfigParser

        Note: if home_dir does not contain config.ini file,
        no error is raised.  Config will be reset to defaults.

        """
        if os.path.isdir(config_path):
            home_dir = config_path
            config_path = os.path.join(config_path, self.INI_FILE)
        else:
            home_dir = os.path.dirname(config_path)
        # parse the file
        config_defaults = {"HOME": home_dir}
        if defaults:
            config_defaults.update(defaults)
        config = configparser.ConfigParser(config_defaults)
        config.read([config_path])
        # .ini file loaded ok.
        self.HOME = home_dir
        self.filepath = config_path
        self._adjust_options(config)
        # set the options, starting from HOME
        self.reset()
        for option in self.items():
            option.load_ini(config)

    def load(self, home_dir):
        """Load configuration settings from home_dir"""
        self.load_ini(home_dir)

    def save(self, ini_file=None):
        """Write current configuration to .ini file

        'ini_file' argument, if passed, must be valid full path
        to the file to write.  If omitted, default file in current
        HOME is created.

        If the file to write already exists, it is saved with '.bak'
        extension.

        """
        if ini_file is None:
            ini_file = self.filepath
        _tmp_file = os.path.splitext(ini_file)[0]
        _bak_file = _tmp_file + ".bak"
        _tmp_file = _tmp_file + ".tmp"
        with open(_tmp_file, "wt") as _fp:
            _fp.write("# %s configuration file\n" % self._get_name())
            _fp.write("# Autogenerated at %s\n" % time.asctime())
            need_set = self._get_unset_options()
            if need_set:
                _fp.write("\n# WARNING! Following options need adjustments:\n")
                for section, options in need_set.items():
                    _fp.write("#  [%s]: %s\n" % (section, ", ".join(options)))
            for section in self.sections:
                comment = self.section_descriptions.get(section, None)
                if comment:
                    _fp.write("\n# ".join([""] + comment.split("\n")) + "\n")
                else:
                    # no section comment - just leave a blank line between sections
                    _fp.write("\n")
                _fp.write("[%s]\n" % section)
                for option in self._get_section_options(section):
                    _fp.write("\n" + self.options[(section, option)].format())

        if os.access(ini_file, os.F_OK):
            if os.access(_bak_file, os.F_OK):
                os.remove(_bak_file)
            os.rename(ini_file, _bak_file)
        os.rename(_tmp_file, ini_file)

    # container emulation

    def __len__(self):
        return len(self.items())

    def __getitem__(self, name):
        if name == "HOME":
            return self.HOME
        else:
            return self._get_option(name).get()

    def __setitem__(self, name, value):
        if name == "HOME":
            self.HOME = value
        else:
            self._get_option(name).set(value)

    def __delitem__(self, name):
        _option = self._get_option(name)
        _section = _option.section
        _name = _option.setting
        self._get_section_options(_section).remove(_name)
        del self.options[(_section, _name)]
        for _alias in _option.aliases:
            del self.options[_alias]

    def items(self):
        """Return the list of Option objects, in .ini file order

        Note that HOME is not included in this list
        because it is builtin pseudo-option, not a real Option
        object loaded from or saved to .ini file.

        """
        return [self.options[(_section, _name)]
                for _section in self.sections
                for _name in self._get_section_options(_section)]

    def keys(self):
        """Return the list of "canonical" names of the options

        Unlike .items(), this list also includes HOME

        """
        return ["HOME"] + [_option.name for _option in self.items()]

    # .values() is not implemented because i am not sure what should be
    # the values returned from this method: Option instances or config values?

    # attribute emulation

    def __setattr__(self, name, value):
        if (name in self.__dict__) or hasattr(self.__class__, name):
            self.__dict__[name] = value
        else:
            self._get_option(name).set(value)

    # Note: __getattr__ is not symmetric to __setattr__:
    #   self.__dict__ lookup is done before calling this method
    def __getattr__(self, name):
        return self[name]


class UserConfig(Config):

    """Configuration for user extensions.

    Instances of this class have no predefined configuration layout.
    Options are created on the fly for each setting present in the
    config file.

    """

    def _adjust_options(self, config):
        # config defaults appear in all sections.
        # we'll need to filter them out.
        defaults = list(config.defaults().keys())
        # see what options are already defined and add missing ones
        preset = [(option.section, option.setting) for option in self.items()]
        for section in config.sections():
            for name in config.options(section):
                if ((section, name) not in preset) \
                   and (name not in defaults):
                    self.add_option(Option(self, section, name))


class CoreConfig(Config):

    """Roundup instance configuration.

    Core config has a predefined layout (see the SETTINGS structure),
    two additional attributes:
        detectors:
            user-defined configuration for detectors
        ext:
            user-defined configuration for extensions

    """

    # user configs
    ext = None
    detectors = None

    def __init__(self, home_dir=None, settings=None):
        if settings is None:
            settings = {}
        Config.__init__(self, home_dir, layout=SETTINGS, settings=settings)
        # load the config if home_dir given
        if home_dir is None:
            self.init_logging()

    def copy(self):
        new = CoreConfig()
        new.sections = list(self.sections)
        new.section_descriptions = dict(self.section_descriptions)
        new.section_options = dict(self.section_options)
        new.options = dict(self.options)
        return new

    def _get_unset_options(self):
        need_set = Config._get_unset_options(self)
        # remove MAIL_PASSWORD if MAIL_USER is empty
        if "password" in need_set.get("mail", []) and \
           not self["MAIL_USERNAME"]:
            settings = need_set["mail"]
            settings.remove("password")
            if not settings:
                del need_set["mail"]
        return need_set

    def _get_name(self):
        return self["TRACKER_NAME"]

    def reset(self):
        Config.reset(self)
        if self.ext:
            self.ext.reset()
        if self.detectors:
            self.detectors.reset()
        self.init_logging()

    def init_logging(self):
        _file = self["LOGGING_CONFIG"]
        if _file and os.path.isfile(_file):
            logging.config.fileConfig(
                _file,
                disable_existing_loggers=self["LOGGING_DISABLE_LOGGERS"])
            return

        _file = self["LOGGING_FILENAME"]
        # set file & level on the roundup logger
        logger = logging.getLogger('roundup')
        hdlr = logging.FileHandler(_file) if _file else \
            logging.StreamHandler(sys.stdout)

        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s %(message)s')
        hdlr.setFormatter(formatter)
        # no logging API to remove all existing handlers!?!
        for h in logger.handlers:
            h.close()
            logger.removeHandler(hdlr)
        logger.handlers = [hdlr]
        logger.setLevel(self["LOGGING_LEVEL"] or "ERROR")

    def validator(self, options):
        """ Validate options once all options are loaded.

            Used to validate settings when options are dependent
            on each other. E.G. indexer_language can only be
            validated if xapian indexer is used.
        """

        for option in self.option_validators:
            # validate() should throw an exception if there is an issue.
            options[option].validate(options)

    def load(self, home_dir):
        """Load configuration from path designated by home_dir argument"""
        if os.path.isfile(os.path.join(home_dir, self.INI_FILE)):
            self.load_ini(home_dir)
        else:
            raise NoConfigError(home_dir)

        # validator does inter-setting validation checks.
        # when there are dependencies between options.
        self.validator(self.options)

        self.init_logging()
        self.ext = UserConfig(os.path.join(home_dir, "extensions"))
        self.detectors = UserConfig(os.path.join(home_dir, "detectors"))

    def load_ini(self, home_dir, defaults=None):
        """Set options from config.ini file in given home_dir directory"""
        config_defaults = {"TRACKER_HOME": home_dir}
        if defaults:
            config_defaults.update(defaults)
        Config.load_ini(self, home_dir, config_defaults)

    # in this config, HOME is also known as TRACKER_HOME
    def __getitem__(self, name):
        if name == "TRACKER_HOME":
            return self.HOME
        else:
            return Config.__getitem__(self, name)

    def __setitem__(self, name, value):
        if name == "TRACKER_HOME":
            self.HOME = value
        else:
            self._get_option(name).set(value)

    def __setattr__(self, name, value):
        if name == "TRACKER_HOME":
            self.__dict__["HOME"] = value
        else:
            Config.__setattr__(self, name, value)

# vim: set et sts=4 sw=4 :
