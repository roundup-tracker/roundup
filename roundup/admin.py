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
__docformat__ = 'restructuredtext'

import csv, getopt, getpass, os, re, shutil, sys, UserDict, operator

from roundup import date, hyperdb, roundupdb, init, password, token
from roundup import __version__ as roundup_version
import roundup.instance
from roundup.configuration import CoreConfig
from roundup.i18n import _
from roundup.exceptions import UsageError

class CommandDict(UserDict.UserDict):
    """Simple dictionary that lets us do lookups using partial keys.

    Original code submitted by Engelbert Gruber.
    """
    _marker = []
    def get(self, key, default=_marker):
        if key in self.data:
            return [(key, self.data[key])]
        keylist = sorted(self.data)
        l = []
        for ki in keylist:
            if ki.startswith(key):
                l.append((ki, self.data[ki]))
        if not l and default is self._marker:
            raise KeyError(key)
        return l

class AdminTool:
    """ A collection of methods used in maintaining Roundup trackers.

        Typically these methods are accessed through the roundup-admin
        script. The main() method provided on this class gives the main
        loop for the roundup-admin script.

        Actions are defined by do_*() methods, with help for the action
        given in the method docstring.

        Additional help may be supplied by help_*() methods.
    """
    def __init__(self):
        self.commands = CommandDict()
        for k in AdminTool.__dict__:
            if k[:3] == 'do_':
                self.commands[k[3:]] = getattr(self, k)
        self.help = {}
        for k in AdminTool.__dict__:
            if k[:5] == 'help_':
                self.help[k[5:]] = getattr(self, k)
        self.tracker_home = ''
        self.db = None
        self.db_uncommitted = False

    def get_class(self, classname):
        """Get the class - raise an exception if it doesn't exist.
        """
        try:
            return self.db.getclass(classname)
        except KeyError:
            raise UsageError(_('no such class "%(classname)s"')%locals())

    def props_from_args(self, args):
        """ Produce a dictionary of prop: value from the args list.

            The args list is specified as ``prop=value prop=value ...``.
        """
        props = {}
        for arg in args:
            if arg.find('=') == -1:
                raise UsageError(_('argument "%(arg)s" not propname=value'
                    )%locals())
            l = arg.split('=')
            if len(l) < 2:
                raise UsageError(_('argument "%(arg)s" not propname=value'
                    )%locals())
            key, value = l[0], '='.join(l[1:])
            if value:
                props[key] = value
            else:
                props[key] = None
        return props

    def usage(self, message=''):
        """ Display a simple usage message.
        """
        if message:
            message = _('Problem: %(message)s\n\n')%locals()
        print _("""%(message)sUsage: roundup-admin [options] [<command> <arguments>]

Options:
 -i instance home  -- specify the issue tracker "home directory" to administer
 -u                -- the user[:password] to use for commands
 -d                -- print full designators not just class id numbers
 -c                -- when outputting lists of data, comma-separate them.
                      Same as '-S ","'.
 -S <string>       -- when outputting lists of data, string-separate them
 -s                -- when outputting lists of data, space-separate them.
                      Same as '-S " "'.
 -V                -- be verbose when importing
 -v                -- report Roundup and Python versions (and quit)

 Only one of -s, -c or -S can be specified.

Help:
 roundup-admin -h
 roundup-admin help                       -- this help
 roundup-admin help <command>             -- command-specific help
 roundup-admin help all                   -- all available help
""")%locals()
        self.help_commands()

    def help_commands(self):
        """List the commands available with their help summary.
        """
        print _('Commands:'),
        commands = ['']
        for command in self.commands.itervalues():
            h = _(command.__doc__).split('\n')[0]
            commands.append(' '+h[7:])
        commands.sort()
        commands.append(_(
"""Commands may be abbreviated as long as the abbreviation
matches only one command, e.g. l == li == lis == list."""))
        print '\n'.join(commands)
        print

    def help_commands_html(self, indent_re=re.compile(r'^(\s+)\S+')):
        """ Produce an HTML command list.
        """
        commands = sorted(self.commands.itervalues(),
            operator.attrgetter('__name__'))
        for command in commands:
            h = _(command.__doc__).split('\n')
            name = command.__name__[3:]
            usage = h[0]
            print """
<tr><td valign=top><strong>%(name)s</strong></td>
    <td><tt>%(usage)s</tt><p>
<pre>""" % locals()
            indent = indent_re.match(h[3])
            if indent: indent = len(indent.group(1))
            for line in h[3:]:
                if indent:
                    print line[indent:]
                else:
                    print line
            print '</pre></td></tr>\n'

    def help_all(self):
        print _("""
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
command-line.

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
""")
        for name, command in self.commands.items():
            print _('%s:')%name
            print '   ', _(command.__doc__)

    def do_help(self, args, nl_re=re.compile('[\r\n]'),
            indent_re=re.compile(r'^(\s+)\S+')):
        ''"""Usage: help topic
        Give help about topic.

        commands  -- list commands
        <command> -- help specific to a command
        initopts  -- init command options
        all       -- all available help
        """
        if len(args)>0:
            topic = args[0]
        else:
            topic = 'help'


        # try help_ methods
        if topic in self.help:
            self.help[topic]()
            return 0

        # try command docstrings
        try:
            l = self.commands.get(topic)
        except KeyError:
            print _('Sorry, no help for "%(topic)s"')%locals()
            return 1

        # display the help for each match, removing the docsring indent
        for name, help in l:
            lines = nl_re.split(_(help.__doc__))
            print lines[0]
            indent = indent_re.match(lines[1])
            if indent: indent = len(indent.group(1))
            for line in lines[1:]:
                if indent:
                    print line[indent:]
                else:
                    print line
        return 0

    def listTemplates(self):
        """ List all the available templates.

        Look in the following places, where the later rules take precedence:

         1. <roundup.admin.__file__>/../../share/roundup/templates/*
            this is where they will be if we installed an egg via easy_install
         2. <prefix>/share/roundup/templates/*
            this should be the standard place to find them when Roundup is
            installed
         3. <roundup.admin.__file__>/../templates/*
            this will be used if Roundup's run in the distro (aka. source)
            directory
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
        templates = {}
        for N in 2, 4, 5:
            path = __file__
            # move up N elements in the path
            for i in range(N):
                path = os.path.dirname(path)
            tdir = os.path.join(path, 'share', 'roundup', 'templates')
            if os.path.isdir(tdir):
                templates = init.listTemplates(tdir)
                break

        # OK, now try as if we're in the roundup source distribution
        # directory, so this module will be in .../roundup-*/roundup/admin.py
        # and we're interested in the .../roundup-*/ part.
        path = __file__
        for i in range(2):
            path = os.path.dirname(path)
        tdir = os.path.join(path, 'templates')
        if os.path.isdir(tdir):
            templates.update(init.listTemplates(tdir))

        # Try subdirs of the current dir
        templates.update(init.listTemplates(os.getcwd()))

        # Finally, try the current directory as a template
        template = init.loadTemplateInfo(os.getcwd())
        if template:
            templates[template['name']] = template

        return templates

    def help_initopts(self):
        templates = self.listTemplates()
        print _('Templates:'), ', '.join(templates)
        import roundup.backends
        backends = roundup.backends.list_backends()
        print _('Back ends:'), ', '.join(backends)

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
                ' does not exist')%locals())

        config_ini_file = os.path.join(tracker_home, CoreConfig.INI_FILE)
        # check for both old- and new-style configs
        if list(filter(os.path.exists, [config_ini_file,
                os.path.join(tracker_home, 'config.py')])):
            ok = raw_input(_(
"""WARNING: There appears to be a tracker in "%(tracker_home)s"!
If you re-install it, you will lose all the data!
Erase it? Y/N: """) % locals())
            if ok.strip().lower() != 'y':
                return 0

            # clear it out so the install isn't confused
            shutil.rmtree(tracker_home)

        # select template
        templates = self.listTemplates()
        template = len(args) > 1 and args[1] or ''
        if template not in templates:
            print _('Templates:'), ', '.join(templates)
        while template not in templates:
            template = raw_input(_('Select template [classic]: ')).strip()
            if not template:
                template = 'classic'

        # select hyperdb backend
        import roundup.backends
        backends = roundup.backends.list_backends()
        backend = len(args) > 2 and args[2] or ''
        if backend not in backends:
            print _('Back ends:'), ', '.join(backends)
        while backend not in backends:
            backend = raw_input(_('Select backend [anydbm]: ')).strip()
            if not backend:
                backend = 'anydbm'
        # XXX perform a unit test based on the user's selections

        # Process configuration file definitions
        if len(args) > 3:
            try:
                defns = dict([item.split("=") for item in args[3].split(",")])
            except:
                print _('Error in configuration settings: "%s"') % args[3]
                raise
        else:
            defns = {}

        # install!
        init.install(tracker_home, templates[template]['path'], settings=defns)
        init.write_select_db(tracker_home, backend)

        print _("""
