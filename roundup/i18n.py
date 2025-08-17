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

import gettext as gettext_module
import os
import sys

from roundup import msgfmt
from roundup.anypy.strings import is_us

# List of directories for mo file search (see SF bug 1219689)
LOCALE_DIRS = [
    gettext_module._default_localedir,
]
# compute mo location relative to roundup installation directory
# (prefix/lib/python/site-packages/roundup/msgfmt.py on posix systems,
# prefix/lib/site-packages/roundup/msgfmt.py on windows).
# locale root is prefix/share/locale.
if os.name == "nt":
    _mo_path = [".."] * 4 + ["share", "locale"]
    root_prefix_chars = 3   # remove c:\ or other drive letter
else:
    _mo_path = [".."] * 5 + ["share", "locale"]
    root_prefix_chars = 1   # remove /

_mo_path = os.path.normpath(os.path.join(msgfmt.__file__, *_mo_path))
if _mo_path not in LOCALE_DIRS:
    LOCALE_DIRS.append(_mo_path)
del _mo_path

# __file__ should be something like:
#    /usr/local/lib/python3.10/site-packages/roundup/i18n.py
# os.prefix should be /usr, /usr/local or root of virtualenv
#    strip leading / to make os.path.join work right.
path = __file__

for _N in 1, 2:  # remove roundup/i18n.py from path
    path = os.path.dirname(path)
    # path is /usr/local/lib/python3.10/site-packages

_ldir = os.path.join(path, sys.prefix[root_prefix_chars:], 'share', 'locale')
if os.path.isdir(_ldir):
    LOCALE_DIRS.append(_ldir)

# try other places locale files are hidden on install
_ldir = os.path.join(path, sys.prefix[root_prefix_chars:], 'local', 'share', 'locale')
if os.path.isdir(_ldir):
    LOCALE_DIRS.append(_ldir)

try:
    _ldir = os.path.join(path, sys.base_prefix[root_prefix_chars:], 'local', 'share', 'locale')
    if os.path.isdir(_ldir):
        LOCALE_DIRS.append(_ldir)
    _ldir = os.path.join(path, sys.base_prefix[root_prefix_chars:], 'share', 'locale')
    if os.path.isdir(_ldir):
        LOCALE_DIRS.append(_ldir)
except AttributeError:
    pass  # no base_prefix on 2.7

# make -C locale local_install - locale directory in roundup source tree
_ldir = os.path.join(path, 'locale', 'locale')
if os.path.isdir(_ldir):
    LOCALE_DIRS.append(_ldir)
del _ldir

# Roundup text domain
DOMAIN = "roundup"

RoundupNullTranslations = gettext_module.NullTranslations
RoundupTranslations = gettext_module.GNUTranslations


def find_locales(language=None):
    """Return normalized list of locale names to try for given language

    Argument 'language' may be a single language code or a list of codes.
    If 'language' is omitted or None, use locale settings in OS environment.

    """
    # body of this function is borrowed from gettext_module.find()
    if language is None:
        languages = []
        for envar in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
            val = os.environ.get(envar)
            if val:
                languages = val.split(':')
                break
    elif is_us(language):
        languages = [language]
    else:
        # 'language' must be iterable
        languages = language
    # now normalize and expand the languages
    nelangs = []
    for lang in languages:
        for nelang in gettext_module._expand_lang(lang):
            if nelang not in nelangs:
                nelangs.append(nelang)
    return nelangs


def get_mofile(languages, localedir, domain=None):
    """Return the first of .mo files found in localedir for languages

    Parameters:
        languages:
            list of locale names to try
        localedir:
            path to directory containing locale files.
            Usually this is either gettext_module._default_localedir
            or 'locale' subdirectory in the tracker home.
        domain:
            optional name of messages domain.
            If omitted or None, work with simplified
            locale directory, as used in tracker homes:
            message catalogs are kept in files locale.po
            instead of locale/LC_MESSAGES/domain.po

    Return the path of the first .mo file found.
    If nothing found, return None.

    Automatically compile .po files if necessary.

    """
    for locale in languages:
        if locale == "C":
            break
        basename = os.path.join(localedir, locale, "LC_MESSAGES", domain) if \
            domain else os.path.join(localedir, locale)
        # look for message catalog files, check timestamps
        mofile = basename + ".mo"
        motime = os.path.getmtime(mofile) if os.path.isfile(mofile) else 0
        pofile = basename + ".po"
        potime = os.path.getmtime(pofile) if os.path.isfile(pofile) else 0

        # see what we've found
        if motime < potime:
            # compile
            mo = msgfmt.Msgfmt(pofile).get()
            with open(mofile, 'wb') as m:
                m.write(mo)
        elif motime == 0:
            # no files found - proceed to the next locale name
            continue
        # .mo file found or made
        return mofile
    return None


def get_translation(language=None, tracker_home=None,
                    translation_class=RoundupTranslations,
                    null_translation_class=RoundupNullTranslations):
    """Return Translation object for given language and domain

    Argument 'language' may be a single language code or a list of codes.
    If 'language' is omitted or None, use locale settings in OS environment.

    Arguments 'translation_class' and 'null_translation_class'
    specify the classes that are instantiated for existing
    and non-existing translations, respectively.

    """
    mofiles = []
    # locale directory paths
    tracker_locale = os.path.join(tracker_home, "locale") if \
        tracker_home is not None else None

    # get the list of locales
    locales = find_locales(language)
    # add mofiles found in the tracker, then in the system locale directory
    if tracker_locale:
        mofiles.append(get_mofile(locales, tracker_locale))
    mofiles.extend([get_mofile(locales, system_locale, DOMAIN)
               for system_locale in LOCALE_DIRS])

    # we want to fall back to english unless english is selected language
    if "en" not in locales:
        locales = find_locales("en")
        # add mofiles found in the tracker, then in the system locale directory
        if tracker_locale:
            mofiles.append(get_mofile(locales, tracker_locale))
        mofiles.extend([get_mofile(locales, system_locale, DOMAIN)
                         for system_locale in LOCALE_DIRS])
    # filter out elements that are not found
    mofiles = filter(None, mofiles)
    translator = None
    for mofile in mofiles:
        try:
            with open(mofile, "rb") as mo:
                if translator is None:
                    translator = translation_class(mo)
                    # the .mo file this translator loaded from
                    translator._file = mofile
                else:
                    # note: current implementation of gettext_module
                    #   always adds fallback to the end of the fallback chain.
                    fallback = translation_class(mo)
                    fallback._file = mofile
                    translator.add_fallback(fallback)
        except IOError:  # noqa: PERF203
            # ignore unreadable .mo files
            pass
    if translator is None:
        translator = null_translation_class()
    return translator


# static translations object
translation = get_translation()
# static translation functions
_ = gettext = translation.gettext
try:
    # Python 2.
    ugettext = translation.ugettext
except AttributeError:
    # Python 3.
    ugettext = translation.gettext
ngettext = translation.ngettext
try:
    # Python 2.
    ungettext = translation.ungettext
except AttributeError:
    # Python 3.
    ungettext = translation.ngettext

# vim: set filetype=python sts=4 sw=4 et si :
