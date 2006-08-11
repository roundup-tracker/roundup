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
# $Id: __init__.py,v 1.5 2006-08-11 00:04:29 richard Exp $
#
__version__='1.1'

import os
# figure where ZRoundup is installed
here = None
if os.environ.has_key('INSTANCE_HOME'):
    here = os.environ['INSTANCE_HOME']
    path = os.path.join(here, 'Products', 'ZRoundup')
    if not os.path.exists(path):
        path = os.path.join(here, 'lib', 'python', 'Products', 'ZRoundup')
        if not os.path.exists(path):
            here = None
if here is None:
    from __main__ import here
    path = os.path.join(here, 'Products', 'ZRoundup')
    if not os.path.exists(path):
        path = os.path.join(here, 'lib', 'python', 'Products', 'ZRoundup')
        if not os.path.exists(path):
            raise ValueError, "Can't determine where ZRoundup is installed"

# product initialisation
from ZRoundup import ZRoundup, manage_addZRoundupForm, manage_addZRoundup
def initialize(context):
    context.registerClass(
        ZRoundup,
        meta_type = 'Z Roundup',
        constructors = (
            manage_addZRoundupForm, manage_addZRoundup
        )
    )

# set up the icon
from ImageFile import ImageFile
misc_ = {
    'icon': ImageFile('icons/tick_symbol.gif', path), 
}


# vim: set filetype=python ts=4 sw=4 et si
