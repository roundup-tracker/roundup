#!/usr/bin/env python

# Roundup requires Python 3.10+ as mentioned in doc\installation.txt
import sys

VERSION_NEEDED = (3, 10)

if sys.version_info < VERSION_NEEDED:
    print("Content-Type: text/plain\n")
    print("Roundup requires Python %s.%s or newer." % VERSION_NEEDED)
    sys.exit(0)
