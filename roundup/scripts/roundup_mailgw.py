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
# $Id: roundup_mailgw.py,v 1.4 2002-09-10 01:07:06 richard Exp $

# python version check
from roundup import version_check

import sys, os, re, cStringIO

from roundup.mailgw import Message
from roundup.i18n import _

def do_pipe(handler):
    '''Read a message from standard input and pass it to the mail handler.
    '''
    handler.main(sys.stdin)
    return 0

def do_mailbox(handler, filename):
    '''Read a series of messages from the specified unix mailbox file and
    pass each to the mail handler.
    '''
    # open the spool file and lock it
    import fcntl, FCNTL
    f = open(filename, 'r+')
    fcntl.flock(f.fileno(), FCNTL.LOCK_EX)

    # handle and clear the mailbox
    try:
        from mailbox import UnixMailbox
        mailbox = UnixMailbox(f, factory=Message)
        # grab one message
        message = mailbox.next()
        while message:
            # call the instance mail handler
            handler.handle_Message(message)
            message = mailbox.next()
        # nuke the file contents
        os.ftruncate(f.fileno(), 0)
    except:
        import traceback
        traceback.print_exc()
        return 1
    fcntl.flock(f.fileno(), FCNTL.LOCK_UN)
    return 0

def do_pop(handler, server, user='', password=''):
    '''Read a series of messages from the specified POP server.
    '''
    import getpass, poplib, socket
    try:
        if not user:
            user = raw_input(_('User: '))
        if not password:
            password = getpass.getpass()
    except (KeyboardInterrupt, EOFError):
        # Ctrl C or D maybe also Ctrl Z under Windows.
        print "\nAborted by user."
        return 1

    # open a connection to the server and retrieve all messages
    try:
        server = poplib.POP3(server)
    except socket.error, message:
        print "POP server error:", message
        return 1
    server.user(user)
    server.pass_(password)
    numMessages = len(server.list()[1])
    for i in range(1, numMessages+1):
        # retr: returns 
        # [ pop response e.g. '+OK 459 octets',
        #   [ array of message lines ],
        #   number of octets ]
        lines = server.retr(i)[1]
        s = cStringIO.StringIO('\n'.join(lines))
        s.seek(0)
        handler.handle_Message(Message(s))
        # delete the message
        server.dele(i)

    # quit the server to commit changes.
    server.quit()
    return 0

def usage(args, message=None):
    if message is not None:
        print message
    print _('Usage: %(program)s <instance home> [source spec]')%{'program': args[0]}
    print _('''
The roundup mail gateway may be called in one of two ways:
 . with an instance home as the only argument,
 . with both an instance home and a mail spool file, or
 . with both an instance home and a pop server account.

PIPE:
 In the first case, the mail gateway reads a single message from the
 standard input and submits the message to the roundup.mailgw module.

UNIX mailbox:
 In the second case, the gateway reads all messages from the mail spool
 file and submits each in turn to the roundup.mailgw module. The file is
 emptied once all messages have been successfully handled. The file is
 specified as:
   mailbox /path/to/mailbox

POP:
 In the third case, the gateway reads all messages from the POP server
 specified and submits each in turn to the roundup.mailgw module. The
 server is specified as:
    pop username:password@server
 The username and password may be omitted:
    pop username@server
    pop server
 are both valid. The username and/or password will be prompted for if
 not supplied on the command-line.
''')
    return 1

def main(args):
    '''Handle the arguments to the program and initialise environment.
    '''
    # figure the instance home
    if len(args) > 1:
        instance_home = args[1]
    else:
        instance_home = os.environ.get('ROUNDUP_INSTANCE', '')
    if not instance_home:
        return usage(args)

    # get the instance
    import roundup.instance
    instance = roundup.instance.open(instance_home)

    # get a mail handler
    db = instance.open('admin')
    handler = instance.MailGW(instance, db)

    # if there's no more arguments, read a single message from stdin
    if len(args) == 2:
        return do_pipe(handler)

    # otherwise, figure what sort of mail source to handle
    if len(args) < 4:
        return usage(args, _('Error: not enough source specification information'))
    source, specification = args[2:]
    if source == 'mailbox':
        return do_mailbox(handler, specification)
    elif source == 'pop':
        m = re.match(r'((?P<user>[^:]+)(:(?P<pass>.+))?@)?(?P<server>.+)',
            specification)
        if m:
            return do_pop(handler, m.group('server'), m.group('user'),
                m.group('pass'))
        return usage(args, _('Error: pop specification not valid'))

    return usage(args, _('Error: The source must be either "mailbox" or "pop"'))

def run():
    sys.exit(main(sys.argv))

# call main
if __name__ == '__main__':
    run()

# vim: set filetype=python ts=4 sw=4 et si