---------------------------------------------------------------------------
 You should now edit the tracker configuration file:
   %(config_file)s""") % {"config_file": config_ini_file}

        # find list of options that need manual adjustments
        # XXX config._get_unset_options() is marked as private
        #   (leading underscore).  make it public or don't care?
        need_set = CoreConfig(tracker_home)._get_unset_options()
        if need_set:
            print _(" ... at a minimum, you must set following options:")
            for section in need_set:
                print "   [%s]: %s" % (section, ", ".join(need_set[section]))

        # note about schema modifications
        print _("""
 If you wish to modify the database schema,
 you should also edit the schema file:
   %(database_config_file)s
 You may also change the database initialisation file:
   %(database_init_file)s
 ... see the documentation on customizing for more information.

 You MUST run the "roundup-admin initialise" command once you've performed
 the above steps.
---------------------------------------------------------------------------
""") % {
    'database_config_file': os.path.join(tracker_home, 'schema.py'),
    'database_init_file': os.path.join(tracker_home, 'initial_data.py'),
}
        return 0

    def do_genconfig(self, args):
        ''"""Usage: genconfig <filename>
        Generate a new tracker config file (ini style) with default values
        in <filename>.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))
        config = CoreConfig()
        config.save(args[0])

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
            raise UsageError(_('Instance home does not exist')%locals())
        try:
            tracker = roundup.instance.open(tracker_home)
        except roundup.instance.TrackerError:
            raise UsageError(_('Instance has not been installed')%locals())

        # is there already a database?
        if tracker.exists():
            ok = raw_input(_(
"""WARNING: The database is already initialised!
If you re-initialise it, you will lose all the data!
Erase it? Y/N: """))
            if ok.strip().lower() != 'y':
                return 0

            backend = tracker.get_backend_name()

            # nuke it
            tracker.nuke()

            # re-write the backend select file
            init.write_select_db(tracker_home, backend, tracker.config.DATABASE)

        # GO
        tracker.init(password.Password(adminpw, config=tracker.config))

        return 0


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
        l = []
        for designator in designators:
            # decode the node designator
            try:
                classname, nodeid = hyperdb.splitDesignator(designator)
            except hyperdb.DesignatorError, message:
                raise UsageError(message)

            # get the class
            cl = self.get_class(classname)
            try:
                id=[]
                if self.separator:
                    if self.print_designator:
                        # see if property is a link or multilink for
                        # which getting a desginator make sense.
                        # Algorithm: Get the properties of the
                        #     current designator's class. (cl.getprops)
                        # get the property object for the property the
                        #     user requested (properties[propname])
                        # verify its type (isinstance...)
                        # raise error if not link/multilink
                        # get class name for link/multilink property
                        # do the get on the designators
                        # append the new designators
                        # print
                        properties = cl.getprops()
                        property = properties[propname]
                        if not (isinstance(property, hyperdb.Multilink) or
                          isinstance(property, hyperdb.Link)):
                            raise UsageError(_('property %s is not of type'
                                ' Multilink or Link so -d flag does not '
                                'apply.')%propname)
                        propclassname = self.db.getclass(property.classname).classname
                        id = cl.get(nodeid, propname)
                        for i in id:
                            l.append(propclassname + i)
                    else:
                        id = cl.get(nodeid, propname)
                        for i in id:
                            l.append(i)
                else:
                    if self.print_designator:
                        properties = cl.getprops()
                        property = properties[propname]
                        if not (isinstance(property, hyperdb.Multilink) or
                          isinstance(property, hyperdb.Link)):
                            raise UsageError(_('property %s is not of type'
                                ' Multilink or Link so -d flag does not '
                                'apply.')%propname)
                        propclassname = self.db.getclass(property.classname).classname
                        id = cl.get(nodeid, propname)
                        for i in id:
                            print propclassname + i
                    else:
                        print cl.get(nodeid, propname)
            except IndexError:
                raise UsageError(_('no such %(classname)s node '
                    '"%(nodeid)s"')%locals())
            except KeyError:
                raise UsageError(_('no such %(classname)s property '
                    '"%(propname)s"')%locals())
        if self.separator:
            print self.separator.join(l)

        return 0


    def do_set(self, args):
        ''"""Usage: set items property=value property=value ...
        Set the given properties of one or more items(s).

        The items are specified as a class or as a comma-separated
        list of item designators (ie "designator[,designator,...]").

        A designator is a classname and a nodeid concatenated,
        eg. bug1, user10, ...

        This command sets the properties to the values for all designators
        given. If the value is missing (ie. "property=") then the property
        is un-set. If the property is a multilink, you specify the linked
        ids for the multilink as comma-separated numbers (ie "1,2,3").
        """
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
            except hyperdb.DesignatorError, message:
                raise UsageError(message)

        # get the props from the args
        props = self.props_from_args(args[1:])

        # now do the set for all the nodes
        for classname, itemid in designators:
            cl = self.get_class(classname)

            properties = cl.getprops()
            for key, value in props.items():
                try:
                    props[key] = hyperdb.rawToHyperdb(self.db, cl, itemid,
                        key, value)
                except hyperdb.HyperdbValueError, message:
                    raise UsageError(message)

            # try the set
            try:
                cl.set(itemid, **props)
            except (TypeError, IndexError, ValueError), message:
                import traceback; traceback.print_exc()
                raise UsageError(message)
        self.db_uncommitted = True
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
        for propname, value in props.iteritems():
            if ',' in value:
                values = value.split(',')
            else:
                values = [value]
            d = props[propname] = {}
            for value in values:
                value = hyperdb.rawToHyperdb(self.db, cl, None, propname, value)
                if isinstance(value, list):
                    for entry in value:
                        d[entry] = 1
                else:
                    d[value] = 1

        # now do the find
        try:
            id = []
            designator = []
            if self.separator:
                if self.print_designator:
                    id = cl.find(**props)
                    for i in id:
                        designator.append(classname + i)
                    print self.separator.join(designator)
                else:
                    print self.separator.join(cl.find(**props))

            else:
                if self.print_designator:
                    id = cl.find(**props)
                    for i in id:
                        designator.append(classname + i)
                    print designator
                else:
                    print cl.find(**props)
        except KeyError:
            raise UsageError(_('%(classname)s has no property '
                '"%(propname)s"')%locals())
        except (ValueError, TypeError), message:
            raise UsageError(message)
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
        for key in cl.properties:
            value = cl.properties[key]
            if keyprop == key:
                print _('%(key)s: %(value)s (key property)')%locals()
            else:
                print _('%(key)s: %(value)s')%locals()

    def do_display(self, args):
        ''"""Usage: display designator[,designator]*
        Show the property values for the given node(s).

        A designator is a classname and a nodeid concatenated,
        eg. bug1, user10, ...

        This lists the properties and their associated values for the given
        node.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))

        # decode the node designator
        for designator in args[0].split(','):
            try:
                classname, nodeid = hyperdb.splitDesignator(designator)
            except hyperdb.DesignatorError, message:
                raise UsageError(message)

            # get the class
            cl = self.get_class(classname)

            # display the values
            keys = sorted(cl.properties)
            for key in keys:
                value = cl.get(nodeid, key)
                print _('%(key)s: %(value)s')%locals()

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
        properties = cl.getprops(protected = 0)
        if len(args) == 1:
            # ask for the properties
            for key in properties:
                if key == 'id': continue
                value = properties[key]
                name = value.__class__.__name__
                if isinstance(value , hyperdb.Password):
                    again = None
                    while value != again:
                        value = getpass.getpass(_('%(propname)s (Password): ')%{
                            'propname': key.capitalize()})
                        again = getpass.getpass(_('   %(propname)s (Again): ')%{
                            'propname': key.capitalize()})
                        if value != again: print _('Sorry, try again...')
                    if value:
                        props[key] = value
                else:
                    value = raw_input(_('%(propname)s (%(proptype)s): ')%{
                        'propname': key.capitalize(), 'proptype': name})
                    if value:
                        props[key] = value
        else:
            props = self.props_from_args(args[1:])

        # convert types
        for propname in props:
            try:
                props[propname] = hyperdb.rawToHyperdb(self.db, cl, None,
                    propname, props[propname])
            except hyperdb.HyperdbValueError, message:
                raise UsageError(message)

        # check for the key property
        propname = cl.getkey()
        if propname and propname not in props:
            raise UsageError(_('you must provide the "%(propname)s" '
                'property.')%locals())

        # do the actual create
        try:
            print cl.create(**props)
        except (TypeError, IndexError, ValueError), message:
            raise UsageError(message)
        self.db_uncommitted = True
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
        classname = args[0]
        
        # get the class
        cl = self.get_class(classname)

        # figure the property
        if len(args) > 1:
            propname = args[1]
        else:
            propname = cl.labelprop()

        if self.separator:
            if len(args) == 2:
                # create a list of propnames since user specified propname
                proplist=[]
                for nodeid in cl.list():
                    try:
                        proplist.append(cl.get(nodeid, propname))
                    except KeyError:
                        raise UsageError(_('%(classname)s has no property '
                            '"%(propname)s"')%locals())
                print self.separator.join(proplist)
            else:
                # create a list of index id's since user didn't specify
                # otherwise
                print self.separator.join(cl.list())
        else:
            for nodeid in cl.list():
                try:
                    value = cl.get(nodeid, propname)
                except KeyError:
                    raise UsageError(_('%(classname)s has no property '
                        '"%(propname)s"')%locals())
                print _('%(nodeid)4s: %(value)s')%locals()
        return 0

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
                            'name:width')%locals())
                else:
                    propname = spec
                if propname not in all_props:
                    raise UsageError(_('%(classname)s has no property '
                        '"%(propname)s"')%locals())
        else:
            prop_names = cl.getprops()

        # now figure column widths
        props = []
        for spec in prop_names:
            if ':' in spec:
                name, width = spec.split(':')
                if width == '':
                    props.append((name, len(spec)))
                else:
                    props.append((name, int(width)))
            else:
               # this is going to be slow
               maxlen = len(spec)
               for nodeid in cl.list():
                   curlen = len(str(cl.get(nodeid, spec)))
                   if curlen > maxlen:
                       maxlen = curlen
               props.append((spec, maxlen))

        # now display the heading
        print ' '.join([name.capitalize().ljust(width) for name,width in props])

        # and the table data
        for nodeid in cl.list():
            l = []
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
                f = '%%-%ds'%width
                l.append(f%value[:width])
            print ' '.join(l)
        return 0

    def do_history(self, args):
        ''"""Usage: history designator
        Show the history entries of a designator.

        A designator is a classname and a nodeid concatenated,
        eg. bug1, user10, ...

        Lists the journal entries for the node identified by the designator.
        """
        if len(args) < 1:
            raise UsageError(_('Not enough arguments supplied'))
        try:
            classname, nodeid = hyperdb.splitDesignator(args[0])
        except hyperdb.DesignatorError, message:
            raise UsageError(message)

        try:
            print self.db.getclass(classname).history(nodeid)
        except KeyError:
            raise UsageError(_('no such class "%(classname)s"')%locals())
        except IndexError:
            raise UsageError(_('no such %(classname)s node '
                '"%(nodeid)s"')%locals())
        return 0

    def do_commit(self, args):
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

    def do_rollback(self, args):
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
            except hyperdb.DesignatorError, message:
                raise UsageError(message)
            try:
                self.db.getclass(classname).retire(nodeid)
            except KeyError:
                raise UsageError(_('no such class "%(classname)s"')%locals())
            except IndexError:
                raise UsageError(_('no such %(classname)s node '
                    '"%(nodeid)s"')%locals())
        self.db_uncommitted = True
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
            except hyperdb.DesignatorError, message:
                raise UsageError(message)
            try:
                self.db.getclass(classname).restore(nodeid)
            except KeyError:
                raise UsageError(_('no such class "%(classname)s"')%locals())
            except IndexError:
                raise UsageError(_('no such %(classname)s node '
                    '"%(nodeid)s"')%locals())
        self.db_uncommitted = True
        return 0

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

        dir = args[-1]

        # get the list of classes to export
        if len(args) == 2:
            if args[0].startswith('-'):
                classes = [ c for c in self.db.classes
                            if not c in args[0][1:].split(',') ]
            else:
                classes = args[0].split(',')
        else:
            classes = self.db.classes

        class colon_separated(csv.excel):
            delimiter = ':'

        # make sure target dir exists
        if not os.path.exists(dir):
            os.makedirs(dir)

        # maximum csv field length exceeding configured size?
        max_len = self.db.config.CSV_FIELD_SIZE

        # do all the classes specified
        for classname in classes:
            cl = self.get_class(classname)

            if not export_files and hasattr(cl, 'export_files'):
                sys.stdout.write('Exporting %s WITHOUT the files\r\n'%
                    classname)

            f = open(os.path.join(dir, classname+'.csv'), 'wb')
            writer = csv.writer(f, colon_separated)

            properties = cl.getprops()
            propnames = cl.export_propnames()
            fields = propnames[:]
            fields.append('is retired')
            writer.writerow(fields)

            # all nodes for this class
            for nodeid in cl.getnodeids():
                if self.verbose:
                    sys.stdout.write('\rExporting %s - %s'%(classname, nodeid))
                    sys.stdout.flush()
                node = cl.getnode(nodeid)
                exp = cl.export_list(propnames, nodeid)
                lensum = sum ([len (repr(node[p])) for p in propnames])
                # for a safe upper bound of field length we add
                # difference between CSV len and sum of all field lengths
                d = sum ([len(x) for x in exp]) - lensum
                assert (d > 0)
                for p in propnames:
                    ll = len(repr(node[p])) + d
                    if ll > max_len:
                        max_len = ll
                writer.writerow(exp)
                if export_files and hasattr(cl, 'export_files'):
                    cl.export_files(dir, nodeid)

            # close this file
            f.close()

            # export the journals
            jf = open(os.path.join(dir, classname+'-journals.csv'), 'wb')
            if self.verbose:
                sys.stdout.write("\nExporting Journal for %s\n" % classname)
                sys.stdout.flush()
            journals = csv.writer(jf, colon_separated)
            for row in cl.export_journals():
                journals.writerow(row)
            jf.close()
        if max_len > self.db.config.CSV_FIELD_SIZE:
            print >> sys.stderr, \
                "Warning: config csv_field_size should be at least %s"%max_len
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

    def do_import(self, args):
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
        from roundup import hyperdb

        if hasattr (csv, 'field_size_limit'):
            csv.field_size_limit(self.db.config.CSV_FIELD_SIZE)

        # directory to import from
        dir = args[0]

        class colon_separated(csv.excel):
            delimiter = ':'

        # import all the files
        for file in os.listdir(dir):
            classname, ext = os.path.splitext(file)
            # we only care about CSV files
            if ext != '.csv' or classname.endswith('-journals'):
                continue

            cl = self.get_class(classname)

            # ensure that the properties and the CSV file headings match
            f = open(os.path.join(dir, file), 'r')
            reader = csv.reader(f, colon_separated)
            file_props = None
            maxid = 1
            # loop through the file and create a node for each entry
            for n, r in enumerate(reader):
                if file_props is None:
                    file_props = r
                    continue

                if self.verbose:
                    sys.stdout.write('\rImporting %s - %s'%(classname, n))
                    sys.stdout.flush()

                # do the import and figure the current highest nodeid
                nodeid = cl.import_list(file_props, r)
                if hasattr(cl, 'import_files'):
                    cl.import_files(dir, nodeid)
                maxid = max(maxid, int(nodeid))

            # (print to sys.stdout here to allow tests to squash it .. ugh)
            print >> sys.stdout

            f.close()

            # import the journals
            f = open(os.path.join(args[0], classname + '-journals.csv'), 'r')
            reader = csv.reader(f, colon_separated)
            cl.import_journals(reader)
            f.close()

            # (print to sys.stdout here to allow tests to squash it .. ugh)
            print >> sys.stdout, 'setting', classname, maxid+1

            # set the id counter
            self.db.setid(classname, str(maxid+1))

        self.db_uncommitted = True
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
            pack_before = date.Date(". - %s"%value)
        elif m['date']:
            pack_before = date.Date(value)
        self.db.pack(pack_before)
        self.db_uncommitted = True
        return 0

    def do_reindex(self, args, desre=re.compile('([A-Za-z]+)([0-9]+)')):
        ''"""Usage: reindex [classname|designator]*
        Re-generate a tracker's search indexes.

        This will re-generate the search indexes for a tracker.
        This will typically happen automatically.
        """
        if args:
            for arg in args:
                m = desre.match(arg)
                if m:
                    cl = self.get_class(m.group(1))
                    try:
                        cl.index(m.group(2))
                    except IndexError:
                        raise UsageError(_('no such item "%(designator)s"')%{
                            'designator': arg})
                else:
                    cl = self.get_class(arg)
                    self.db.reindex(arg)
        else:
            self.db.reindex(show_progress=True)
        return 0

    def do_security(self, args):
        ''"""Usage: security [Role name]
        Display the Permissions available to one or all Roles.
        """
        if len(args) == 1:
            role = args[0]
            try:
                roles = [(args[0], self.db.security.role[args[0]])]
            except KeyError:
                print _('No such Role "%(role)s"')%locals()
                return 1
        else:
            roles = list(self.db.security.role.items())
            role = self.db.config.NEW_WEB_USER_ROLES
            if ',' in role:
                print _('New Web users get the Roles "%(role)s"')%locals()
            else:
                print _('New Web users get the Role "%(role)s"')%locals()
            role = self.db.config.NEW_EMAIL_USER_ROLES
            if ',' in role:
                print _('New Email users get the Roles "%(role)s"')%locals()
            else:
                print _('New Email users get the Role "%(role)s"')%locals()
        roles.sort()
        for rolename, role in roles:
            print _('Role "%(name)s":')%role.__dict__
            for permission in role.permissions:
                d = permission.__dict__
                if permission.klass:
                    if permission.properties:
                        print _(' %(description)s (%(name)s for "%(klass)s"'
                          ': %(properties)s only)')%d
                    else:
                        print _(' %(description)s (%(name)s for "%(klass)s" '
                            'only)')%d
                else:
                    print _(' %(description)s (%(name)s)')%d
        return 0


    def do_migrate(self, args):
        ''"""Usage: migrate
        Update a tracker's database to be compatible with the Roundup
        codebase.

        You should run the "migrate" command for your tracker once you've
        installed the latest codebase. 

        Do this before you use the web, command-line or mail interface and
        before any users access the tracker.

        This command will respond with either "Tracker updated" (if you've
        not previously run it on an RDBMS backend) or "No migration action
        required" (if you have run it, or have used another interface to the
        tracker, or possibly because you are using anydbm).

        It's safe to run this even if it's not required, so just get into
        the habit.
        """
        if getattr(self.db, 'db_version_updated'):
            print _('Tracker updated')
            self.db_uncommitted = True
        else:
            print _('No migration action required')
        return 0

    def run_command(self, args):
        """Run a single command
        """
        command = args[0]

        # handle help now
        if command == 'help':
            if len(args)>1:
                self.do_help(args[1:])
                return 0
            self.do_help(['help'])
            return 0
        if command == 'morehelp':
            self.do_help(['help'])
            self.help_commands()
            self.help_all()
            return 0
        if command == 'config':
            self.do_config(args[1:])
            return 0

        # figure what the command is
        try:
            functions = self.commands.get(command)
        except KeyError:
            # not a valid command
            print _('Unknown command "%(command)s" ("help commands" for a '
                'list)')%locals()
            return 1

        # check for multiple matches
        if len(functions) > 1:
            print _('Multiple commands match "%(command)s": %(list)s')%{'command':
                command, 'list': ', '.join([i[0] for i in functions])}
            return 1
        command, function = functions[0]

        # make sure we have a tracker_home
        while not self.tracker_home:
            self.tracker_home = raw_input(_('Enter tracker home: ')).strip()

        # before we open the db, we may be doing an install or init
        if command == 'initialise':
            try:
                return self.do_initialise(self.tracker_home, args)
            except UsageError, message:
                print _('Error: %(message)s')%locals()
                return 1
        elif command == 'install':
            try:
                return self.do_install(self.tracker_home, args)
            except UsageError, message:
                print _('Error: %(message)s')%locals()
                return 1

        # get the tracker
        try:
            tracker = roundup.instance.open(self.tracker_home)
        except ValueError, message:
            self.tracker_home = ''
            print _("Error: Couldn't open tracker: %(message)s")%locals()
            return 1

        # only open the database once!
        if not self.db:
            self.db = tracker.open('admin')

        # do the command
        ret = 0
        try:
            ret = function(args[1:])
        except UsageError, message:
            print _('Error: %(message)s')%locals()
            print
            print function.__doc__
            ret = 1
        except:
            import traceback
            traceback.print_exc()
            ret = 1
        return ret

    def interactive(self):
        """Run in an interactive mode
        """
        print _('Roundup %s ready for input.\nType "help" for help.'
            % roundup_version)
        try:
            import readline
        except ImportError:
            print _('Note: command history and editing not available')

        while 1:
            try:
                command = raw_input(_('roundup> '))
            except EOFError:
                print _('exit...')
                break
            if not command: continue
            args = token.token_split(command)
            if not args: continue
            if args[0] in ('quit', 'exit'): break
            self.run_command(args)

        # exit.. check for transactions
        if self.db and self.db_uncommitted:
            commit = raw_input(_('There are unsaved changes. Commit them (y/N)? '))
            if commit and commit[0].lower() == 'y':
                self.db.commit()
        return 0

    def main(self):
        try:
            opts, args = getopt.getopt(sys.argv[1:], 'i:u:hcdsS:vV')
        except getopt.GetoptError, e:
            self.usage(str(e))
            return 1

        # handle command-line args
        self.tracker_home = os.environ.get('TRACKER_HOME', '')
        # TODO: reinstate the user/password stuff (-u arg too)
        name = password = ''
        if 'ROUNDUP_LOGIN' in os.environ:
            l = os.environ['ROUNDUP_LOGIN'].split(':')
            name = l[0]
            if len(l) > 1:
                password = l[1]
        self.separator = None
        self.print_designator = 0
        self.verbose = 0
        for opt, arg in opts:
            if opt == '-h':
                self.usage()
                return 0
            elif opt == '-v':
                print '%s (python %s)'%(roundup_version, sys.version.split()[0])
                return 0
            elif opt == '-V':
                self.verbose = 1
            elif opt == '-i':
                self.tracker_home = arg
            elif opt == '-c':
                if self.separator != None:
                    self.usage('Only one of -c, -S and -s may be specified')
                    return 1
                self.separator = ','
            elif opt == '-S':
                if self.separator != None:
                    self.usage('Only one of -c, -S and -s may be specified')
                    return 1
                self.separator = arg
            elif opt == '-s':
                if self.separator != None:
                    self.usage('Only one of -c, -S and -s may be specified')
                    return 1
                self.separator = ' '
            elif opt == '-d':
                self.print_designator = 1

        # if no command - go interactive
        # wrap in a try/finally so we always close off the db
        ret = 0
        try:
            if not args:
                self.interactive()
            else:
                ret = self.run_command(args)
                if self.db: self.db.commit()
            return ret
        finally:
            if self.db:
                self.db.close()

if __name__ == '__main__':
    tool = AdminTool()
    sys.exit(tool.main())

# vim: set filetype=python sts=4 sw=4 et si :
