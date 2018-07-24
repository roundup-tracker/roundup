#! /usr/bin/env python
'''
migrate-queries <instance-home> [<instance-home> *]

Migrate old queries in the specified instances to Roundup 0.6.0+ by
removing the leading ? from their URLs. 0.6.0+ queries do not carry a
leading ?; it is added by the 0.6.0 templating, so old queries lead
to query URLs with a double leading ?? and a consequent 404 Not Found.
'''
from __future__ import print_function
__author__ = 'James Kew <jkew@mediabright.co.uk>'

import sys
import roundup.instance

if len(sys.argv) == 1:
    print(__doc__)
    sys.exit(1)

# Iterate over all instance homes specified in argv.
for home in sys.argv[1:]:
    # Do some basic exception handling to catch bad arguments.
    try:
        instance = roundup.instance.open(home)
    except:
        print('Cannot open instance home directory %s!' % home)
        continue

    db = instance.open('admin')
    db.tx_Source = "cli"

    print('Migrating active queries in %s (%s):'%(
        instance.config.TRACKER_NAME, home))
    for query in db.query.list():
        url = db.query.get(query, 'url')
        if url[0] == '?':
            url = url[1:]
            print('  Migrating query%s (%s)'%(query,
                db.query.get(query, 'name')))
            db.query.set(query, url=url)

    db.commit()
    db.close()

