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
# $Id: __init__.py,v 1.27 2004-04-05 23:43:03 richard Exp $

'''Container for the hyperdb storage backend implementations.

The __all__ variable is constructed containing only the backends which are
available.
'''
__docformat__ = 'restructuredtext'

__all__ = []

for backend in ['anydbm', ('mysql', 'MySQLdb'), ('bsddb', '_bsddb'),
        'bsddb3', 'sqlite', 'metakit', ('postgresql', 'psycopg')]:
    if len(backend) == 2:
        backend, backend_module = backend
    else:
        backend_module = backend
    try:
        globals()[backend] = __import__('back_%s'%backend, globals())
        __all__.append(backend)
    except ImportError, e:
        if not str(e).startswith('No module named %s'%backend_module):
            raise

# vim: set filetype=python ts=4 sw=4 et si
