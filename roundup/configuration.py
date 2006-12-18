# Roundup Issue Tracker configuration support
#
# $Id: configuration.py,v 1.39 2006-12-18 06:06:03 richard Exp $
#
__docformat__ = "restructuredtext"

import getopt
import imp
import os
import time
import ConfigParser
import logging, logging.config
import sys

import roundup.date

# XXX i don't think this module needs string translation, does it?

### Exceptions

class ConfigurationError(Exception):
    pass

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
        "to the directory containig this config file."

    def get(self):
        _val = Option.get(self)
        if _val and not os.path.isabs(_val):
            _val = os.path.join(self.config["HOME"], _val)
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

class OctalNumberOption(Option):

    """Octal Integer numbers"""

    def str2value(self, value):
        try:
            return int(value, 8)
        except ValueError:
            raise OptionValueError(self, value, "Octal Integer number required")

    def _value2str(self, value):
        return oct(value)

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

class TimezoneOption(Option):

    class_description = \
        "If pytz module is installed, value may be any valid\n" \
        "timezone specification (e.g. EET or Europe/Warsaw).\n" \
        "If pytz is not installed, value must be integer number\n" \
        "giving local timezone offset from UTC in hours."

    def str2value(self, value):
        try:
            roundup.date.get_timezone(value)
        except KeyError:
            raise OptionValueError(self, value,
                    "Timezone name or numeric hour offset required")
        return value

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
        (NullableFilePathOption, "static_files", "",
            "Path to directory holding additional static files\n"
            "available via Web UI.  This directory may contain\n"
            "sitewide images, CSS stylesheets etc. and is searched\n"
            "for these files prior to the TEMPLATES directory\n"
            "specified above.  If this option is not set, all static\n"
            "files are taken from the TEMPLATES directory"),
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
        (TimezoneOption, "timezone", "UTC", "Default timezone offset,"
            " applied when user's timezone is not set.",
            ["DEFAULT_TIMEZONE"]),
        (BooleanOption, "instant_registration", "no",
            "Register new users instantly, or require confirmation via\n"
            "email?"),
        (BooleanOption, "email_registration_confirmation", "yes",
            "Offer registration confirmation by email or only through the web?"),
        (WordListOption, "indexer_stopwords", "",
            "Additional stop-words for the full-text indexer specific to\n"
            "your tracker. See the indexer source for the default list of\n"
            "stop-words (eg. A,AND,ARE,AS,AT,BE,BUT,BY, ...)"),
        (OctalNumberOption, "umask", "02",
            "Defines the file creation mode mask."),
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
        (NullableOption, "language", "",
            "Default locale name for this tracker.\n"
            "If this option is not set, the language is determined\n"
            "by OS environment variable LANGUAGE, LC_ALL, LC_MESSAGES,\n"
            "or LANG, in that order of preference."),
    )),
    ("web", (
        (BooleanOption, 'http_auth', "yes",
            "Whether to use HTTP Basic Authentication, if present.\n"
            "Roundup will use either the REMOTE_USER or HTTP_AUTHORIZATION\n"
            "variables supplied by your web server (in that order).\n"
            "Set this option to 'no' if you do not wish to use HTTP Basic\n"
            "Authentication in your web interface."),
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
    )),
    ("rdbms", (
        (Option, 'name', 'roundup',
            "Name of the database to use.",
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
        (NullableOption, 'password', 'roundup',
            "Database user password.",
            ['MYSQL_DBPASSWORD']),
        (NullableOption, 'read_default_file', '~/.my.cnf',
            "Name of the MySQL defaults file.\n"
            "Only used in MySQL connections."),
        (NullableOption, 'read_default_group', 'roundup',
            "Name of the group to use in the MySQL defaults file (.my.cnf).\n"
            "Only used in MySQL connections."),
    ), "Settings in this section are used"
        " by Postgresql and MySQL backends only"
    ),
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
            "SMTP mail host that roundup will use to send mail",
            ["MAILHOST"],),
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
    ), "Outgoing email options.\nUsed for nozy messages and approval requests"),
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
        (NullableOption, "language", "",
            "Default locale name for the tracker mail gateway.\n"
            "If this option is not set, mail gateway will use\n"
            "the language of the tracker instance."),
        (Option, "subject_prefix_parsing", "strict",
            "Controls the parsing of the [prefix] on subject\n"
            "lines in incoming emails. \"strict\" will return an\n"
            "error to the sender if the [prefix] is not recognised.\n"
            "\"loose\" will attempt to parse the [prefix] but just\n"
            "pass it through as part of the issue title if not\n"
            "recognised. \"none\" will always pass any [prefix]\n"
            "through as part of the issue title."),
        (Option, "subject_suffix_parsing", "strict",
            "Controls the parsing of the [suffix] on subject\n"
            "lines in incoming emails. \"strict\" will return an\n"
            "error to the sender if the [suffix] is not recognised.\n"
            "\"loose\" will attempt to parse the [suffix] but just\n"
            "pass it through as part of the issue title if not\n"
            "recognised. \"none\" will always pass any [suffix]\n"
            "through as part of the issue title."),
        (Option, "subject_suffix_delimiters", "[]",
            "Defines the brackets used for delimiting the prefix and \n"
            'suffix in a subject line. The presence of "suffix" in\n'
            "the config option name is a historical artifact and may\n"
            "be ignored."),
        (Option, "subject_content_match", "always",
            "Controls matching of the incoming email subject line\n"
            "against issue titles in the case where there is no\n"
            "designator [prefix]. \"never\" turns off matching.\n"
            "\"creation + interval\" or \"activity + interval\"\n"
            "will match an issue for the interval after the issue's\n"
            "creation or last activity. The interval is a standard\n"
            "Roundup interval."),
    ), "Roundup Mail Gateway options"),
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
        (Option, "email_sending", "single",
            "Controls the email sending from the nosy reactor. If\n"
            "\"multiple\" then a separate email is sent to each\n"
            "recipient. If \"single\" then a single email is sent with\n"
            "each recipient as a CC address."),
    ), "Nosy messages sending"),
)

