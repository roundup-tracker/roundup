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
# $Id: instance.py,v 1.7 2002-09-17 23:59:32 richard Exp $

__doc__ = '''
Tracker handling (open tracker).

Currently this module provides one function: open. This function opens
a tracker. Note that trackers used to be called instances.
'''

import imp, os

class InstanceError(Exception):
    pass

class Opener:
    def __init__(self):
        self.number = 0
        self.trackers = {}

    def open(self, tracker_home):
        ''' Open the tracker.

            Raise ValueError if the tracker home doesn't exist.
        '''
        if not os.path.exists(tracker_home):
            raise ValueError, 'no such directory: "%s"'%tracker_home
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
                raise InstanceError, 'Required tracker attribute "%s" '\
                    'missing'%required

        return tracker

opener = Opener()
open = opener.open

del Opener
del opener


# vim: set filetype=python ts=4 sw=4 et si
