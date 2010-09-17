#!/usr/bin/env python
"""\
This script is a wrapper around the mailgw.py script that exists in roundup.
It runs as service instead of running as a one-time shot.
It also connects to a secure IMAP server. The main reasons for this script are:

1) The roundup-mailgw script isn't designed to run as a server. It
    expects that you either run it by hand, and enter the password each
    time, or you supply the password on the command line. I prefer to
    run a server that I initialize with the password, and then it just
    runs. I don't want to have to pass it on the command line, so
    running through crontab isn't a possibility. (This wouldn't be a
    problem on a local machine running through a mailspool.)
2) mailgw.py somehow screws up SSL support so IMAP4_SSL doesn't work. So
    hopefully running that work outside of the mailgw will allow it to work.
3) I wanted to be able to check multiple projects at the same time.
    roundup-mailgw is only for 1 mailbox and 1 project.


*TODO*:
  For the first round, the program spawns a new roundup-mailgw for
  each imap message that it finds and pipes the result in. In the
  future it might be more practical to actually include the roundup
  files and run the appropriate commands using python.

*TODO*:
  Look into supporting a logfile instead of using 2>/logfile

*TODO*:
  Add an option for changing the uid/gid of the running process.
"""

import getpass
import logging
import imaplib
import optparse
import os
import re
import time

logging.basicConfig()
log = logging.getLogger('roundup.IMAPServer')

version = '0.1.2'

class RoundupMailbox:
    """This contains all the info about each mailbox.
    Username, Password, server, security, roundup database
    """
    def __init__(self, dbhome='', username=None, password=None, mailbox=None
        , server=None, protocol='imaps'):
        self.username = username
        self.password = password
        self.mailbox = mailbox
        self.server = server
        self.protocol = protocol
        self.dbhome = dbhome

        try:
            if not self.dbhome:
                self.dbhome = raw_input('Tracker home: ')
                if not os.path.exists(self.dbhome):
                    raise ValueError, 'Invalid home address: ' \
                        'directory "%s" does not exist.' % self.dbhome

            if not self.server:
                self.server = raw_input('Server: ')
                if not self.server:
                    raise ValueError, 'No Servername supplied'
                protocol = raw_input('protocol [imaps]? ')
                self.protocol = protocol

            if not self.username:
                self.username = raw_input('Username: ')
                if not self.username:
                    raise ValueError, 'Invalid Username'

            if not self.password:
                print 'For server %s, user %s' % (self.server, self.username)
                self.password = getpass.getpass()
                # password can be empty because it could be superceeded
                # by a later entry

            #if self.mailbox is None:
            #   self.mailbox = raw_input('Mailbox [INBOX]: ')
            #   # We allow an empty mailbox because that will
            #   # select the INBOX, whatever it is called

        except (KeyboardInterrupt, EOFError):
            raise ValueError, 'Canceled by User'

    def __str__(self):
        return 'Mailbox{ server:%(server)s, protocol:%(protocol)s, ' \
            'username:%(username)s, mailbox:%(mailbox)s, ' \
            'dbhome:%(dbhome)s }' % self.__dict__


