# Roundup Issue Tracker configuration support
#
# $Id: configuration.py,v 1.11 2004-07-27 01:18:25 richard Exp $
#
__docformat__ = "restructuredtext"

import imp
import os
import time
import ConfigParser

from roundup import rlog
# XXX i don't think this module needs string translation, does it?

### Exceptions

class ConfigurationError(Exception):

    # without this, pychecker complains about missing class attribute...
    args = ()

class NoConfigError(ConfigurationError):

    """Raised when configuration loading fails

    Constructor parameters: path to the directory that was used as TRACKER_HOME

    """

    def __str__(self):
        return "No valid configuration files found in directory %s" \
            % self.args[0]

class InvalidOptionError(ConfigurationError, KeyError, AttributeError):

    """Attempted access to non-existing configuration option

    Configuration options may be accessed as configuration object
    attributes or items.  So this exception instances also are
    instances of KeyError (invalid item access) and AttrributeError
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

### Option classes

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
        default=NODEFAULT, description=None, aliases=None
    ):
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
        if default is NODEFAULT:
            _value = default
        else:
            _value = self.str2value(default)
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

    def value2str(self, value):
        """Return 'value' argument converted to external representation"""
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
        """Return True if the value is avaliable (either set or default)"""
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
        if self.isset():
            _is_set = ""
        else:
            _is_set = "#"
        _rv = "# %(description)s\n# Default: %(default)s\n" \
            "%(is_set)s%(name)s = %(value)s\n" % {
                "description": "\n# ".join(_desc_lines),
                "default": self.value2str(self._default_value),
                "name": self.setting,
                "value": self.value2str(self._value),
                "is_set": _is_set
            }
        return _rv

    def load_ini(self, config):
        """Load value from ConfigParser object"""
        if config.has_option(self.section, self.setting):
            self.set(config.get(self.section, self.setting))

    def load_pyconfig(self, config):
        """Load value from old-style config (python module)"""
        for _name in self.aliases:
            if hasattr(config, _name):
                self.set(getattr(config, _name))
                break

class BooleanOption(Option):

    """Boolean option: yes or no"""

    class_description = "Allowed values: yes, no"

    def _value2str(self, value):
        if value:
            return "yes"
        else:
            return "no"

    def str2value(self, value):
        if type(value) == type(""):
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

class RunDetectorOption(Option):

    """When a detector is run: always, never or for new items only"""

    class_description = "Allowed values: yes, no, new"

    def str2value(self, value):
        _val = value.lower()
        if _val in ("yes", "no", "new"):
            return _val
        else:
            raise OptionValueError(self, value, self.class_description)

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

    Paths may be either absolute or relative to the TRACKER_HOME.

    """

    class_description = "The path may be either absolute" \
        " or relative to the tracker home."

    def get(self):
        _val = Option.get(self)
        if _val and not os.path.isabs(_val):
            _val = os.path.join(self.config["TRACKER_HOME"], _val)
        return _val

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

class NullableOption(Option):

    """Option that is set to None if it's string value is one of NULL strings

    Default nullable strings list contains empty string only.
    There is constructor parameter allowing to specify different nullables.

    Conversion to external representation returns the first of the NULL
    strings list when the value is None.

    """

    NULL_STRINGS = ("",)

    def __init__(self, config, section, setting,
        default=NODEFAULT, description=None, aliases=None,
        null_strings=NULL_STRINGS
    ):
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

