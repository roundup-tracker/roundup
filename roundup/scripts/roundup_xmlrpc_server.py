#! /usr/bin/env python
#
# Copyright (C) 2007 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#

import getopt, os, sys, socket
from roundup.xmlrpc import RoundupServer, RoundupRequestHandler
from roundup.instance import TrackerError
from SimpleXMLRPCServer import SimpleXMLRPCServer

def usage():
    print """

Options:
 -i instance home  -- specify the issue tracker "home directory" to administer
 -V                -- be verbose when importing
 -p, --port <port> -- port to listen on

"""

def run():

    try:
        opts, args = getopt.getopt(sys.argv[1:],
                                   'e:i:p:V', ['encoding=', 'port='])
    except getopt.GetoptError, e:
        usage()
        return 1

    verbose = False
    tracker = ''
    port = 8000
    encoding = None

    for opt, arg in opts:
        if opt == '-V':
            verbose = True
        elif opt == '-i':
            tracker = arg
        elif opt in ['-p', '--port']:
            port = int(arg)
        elif opt in ['-e', '--encoding']:
            encoding = encoding

        if sys.version_info[0:2] < (2,5):
            if encoding:
                print 'encodings not supported with python < 2.5'
                sys.exit(-1)
            server = SimpleXMLRPCServer(('', port), RoundupRequestHandler)
        else:
            server = SimpleXMLRPCServer(('', port), RoundupRequestHandler,
                                        allow_none=True, encoding=encoding)
    if not os.path.exists(tracker):
        print 'Instance home does not exist.'
        sys.exit(-1)
    try:
        object = RoundupServer(tracker, verbose)
    except TrackerError:
        print 'Instance home does not exist.'
        sys.exit(-1)

    server.register_instance(object)

    # Go into the main listener loop
    print 'Roundup XMLRPC server started on %s:%d' \
          % (socket.gethostname(), port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print 'Keyboard Interrupt: exiting'

if __name__ == '__main__':
    run()
