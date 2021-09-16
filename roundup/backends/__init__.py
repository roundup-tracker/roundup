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

'''Container for the hyperdb storage backend implementations.
'''
__docformat__ = 'restructuredtext'

import sys

# These names are used to suppress import errors.
# If get_backend raises an ImportError with appropriate
# module name, have_backend quietly returns False.
# Otherwise the error is reraised.
_modules = {
    'mysql': ('MySQLdb',),
    'postgresql': ('psycopg2',),
    'sqlite': ('pysqlite', 'pysqlite2', 'sqlite3', '_sqlite3', 'sqlite'),
}

def get_backend(name):
    '''Get a specific backend by name.'''
    vars = globals()
    # if requested backend has been imported yet, return current instance
    if name in vars:
        return vars[name]
    # import the backend module
    module_name = 'back_%s' % name
    module = __import__(module_name, vars, level=1)
    vars[name] = module
    return module

def have_backend(name):
    '''Is backend "name" available?'''
    try:
        get_backend(name)
        return 1
    except ImportError as e:
        if hasattr(e, 'name'):
            modname = e.name
        else:
            modname = e.args[0][16:] if e.args[0].startswith('No module named ') else None

        # It's always ok if memorydb is not found
        if modname.endswith('back_memorydb'):
            return 0
        if modname and (modname in _modules.get(name, (name,))):
            return 0
        raise
    return 0

def list_backends():
    '''List all available backend names.

    This function has side-effect of registering backward-compatible
    globals for all available backends.

    Note: Since memorydb does not live in the backends directory, it will
    never be found in the default setup. It *can* be enabled by preloading
    test/memorydb and injecting into roundup.backends. So the normal user
    can never configure memorydb but it makes using the tests easier
    because we do not need to monkey-patch list_backends.

    '''
    l = []
    for name in 'anydbm', 'mysql', 'sqlite', 'postgresql', 'memorydb':
        if have_backend(name):
            l.append(name)
    return l

# vim: set filetype=python sts=4 sw=4 et si :
