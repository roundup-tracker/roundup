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
# $Id: admin.py,v 1.54 2003-05-29 00:42:34 richard Exp $

'''Administration commands for maintaining Roundup trackers.
'''

import sys, os, getpass, getopt, re, UserDict, shutil, rfc822
try:
    import csv
except ImportError:
    csv = None
from roundup import date, hyperdb, roundupdb, init, password, token
from roundup import __version__ as roundup_version
import roundup.instance
from roundup.i18n import _

class CommandDict(UserDict.UserDict):
    '''Simple dictionary that lets us do lookups using partial keys.

    Original code submitted by Engelbert Gruber.
    '''
    _marker = []
    def get(self, key, default=_marker):
        if self.data.has_key(key):
            return [(key, self.data[key])]
        keylist = self.data.keys()
        keylist.sort()
        l = []
        for ki in keylist:
            if ki.startswith(key):
                l.append((ki, self.data[ki]))
        if not l and default is self._marker:
            raise KeyError, key
        return l

class UsageError(ValueError):
    pass

class AdminTool:
    ''' A collection of methods used in maintaining Roundup trackers.

        Typically these methods are accessed through the roundup-admin
        script. The main() method provided on this class gives the main
        loop for the roundup-admin script.

        Actions are defined by do_*() methods, with help for the action
        given in the method docstring.

        Additional help may be supplied by help_*() methods.
    '''
    def __init__(self):
        self.commands = CommandDict()
        for k in AdminTool.__dict__.keys():
            if k[:3] == 'do_':
                self.commands[k[3:]] = getattr(self, k)
        self.help = {}
        for k in AdminTool.__dict__.keys():
            if k[:5] == 'help_':
                self.help[k[5:]] = getattr(self, k)
        self.tracker_home = ''
        self.db = None

    def get_class(self, classname):
        '''Get the class - raise an exception if it doesn't exist.
        '''
        try:
            return self.db.getclass(classname)
        except KeyError:
            raise UsageError, _('no such class "%(classname)s"')%locals()

    def props_from_args(self, args):
        ''' Produce a dictionary of prop: value from the args list.

            The args list is specified as ``prop=value prop=value ...``.
        '''
        props = {}
        for arg in args:
            if arg.find('=') == -1:
                raise UsageError, _('argument "%(arg)s" not propname=value'
                    )%locals()
            l = arg.split('=')
            if len(l) < 2:
                raise UsageError, _('argument "%(arg)s" not propname=value'
                    )%locals()
            key, value = l[0], '='.join(l[1:])
            if value:
                props[key] = value
            else:
                props[key] = None
        return props

    def usage(self, message=''):
        ''' Display a simple usage message.
        '''
        if message:
            message = _('Problem: %(message)s\n\n')%locals()
        print _('''%(message)sUsage: roundup-admin [options] [<command> <arguments>]

Options:
 -i instance home  -- specify the issue tracker "home directory" to administer
 -u                -- the user[:password] to use for commands
 -d                -- print full designators not just class id numbers
 -c                -- when outputting lists of data, comma-separate them.
		      Same as '-S ","'.
 -S <string>       -- when outputting lists of data, string-separate them
 -s                -- when outputting lists of data, space-separate them.
		      Same as '-S " "'.

 Only one of -s, -c or -S can be specified.

Help:
 roundup-admin -h
 roundup-admin help                       -- this help
 roundup-admin help <command>             -- command-specific help
 roundup-admin help all                   -- all available help
''')%locals()
        self.help_commands()

    def help_commands(self):
        ''' List the commands available with their precis help.
        '''
        print _('Commands:'),
        commands = ['']
        for command in self.commands.values():
            h = command.__doc__.split('\n')[0]
            commands.append(' '+h[7:])
        commands.sort()
        commands.append(_('Commands may be abbreviated as long as the abbreviation matches only one'))
        commands.append(_('command, e.g. l == li == lis == list.'))
        print '\n'.join(commands)
        print

    def help_commands_html(self, indent_re=re.compile(r'^(\s+)\S+')):
        ''' Produce an HTML command list.
        '''
        commands = self.commands.values()
        def sortfun(a, b):
            return cmp(a.__name__, b.__name__)
        commands.sort(sortfun)
        for command in commands:
            h = command.__doc__.split('\n')
            name = command.__name__[3:]
            usage = h[0]
            print _('''
<tr><td valign=top><strong>%(name)s</strong></td>
    <td><tt>%(usage)s</tt><p>
<pre>''')%locals()
            indent = indent_re.match(h[3])
            if indent: indent = len(indent.group(1))
            for line in h[3:]:
                if indent:
                    print line[indent:]
                else:
                    print line
            print _('</pre></td></tr>\n')

    def help_all(self):
        print _('''
All commands (except help) require a tracker specifier. This is just the path
to the roundup tracker you're working with. A roundup tracker is where 
roundup keeps the database and configuration file that defines an issue
tracker. It may be thought of as the issue tracker's "home directory". It may
be specified in the environment variable TRACKER_HOME or on the command
line as "-i tracker".

A designator is a classname and a nodeid concatenated, eg. bug1, user10, ...

Property values are represented as strings in command arguments and in the
printed results:
 . Strings are, well, strings.
 . Date values are printed in the full date format in the local time zone, and
   accepted in the full format or any of the partial formats explained below.
 . Link values are printed as node designators. When given as an argument,
   node designators and key strings are both accepted.
 . Multilink values are printed as lists of node designators joined by commas.
   When given as an argument, node designators and key strings are both
   accepted; an empty string, a single node, or a list of nodes joined by
   commas is accepted.

When property values must contain spaces, just surround the value with
quotes, either ' or ". A single space may also be backslash-quoted. If a
valuu must contain a quote character, it must be backslash-quoted or inside
quotes. Examples:
           hello world      (2 tokens: hello, world)
           "hello world"    (1 token: hello world)
           "Roch'e" Compaan (2 tokens: Roch'e Compaan)
           Roch\'e Compaan  (2 tokens: Roch'e Compaan)
           address="1 2 3"  (1 token: address=1 2 3)
           \\               (1 token: \)
           \n\r\t           (1 token: a newline, carriage-return and tab)

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
''')
        for name, command in self.commands.items():
            print _('%s:')%name
            print _('   '), command.__doc__

    def do_help(self, args, nl_re=re.compile('[\r\n]'),
            indent_re=re.compile(r'^(\s+)\S+')):
        '''Usage: help topic
        Give help about topic.

        commands  -- list commands
        <command> -- help specific to a command
        initopts  -- init command options
        all       -- all available help
        '''
        if len(args)>0:
            topic = args[0]
        else:
            topic = 'help'
 

        # try help_ methods
        if self.help.has_key(topic):
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
            lines = nl_re.split(help.__doc__)
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
        ''' List all the available templates.

            Look in three places:
                <prefix>/share/roundup/templates/*
                <__file__>/../templates/*
                current dir/*
                current dir as a template
        '''
        # OK, try <prefix>/share/roundup/templates
        # -- this module (roundup.admin) will be installed in something
        # like:
        #    /usr/lib/python2.2/site-packages/roundup/admin.py  (5 dirs up)
        #    c:\python22\lib\site-packages\roundup\admin.py     (4 dirs up)
        # we're interested in where the "lib" directory is - ie. the /usr/
        # part
        templates = {}
        for N in 4, 5:
            path = __file__
            # move up N elements in the path
            for i in range(N):
                path = os.path.dirname(path)
            tdir = os.path.join(path, 'share', 'roundup', 'templates')
            if os.path.isdir(tdir):
                templates = listTemplates(tdir)
                break

        # OK, now try as if we're in the roundup source distribution
        # directory, so this module will be in .../roundup-*/roundup/admin.py
        # and we're interested in the .../roundup-*/ part.
        path = __file__
        for i in range(2):
            path = os.path.dirname(path)
        tdir = os.path.join(path, 'templates')
        if os.path.isdir(tdir):
            templates.update(listTemplates(tdir))

        # Try subdirs of the current dir
        templates.update(listTemplates(os.getcwd()))

        # Finally, try the current directory as a template
        template = loadTemplate(os.getcwd())
        if template:
            templates[template['name']] = template

        return templates

    def help_initopts(self):
        templates = self.listTemplates()
        print _('Templates:'), ', '.join(templates.keys())
        import roundup.backends
        backends = roundup.backends.__all__
        print _('Back ends:'), ', '.join(backends)

    def do_install(self, tracker_home, args):
        '''Usage: install [template [backend [admin password]]]
        Install a new Roundup tracker.

        The command will prompt for the tracker home directory (if not supplied
        through TRACKER_HOME or the -i option). The template, backend and admin
        password may be specified on the command-line as arguments, in that
        order.

        The initialise command must be called after this command in order
        to initialise the tracker's database. You may edit the tracker's
        initial database contents before running that command by editing
        the tracker's dbinit.py module init() function.

        See also initopts help.
        '''
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')

        # make sure the tracker home can be created
        parent = os.path.split(tracker_home)[0]
        if not os.path.exists(parent):
            raise UsageError, _('Instance home parent directory "%(parent)s"'
                ' does not exist')%locals()

        # select template
        templates = self.listTemplates()
        template = len(args) > 1 and args[1] or ''
        if not templates.has_key(template):
            print _('Templates:'), ', '.join(templates.keys())
        while not templates.has_key(template):
            template = raw_input(_('Select template [classic]: ')).strip()
            if not template:
                template = 'classic'

        # select hyperdb backend
        import roundup.backends
        backends = roundup.backends.__all__
        backend = len(args) > 2 and args[2] or ''
        if backend not in backends:
            print _('Back ends:'), ', '.join(backends)
        while backend not in backends:
            backend = raw_input(_('Select backend [anydbm]: ')).strip()
            if not backend:
                backend = 'anydbm'
        # XXX perform a unit test based on the user's selections

        # install!
        init.install(tracker_home, templates[template]['path'])
        init.write_select_db(tracker_home, backend)

        print _('''
 You should now edit the tracker configuration file:
   %(config_file)s
 ... at a minimum, you must set MAILHOST, TRACKER_WEB, MAIL_DOMAIN and
 ADMIN_EMAIL.

 If you wish to modify the default schema, you should also edit the database
 initialisation file:
   %(database_config_file)s
 ... see the documentation on customizing for more information.
''')%{
    'config_file': os.path.join(tracker_home, 'config.py'),
    'database_config_file': os.path.join(tracker_home, 'dbinit.py')
}
        return 0


    def do_initialise(self, tracker_home, args):
        '''Usage: initialise [adminpw]
        Initialise a new Roundup tracker.

        The administrator details will be set at this step.

        Execute the tracker's initialisation function dbinit.init()
        '''
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
            raise UsageError, _('Instance home does not exist')%locals()
        try:
            tracker = roundup.instance.open(tracker_home)
        except roundup.instance.TrackerError:
            raise UsageError, _('Instance has not been installed')%locals()

        # is there already a database?
        try:
            db_exists = tracker.select_db.Database.exists(tracker.config)
        except AttributeError:
            # TODO: move this code to exists() static method in every backend
            db_exists = os.path.exists(os.path.join(tracker_home, 'db'))
        if db_exists:
            print _('WARNING: The database is already initialised!')
            print _('If you re-initialise it, you will lose all the data!')
            ok = raw_input(_('Erase it? Y/[N]: ')).strip()
            if ok.lower() != 'y':
                return 0

            # Get a database backend in use by tracker
            try:
                # nuke it
                tracker.select_db.Database.nuke(tracker.config)
            except AttributeError:
                # TODO: move this code to nuke() static method in every backend
                shutil.rmtree(os.path.join(tracker_home, 'db'))

        # GO
        init.initialise(tracker_home, adminpw)

        return 0


    def do_get(self, args):
        '''Usage: get property designator[,designator]*
        Get the given property of one or more designator(s).

        Retrieves the property value of the nodes specified by the designators.
        '''
        if len(args) < 2:
            raise UsageError, _('Not enough arguments supplied')
        propname = args[0]
        designators = args[1].split(',')
        l = []
        for designator in designators:
            # decode the node designator
            try:
                classname, nodeid = hyperdb.splitDesignator(designator)
            except hyperdb.DesignatorError, message:
                raise UsageError, message

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
                            raise UsageError, _('property %s is not of type Multilink or Link so -d flag does not apply.')%propname
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
                            raise UsageError, _('property %s is not of type Multilink or Link so -d flag does not apply.')%propname
                        propclassname = self.db.getclass(property.classname).classname
		        id = cl.get(nodeid, propname)
			for i in id:
                            print propclassname + i
                    else:
                        print cl.get(nodeid, propname)
            except IndexError:
                raise UsageError, _('no such %(classname)s node "%(nodeid)s"')%locals()
            except KeyError:
                raise UsageError, _('no such %(classname)s property '
                    '"%(propname)s"')%locals()
        if self.separator:
            print self.separator.join(l)

        return 0


    def do_set(self, args, pwre = re.compile(r'{(\w+)}(.+)')):
        '''Usage: set items property=value property=value ...
        Set the given properties of one or more items(s).

        The items are specified as a class or as a comma-separated
        list of item designators (ie "designator[,designator,...]").

        This command sets the properties to the values for all designators
        given. If the value is missing (ie. "property=") then the property is
        un-set. If the property is a multilink, you specify the linked ids
        for the multilink as comma-separated numbers (ie "1,2,3").
        '''
        if len(args) < 2:
            raise UsageError, _('Not enough arguments supplied')
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
                raise UsageError, message

        # get the props from the args
        props = self.props_from_args(args[1:])

        # now do the set for all the nodes
        for classname, itemid in designators:
            cl = self.get_class(classname)

            properties = cl.getprops()
            for key, value in props.items():
                proptype =  properties[key]
                if isinstance(proptype, hyperdb.Multilink):
                    if value is None:
                        props[key] = []
                    else:
                        props[key] = value.split(',')
                elif value is None:
                    continue
                elif isinstance(proptype, hyperdb.String):
                    continue
                elif isinstance(proptype, hyperdb.Password):
                    m = pwre.match(value)
                    if m:
                        # password is being given to us encrypted
                        p = password.Password()
                        p.scheme = m.group(1)
                        p.password = m.group(2)
                        props[key] = p
                    else:
                        props[key] = password.Password(value)
                elif isinstance(proptype, hyperdb.Date):
                    try:
                        props[key] = date.Date(value)
                    except ValueError, message:
                        raise UsageError, '"%s": %s'%(value, message)
                elif isinstance(proptype, hyperdb.Interval):
                    try:
                        props[key] = date.Interval(value)
                    except ValueError, message:
                        raise UsageError, '"%s": %s'%(value, message)
                elif isinstance(proptype, hyperdb.Link):
                    props[key] = value
                elif isinstance(proptype, hyperdb.Boolean):
                    props[key] = value.lower() in ('yes', 'true', 'on', '1')
                elif isinstance(proptype, hyperdb.Number):
                    props[key] = float(value)

            # try the set
            try:
                apply(cl.set, (itemid, ), props)
            except (TypeError, IndexError, ValueError), message:
                import traceback; traceback.print_exc()
                raise UsageError, message
        return 0

    def do_find(self, args):
        '''Usage: find classname propname=value ...
        Find the nodes of the given class with a given link property value.

        Find the nodes of the given class with a given link property value. The
        value may be either the nodeid of the linked node, or its key value.
        '''
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')
        classname = args[0]
        # get the class
        cl = self.get_class(classname)

        # handle the propname=value argument
        props = self.props_from_args(args[1:])

        # if the value isn't a number, look up the linked class to get the
        # number
        for propname, value in props.items():
            num_re = re.compile('^\d+$')
            if value == '-1':
                props[propname] = None
            elif not num_re.match(value):
                # get the property
                try:
                    property = cl.properties[propname]
                except KeyError:
                    raise UsageError, _('%(classname)s has no property '
                        '"%(propname)s"')%locals()

                # make sure it's a link
                if (not isinstance(property, hyperdb.Link) and not
                        isinstance(property, hyperdb.Multilink)):
                    raise UsageError, _('You may only "find" link properties')

                # get the linked-to class and look up the key property
                link_class = self.db.getclass(property.classname)
                try:
                    props[propname] = link_class.lookup(value)
                except TypeError:
                    raise UsageError, _('%(classname)s has no key property"')%{
                        'classname': link_class.classname}

        # now do the find 
        try:
            id = []
            designator = []
            if self.separator:
                if self.print_designator:
		    id=apply(cl.find, (), props)
		    for i in id:
		        designator.append(classname + i)
                    print self.separator.join(designator)
                else:
		    print self.separator.join(apply(cl.find, (), props))

            else:
                if self.print_designator:
		    id=apply(cl.find, (), props)
		    for i in id:
		        designator.append(classname + i)
                    print designator
		else:
		    print apply(cl.find, (), props)
        except KeyError:
            raise UsageError, _('%(classname)s has no property '
                '"%(propname)s"')%locals()
        except (ValueError, TypeError), message:
            raise UsageError, message
        return 0

    def do_specification(self, args):
        '''Usage: specification classname
        Show the properties for a classname.

        This lists the properties for a given class.
        '''
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')
        classname = args[0]
        # get the class
        cl = self.get_class(classname)

        # get the key property
        keyprop = cl.getkey()
        for key, value in cl.properties.items():
            if keyprop == key:
                print _('%(key)s: %(value)s (key property)')%locals()
            else:
                print _('%(key)s: %(value)s')%locals()

    def do_display(self, args):
        '''Usage: display designator[,designator]*
        Show the property values for the given node(s).

        This lists the properties and their associated values for the given
        node.
        '''
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')

        # decode the node designator
	for designator in args[0].split(','):
            try:
                classname, nodeid = hyperdb.splitDesignator(designator)
	    except hyperdb.DesignatorError, message:
		raise UsageError, message

	    # get the class
	    cl = self.get_class(classname)

	    # display the values
	    for key in cl.properties.keys():
		value = cl.get(nodeid, key)
		print _('%(key)s: %(value)s')%locals()

    def do_create(self, args, pwre = re.compile(r'{(\w+)}(.+)')):
        '''Usage: create classname property=value ...
        Create a new entry of a given class.

        This creates a new entry of the given class using the property
        name=value arguments provided on the command line after the "create"
        command.
        '''
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')
        from roundup import hyperdb

        classname = args[0]

        # get the class
        cl = self.get_class(classname)

        # now do a create
        props = {}
        properties = cl.getprops(protected = 0)
        if len(args) == 1:
            # ask for the properties
            for key, value in properties.items():
                if key == 'id': continue
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
        for propname, value in props.items():
            # get the property
            try:
                proptype = properties[propname]
            except KeyError:
                raise UsageError, _('%(classname)s has no property '
                    '"%(propname)s"')%locals()

            if isinstance(proptype, hyperdb.Date):
                try:
                    props[propname] = date.Date(value)
                except ValueError, message:
                    raise UsageError, _('"%(value)s": %(message)s')%locals()
            elif isinstance(proptype, hyperdb.Interval):
                try:
                    props[propname] = date.Interval(value)
                except ValueError, message:
                    raise UsageError, _('"%(value)s": %(message)s')%locals()
            elif isinstance(proptype, hyperdb.Password):
                m = pwre.match(value)
                if m:
                    # password is being given to us encrypted
                    p = password.Password()
                    p.scheme = m.group(1)
                    p.password = m.group(2)
                    props[propname] = p
                else:
                    props[propname] = password.Password(value)
            elif isinstance(proptype, hyperdb.Multilink):
                props[propname] = value.split(',')
            elif isinstance(proptype, hyperdb.Boolean):
                props[propname] = value.lower() in ('yes', 'true', 'on', '1')
            elif isinstance(proptype, hyperdb.Number):
                props[propname] = float(value)

        # check for the key property
        propname = cl.getkey()
        if propname and not props.has_key(propname):
            raise UsageError, _('you must provide the "%(propname)s" '
                'property.')%locals()

        # do the actual create
        try:
            print apply(cl.create, (), props)
        except (TypeError, IndexError, ValueError), message:
            raise UsageError, message
        return 0

    def do_list(self, args):
        '''Usage: list classname [property]
        List the instances of a class.

        Lists all instances of the given class. If the property is not
        specified, the  "label" property is used. The label property is tried
        in order: the key, "name", "title" and then the first property,
        alphabetically.

	With -c, -S or -s print a list of item id's if no property specified.
        If property specified, print list of that property for every class
	instance.
        '''
	if len(args) > 2:
	    raise UsageError, _('Too many arguments supplied')
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')
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
			raise UsageError, _('%(classname)s has no property '
			    '"%(propname)s"')%locals()
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
                    raise UsageError, _('%(classname)s has no property '
                        '"%(propname)s"')%locals()
                print _('%(nodeid)4s: %(value)s')%locals()
        return 0

    def do_table(self, args):
        '''Usage: table classname [property[,property]*]
        List the instances of a class in tabular form.

        Lists all instances of the given class. If the properties are not
        specified, all properties are displayed. By default, the column widths
        are the width of the largest value. The width may be explicitly defined
        by defining the property as "name:width". For example::
          roundup> table priority id,name:10
          Id Name
          1  fatal-bug 
          2  bug       
          3  usability 
          4  feature   

        Also to make the width of the column the width of the label,
        leave a trailing : without a width on the property. E.G.
          roundup> table priority id,name:
          Id Name
          1  fata
          2  bug       
          3  usab
          4  feat

        will result in a the 4 character wide "Name" column.
        '''
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')
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
                        raise UsageError, _('"%(spec)s" not name:width')%locals()
                else:
                    propname = spec
                if not all_props.has_key(propname):
                    raise UsageError, _('%(classname)s has no property '
                        '"%(propname)s"')%locals()
        else:
            prop_names = cl.getprops().keys()

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
        '''Usage: history designator
        Show the history entries of a designator.

        Lists the journal entries for the node identified by the designator.
        '''
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')
        try:
            classname, nodeid = hyperdb.splitDesignator(args[0])
        except hyperdb.DesignatorError, message:
            raise UsageError, message

        try:
            print self.db.getclass(classname).history(nodeid)
        except KeyError:
            raise UsageError, _('no such class "%(classname)s"')%locals()
        except IndexError:
            raise UsageError, _('no such %(classname)s node "%(nodeid)s"')%locals()
        return 0

    def do_commit(self, args):
        '''Usage: commit
        Commit all changes made to the database.

        The changes made during an interactive session are not
        automatically written to the database - they must be committed
        using this command.

        One-off commands on the command-line are automatically committed if
        they are successful.
        '''
        self.db.commit()
        return 0

    def do_rollback(self, args):
        '''Usage: rollback
        Undo all changes that are pending commit to the database.

        The changes made during an interactive session are not
        automatically written to the database - they must be committed
        manually. This command undoes all those changes, so a commit
        immediately after would make no changes to the database.
        '''
        self.db.rollback()
        return 0

    def do_retire(self, args):
        '''Usage: retire designator[,designator]*
        Retire the node specified by designator.

        This action indicates that a particular node is not to be retrieved by
        the list or find commands, and its key value may be re-used.
        '''
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')
        designators = args[0].split(',')
        for designator in designators:
            try:
                classname, nodeid = hyperdb.splitDesignator(designator)
            except hyperdb.DesignatorError, message:
                raise UsageError, message
            try:
                self.db.getclass(classname).retire(nodeid)
            except KeyError:
                raise UsageError, _('no such class "%(classname)s"')%locals()
            except IndexError:
                raise UsageError, _('no such %(classname)s node "%(nodeid)s"')%locals()
        return 0

    def do_restore(self, args):
        '''Usage: restore designator[,designator]*
        Restore the retired node specified by designator.

        The given nodes will become available for users again.
        '''
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')
        designators = args[0].split(',')
        for designator in designators:
            try:
                classname, nodeid = hyperdb.splitDesignator(designator)
            except hyperdb.DesignatorError, message:
                raise UsageError, message
            try:
                self.db.getclass(classname).restore(nodeid)
            except KeyError:
                raise UsageError, _('no such class "%(classname)s"')%locals()
            except IndexError:
                raise UsageError, _('no such %(classname)s node "%(nodeid)s"')%locals()
        return 0

    def do_export(self, args):
        '''Usage: export [class[,class]] export_dir
        Export the database to colon-separated-value files.

        This action exports the current data from the database into
        colon-separated-value files that are placed in the nominated
        destination directory. The journals are not exported.
        '''
        # we need the CSV module
        if csv is None:
            raise UsageError, \
                _('Sorry, you need the csv module to use this function.\n'
                'Get it from: http://www.object-craft.com.au/projects/csv/')

        # grab the directory to export to
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')
        dir = args[-1]

        # get the list of classes to export
        if len(args) == 2:
            classes = args[0].split(',')
        else:
            classes = self.db.classes.keys()

        # use the csv parser if we can - it's faster
        p = csv.parser(field_sep=':')

        # do all the classes specified
        for classname in classes:
            cl = self.get_class(classname)
            f = open(os.path.join(dir, classname+'.csv'), 'w')
            properties = cl.getprops()
            propnames = properties.keys()
            propnames.sort()
            l = propnames[:]
            l.append('is retired')
            print >> f, p.join(l)

            # all nodes for this class (not using list() 'cos it doesn't
            # include retired nodes)

            for nodeid in self.db.getclass(classname).getnodeids():
                # get the regular props
                print >>f, p.join(cl.export_list(propnames, nodeid))

            # close this file
            f.close()
        return 0

    def do_import(self, args):
        '''Usage: import import_dir
        Import a database from the directory containing CSV files, one per
        class to import.

        The files must define the same properties as the class (including having
        a "header" line with those property names.)

        The imported nodes will have the same nodeid as defined in the
        import file, thus replacing any existing content.

        The new nodes are added to the existing database - if you want to
        create a new database using the imported data, then create a new
        database (or, tediously, retire all the old data.)
        '''
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')
        if csv is None:
            raise UsageError, \
                _('Sorry, you need the csv module to use this function.\n'
                'Get it from: http://www.object-craft.com.au/projects/csv/')

        from roundup import hyperdb

        for file in os.listdir(args[0]):
            # we only care about CSV files
            if not file.endswith('.csv'):
                continue

            f = open(os.path.join(args[0], file))

            # get the classname
            classname = os.path.splitext(file)[0]

            # ensure that the properties and the CSV file headings match
            cl = self.get_class(classname)
            p = csv.parser(field_sep=':')
            file_props = p.parse(f.readline())

