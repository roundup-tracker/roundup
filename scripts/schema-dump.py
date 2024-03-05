#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Use recently documented XML-RPC API to dump
Roundup data schema in human readable form.

Works with demo tracker using:

   http://admin:admin@localhost:8917/demo/xmlrpc

Future development may cover:
[ ] unreadable dump formats
[ ] access to local database
[ ] lossless dump/restore cycle
[ ] data dump and filtering with preserved

Works in Python 2 as well.
"""
from __future__ import print_function

__license__ = "Public Domain"
__version__ = "1.1"
__authors__ = [
    "anatoly techtonik <techtonik@gmail.com>"
    "John Rouillard <rouilj@users.sourceforge.net>",
]

import os
import pprint
import sys
import textwrap

try:
    import urllib.parse as url_parser  # python 3
except ImportError:
    import urlparse as url_parser  # python 2

from argparse import ArgumentParser

from roundup.anypy import xmlrpc_

sname = os.path.basename(sys.argv[0])
usage = """\
usage: %s [options] URL

URL is XML-RPC endpoint for your tracker, such as:

    http://localhost:8917/demo/xmlrpc

options:
  --pprint     (default)
  --json
  --yaml
  --raw

  -h --help
  --version
""" % sname


def format_pprint(var):
    return pprint.pformat(var)


def format_json(var):
    jout = pprint.pformat(var)
    jout = jout.replace('"', "\\'")  # " to \'
    jout = jout.replace("'", '"')    # ' to "
    jout = jout.replace('\\"', "'")  # \" to '
    return jout


def format_yaml(var):
    out = pprint.pformat(var)
    out = out.replace('{', ' ')
    out = out.replace('}', '')
    out = textwrap.dedent(out)
    out = out.replace("'", '')
    out = out.replace(' [[', '\n  [')
    out = out.replace(']]', ']')
    out = out.replace('],', '')
    out = out.replace(']', '')
    out2 = []
    for line in out.splitlines():
        if '[' in line:
            line = '  ' + line.lstrip(' [')
            line = line.replace('>', '')
            line = line.replace('roundup.hyperdb.', '')
            # expandtabs(16) with limit=1
            n, v = line.split(', <')
            if len(n) > 14:
                indent = 0
            else:
                indent = 14 - len(n)
            line = line.replace(', <', ': '+' '*indent)
        line.split(",")
        out2.append(line)
    out = '\n'.join(out2)
    return out


class SpecialTransport():
    """Mixin for http/https transports to implement new send_content with
       CSRF prevention headers to both of them.
    """
    def send_content(self, connection, request_body):
        connection.putheader("Referer", "%s://%s%s%s/" % (
            self.components.scheme,
            self.components.hostname,
            ':' + str(self.components.port) if self.components.port else '',
            self.components.path))
        connection.putheader("Origin", "%s://%s%s" % (
            self.components.scheme, self.components.hostname,
            ':' + str(self.components.port) if self.components.port else ''))
        connection.putheader("X-Requested-With", "XMLHttpRequest")

        connection.putheader("Content-Type", "text/xml")
        connection.putheader("Content-Length", str(len(request_body)))
        connection.endheaders()
        if request_body:
            connection.send(request_body)


class SpecialHttpTransport(SpecialTransport, xmlrpc_.client.Transport,
                           object):
    """SpecialTransport must be first to use its send_content. Explicit
       object inheritance required for python2 apparently."""
    def __init__(self, url):
        self.components = url_parser.urlparse(url)
        # works both python2 (with object inheritance) and python3
        super(SpecialHttpTransport, self).__init__(self)


class SpecialHttpsTransport(SpecialTransport, xmlrpc_.client.SafeTransport,
                            object):
    """SpecialTransport must be first to use its send_content. Explicit
       object inheritance required for python2 apparently."""
    def __init__(self, url):
        self.components = url_parser.urlparse(url)
        # works both python2 (with object inheritance) and python3
        super(SpecialHttpsTransport, self).__init__(self)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("url", nargs=1)
    parser.add_argument("--raw", action='store_true')
    parser.add_argument("--yaml", action='store_true')
    parser.add_argument("--json", action='store_true')
    parser.add_argument("-v", "--version", action='store_true')
    args = parser.parse_args()
    if args.version:
        sys.exit(sname + " " + __version__)

    if args.url[0].lower().startswith('https:'):
        transport = SpecialHttpsTransport
    else:
        transport = SpecialHttpTransport

    roundup_server = xmlrpc_.client.ServerProxy(
        args.url[0],
        transport=transport(args.url[0]),
        verbose=False,
        allow_none=True)

    schema = roundup_server.schema()
    if args.raw:
        print(str(schema))
    elif args.yaml:
        print(format_yaml(schema))
    elif args.json:
        print(format_json(schema))
    else:
        print(format_pprint(schema))

    print("")
