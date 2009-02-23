#! /usr/bin/env python
#
# Copyright (c) 2003 Richard Jones (richard@mechanicalcat.net)
#
# $Id: demo.py,v 1.26 2007-08-28 22:37:45 jpend Exp $

import errno
import os
import socket
import sys
import urlparse
from glob import glob

from roundup import configuration
from roundup.scripts import roundup_server

def install_demo(home, backend, template):
    """Install a demo tracker

    Parameters:
        home:
            tracker home directory path
        backend:
            database backend name
        template:
            full path to the tracker template directory

    """
    from roundup import init, instance, password, backends

    # set up the config for this tracker
    config = configuration.CoreConfig()
    config['TRACKER_HOME'] = home
    config['MAIL_DOMAIN'] = 'localhost'
    config['DATABASE'] = 'db'
    config['WEB_DEBUG'] = True
    if backend in ('mysql', 'postgresql'):
        config['RDBMS_HOST'] = 'localhost'
        config['RDBMS_USER'] = 'rounduptest'
        config['RDBMS_PASSWORD'] = 'rounduptest'
        config['RDBMS_NAME'] = 'rounduptest'

    # see if we have further db nuking to perform
    module = backends.get_backend(backend)
    if module.db_exists(config):
        module.db_nuke(config)

    init.install(home, template)
    # don't have email flying around
    os.remove(os.path.join(home, 'detectors', 'nosyreaction.py'))
    try:
        os.remove(os.path.join(home, 'detectors', 'nosyreaction.pyc'))
    except os.error, error:
        if error.errno != errno.ENOENT:
            raise
    init.write_select_db(home, backend)

    # figure basic params for server
    hostname = 'localhost'
    # pick a fairly odd, random port
    port = 8917
    while 1:
        print 'Trying to set up web server on port %d ...'%port,
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.connect((hostname, port))
        except socket.error, e:
            if not hasattr(e, 'args') or e.args[0] != errno.ECONNREFUSED:
                raise
            print 'should be ok.'
            break
        else:
            s.close()
            print 'already in use.'
            port += 100
    config['TRACKER_WEB'] = 'http://%s:%s/demo/'%(hostname, port)

    # write the config
    config['INSTANT_REGISTRATION'] = 1
    config.save(os.path.join(home, config.INI_FILE))

    # open the tracker and initialise
    tracker = instance.open(home)
    tracker.init(password.Password('admin'))

    # add the "demo" user
    db = tracker.open('admin')
    db.user.create(username='demo', password=password.Password('demo'),
        realname='Demo User', roles='User')
    db.commit()
    db.close()

def run_demo(home):
    """Run the demo tracker installed in ``home``"""
    cfg = configuration.CoreConfig(home)
    url = cfg["TRACKER_WEB"]
    hostname, port = urlparse.urlparse(url)[1].split(':')
    port = int(port)
    success_message = '''Server running - connect to:
    %s
1. Log in as "demo"/"demo" or "admin"/"admin".
2. Hit Control-C to stop the server.
3. Re-start the server by running "roundup-demo" again.
4. Re-initialise the server by running "roundup-demo nuke".

Demo tracker is set up to be accessed by localhost browser.  If you
run demo on a server host, please stop the demo, open file
"demo/config.ini" with your editor, change the host name in the "web"
option in section "[tracker]", save the file, then re-run the demo
program.

''' % url

    # disable command line processing in roundup_server
    sys.argv = sys.argv[:1] + ['-p', str(port), 'demo=' + home]
    roundup_server.run(success_message=success_message)

def demo_main():
    """Run a demo server for users to play with for instant gratification.

    Sets up the web service on localhost. Disables nosy lists.
    """
    home = os.path.abspath('demo')
    if not os.path.exists(home) or (sys.argv[-1] == 'nuke'):
        if len(sys.argv) > 2:
            backend = sys.argv[-2]
        else:
            backend = 'anydbm'
        install_demo(home, backend, os.path.join('share', 'roundup', 'templates', 'classic'))
    run_demo(home)

if __name__ == '__main__':
    demo_main()

# vim: set filetype=python sts=4 sw=4 et si :
