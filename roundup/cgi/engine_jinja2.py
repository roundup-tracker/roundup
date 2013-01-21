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
[ ] figure out what to do with autoescaping - it is disabled
    by default in Jinja2

[ ] precompile() is a stub

[ ] add {{ debug() }} dumper to inspect available variables
    https://github.com/mitsuhiko/jinja2/issues/174
"""

import jinja2

# http://jinja.pocoo.org/docs/api/#loaders

from roundup.cgi.templating import context, LoaderBase, TemplateBase

class Jinja2Loader(LoaderBase):
    def __init__(self, dir):
        jinjadir = dir + '/jinja2'
        # [ ] separate configuration when multiple loaders are used
        print "Jinja2 templates:", jinjadir
        self._env = jinja2.Environment(
                        loader=jinja2.FileSystemLoader(jinjadir)
                    )

    def check(self, tplname):
        print tplname
        try:
            print self._env.get_template(tplname + '.html')
        except jinja2.TemplateNotFound:
            return
        else:
            return True

    def load(self, tplname):
        #src, filename = self.check(tplname)
        return Jinja2ProxyPageTemplate(self._env.get_template(tplname + '.html'))

    def precompile(self):
        pass

class Jinja2ProxyPageTemplate(TemplateBase):
    def __init__(self, template):
        self._tpl = template

    def render(self, client, classname, request, **options):
        # [ ] limit the information passed to the minimal necessary set
        c = context(client, self, classname, request)
        '''c.update({'options': options})

        def translate(msgid, domain=None, mapping=None, default=None):
            result = client.translator.translate(domain, msgid,
                         mapping=mapping, default=default)
            return unicode(result, client.translator.OUTPUT_ENCODING)

        output = self._pt.render(None, translate, **c)
        return output.encode(client.charset)
        '''
        return self._tpl.render(c)

    def __getitem__(self, name):
        # [ ] figure out what are these for
        raise NotImplemented
        #return self._pt[name]

    def __getattr__(self, name):
        # [ ] figure out what are these for
        raise NotImplemented
        #return getattr(self._pt, name)

