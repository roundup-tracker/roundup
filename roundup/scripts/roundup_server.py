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
""" HTTP Server that serves roundup.

$Id: roundup_server.py,v 1.8 2002-09-07 22:46:19 richard Exp $
"""

# python version check
from roundup import version_check

import sys, os, urllib, StringIO, traceback, cgi, binascii, getopt, imp
import BaseHTTPServer

# Roundup modules of use here
from roundup.cgi import cgitb, client
import roundup.instance
from roundup.i18n import _

#
##  Configuration
#

# This indicates where the Roundup instance lives
ROUNDUP_INSTANCE_HOMES = {
    'bar': '/tmp/bar',
}

ROUNDUP_USER = None


# Where to log debugging information to. Use an instance of DevNull if you
# don't want to log anywhere.
# TODO: actually use this stuff
#class DevNull:
#    def write(self, info):
#        pass
#LOG = open('/var/log/roundup.cgi.log', 'a')
#LOG = DevNull()

#
##  end configuration
#


class RoundupRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    ROUNDUP_INSTANCE_HOMES = ROUNDUP_INSTANCE_HOMES
    ROUNDUP_USER = ROUNDUP_USER

    def run_cgi(self):
        """ Execute the CGI command. Wrap an innner call in an error
            handler so all errors can be caught.
        """
        save_stdin = sys.stdin
        sys.stdin = self.rfile
        try:
            self.inner_run_cgi()
        except client.NotFound:
            self.send_error(404, self.path)
        except client.Unauthorised:
            self.send_error(403, self.path)
        except:
            # it'd be nice to be able to detect if these are going to have
            # any effect...
            self.send_response(400)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            try:
                reload(cgitb)
                self.wfile.write(cgitb.breaker())
                self.wfile.write(cgitb.html())
            except:
                self.wfile.write("<pre>")
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                self.wfile.write(cgi.escape(s.getvalue()))
                self.wfile.write("</pre>\n")
        sys.stdin = save_stdin

    do_GET = do_POST = do_HEAD = send_head = run_cgi

    def index(self):
        ''' Print up an index of the available instances
        '''
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        w = self.wfile.write
        w(_('<html><head><title>Roundup instances index</title></head>\n'))
        w(_('<body><h1>Roundup instances index</h1><ol>\n'))
        for instance in self.ROUNDUP_INSTANCE_HOMES.keys():
            w(_('<li><a href="%(instance_url)s/index">%(instance_name)s</a>\n')%{
                'instance_url': urllib.quote(instance),
                'instance_name': cgi.escape(instance)})
        w(_('</ol></body></html>'))

    def inner_run_cgi(self):
        ''' This is the inner part of the CGI handling
        '''

        rest = self.path
        i = rest.rfind('?')
        if i >= 0:
            rest, query = rest[:i], rest[i+1:]
        else:
            query = ''

        # figure the instance
        if rest == '/':
            return self.index()
        l_path = rest.split('/')
        instance_name = urllib.unquote(l_path[1])
        if self.ROUNDUP_INSTANCE_HOMES.has_key(instance_name):
            instance_home = self.ROUNDUP_INSTANCE_HOMES[instance_name]
            instance = roundup.instance.open(instance_home)
        else:
            raise client.NotFound

        # figure out what the rest of the path is
        if len(l_path) > 2:
            rest = '/'.join(l_path[2:])
        else:
            rest = '/'

        # Set up the CGI environment
        env = {}
        env['INSTANCE_NAME'] = instance_name
        env['REQUEST_METHOD'] = self.command
        env['PATH_INFO'] = urllib.unquote(rest)
        if query:
            env['QUERY_STRING'] = query
        host = self.address_string()
        if self.headers.typeheader is None:
            env['CONTENT_TYPE'] = self.headers.type
        else:
            env['CONTENT_TYPE'] = self.headers.typeheader
        length = self.headers.getheader('content-length')
        if length:
            env['CONTENT_LENGTH'] = length
        co = filter(None, self.headers.getheaders('cookie'))
        if co:
            env['HTTP_COOKIE'] = ', '.join(co)
        env['SCRIPT_NAME'] = ''
        env['SERVER_NAME'] = self.server.server_name
        env['SERVER_PORT'] = str(self.server.server_port)
        env['HTTP_HOST'] = self.headers['host']

        decoded_query = query.replace('+', ' ')

        # do the roundup thang
        c = instance.Client(instance, self, env)
        c.main()

