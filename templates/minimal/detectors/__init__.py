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
#$Id: __init__.py,v 1.1.2.1 2003-09-04 23:40:16 richard Exp $

import sys, os, imp

def init(db):
    ''' execute the init functions of all the modules in this directory
    '''
    this_dir = os.path.split(__file__)[0]
    for file in os.listdir(this_dir):
        path = os.path.join(this_dir, file)
        name, ext = os.path.splitext(file)
        if name == '__init__':
            continue
        if ext == '.py':
            module = imp.load_module(name, open(path), os.path.abspath(path),
                ('.py', 'r', imp.PY_SOURCE))
            print (name, open(path), file, module)
            module.init(db)

# vim: set filetype=python ts=4 sw=4 et si
