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
# $Id: i18n.py,v 1.1 2001-11-21 22:57:29 jhermann Exp $

"""
RoundUp Internationalization (I18N)

To use this module, the following code should be used:

    from roundup.i18n import _
    ...
    print _("Some text that can be translated")

Note that to enable re-ordering of inserted texts in formatting strings
(which can easily happen if a sentence has to be re-ordered due to
grammatical changes), translatable formats should use named format specs:

    ... _('Index of %(classname)s') % {'classname': cn} ...

Also, this eases the job of translators since they have some context what
the dynamic portion of a message really means.

"""

# first, we try to import gettext; this probably never fails, but we make
# sure we survive this anyway
try:
    import gettext
except ImportError:
    # fall-back to dummy on errors (returning the english text)
    _ = lambda text: text
else:
    # and for now, we JUST implement the dummy in any case
    _ = lambda text: text

