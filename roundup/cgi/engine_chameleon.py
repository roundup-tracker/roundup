"""Templating engine adapter for the Chameleon."""

__docformat__ = 'restructuredtext'

import os.path
import chameleon

from roundup.cgi.templating import StringIO, context, LoaderBase

class Loader(LoaderBase):
    def __init__(self, dir):
        self.dir = dir
        self.loader = chameleon.PageTemplateLoader(dir)

    def check(self, name):
        for extension in ['', '.html', '.xml']:
            f = name + extension
            src = os.path.join(self.dir, f)
            if os.path.exists(src):
                return (src, f)

    def load(self, tplname):
        src, filename = self.check(tplname)
        return RoundupPageTemplate(self.loader.load(src))

class RoundupPageTemplate(object):
    def __init__(self, pt):
        self._pt = pt

    def render(self, client, classname, request, **options):
        c = context(client, self, classname, request)
        c.update({'options': options})

        def translate(msgid, domain=None, mapping=None, default=None):
            result = client.translator.translate(domain, msgid,
                         mapping=mapping, default=default)
            return unicode(result, client.translator.OUTPUT_ENCODING)

        output = self._pt.render(None, translate, **c)
        return output.encode(client.charset)

    def __getitem__(self, name):
        return self._pt[name]

    def __getattr__(self, name):
        return getattr(self._pt, name)

