#! /usr/bin/env python
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
#

"""Administration commands for maintaining Roundup trackers.
"""
from __future__ import print_function

__docformat__ = 'restructuredtext'
import csv
import getopt
import getpass
import operator
import os
import re
import shutil
import sys

import roundup.instance
from roundup import __version__ as roundup_version
from roundup import date, hyperdb, init, password, token_r
from roundup.anypy.my_input import my_input
from roundup.anypy.strings import repr_export
from roundup.configuration import (
    CoreConfig,
    NoConfigError,
    Option,
    OptionUnsetError,
    OptionValueError,
    ParsingOptionError,
    UserConfig,
)
from roundup.exceptions import UsageError
from roundup.i18n import _, get_translation
from roundup import support

try:
    from UserDict import UserDict
except ImportError:
    from collections import UserDict


class CommandDict(UserDict):
    """Simple dictionary that lets us do lookups using partial keys.

    Original code submitted by Engelbert Gruber.
    """
    _marker = ('CommandDictMarker')

    def get(self, key, default=_marker):
        if key in self.data:
            return [(key, self.data[key])]
        keylist = sorted(self.data)

        matching_keys = [(ki, self.data[ki]) for ki in keylist
                          if ki.startswith(key)]

        if not matching_keys and default is self._marker:
            raise KeyError(key)
        # FIXME: what happens if default is not self._marker but
        # there are no matching keys? Should (default, self.data[default])
        # be returned???
        return matching_keys


