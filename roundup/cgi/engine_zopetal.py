"""Templating engine adapter for the legacy TAL implementation ported from
Zope.
"""
__docformat__ = 'restructuredtext'

import errno
import mimetypes
import os
import os.path

from roundup.cgi.templating import StringIO, context, translationService, LoaderBase
from roundup.cgi.PageTemplates import PageTemplate, GlobalTranslationService
from roundup.cgi.PageTemplates.Expressions import getEngine
from roundup.cgi.TAL import TALInterpreter

GlobalTranslationService.setGlobalTranslationService(translationService)

class Loader(LoaderBase):
    templates = {}

    def __init__(self, dir):
        self.dir = dir

    def check(self, name):
        for extension in ['', '.html', '.xml']:
            f = name + extension
            src = os.path.join(self.dir, f)
            if os.path.exists(src):
                return (src, f)

    def load(self, tplname):
        # find the source
        src, filename = self.check(tplname)

        # has it changed?
        try:
            stime = os.stat(src)[os.path.stat.ST_MTIME]
        except os.error, error:
            if error.errno != errno.ENOENT:
                raise

        if self.templates.has_key(src) and \
                stime <= self.templates[src].mtime:
            # compiled template is up to date
            return self.templates[src]

        # compile the template
        pt = RoundupPageTemplate()
        # use pt_edit so we can pass the content_type guess too
        content_type = mimetypes.guess_type(filename)[0] or 'text/html'
        pt.pt_edit(open(src).read(), content_type)
        pt.id = filename
        pt.mtime = stime
        # Add it to the cache.  We cannot do this until the template
        # is fully initialized, as we could otherwise have a race
        # condition when running with multiple threads:
        #
        # 1. Thread A notices the template is not in the cache,
        #    adds it, but has not yet set "mtime".
        #
        # 2. Thread B notices the template is in the cache, checks
        #    "mtime" (above) and crashes.
        #
        # Since Python dictionary access is atomic, as long as we
        # insert "pt" only after it is fully initialized, we avoid
        # this race condition.  It's possible that two separate
        # threads will both do the work of initializing the template,
        # but the risk of wasted work is offset by avoiding a lock.
        self.templates[src] = pt
        return pt

class RoundupPageTemplate(PageTemplate.PageTemplate):
    """A Roundup-specific PageTemplate.

    Interrogate the client to set up Roundup-specific template variables
    to be available.  See 'context' function for the list of variables.

    """

    def render(self, client, classname, request, **options):
        """Render this Page Template"""

        if not self._v_cooked:
            self._cook()

        __traceback_supplement__ = (PageTemplate.PageTemplateTracebackSupplement, self)

        if self._v_errors:
            raise PageTemplate.PTRuntimeError, \
                'Page Template %s has errors.'%self.id

        # figure the context
        c = context(client, self, classname, request)
        c.update({'options': options})

        # and go
        output = StringIO.StringIO()
        TALInterpreter.TALInterpreter(self._v_program, self.macros,
            getEngine().getContext(c), output, tal=1, strictinsert=0)()
        return output.getvalue()

