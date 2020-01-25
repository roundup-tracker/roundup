"""
Experimental Jinja2 support for Roundup. It will become less
experimental when it is completely clear what information is
passed to template, and when the info is limited to the sane
minimal set (to avoid Roundup state changes from template).

[ ] fallback mechanizm to use multiple templating engines in
    parallel and aid in incremental translation from one
    engine to another

[ ] define a place for templates
    probably
      TRACKER_HOME/templates/jinja2
    with
      TRACKER_HOME/templates/INFO.txt
        describing how the dir was created, for example
          "This is a copy of 'classic' template from ..."
        also template fallback mechanizm for multi-engine
          configuration
    [ ] backward compatibility - if no engine is explicitly
          specified, use TRACKER_HOME/html directory
    [ ] copy TEMPLATES-INFO.txt to INFO.txt
      [ ] implement VERSION file in environment for auto
          upgrade

[ ] precompile() is a stub

[ ] add {{ debug() }} dumper to inspect available variables
    https://github.com/mitsuhiko/jinja2/issues/174
"""

from __future__ import print_function
import jinja2
import gettext
import mimetypes
import sys

# http://jinja.pocoo.org/docs/api/#loaders

from roundup.cgi.templating import context, LoaderBase, TemplateBase
from roundup.anypy.strings import s2u


class Jinja2Loader(LoaderBase):
    def __init__(self, dir):
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(dir),
            extensions=['jinja2.ext.i18n'],
            autoescape=True
        )

        # Adding a custom filter that can transform roundup's vars to unicode
        # This is necessary because jinja2 can only deal with unicode objects
        # and roundup uses utf-8 for the internal representation.
        # The automatic conversion will assume 'ascii' and fail sometime.
        # Analysed with roundup 1.5.0 and jinja 2.7.1. See issue2550811.
        self._env.filters["u"] = s2u

    def _find(self, tplname):
        for extension in ('', '.html', '.xml'):
            try:
                filename = tplname + extension
                return self._env.get_template(filename)
            except jinja2.TemplateNotFound:
                continue

        return None

    def check(self, tplname):
        return bool(self._find(tplname))

    def load(self, tplname):
        tpl = self._find(tplname)
        pt = Jinja2ProxyPageTemplate(tpl)
        pt.content_type = mimetypes.guess_type(tpl.filename)[0] or 'text/html'
        return pt

    def precompile(self):
        pass


class Jinja2ProxyPageTemplate(TemplateBase):
    def __init__(self, template):
        self._tpl = template

    def render(self, client, classname, request, **options):
        # [ ] limit the information passed to the minimal necessary set
        c = context(client, self, classname, request)

        c.update({'options': options,
                  'gettext': lambda s: s2u(client.gettext(s)),
                  'ngettext': lambda s, p, n: s2u(client.ngettext(s, p, n))})
        s = self._tpl.render(c)
        return s if sys.version_info[0] > 2 else \
            s.encode(client.STORAGE_CHARSET, )

    def __getitem__(self, name):
        # [ ] figure out what are these for
        raise NotImplementedError
        # return self._pt[name]

    def __getattr__(self, name):
        # [ ] figure out what are these for
        raise NotImplementedError
        # return getattr(self._pt, name)