# XXX we don't _really_ need to do this...
#            properties = cl.getprops()
#            propnames = properties.keys()
#            propnames.sort()
#            m = file_props[:]
#            m.sort()
#            if m != propnames:
#                raise UsageError, _('Import file doesn\'t define the same '
#                    'properties as "%(arg0)s".')%{'arg0': args[0]}

            # loop through the file and create a node for each entry
            maxid = 1
            while 1:
                line = f.readline()
                if not line: break

                # parse lines until we get a complete entry
                while 1:
                    l = p.parse(line)
                    if l: break
                    line = f.readline()
                    if not line:
                        raise ValueError, "Unexpected EOF during CSV parse"

                # do the import and figure the current highest nodeid
                maxid = max(maxid, int(cl.import_list(file_props, l)))

            print 'setting', classname, maxid+1
            self.db.setid(classname, str(maxid+1))
        return 0

    def do_pack(self, args):
        '''Usage: pack period | date

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
    
        '''
        if len(args) <> 1:
            raise UsageError, _('Not enough arguments supplied')
        
        # are we dealing with a period or a date
        value = args[0]
        date_re = re.compile(r'''
              (?P<date>\d\d\d\d-\d\d?-\d\d?)? # yyyy-mm-dd
              (?P<period>(\d+y\s*)?(\d+m\s*)?(\d+d\s*)?)?
              ''', re.VERBOSE)
        m = date_re.match(value)
        if not m:
            raise ValueError, _('Invalid format')
        m = m.groupdict()
        if m['period']:
            pack_before = date.Date(". - %s"%value)
        elif m['date']:
            pack_before = date.Date(value)
        self.db.pack(pack_before)
        return 0

    def do_reindex(self, args):
        '''Usage: reindex
        Re-generate a tracker's search indexes.

        This will re-generate the search indexes for a tracker. This will
        typically happen automatically.
        '''
        self.db.indexer.force_reindex()
        self.db.reindex()
        return 0

    def do_security(self, args):
        '''Usage: security [Role name]
        Display the Permissions available to one or all Roles.
        '''
        if len(args) == 1:
            role = args[0]
            try:
                roles = [(args[0], self.db.security.role[args[0]])]
            except KeyError:
                print _('No such Role "%(role)s"')%locals()
                return 1
        else:
            roles = self.db.security.role.items()
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
                if permission.klass:
                    print _(' %(description)s (%(name)s for "%(klass)s" '
                        'only)')%permission.__dict__
                else:
                    print _(' %(description)s (%(name)s)')%permission.__dict__
        return 0

    def run_command(self, args):
        '''Run a single command
        '''
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
        '''Run in an interactive mode
        '''
        print _('Roundup %s ready for input.'%roundup_version)
        print _('Type "help" for help.')
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
        if self.db and self.db.transactions:
            commit = raw_input(_('There are unsaved changes. Commit them (y/N)? '))
            if commit and commit[0].lower() == 'y':
                self.db.commit()
        return 0

    def main(self):
        try:
            opts, args = getopt.getopt(sys.argv[1:], 'i:u:hcdsS:')
        except getopt.GetoptError, e:
            self.usage(str(e))
            return 1

        # handle command-line args
        self.tracker_home = os.environ.get('TRACKER_HOME', '')
        # TODO: reinstate the user/password stuff (-u arg too)
        name = password = ''
        if os.environ.has_key('ROUNDUP_LOGIN'):
            l = os.environ['ROUNDUP_LOGIN'].split(':')
            name = l[0]
            if len(l) > 1:
                password = l[1]
        self.separator = None
        self.print_designator = 0
        for opt, arg in opts:
            if opt == '-h':
                self.usage()
                return 0
            if opt == '-i':
                self.tracker_home = arg
            if opt == '-c':
	        if self.separator != None:
	            self.usage('Only one of -c, -S and -s may be specified')
		    return 1
                self.separator = ','
            if opt == '-S':
	        if self.separator != None:
	            self.usage('Only one of -c, -S and -s may be specified')
		    return 1
                self.separator = arg
	    if opt == '-s':
	        if self.separator != None:
	            self.usage('Only one of -c, -S and -s may be specified')
		    return 1
                self.separator = ' '
            if opt == '-d':
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


def listTemplates(dir):
    ''' List all the Roundup template directories in a given directory.

        Find all the dirs that contain a TEMPLATE-INFO.txt and parse it.

        Return a list of dicts of info about the templates.
    '''
    ret = {}
    for idir in os.listdir(dir):
        idir = os.path.join(dir, idir)
        ti = loadTemplate(idir)
        if ti:
            ret[ti['name']] = ti
    return ret

def loadTemplate(dir):
    ''' Attempt to load a Roundup template from the indicated directory.

        Return None if there's no template, otherwise a template info
        dictionary.
    '''
    ti = os.path.join(dir, 'TEMPLATE-INFO.txt')
    if not os.path.exists(ti):
        return None

    # load up the template's information
    m = rfc822.Message(open(ti))
    ti = {}
    ti['name'] = m['name']
    ti['description'] = m['description']
    ti['intended-for'] = m['intended-for']
    ti['path'] = dir
    return ti

if __name__ == '__main__':
    tool = AdminTool()
    sys.exit(tool.main())

# vim: set filetype=python ts=4 sw=4 et si