# [als] class name is misleading.  this is imap client, not imap server
class IMAPServer:

    """IMAP mail gatherer.

    This class runs as a server process. It is configured with a list of
    mailboxes to connect to, along with the roundup database directories
    that correspond with each email address.  It then connects to each
    mailbox at a specified interval, and if there are new messages it
    reads them, and sends the result to the roundup.mailgw.

    *TODO*:
      Try to be smart about how you access the mailboxes so that you can
      connect once, and access multiple mailboxes and possibly multiple
      usernames.

    *NOTE*:
      This assumes that if you are using the same user on the same
      server, you are using the same password. (the last one supplied is
      used.) Empty passwords are ignored.  Only the last protocol
      supplied is used.
    """

    def __init__(self, pidfile=None, delay=5, daemon=False):
        #This is sorted by servername, then username, then mailboxes
        self.mailboxes = {}
        self.delay = float(delay)
        self.pidfile = pidfile
        self.daemon = daemon

    def setDelay(self, delay):
        self.delay = delay

    def addMailbox(self, mailbox):
        """ The linkage is as follows:
        servers -- users - mailbox:dbhome
        So there can be multiple servers, each with multiple users.
        Each username can be associated with multiple mailboxes.
        each mailbox is associated with 1 database home
        """
        log.info('Adding mailbox %s', mailbox)
        if not self.mailboxes.has_key(mailbox.server):
            self.mailboxes[mailbox.server] = {'protocol':'imaps', 'users':{}}
        server = self.mailboxes[mailbox.server]
        if mailbox.protocol:
            server['protocol'] = mailbox.protocol

        if not server['users'].has_key(mailbox.username):
            server['users'][mailbox.username] = {'password':'', 'mailboxes':{}}
        user = server['users'][mailbox.username]
        if mailbox.password:
            user['password'] = mailbox.password

        if user['mailboxes'].has_key(mailbox.mailbox):
            raise ValueError, 'Mailbox is already defined'

        user['mailboxes'][mailbox.mailbox] = mailbox.dbhome

    def _process(self, message, dbhome):
        """Actually process one of the email messages"""
        child = os.popen('roundup-mailgw %s' % dbhome, 'wb')
        child.write(message)
        child.close()
        #print message

    def _getMessages(self, serv, count, dbhome):
        """This assumes that you currently have a mailbox open, and want to
        process all messages that are inside.
        """
        for n in range(1, count+1):
            (t, data) = serv.fetch(n, '(RFC822)')
            if t == 'OK':
                self._process(data[0][1], dbhome)
                serv.store(n, '+FLAGS', r'(\Deleted)')

    def checkBoxes(self):
        """This actually goes out and does all the checking.
        Returns False if there were any errors, otherwise returns true.
        """
        noErrors = True
        for server in self.mailboxes:
            log.info('Connecting to server: %s', server)
            s_vals = self.mailboxes[server]

            try:
                for user in s_vals['users']:
                    u_vals = s_vals['users'][user]
                    # TODO: As near as I can tell, you can only
                    # login with 1 username for each connection to a server.
                    protocol = s_vals['protocol'].lower()
                    if protocol == 'imaps':
                        serv = imaplib.IMAP4_SSL(server)
                    elif protocol == 'imap':
                        serv = imaplib.IMAP4(server)
                    else:
                        raise ValueError, 'Unknown protocol %s' % protocol

                    password = u_vals['password']

                    try:
                        log.info('Connecting as user: %s', user)
                        serv.login(user, password)

                        for mbox in u_vals['mailboxes']:
                            dbhome = u_vals['mailboxes'][mbox]
                            log.info('Using mailbox: %s, home: %s',
                                mbox, dbhome)
                            #access a specific mailbox
                            if mbox:
                                (t, data) = serv.select(mbox)
                            else:
                                # Select the default mailbox (INBOX)
                                (t, data) = serv.select()
                            try:
                                nMessages = int(data[0])
                            except ValueError:
                                nMessages = 0

                            log.info('Found %s messages', nMessages)

                            if nMessages:
                                self._getMessages(serv, nMessages, dbhome)
                                serv.expunge()

                            # We are done with this mailbox
                            serv.close()
                    except:
                        log.exception('Exception with server %s user %s',
                            server, user)
                        noErrors = False

                    serv.logout()
                    serv.shutdown()
                    del serv
            except:
                log.exception('Exception while connecting to %s', server)
                noErrors = False
        return noErrors


    def makeDaemon(self):
        """Turn this process into a daemon.

        - make our parent PID 1

        Write our new PID to the pidfile.

        From A.M. Kuuchling (possibly originally Greg Ward) with
        modification from Oren Tirosh, and finally a small mod from me.
        Originally taken from roundup.scripts.roundup_server.py
        """
        log.info('Running as Daemon')
        # Fork once
        if os.fork() != 0:
            os._exit(0)

        # Create new session
        os.setsid()

        # Second fork to force PPID=1
        pid = os.fork()
        if pid:
            if self.pidfile:
                pidfile = open(self.pidfile, 'w')
                pidfile.write(str(pid))
                pidfile.close()
            os._exit(0)

    def run(self):
        """Run email gathering daemon.

        This spawns itself as a daemon, and then runs continually, just
        sleeping inbetween checks.  It is recommended that you run
        checkBoxes once first before you select run. That way you can
        know if there were any failures.
        """
        if self.daemon:
            self.makeDaemon()
        while True:

            time.sleep(self.delay * 60.0)
            log.info('Time: %s', time.strftime('%Y-%m-%d %H:%M:%S'))
            self.checkBoxes()

