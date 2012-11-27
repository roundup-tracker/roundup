#!/usr/bin/env python

# Roundup requires Python 2.5+ as mentioned in doc\installation.txt
VERSION_NEEDED = (2,5)

import sys
if sys.version_info < VERSION_NEEDED:
    print "Content-Type: text/plain\n"
    print "Roundup requires Python %s.%s or newer." % VERSION_NEEDED
    sys.exit(0)
