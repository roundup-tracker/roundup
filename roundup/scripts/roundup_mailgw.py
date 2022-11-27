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
from __future__ import print_function
__docformat__ = 'restructuredtext'


# --- patch sys.path to make sure 'import roundup' finds correct version
import sys
import os.path as osp
from argparse import ArgumentParser, RawDescriptionHelpFormatter

thisdir = osp.dirname(osp.abspath(__file__))
rootdir = osp.dirname(osp.dirname(thisdir))
if (osp.exists(thisdir + '/__init__.py') and
        osp.exists(rootdir + '/roundup/__init__.py')):
    # the script is located inside roundup source code
    sys.path.insert(0, rootdir)
# --/


# python version check
from roundup import version_check
from roundup import __version__ as roundup_version

import sys, os, re, getopt, socket, netrc

from roundup import mailgw
from roundup.i18n import _


usage_epilog = """
The roundup mail gateway may be called in one of the following ways:
 . without arguments. Then the env var ROUNDUP_INSTANCE will be tried.
 . with an instance home as the only argument,
 . with both an instance home and a mail spool file, or
 . with an instance home, a mail source type and its specification.

It also supports optional -S (or --set-value) arguments that allows you
to set fields for a class created by the roundup-mailgw. The format for
this option is [class.]property=value where class can be omitted and
defaults to msg. The -S options uses the same
property=value[;property=value] notation accepted by the command line
roundup command or the commands that can be given on the Subject line of
an email message (if you're using multiple properties delimited with a
semicolon the class must be specified only once in the beginning).

It can let you set the type of the message on a per email address basis
by calling roundup-mailgw with different email addresses and other
settings.

PIPE:
 If there is no mail source specified, the mail gateway reads a single
 message from the standard input and submits the message to the
 roundup.mailgw module.

Mail source "mailbox":
 In this case, the gateway reads all messages from the UNIX mail spool
 file and submits each in turn to the roundup.mailgw module. The file is
 emptied once all messages have been successfully handled. The file is
 specified as:
   mailbox /path/to/mailbox

In all of the following mail source types, the username and password
can be stored in a ~/.netrc file. If done so, only the server name
needs to be specified on the command-line.

The username and/or password will be prompted for if not supplied on
the command-line or in ~/.netrc.

POP:
 For the mail source "pop", the gateway reads all messages from the POP
 server specified and submits each in turn to the roundup.mailgw module.
 The server is specified as:
    pop username:password@server
 The username and password may be omitted:
    pop username@server
    pop server
 are both valid.

POPS:
 Connect to a POP server over ssl/tls.
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
 Connect to an IMAP server over ssl/tls.
 This supports the same notation as IMAP.
    imaps username:password@server [mailbox]

IMAPS_CRAM:
 Connect to an IMAP server over ssl/tls using CRAM-MD5 authentication.
 This supports the same notation as IMAP.
    imaps_cram username:password@server [mailbox]

IMAPS_OAUTH:
 Connect to an IMAP server over ssl/tls using OAUTH authentication.
 Note that this does not support a password in imaps URLs.
 Instead it uses only the user and server and a command-line option for
 the directory with the files 'access_token', 'refresh_token',
 'client_secret', and 'client_id'.
 By default this directory is 'oauth' in your tracker home directory. The
 access token is tried first and, if expired, the refresh token together
 with the client secret is used to retrieve a new access token. Note that
 both token files need to be *writeable*, the access token is
 continuously replaced and some cloud providers may also renew the
 refresh token from time to time:
    imaps_oauth username@server [mailbox]
 The refresh and access tokens (the latter can be left empty), the
 client id and the client secret need to be retrieved via cloud provider
 specific protocols or websites.



"""

def parse_arguments(argv):
    '''Handle the arguments to the program
    '''
    # take the argv array and parse it leaving the non-option
    # arguments in the list 'args'.
    cmd = ArgumentParser(epilog=usage_epilog,
        formatter_class=RawDescriptionHelpFormatter)
    cmd.add_argument('args', nargs='*')
    cmd.add_argument('-v', '--version', action='store_true',
        help='print version and exit')
    cmd.add_argument('-c', '--default-class', default='',
        help="Default class of item to create (else the tracker's "
        "MAILGW_DEFAULT_CLASS)")
    cmd.add_argument('-O', '--oauth-directory',
        help='Directory with OAUTH credentials, default "oauth" in '
        'tracker home')
    cmd.add_argument('-S', '--set-value', action='append',
        help="Set additional properties on some classes", default=[])
    cmd.add_argument('-T', '--oauth-token-endpoint',
        help="OAUTH token endpoint for access_token renew, default=%(default)s",
        default='https://login.microsoftonline.com/'
            'organizations/oauth2/v2.0/token')
    return cmd, cmd.parse_args(argv)

def main(argv):
    '''Handle the arguments to the program and initialise environment.
    '''
    cmd, args = parse_arguments(argv)
    if args.version:
        print('%s (python %s)' % (roundup_version, sys.version.split()[0]))
        return

    # figure the instance home
    if len(args.args) > 0:
        instance_home = args.args[0]
    else:
        instance_home = os.environ.get('ROUNDUP_INSTANCE', '')
    if not (instance_home and os.path.isdir(instance_home)):
        cmd.print_help(sys.stderr)
        return _('\nError: The instance home must be specified')

    # get the instance
    import roundup.instance
    instance = roundup.instance.open(instance_home)

    if hasattr(instance, 'MailGW'):
        handler = instance.MailGW(instance, args)
    else:
        handler = mailgw.MailGW(instance, args)

    # if there's no more arguments, read a single message from stdin
    if len(args.args) == 1:
        return handler.do_pipe()

    # otherwise, figure what sort of mail source to handle
    if len(args.args) < 3:
        cmd.print_help(sys.stderr)
        return _('\nError: not enough source specification information')

    source, specification = args.args[1:3]

    # time out net connections after a minute if we can
    if source not in ('mailbox', 'imaps', 'imaps_cram', 'imaps_oauth'):
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
            cmd.print_help(sys.stderr)
            return _('\nError: %s specification not valid') % source

    # now invoke the mailgw handler depending on the server handler requested
    if source.startswith('pop'):
        ssl = source.endswith('s')
        return handler.do_pop(server, username, password, ssl)
    elif source == 'apop':
        return handler.do_apop(server, username, password)
    elif source.startswith('imap'):
        d = {}
        if source.endswith('s'):
            d.update(ssl = 1)
        elif source.endswith('s_cram'):
            d.update(ssl = 1, cram = 1)
        elif source == 'imaps_oauth':
            d.update(ssl = 1, oauth = 1, oauth_path = args.oauth_directory)
            d.update(token_endpoint = args.oauth_token_endpoint)
        mailbox = ''
        if len(args.args) > 3:
            mailbox = args.args[3]
        return handler.do_imap(server, username, password, mailbox, **d)

    cmd.print_help(sys.stderr)
    return _('\nError: The source must be either "mailbox",'
             ' "pop", "pops", "apop", "imap", "imaps", '
             ' "imaps_cram", or "imaps_oauth"')


def run():
    sys.exit(main(sys.argv [1:]))


# call main
if __name__ == '__main__':
    run()

# vim: set filetype=python ts=4 sw=4 et si
