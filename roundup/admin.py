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
# $Id: admin.py,v 1.3 2002-01-08 05:26:32 rochecompaan Exp $

import sys, os, getpass, getopt, re, UserDict, shlex
try:
    import csv
except ImportError:
    csv = None
from roundup import date, hyperdb, roundupdb, init, password, token
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

    def __init__(self):
        self.commands = CommandDict()
        for k in AdminTool.__dict__.keys():
            if k[:3] == 'do_':
                self.commands[k[3:]] = getattr(self, k)
        self.help = {}
        for k in AdminTool.__dict__.keys():
            if k[:5] == 'help_':
                self.help[k[5:]] = getattr(self, k)
        self.instance_home = ''
        self.db = None

    def get_class(self, classname):
        '''Get the class - raise an exception if it doesn't exist.
        '''
        try:
            return self.db.getclass(classname)
        except KeyError:
            raise UsageError, _('no such class "%(classname)s"')%locals()

    def props_from_args(self, args, klass=None):
        props = {}
        for arg in args:
            if arg.find('=') == -1:
                raise UsageError, _('argument "%(arg)s" not propname=value')%locals()
            try:
                key, value = arg.split('=')
            except ValueError:
                raise UsageError, _('argument "%(arg)s" not propname=value')%locals()
            props[key] = value
        return props

    def usage(self, message=''):
        if message:
            message = _('Problem: %(message)s)\n\n')%locals()
        print _('''%(message)sUsage: roundup-admin [-i instance home] [-u login] [-c] <command> <arguments>

Help:
 roundup-admin -h
 roundup-admin help                       -- this help
 roundup-admin help <command>             -- command-specific help
 roundup-admin help all                   -- all available help
Options:
 -i instance home  -- specify the issue tracker "home directory" to administer
 -u                -- the user[:password] to use for commands
 -c                -- when outputting lists of data, just comma-separate them''')%locals()
        self.help_commands()

    def help_commands(self):
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
All commands (except help) require an instance specifier. This is just the path
to the roundup instance you're working with. A roundup instance is where 
roundup keeps the database and configuration file that defines an issue
tracker. It may be thought of as the issue tracker's "home directory". It may
be specified in the environment variable ROUNDUP_INSTANCE or on the command
line as "-i instance".

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
        topic = args[0]

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

    def help_initopts(self):
        import roundup.templates
        templates = roundup.templates.listTemplates()
        print _('Templates:'), ', '.join(templates)
        import roundup.backends
        backends = roundup.backends.__all__
        print _('Back ends:'), ', '.join(backends)


    def do_initialise(self, instance_home, args):
        '''Usage: initialise [template [backend [admin password]]]
        Initialise a new Roundup instance.

        The command will prompt for the instance home directory (if not supplied
        through INSTANCE_HOME or the -i option). The template, backend and admin
        password may be specified on the command-line as arguments, in that
        order.

        See also initopts help.
        '''
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')
        # select template
        import roundup.templates
        templates = roundup.templates.listTemplates()
        template = len(args) > 1 and args[1] or ''
        if template not in templates:
            print _('Templates:'), ', '.join(templates)
        while template not in templates:
            template = raw_input(_('Select template [classic]: ')).strip()
            if not template:
                template = 'classic'

        import roundup.backends
        backends = roundup.backends.__all__
        backend = len(args) > 2 and args[2] or ''
        if backend not in backends:
            print _('Back ends:'), ', '.join(backends)
        while backend not in backends:
            backend = raw_input(_('Select backend [anydbm]: ')).strip()
            if not backend:
                backend = 'anydbm'
        if len(args) > 3:
            adminpw = confirm = args[3]
        else:
            adminpw = ''
            confirm = 'x'
        while adminpw != confirm:
            adminpw = getpass.getpass(_('Admin Password: '))
            confirm = getpass.getpass(_('       Confirm: '))
        init.init(instance_home, template, backend, adminpw)
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
                classname, nodeid = roundupdb.splitDesignator(designator)
            except roundupdb.DesignatorError, message:
                raise UsageError, message

            # get the class
            cl = self.get_class(classname)
            try:
                if self.comma_sep:
                    l.append(cl.get(nodeid, propname))
                else:
                    print cl.get(nodeid, propname)
            except IndexError:
                raise UsageError, _('no such %(classname)s node "%(nodeid)s"')%locals()
            except KeyError:
                raise UsageError, _('no such %(classname)s property '
                    '"%(propname)s"')%locals()
        if self.comma_sep:
            print ','.join(l)
        return 0


    def do_set(self, args):
        '''Usage: set designator[,designator]* propname=value ...
        Set the given property of one or more designator(s).

        Sets the property to the value for all designators given.
        '''
        if len(args) < 2:
            raise UsageError, _('Not enough arguments supplied')
        from roundup import hyperdb

        designators = args[0].split(',')

        # get the props from the args
        props = self.props_from_args(args[1:])

        # now do the set for all the nodes
        for designator in designators:
            # decode the node designator
            try:
                classname, nodeid = roundupdb.splitDesignator(designator)
            except roundupdb.DesignatorError, message:
                raise UsageError, message

            # get the class
            cl = self.get_class(classname)

            properties = cl.getprops()
            for key, value in props.items():
                proptype =  properties[key]
                if isinstance(proptype, hyperdb.String):
                    continue
                elif isinstance(proptype, hyperdb.Password):
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
                elif isinstance(proptype, hyperdb.Multilink):
                    props[key] = value.split(',')

            # try the set
            try:
                apply(cl.set, (nodeid, ), props)
            except (TypeError, IndexError, ValueError), message:
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
            if not num_re.match(value):
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
                except KeyError:
                    raise UsageError, _('%(classname)s has no entry "%(propname)s"')%{
                        'classname': link_class.classname, 'propname': propname}

        # now do the find 
        try:
            if self.comma_sep:
                print ','.join(apply(cl.find, (), props))
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
        '''Usage: display designator
        Show the property values for the given node.

        This lists the properties and their associated values for the given
        node.
        '''
        if len(args) < 1:
            raise UsageError, _('Not enough arguments supplied')

        # decode the node designator
        try:
            classname, nodeid = roundupdb.splitDesignator(args[0])
        except roundupdb.DesignatorError, message:
            raise UsageError, message

        # get the class
        cl = self.get_class(classname)

        # display the values
        for key in cl.properties.keys():
            value = cl.get(nodeid, key)
            print _('%(key)s: %(value)s')%locals()

    def do_create(self, args):
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
        for propname in props.keys():
            # get the property
            try:
                proptype = properties[propname]
            except KeyError:
                raise UsageError, _('%(classname)s has no property '
                    '"%(propname)s"')%locals()

            if isinstance(proptype, hyperdb.Date):
                try:
                    props[key] = date.Date(value)
                except ValueError, message:
                    raise UsageError, _('"%(value)s": %(message)s')%locals()
            elif isinstance(proptype, hyperdb.Interval):
                try:
                    props[key] = date.Interval(value)
                except ValueError, message:
                    raise UsageError, _('"%(value)s": %(message)s')%locals()
            elif isinstance(proptype, hyperdb.Password):
                props[key] = password.Password(value)
            elif isinstance(proptype, hyperdb.Multilink):
                props[key] = value.split(',')

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
        '''
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

        if self.comma_sep:
            print ','.join(cl.list())
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
        are the width of the property names. The width may be explicitly defined
        by defining the property as "name:width". For example::
          roundup> table priority id,name:10
          Id Name
          1  fatal-bug 
          2  bug       
          3  usability 
          4  feature   
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
                props.append((name, int(width)))
            else:
                props.append((spec, len(spec)))

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
            classname, nodeid = roundupdb.splitDesignator(args[0])
        except roundupdb.DesignatorError, message:
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
                classname, nodeid = roundupdb.splitDesignator(designator)
            except roundupdb.DesignatorError, message:
                raise UsageError, message
            try:
                self.db.getclass(classname).retire(nodeid)
            except KeyError:
                raise UsageError, _('no such class "%(classname)s"')%locals()
            except IndexError:
                raise UsageError, _('no such %(classname)s node "%(nodeid)s"')%locals()
        return 0

    def do_export(self, args):
        '''Usage: export class[,class] destination_dir
        Export the database to tab-separated-value files.

        This action exports the current data from the database into
        tab-separated-value files that are placed in the nominated destination
        directory. The journals are not exported.
        '''
        if len(args) < 2:
            raise UsageError, _('Not enough arguments supplied')
        classes = args[0].split(',')
        dir = args[1]

        # use the csv parser if we can - it's faster
        if csv is not None:
            p = csv.parser(field_sep=':')

        # do all the classes specified
        for classname in classes:
            cl = self.get_class(classname)
            f = open(os.path.join(dir, classname+'.csv'), 'w')
            f.write(':'.join(cl.properties.keys()) + '\n')

            # all nodes for this class
            properties = cl.properties.items()
            for nodeid in cl.list():
                l = []
                for prop, proptype in properties:
                    value = cl.get(nodeid, prop)
                    # convert data where needed
                    if isinstance(proptype, hyperdb.Date):
                        value = value.get_tuple()
                    elif isinstance(proptype, hyperdb.Interval):
                        value = value.get_tuple()
                    elif isinstance(proptype, hyperdb.Password):
                        value = str(value)
                    l.append(repr(value))

                # now write
                if csv is not None:
                   f.write(p.join(l) + '\n')
                else:
                   # escape the individual entries to they're valid CSV
                   m = []
                   for entry in l:
                      if '"' in entry:
                          entry = '""'.join(entry.split('"'))
                      if ':' in entry:
                          entry = '"%s"'%entry
                      m.append(entry)
                   f.write(':'.join(m) + '\n')
        return 0

    def do_import(self, args):
        '''Usage: import class file
        Import the contents of the tab-separated-value file.

        The file must define the same properties as the class (including having
        a "header" line with those property names.) The new nodes are added to
        the existing database - if you want to create a new database using the
        imported data, then create a new database (or, tediously, retire all
        the old data.)
        '''
        if len(args) < 2:
            raise UsageError, _('Not enough arguments supplied')
        if csv is None:
            raise UsageError, \
                _('Sorry, you need the csv module to use this function.\n'
                'Get it from: http://www.object-craft.com.au/projects/csv/')

        from roundup import hyperdb

        # ensure that the properties and the CSV file headings match
        classname = args[0]
        cl = self.get_class(classname)
        f = open(args[1])
        p = csv.parser(field_sep=':')
        file_props = p.parse(f.readline())
        props = cl.properties.keys()
        m = file_props[:]
        m.sort()
        props.sort()
        if m != props:
            raise UsageError, _('Import file doesn\'t define the same '
                'properties as "%(arg0)s".')%{'arg0': args[0]}

        # loop through the file and create a node for each entry
        n = range(len(props))
        while 1:
            line = f.readline()
            if not line: break

            # parse lines until we get a complete entry
            while 1:
                l = p.parse(line)
                if l: break

            # make the new node's property map
            d = {}
            for i in n:
                # Use eval to reverse the repr() used to output the CSV
                value = eval(l[i])
                # Figure the property for this column
                key = file_props[i]
                proptype = cl.properties[key]
                # Convert for property type
                if isinstance(proptype, hyperdb.Date):
                    value = date.Date(value)
                elif isinstance(proptype, hyperdb.Interval):
                    value = date.Interval(value)
                elif isinstance(proptype, hyperdb.Password):
                    pwd = password.Password()
                    pwd.unpack(value)
                    value = pwd
                if value is not None:
                    d[key] = value

            # and create the new node
            apply(cl.create, (), d)
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

        # make sure we have an instance_home
        while not self.instance_home:
            self.instance_home = raw_input(_('Enter instance home: ')).strip()

        # before we open the db, we may be doing an init
        if command == 'initialise':
            return self.do_initialise(self.instance_home, args)

        # get the instance
        try:
            instance = roundup.instance.open(self.instance_home)
        except ValueError, message:
            self.instance_home = ''
            print _("Couldn't open instance: %(message)s")%locals()
            return 1

        # only open the database once!
        if not self.db:
            self.db = instance.open('admin')

        # do the command
        ret = 0
        try:
            ret = function(args[1:])
        except UsageError, message:
            print _('Error: %(message)s')%locals()
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
        print _('Roundup {version} ready for input.')
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
            opts, args = getopt.getopt(sys.argv[1:], 'i:u:hc')
        except getopt.GetoptError, e:
            self.usage(str(e))
            return 1

        # handle command-line args
        self.instance_home = os.environ.get('ROUNDUP_INSTANCE', '')
        name = password = ''
        if os.environ.has_key('ROUNDUP_LOGIN'):
            l = os.environ['ROUNDUP_LOGIN'].split(':')
            name = l[0]
            if len(l) > 1:
                password = l[1]
        self.comma_sep = 0
        for opt, arg in opts:
            if opt == '-h':
                self.usage()
                return 0
            if opt == '-i':
                self.instance_home = arg
            if opt == '-c':
                self.comma_sep = 1

        # if no command - go interactive
        ret = 0
        if not args:
            self.interactive()
        else:
            ret = self.run_command(args)
            if self.db: self.db.commit()
        return ret


if __name__ == '__main__':
    tool = AdminTool()
    sys.exit(tool.main())

#
# $Log: not supported by cvs2svn $
# Revision 1.2  2002/01/07 10:41:44  richard
# #500140 ] AdminTool.get_class() returns nothing
#
# Revision 1.1  2002/01/05 02:11:22  richard
# I18N'ed roundup admin - and split the code off into a module so it can be used
# elsewhere.
# Big issue with this is the doc strings - that's the help. We're probably going to
# have to switch to not use docstrings, which will suck a little :(
#
#
#
# vim: set filetype=python ts=4 sw=4 et si