def getItems(s):
    """Parse a string looking for userame@server"""
    myRE = re.compile(
        r'((?P<protocol>[^:]+)://)?'#You can supply a protocol if you like
        r'('                        #The username part is optional
         r'(?P<username>[^:]+)'     #You can supply the password as
         r'(:(?P<password>.+))?'    #username:password@server
        r'@)?'
        r'(?P<server>[^/]+)'
        r'(/(?P<mailbox>.+))?$'
    )
    m = myRE.match(s)
    if m:
        return m.groupdict()
    else:
        return None

def main():
    """This is what is called if run at the prompt"""
    parser = optparse.OptionParser(
        version=('%prog ' + version),
        usage="""usage: %prog [options] (home server)...

So each entry has a home, and then the server configuration. Home is just
a path to the roundup issue tracker. The server is something of the form:

    imaps://user:password@server/mailbox

If you don't supply the protocol, imaps is assumed. Without user or
password, you will be prompted for them. The server must be supplied.
Without mailbox the INBOX is used.

Examples:
  %prog /home/roundup/trackers/test imaps://test@imap.example.com/test
  %prog /home/roundup/trackers/test imap.example.com \
/home/roundup/trackers/test2 imap.example.com/test2
"""
    )
    parser.add_option('-d', '--delay', dest='delay', type='float',
        metavar='<sec>', default=5,
        help="Set the delay between checks in minutes. (default 5)"
    )
    parser.add_option('-p', '--pid-file', dest='pidfile',
        metavar='<file>', default=None,
        help="The pid of the server process will be written to <file>"
    )
    parser.add_option('-n', '--no-daemon', dest='daemon',
        action='store_false', default=True,
        help="Do not fork into the background after running the first check."
    )
    parser.add_option('-v', '--verbose', dest='verbose',
        action='store_const', const=logging.INFO,
        help="Be more verbose in letting you know what is going on."
        " Enables informational messages."
    )
    parser.add_option('-V', '--very-verbose', dest='verbose',
        action='store_const', const=logging.DEBUG,
        help="Be very verbose in letting you know what is going on."
            " Enables debugging messages."
    )
    parser.add_option('-q', '--quiet', dest='verbose',
        action='store_const', const=logging.ERROR,
        help="Be less verbose. Ignores warnings, only prints errors."
    )
    parser.add_option('-Q', '--very-quiet', dest='verbose',
        action='store_const', const=logging.CRITICAL,
        help="Be much less verbose. Ignores warnings and errors."
            " Only print CRITICAL messages."
    )

    (opts, args) = parser.parse_args()
    if (len(args) == 0) or (len(args) % 2 == 1):
        parser.error('Invalid number of arguments. '
            'Each site needs a home and a server.')

    log.setLevel(opts.verbose)
    myServer = IMAPServer(delay=opts.delay, pidfile=opts.pidfile,
        daemon=opts.daemon)
    for i in range(0,len(args),2):
        home = args[i]
        server = args[i+1]
        if not os.path.exists(home):
            parser.error('Home: "%s" does not exist' % home)

        info = getItems(server)
        if not info:
            parser.error('Invalid server string: "%s"' % server)

        myServer.addMailbox(
            RoundupMailbox(dbhome=home, mailbox=info['mailbox']
            , username=info['username'], password=info['password']
            , server=info['server'], protocol=info['protocol']
            )
        )

    if myServer.checkBoxes():
        myServer.run()

if __name__ == '__main__':
    main()

# vim: et ft=python si sts=4 sw=4
