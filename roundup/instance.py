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
# $Id: instance.py,v 1.17 2004-07-27 00:57:18 richard Exp $

'''Tracker handling (open tracker).

Backwards compatibility for the old-style "imported" trackers.
'''
__docformat__ = 'restructuredtext'

import os
from roundup import configuration, rlog
from roundup import hyperdb, backends

class Vars:
    def __init__(self, vars):
        self.__dict__.update(vars)

class Tracker:
    def __init__(self, tracker_home):
        self.tracker_home = tracker_home
        self.config = configuration.Config(tracker_home)
        self.cgi_actions = {}
        self.templating_utils = {}

    def get_backend(self):
        o = __builtins__['open']
        f = o(os.path.join(self.tracker_home, 'db', 'backend_name'))
        name = f.readline().strip()
        f.close()
        return getattr(backends, name)

    def open(self, name):
        backend = self.get_backend()
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
        self._load_python('schema.py', vars)
        db = vars['db']

        detectors_dir = os.path.join(self.tracker_home, 'detectors')
        for name in os.listdir(detectors_dir):
            if not name.endswith('.py'):
                continue
            self._load_python(os.path.join('detectors', name), vars)
            vars['init'](db)

        db.post_init()
        return db

    def init(self, adminpw):
        db = self.open('admin')
        self._load_python('initial_data.py', {'db': db, 'adminpw': adminpw,
            'admin_email': self.config['ADMIN_EMAIL']})
        db.commit()
        db.close()

    def exists(self):
        backend = self.get_backend()
        return backend.db_exists(self.config)

    def nuke(self):
        backend = self.get_backend()
        backend.db_nuke(self.config)

    def _load_python(self, file, vars):
        file = os.path.join(self.tracker_home, file)
        execfile(file, vars)
        return vars

    def registerAction(self, name, action):
        self.cgi_actions[name] = action

    def registerUtil(self, name, function):
        self.templating_utils[name] = function

class TrackerError(Exception):
    pass


class OldStyleTrackers:
    def __init__(self):
        self.number = 0
        self.trackers = {}

    def open(self, tracker_home):
        ''' Open the tracker.

            Raise ValueError if the tracker home doesn't exist.
        '''
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
        tracker.config = configuration.Config(tracker_home)
        # FIXME! dbinit does "import config".
        #   What would be the upgrade plan for existing trackers?
        tracker.dbinit.config = tracker.config

        return tracker

OldStyleTrackers = OldStyleTrackers()
def open(tracker_home):
    if os.path.exists(os.path.join(tracker_home, 'dbinit.py')):
        # user should upgrade...
        return OldStyleTrackers.open(tracker_home)

    return Tracker(tracker_home)

# vim: set filetype=python sts=4 sw=4 et si :