def usage(message=''):
    if message:
        message = _('Error: %(error)s\n\n')%{'error': message}
    print _('''%(message)sUsage:
roundup-server [-n hostname] [-p port] [-l file] [-d file] [name=instance home]*

 -n: sets the host name
 -p: sets the port to listen on
 -l: sets a filename to log to (instead of stdout)
 -d: daemonize, and write the server's PID to the nominated file

 name=instance home
   Sets the instance home(s) to use. The name is how the instance is
   identified in the URL (it's the first part of the URL path). The
   instance home is the directory that was identified when you did
   "roundup-admin init". You may specify any number of these name=home
   pairs on the command-line. For convenience, you may edit the
   ROUNDUP_INSTANCE_HOMES variable in the roundup-server file instead.
''')%locals()
    sys.exit(0)

def daemonize(pidfile):
    ''' Turn this process into a daemon.
        - make sure the sys.std(in|out|err) are completely cut off
        - make our parent PID 1

        Write our new PID to the pidfile.

        From A.M. Kuuchling (possibly originally Greg Ward) with
        modification from Oren Tirosh, and finally a small mod from me.
    '''
    # Fork once
    if os.fork() != 0:
        os._exit(0)

    # Create new session
    os.setsid()

    # Second fork to force PPID=1
    pid = os.fork()
    if pid:
        pidfile = open(pidfile, 'w')
        pidfile.write(str(pid))
        pidfile.close()
        os._exit(0)         

    os.chdir("/")         
    os.umask(0)

    # close off sys.std(in|out|err), redirect to devnull so the file
    # descriptors can't be used again
    devnull = os.open('/dev/null', 0)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)

def run():
    hostname = ''
    port = 8080
    pidfile = None
    logfile = None
    try:
        # handle the command-line args
        try:
            optlist, args = getopt.getopt(sys.argv[1:], 'n:p:u:d:l:')
        except getopt.GetoptError, e:
            usage(str(e))

        user = ROUNDUP_USER
        for (opt, arg) in optlist:
            if opt == '-n': hostname = arg
            elif opt == '-p': port = int(arg)
            elif opt == '-u': user = arg
            elif opt == '-d': pidfile = arg
            elif opt == '-l': logfile = arg
            elif opt == '-h': usage()

        if hasattr(os, 'getuid'):
            # if root, setuid to the running user
            if not os.getuid() and user is not None:
                try:
                    import pwd
                except ImportError:
                    raise ValueError, _("Can't change users - no pwd module")
                try:
                    uid = pwd.getpwnam(user)[2]
                except KeyError:
                    raise ValueError, _("User %(user)s doesn't exist")%locals()
                os.setuid(uid)
            elif os.getuid() and user is not None:
                print _('WARNING: ignoring "-u" argument, not root')

            # People can remove this check if they're really determined
            if not os.getuid() and user is None:
                raise ValueError, _("Can't run as root!")

        # handle instance specs
        if args:
            d = {}
            for arg in args:
		try:
                    name, home = arg.split('=')
                except ValueError:
                    raise ValueError, _("Instances must be name=home")
                d[name] = home
            RoundupRequestHandler.ROUNDUP_INSTANCE_HOMES = d
    except SystemExit:
        raise
    except:
        exc_type, exc_value = sys.exc_info()[:2]
        usage('%s: %s'%(exc_type, exc_value))

    # we don't want the cgi module interpreting the command-line args ;)
    sys.argv = sys.argv[:1]
    address = (hostname, port)

    # fork?
    if pidfile:
        daemonize(pidfile)

    # redirect stdout/stderr to our logfile
    if logfile:
        sys.stdout = sys.stderr = open(logfile, 'a')

    httpd = BaseHTTPServer.HTTPServer(address, RoundupRequestHandler)
    print _('Roundup server started on %(address)s')%locals()
    httpd.serve_forever()

if __name__ == '__main__':
    run()