class AdminTool:
    """ A collection of methods used in maintaining Roundup trackers.

        Typically these methods are accessed through the roundup-admin
        script. The main() method provided on this class gives the main
        loop for the roundup-admin script.

        Actions are defined by do_*() methods, with help for the action
        given in the method docstring.

        Additional help may be supplied by help_*() methods.
    """

    # Make my_input a property to allow overriding in testing.
    # my_input is imported in other places, so just set it from
    # the imported value rather than moving def here.
    my_input = my_input

    def __init__(self):
        self.commands = CommandDict()
        for k in AdminTool.__dict__:
            if k[:3] == 'do_':
                self.commands[k[3:]] = getattr(self, k)
        self.help = {}
        for k in AdminTool.__dict__:
            if k[:5] == 'help_':
                self.help[k[5:]] = getattr(self, k)
        self.tracker = None
        self.tracker_home = ''
        self.db = None
        self.db_uncommitted = False
        self._default_savepoint_setting = 10000
        self.force = None
        self.settings = {
            'display_header': False,
            'display_protected': False,
            'indexer_backend': "as set in config.ini",
            'history_features': 0,
            'history_length': -1,
            '_reopen_tracker': False,
            'savepoint_limit': self._default_savepoint_setting,
            'show_retired': "no",
            '_retired_val': False,
            'verbose': False,
            '_inttest': 3,
            '_floattest': 3.5,
        }
        self.settings_help = {
            'display_header':
            _("Have 'display designator[,designator*]' show header inside\n"
              "      []'s before items. Includes retired/active status.\n"),

            'display_protected':
            _("Have 'display designator' and 'specification class' show\n"
              "      protected fields: creator, id etc.\n"),

            'history_features':
            _("Controls history options. It is a bitstring where setting\n"
              "      the bit disables the feature. A value of 0 (default)\n"
              "      enables all features. Value 1 disables loading of\n"
              "      history.  Value 2 disables saving history. Value 4\n"
              "      disables loading init file. Since it is a bitstring a\n"
              "      value of 6 disables both loading init file and saving\n"
              "      history.\n"),

            'history_length':
            _("Set the number of lines of history to keep for this session.\n"
              "      -1 is infinite.\n"),

            'indexer_backend':
            _("Set indexer to use when running 'reindex' NYI\n"),

            '_reopen_tracker':
            _("Force reopening of tracker when running each command.\n"),

            'savepoint_limit':
            _("set the number of rows imported before a database commit is\n"
              "      done. Used only for imports on PostgreSQL.\n"),
            'show_retired': _("Show retired items in table, list etc. "
            "One of 'no', 'only', 'both'\n"),
            '_retired_val': _("internal mapping for show_retired.\n"),
            'verbose': _("Enable verbose output: tracing, descriptions...\n"),

            '_inttest': "Integer valued setting. For testing only.\n",
            '_floattest': "Float valued setting. For testing only.\n",
        }

    def get_class(self, classname):
        """Get the class - raise an exception if it doesn't exist.
        """
        try:
            return self.db.getclass(classname)
        except KeyError:
            raise UsageError(_('no such class "%(classname)s"') % locals())

    def props_from_args(self, args):
        """ Produce a dictionary of prop: value from the args list.

            The args list is specified as ``prop=value prop=value ...``.
            A missing value is recorded as None.
        """
        props = {}
        for arg in args:
            key_val = arg.split('=', 1)
            # if = not in string, will return one element
            if len(key_val) != 2:
                raise UsageError(_('argument "%(arg)s" not propname=value') %
                                 locals())
            key, value = key_val
            if value:
                props[key] = value
            else:
                props[key] = None
        return props

    def usage(self, message=''):
        """ Display a simple usage message.
        """
        if message:
            message = _('Problem: %(message)s\n\n') % locals()
        sys.stdout.write(_("""%(message)sUsage: roundup-admin [options] [<command> <arguments>]

Options:
 -i instance home  -- specify the issue tracker "home directory" to administer
 -u                -- the user[:password] to use for commands (default admin)
 -d                -- print full designators not just class id numbers
 -c                -- when outputting lists of data, comma-separate them.
                      Same as '-S ","'.
 -S <string>       -- when outputting lists of data, string-separate them
 -s                -- when outputting lists of data, space-separate them.
                      Same as '-S " "'.
 -P pragma=value   -- Set a pragma on command line rather than interactively.
                      Can be used multiple times.
 -V                -- be verbose when importing
 -v                -- report Roundup and Python versions (and quit)

 Only one of -s, -c or -S can be specified.

Help:
 roundup-admin -h
 roundup-admin help                       -- this help
 roundup-admin help <command>             -- command-specific help
 roundup-admin help all                   -- all available help
""") % locals())
        self.help_commands()

    def help_commands(self):
        """List the commands available with their help summary.
        """
        sys.stdout.write(_('Commands: '))
        commands = ['']
        for command in self.commands.values():
            h = _(command.__doc__).split('\n')[0]
            commands.append(' ' + h[7:])
        commands.sort()
        commands.append(_(
"""Commands may be abbreviated as long as the abbreviation
matches only one command, e.g. l == li == lis == list."""))
        sys.stdout.write('\n'.join(commands) + '\n\n')

    indent_re = re.compile(r'^(\s+)\S+')

    def help_commands_html(self, indent_re=indent_re):
        """ Produce an HTML command list.
        """
        commands = sorted(iter(self.commands.values()),
                          key=operator.attrgetter('__name__'))
        for command in commands:
            h = _(command.__doc__).split('\n')
            name = command.__name__[3:]
            usage = h[0]
            print("""
<tr><td valign=top><strong>%(name)s</strong></td>
    <td><tt>%(usage)s</tt><p>
<pre>""" % locals())
            indent = indent_re.match(h[3])
            if indent: indent = len(indent.group(1))  # noqa: E701
            for line in h[3:]:
                if indent:
                    print(line[indent:])
                else:
                    print(line)
            print('</pre></td></tr>\n')

    def help_all(self):
        print(_("""
All commands (except help) require a tracker specifier. This is just
the path to the roundup tracker you're working with. A roundup tracker
is where roundup keeps the database and configuration file that defines
an issue tracker. It may be thought of as the issue tracker's "home
directory". It may be specified in the environment variable TRACKER_HOME
or on the command line as "-i tracker".

A designator is a classname and a nodeid concatenated, eg. bug1, user10, ...

Property values are represented as strings in command arguments and in the
printed results:
 . Strings are, well, strings.
 . Date values are printed in the full date format in the local time zone,
   and accepted in the full format or any of the partial formats explained
   below.
 . Link values are printed as node designators. When given as an argument,
   node designators and key strings are both accepted.
 . Multilink values are printed as lists of node designators joined
   by commas.  When given as an argument, node designators and key
   strings are both accepted; an empty string, a single node, or a list
   of nodes joined by commas is accepted.

When property values must contain spaces, just surround the value with
quotes, either ' or ". A single space may also be backslash-quoted. If a
value must contain a quote character, it must be backslash-quoted or inside
quotes. Examples:
           hello world      (2 tokens: hello, world)
           "hello world"    (1 token: hello world)
           "Roch'e" Compaan (2 tokens: Roch'e Compaan)
           Roch\\'e Compaan  (2 tokens: Roch'e Compaan)
           address="1 2 3"  (1 token: address=1 2 3)
           \\\\               (1 token: \\)
           \\n\\r\\t           (1 token: a newline, carriage-return and tab)
           f "test\\"q"      (2 tokens: f test"q)

When multiple nodes are specified to the roundup get or roundup set
commands, the specified properties are retrieved or set on all the listed
nodes.

When multiple results are returned by the roundup get or roundup find
commands, they are printed one per line (default) or joined by commas (with
the -c) option.

Where the command changes data, a login name/password is required. The
login may be specified as either "name" or "name:password".
 . ROUNDUP_LOGIN environment variable
 . the -u command-line option
If either the name or password is not supplied, they are obtained from the
command-line. (See admin guide before using -u.)

Date format examples:
  "2000-04-17.03:45" means <Date 2000-04-17.08:45:00>
  "2000-04-17" means <Date 2000-04-17.00:00:00>
  "01-25" means <Date yyyy-01-25.00:00:00>
  "08-13.22:13" means <Date yyyy-08-14.03:13:00>
  "11-07.09:32:43" means <Date yyyy-11-07.14:32:43>
  "14:25" means <Date yyyy-mm-dd.19:25:00>
  "8:47:11" means <Date yyyy-mm-dd.13:47:11>
  "." means "right now"

Command help:
"""))
        for name, command in list(self.commands.items()):
            print(_('%s:') % name)
            print('   ', _(command.__doc__))

    nl_re = re.compile('[\r\n]')
    # indent_re defined above

    def listTemplates(self, trace_search=False):
        """ List all the available templates.

        Look in the following places, where the later rules take precedence:

         1. <roundup.admin.__file__>/../../share/roundup/templates/*
            this is where they will be if we installed an egg via easy_install
            or we are in the source tree.
         2. <prefix>/share/roundup/templates/*
            this should be the standard place to find them when Roundup is
            installed using setup.py without a prefix
         3. <roundup.admin.__file__>/../../<sys.prefix>/share/\
                 roundup/templates/* which is where they will be found if
            roundup is installed as a wheel using pip install
         4. <current working dir>/*
            this is for when someone unpacks a 3rd-party template
         5. <current working dir>
            this is for someone who "cd"s to the 3rd-party template dir
        """
        # OK, try <prefix>/share/roundup/templates
        #     and <egg-directory>/share/roundup/templates
        # -- this module (roundup.admin) will be installed in something
        # like:
        #    /usr/lib/python2.5/site-packages/roundup/admin.py  (5 dirs up)
        #    c:\python25\lib\site-packages\roundup\admin.py     (4 dirs up)
        #    /usr/lib/python2.5/site-packages/roundup-1.3.3-py2.5-egg/roundup/admin.py
        #    (2 dirs up)
        #
        # we're interested in where the directory containing "share" is
        debug = False
        templates = {}
        if debug: print(__file__)  # noqa: E701
        for N in 2, 4, 5, 6:
            path = __file__
            # move up N elements in the path
            for _i in range(N):
                path = os.path.dirname(path)
            tdir = os.path.join(path, 'share', 'roundup', 'templates')
            if debug or trace_search: print(tdir)  # noqa: E701
            if os.path.isdir(tdir):
                templates = init.listTemplates(tdir)
                if debug: print(" Found templates breaking loop")  # noqa: E701
                break

        # search for data files parallel to the roundup
        # install dir. E.G. a wheel install
        #  use roundup.__path__ and go up a level then use sys.prefix
        #  to create a base path for searching.

        import sys
        # __file__ should be something like:
        #    /usr/local/lib/python3.10/site-packages/roundup/admin.py
        # os.prefix should be /usr, /usr/local or root of virtualenv
        #    strip leading / to make os.path.join work right.
        path = __file__
        for _N in 1, 2:
            path = os.path.dirname(path)
        # path is /usr/local/lib/python3.10/site-packages
        tdir = os.path.join(path, sys.prefix[1:], 'share',
                            'roundup', 'templates')
        if debug or trace_search: print(tdir)  # noqa: E701
        if os.path.isdir(tdir):
            templates.update(init.listTemplates(tdir))

        try:
            # sigh pip 3.10 in virtual env finds another place to bury them.
            # why local and sys.base_prefix are in path I do not know.
            # path is /usr/local/lib/python3.10/site-packages
            tdir = os.path.join(path, sys.base_prefix[1:], 'local', 'share',
                                'roundup', 'templates')
            if debug or trace_search: print(tdir)  # noqa: E701
            if os.path.isdir(tdir):
                templates.update(init.listTemplates(tdir))
                # path is /usr/local/lib/python3.10/site-packages

            tdir = os.path.join(path, sys.base_prefix[1:], 'share',
                                'roundup', 'templates')
            if debug or trace_search: print(tdir)  # noqa: E701
            if os.path.isdir(tdir):
                templates.update(init.listTemplates(tdir))
        except AttributeError:
            pass  # sys.base_prefix doesn't work under python2

        # Try subdirs of the current dir
        templates.update(init.listTemplates(os.getcwd()))
        if debug or trace_search: print(os.getcwd() + '/*')  # noqa: E701

        # Finally, try the current directory as a template
        template = init.loadTemplateInfo(os.getcwd())
        if debug or trace_search: print(os.getcwd())  # noqa: E701
        if template:
            if debug: print("  Found template %s" %   # noqa: E701
                            template['name'])
            templates[template['name']] = template

        return templates

    def help_initopts(self):
        templates = self.listTemplates()
        print(_('Templates:'), ', '.join(templates))
        import roundup.backends
        backends = roundup.backends.list_backends()
        print(_('Back ends:'), ', '.join(backends))

    def _get_choice(self, list_name, prompt, options, argument, default=None):
        if default is None:
            default = options[0]  # just pick the first one
        if argument in options:
            return argument
        if self.force:
            return default
        sys.stdout.write('%s: %s\n' % (list_name, ', '.join(options)))
        while argument not in options:
            argument = self.my_input('%s [%s]: ' % (prompt, default))
            if not argument:
                return default
        return argument

    def do_commit(self, args):  # noqa: ARG002
        ''"""Usage: commit
        Commit changes made to the database during an interactive session.

        The changes made during an interactive session are not
        automatically written to the database - they must be committed
        using this command.

        One-off commands on the command-line are automatically committed if
        they are successful.
        """
        self.db.commit()
        self.db_uncommitted = False
        return 0

    def do_create(self, args):
        ''"""Usage: create classname property=value ...
        Create a new entry of a given class.

        This creates a new entry of the given class using the property
        name=value arguments provided on the command line after the "create"
        command.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))
        from roundup import hyperdb

        classname = args[0]

        # get the class
        cl = self.get_class(classname)

        # now do a create
        props = {}
        properties = cl.getprops(protected=0)
        if len(args) == 1:
            # ask for the properties
            for key in properties:
                if key == 'id': continue  # noqa: E701
                value = properties[key]
                name = value.__class__.__name__
                if isinstance(value, hyperdb.Password):
                    again = None
                    while value != again:
                        value = getpass.getpass(_('%(propname)s (Password): ')
                                                %
                                                {'propname': key.capitalize()})
                        again = getpass.getpass(_('   %(propname)s (Again): ')
                                                %
                                                {'propname': key.capitalize()})
                        if value != again:
                            print(_('Sorry, try again...'))
                    if value:
                        props[key] = value
                else:
                    value = self.my_input(_(
                        '%(propname)s (%(proptype)s): ') % {
                            'propname': key.capitalize(), 'proptype': name})
                    if value:
                        props[key] = value
        else:
            props = self.props_from_args(args[1:])

        # convert types
        try:
            for propname in props:
                props[propname] = hyperdb.rawToHyperdb(self.db, cl, None,
                                                       propname,
                                                       props[propname])
        except hyperdb.HyperdbValueError as message:
            raise UsageError(message)

        # check for the key property
        propname = cl.getkey()
        if propname and propname not in props:
            raise UsageError(_('you must provide the "%(propname)s" '
                               'property.') % locals())

        # do the actual create
        try:
            sys.stdout.write(cl.create(**props) + '\n')
        except (TypeError, IndexError, ValueError) as message:
            raise UsageError(message)
        self.db_uncommitted = True
        return 0

    def do_display(self, args):
        ''"""Usage: display designator[,designator]*

        Show the property values for the given node(s).

        A designator is a classname and a nodeid concatenated,
        eg. bug1, user10, ...

        This lists the properties and their associated values
        for the given node.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))

        display_protected = self.settings['display_protected']
        display_header = self.settings['display_header']

        # decode the node designator
        for designator in args[0].split(','):
            try:
                classname, nodeid = hyperdb.splitDesignator(designator)
            except hyperdb.DesignatorError as message:
                raise UsageError(message)

            # get the class
            cl = self.get_class(classname)

            # display the values
            normal_props = sorted(cl.properties)

            keys = sorted(cl.getprops()) if display_protected else normal_props

            if display_header:
                status = "retired" if cl.is_retired(nodeid) else "active"
                print('\n[%s (%s)]' % (designator, status))
            for key in keys:
                value = cl.get(nodeid, key)
                # prepend * for protected properties else just indent
                # with space.
                if display_protected or display_header:  # noqa: SIM108
                    protected = "*" if key not in normal_props else ' '
                else:
                    protected = ""
                print(_('%(protected)s%(key)s: %(value)s') % locals())

    def do_export(self, args, export_files=True):
        ''"""Usage: export [[-]class[,class]] export_dir
        Export the database to colon-separated-value files.
        To exclude the files (e.g. for the msg or file class),
        use the exporttables command.

        Optionally limit the export to just the named classes
        or exclude the named classes, if the 1st argument starts with '-'.

        This action exports the current data from the database into
        colon-separated-value files that are placed in the nominated
        destination directory.
        """
        # grab the directory to export to
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))

        export_dir = args[-1]

        # get the list of classes to export
        if len(args) == 2:
            if args[0].startswith('-'):
                classes = [c for c in self.db.classes
                           if c not in args[0][1:].split(',')]
            else:
                classes = args[0].split(',')
        else:
            classes = self.db.classes

        class colon_separated(csv.excel):
            delimiter = ':'

        # make sure target dir exists
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)

        # maximum csv field length exceeding configured size?
        max_len = self.db.config.CSV_FIELD_SIZE

        # do all the classes specified
        for classname in classes:
            cl = self.get_class(classname)

            if not export_files and hasattr(cl, 'export_files'):
                sys.stdout.write('Exporting %s WITHOUT the files\r\n' %
                                 classname)

            with open(os.path.join(export_dir, classname + '.csv'), 'w') as f:
                writer = csv.writer(f, colon_separated, lineterminator='\n')

                propnames = cl.export_propnames()
                fields = propnames[:]
                fields.append('is retired')
                writer.writerow(fields)

                # If a node has a key, sort all nodes by key
                # with retired nodes first. Retired nodes
                # must occur before a non-retired node with
                # the same key. Otherwise you get an
                # IntegrityError: UNIQUE constraint failed:
                #     _class.__retired__, _<class>._<keyname>
                # on imports to rdbms.
                all_nodes = cl.getnodeids()

                classkey = cl.getkey()
                if classkey:  # False sorts before True, so negate is_retired
                    keysort = lambda i: (      # noqa: E731
                        cl.get(i, classkey),   # noqa: B023 cl is not loop var
                        not cl.is_retired(i),  # noqa: B023 cl is not loop var
                    )
                    all_nodes.sort(key=keysort)
                # if there is no classkey no need to sort

                for nodeid in support.Progress( "Exporting %s" %
                                                classname, all_nodes):
                    if self.verbose:
                        sys.stdout.write('\rExporting %s - %s ' %
                                         (classname, nodeid))
                        sys.stdout.flush()
                    node = cl.getnode(nodeid)
                    exp = cl.export_list(propnames, nodeid)
                    lensum = sum([len(repr_export(node[p])) for
                                  p in propnames])
                    # for a safe upper bound of field length we add
                    # difference between CSV len and sum of all field lengths
                    d = sum([len(x) for x in exp]) - lensum
                    if not d > 0:
                        raise AssertionError("Bad assertion d > 0")
                    for p in propnames:
                        ll = len(repr_export(node[p])) + d
                        if ll > max_len:
                            max_len = ll
                    writer.writerow(exp)
                    if export_files and hasattr(cl, 'export_files'):
                        cl.export_files(export_dir, nodeid)

            # export the journals
            with open(os.path.join(export_dir,
                                   classname + '-journals.csv'), 'w') as jf:
                if self.verbose:
                    sys.stdout.write("\nExporting Journal for %s\n" %
                                     classname)
                    sys.stdout.flush()
                journals = csv.writer(jf, colon_separated, lineterminator='\n')
                for row in support.Progress("   Writing journals",
                                            cl.export_journals()):
                    journals.writerow(row)
        if max_len > self.db.config.CSV_FIELD_SIZE:
            print("Warning: config csv_field_size should be at least %s" %
                  max_len, file=sys.stderr)
        return 0

    def do_exporttables(self, args):
        ''"""Usage: exporttables [[-]class[,class]] export_dir
        Export the database to colon-separated-value files, excluding the
        files below $TRACKER_HOME/db/files/ (which can be archived separately).
        To include the files, use the export command.

        Optionally limit the export to just the named classes
        or exclude the named classes, if the 1st argument starts with '-'.

        This action exports the current data from the database into
        colon-separated-value files that are placed in the nominated
        destination directory.
        """
        return self.do_export(args, export_files=False)

    def do_filter(self, args):
        ''"""Usage: filter classname propname=value ...
        Find the nodes of the given class with a given property value.

        Find the nodes of the given class with a given property value.
        Multiple values can be specified by separating them with commas.
        If property is a string, all values must match. I.E. it's an
        'and' operation. If the property is a link/multilink any value
        matches. I.E. an 'or' operation.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))
        classname = args[0]
        # get the class
        cl = self.get_class(classname)

        # handle the propname=value argument
        props = self.props_from_args(args[1:])

        # convert the user-input value to a value used for filter
        # multiple , separated values become a list
        for propname, prop_value in props.items():
            values = prop_value.split(',') if ',' in prop_value \
                else [prop_value]

            props[propname] = []
            # start handling transitive props
            # given filter issue assignedto.roles=Admin
            # start at issue
            curclass = cl
            lastprop = propname  # handle case 'issue assignedto=admin'
            if '.' in propname:
                # start splitting transitive prop into components
                # we end when we have no more links
                for pn in propname.split('.'):
                    try:
                        lastprop = pn  # get current component
                        # get classname for this link
                        try:
                            curclassname = curclass.getprops()[pn].classname
                        except KeyError:
                            raise UsageError(_(
                                "Class %(curclassname)s has "
                                "no property %(pn)s in %(propname)s.") %
                                locals())
                        # get class object
                        curclass = self.get_class(curclassname)
                    except AttributeError:
                        # curclass.getprops()[pn].classname raises this
                        # when we are at a non link/multilink property
                        pass

            for value in values:
                val = hyperdb.rawToHyperdb(self.db, curclass, None,
                                           lastprop, value)
                props[propname].append(val)

        # now do the filter
        props = {"filterspec": props}
        try:
            output_items = cl.filter(None, **props)
            if self.print_designator:
                output_items = [classname + i for i in output_items]

            if self.separator:
                print(self.separator.join(output_items))
            else:
                print(output_items)
        except KeyError:
            raise UsageError(_('%(classname)s has no property '
                               '"%(propname)s"') % locals())
        except (ValueError, TypeError) as message:
            raise UsageError(message)
        return 0

    def do_find(self, args):
        ''"""Usage: find classname propname=value ...
        Find the nodes of the given class with a given link property value.

        Find the nodes of the given class with a given link property value.
        The value may be either the nodeid of the linked node, or its key
        value.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))
        classname = args[0]
        # get the class
        cl = self.get_class(classname)

        # handle the propname=value argument
        props = self.props_from_args(args[1:])

        # convert the user-input value to a value used for find()
        for propname, prop_value in props.items():
            values = prop_value.split(',') if ',' in prop_value \
                else [prop_value]

            d = props[propname] = {}
            for value in values:
                val = hyperdb.rawToHyperdb(self.db, cl, None,
                                             propname, value)
                if isinstance(val, list):
                    for entry in val:
                        d[entry] = 1
                else:
                    d[val] = 1

        # now do the find
        try:
            output_items = cl.find(**props)
            if self.print_designator:
                output_items = [classname + i for i in output_items]

            if self.separator:
                print(self.separator.join(output_items))
            else:
                print(output_items)
        except KeyError:
            raise UsageError(_('%(classname)s has no property '
                               '"%(propname)s"') % locals())
        except (ValueError, TypeError) as message:
            raise UsageError(message)
        return 0

    def do_genconfig(self, args, update=False):
        ''"""Usage: genconfig <filename>
        Generate a new tracker config file (ini style) with default
        values in <filename>.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))

        if update:
            # load current config for writing
            config = CoreConfig(self.tracker_home)

            # change config to update settings to new defaults
            # where prior defaults were chosen
            default_ppdr = config._get_option(
                'PASSWORD_PBKDF2_DEFAULT_ROUNDS')._default_value

            print("")  # put a blank line before feedback
            if config.PASSWORD_PBKDF2_DEFAULT_ROUNDS in [10000]:
                print(_("Changing option\n"
                        "   'password_pbkdf2_default_rounds'\n"
                        "from old default of %(old_number)s to new "
                        "default of %(new_number)s.") % {
                            "old_number":
                            config.PASSWORD_PBKDF2_DEFAULT_ROUNDS,
                            "new_number": default_ppdr,
                        })
                config.PASSWORD_PBKDF2_DEFAULT_ROUNDS = default_ppdr

            if default_ppdr > config.PASSWORD_PBKDF2_DEFAULT_ROUNDS:
                print(_("Update "
                        "'password_pbkdf2_default_rounds' "
                        "to a number equal to or larger\n  than %s.\n") %
                      default_ppdr)

            if not config.RDBMS_MYSQL_COLLATION.startswith(
                    config.RDBMS_MYSQL_CHARSET + "_"):
                print(_("Check the rdbms mysql_* settings. Your charset and "
                        "collations may need\n"
                        "  to be changed. See upgrading instructions.\n"))
        else:
            # generate default config
            config = CoreConfig()

        config.save(args[0])

    def do_get(self, args):
        ''"""Usage: get property designator[,designator]*
        Get the given property of one or more designator(s).

        A designator is a classname and a nodeid concatenated,
        eg. bug1, user10, ...

        Retrieves the property value of the nodes specified
        by the designators.
        """
        if len(args) < 2:
            raise UsageError(_('Not enough arguments supplied'))
        propname = args[0]
        designators = args[1].split(',')
        linked_props = []
        for designator in designators:
            # decode the node designator
            try:
                classname, nodeid = hyperdb.splitDesignator(designator)
            except hyperdb.DesignatorError as message:
                raise UsageError(message)

            # get the class
            cl = self.get_class(classname)
            try:
                if not (self.separator or self.print_designator):
                    print(cl.get(nodeid, propname))
                    continue

                properties = cl.getprops()
                prop_obj = properties[propname]
                if not (isinstance(prop_obj,
                                   (hyperdb.Link, hyperdb.Multilink))):
                    raise UsageError(_(
                        'property %s is not of type'
                        ' Multilink or Link so -d flag does not '
                        'apply.') % propname)
                propclassname = self.db.getclass(
                    prop_obj.classname).classname

                output_items = cl.get(nodeid, propname)
                if self.print_designator:
                    output_items = [propclassname + i for i in output_items]

                if self.separator:
                    print(self.separator.join(output_items))
                else:
                    # default is to list each on a line
                    print('\n'.join(output_items))

            except IndexError:
                raise UsageError(_('no such %(classname)s node '
                                   '"%(nodeid)s"') % locals())
            except KeyError:
                raise UsageError(_('no such %(classname)s property '
                                   '"%(propname)s"') % locals())
        return 0

    def do_help(self, args, nl_re=nl_re, indent_re=indent_re):
        ''"""Usage: help topic
        Give help about topic.

        commands  -- list commands
        <command> -- help specific to a command
        initopts  -- init command options
        all       -- all available help
        """
        topic = args[0] if len(args) > 0 else 'help'

        # try help_ methods
        if topic in self.help:
            self.help[topic]()
            return 0

        # try command docstrings
        try:
            cmd_docs = self.commands.get(topic)
        except KeyError:
            print(_('Sorry, no help for "%(topic)s"') % locals())
            return 1

        # display the help for each match, removing the docstring indent
        for _name, do_function in cmd_docs:
            lines = nl_re.split(_(do_function.__doc__))
            print(lines[0])
            indent = indent_re.match(lines[1])
            if indent: indent = len(indent.group(1))  # noqa: E701
            for line in lines[1:]:
                if indent:
                    print(line[indent:])
                else:
                    print(line)
        return 0

    def do_history(self, args):
        ''"""Usage: history designator [skipquiet] [raw]
        Show the history entries of a designator.

        A designator is a classname and a nodeid concatenated,
        eg. bug1, user10, ...

        Lists the journal entries viewable by the user for the node
        identified by the designator. If skipquiet is added, journal
        entries for quiet properties are not shown. If raw is added,
        the output is the raw representation of the journal entries.
        """

        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))
        try:
            classname, nodeid = hyperdb.splitDesignator(args[0])
        except hyperdb.DesignatorError as message:
            raise UsageError(message)

        valid_args = ['skipquiet', 'raw']

        if len(args) >= 2:
            check = [a for a in args[1:] if a not in valid_args]
            if check:
                raise UsageError(
                    _("Unexpected argument(s): %s. "
                      "Expected 'skipquiet' or 'raw'.") % ", ".join(check))

        skipquiet = 'skipquiet' in args[1:]
        raw = 'raw' in args[1:]

        getclass = self.db.getclass

        def get_prop_name(key, prop_name):
            # getclass and classname from enclosing method
            klass = getclass(classname)
            try:
                property_obj = klass.properties[prop_name]
            except KeyError:
                # the property has been removed from the schema.
                return None
            if isinstance(property_obj,
                        (hyperdb.Link, hyperdb.Multilink)):
                prop_class = getclass(property_obj.classname)
                label_prop_name = prop_class.labelprop(default_to_id=True)
                if label_prop_name not in ['id', 'title']:
                    # Don't return 'id', its value is the key. If name is
                    # empty, the caller will use the classname with the key
                    # as the identifier: show "issue23" not "23(23)".
                    # Also don't use the title. It's too long in most
                    # cases. show: "issue23" not "please help me with
                    # samba use athentication issue(23)"
                    return prop_class.get(key, label_prop_name)
                # None indicates that there is no viable label_prop
                return None
            return None

        def get_prop_class(prop_name):
            # getclass and classname from enclosing method
            klass = getclass(classname)
            try:
                property_obj = klass.properties[prop_name]
            except KeyError:
                # the property has been removed from the schema.
                return None
            if isinstance(property_obj,
                          (hyperdb.Link, hyperdb.Multilink)):
                prop_class = getclass(property_obj.classname)
                return prop_class.classname
            return None  # it's not a link

        def _format_tuple_change(data, prop):
            ''' ('-', ['2', '4'] ->
                "removed fred(2), jim(6)"
            '''
            if data[0] == '-':
                op = _("removed")
            elif data[0] == '+':
                op = _("added")
            else:
                raise ValueError(_("Unknown history set operation '%s'. "
                                 "Expected +/-.") % op)
            op_params = data[1]
            name = get_prop_name(op_params[0], prop)
            if name is not None:
                list_items = ["%s(%s)" %
                              (get_prop_name(o, prop), o)
                              for o in op_params]
            else:
                propclass = get_prop_class(prop)
                if propclass:  # noqa: SIM108
                    list_items = ["%s%s" % (propclass, o)
                                  for o in op_params]
                else:
                    list_items = op_params

            return "%s: %s" % (op, ", ".join(list_items))

        def format_report_class(_data):
            """Eat the empty data dictionary or None"""
            return classname

        def format_link(data):
            '''data = ('issue', '157', 'dependson')'''
            # .Hint added issue23 to superseder
            f = _("added %(class)s%(item_id)s to %(propname)s")
            return f % {
                'class': data[0], 'item_id': data[1], 'propname': data[2]}

        def format_set(data):
            '''data  = set {'fyi': None, 'priority': '5'}
               set {'fyi': '....\ned through cleanly', 'priority': '3'}
            '''
            result = []

            # Note that set data is the old value. So don't use
            # current/future tense in sentences.

            for prop, value in data.items():
                if isinstance(value, str):
                    name = get_prop_name(value, prop)
                    if name:
                        result.append(
                            # .Hint read as: assignedto was admin(1)
                            # where assignedto is the property
                            # admin is the key name for value 1
                            _("%(prop)s was %(name)s(%(value)s)") % {
                                "prop": prop, "name": name, "value": value})
                    else:
                        # use repr so strings with embedded \n etc. don't
                        # generate newlines in output. Try to keep each
                        # journal entry on 1 line.
                        result.append(_("%(prop)s was %(value)s") % {
                            "prop": prop, "value": repr(value)})
                elif isinstance(value, list):
                    # test to see if there is a key prop.
                    # Assumption, geting None here means no key
                    # is defined for the property's class.
                    name = get_prop_name(value[0], prop)
                    if name is not None:
                        list_items = ["%s(%s)" %
                                      (get_prop_name(v, prop), v)
                                      for v in value]
                    else:
                        prop_class = get_prop_class(prop)
                        if prop_class:  # noqa: SIM108
                            list_items = ["%s%s" % (prop_class, v)
                                           for v in value]
                        else:
                            list_items = value

                    result.append(_("%(prop)s was [%(value_list)s]") % {
                        "prop": prop, "value_list": ", ".join(list_items)})
                elif isinstance(value, tuple):
                    # operation data
                    decorated = [_format_tuple_change(data, prop)
                                 for data in value]
                    result.append(# .Hint modified nosy: added demo(3)
                        _("modified %(prop)s: %(how)s") % {
                        "prop": prop, "how": ", ".join(decorated)})
                else:
                    result.append(_("%(prop)s was %(value)s") % {
                        "prop": prop, "value": value})

            return '; '.join(result)

        def format_unlink(data):
            '''data = ('issue', '157', 'dependson')'''
            return "removed %s%s from %s" % (data[0], data[1], data[2])

        formatters = {
            "create": format_report_class,
            "link": format_link,
            "restored": format_report_class,
            "retired": format_report_class,
            "set": format_set,
            "unlink": format_unlink,
        }

        try:
            # returns a tuple: (
            # [0] = nodeid
            # [1] = date
            # [2] = userid
            # [3] = operation
            # [4] = details
            raw_history = self.db.getclass(classname).history(nodeid,
                                                      skipquiet=skipquiet)
            if raw:
                print(raw_history)
                return 0

            def make_readable(hist):
                return "%s(%s) %s %s" % (self.db.user.get(hist[2], 'username'),
                                  hist[1],
                                  hist[3],
                                  formatters.get(hist[3], lambda x: x)(
                                      hist[4]))
            printable_history = [make_readable(hist) for hist in raw_history]

            print("\n".join(printable_history))
        except KeyError:
            raise UsageError(_('no such class "%(classname)s"') % locals())
        except IndexError:
            raise UsageError(_('no such %(classname)s node '
                               '"%(nodeid)s"') % locals())
        return 0

    def do_import(self, args, import_files=True):
        ''"""Usage: import import_dir
        Import a database from the directory containing CSV files,
        two per class to import.

        The files used in the import are:

        <class>.csv
          This must define the same properties as the class (including
          having a "header" line with those property names.)
        <class>-journals.csv
          This defines the journals for the items being imported.

        The imported nodes will have the same nodeid as defined in the
        import file, thus replacing any existing content.

        The new nodes are added to the existing database - if you want to
        create a new database using the imported data, then create a new
        database (or, tediously, retire all the old data.)
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))

        if hasattr(csv, 'field_size_limit'):
            csv.field_size_limit(self.db.config.CSV_FIELD_SIZE)

        # default value is 10000, only go through this if default
        # is different.
        if self.settings['savepoint_limit'] != self._default_savepoint_setting:
            # create a new option on the fly in the config under the
            # rdbms section. It is used by the postgresql backend's
            # checkpoint_data method.
            self.db.config.add_option(Option(self.db.config,
                                             "rdbms", "savepoint_limit"))
            self.db.config.options["RDBMS_SAVEPOINT_LIMIT"].set(
                self.settings['savepoint_limit'])

        # directory to import from
        import_dir = args[0]

        class colon_separated(csv.excel):
            delimiter = ':'

        # import all the files
        for file in os.listdir(import_dir):
            classname, ext = os.path.splitext(file)
            # we only care about CSV files
            if ext != '.csv' or classname.endswith('-journals'):
                continue

            cl = self.get_class(classname)

            # ensure that the properties and the CSV file headings match
            with open(os.path.join(import_dir, file), 'r') as f:
                reader = csv.reader(f, colon_separated, lineterminator='\n')
                file_props = None
                maxid = 1
                # loop through the file and create a node for each entry
                for n, r in enumerate(reader):
                    if file_props is None:
                        file_props = r
                        continue

                    if self.verbose:
                        sys.stdout.write('\rImporting %s - %s' % (classname, n))
                        sys.stdout.flush()

                    # do the import and figure the current highest nodeid
                    nodeid = cl.import_list(file_props, r)
                    if hasattr(cl, 'import_files') and import_files:
                        cl.import_files(import_dir, nodeid)
                    maxid = max(maxid, int(nodeid))

                # (print to sys.stdout here to allow tests to squash it .. ugh)
                print(file=sys.stdout)

            # import the journals
            with open(os.path.join(import_dir, classname + '-journals.csv'), 'r') as f:
                reader = csv.reader(f, colon_separated, lineterminator='\n')
                cl.import_journals(reader)

            # (print to sys.stdout here to allow tests to squash it .. ugh)
            print('setting', classname, maxid + 1, file=sys.stdout)

            # set the id counter
            self.db.setid(classname, str(maxid + 1))

        self.db_uncommitted = True
        return 0

    def do_importtables(self, args):
        ''"""Usage: importtables export_dir

        This imports the database tables exported using exporttables.
        """
        return self.do_import(args, import_files=False)

    def do_initialise(self, tracker_home, args):
        ''"""Usage: initialise [adminpw]
        Initialise a new Roundup tracker.

        The administrator details will be set at this step.

        Execute the tracker's initialisation function dbinit.init()
        """
        # password
        if len(args) > 1:
            adminpw = args[1]
        else:
            adminpw = ''
            confirm = 'x'
            while adminpw != confirm:
                adminpw = getpass.getpass(_('Admin Password: '))
                confirm = getpass.getpass(_('       Confirm: '))

        # make sure the tracker home is installed
        if not os.path.exists(tracker_home):
            raise UsageError(_('Instance home does not exist') % locals())
        try:
            tracker = roundup.instance.open(tracker_home)
        except roundup.instance.TrackerError:
            raise UsageError(_('Instance has not been installed') % locals())
        except OptionValueError as e:
            raise UsageError(e)

        # is there already a database?
        if tracker.exists():
            if not self.force:
                ok = self.my_input(_(
"""WARNING: The database is already initialised!
If you re-initialise it, you will lose all the data!
Erase it? Y/N: """))
                if ok.strip().lower() != 'y':
                    return 0

            # nuke it
            tracker.nuke()

        # GO
        try:
            tracker.init(password.Password(adminpw, config=tracker.config),
                         tx_Source='cli')
        except OptionUnsetError as e:
            raise UsageError("In %(tracker_home)s/config.ini - %(error)s" % {
                'error': str(e), 'tracker_home': tracker_home})

        return 0

    def do_install(self, tracker_home, args):
        ''"""Usage: install [template [backend [key=val[,key=val]]]]
        Install a new Roundup tracker.

        The command will prompt for the tracker home directory
        (if not supplied through TRACKER_HOME or the -i option).
        The template and backend may be specified on the command-line
        as arguments, in that order.

        Command line arguments following the backend allows you to
        pass initial values for config options.  For example, passing
        "web_http_auth=no,rdbms_user=dinsdale" will override defaults
        for options http_auth in section [web] and user in section [rdbms].
        Please be careful to not use spaces in this argument! (Enclose
        whole argument in quotes if you need spaces in option value).

        The initialise command must be called after this command in order
        to initialise the tracker's database. You may edit the tracker's
        initial database contents before running that command by editing
        the tracker's dbinit.py module init() function.

        See also initopts help.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))

        # make sure the tracker home can be created
        tracker_home = os.path.abspath(tracker_home)
        parent = os.path.split(tracker_home)[0]
        if not os.path.exists(parent):
            raise UsageError(_('Instance home parent directory "%(parent)s"'
                               ' does not exist') % locals())

        config_ini_file = os.path.join(tracker_home, CoreConfig.INI_FILE)
        # check for both old- and new-style configs
        if list(filter(os.path.exists, [config_ini_file,
                os.path.join(tracker_home, 'config.py')])):
            if not self.force:
                ok = self.my_input(_(
"""WARNING: There appears to be a tracker in "%(tracker_home)s"!
If you re-install it, you will lose all the data!
Erase it? Y/N: """) % locals())
                if ok.strip().lower() != 'y':
                    return 0

            # clear it out so the install isn't confused
            shutil.rmtree(tracker_home)

        # select template
        templates = self.listTemplates()
        template = self._get_choice(
            list_name=_('Templates:'),
            prompt=_('Select template'),
            options=templates,
            argument=len(args) > 1 and args[1] or '',
            default='classic')

        # select hyperdb backend
        import roundup.backends
        backends = roundup.backends.list_backends()
        backend = self._get_choice(
            list_name=_('Back ends:'),
            prompt=_('Select backend'),
            options=backends,
            argument=len(args) > 2 and args[2] or '',
            default='anydbm')
        # XXX perform a unit test based on the user's selections

        # Process configuration file definitions
        if len(args) > 3:
            try:
                defns = dict([item.split("=") for item in args[3].split(",")])
            except Exception:
                print(_('Error in configuration settings: "%s"') % args[3])
                raise
        else:
            defns = {}

        defns['rdbms_backend'] = backend

        # load config_ini.ini from template if it exists.
        # it sets parameters like template_engine that are
        # template specific.
        template_config = UserConfig(templates[template]['path'] +
                                     "/config_ini.ini")

        # .keys() is required. UserConfig has no __iter__ or __next__
        for k in template_config.keys():  # noqa: SIM118
            if k == 'HOME':  # ignore home. It is a default param.
                continue
            defns[k] = template_config[k]

        # install!
        init.install(tracker_home, templates[template]['path'], settings=defns)

        # Remove config_ini.ini file from tracker_home (not template dir).
        # Ignore file not found - not all templates have
        #   config_ini.ini files.
        try:
            os.remove(tracker_home + "/config_ini.ini")
        except OSError as e:  # FileNotFound exception under py3
            if e.errno == 2:
                pass
            else:
                raise

        print(_("""
