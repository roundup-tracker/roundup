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

"""Tracker handling (open tracker).

Backwards compatibility for the old-style "imported" trackers.
"""
__docformat__ = 'restructuredtext'

import os
import sys
from roundup import configuration, mailgw
from roundup import hyperdb, backends, actions
from roundup.cgi import client, templating
from roundup.cgi import actions as cgi_actions

class Vars:
    def __init__(self, vars):
        self.__dict__.update(vars)

class Tracker:
    def __init__(self, tracker_home, optimize=0):
        """New-style tracker instance constructor

        Parameters:
            tracker_home:
                tracker home directory
            optimize:
                if set, precompile html templates

        """
        self.tracker_home = tracker_home
        self.optimize = optimize
        # if set, call schema_hook after executing schema.py will get
        # same variables (in particular db) as schema.py main purpose is
        # for regression tests
        self.schema_hook = None
        self.config = configuration.CoreConfig(tracker_home)
        self.actions = {}
        self.cgi_actions = {}
        self.templating_utils = {}
        self.load_interfaces()
        self.templates = templating.Templates(self.config["TEMPLATES"])
        self.backend = backends.get_backend(self.get_backend_name())
        if self.optimize:
            libdir = os.path.join(self.tracker_home, 'lib')
            if os.path.isdir(libdir):
                sys.path.insert(1, libdir)
            self.templates.precompileTemplates()
            # initialize tracker extensions
            for extension in self.get_extensions('extensions'):
                extension(self)
            # load database schema
            schemafilename = os.path.join(self.tracker_home, 'schema.py')
            # Note: can't use built-in open()
            #   because of the global function with the same name
            schemafile = file(schemafilename, 'rt')
            self.schema = compile(schemafile.read(), schemafilename, 'exec')
            schemafile.close()
            # load database detectors
            self.detectors = self.get_extensions('detectors')
            # db_open is set to True after first open()
            self.db_open = 0
            if libdir in sys.path:
                sys.path.remove(libdir)

    def get_backend_name(self):
        o = __builtins__['open']
        f = o(os.path.join(self.tracker_home, 'db', 'backend_name'))
        name = f.readline().strip()
        f.close()
        return name

    def open(self, name=None):
        # load the database schema
        # we cannot skip this part even if self.optimize is set
        # because the schema has security settings that must be
        # applied to each database instance
        backend = self.backend
        vars = {
            'Class': backend.Class,
            'FileClass': backend.FileClass,
            'IssueClass': backend.IssueClass,
            'String': hyperdb.String,
            'Password': hyperdb.Password,
            'Date': hyperdb.Date,
            'Link': hyperdb.Link,
            'Multilink': hyperdb.Multilink,
            'Interval': hyperdb.Interval,
            'Boolean': hyperdb.Boolean,
            'Number': hyperdb.Number,
            'db': backend.Database(self.config, name)
        }

        if self.optimize:
            # execute preloaded schema object
            exec(self.schema, vars)
            if callable (self.schema_hook):
                self.schema_hook(**vars)
            # use preloaded detectors
            detectors = self.detectors
        else:
            libdir = os.path.join(self.tracker_home, 'lib')
            if os.path.isdir(libdir):
                sys.path.insert(1, libdir)
            # execute the schema file
            self._load_python('schema.py', vars)
            if callable (self.schema_hook):
                self.schema_hook(**vars)
            # reload extensions and detectors
            for extension in self.get_extensions('extensions'):
                extension(self)
            detectors = self.get_extensions('detectors')
            if libdir in sys.path:
                sys.path.remove(libdir)
        db = vars['db']
        # apply the detectors
        for detector in detectors:
            detector(db)
        # if we are running in debug mode
        # or this is the first time the database is opened,
        # do database upgrade checks
        if not (self.optimize and self.db_open):
            # As a consistency check, ensure that every link property is
            # pointing at a defined class.  Otherwise, the schema is
            # internally inconsistent.  This is an important safety
            # measure as it protects against an accidental schema change
            # dropping a table while there are still links to the table;
            # once the table has been dropped, there is no way to get it
            # back, so it is important to drop it only if we are as sure
            # as possible that it is no longer needed.
            classes = db.getclasses()
            for classname in classes:
                cl = db.getclass(classname)
                for propname, prop in cl.getprops().iteritems():
                    if not isinstance(prop, (hyperdb.Link,
                                             hyperdb.Multilink)):
                        continue
                    linkto = prop.classname
                    if linkto not in classes:
                        raise ValueError, \
                            ("property %s.%s links to non-existent class %s"
                             % (classname, propname, linkto))

            db.post_init()
            self.db_open = 1
        return db

    def load_interfaces(self):
        """load interfaces.py (if any), initialize Client and MailGW attrs"""
        vars = {}
        if os.path.isfile(os.path.join(self.tracker_home, 'interfaces.py')):
            self._load_python('interfaces.py', vars)
        self.Client = vars.get('Client', client.Client)
        self.MailGW = vars.get('MailGW', mailgw.MailGW)

    def get_extensions(self, dirname):
        """Load python extensions

        Parameters:
            dirname:
                extension directory name relative to tracker home

        Return value:
            list of init() functions for each extension

        """
        extensions = []
        dirpath = os.path.join(self.tracker_home, dirname)
        if os.path.isdir(dirpath):
            sys.path.insert(1, dirpath)
            for name in os.listdir(dirpath):
                if not name.endswith('.py'):
                    continue
                vars = {}
                self._load_python(os.path.join(dirname, name), vars)
                extensions.append(vars['init'])
            sys.path.remove(dirpath)
        return extensions

    def init(self, adminpw):
        db = self.open('admin')
        self._load_python('initial_data.py', {'db': db, 'adminpw': adminpw,
            'admin_email': self.config['ADMIN_EMAIL']})
        db.commit()
        db.close()

    def exists(self):
        return self.backend.db_exists(self.config)

    def nuke(self):
        self.backend.db_nuke(self.config)

    def _load_python(self, file, vars):
        file = os.path.join(self.tracker_home, file)
        execfile(file, vars)
        return vars

    def registerAction(self, name, action):

        # The logic here is this:
        # * if `action` derives from actions.Action,
        #   it is executable as a generic action.
        # * if, moreover, it also derives from cgi.actions.Bridge,
        #   it may in addition be called via CGI
        # * in all other cases we register it as a CGI action, without
        #   any check (for backward compatibility).
        if issubclass(action, actions.Action):
            self.actions[name] = action
            if issubclass(action, cgi_actions.Bridge):
                self.cgi_actions[name] = action
        else:
            self.cgi_actions[name] = action

    def registerUtil(self, name, function):
        self.templating_utils[name] = function

