"""Templating engine adapter for the Chameleon."""

__docformat__ = 'restructuredtext'

import chameleon

from roundup.cgi.templating import context, TALLoaderBase
from roundup.anypy.strings import s2u


class Loader(TALLoaderBase):
    def __init__(self, template_dir):
        self.template_dir = template_dir
        self.loader = chameleon.PageTemplateLoader(template_dir)

    def load(self, tplname):
        try:
            src, filename = self._find(tplname)
        except TypeError as e:
            raise ValueError("Unable to load template file basename: %s: %s" % (
                tplname, e))

        return RoundupPageTemplate(self.loader.load(src))


class RoundupPageTemplate(object):
    def __init__(self, pt):
        self._pt = pt

    def render(self, client, classname, request, **options):
        c = context(client, self, classname, request)
        c.update({'options': options})

        def translate(msgid, domain=None, mapping=None, default=None):
            result = client.translator.translate(domain, msgid,
                                                 mapping=mapping,
                                                 default=default)
            return s2u(result)

        output = self._pt.render(None, translate, **c)
        return output.encode(client.charset)

    def __getitem__(self, name):
        return self._pt[name]

    def __getattr__(self, name):
        return getattr(self._pt, name)
