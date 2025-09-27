#!/usr/bin/env python

# Roundup requires Python 3.7+ as mentioned in doc\installation.txt
from __future__ import print_function
import sys

VERSION_NEEDED = (3, 7)

if sys.version_info < VERSION_NEEDED:
    print("Content-Type: text/plain\n")
    print("Roundup requires Python %s.%s or newer." % VERSION_NEEDED)
    sys.exit(0)
