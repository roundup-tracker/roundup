#!/usr/bin/env python

"""
:Author: David Goodger
:Contact: goodger@users.sourceforge.net
:Revision: $Revision: 1.1 $
:Date: $Date: 2002-03-08 23:41:46 $
:Copyright: This module has been placed in the public domain.

A minimal front-end to the Docutils Publisher.

This module takes advantage of the default values defined in `publish()`.
"""

import sys, os.path
from dps.core import publish
from dps import utils

if len(sys.argv) < 2:
    print >>sys.stderr, 'I need at least one filename'
    sys.exit(1)

reporter = utils.Reporter(2, 4)

for file in sys.argv[1:]:
    name, ext = os.path.splitext(file)
    dest = '%s.html'%name
    print >>sys.stderr, '%s -> %s'%(file, dest)
    publish(writername='html', source=file, destination=dest,
        reporter=reporter)

