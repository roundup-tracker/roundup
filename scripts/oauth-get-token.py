#!/usr/bin/python3

import requests
import time
import sys
import webbrowser
import ssl

from urllib.parse import urlparse, urlencode, parse_qs
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from http.server import HTTPServer, BaseHTTPRequestHandler

class Request_Token:

    def __init__ (self, args):
        self.args    = args
        self.session = requests.session ()
        self.url     = '/'.join ((args.url.rstrip ('/'), args.tenant))
        self.url     = '/'.join ((self.url, 'oauth2/v2.0'))
        self.state   = None
        self.use_tls = self.args.use_tls
        if self.use_tls is None:
            self.use_tls = self.args.redirect_uri.startswith ('https')
    # end def __init__

    def check_err (self, r):
        if not 200 <= r.status_code <= 299:
            raise RuntimeError \
                ( 'Invalid result: %s: %s\n    %s'
                % (r.status_code, r.reason, r.text)
                )
    # end def check_err

    def get_url (self, path, params):
        url = ('/'.join ((self.url, path)))
        url = url + '?' + urlencode (params)
        return url
    # end def get_url

    def post_or_put (self, method, path, data = None, json = None):
        d = {}
        if data:
            d.update (data = data)
        if json:
            d.update (json = json)
        url = ('/'.join ((self.url, path)))
        r = method (url, **d)
        self.check_err (r)
        return r.json ()
    # end def post_or_put

    def post (self, path, data = None, json = None):
        return self.post_or_put (self.session.post, path, data, json)
    # end def post

    def authcode_callback (self, handler):
        msg = ['']
        self.request_received = False
        r = urlparse (handler.path)
        if r.query:
            q = parse_qs (r.query)
            if 'state' in q:
                state = q ['state'][0]
                if state != self.state:
                    msg.append \
                        ( 'State did not match: expect "%s" got "%s"'
                        % (self.state, state)
                        )
                elif 'code' not in q:
                    msg.append ('Got no code')
                else:
                    with open ('oauth/authcode', 'w') as f:
                        f.write (q ['code'][0])
                    msg.append ('Wrote code to oauth/authcode')
                    self.request_received = True
            else:
                msg.append ('No state and no code')
        return 200, '\n'.join (msg).encode ('utf-8')
    # end def authcode_callback

    def request_authcode (self):
        with open ('oauth/client_id', 'r') as f:
            client_id = f.read ()
        self.state = 'authcode' + str (time.time ())
        params = dict \
            ( client_id     = client_id
            , response_type = 'code'
            , response_mode = 'query'
            , state         = self.state
            , redirect_uri  = self.args.redirect_uri
            , scope         = ' '.join
                (( 'https://outlook.office.com/IMAP.AccessAsUser.All'
                ,  'https://outlook.office.com/User.Read'
                ,  'offline_access'
                ))
            )
        url = self.get_url ('authorize', params)
        print (url)
        if self.args.webbrowser:
            browser = webbrowser.get (self.args.browser)
            browser.open_new_tab (url)
        if self.args.run_https_server:
            self.https_server ()
        if self.args.request_tokens:
            self.request_token ()
    # end def request_authcode

    def request_token (self):
        with open ('oauth/client_id', 'r') as f:
            client_id = f.read ()
        with open ('oauth/client_secret', 'r') as f:
            client_secret = f.read ().strip ()
        with open ('oauth/authcode', 'r') as f:
            authcode = f.read ().strip ()
        params = dict \
            ( client_id     = client_id
            , code          = authcode
            , client_secret = client_secret
            , redirect_uri  = self.args.redirect_uri
            , grant_type    = 'authorization_code'
            # Only a single scope parameter is allowed here
            , scope         = ' '.join
                (( 'https://outlook.office.com/User.Read'
                 ,
                ))
            )
        result = self.post ('token', data = params)
        with open ('oauth/refresh_token', 'w') as f:
            f.write (result ['refresh_token'])
        with open ('oauth/access_token', 'w') as f:
            f.write (result ['access_token'])
    # end def request_token

    def https_server (self):
        self.request_received = False
        class RQ_Handler (BaseHTTPRequestHandler):
            token_handler = self

            def do_GET (self):
                self.close_connection = True
                code, msg = self.token_handler.authcode_callback (self)
                self.send_response (code)
                self.send_header ('Content-Type', 'text/plain')
                self.end_headers ()
                self.wfile.write (msg)
                self.wfile.flush ()

        port  = self.args.https_server_port
        httpd = HTTPServer (('localhost', port), RQ_Handler)

        if self.use_tls:
            # note this opens a server on localhost. Only
            # a process on the same host can get the credentials.
            # Even unencrypted (http://) url is fine as the credentials
            # will be saved in clear text on disk for use. So a
            # compromised local host will still get the credentials.
            context = ssl.SSLContext(ssl_version=ssl.PROTOCOL_TLS_SERVER)

            # This should not be needed as PROTOCOL_TLS_SERVER disables
            # unsafe protocols. Uses Python 3.10+ setting ssl.TLSVersion....
            # context.minimum_version = ssl.TLSVersion.TLSv1_2
            # for previous Python versions 3.6+ maybe:
            #   ssl.PROTOCOL_TLSv1_2
            # would work?

            context.load_cert_chain \
                ( keyfile  = self.args.keyfile
                , certfile = self.args.certfile
                )
            httpd.socket = context.wrap_socket \
                (httpd.socket, server_side = True)
        while not self.request_received:
            httpd.handle_request ()
    # end def https_server

# end class Request_Token

