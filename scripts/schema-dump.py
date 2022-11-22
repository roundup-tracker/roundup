#!/usr/bin/env python3
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
from __future__ import print_function

__license__ = "Public Domain"
__version__ = "1.0"
__authors__ = [
    "anatoly techtonik <techtonik@gmail.com>"
]

import os
import sys
from roundup.anypy import xmlrpc_
import pprint
import textwrap
from argparse import ArgumentParser

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
    parser = ArgumentParser()
    parser.add_argument("url", nargs=1)
    parser.add_argument("--raw", action='store_true')
    parser.add_argument("--yaml", action='store_true')
    parser.add_argument("--json", action='store_true')
    parser.add_argument("-v", "--version", action='store_true')
    args = parser.parse_args()
    if args.version:
        sys.exit(sname + " " + __version__)

    roundup_server = xmlrpc_.client.ServerProxy(args.url[0], allow_none=True)
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