class TrackerError(Exception):
    pass


class OldStyleTrackers:
    def __init__(self):
        self.number = 0
        self.trackers = {}

    def open(self, tracker_home, optimize=0):
        """Open the tracker.

        Parameters:
            tracker_home:
                tracker home directory
            optimize:
                if set, precompile html templates

        Raise ValueError if the tracker home doesn't exist.

        """
        import imp
        # sanity check existence of tracker home
        if not os.path.exists(tracker_home):
            raise ValueError, 'no such directory: "%s"'%tracker_home

        # sanity check tracker home contents
        for reqd in 'config dbinit select_db interfaces'.split():
            if not os.path.exists(os.path.join(tracker_home, '%s.py'%reqd)):
                raise TrackerError, 'File "%s.py" missing from tracker '\
                    'home "%s"'%(reqd, tracker_home)

        if self.trackers.has_key(tracker_home):
            return imp.load_package(self.trackers[tracker_home],
                tracker_home)
        # register all available backend modules
        backends.list_backends()
        self.number = self.number + 1
        modname = '_roundup_tracker_%s'%self.number
        self.trackers[tracker_home] = modname

        # load the tracker
        tracker = imp.load_package(modname, tracker_home)

        # ensure the tracker has all the required bits
        for required in 'open init Client MailGW'.split():
            if not hasattr(tracker, required):
                raise TrackerError, \
                    'Required tracker attribute "%s" missing'%required

        # load and apply the config
        tracker.config = configuration.CoreConfig(tracker_home)
        tracker.dbinit.config = tracker.config

        tracker.optimize = optimize
        tracker.templates = templating.Templates(tracker.config["TEMPLATES"])
        if optimize:
            tracker.templates.precompileTemplates()

        return tracker

OldStyleTrackers = OldStyleTrackers()
def open(tracker_home, optimize=0):
    if os.path.exists(os.path.join(tracker_home, 'dbinit.py')):
        # user should upgrade...
        return OldStyleTrackers.open(tracker_home, optimize=optimize)

    return Tracker(tracker_home, optimize=optimize)

# vim: set filetype=python sts=4 sw=4 et si :