---------------------------------------------------------------------------
 You should now edit the tracker configuration file:
   %(config_file)s""") % {"config_file": config_ini_file})

        # find list of options that need manual adjustments
        # XXX config._get_unset_options() is marked as private
        #   (leading underscore).  make it public or don't care?
        need_set = CoreConfig(tracker_home)._get_unset_options()
        if need_set:
            print(_(" ... at a minimum, you must set following options:"))
            for section in need_set:
                print("   [%s]: %s" % (section, ", ".join(need_set[section])))

        # note about schema modifications
        print(_("""
 If you wish to modify the database schema,
 you should also edit the schema file:
   %(database_config_file)s
 You may also change the database initialisation file:
   %(database_init_file)s
 ... see the documentation on customizing for more information.

 You MUST run the "roundup-admin initialise" command once you've performed
 the above steps.
---------------------------------------------------------------------------
""") % {'database_config_file': os.path.join(tracker_home, 'schema.py'),
        'database_init_file': os.path.join(tracker_home, 'initial_data.py')})
        return 0

    def do_list(self, args):
        ''"""Usage: list classname [property]
        List the instances of a class.

        Lists all instances of the given class. If the property is not
        specified, the  "label" property is used. The label property is
        tried in order: the key, "name", "title" and then the first
        property, alphabetically.

        With -c, -S or -s print a list of item id's if no property
        specified.  If property specified, print list of that property
        for every class instance.
        """
        if len(args) > 2:
            raise UsageError(_('Too many arguments supplied'))
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))

        retired = self.settings['_retired_val']

        classname = args[0]

        # get the class
        cl = self.get_class(classname)

        # figure the property
        propname = args[1] if len(args) > 1 else cl.labelprop()

        if self.separator:
            if len(args) == 2:
                # create a list of propnames since user specified propname
                proplist = []
                try:
                    proplist = [cl.get(nodeid, propname) for nodeid in
                                 cl.getnodeids(retired=retired)]
                except KeyError:
                    raise UsageError(_('%(classname)s has no property '
                                           '"%(propname)s"') % locals())
                print(self.separator.join(proplist))
            else:
                # create a list of index id's since user didn't specify
                # otherwise
                print(self.separator.join(cl.getnodeids(retired=retired)))
        else:
            try:
                for nodeid in cl.getnodeids(retired=retired):
                    value = cl.get(nodeid, propname)
                    print(_('%(nodeid)4s: %(value)s') % locals())
            except KeyError:
                raise UsageError(_('%(classname)s has no property '
                                   '"%(propname)s"') % locals())
        return 0

    def do_migrate(self, args):  # noqa: ARG002  - args unused
        ''"""Usage: migrate

        Update a tracker's database to be compatible with the Roundup
        codebase.

        You should run the "migrate" command for your tracker once
        you've installed the latest codebase.

        Do this before you use the web, command-line or mail interface
        and before any users access the tracker.

        This command will respond with either "Tracker updated" (if
        you've not previously run it on an RDBMS backend) or "No
        migration action required" (if you have run it, or have used
        another interface to the tracker, or possibly because you are
        using anydbm).

        It's safe to run this even if it's not required, so just get
        into the habit.
        """
        if self.db.db_version_updated:
            print(_('Tracker updated to schema version %s.') %
                  self.db.database_schema['version'])
            self.db_uncommitted = True
        else:
            print(_('No migration action required. At schema version %s.') %
                  self.db.database_schema['version'])
        return 0

    def do_pack(self, args):
        ''"""Usage: pack period | date

        Remove journal entries older than a period of time specified or
        before a certain date.

        A period is specified using the suffixes "y", "m", and "d". The
        suffix "w" (for "week") means 7 days.

              "3y" means three years
              "2y 1m" means two years and one month
              "1m 25d" means one month and 25 days
              "2w 3d" means two weeks and three days

        Date format is "YYYY-MM-DD" eg:
            2001-01-01

        """
        if len(args) != 1:
            raise UsageError(_('Not enough arguments supplied'))

        # are we dealing with a period or a date
        value = args[0]
        date_re = re.compile(r"""
              (?P<date>\d\d\d\d-\d\d?-\d\d?)? # yyyy-mm-dd
              (?P<period>(\d+y\s*)?(\d+m\s*)?(\d+d\s*)?)?
              """, re.VERBOSE)
        m = date_re.match(value)
        if not m:
            raise ValueError(_('Invalid format'))
        m = m.groupdict()
        if m['period']:
            pack_before = date.Date(". - %s" % value)
        elif m['date']:
            pack_before = date.Date(value)
        self.db.pack(pack_before)
        self.db_uncommitted = True
        return 0

    def do_perftest(self, args):
        ''"""Usage: perftest [mode] [arguments]*

        Time operations in Roundup. Supported arguments:

            [password] [rounds=<integer>] [scheme=<scheme>]

        'password' is the default mode.  The tracker's config.ini
        setting for 'password_pbkdf2_default_rounds' is the default
        value for 'rounds'. On the command line, 'rounds' can include
        thousands separator of ',' or '.'.  'scheme' is the default
        coded into Roundup. List supported schemes by using 'scheme='.

        """
        from roundup.anypy.time_ import perf_counter

        props = {"rounds": self.db.config.PASSWORD_PBKDF2_DEFAULT_ROUNDS,
                 "scheme": password.Password.default_scheme}

        print_supported_schemes = lambda: print(
            "Supported schemes (default is first, case "
            "sensitive):\n   %s." %
            ", ".join(password.Password.known_schemes))

        if (args[0].find("=") != -1):
            args.insert(0, 'password')

        props.update(self.props_from_args(args[1:]))

        if args[0] == "password":
            try:
                # convert 10,000,000 or 10.000.000 to 10000000
                r = int(re.sub('[,.]', '', props['rounds']))
                if r < 1000:
                    print(_("Invalid 'rounds'. Must be larger than 999."))
                    return
                props['rounds'] = r
            except (TypeError, ValueError):
                print(_("Invalid 'rounds'. It must be an integer not: %s") %
                      props['rounds'])
                return
            if props['scheme'] is None:
                print_supported_schemes()
                return

            self.db.config.PASSWORD_PBKDF2_DEFAULT_ROUNDS = props['rounds']

            try:
                tic = perf_counter()
                pw_hash = password.encodePassword(
                    "this is a long password to hash",
                    props['scheme'],
                    None,
                    config=self.db.config,
                )
                toc = perf_counter()
            except password.PasswordValueError as e:
                print(e)
                print_supported_schemes()
                return

            if props['scheme'].startswith('PBKDF2'):
                (rounds, _salt, _raw_salt, _digest) = password.pbkdf2_unpack(
                    pw_hash)
            else:
                rounds = _("scheme does not support rounds.")

            print(_(
                "Hash time: %(time)0.9f seconds, scheme: %(scheme)s, "
                "rounds: %(rounds)s") %
                  {"time": toc - tic, "scheme": props['scheme'],
                   "rounds": rounds})

    def do_pragma(self, args):
        ''"""Usage: pragma setting=value | 'list'
        Set internal admin settings to a value. E.G.

            pragma verbose=True
            pragma verbose=yes
            pragma verbose=on
            pragma verbose=1

         will turn on verbose mode for roundup-admin.

            pragma list

         will show all settings and their current values. If verbose
         is enabled hidden settings and descriptions will be shown.
        """
        """
          The following are to be implemented:
           exportfiles={true|false} - Not Implemented - If true
                    (default) export/import db tables and files. If
                    False, export/import just database tables, not
                    files. Use for faster database migration.
                    Replaces exporttables/importtables with
                    exportfiles=false then export/import
        """

        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))

        try:
            (setting, value) = args[0].split("=", 1)
        except ValueError:
            if args[0] != "list":
                raise UsageError(_(
                    'Argument must be setting=value, was given: %s.') %
                                 args[0])

            print(_("Current settings and values "
                    "(NYI - not yet implemented):"))
            is_verbose = self.settings['verbose']
            for key in sorted(self.settings.keys()):
                if key.startswith('_') and not is_verbose:
                    continue
                print("   %s=%s" % (key, self.settings[key]))
                if is_verbose:
                    try:
                        print("      %s" % self.settings_help[key])
                    except KeyError:
                        print(_("      Help for this pragma is missing. "
                                "Please report it to the Roundup project.\n"))

            return

        if setting not in self.settings:
            raise UsageError(_('Unknown setting %s. Try "pragma list".')
                             % setting)
        if isinstance(self.settings[setting], bool):
            value = value.lower()
            if value in ("yes", "true", "on", "1"):
                value = True
            elif value in ("no", "false", "off", "0"):
                value = False
            else:
                raise UsageError(_(
                    'Incorrect value for boolean setting %(setting)s: '
                    '%(value)s.') % {"setting": setting, "value": value})
        elif isinstance(self.settings[setting], int):
            try:
                _val = int(value)
            except ValueError:
                raise UsageError(_(
                    'Incorrect value for integer setting %(setting)s: '
                    '%(value)s.') % {"setting": setting, "value": value})
            value = _val
        elif isinstance(self.settings[setting], str):
            if setting == "show_retired":
                if value not in ["no", "only", "both"]:
                    raise UsageError(_(
                        'Incorrect value for setting %(setting)s: '
                        '%(value)s. Should be no, both, or only.') % {
                            "setting": setting, "value": value})
                if value == "both":
                    self.settings['_retired_val'] = None
                elif value == "only":  # numerical value not boolean
                    self.settings['_retired_val'] = True
                else:  # numerical value not boolean
                    self.settings['_retired_val'] = False
        else:
            raise UsageError(_('Internal error: pragma can not handle '
                               'values of type: %s') %
                             type(self.settings[setting]).__name__)
        self.settings[setting] = value

    designator_re = re.compile('([A-Za-z]+)([0-9]+)$')
    designator_rng = re.compile('([A-Za-z]+):([0-9]+)-([0-9]+)$')

    def do_reindex(self, args, desre=designator_re, desrng=designator_rng):
        ''"""Usage: reindex [classname|classname:#-#|designator]*
        Re-generate a tracker's search indexes.

        This will re-generate the search indexes for a tracker.
        This will typically happen automatically.

        You can incrementally reindex using an argument like:

            reindex issue:23-1000

        to reindex issue class items 23-1000. Missing items
        are reported but do not stop indexing of the range.
        """
        if args:
            for arg in args:
                m = desre.match(arg)
                r = desrng.match(arg)
                if m:
                    cl = self.get_class(m.group(1))
                    try:
                        cl.index(m.group(2))
                    except IndexError:
                        raise UsageError(_('no such item "%(designator)s"') % {
                            'designator': arg})
                elif r:
                    cl = self.get_class(r.group(1))
                    for item in support.Progress(
                            'Reindexing %s' % r.group(1),
                            range(int(r.group(2)), int(r.group(3)))):
                        try:
                            cl.index(str(item))
                        except IndexError:
                            print(_('no such item "%(class)s%(id)s"') % {
                                'class': r.group(1),
                                'id': item})

                else:
                    cl = self.get_class(arg)  # Bad class raises UsageError
                    self.db.reindex(arg, show_progress=True)
        else:
            self.db.reindex(show_progress=True)
        return 0

    def do_restore(self, args):
        ''"""Usage: restore designator[,designator]*
        Restore the retired node specified by designator.

        A designator is a classname and a nodeid concatenated,
        eg. bug1, user10, ...

        The given nodes will become available for users again.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))
        designators = args[0].split(',')
        for designator in designators:
            try:
                classname, nodeid = hyperdb.splitDesignator(designator)
            except hyperdb.DesignatorError as message:
                raise UsageError(message)
            try:
                dbclass = self.db.getclass(classname)
            except KeyError:
                raise UsageError(_('no such class "%(classname)s"') % locals())
            try:
                dbclass.restore(nodeid)
            except KeyError as e:
                raise UsageError(e.args[0])
            except IndexError:
                raise UsageError(_('no such %(classname)s node '
                                   '" % (nodeid)s"') % locals())
        self.db_uncommitted = True
        return 0

    def do_retire(self, args):
        ''"""Usage: retire designator[,designator]*
        Retire the node specified by designator.

        A designator is a classname and a nodeid concatenated,
        eg. bug1, user10, ...

        This action indicates that a particular node is not to be retrieved
        by the list or find commands, and its key value may be re-used.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))
        designators = args[0].split(',')
        for designator in designators:
            try:
                classname, nodeid = hyperdb.splitDesignator(designator)
            except hyperdb.DesignatorError as message:
                raise UsageError(message)
            try:
                self.db.getclass(classname).retire(nodeid)
            except KeyError:
                raise UsageError(_('no such class "%(classname)s"') % locals())
            except IndexError:
                raise UsageError(_('no such %(classname)s node '
                                   '"%(nodeid)s"') % locals())
        self.db_uncommitted = True
        return 0

    def do_rollback(self, args):  # noqa: ARG002 - args unused
        ''"""Usage: rollback
        Undo all changes that are pending commit to the database.

        The changes made during an interactive session are not
        automatically written to the database - they must be committed
        manually. This command undoes all those changes, so a commit
        immediately after would make no changes to the database.
        """
        self.db.rollback()
        self.db_uncommitted = False
        return 0

    def do_security(self, args):
        ''"""Usage: security [Role name]

             Display the Permissions available to one or all Roles.
             Also validates that any properties defined in a
             permission are valid.

             Run this after changing your permissions to catch
             typos.
        """
        if len(args) == 1:
            role = args[0]
            try:
                roles = [(args[0].lower(),
                          self.db.security.role[args[0].lower()])]
            except KeyError:
                sys.stdout.write(_('No such Role "%(role)s"\n') % locals())
                return 1
        else:
            roles = list(self.db.security.role.items())
            role = self.db.config.NEW_WEB_USER_ROLES
            if ',' in role:
                sys.stdout.write(_('New Web users get the Roles "%(role)s"\n')
                                 % locals())
            else:
                sys.stdout.write(_('New Web users get the Role "%(role)s"\n')
                                 % locals())
            role = self.db.config.NEW_EMAIL_USER_ROLES
            if ',' in role:
                sys.stdout.write(_('New Email users get the Roles "%(role)s"\n') % locals())
            else:
                sys.stdout.write(_('New Email users get the Role "%(role)s"\n') % locals())
        roles.sort()
        for _rolename, role in roles:
            sys.stdout.write(_('Role "%(name)s":\n') % role.__dict__)
            for permission in role.permissions:
                d = permission.__dict__
                if permission.klass:
                    if permission.properties:
                        sys.stdout.write(_(
                            ' %(description)s (%(name)s for "%(klass)s"' +
                            ': %(properties)s only)\n') % d)
                        # verify that properties exist; report bad props
                        bad_props = []
                        cl = self.db.getclass(permission.klass)
                        class_props = cl.getprops(protected=True)
                        for p in permission.properties:
                            if p in class_props:
                                continue

                            bad_props.append(p)
                        if bad_props:
                            sys.stdout.write(_(
                                '\n  **Invalid properties for %(class)s: '
                                '%(props)s\n\n') % {
                                    "class": permission.klass,
                                    "props": bad_props})
                            return 1
                    else:
                        sys.stdout.write(_(' %(description)s (%(name)s for '
                                           '"%(klass)s" only)\n') % d)
                else:
                    sys.stdout.write(_(' %(description)s (%(name)s)\n') % d)
        return 0

    def do_set(self, args):
        ''"""Usage: set items property=value [property=value ...]
        Set the given properties of one or more items(s).

        The items are specified as a class or as a comma-separated
        list of item designators (ie "designator[,designator,...]").

        A designator is a classname and a nodeid concatenated,
        eg. bug1, user10, ...

        This command sets the properties to the values for all
        designators given. If a class is used, the property will be
        set for all items in the class. If the value is missing
        (ie. "property=") then the property is un-set. If the property
        is a multilink, you specify the linked ids for the multilink
        as comma-separated numbers (ie "1,2,3").

        """
        import copy  # needed for copying props list

        if len(args) < 2:
            raise UsageError(_('Not enough arguments supplied'))
        from roundup import hyperdb

        designators = args[0].split(',')
        if len(designators) == 1:
            designator = designators[0]
            try:
                designator = hyperdb.splitDesignator(designator)
                designators = [designator]
            except hyperdb.DesignatorError:
                cl = self.get_class(designator)
                designators = [(designator, x) for x in cl.list()]
        else:
            try:
                designators = [hyperdb.splitDesignator(x) for x in designators]
            except hyperdb.DesignatorError as message:
                raise UsageError(message)

        # get the props from the args
        propset = self.props_from_args(args[1:])  # parse the cli once

        # now do the set for all the nodes
        for classname, itemid in designators:
            props = copy.copy(propset)  # make a new copy for every designator
            cl = self.get_class(classname)

            try:
                for key, value in list(props.items()):
                    # You must reinitialize the props every time though.
                    # if props['nosy'] = '+admin' initally, it gets
                    # set to 'demo,admin' (assuming it was set to demo
                    # in the db) after rawToHyperdb returns.
                    # This  new value is used for all the rest of the
                    # designators if not reinitalized.
                    props[key] = hyperdb.rawToHyperdb(self.db, cl, itemid,
                                                      key, value)
            except hyperdb.HyperdbValueError as message:
                raise UsageError(message)

            # try the set
            try:
                cl.set(itemid, **props)
            except (TypeError, IndexError, ValueError) as message:
                raise UsageError(message)
        self.db_uncommitted = True
        return 0

    def do_specification(self, args):
        ''"""Usage: specification classname
        Show the properties for a classname.

        This lists the properties for a given class.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))
        classname = args[0]
        # get the class
        cl = self.get_class(classname)

        # get the key property
        keyprop = cl.getkey()
        properties = cl.getprops() if self.settings['display_protected'] \
            else cl.properties

        for key in properties:
            value = properties[key]
            if keyprop == key:
                sys.stdout.write(_('%(key)s: %(value)s (key property)\n') %
                                 locals())
            else:
                sys.stdout.write(_('%(key)s: %(value)s\n') % locals())

    def do_table(self, args):
        ''"""Usage: table classname [property[,property]*]
        List the instances of a class in tabular form.

        Lists all instances of the given class. If the properties are not
        specified, all properties are displayed. By default, the column
        widths are the width of the largest value. The width may be
        explicitly defined by defining the property as "name:width".
        For example::

          roundup> table priority id,name:10
          Id Name
          1  fatal-bug
          2  bug
          3  usability
          4  feature

        Also to make the width of the column the width of the label,
        leave a trailing : without a width on the property. For example::

          roundup> table priority id,name:
          Id Name
          1  fata
          2  bug
          3  usab
          4  feat

        will result in a the 4 character wide "Name" column.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))
        classname = args[0]

        retired = self.settings['_retired_val']

        # get the class
        cl = self.get_class(classname)

        # figure the property names to display
        if len(args) > 1:
            prop_names = args[1].split(',')
            all_props = cl.getprops()
            for spec in prop_names:
                if ':' in spec:
                    try:
                        propname, width = spec.split(':')
                    except (ValueError, TypeError):
                        raise UsageError(_('"%(spec)s" not '
                                           'name:width') % locals())
                else:
                    propname = spec
                if propname not in all_props:
                    raise UsageError(_('%(classname)s has no property '
                                       '"%(propname)s"') % locals())
        else:
            prop_names = cl.getprops()

        # now figure column widths
        props = []
        for spec in prop_names:
            if ':' in spec:
                name, width = spec.split(':')
                if width == '':
                    # spec includes trailing :, use label/name width
                    props.append((name, len(name)))
                else:
                    try:
                        props.append((name, int(width)))
                    except ValueError:
                        raise UsageError(_('"%(spec)s" does not have an '
                                           'integer width: "%(width)s"') %
                                         locals())
            else:
                # this is going to be slow
                maxlen = len(spec)
                for nodeid in cl.getnodeids(retired=retired):
                    curlen = len(str(cl.get(nodeid, spec)))
                    if curlen > maxlen:
                        maxlen = curlen
                props.append((spec, maxlen))

        # now display the heading
        print(' '.join([name.capitalize().ljust(width)
                        for name, width in props]))

        # and the table data
        for nodeid in cl.getnodeids(retired=retired):
            table_columns = []
            for name, width in props:
                if name != 'id':
                    try:
                        value = str(cl.get(nodeid, name))
                    except KeyError:
                        # we already checked if the property is valid - a
                        # KeyError here means the node just doesn't have a
                        # value for it
                        value = ''
                else:
                    value = str(nodeid)
                f = '%%-%ds' % width
                table_columns.append(f % value[:width])
            print(' '.join(table_columns))
        return 0

    def do_templates(self, args):
        ''"""Usage: templates [trace_search]
        List templates and their installed directories.

        With trace_search also list all directories that are
        searched for templates.
        """
        import textwrap

        trace_search = False
        if args and args[0] == "trace_search":
            trace_search = True

        templates = self.listTemplates(trace_search=trace_search)

        for name in sorted(templates.keys()):
            templates[name]['description'] = textwrap.fill(
                "\n".join([line.lstrip() for line in
                           templates[name]['description'].split("\n")]),
                70,
                subsequent_indent="      ",
            )
            print("""
