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
# $Id: instance.py,v 1.15 2004-07-19 01:49:26 richard Exp $

'''Tracker handling (open tracker).

Backwards compatibility for the old-style "imported" trackers.
'''
__docformat__ = 'restructuredtext'

import os
from roundup import rlog

class Vars:
    ''' I'm just a container '''

class Tracker:
    def __init__(self, tracker_home):
        self.tracker_home = tracker_home
        self.select_db = self._load_python('select_db.py')
        self.config = self._load_config('config.py')
        raise NotImplemented, 'this is *so* not finished'
        self.init =  XXX
        self.Client = XXX
        self.MailGW = XXX

    def open(self):
        return self._load_config('schema.py').db
        self._load_config('security.py', db=db)


    def _load_python(self, file):
        file = os.path.join(self.tracker_home, file)
        vars = Vars()
        execfile(file, vars.__dict__)
        return vars


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
        for required in 'config open init Client MailGW'.split():
            if not hasattr(tracker, required):
                raise TrackerError, \
                    'Required tracker attribute "%s" missing'%required

        # init the logging
        config = tracker.config
        if hasattr(config, 'LOGGING_CONFIG'):
            try:
                import logging
                config.logging = logging
            except ImportError, msg:
                raise TrackerError, 'Python logging module unavailable: %s'%msg
            config.logging.fileConfig(config.LOGGING_CONFIG)
        else:
            config.logging = rlog.BasicLogging()
            if hasattr(config, 'LOGGING_FILENAME'):
                config.logging.setFile(config.LOGGING_FILENAME)
            if hasattr(config, 'LOGGING_LEVEL'):
                config.logging.setLevel(config.LOGGING_LEVEL)
            else:
                config.logging.setLevel('ERROR')

        return tracker

OldStyleTrackers = OldStyleTrackers()
def open(tracker_home):
    if os.path.exists(os.path.join(tracker_home, 'dbinit.py')):
        # user should upgrade...
        return OldStyleTrackers.open(tracker_home)

    return Tracker(tracker_home)

# vim: set filetype=python ts=4 sw=4 et si
