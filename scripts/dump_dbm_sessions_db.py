#! /usr/bin/env python3
"""Usage: dump_dbm_sessions_db.py [filename]

Simple script to dump the otks and sessions dbm databases.  Dumps
sessions db in current directory if no argument is given.

Dump format:

   key: <timestamp> data

where <timestamp> is the human readable __timestamp decoded from the
data object. Data object is dumped in json format. With pretty print

   key:
     <timestamp>
       {
          key: val,
          ...
       }

if data is not a python object, print will be key: data or
   key:
     data

if pretty printed.
"""

import argparse
import dbm
import json
import marshal
import os
import sys
from datetime import datetime


def indent(text, amount, ch=" "):
  """ Found at: https://stackoverflow.com/a/8348914
  """
  padding = amount * ch
  return ''.join(padding+line for line in text.splitlines(True))

def print_marshal(k):
  d = marshal.loads(db[k])
  try:
    t = datetime.fromtimestamp(d['__timestamp'])
  except (KeyError, TypeError):
    # TypeError raised if marshalled data is not a dict (list, tuple etc)
    t = "no_timestamp"
  if args.pretty:
    print("%s:\n  %s\n%s"%(k, t, indent(json.dumps(
      d, sort_keys=True, indent=4), 4)))
  else:
    print("%s: %s %s"%(k, t, d))

def print_raw(k):
  if args.pretty:
    print("%s:\n  %s"%(k, db[k]))
  else:
    print("%s: %s"%(k, db[k]))

parser = argparse.ArgumentParser(
  description='Dump DBM files used by Roundup in storage order.')
parser.add_argument('-k', '--key', action="append",
    help='dump the entry for a key, can be used multiple times.')
parser.add_argument('-K', '--keysonly', action='store_true',
    help='print the database keys, sorted in byte order.')
parser.add_argument('-p', '--pretty', action='store_true',
    help='pretty print the output rather than printing on one line.')
parser.add_argument('file', nargs='?',
                    help='file to be dumped ("sessions" if not provided)')
args = parser.parse_args()

if args.file:
  file = args.file
else:
  file="sessions"

try:
   db = dbm.open(file)
except Exception as e:
  print("Unable to open database for %s: %s"%(file, e))
  try:
    os.stat(file)
    print("  perhaps file is invalid or was created with a different version of Python?")
  except OSError:
    # the file does exist on disk.
    pass
  sys.exit(1)

if args.keysonly:
  for k in sorted(db.keys()):
    print("%s"%k)
  sys.exit(0)

if args.key:
  for k in args.key:
    try:
      print_marshal(k)
    except (ValueError):
      print_raw(k)
  sys.exit(0)

k = db.firstkey()
while k is not None:
  try:
    print_marshal(k)
  except (ValueError):  # ValueError marshal.loads failed
    print_raw(k)

  k = db.nextkey(k)