### Configuration classes

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

    def __init__(self, config_path=None, layout=None, settings={}):
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
        # initialize option containers:
        self.sections = []
        self.section_descriptions = {}
        self.section_options = {}
        self.options = {}
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
        if description or not self.section_descriptions.has_key(section):
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
        # make the option known under all of it's A.K.A.s
        for _name in option.aliases:
            self.options[_name] = option

    def update_option(self, name, klass,
        default=NODEFAULT, description=None
    ):
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
        config_load_options=("C", "config"), **options
    ):
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
            name = name.lower().replace("_", "-")
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
            if (opt in booleans): # and not arg
                arg = "yes"
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
        config = ConfigParser.ConfigParser(config_defaults)
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
        _fp = file(_tmp_file, "wt")
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
                _fp.write("\n# ".join([""] + comment.split("\n")) +"\n")
            else:
                # no section comment - just leave a blank line between sections
                _fp.write("\n")
            _fp.write("[%s]\n" % section)
            for option in self._get_section_options(section):
                _fp.write("\n" + self.options[(section, option)].format())
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
            for _name in self._get_section_options(_section)
        ]

    def keys(self):
        """Return the list of "canonical" names of the options

        Unlike .items(), this list also includes HOME

        """
        return ["HOME"] + [_option.name for _option in self.items()]

    # .values() is not implemented because i am not sure what should be
    # the values returned from this method: Option instances or config values?

    # attribute emulation

    def __setattr__(self, name, value):
        if self.__dict__.has_key(name) or hasattr(self.__class__, name):
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
        defaults = config.defaults().keys()
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
    supports loading of old-style pythonic configurations and holds
    three additional attributes:
        logging:
            instance logging engine, from standard python logging module
            or minimalistic logger implemented in Roundup
        detectors:
            user-defined configuration for detectors
        ext:
            user-defined configuration for extensions

    """

    # module name for old style configuration
    PYCONFIG = "config"
    # user configs
    ext = None
    detectors = None

    def __init__(self, home_dir=None, settings={}):
        Config.__init__(self, home_dir, layout=SETTINGS, settings=settings)
        # load the config if home_dir given
        if home_dir is None:
            self.init_logging()

    def _get_unset_options(self):
        need_set = Config._get_unset_options(self)
        # remove MAIL_PASSWORD if MAIL_USER is empty
        if "password" in need_set.get("mail", []):
            if not self["MAIL_USERNAME"]:
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
            logging.config.fileConfig(_file)
            return

        _file = self["LOGGING_FILENAME"]
        # set file & level on the root logger
        logger = logging.getLogger()
        if _file:
            hdlr = logging.FileHandler(_file)
        else:
            hdlr = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s %(message)s')
        hdlr.setFormatter(formatter)
        # no logging API to remove all existing handlers!?!
        logger.handlers = [hdlr]
        logger.setLevel(logging._levelNames[self["LOGGING_LEVEL"] or "ERROR"])

    def load(self, home_dir):
        """Load configuration from path designated by home_dir argument"""
        if os.path.isfile(os.path.join(home_dir, self.INI_FILE)):
            self.load_ini(home_dir)
        else:
            self.load_pyconfig(home_dir)
        self.init_logging()
        self.ext = UserConfig(os.path.join(home_dir, "extensions"))
        self.detectors = UserConfig(os.path.join(home_dir, "detectors"))

    def load_ini(self, home_dir, defaults=None):
        """Set options from config.ini file in given home_dir directory"""
        config_defaults = {"TRACKER_HOME": home_dir}
        if defaults:
            config_defaults.update(defaults)
        Config.load_ini(self, home_dir, config_defaults)

    def load_pyconfig(self, home_dir):
        """Set options from config.py file in given home_dir directory"""
        # try to locate and import the module
        _mod_fp = None
        try:
            try:
                _module = imp.find_module(self.PYCONFIG, [home_dir])
                _mod_fp = _module[0]
                _config = imp.load_module(self.PYCONFIG, *_module)
            except ImportError:
                raise NoConfigError(home_dir)
        finally:
            if _mod_fp is not None:
                _mod_fp.close()
        # module loaded ok.  set the options, starting from HOME
        self.reset()
        self.HOME = home_dir
        for _option in self.items():
            _option.load_pyconfig(_config)
        # backward compatibility:
        # SMTP login parameters were specified as a tuple in old style configs
        # convert them to new plain string options
        _mailuser = getattr(_config, "MAILUSER", ())
        if len(_mailuser) > 0:
            self.MAIL_USERNAME = _mailuser[0]
        if len(_mailuser) > 1:
            self.MAIL_PASSWORD = _mailuser[1]

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