epilog = """\
Retrieving the necessary refresh_token and access_token credentials
using this script. This asumes you have an email account (plus the
password) to be used for mail retrieval. And you have registered an
application in the cloud for this process. The registering of an
application will give you an application id (also called client id) and
a tenant in UUID format.

First define the necessary TENANT variable:

    TENANT=XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX

You need to create a directory named 'oauth' (if not yet existing) and
put the client id (also called application id) into the file
'oauth/client_id' and the corresponding secret into the file
'oauth/client_secret'.

By default calling the script with no arguments, the whole process is
automatic. Note that the default TLS key used for the built-in server is
a self-signed certificate which is automatically created on Debian-based
(including Ubuntu) Linux distributions. But the key-file is not readable
for everyone, you need to be in the group 'ssl-cert' or need otherwise
elevated privileges. If you're using a http (as opposed to https)
redirect URI, of course no TLS files are needed. You may want to specify
the tenant explicitly using:

 ./oauth-get-token.py -t $TENANT

Specifying the tenant explicitly will select the customized company
login form directly.

The automatic process works as follows:
- First the authorization URL is constructed and pushed to a local
  browser. By default the default browser on that machine is used, you
  can specify a different browser with the -b/--browser option.
  This will show a login form where you should be able to select the
  user to log in with. Log in with the username (the email address) and
  password for that user.
- A web-server is started on the given port. When you fill out the
  authentication form pushed to the browser, the last step is a redirect
  to an URL that calls back to this webserver. The necessary
  authentication code is transmitted in a query parameter. The code is
  stored into the file 'oauth/authcode'. Using the authcode, the
  refresh_token and access_token are requested and stored in the oauth
  directory.

These steps can be broken down into individual steps by options
disabling one of the steps:
- The push to the webserver can be disabled with the option
  -w/--dont-push-to-webbrowser -- in that case the URL is printed on
  standard output and must be pasted into the URL input field of a
  browser. It is typically a good idea to use a browser that is
  currently not logged into the company network.
- The start of the webserver can be disabled with the option
  -s/--dont-run-https-server -- when called with that option no
  webserver is started. You get a redirect to a non-existing page. The
  error-message is something like:

    This site can’t be reached

  Copy the URL from the browser into the file 'oauth/authcode'. The URL
  has paramters. We're interested in the 'code' parameter, a very long
  string. Edit the file so that only that string (without the 'code='
  part) is in the file.
- Requesting the tokens can be disabled with the option
  -n/--dont-request-tokens -- if this option is given, after receiving
  the redirect from the webserver the authentication code is written to
  the file 'oauth/authcode' but no token request is started.

If you have either disabled the webserver or the token request, the
token can be requested (using the file 'oauth/authcode' constructed by
hand as described above or written by the webserver) with the
-T/--request-token option:

 ./oauth-get-token.py [-t $TENANT] -T

If successful this will create the 'oauth/access_token' and
'oauth/refresh_token' files. Note that the authentication code has a
limited lifetime.

"""

def main ():
    cmd = ArgumentParser \
        (epilog=epilog, formatter_class=RawDescriptionHelpFormatter)
    cmd.add_argument \
        ( '-b', '--browser'
        , help    = "Use non-default browser"
        )
    cmd.add_argument \
        ( '--certfile'
        , help    = "TLS certificate file, default=%(default)s"
        , default = "/etc/ssl/certs/ssl-cert-snakeoil.pem"
        )
    cmd.add_argument \
        ( '--keyfile'
        , help    = "TLS key file, default=%(default)s"
        , default = "/etc/ssl/private/ssl-cert-snakeoil.key"
        )
    cmd.add_argument \
        ( '-n', '--dont-request-tokens'
        , dest    = 'request_tokens'
        , help    = "Do not request tokens, just write authcode"
        , action  = 'store_false'
        , default = True
        )
    cmd.add_argument \
        ( '-p', '--https-server-port'
        , type    = int
        , help    = "Port for https server to listen, default=%(default)s"
                    " see also -r option, ports must (usually) match."
        , default = 8181
        )
    cmd.add_argument \
        ( '-r', '--redirect-uri'
        , help    = "Redirect URI, default=%(default)s"
        , default = 'https://localhost:8181'
        )
    cmd.add_argument \
        ( '-s', '--dont-run-https-server'
        , dest    = 'run_https_server'
        , help    = "Run https server to wait for connection of browser "
                    "to transmit auth code via GET request"
        , action  = 'store_false'
        , default = True
        )
    cmd.add_argument \
        ( '-T', '--request-token'
        , help    = "Run only the token-request step"
        , action  = 'store_true'
        )
    cmd.add_argument \
        ( '-t', '--tenant'
        , help    = "Tenant part of url, default=%(default)s"
        , default = 'organizations'
        )
    cmd.add_argument \
        ( '--use-tls'
        , help    = "Enforce use of TLS even if the redirect uri is http"
        , action  = 'store_true'
        , default = None
        )
    cmd.add_argument \
        ( '--no-use-tls', '--dont-use-tls'
        , help    = "Disable use of TLS even if the redirect uri is https"
        , dest    = 'use_tls'
        , action  = 'store_false'
        , default = None
        )
    cmd.add_argument \
        ( '-u', '--url'
        , help    = "Base url for requests, default=%(default)s"
        , default = 'https://login.microsoftonline.com'
        )
    cmd.add_argument \
        ( '-w', '--dont-push-to-webbrowser'
        , dest    = 'webbrowser'
        , help    = "Do not push authcode url into the browser"
        , action  = 'store_false'
        , default = True
        )
    args = cmd.parse_args ()
    rt = Request_Token (args)
    if args.request_token:
        rt.request_token ()
    else:
        rt.request_authcode ()
# end def main

if __name__ == '__main__':
    main ()
