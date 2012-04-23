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

"""Top-level tracker interface.

Open a tracker with:

    >>> from roundup import instance
    >>> db = instance.open('path to tracker home')

The "db" handle you get back is the tracker's hyperdb which has the interface
described in `roundup.hyperdb.Database`.
"""
__docformat__ = 'restructuredtext'

import os
import sys
from roundup import configuration, mailgw
from roundup import hyperdb, backends, actions
from roundup.cgi import client, templating
from roundup.cgi import actions as cgi_actions

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

        libdir = os.path.join(self.tracker_home, 'lib')
        self.libdir = os.path.isdir(libdir) and libdir or ''

        self.load_interfaces()
        self.templates = templating.get_templates(self.config["TEMPLATES"],
            self.config["TEMPLATE_ENGINE"])
        self.backend = backends.get_backend(self.get_backend_name())

        if self.optimize:
            self.templates.precompileTemplates()
            # initialize tracker extensions
            for extension in self.get_extensions('extensions'):
                extension(self)
            # load database schema
            self.schema = self._compile('schema.py')
            # load database detectors
            self.detectors = self.get_extensions('detectors')
            # db_open is set to True after first open()
            self.db_open = 0

    def get_backend_name(self):
        f = file(os.path.join(self.config.DATABASE, 'backend_name'))
        name = f.readline().strip()
        f.close()
        return name

    def open(self, name=None):
        # load the database schema
        # we cannot skip this part even if self.optimize is set
        # because the schema has security settings that must be
        # applied to each database instance
        backend = self.backend
        env = {
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
            self._exec(self.schema, env)
            if callable (self.schema_hook):
                self.schema_hook(**env)
            # use preloaded detectors
            detectors = self.detectors
        else:
            # execute the schema file
            self._execfile('schema.py', env)
            if callable (self.schema_hook):
                self.schema_hook(**env)
            # reload extensions and detectors
            for extension in self.get_extensions('extensions'):
                extension(self)
            detectors = self.get_extensions('detectors')
        db = env['db']
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
        env = {}
        if os.path.isfile(os.path.join(self.tracker_home, 'interfaces.py')):
            self._execfile('interfaces.py', env)
        self.Client = env.get('Client', client.Client)
        self.MailGW = env.get('MailGW', mailgw.MailGW)
        self.TemplatingUtils = env.get('TemplatingUtils', templating.TemplatingUtils)

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
                env = {}
                self._execfile(os.path.join(dirname, name), env)
                extensions.append(env['init'])
            sys.path.remove(dirpath)
        return extensions

    def init(self, adminpw):
        db = self.open('admin')
        self._execfile('initial_data.py', {'db': db, 'adminpw': adminpw,
            'admin_email': self.config['ADMIN_EMAIL']})
        db.commit()
        db.close()

    def exists(self):
        return self.backend.db_exists(self.config)

    def nuke(self):
        self.backend.db_nuke(self.config)

    def _compile(self, fname):
        fname = os.path.join(self.tracker_home, fname)
        return compile(file(fname).read(), fname, 'exec')

    def _exec(self, obj, env):
        if self.libdir:
            sys.path.insert(1, self.libdir)
        exec(obj, env)
        if self.libdir:
            sys.path.remove(self.libdir)
        return env

    def _execfile(self, fname, env):
        self._exec(self._compile(fname), env)

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
