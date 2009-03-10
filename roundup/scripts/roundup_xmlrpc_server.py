#! /usr/bin/env python
#
# Copyright (C) 2007 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#

import base64, getopt, os, sys, socket, urllib
from roundup.xmlrpc import translate
from roundup.xmlrpc import RoundupInstance
import roundup.instance
from roundup.instance import TrackerError
from roundup.cgi.exceptions import Unauthorised
from SimpleXMLRPCServer import SimpleXMLRPCServer
from SimpleXMLRPCServer import SimpleXMLRPCRequestHandler


class RequestHandler(SimpleXMLRPCRequestHandler):
    """A SimpleXMLRPCRequestHandler with support for basic
    HTTP Authentication."""

    TRACKER_HOMES = {}
    TRACKERS = {}

    def is_rpc_path_valid(self):
        path = self.path.split('/')
        name = urllib.unquote(path[1]).lower()
        return name in self.TRACKER_HOMES

    def get_tracker(self, name):
        """Return a tracker instance for given tracker name."""

        if name in self.TRACKERS:
            return self.TRACKERS[name]

        if name not in self.TRACKER_HOMES:
            raise Exception('No such tracker "%s"'%name)
        tracker_home = self.TRACKER_HOMES[name]
        tracker = roundup.instance.open(tracker_home)
        self.TRACKERS[name] = tracker
        return tracker


    def authenticate(self, tracker):

        
        # Try to extract username and password from HTTP Authentication.
        username, password = None, None
        authorization = self.headers.get('authorization', ' ')
        scheme, challenge = authorization.split(' ', 1)

        if scheme.lower() == 'basic':
            decoded = base64.decodestring(challenge)
            if ':' in decoded:
                username, password = decoded.split(':')
            else:
                username = decoded
        if not username:
            username = 'anonymous'
        db = tracker.open('admin')
        try:
            userid = db.user.lookup(username)
        except KeyError: # No such user
            db.close()
            raise Unauthorised, 'Invalid user'
        stored = db.user.get(userid, 'password')
        if stored != password:
            # Wrong password
            db.close()
            raise Unauthorised, 'Invalid user'
        db.setCurrentUser(username)
        return db


    def do_POST(self):
        """Extract username and password from authorization header."""

        db = None
        try:
            path = self.path.split('/')
            tracker_name = urllib.unquote(path[1]).lower()
            tracker = self.get_tracker(tracker_name)
            db = self.authenticate(tracker)

            instance = RoundupInstance(db, tracker.actions, None)
            self.server.register_instance(instance)
            SimpleXMLRPCRequestHandler.do_POST(self)
        except Unauthorised, message:
            self.send_error(403, '%s (%s)'%(self.path, message))
        except:
            if db:
                db.close()
            exc, val, tb = sys.exc_info()
            print exc, val, tb
            raise
        if db:
            db.close()


class Server(SimpleXMLRPCServer):

    def _dispatch(self, method, params):

        retn = SimpleXMLRPCServer._dispatch(self, method, params)
        retn = translate(retn)
        return retn


def usage():
    print """Usage: %s: [options] [name=tracker home]+

Options:
 -e, --encoding    -- specify the encoding to use
 -V                -- be verbose when importing
 -p, --port <port> -- port to listen on

"""%sys.argv[0]

def run():

    try:
        opts, args = getopt.getopt(sys.argv[1:],
                                   'e:i:p:V', ['encoding=', 'port='])
    except getopt.GetoptError, e:
        usage()
        return 1

    verbose = False
    port = 8000
    encoding = None

    for opt, arg in opts:
        if opt == '-V':
            verbose = True
        elif opt in ['-p', '--port']:
            port = int(arg)
        elif opt in ['-e', '--encoding']:
            encoding = encoding

    tracker_homes = {}
    for arg in args:
        try:
            name, home = arg.split('=', 1)
            # Validate the argument
            tracker = roundup.instance.open(home)
        except ValueError:
            print 'Instances must be name=home'
            sys.exit(-1)
        except TrackerError:
            print 'Tracker home does not exist.'
            sys.exit(-1)

        tracker_homes[name] = home

    RequestHandler.TRACKER_HOMES=tracker_homes

    if sys.version_info[0:2] < (2,5):
        if encoding:
            print 'encodings not supported with python < 2.5'
            sys.exit(-1)
        server = Server(('', port), RequestHandler)
    else:
        server = Server(('', port), RequestHandler,
                        allow_none=True, encoding=encoding)

    # Go into the main listener loop
    print 'Roundup XMLRPC server started on %s:%d' \
          % (socket.gethostname(), port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print 'Keyboard Interrupt: exiting'

if __name__ == '__main__':
    run()
