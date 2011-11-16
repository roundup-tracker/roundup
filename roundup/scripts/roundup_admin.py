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

"""Command-line script stub that calls the roundup.admin functions.
"""
__docformat__ = 'restructuredtext'

# python version check
from roundup import version_check

# import the admin tool guts and make it go
from roundup.admin import AdminTool
from roundup.i18n import _

import sys

def run():
    # time out after a minute if we can
    import socket
    if hasattr(socket, 'setdefaulttimeout'):
        socket.setdefaulttimeout(60)
    tool = AdminTool()
    sys.exit(tool.main())

if __name__ == '__main__':
    run()

# vim: set filetype=python ts=4 sw=4 et si