Name: %(name)s
Path: %(path)s
Desc: %(description)s
""" % templates[name])

    def do_updateconfig(self, args):
        ''"""Usage: updateconfig <filename>
        Generate an updated tracker config file (ini style) in
        <filename>. Use current settings from existing roundup
        tracker in tracker home.
        """
        self.do_genconfig(args, update=True)

    def usageError_feedback(self, message, function):
        print(_('Error: %s') % message)
        print()
        print(function.__doc__)
        return 1

    def run_command(self, args):
        """Run a single command
        """
        command = args[0]

        # handle help now
        if command == 'help':
            if len(args) > 1:
                self.do_help(args[1:])
            else:
                self.do_help(['help'])
            return 0
        if command == 'morehelp':
            self.do_help(['help'])
            self.help_commands()
            self.help_all()
            return 0

        if command == 'htmlhelp':
            self.help_commands_html()
            return 0

        # figure what the command is
        try:
            functions = self.commands.get(command)
        except KeyError:
            # not a valid command
            print(_('Unknown command "%(command)s" ("help commands" for a '
                    'list)') % locals())
            return 1

        # check for multiple matches
        if len(functions) > 1:
            print(_('Multiple commands match "%(command)s": %(list)s') %
                  {'command': command,
                   'list': ', '.join([i[0] for i in functions])})
            return 1
        command, function = functions[0]

        if command in ['genconfig', 'templates']:
            try:
                return function(args[1:])
            except UsageError as message:
                return self.usageError_feedback(message, function)

        # make sure we have a tracker_home
        while not self.tracker_home:
            if not self.force:
                self.tracker_home = self.my_input(_('Enter tracker home: ')).strip()
            else:
                self.tracker_home = os.curdir

        # before we open the db, we may be doing an install or init
        if command == 'initialise':
            try:
                return self.do_initialise(self.tracker_home, args)
            except UsageError as message:
                return self.usageError_feedback(message, function)
        elif command == 'install':
            try:
                return self.do_install(self.tracker_home, args)
            except UsageError as message:
                return self.usageError_feedback(message, function)

        # get the tracker
        try:
            if self.tracker and not self.settings['_reopen_tracker']:
                tracker = self.tracker
            else:
                if self.settings["verbose"]:
                    print("Reopening tracker")
                tracker = roundup.instance.open(self.tracker_home)
                self.tracker = tracker
                self.settings['indexer_backend'] = self.tracker.config['INDEXER']

        except ValueError as message:  # noqa: F841  -- used from locals
            self.tracker_home = ''
            print(_("Error: Couldn't open tracker: %(message)s") % locals())
            return 1
        except NoConfigError as message:  # noqa: F841  -- used from locals
            self.tracker_home = ''
            print(_("Error: Couldn't open tracker: %(message)s") % locals())
            return 1
        # message used via locals
        except ParsingOptionError as message:  # noqa: F841 -- used from locals
            print("%(message)s" % locals())
            return 1

        # only open the database once!
        if not self.db:
            self.db = tracker.open(self.name)
            # don't use tracker.config["TRACKER_LANGUAGE"] here as the
            # cli operator likely wants to have i18n as set in the
            # environment.
            # This is needed to fetch the locale's of the tracker's home dir.
            self.db.i18n = get_translation(tracker_home=tracker.tracker_home)

        self.db.tx_Source = 'cli'

        # do the command
        ret = 0
        try:
            ret = function(args[1:])
        except UsageError as message:
            ret = self.usageError_feedback(message, function)
        except Exception:
            import traceback
            traceback.print_exc()
            ret = 1
        return ret

    def history_features(self, feature):
        """ self.settings['history_features'] = 0: load rc, load/save history
         self.settings['history_features'] = 1: do not load history
         self.settings['history_features'] = 2: do not save history
         self.settings['history_features'] = 4: don't load rc
        """

        features = {  # bit bashing
            'load_history': 1,
            'save_history': 2,
            'load_rc': 4}

        # setting the bit disables the feature, so use not.
        return not self.settings['history_features'] & features[feature]

    def interactive(self):
        """Run in an interactive mode
        """
        print(_('Roundup %s ready for input.\nType "help" for help.')
                % roundup_version)

        initfile = os.path.join(os.path.expanduser("~"),
                                ".roundup_admin_rlrc")
        histfile = os.path.join(os.path.expanduser("~"),
                                ".roundup_admin_history")

        try:
            import readline
            try:
                if self.history_features('load_rc'):
                    readline.read_init_file(initfile)
            except IOError: # FileNotFoundError under python3
                # file is optional
                pass

            try:
                if self.history_features('load_history'):
                    readline.read_history_file(histfile)
            except IOError:  # FileNotFoundError under python3
                # no history file yet
                pass

            # Default history length is unlimited.
            # Set persistently in readline init file
            # Pragma history_length allows setting on a per
            #   invocation basis at startup
            if self.settings['history_length'] != -1:
                readline.set_history_length(
                    self.settings['history_length'])
        except ImportError:
            readline = None
            print(_('Note: command history and editing not available'))

        while 1:
            try:
                command = self.my_input('roundup> ')
            except EOFError:
                print(_('exit...'))
                break
            if not command: continue  # noqa: E701
            try:
                args = token_r.token_split(command)
            except ValueError:
                continue        # Ignore invalid quoted token
            if not args: continue  # noqa: E701
            if args[0] in ('quit', 'exit'): break   # noqa: E701
            self.run_command(args)

        # exit.. check for transactions
        if self.db and self.db_uncommitted:
            commit = self.my_input(_('There are unsaved changes. Commit them (y/N)? '))
            if commit and commit[0].lower() == 'y':
                self.db.commit()

        # looks like histfile is saved with mode 600
        if readline and self.history_features('save_history'):
                readline.write_history_file(histfile)
        return 0

    def main(self):  # noqa: PLR0912, PLR0911
        try:
            opts, args = getopt.getopt(sys.argv[1:], 'i:u:hcdP:sS:vV')
        except getopt.GetoptError as e:
            self.usage(str(e))
            return 1

        # handle command-line args
        self.tracker_home = os.environ.get('TRACKER_HOME', '')
        self.name = 'admin'
        self.password = ''  # unused
        if 'ROUNDUP_LOGIN' in os.environ:
            login_env = os.environ['ROUNDUP_LOGIN'].split(':')
            self.name = login_env[0]
            if len(login_env) > 1:
                self.password = login_env[1]
        self.separator = None
        self.print_designator = 0
        self.verbose = 0
        for opt, arg in opts:
            if opt == '-h':
                self.usage()
                return 0
            elif opt == '-v':  # noqa: RET505 - allow elif after returns
                print('%s (python %s)' % (roundup_version,
                                          sys.version.split()[0]))
                return 0
            elif opt == '-V':
                self.verbose = 1
            elif opt == '-i':
                self.tracker_home = arg
            elif opt == '-c':
                if self.separator is not None:
                    self.usage('Only one of -c, -S and -s may be specified')
                    return 1
                self.separator = ','
            elif opt == '-S':
                if self.separator is not None:
                    self.usage('Only one of -c, -S and -s may be specified')
                    return 1
                self.separator = arg
            elif opt == '-s':
                if self.separator is not None:
                    self.usage('Only one of -c, -S and -s may be specified')
                    return 1
                self.separator = ' '
            elif opt == '-d':
                self.print_designator = 1
            elif opt == '-P':
                try:
                    self.do_pragma([arg])
                except UsageError as e:
                    print('\n%s\n' % e)
            elif opt == '-u':
                login_opt = arg.split(':')
                self.name = login_opt[0]
                if len(login_opt) > 1:
                    self.password = login_opt[1]

        # if no command - go interactive
        # wrap in a try/finally so we always close off the db
        ret = 0
        try:
            if not args:
                self.interactive()
            else:
                ret = self.run_command(args)
                if self.db: self.db.commit()  # noqa: E701
            return ret
        finally:
            if self.db:
                self.db.close()


if __name__ == '__main__':
    tool = AdminTool()
    sys.exit(tool.main())

# vim: set filetype=python sts=4 sw=4 et si :
