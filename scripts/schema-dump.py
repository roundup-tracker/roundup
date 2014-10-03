#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Use recently documented XML-RPC API to dump
Roundup data schema in human readable form.

Future development may cover:
[ ] unreadable dump formats
[ ] access to local database
[ ] lossless dump/restore cycle
[ ] data dump and filtering with preserved 
"""
__license__ = "Public Domain"
__version__ = "1.0"
__authors__ = [
    "anatoly techtonik <techtonik@gmail.com>"
]

import os
import sys
import xmlrpclib
import pprint
import textwrap
from optparse import OptionParser

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
 
if __name__ == "__main__":
    if len(sys.argv) < 2 or "-h" in sys.argv or "--help" in sys.argv:
        sys.exit(usage)
    if "--version" in sys.argv:
        sys.exit(sname + " " + __version__)

    parser = OptionParser()
    parser.add_option("--raw", action='store_true')
    parser.add_option("--yaml", action='store_true')
    parser.add_option("--json", action='store_true')
    (options, args) = parser.parse_args()

    url = args[0]
    roundup_server = xmlrpclib.ServerProxy(url, allow_none=True)
    schema = roundup_server.schema()
    if options.raw:
        print(str(schema))
    elif options.yaml:
        print(format_yaml(schema))
    elif options.json:
        print(format_json(schema))
    else:
        print(format_pprint(schema))

    print("")
