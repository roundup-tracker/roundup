#! /usr/bin/python

import sys
if int(sys.version[0]) < 2:
    print 'Roundup requires python 2.0 or later.'
    sys.exit(1)

import string, os, getpass
import config, date, roundupdb

def determineLogin(argv):
    n = 2
    name = password = ''
    if sys.argv[2] == '-user':
        l = sys.argv[3].split(':')
        name = l[0]
        if len(l) > 1:
            password = l[1]
        n = 4
    elif os.environ.has_key('ROUNDUP_LOGIN'):
        l = os.environ['ROUNDUP_LOGIN'].split(':')
        name = l[0]
        if len(l) > 1:
            password = l[1]
    while not name:
        name = raw_input('Login name: ')
    while not password:
        password = getpass.getpass('  password: ')
    return n, roundupdb.openDB(config.DATABASE, name, password)

def usage():
    print '''Usage:

 roundup init
 roundup spec classname
 roundup create [-user login] classanme propname=value ...
 roundup list [-list] classname
 roundup history [-list] designator
 roundup get [-list] designator[,designator,...] propname
 roundup set [-user login] designator[,designator,...] propname=value ...
 roundup find [-list] classname propname=value ...
 roundup retire designator[,designator,...]

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

When multiple nodes are specified to the roundup get or roundup set
commands, the specified properties are retrieved or set on all the listed
nodes. 

When multiple results are returned by the roundup get or roundup find
commands, they are printed one per line (default) or joined by commas (with
the -list) option. 

Where the command changes data, a login name/password is required. The
login may be specified as either "name" or "name:password".
 . ROUNDUP_LOGIN environment variable
 . the -user command-line option
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
'''

def main():

    if len(sys.argv) == 1:
        usage()
        return 1

    command = sys.argv[1]
    if command == 'init':
        password = ''
        confirm = 'x'
        while password != confirm:
            password = getpass.getpass('Admin Password:')
            confirm = getpass.getpass('       Confirm:')
        roundupdb.initDB(config.DATABASE, password)
        return 0

    if command == 'get':
        db = roundupdb.openDB(config.DATABASE)
        designators = string.split(sys.argv[2], ',')
        propname = sys.argv[3]
        for designator in designators:
            classname, nodeid = roundupdb.splitDesignator(designator)
            print db.getclass(classname).get(nodeid, propname)

    elif command == 'set':
        n, db = determineLogin(sys.argv)
        designators = string.split(sys.argv[n], ',')
        props = {}
        for prop in sys.argv[n+1:]:
            key, value = prop.split('=')
            props[key] = value
        for designator in designators:
            classname, nodeid = roundupdb.splitDesignator(designator)
            cl = db.getclass(classname)
            properties = cl.getprops()
            for key, value in props.items():
                type =  properties[key]
                if type.isStringType:
                    continue
                elif type.isDateType:
                    props[key] = date.Date(value)
                elif type.isIntervalType:
                    props[key] = date.Interval(value)
                elif type.isLinkType:
                    props[key] = value
                elif type.isMultilinkType:
                    props[key] = value.split(',')
            apply(cl.set, (nodeid, ), props)

    elif command == 'find':
        db = roundupdb.openDB(config.DATABASE)
        classname = sys.argv[2]
        cl = db.getclass(classname)

        # look up the linked-to class and get the nodeid that has the value
        propname, value = sys.argv[3:].split('=')
        propcl = cl[propname].classname
        nodeid = propcl.lookup(value)

        # now do the find
        print cl.find(propname, nodeid)

    elif command == 'spec':
        db = roundupdb.openDB(config.DATABASE)
        classname = sys.argv[2]
        cl = db.getclass(classname)
        for key, value in cl.properties.items():
            print '%s: %s'%(key, value)

    elif command == 'create':
        n, db = determineLogin(sys.argv)
        classname = sys.argv[n]
        cl = db.getclass(classname)
        props = {}
        properties = cl.getprops()
        for prop in sys.argv[n+1:]:
            key, value = prop.split('=')
            type =  properties[key]
            if type.isStringType:
                props[key] = value 
            elif type.isDateType:
                props[key] = date.Date(value)
            elif type.isIntervalType:
                props[key] = date.Interval(value)
            elif type.isLinkType:
                props[key] = value
            elif type.isMultilinkType:
                props[key] = value.split(',')
        print apply(cl.create, (), props)

    elif command == 'list':
        db = roundupdb.openDB(config.DATABASE)
        classname = sys.argv[2]
        cl = db.getclass(classname)
        key = cl.getkey() or cl.properties.keys()[0]
        for nodeid in cl.list():
            value = cl.get(nodeid, key)
            print "%4s: %s"%(nodeid, value)

    elif command == 'history':
        db = roundupdb.openDB(config.DATABASE)
        classname, nodeid = roundupdb.splitDesignator(sys.argv[2])
        print db.getclass(classname).history(nodeid)

    elif command == 'retire':
        n, db = determineLogin(sys.argv)
        designators = string.split(sys.argv[2], ',')
        for designator in designators:
            classname, nodeid = roundupdb.splitDesignator(designator)
            db.getclass(classname).retire(nodeid)

    else:
        usage()
        return 1

    db.close()
    return 0

if __name__ == '__main__':
    sys.exit(main())

