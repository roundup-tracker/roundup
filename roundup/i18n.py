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
# $Id: i18n.py,v 1.7 2004-05-22 14:40:17 a1s Exp $

"""
RoundUp Internationalization (I18N)

To use this module, the following code should be used::

    from roundup.i18n import _
    ...
    print _("Some text that can be translated")

Note that to enable re-ordering of inserted texts in formatting strings
(which can easily happen if a sentence has to be re-ordered due to
grammatical changes), translatable formats should use named format specs::

    ... _('Index of %(classname)s') % {'classname': cn} ...

Also, this eases the job of translators since they have some context what
the dynamic portion of a message really means.
"""
__docformat__ = 'restructuredtext'

import errno

# Roundup text domain
DOMAIN = "roundup"

# first, we try to import gettext; this probably never fails, but we make
# sure we survive this anyway
try:
    import gettext as gettext_module
except ImportError:
    gettext_module = None

# use or emulate features of gettext_module
if not gettext_module:
    # no gettext engine available.
    # implement emulation for Translations class
    # and translation() function
    class RoundupNullTranslations:
        """Dummy Translations class

        Only methods used by Roundup are implemented.

        """
        def add_fallback(self, fallback):
            pass
        def gettext(self, text):
            return text
        def ugettext(self, text):
            return unicode(text)
        def ngettext(self, singular, plural, count):
            if count == 1: return singular
            return plural
        def ungettext(self, singular, plural, count):
            return unicode(self.ngettext(singular, plural, count))

    RoundupTranslations = RoundupNullTranslations

    def translation(domain, localedir=None, languages=None, class_=None):
        """Always raise IOError (no message catalogs available)"""
        raise IOError(errno.ENOENT,
            "No translation file found for domain", domain)

elif not hasattr(gettext_module.GNUTranslations, "ngettext"):
    # prior to 2.3, there was no plural forms.  mix simple emulation in
    class PluralFormsMixIn:
        def ngettext(self, singular, plural, count):
            if count == 1:
                _msg = singular
            else:
                _msg = plural
            return self.gettext(_msg)
        def ngettext(self, singular, plural, count):
            if count == 1:
                _msg = singular
            else:
                _msg = plural
            return self.gettext(_msg)
    class RoundupNullTranslations(
        gettext_module.NullTranslations, PluralFormsMixIn
    ):
        pass
    class RoundupTranslations(
        gettext_module.GNUTranslations, PluralFormsMixIn
    ):
        pass
    # lookup function is available
    translation = gettext_module.translation
else:
    # gettext_module has everything needed
    RoundupNullTranslations = gettext_module.NullTranslations
    RoundupTranslations = gettext_module.GNUTranslations
    translation = gettext_module.translation


def get_translation(language=None, domain=DOMAIN):
    """Return Translation object for given language and domain"""
    if language:
        _languages = [language]
    else:
        # use OS environment
        _languages = None
    # except for english ("en") language, add english fallback if available
    try:
        _fallback = translation(domain=domain, languages=["en"],
            class_=RoundupTranslations)
    except IOError:
        # no .mo files found
        _fallback = None
    # get the translation
    try:
        _translation = translation(domain=domain, languages=_languages,
            class_=RoundupTranslations)
    except IOError:
        _translation = None
    # see what's found
    if _translation and _fallback:
        _translation.add_fallback(_fallback)
    elif _fallback:
        _translation = _fallback
    elif not _translation:
        _translation = RoundupNullTranslations()
    return _translation

# static translations object
translation = get_translation()
# static translation functions
_ = gettext = translation.gettext
ugettext = translation.ugettext
ngettext = translation.ngettext
ungettext = translation.ungettext

# vim: set filetype=python sts=4 sw=4 et si
