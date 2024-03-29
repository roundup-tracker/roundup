# TranslationService for Roundup templates
#
# This module is free software, you may redistribute it
# and/or modify under the same terms as Python.
#
# This module provides National Language Support
# for Roundup templating - much like roundup.i18n
# module for Roundup command line interface.
# The only difference is that translator objects
# returned by get_translation() have one additional
# method which is used by TAL engines:
#
#   translate(domain, msgid, mapping, context, target_language, default)
#

from roundup import i18n
from roundup.cgi.PageTemplates import Expressions, PathIterator, TALES
from roundup.cgi.TAL import TALInterpreter
from roundup.anypy.strings import us2u, u2s

### Translation classes


class TranslationServiceMixin:

    def translate(self, domain, msgid, mapping=None,
                  context=None, target_language=None, default=None):
        _msg = self.gettext(msgid)
        # print ("TRANSLATE", msgid, _msg, mapping, context)
        _msg = TALInterpreter.interpolate(_msg, mapping)
        return _msg

    if hasattr(i18n.RoundupTranslations, 'ugettext'):
        def gettext(self, msgid):
            msgid = us2u(msgid)
            msgtrans = self.ugettext(msgid)
            return u2s(msgtrans)

        def ngettext(self, singular, plural, number):
            singular = us2u(singular)
            plural = us2u(plural)
            msgtrans = self.ungettext(singular, plural, number)
            return u2s(msgtrans)


class TranslationService(TranslationServiceMixin, i18n.RoundupTranslations):
    pass


class NullTranslationService(TranslationServiceMixin,
                             i18n.RoundupNullTranslations):
    if hasattr(i18n.RoundupNullTranslations, 'ugettext'):
        def ugettext(self, message):
            if self._fallback:
                return self._fallback.ugettext(message)
            # Sometimes the untranslatable message is a UTF-8 encoded string
            # (thanks to PageTemplate's internals).
            message = us2u(message)
            return message

### TAL patching
#
# Template Attribute Language (TAL) uses only global translation service,
# which is not thread-safe.  We will use context variable 'i18n'
# to access request-dependent transalation service (with domain
# and target language set during initializations of the roundup
# client interface.
#


class Context(TALES.Context):

    def __init__(self, compiler, contexts):
        TALES.Context.__init__(self, compiler, contexts)
        if not self.contexts.get('i18n', None):
            # if the context contains no TranslationService,
            # create default one
            self.contexts['i18n'] = get_translation()
        self.i18n = self.contexts['i18n']

    def translate(self, domain, msgid, mapping=None,
                  context=None, target_language=None, default=None):
        if context is None:
            context = self.contexts.get('here')
        return self.i18n.translate(domain, msgid,
                                   mapping=mapping, context=context,
                                   default=default,
                                   target_language=target_language)


class Engine(TALES.Engine):

    def getContext(self, contexts=None, **kwcontexts):
        if contexts is not None:
            if kwcontexts:
                kwcontexts.update(contexts)
            else:
                kwcontexts = contexts
        return Context(self, kwcontexts)


# patching TAL like this is a dirty hack,
# but i see no other way to specify different Context class
Expressions._engine = Engine(PathIterator.Iterator)
Expressions.installHandlers(Expressions._engine)

### main API function


def get_translation(language=None, tracker_home=None,
                    translation_class=TranslationService,
                    null_translation_class=NullTranslationService):
    """Return Translation object for given language and domain

    Arguments 'translation_class' and 'null_translation_class'
    specify the classes that are instantiated for existing
    and non-existing translations, respectively.
    """
    return i18n.get_translation(language=language,
                                tracker_home=tracker_home,
                                translation_class=translation_class,
                                null_translation_class=null_translation_class)

# vim: set et sts=4 sw=4 :
