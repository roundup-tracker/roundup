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
# $Id: __init__.py,v 1.29 2004-11-03 01:34:21 richard Exp $

'''Container for the hyperdb storage backend implementations.
'''
__docformat__ = 'restructuredtext'

_modules = {
    'mysql': 'MySQLdb',
    'postgresql': 'psycopg',
}

def get_backend(name):
    '''Get a specific backend by name.'''
    return __import__('back_%s'%name, globals())

def have_backend(name):
    '''Is backend "name" available?'''
    module = _modules.get(name, name)
    try:
        get_backend(name)
        return 1
    except ImportError, e:
        if not str(e).startswith('No module named %s'%module):
            raise
    return 0

def list_backends():
    '''List all available backend names.'''
    l = []
    for name in 'anydbm', 'mysql', 'sqlite', 'metakit', 'postgresql':
        if have_backend(name):
            l.append(name)
    return l

# vim: set filetype=python ts=4 sw=4 et si