#
# $Log: not supported by cvs2svn $
# Revision 1.7  2002/09/04 07:32:55  richard
# add daemonification
#
# Revision 1.6  2002/08/30 08:33:28  richard
# new CGI frontend support
#
# Revision 1.5  2002/03/14 23:59:24  richard
#  . #517734 ] web header customisation is obscure
#
# Revision 1.4  2002/02/21 07:02:54  richard
# The correct var is "HTTP_HOST"
#
# Revision 1.3  2002/02/21 06:57:39  richard
#  . Added popup help for classes using the classhelp html template function.
#    - add <display call="classhelp('priority', 'id,name,description')">
#      to an item page, and it generates a link to a popup window which displays
#      the id, name and description for the priority class. The description
#      field won't exist in most installations, but it will be added to the
#      default templates.
#
# Revision 1.2  2002/01/29 20:07:15  jhermann
# Conversion to generated script stubs
#
# Revision 1.1  2002/01/29 19:53:08  jhermann
# Moved scripts from top-level dir to roundup.scripts subpackage
#
# Revision 1.25  2002/01/05 02:21:21  richard
# fixes
#
# Revision 1.24  2002/01/05 02:19:03  richard
# i18n'ification
#
# Revision 1.23  2001/12/15 23:47:07  richard
# sys module went away...
#
# Revision 1.22  2001/12/13 00:20:01  richard
#  . Centralised the python version check code, bumped version to 2.1.1 (really
#    needs to be 2.1.2, but that isn't released yet :)
#
# Revision 1.21  2001/12/02 05:06:16  richard
# . We now use weakrefs in the Classes to keep the database reference, so
#   the close() method on the database is no longer needed.
#   I bumped the minimum python requirement up to 2.1 accordingly.
# . #487480 ] roundup-server
# . #487476 ] INSTALL.txt
#
# I also cleaned up the change message / post-edit stuff in the cgi client.
# There's now a clearly marked "TODO: append the change note" where I believe
# the change note should be added there. The "changes" list will obviously
# have to be modified to be a dict of the changes, or somesuch.
#
# More testing needed.
#
# Revision 1.20  2001/11/26 22:55:56  richard
# Feature:
#  . Added INSTANCE_NAME to configuration - used in web and email to identify
#    the instance.
#  . Added EMAIL_SIGNATURE_POSITION to indicate where to place the roundup
#    signature info in e-mails.
#  . Some more flexibility in the mail gateway and more error handling.
#  . Login now takes you to the page you back to the were denied access to.
#
# Fixed:
#  . Lots of bugs, thanks Roché and others on the devel mailing list!
#
# Revision 1.19  2001/11/12 22:51:04  jhermann
# Fixed option & associated error handling
#
# Revision 1.18  2001/11/01 22:04:37  richard
# Started work on supporting a pop3-fetching server
# Fixed bugs:
#  . bug #477104 ] HTML tag error in roundup-server
#  . bug #477107 ] HTTP header problem
#
# Revision 1.17  2001/10/29 23:55:44  richard
# Fix to CGI top-level index (thanks Juergen Hermann)
#
# Revision 1.16  2001/10/27 00:12:21  richard
# Fixed roundup-server for windows, thanks Juergen Hermann.
#
# Revision 1.15  2001/10/12 02:23:26  richard
# Didn't clean up after myself :)
#
# Revision 1.14  2001/10/12 02:20:32  richard
# server now handles setuid'ing much better
#
# Revision 1.13  2001/10/05 02:23:24  richard
#  . roundup-admin create now prompts for property info if none is supplied
#    on the command-line.
#  . hyperdb Class getprops() method may now return only the mutable
#    properties.
#  . Login now uses cookies, which makes it a whole lot more flexible. We can
#    now support anonymous user access (read-only, unless there's an
#    "anonymous" user, in which case write access is permitted). Login
#    handling has been moved into cgi_client.Client.main()
#  . The "extended" schema is now the default in roundup init.
#  . The schemas have had their page headings modified to cope with the new
#    login handling. Existing installations should copy the interfaces.py
#    file from the roundup lib directory to their instance home.
#  . Incorrectly had a Bizar Software copyright on the cgitb.py module from
#    Ping - has been removed.
#  . Fixed a whole bunch of places in the CGI interface where we should have
#    been returning Not Found instead of throwing an exception.
#  . Fixed a deviation from the spec: trying to modify the 'id' property of
#    an item now throws an exception.
#
# Revision 1.12  2001/09/29 13:27:00  richard
# CGI interfaces now spit up a top-level index of all the instances they can
# serve.
#
# Revision 1.11  2001/08/07 00:24:42  richard
# stupid typo
#
# Revision 1.10  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.9  2001/08/05 07:44:36  richard
# Instances are now opened by a special function that generates a unique
# module name for the instances on import time.
#
# Revision 1.8  2001/08/03 01:28:33  richard
# Used the much nicer load_package, pointed out by Steve Majewski.
#
# Revision 1.7  2001/08/03 00:59:34  richard
# Instance import now imports the instance using imp.load_module so that
# we can have instance homes of "roundup" or other existing python package
# names.
#
# Revision 1.6  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.5  2001/07/24 01:07:59  richard
# Added command-line arg handling to roundup-server so it's more useful
# out-of-the-box.
#
# Revision 1.4  2001/07/23 10:31:45  richard
# disabled the reloading until it can be done properly
#
# Revision 1.3  2001/07/23 08:53:44  richard
# Fixed the ROUNDUPS decl in roundup-server
# Move the installation notes to INSTALL
#
# Revision 1.2  2001/07/23 04:05:05  anthonybaxter
# actually quit if python version wrong
#
# Revision 1.1  2001/07/23 03:46:48  richard
# moving the bin files to facilitate out-of-the-boxness
#
# Revision 1.1  2001/07/22 11:15:45  richard
# More Grande Splite stuff
#
#
# vim: set filetype=python ts=4 sw=4 et si