### Main configuration layout.
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
        (FilePathOption, "templates", "html",
            "Path to the HTML templates directory."),
        (MailAddressOption, "admin_email", "roundup-admin",
            "Email address that roundup will complain to"
            " if it runs into trouble."),
        (MailAddressOption, "dispatcher_email", "roundup-admin",
            "The 'dispatcher' is a role that can get notified\n"
            "of new items to the database.\n"
            "It is used by the ERROR_MESSAGES_TO config setting."),
        (Option, "email_from_tag", "",
            "Additional text to include in the \"name\" part\n"
            "of the From: address used in nosy messages.\n"
            "If the sending user is \"Foo Bar\", the From: line\n"
            "is usually: \"Foo Bar\" <issue_tracker@tracker.example>\n"
            "the EMAIL_FROM_TAG goes inside the \"Foo Bar\" quotes like so:\n"
            "\"Foo Bar EMAIL_FROM_TAG\" <issue_tracker@tracker.example>"),
        (Option, "new_web_user_roles", "User",
            "Roles that a user gets when they register"
            " with Web User Interface.\n"
            "This is a comma-separated string of role names"
            " (e.g. 'Admin,User')."),
        (Option, "new_email_user_roles", "User",
            "Roles that a user gets when they register"
            " with Email Gateway.\n"
            "This is a comma-separated string of role names"
            " (e.g. 'Admin,User')."),
        (Option, "error_messages_to", "user",
            # XXX This description needs better wording,
            #   with explicit allowed values list.
            "Send error message emails to the dispatcher, user, or both?\n"
            "The dispatcher is configured using the DISPATCHER_EMAIL"
            " setting."),
        (Option, "html_version", "html4",
            "HTML version to generate. The templates are html4 by default.\n"
            "If you wish to make them xhtml, then you'll need to change this\n"
            "var to 'xhtml' too so all auto-generated HTML is compliant.\n"
            "Allowed values: html4, xhtml"),
        # It seems to me that all timezone offsets in the modern world
        # are integral hours.  However, there were fractional hour offsets
        # in the past.  Use float number for sure.
        (FloatNumberOption, "timezone", "0",
            "Numeric timezone offset used when users do not choose their own\n"
            "in their settings.",
            ["DEFAULT_TIMEZONE"]),
    )),
    ("tracker", (
        (Option, "name", "Roundup issue tracker",
            "A descriptive name for your roundup instance."),
        (Option, "web", NODEFAULT,
            "The web address that the tracker is viewable at.\n"
            "This will be included in information"
            " sent to users of the tracker.\n"
            "The URL MUST include the cgi-bin part or anything else\n"
            "that is required to get to the home page of the tracker.\n"
            "You MUST include a trailing '/' in the URL."),
        (MailAddressOption, "email", "issue_tracker",
            "Email address that mail to roundup should go to."),
    )),
    ("rdbms", (
        (Option, 'name', 'roundup',
            "Name of the Postgresql or MySQL database to use."),
        (NullableOption, 'host', 'localhost'
            "Hostname that the Postgresql or MySQL database resides on."),
        (NullableOption, 'port', '5432'
            "Port number that the Postgresql or MySQL database resides on."),
        (NullableOption, 'user', 'roundup'
            "Postgresql or MySQL database user that Roundup should use."),
        (NullableOption, 'password', 'roundup',
            "Password for the Postgresql or MySQL database user."),
    )),
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
    )),
    ("mail", (
        (Option, "domain", NODEFAULT, "Domain name used for email addresses."),
        (Option, "host", NODEFAULT,
            "SMTP mail host that roundup will use to send mail"),
        (Option, "username", "", "SMTP login name.\n"
            "Set this if your mail host requires authenticated access.\n"
            "If username is not empty, password (below) MUST be set!"),
        (Option, "password", NODEFAULT, "SMTP login password.\n"
            "Set this if your mail host requires authenticated access."),
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
            "Setting this option makes Roundup to write all outgoing email\n"
            "messages to this file *instead* of sending them.\n"
            "This option has the same effect as environment variable"
            " SENDMAILDEBUG.\nEnvironment variable takes precedence."),
    )),
    ("mailgw", (
        (BooleanOption, "keep_quoted_text", "yes",
            "Keep email citations when accepting messages.\n"
            "Setting this to \"no\" strips out \"quoted\" text"
            " from the message.\n"
            "Signatures are also stripped.",
            ["EMAIL_KEEP_QUOTED_TEXT"]),
        (BooleanOption, "leave_body_unchanged", "no",
            "Preserve the email body as is - that is,\n"
            "keep the citations _and_ signatures.",
            ["EMAIL_LEAVE_BODY_UNCHANGED"]),
        (Option, "default_class", "issue",
            "Default class to use in the mailgw\n"
            "if one isn't supplied in email subjects.\n"
            "To disable, leave the value blank.",
            ["MAIL_DEFAULT_CLASS"]),
    )),
    ("nosy", (
        (RunDetectorOption, "messages_to_author", "no",
            "Send nosy messages to the author of the message.",
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
    )),
)

### Main class

