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

"""Command-line script stub that calls the roundup.mailgw.
"""
__docformat__ = 'restructuredtext'

# python version check
from roundup import version_check
from roundup import __version__ as roundup_version

import sys, os, re, cStringIO, getopt, socket, netrc

from roundup import mailgw
from roundup.i18n import _

def usage(args, message=None):
    if message is not None:
        print message
    print _(
"""Usage: %(program)s [-v] [-c class] [[-C class] -S field=value]* <instance home> [method]

Options:
 -v: print version and exit
 -c: default class of item to create (else the tracker's MAIL_DEFAULT_CLASS)
 -C / -S: see below

The roundup mail gateway may be called in one of four ways:
 . with an instance home as the only argument,
 . with both an instance home and a mail spool file,
 . with both an instance home and a POP/APOP server account, or
 . with both an instance home and a IMAP/IMAPS server account.

It also supports optional -C and -S arguments that allows you to set a
fields for a class created by the roundup-mailgw. The default class if
not specified is msg, but the other classes: issue, file, user can
also be used. The -S or --set options uses the same
property=value[;property=value] notation accepted by the command line
roundup command or the commands that can be given on the Subject line
of an email message.

It can let you set the type of the message on a per email address basis.

PIPE:
 In the first case, the mail gateway reads a single message from the
 standard input and submits the message to the roundup.mailgw module.

UNIX mailbox:
 In the second case, the gateway reads all messages from the mail spool
 file and submits each in turn to the roundup.mailgw module. The file is
 emptied once all messages have been successfully handled. The file is
 specified as:
   mailbox /path/to/mailbox

In all of the following the username and password can be stored in a
~/.netrc file. In this case only the server name need be specified on
the command-line.

The username and/or password will be prompted for if not supplied on
the command-line or in ~/.netrc.

POP:
 In the third case, the gateway reads all messages from the POP server
 specified and submits each in turn to the roundup.mailgw module. The
 server is specified as:
    pop username:password@server
 Alternatively, one can omit one or both of username and password:
    pop username@server
    pop server
 are both valid.

POPS:
 Connect to a POP server over ssl. This requires python 2.4 or later.
 This supports the same notation as POP.

APOP:
 Same as POP, but using Authenticated POP:
    apop username:password@server

IMAP:
 Connect to an IMAP server. This supports the same notation as that of
 POP mail.
    imap username:password@server
 It also allows you to specify a specific mailbox other than INBOX using
 this format:
    imap username:password@server mailbox

IMAPS:
 Connect to an IMAP server over ssl.
 This supports the same notation as IMAP.
    imaps username:password@server [mailbox]

IMAPS_CRAM:
 Connect to an IMAP server over ssl using CRAM-MD5 authentication.
 This supports the same notation as IMAP.
    imaps_cram username:password@server [mailbox]

""")%{'program': args[0]}
    return 1

def main(argv):
    '''Handle the arguments to the program and initialise environment.
    '''
    # take the argv array and parse it leaving the non-option
    # arguments in the args array.
    try:
        optionsList, args = getopt.getopt(argv[1:], 'vc:C:S:', ['set=',
            'class='])
    except getopt.GetoptError:
        # print help information and exit:
        usage(argv)
        sys.exit(2)

    for (opt, arg) in optionsList:
        if opt == '-v':
            print '%s (python %s)'%(roundup_version, sys.version.split()[0])
            return

    # figure the instance home
    if len(args) > 0:
        instance_home = args[0]
    else:
        instance_home = os.environ.get('ROUNDUP_INSTANCE', '')
    if not (instance_home and os.path.isdir(instance_home)):
        return usage(argv)

    # get the instance
    import roundup.instance
    instance = roundup.instance.open(instance_home)

    if hasattr(instance, 'MailGW'):
        handler = instance.MailGW(instance, optionsList)
    else:
        handler = mailgw.MailGW(instance, optionsList)

    # if there's no more arguments, read a single message from stdin
    if len(args) == 1:
        return handler.do_pipe()

    # otherwise, figure what sort of mail source to handle
    if len(args) < 3:
        return usage(argv, _('Error: not enough source specification information'))
    source, specification = args[1:3]

    # time out net connections after a minute if we can
    if source not in ('mailbox', 'imaps', 'imaps_cram'):
        if hasattr(socket, 'setdefaulttimeout'):
            socket.setdefaulttimeout(60)

    if source == 'mailbox':
        return handler.do_mailbox(specification)

    # the source will be a network server, so obtain the credentials to
    # use in connecting to the server
    try:
        # attempt to obtain credentials from a ~/.netrc file
        authenticator = netrc.netrc().authenticators(specification)
        username = authenticator[0]
        password = authenticator[2]
        server = specification
        # IOError if no ~/.netrc file, TypeError if the hostname
        # not found in the ~/.netrc file:
    except (IOError, TypeError):
        match = re.match(r'((?P<user>[^:]+)(:(?P<pass>.+))?@)?(?P<server>.+)',
                         specification)
        if match:
            username = match.group('user')
            password = match.group('pass')
            server = match.group('server')
        else:
            return usage(argv, _('Error: %s specification not valid') % source)

    # now invoke the mailgw handler depending on the server handler requested
    if source.startswith('pop'):
        ssl = source.endswith('s')
        if ssl and sys.version_info<(2,4):
            return usage(argv, _('Error: a later version of python is required'))
        return handler.do_pop(server, username, password, ssl)
    elif source == 'apop':
        return handler.do_apop(server, username, password)
    elif source.startswith('imap'):
        ssl = cram = 0
        if source.endswith('s'):
            ssl = 1
        elif source.endswith('s_cram'):
            ssl = cram = 1
        mailbox = ''
        if len(args) > 3:
            mailbox = args[3]
        return handler.do_imap(server, username, password, mailbox, ssl,
            cram)

    return usage(argv, _('Error: The source must be either "mailbox",'
        ' "pop", "pops", "apop", "imap", "imaps" or "imaps_cram'))

def run():
    sys.exit(main(sys.argv))

# call main
if __name__ == '__main__':
    run()

# vim: set filetype=python ts=4 sw=4 et si
