#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
# 
# $Id: __init__.py,v 1.18 2002-09-10 00:19:54 richard Exp $

import os, tempfile, unittest, shutil
import roundup.roundupdb
roundup.roundupdb.SENDMAILDEBUG=os.environ['SENDMAILDEBUG']=tempfile.mktemp()

# figure all the modules available
dir = os.path.split(__file__)[0]
test_mods = {}
for file in os.listdir(dir):
    if file.startswith('test_') and file.endswith('.py'):
	name = file[5:-3]
	test_mods[name] = __import__(file[:-3], globals(), locals(), [])
all_tests = test_mods.keys()

def go(tests=all_tests):
    l = []
    for name in tests:
        l.append(test_mods[name].suite())
    suite = unittest.TestSuite(l)
    runner = unittest.TextTestRunner()
    runner.run(suite)

# vim: set filetype=python ts=4 sw=4 et si
