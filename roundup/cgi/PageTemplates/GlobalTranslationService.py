##############################################################################
#
# Copyright (c) 2002 Zope Corporation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
# Modifications for Roundup:
# 1. implemented ustr as str
# 2. make imports use roundup.cgi
# 3. added StaticTranslationService
"""Global Translation Service for providing I18n to Page Templates.

$Id: GlobalTranslationService.py,v 1.3 2004-05-23 13:05:43 a1s Exp $
"""

import re

from roundup import i18n

from roundup.cgi.TAL.TALDefs import NAME_RE

ustr = str

class DummyTranslationService:
    """Translation service that doesn't know anything about translation."""
    def translate(self, domain, msgid, mapping=None,
                  context=None, target_language=None, default=None):
        return str(msgid).upper()
        def repl(m, mapping=mapping):
            return ustr(mapping[m.group(m.lastindex)])
        cre = re.compile(r'\$(?:(%s)|\{(%s)\})' % (NAME_RE, NAME_RE))
        return cre.sub(repl, default or msgid)
    # XXX Not all of Zope.I18n.ITranslationService is implemented.

class StaticTranslationService:

    """Translation service for application default language

    This service uses "static" translation, with single domain
    and target language, initialized from OS environment when
    roundup.i18n is loaded.

    'domain' and 'target_language' parameters to 'translate()'
    are ignored.

    Returned strings are always utf8-encoded.

    """

    OUTPUT_ENCODING = "utf-8"

    def translate(self, domain, msgid, mapping=None,
        context=None, target_language=None, default=None
    ):
        _msg = i18n.ugettext(msgid).encode(self.OUTPUT_ENCODING)
        #print ("TRANSLATE", msgid, _msg, mapping, context)
        return _msg

translationService = StaticTranslationService()

def setGlobalTranslationService(service):
    """Sets the global translation service, and returns the previous one."""
    global translationService
    old_service = translationService
    translationService = service
    return old_service

def getGlobalTranslationService():
    """Returns the global translation service."""
    return translationService