class Config:

    """Roundup instance configuration.

    Configuration options may be accessed as attributes or items
    of instances of this class.  All option names are uppercased.

    """

    # Config file names (in the TRACKER_HOME directory):
    INI_FILE = "config.ini" # new style config file name
    PYCONFIG = "config"     # module name for old style configuration

    # Object attributes that should not be taken as common configuration
    # options in __setattr__ (most of them are initialized in constructor):
    #   builtin pseudo-option - tracker home directory
    TRACKER_HOME = "."
    # names of .ini file sections, in order
    sections = None
    # lists of option names for each section, in order
    section_options = None
    # mapping from option names and aliases to Option instances
    options = None
    # logging engine
    logging = rlog.BasicLogging()

    def __init__(self, tracker_home=None):
        # initialize option containers:
        self.sections = []
        self.section_options = {}
        self.options = {}
        # add options from the SETTINGS structure
        for (_section, _options) in SETTINGS:
            for _option_def in _options:
                _class = _option_def[0]
                _args = _option_def[1:]
                _option = _class(self, _section, *_args)
                self.add_option(_option)
        # load the config if tracker_home given
        if tracker_home is None:
            self.init_logging()
        else:
            self.load(tracker_home)

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
        # make the option known under all of it's A.K.A.s
        for _name in option.aliases:
            self.options[_name] = option

    def reset(self):
        """Set all options to their default values"""
        for _option in self.items():
            _option.reset()
        self.init_logging()

    def init_logging(self):
        _file = self["LOGGING_CONFIG"]
        if _file and os.path.isfile(_file):
            try:
                import logging
                _logging = logging
            except ImportError, _err:
                _option = self._get_option("LOGGING_CONFIG")
                raise OptionValueError(_option, _file,
                    "Python logging module is not available: %s" % _err)
            _logging.fileConfig(_file)
        else:
            _logging = rlog.BasicLogging()
            _file = self["LOGGING_FILENAME"]
            if _file:
                _logging.setFile(_file)
            _logging.setLevel(self["LOGGING_LEVEL"] or "ERROR")
        self.logging = _logging

    # option and section locators (used in option access methods)

    def _get_option(self, name):
        try:
            return self.options[name]
        except KeyError:
            raise InvalidOptionError(name)

    def _get_section_options(self, name):
        return self.section_options.setdefault(name, [])

    # file operations

    def load(self, tracker_home):
        """Load configuration from path designated by tracker_home argument"""
        if os.path.isfile(os.path.join(tracker_home, self.INI_FILE)):
            self.load_ini(tracker_home)
        else:
            self.load_pyconfig(tracker_home)

    def load_ini(self, tracker_home):
        """Set options from config.ini file in given tracker_home directory"""
        # parse the file
        _config = ConfigParser.ConfigParser({"TRACKER_HOME": tracker_home})
        _config.read([os.path.join(tracker_home, self.INI_FILE)])
        # .ini file loaded ok.  set the options, starting from TRACKER_HOME
        self.reset()
        self.TRACKER_HOME = tracker_home
        for _option in self.items():
            _option.load_ini(_config)
        self.init_logging()

    def load_pyconfig(self, tracker_home):
        """Set options from config.py file in given tracker_home directory"""
        # try to locate and import the module
        _mod_fp = None
        try:
            try:
                _module = imp.find_module(self.PYCONFIG, [tracker_home])
                _mod_fp = _module[0]
                _config = imp.load_module(self.PYCONFIG, *_module)
            except ImportError:
                raise NoConfigError(tracker_home)
        finally:
            if _mod_fp is not None:
                _mod_fp.close()
        # module loaded ok.  set the options, starting from TRACKER_HOME
        self.reset()
        self.TRACKER_HOME = tracker_home
        for _option in self.items():
            _option.load_pyconfig(_config)
        self.init_logging()
        # backward compatibility:
        # SMTP login parameters were specified as a tuple in old style configs
        # convert them to new plain string options
        _mailuser = getattr(_config, "MAILUSER", ())
        if len(_mailuser) > 0:
            self.MAIL_USERNAME = _mailuser[0]
        if len(_mailuser) > 1:
            self.MAIL_PASSWORD = _mailuser[1]

    def save(self, ini_file=None):
        """Write current configuration to .ini file

        'ini_file' argument, if passed, must be valid full path
        to the file to write.  If omitted, default file in current
        TRACKER_HOME is created.

        If the file to write already exists, it is saved with '.bak'
        extension.

        """
        if ini_file is None:
            ini_file = os.path.join(self.TRACKER_HOME, self.INI_FILE)
        _tmp_file = os.path.splitext(ini_file)[0]
        _bak_file = _tmp_file + ".bak"
        _tmp_file = _tmp_file + ".tmp"
        _fp = file(_tmp_file, "wt")
        _fp.write("# %s configuration file\n" % self["TRACKER_NAME"])
        _fp.write("# Autogenerated at %s\n" % time.asctime())
        for _section in self.sections:
            _fp.write("\n[%s]\n" % _section)
            for _option in self._get_section_options(_section):
                _fp.write("\n" + self.options[(_section, _option)].format())
        _fp.close()
        if os.access(ini_file, os.F_OK):
            if os.access(_bak_file, os.F_OK):
                os.remove(_bak_file)
            os.rename(ini_file, _bak_file)
        os.rename(_tmp_file, ini_file)

    # container emulation

    def __len__(self):
        return len(self.items())

    def __getitem__(self, name):
        if name == "TRACKER_HOME":
            return self.TRACKER_HOME
        else:
            return self._get_option(name).get()

    def __setitem__(self, name, value):
        if name == "TRACKER_HOME":
            self.TRACKER_HOME = value
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

        Note that TRACKER_HOME is not included in this list
        because it is builtin pseudo-option, not a real Option
        object loaded from or saved to .ini file.

        """
        return [self.options[(_section, _name)]
            for _section in self.sections
            for _name in self._get_section_options(_section)
        ]

    def keys(self):
        """Return the list of "canonical" names of the options

        Unlike .items(), this list also includes TRACKER_HOME

        """
        return ["TRACKER_HOME"] + [_option.name for _option in self.items()]

    # .values() is not implemented because i am not sure what should be
    # the values returned from this method: Option instances or config values?

    # attribute emulation

    def __setattr__(self, name, value):
        if self.__dict__.has_key(name) \
        or self.__class__.__dict__.has_key(name):
            self.__dict__[name] = value
        else:
            self._get_option(name).set(value)

    # Note: __getattr__ is not symmetric to __setattr__:
    #   self.__dict__ lookup is done before calling this method
    __getattr__ = __getitem__

# vim: set et sts=4 sw=4 :
