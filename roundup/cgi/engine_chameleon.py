"""Templating engine adapter for the Chameleon."""

__docformat__ = 'restructuredtext'

import os.path
from chameleon import PageTemplateLoader

from roundup.cgi.templating import StringIO, context, find_template, TemplatesBase

class Templates(TemplatesBase):
    def __init__(self, dir):
        self.dir = dir
        self.loader = PageTemplateLoader(dir)

    def get(self, name, extension=None):
        # default the name to "home"
        if name is None:
            name = 'home'
        elif extension is None and '.' in name:
            # split name
            name, extension = name.split('.')

        src, filename = find_template(self.dir, name, extension)
        return RoundupPageTemplate(self.loader.load(src))

class RoundupPageTemplate():
    def __init__(self, pt):
        self._pt = pt

    def render(self, client, classname, request, **options):
        c = context(client, self, classname, request)
        c.update({'options': options})

        def translate(msgid, domain=None, mapping=None, default=None):
            result = client.translator.translate(domain, msgid,
                         mapping=mapping, default=default)
            return unicode(result, client.translator.OUTPUT_ENCODING)

        output = self._pt.render(None, translate, None, **c)
        return output.encode(client.charset)

    def __getitem__(self, name):
        return self._pt[name]

    def __getattr__(self, name):
        return getattr(self._pt, name)

