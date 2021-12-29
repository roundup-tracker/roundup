#! /usr/bin/env python3
"""Usage: dump_dbm_sessions_db.py [filename]

Simple script to dump the otks and sessions dbm databases.  Dumps
sessions db in current directory if no argument is given.

Dump format:

   key: <timestamp> data

where <timestamp> is the human readable __timestamp decoded from the
data object.

"""

import dbm, marshal, sys
from datetime import datetime

try:
  file = sys.argv[1]
except IndexError:
  file="sessions"

try:
   db = dbm.open(file)
except Exception:
   print("Unable to open database: %s"%file)
   exit(1)

k = db.firstkey()
while k is not None:
    d = marshal.loads(db[k])
    t = datetime.fromtimestamp(d['__timestamp'])
    print("%s: %s %s"%(k, t, d))
    k = db.nextkey(k)
