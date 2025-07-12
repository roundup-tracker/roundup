"""Implements the API used in the HTML templating for the web interface.
"""

__todo__ = """
- Document parameters to Template.render() method
- Add tests for Loader.load() method
- Most methods should have a "default" arg to supply a value
  when none appears in the hyperdb or request.
- Multilink property additions: change_note and new_upload
- Add class.find() too
- NumberHTMLProperty should support numeric operations
- LinkHTMLProperty should handle comparisons to strings (cf. linked name)
- HTMLRequest.default(self, sort, group, filter, columns, **filterspec):
  '''Set the request's view arguments to the given values when no
     values are found in the CGI environment.
  '''
- have menu() methods accept filtering arguments
"""

__docformat__ = 'restructuredtext'

import calendar
import csv
import logging
import os.path
import re
import textwrap

from roundup import date, hyperdb, support
from roundup.anypy import scandir_
from roundup.anypy import urllib_
from roundup.anypy.cgi_ import cgi
from roundup.anypy.html import html_escape
from roundup.anypy.strings import StringIO, is_us, s2u, u2s, us2s
from roundup.cgi import TranslationService, ZTUtils
from roundup.cgi.timestamp import pack_timestamp
from roundup.exceptions import RoundupException

from .KeywordsExpr import render_keywords_expression_editor

try:
    from docutils.core import publish_parts as ReStructuredText
except ImportError:
    ReStructuredText = None
try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest

logger = logging.getLogger('roundup.template')

# List of schemes that are not rendered as links in rst and markdown.
_disable_url_schemes = ['javascript', 'data']


def _import_markdown2():
    try:
        import re

        import markdown2

        # Note: version 2.4.9 does not work with Roundup as it breaks
        # [issue1](issue1) formatted links.

        # Versions 2.4.8 and 2.4.10 use different methods to filter
        # allowed schemes. 2.4.8 uses a pre-compiled regexp while
        # 2.4.10 uses a regexp string that it compiles.

        markdown2_vi = markdown2.__version_info__
        if markdown2_vi > (2, 4, 9):
            # Create the filtering regexp.
            # Allowed default is same as what hyper_re supports.

            # pathed_schemes are terminated with ://
            pathed_schemes = ['http', 'https', 'ftp', 'ftps']
            # non_pathed are terminated with a :
            non_pathed_schemes = ["mailto"]

            for disabled in _disable_url_schemes:
                try:
                    pathed_schemes.remove(disabled)
                except ValueError:  # if disabled not in list
                    pass
                try:
                    non_pathed_schemes.remove(disabled)
                except ValueError:
                    pass

            re_list = []
            for scheme in pathed_schemes:
                re_list.append(r'(?:%s)://' % scheme)
            for scheme in non_pathed_schemes:
                re_list.append(r'(?:%s):' % scheme)

            enabled_schemes = r"|".join(re_list)

            class Markdown(markdown2.Markdown):
                _safe_protocols = enabled_schemes
        elif markdown2_vi == (2, 4, 9):
            raise RuntimeError("Unsupported version - markdown2 v2.4.9\n")
        else:
            class Markdown(markdown2.Markdown):
                # don't allow disabled protocols in links
                _safe_protocols = re.compile('(?!' + ':|'.join([
                    re.escape(s) for s in _disable_url_schemes])
                                         + ':)', re.IGNORECASE)

        def _extras(config):
            extras = {'fenced-code-blocks': {}, 'nofollow': None}
            if config['MARKDOWN_BREAK_ON_NEWLINE']:
                extras['break-on-newline'] = True
            return extras

        markdown = lambda s, c: Markdown(safe_mode='escape', extras=_extras(c)).convert(s)  # noqa: E731
    except ImportError:
        markdown = None

    return markdown


def _import_markdown():
    try:
        from markdown import markdown as markdown_impl
        from markdown.extensions import Extension as MarkdownExtension
        from markdown.treeprocessors import Treeprocessor

        class RestrictLinksProcessor(Treeprocessor):
            def run(self, root):
                for el in root.iter('a'):
                    if 'href' in el.attrib:
                        url = el.attrib['href'].lstrip(' \r\n\t\x1a\0').lower()
                        for s in _disable_url_schemes:
                            if url.startswith(s + ':'):
                                el.attrib['href'] = '#'

        class LinkRendererWithRel(Treeprocessor):
            ''' Rendering class that sets the rel="nofollow noreferer"
                for links. '''
            rel_value = "nofollow noopener"

            def run(self, root):
                for el in root.iter('a'):
                    if 'href' in el.attrib:
                        url = el.get('href').lstrip(' \r\n\t\x1a\0').lower()
                        if not url.startswith('http'):  # only add rel for absolute http url's
                            continue
                        el.set('rel', self.rel_value)

        # make sure any HTML tags get escaped and some links restricted
        # and rel="nofollow noopener" are added to links
        class SafeHtml(MarkdownExtension):
            def extendMarkdown(self, md, md_globals=None):
                if hasattr(md.preprocessors, 'deregister'):
                    md.preprocessors.deregister('html_block')
                else:
                    del md.preprocessors['html_block']
                if hasattr(md.inlinePatterns, 'deregister'):
                    md.inlinePatterns.deregister('html')
                else:
                    del md.inlinePatterns['html']

                if hasattr(md.preprocessors, 'register'):
                    md.treeprocessors.register(RestrictLinksProcessor(), 'restrict_links', 0)
                else:
                    md.treeprocessors['restrict_links'] = RestrictLinksProcessor()
                if hasattr(md.preprocessors, 'register'):
                    md.treeprocessors.register(LinkRendererWithRel(), 'add_link_rel', 0)
                else:
                    md.treeprocessors['add_link_rel'] = LinkRendererWithRel()

        def _extensions(config):
            extensions = [SafeHtml(), 'fenced_code']
            if config['MARKDOWN_BREAK_ON_NEWLINE']:
                extensions.append('nl2br')
            return extensions

        markdown = lambda s, c: markdown_impl(s, extensions=_extensions(c))  # noqa: E731
    except ImportError:
        markdown = None

    return markdown


def _import_mistune():
    try:
        import mistune
        from mistune import Renderer, escape, escape_link

        mistune._scheme_blacklist = [s + ':' for s in _disable_url_schemes]

        class LinkRendererWithRel(Renderer):
            ''' Rendering class that sets the rel="nofollow noreferer"
                for links. '''

            rel_value = "nofollow noopener"

            def autolink(self, link, is_email=False):
                ''' handle <url or email> style explicit links '''
                text = link = escape_link(link)
                if is_email:
                    link = 'mailto:%s' % link
                    return '<a href="%(href)s">%(text)s</a>' % {
                        'href': link, 'text': text}
                return '<a href="%(href)s" rel="%(rel)s">%(href)s</a>' % {
                    'rel': self.rel_value, 'href': escape_link(link)}

            def link(self, link, title, content):
                ''' handle [text](url "title") style links and Reference
                    links '''

                values = {
                    'content': escape(content),
                    'href': escape_link(link),
                    'rel': self.rel_value,
                    'title': escape(title) if title else '',
                }

                if title:
                    return '<a href="%(href)s" rel="%(rel)s" ' \
                            'title="%(title)s">%(content)s</a>' % values

                return '<a href="%(href)s" rel="%(rel)s">%(content)s</a>' % values

        def _options(config):
            options = {'renderer': LinkRendererWithRel(escape=True)}
            if config['MARKDOWN_BREAK_ON_NEWLINE']:
                options['hard_wrap'] = True
            return options

        markdown = lambda s, c: mistune.markdown(s, **_options(c))  # noqa: E731
    except ImportError:
        markdown = None

    return markdown


markdown = _import_markdown2() or _import_markdown() or _import_mistune()


def anti_csrf_nonce(client, lifetime=None):
    ''' Create a nonce for defending against CSRF attack.

        Then it stores the nonce, the session id for the user
        and the user id in the one time key database for use
        by the csrf validator that runs in the client::inner_main
        module/function.
    '''
    otks = client.db.getOTKManager()
    key = otks.getUniqueKey()
    # lifetime is in minutes.
    if lifetime is None:
        lifetime = client.db.config['WEB_CSRF_TOKEN_LIFETIME']

    ts = otks.lifetime(lifetime * 60)
    otks.set(key, uid=client.db.getuid(),
             sid=client.session_api._sid,
             __timestamp=ts)
    otks.commit()
    return key

# templating


class NoTemplate(RoundupException):
    pass


class Unauthorised(RoundupException):
    def __init__(self, action, klass, translator=None):
        self.action = action
        self.klass = klass
        if translator:
            self._ = translator.gettext
        else:
            self._ = TranslationService.get_translation().gettext

    def __str__(self):
        return self._('You are not allowed to %(action)s '
                      'items of class %(class)s') % {
                          'action': self.action, 'class': self.klass}


# --- Template Loader API

class LoaderBase:
    """ Base for engine-specific template Loader class."""
    def __init__(self, template_dir):
        # loaders are given the template directory as a first argument
        pass

    def precompile(self):
        """ This method may be called when tracker is loaded to precompile
            templates that support this ability.
        """
        pass

    def load(self, tplname):
        """ Load template and return template object with render() method.

            "tplname" is a template name. For filesystem loaders it is a
            filename without extensions, typically in the "classname.view"
            format.
        """
        raise NotImplementedError

    def check(self, name):
        """ Check if template with the given name exists. Should return
            false if template can not be found.
        """
        raise NotImplementedError


class TALLoaderBase(LoaderBase):
    """ Common methods for the legacy TAL loaders."""

    def __init__(self, template_dir):
        self.template_dir = template_dir

    def _find(self, name):
        """ Find template, return full path and filename of the
            template if it is found, None otherwise."""
        realsrc = os.path.realpath(self.template_dir)
        for extension in ['', '.html', '.xml']:
            f = name + extension
            src = os.path.join(realsrc, f)
            realpath = os.path.realpath(src)
            if not realpath.startswith(realsrc):
                return None # will raise invalid template
            if os.path.exists(src):
                return (src, f)
        return None

    def check(self, name):
        return bool(self._find(name))

    def precompile(self):
        """ Precompile templates in load directory by loading them """
        for dir_entry in os.scandir(self.template_dir):
            filename = dir_entry.name
            # skip subdirs
            if dir_entry.is_dir():
                continue

            # skip files without ".html" or ".xml" extension - .css, .js etc.
            for extension in '.html', '.xml':
                if filename.endswith(extension):
                    break
            else:
                continue

            # remove extension
            filename = filename[:-len(extension)]
            self.load(filename)

    def __getitem__(self, name):
        """Special method to access templates by loader['name']"""
        try:
            return self.load(name)
        except NoTemplate as message:
            raise KeyError(message)


class MultiLoader(LoaderBase):
    def __init__(self):
        self.loaders = []

    def add_loader(self, loader):
        self.loaders.append(loader)

    def check(self, name):
        for loader in self.loaders:
            if loader.check(name):
                return True

    def load(self, name):
        for loader in self.loaders:
            if loader.check(name):
                return loader.load(name)

    def __getitem__(self, name):
        """Needed for TAL templates compatibility"""
        # [ ] document root and helper templates
        try:
            return self.load(name)
        except NoTemplate as message:
            raise KeyError(message)


class TemplateBase:
    content_type = 'text/html'


def get_loader(template_dir, template_engine):

    # Support for multiple engines using fallback mechanizm
    # meaning that if first engine can't find template, we
    # use the second

    engines = template_engine.split(',')
    engines = [x.strip() for x in engines]
    ml = MultiLoader()

    for engine_name in engines:
        if engine_name == 'chameleon':
            from .engine_chameleon import Loader
        elif engine_name == 'jinja2':
            from .engine_jinja2 import Jinja2Loader as Loader
        elif engine_name == 'zopetal':
            from .engine_zopetal import Loader
        else:
            raise Exception('Unknown template engine "%s"' % engine_name)
        ml.add_loader(Loader(template_dir))

    if len(engines) == 1:
        return ml.loaders[0]
    else:
        return ml

# --/ Template Loader API


def context(client, template=None, classname=None, request=None):
    """Return the rendering context dictionary

    The dictionary includes following symbols:

    *context*
     this is one of three things:

     1. None - we're viewing a "home" page
     2. The current class of item being displayed. This is an HTMLClass
        instance.
     3. The current item from the database, if we're viewing a specific
        item, as an HTMLItem instance.

    *request*
      Includes information about the current request, including:

       - the url
       - the current index information (``filterspec``, ``filter`` args,
         ``properties``, etc) parsed out of the form.
       - methods for easy filterspec link generation
       - *user*, the current user node as an HTMLItem instance
       - *form*, the current CGI form information as a FieldStorage

    *config*
      The current tracker config.

    *db*
      The current database, used to access arbitrary database items.

    *utils*
      This is an instance of client.instance.TemplatingUtils, which is
      optionally defined in the tracker interfaces module and defaults to
      TemplatingUtils class in this file.

    *templates*
      Access to all the tracker templates by name.
      Used mainly in *use-macro* commands.

    *template*
      Current rendering template.

    *true*
      Logical True value.

    *false*
      Logical False value.

    *i18n*
      Internationalization service, providing string translation
      methods ``gettext`` and ``ngettext``.

    """

    # if template, classname and/or request are not passed explicitely,
    # compute form client
    if template is None:
        template = client.template
    if classname is None:
        classname = client.classname
    if request is None:
        request = HTMLRequest(client)

    c = {
         'context': None,
         'options': {},
         'nothing': None,
         'request': request,
         'db': HTMLDatabase(client),
         'config': client.instance.config,
         'tracker': client.instance,
         'utils': client.instance.TemplatingUtils(client),
         'templates': client.instance.templates,
         'template': template,
         'true': 1,
         'false': 0,
         'i18n': client.translator
    }
    # add in the item if there is one
    if client.nodeid:
        c['context'] = HTMLItem(client, classname, client.nodeid,
                                anonymous=1)
    elif classname in client.db.classes:
        c['context'] = HTMLClass(client, classname, anonymous=1)
    return c


class HTMLDatabase:
    """ Return HTMLClasses for valid class fetches
    """
    def __init__(self, client):
        self._client = client
        self._ = client._
        self._db = client.db

        # we want config to be exposed
        self.config = client.db.config

    def __getitem__(self, item, desre=re.compile(r'(?P<cl>[a-zA-Z_]+)(?P<id>[-\d]+)')):
        # check to see if we're actually accessing an item
        m = desre.match(item)
        if m:
            cl = m.group('cl')
            self._client.db.getclass(cl)
            return HTMLItem(self._client, cl, m.group('id'))
        else:
            self._client.db.getclass(item)
            return HTMLClass(self._client, item)

    def __getattr__(self, attr):
        try:
            return self[attr]
        except KeyError:
            raise AttributeError(attr)

    def classes(self):
        class_keys = sorted(self._client.db.classes.keys())
        m = []
        for item in class_keys:
            m.append(HTMLClass(self._client, item))
        return m


num_re = re.compile(r'^-?\d+$')


def lookupIds(db, prop, ids, fail_ok=0, num_re=num_re, do_lookup=True):
    """ "fail_ok" should be specified if we wish to pass through bad values
        (most likely form values that we wish to represent back to the user)
        "do_lookup" is there for preventing lookup by key-value (if we
        know that the value passed *is* an id)
    """
    cl = db.getclass(prop.classname)
    l = []
    for entry in ids:
        # Do not look up numeric IDs if try_id_parsing
        if prop.try_id_parsing and num_re.match(entry):
            l.append(entry)
            continue
        if do_lookup:
            try:
                item = cl.lookup(entry)
            except (TypeError, KeyError):
                pass
            else:
                l.append(item)
                continue

        # if fail_ok, ignore lookup error
        # otherwise entry must be existing object id rather than key value
        if fail_ok:
            l.append(entry)
        elif entry == '@current_user' and prop.classname == 'user':
            # as a special case, '@current_user' means the currently
            # logged-in user
            l.append(entry)

    return l


def lookupKeys(linkcl, key, ids, num_re=num_re):
    """ Look up the "key" values for "ids" list - though some may already
    be key values, not ids.
    """
    l = []
    for entry in ids:
        if num_re.match(entry):
            try:
                label = linkcl.get(entry, key, allow_abort=False)
            except IndexError:
                # fall back to id if illegal (avoid template crash)
                label = entry
            # fall back to designator if label is None
            if label is None:
                label = '%s%s' % (linkcl.classname, entry)
            l.append(label)
        else:
            l.append(entry)
    return l


def _set_input_default_args(dic):
    # 'text' is the default value anyway --
    # but for CSS usage it should be present
    dic.setdefault('type', 'text')
    # useful e.g for HTML LABELs:
    if 'id' not in dic:
        try:
            if dic['type'] in ('radio', 'checkbox'):
                dic['id'] = '%(name)s-%(value)s' % dic
            else:
                dic['id'] = dic['name']
        except KeyError:
            pass


def html4_cgi_escape_attrs(**attrs):
    ''' Boolean attributes like 'disabled', 'required'
        are represented without a value. E.G.
        <input required ..> not <input required="required" ...>
        The latter is xhtml. Recognize booleans by:
          value is None
        Code can use None to indicate a pure boolean.
    '''
    return ' '.join(['%s="%s"' % (k, html_escape(str(v), True))
                     if v is not None else '%s' % (k)
                     for k, v in sorted(attrs.items())])


def input_html4(**attrs):
    """Generate an 'input' (html4) element with given attributes"""
    _set_input_default_args(attrs)
    return '<input %s>' % html4_cgi_escape_attrs(**attrs)


class HTMLInputMixin(object):
    """ requires a _client property """
    def __init__(self):
        html_version = 'html4'
        if hasattr(self._client.instance.config, 'HTML_VERSION'):
            html_version = self._client.instance.config.HTML_VERSION
        self.input = input_html4
        self.cgi_escape_attrs = html4_cgi_escape_attrs
        # self._context is used for translations.
        # will be initialized by the first call to .gettext()
        self._context = None

    def gettext(self, msgid):
        """Return the localized translation of msgid"""
        if self._context is None:
            self._context = context(self._client)
        return self._client.translator.translate(
            domain="roundup", msgid=msgid, context=self._context)

    _ = gettext


class HTMLPermissions(object):

    def view_check(self):
        """ Raise the Unauthorised exception if the user's not permitted to
            view this class.
        """
        if not self.is_view_ok():
            raise Unauthorised("view", self._classname,
                               translator=self._client.translator)

    def edit_check(self):
        """ Raise the Unauthorised exception if the user's not permitted to
            edit items of this class.
        """
        if not self.is_edit_ok():
            raise Unauthorised("edit", self._classname,
                               translator=self._client.translator)

    def retire_check(self):
        """ Raise the Unauthorised exception if the user's not permitted to
            retire items of this class.
        """
        if not self.is_retire_ok():
            raise Unauthorised("retire", self._classname,
                               translator=self._client.translator)


class HTMLClass(HTMLInputMixin, HTMLPermissions):
    """ Accesses through a class (either through *class* or *db.<classname>*)
    """
    def __init__(self, client, classname, anonymous=0):
        self._client = client
        self._ = client._
        self._db = client.db
        self._anonymous = anonymous

        # we want classname to be exposed, but _classname gives a
        # consistent API for extending Class/Item
        self._classname = self.classname = classname
        self._klass = self._db.getclass(self.classname)
        self._props = self._klass.getprops()

        HTMLInputMixin.__init__(self)

    def is_edit_ok(self):
        """ Is the user allowed to Create the current class?
        """
        perm = self._db.security.hasPermission
        return perm('Web Access', self._client.userid) and perm(
            'Create', self._client.userid, self._classname)

    def is_retire_ok(self):
        """ Is the user allowed to retire items of the current class?
        """
        perm = self._db.security.hasPermission
        return perm('Web Access', self._client.userid) and perm(
            'Retire', self._client.userid, self._classname)

    def is_restore_ok(self):
        """ Is the user allowed to restore retired items of the current class?
        """
        perm = self._db.security.hasPermission
        return perm('Web Access', self._client.userid) and perm(
            'Restore', self._client.userid, self._classname)

    def is_view_ok(self):
        """ Is the user allowed to View the current class?
        """
        perm = self._db.security.hasPermission
        return perm('Web Access', self._client.userid) and perm(
            'View', self._client.userid, self._classname)

    def is_only_view_ok(self):
        """ Is the user only allowed to View (ie. not Create) the current class?
        """
        return self.is_view_ok() and not self.is_edit_ok()

    def __repr__(self):
        return '<HTMLClass(0x%x) %s>' % (id(self), self.classname)

    def __getitem__(self, item):
        """ return an HTMLProperty instance
        """

        # we don't exist
        if item == 'id':
            return None

        # get the property
        try:
            prop = self._props[item]
        except KeyError:
            raise KeyError('No such property "%s" on %s' % (item,
                                                            self.classname))

        # look up the correct HTMLProperty class
        for klass, htmlklass in propclasses:
            if not isinstance(prop, klass):
                continue
            return htmlklass(self._client, self._classname, None, prop, item,
                             None, self._anonymous)

        # no good
        raise KeyError(item)

    def __getattr__(self, attr):
        """ convenience access """
        try:
            return self[attr]
        except KeyError:
            raise AttributeError(attr)

    def designator(self):
        """ Return this class' designator (classname) """
        return self._classname

    def getItem(self, itemid, num_re=num_re):
        """ Get an item of this class by its item id.
        """
        # make sure we're looking at an itemid
        if not isinstance(itemid, type(1)) and not num_re.match(itemid):
            itemid = self._klass.lookup(itemid)

        return HTMLItem(self._client, self.classname, itemid)

    def properties(self, sort=1, cansearch=True):
        """ Return HTMLProperty for allowed class' properties.

            To return all properties call it with cansearch=False
            and it will return properties the user is unable to
            search.
        """
        l = []
        canSearch = self._db.security.hasSearchPermission
        userid = self._client.userid
        for name, prop in self._props.items():
            if cansearch and \
               not canSearch(userid, self._classname, name):
                continue
            for klass, htmlklass in propclasses:
                if isinstance(prop, klass):
                    value = prop.get_default_value()
                    l.append(htmlklass(self._client, self._classname, '',
                                       prop, name, value, self._anonymous))
        if sort:
            l.sort(key=lambda a: a._name)
        return l

    def list(self, sort_on=None):
        """ List all items in this class.
        """
        # get the list and sort it nicely
        class_list = self._klass.list()
        keyfunc = make_key_function(self._db, self._classname, sort_on)
        class_list.sort(key=keyfunc)

        # check perms
        check = self._client.db.security.hasPermission
        userid = self._client.userid
        if not check('Web Access', userid):
            return []

        class_list = [HTMLItem(self._client, self._classname, itemid)
                      for itemid in class_list if
                      check('View', userid, self._classname, itemid=itemid)]

        return class_list

    def csv(self):
        """ Return the items of this class as a chunk of CSV text.
        """
        props = self.propnames()
        s = StringIO()
        writer = csv.writer(s)
        writer.writerow(props)
        check = self._client.db.security.hasPermission
        userid = self._client.userid
        if not check('Web Access', userid):
            return ''
        for nodeid in self._klass.list():
            l = []
            for name in props:
                # check permission to view this property on this item
                if not check('View', userid, itemid=nodeid,
                             classname=self._klass.classname, property=name):
                    raise Unauthorised('view', self._klass.classname,
                                       translator=self._client.translator)
                value = self._klass.get(nodeid, name)
                if value is None:
                    l.append('')
                elif isinstance(value, type([])):
                    l.append(':'.join(map(str, value)))
                else:
                    l.append(str(self._klass.get(nodeid, name)))
            writer.writerow(l)
        return s.getvalue()

    def propnames(self):
        """ Return the list of the names of the properties of this class.
        """
        idlessprops = sorted(self._klass.getprops(protected=0).keys())
        return ['id'] + idlessprops

    def filter(self, request=None, filterspec={}, sort=[], group=[]):
        """ Return a list of items from this class, filtered and sorted
            by the current requested filterspec/filter/sort/group args

            "request" takes precedence over the other three arguments.
        """
        security = self._db.security
        userid = self._client.userid
        if request is not None:
            # for a request we asume it has already been
            # security-filtered
            filterspec = request.filterspec
            sort = request.sort
            group = request.group
        else:
            cn = self.classname
            filterspec = security.filterFilterspec(userid, cn, filterspec)
            sort = security.filterSortspec(userid, cn, sort)
            group = security.filterSortspec(userid, cn, group)

        check = security.hasPermission
        if not check('Web Access', userid):
            return []

        filtered = [HTMLItem(self._client, self.classname, itemid)
                    for itemid in self._klass.filter(None, filterspec,
                                                     sort, group)
                    if check('View', userid, self.classname, itemid=itemid)]
        return filtered

    def classhelp(self, properties=None, label=''"(list)", width='500',
                  height='600', property='', form='itemSynopsis',
                  pagesize=50, inputtype="checkbox", html_kwargs={},
                  group='', sort=None, filter=None):
        """Pop up a javascript window with class help

        This generates a link to a popup window which displays the
        properties indicated by "properties" of the class named by
        "classname". The "properties" should be a comma-separated list
        (eg. 'id,name,description'). Properties defaults to all the
        properties of a class (excluding id, creator, created and
        activity).

        You may optionally override the label displayed, the width,
        the height, the number of items per page and the field on which
        the list is sorted (defaults to username if in the displayed
        properties).

        With the "filter" arg it is possible to specify a filter for
        which items are supposed to be displayed. It has to be of
        the format "<field>=<values>;<field>=<values>;...".

        The popup window will be resizable and scrollable.

        If the "property" arg is given, it's passed through to the
        javascript help_window function.

        You can use inputtype="radio" to display a radio box instead
        of the default checkbox (useful for entering Link-properties)

        If the "form" arg is given, it's passed through to the
        javascript help_window function. - it's the name of the form
        the "property" belongs to.
        """
        if properties is None:
            properties = sorted(self._klass.getprops(protected=0).keys())
            properties = ','.join(properties)
        if sort is None:
            if 'username' in properties.split(','):
                sort = 'username'
            else:
                sort = self._klass.orderprop()
        sort = '&amp;@sort=' + sort
        if group:
            group = '&amp;@group=' + group
        if property:
            property = '&amp;property=%s' % property
        if form:
            form = '&amp;form=%s' % form
        if inputtype:
            type = '&amp;type=%s' % inputtype
        if filter:
            filterprops = filter.split(';')
            filtervalues = []
            names = []
            for x in filterprops:
                (name, values) = x.split('=')
                names.append(name)
                filtervalues.append('&amp;%s=%s' % (name, urllib_.quote(values)))
            filter = '&amp;@filter=%s%s' % (','.join(names), ''.join(filtervalues))
        else:
            filter = ''
        help_url = "%s?@startwith=0&amp;@template=help&amp;"\
                   "properties=%s%s%s%s%s%s&amp;@pagesize=%s%s" % \
                   (self.classname, properties, property, form, type,
                    group, sort, pagesize, filter)
        onclick = "javascript:help_window('%s', '%s', '%s');return false;" % \
                  (help_url, width, height)

        if 'class' in html_kwargs:
            html_classes = ("classhelp %s" %
                            html_escape(str(html_kwargs["class"]), True))
            del html_kwargs["class"]
        else:
            html_classes = "classhelp"

        return ('<a class="%s" data-helpurl="%s" '
                'data-width="%s" data-height="%s" href="%s" '
                'target="_blank" onclick="%s" %s>%s</a>') % (
                    html_classes, help_url, width, height,
                    help_url, onclick, self.cgi_escape_attrs(**html_kwargs),
                    self._(label))

    def submit(self, label=''"Submit New Entry", action="new", html_kwargs={}):
        """ Generate a submit button (and action hidden element)

            "html_kwargs" specified additional html args for the
            generated html <select>

        Generate nothing if we're not editable.
        """
        if not self.is_edit_ok():
            return ''

        return \
            self.input(type="submit", name="submit_button",
                       value=self._(label), **html_kwargs) + \
            '\n' + \
            self.input(type="hidden", name="@csrf",
                       value=anti_csrf_nonce(self._client)) + \
            '\n' + \
            self.input(type="hidden", name="@action", value=action)

    def history(self, **args):
        if not self.is_view_ok():
            return self._('[hidden]')
        return self._('New node - no history')

    def renderWith(self, name, **kwargs):
        """ Render this class with the given template.
        """
        # create a new request and override the specified args
        req = HTMLRequest(self._client)
        req.classname = self.classname
        req.update(kwargs)

        # new template, using the specified classname and request
        # [ ] this code is too similar to client.renderContext()
        tplname = self._client.selectTemplate(self.classname, name)
        pt = self._client.instance.templates.load(tplname)

        # use our fabricated request
        args = {
            'ok_message': self._client._ok_message,
            'error_message': self._client._error_message
        }
        return pt.render(self._client, self.classname, req, **args)


class _HTMLItem(HTMLInputMixin, HTMLPermissions):
    """ Accesses through an *item*
    """
    def __init__(self, client, classname, nodeid, anonymous=0):
        self._client = client
        self._db = client.db
        self._classname = classname
        self._nodeid = nodeid
        self._klass = self._db.getclass(classname)
        self._props = self._klass.getprops()

        # do we prefix the form items with the item's identification?
        self._anonymous = anonymous

        HTMLInputMixin.__init__(self)

    def is_edit_ok(self):
        """ Is the user allowed to Edit this item?
        """
        perm = self._db.security.hasPermission
        return perm('Web Access', self._client.userid) and perm(
            'Edit', self._client.userid, self._classname, itemid=self._nodeid)

    def is_retire_ok(self):
        """ Is the user allowed to Reture this item?
        """
        perm = self._db.security.hasPermission
        return perm('Web Access', self._client.userid) and perm(
            'Retire', self._client.userid, self._classname,
            itemid=self._nodeid)

    def is_restore_ok(self):
        """ Is the user allowed to restore this item?
        """
        perm = self._db.security.hasPermission
        return perm('Web Access', self._client.userid) and perm(
            'Restore', self._client.userid, self._classname,
            itemid=self._nodeid)

    def is_view_ok(self):
        """ Is the user allowed to View this item?
        """
        perm = self._db.security.hasPermission
        if perm('Web Access', self._client.userid) and perm(
                'View', self._client.userid, self._classname,
                itemid=self._nodeid):
            return 1
        return self.is_edit_ok()

    def is_only_view_ok(self):
        """ Is the user only allowed to View (ie. not Edit) this item?
        """
        return self.is_view_ok() and not self.is_edit_ok()

    def __repr__(self):
        return '<HTMLItem(0x%x) %s %s>' % (id(self), self._classname,
                                           self._nodeid)

    def __getitem__(self, item):
        """ return an HTMLProperty instance
            this now can handle transitive lookups where item is of the
            form x.y.z
        """
        if item == 'id':
            return self._nodeid

        items = item.split('.', 1)
        has_rest = len(items) > 1

        # get the property
        prop = self._props[items[0]]

        if has_rest and not isinstance(prop, (hyperdb.Link, hyperdb.Multilink)):
            raise KeyError(item)

        # get the value, handling missing values
        value = None
        try:
            if int(self._nodeid) > 0:
                value = self._klass.get(self._nodeid, items[0], None,
                                        allow_abort=False)
        except (IndexError, ValueError):
            value = self._nodeid
        if value is None:
            if isinstance(prop, hyperdb.Multilink):
                value = []

        # look up the correct HTMLProperty class
        htmlprop = None
        for klass, htmlklass in propclasses:
            if isinstance(prop, klass):
                htmlprop = htmlklass(self._client, self._classname,
                                     self._nodeid, prop, items[0],
                                     value, self._anonymous)
        if htmlprop is not None:
            if has_rest:
                if isinstance(htmlprop, MultilinkHTMLProperty):
                    return [h[items[1]] for h in htmlprop]
                return htmlprop[items[1]]
            return htmlprop

        raise KeyError(item)

    def __getattr__(self, attr):
        """ convenience access to properties """
        try:
            return self[attr]
        except KeyError:
            raise AttributeError(attr)

    def designator(self):
        """Return this item's designator (classname + id)."""
        return '%s%s' % (self._classname, self._nodeid)

    def is_retired(self):
        """Is this item retired?"""
        return self._klass.is_retired(self._nodeid, allow_abort=False)

    def submit(self, label=''"Submit Changes", action="edit", html_kwargs={}):
        """Generate a submit button.

            "html_kwargs" specified additional html args for the
            generated html <select>

        Also sneak in the lastactivity and action hidden elements.
        """
        return \
            self.input(type="submit", name="submit_button",
                       value=self._(label), **html_kwargs) + \
            '\n' + \
            self.input(type="hidden", name="@lastactivity",
                       value=self.activity.local(0)) + \
            '\n' + \
            self.input(type="hidden", name="@csrf",
                       value=anti_csrf_nonce(self._client)) + \
            '\n' + \
            self.input(type="hidden", name="@action", value=action)

    def journal(self, direction='descending'):
        """ Return a list of HTMLJournalEntry instances.
        """
        # XXX do this
        return []

    def history(self, direction='descending', dre=re.compile(r'^\d+$'),
                limit=None, showall=False):
        """Create an html view of the journal for the item.

           Display property changes for all properties that does not have quiet set.
           If showall=True then all properties regardless of quiet setting will be
           shown.
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        # history should only use database values not current
        # form values. Disable form_wins for the body of the
        # function. Reset it to original value on return.
        orig_form_wins = self._client.form_wins
        self._client.form_wins = False

        # get the journal, sort and reverse
        history = self._klass.history(self._nodeid, skipquiet=(not showall))
        history.sort(key=lambda a: a[:3])
        history.reverse()

        # restrict the volume
        if limit:
            history = history[:limit]

        timezone = self._db.getUserTimezone()
        l = []
        current = {}
        comments = {}
        for _id, evt_date, user, action, args in history:
            date_s = str(evt_date.local(timezone)).replace(".", " ")
            arg_s = ''
            if action in ['link', 'unlink'] and isinstance(args, tuple):
                if len(args) == 3:
                    linkcl, linkid, key = args
                    arg_s += '<a rel="nofollow noopener" href="%s%s">%s%s %s</a>' % (
                        linkcl, linkid, linkcl, linkid, key)
                else:
                    arg_s = str(args)
            elif isinstance(args, dict):
                cell = []
                for k in args.keys():
                    # try to get the relevant property and treat it
                    # specially
                    try:
                        prop = self._props[k]
                    except KeyError:
                        prop = None
                    if prop is None:
                        # property no longer exists
                        comments['no_exist'] = self._(
                            "<em>The indicated property no longer exists</em>")
                        cell.append('<em>%s: %s</em>\n'
                                    % (self._(k), str(args[k])))
                        continue

                    # load the current state for the property (if we
                    # haven't already)
                    if k not in current:
                        val = self[k]
                        if not isinstance(val, HTMLProperty):
                            current[k] = None
                        else:
                            current[k] = val.plain(escape=1)
                            # make link if hrefable
                            if (isinstance(prop, hyperdb.Link)):
                                classname = prop.classname
                                try:
                                    template = self._client.selectTemplate(classname, 'item')
                                    if template.startswith('_generic.'):
                                        raise NoTemplate('not really...')
                                except NoTemplate:
                                    pass
                                else:
                                    linkid = self._klass.get(self._nodeid, k, None)
                                    current[k] = '<a rel="nofollow noopener" href="%s%s">%s</a>' % (
                                        classname, linkid, current[k])

                    if args[k] and (isinstance(prop, hyperdb.Multilink) or
                                    isinstance(prop, hyperdb.Link)):
                        # figure what the link class is
                        classname = prop.classname
                        try:
                            linkcl = self._db.getclass(classname)
                        except KeyError:
                            labelprop = None
                            comments[classname] = self._(
                                "The linked class %(classname)s no longer exists"
                            ) % locals()
                        labelprop = linkcl.labelprop(1)
                        try:
                            template = self._client.selectTemplate(classname,
                                                                   'item')
                            if template.startswith('_generic.'):
                                raise NoTemplate('not really...')
                            hrefable = 1
                        except NoTemplate:
                            hrefable = 0

                    if isinstance(prop, hyperdb.Multilink) and args[k]:
                        ml = []
                        for linkid in args[k]:
                            if isinstance(linkid, type(())):
                                sublabel = linkid[0] + ' '
                                linkids = linkid[1]
                            else:
                                sublabel = ''
                                linkids = [linkid]
                            subml = []
                            for linkid in linkids:
                                # We're seeing things like
                                # {'nosy':['38', '113', None, '82']} in the wild
                                if linkid is None:
                                    continue
                                label = classname + linkid
                                # if we have a label property, try to use it
                                # TODO: test for node existence even when
                                # there's no labelprop!
                                try:
                                    if labelprop is not None and \
                                            labelprop != 'id':
                                        label = linkcl.get(
                                            linkid, labelprop,
                                            default=self._(
                                                "[label is missing]"))
                                        label = html_escape(label)
                                except IndexError:
                                    comments['no_link'] = self._(
                                        "<strike>The linked node"
                                        " no longer exists</strike>")
                                    subml.append('<strike>%s</strike>' % label)
                                else:
                                    if hrefable:
                                        subml.append(
                                            '<a rel="nofollow noopener" '
                                            'href="%s%s">%s</a>' % (
                                                classname, linkid, label))
                                    elif label is None:
                                        subml.append('%s%s' % (classname,
                                                               linkid))
                                    else:
                                        subml.append(label)
                            ml.append(sublabel + ', '.join(subml))
                        cell.append('%s:\n  %s' % (self._(k), ', '.join(ml)))
                    elif isinstance(prop, hyperdb.Link) and args[k]:
                        label = classname + args[k]
                        # if we have a label property, try to use it
                        # TODO: test for node existence even when
                        # there's no labelprop!
                        if labelprop is not None and labelprop != 'id':
                            try:
                                label = html_escape(
                                    linkcl.get(args[k],
                                               labelprop, default=self._(
                                                   "[label is missing]")))
                            except IndexError:
                                comments['no_link'] = self._(
                                    "<strike>The linked node"
                                    " no longer exists</strike>")
                                cell.append(' <strike>%s</strike>,\n' % label)
                                # "flag" this is done .... euwww
                                label = None
                        if label is not None:
                            if hrefable:
                                old = '<a rel="nofollow noopener" href="%s%s">%s</a>' % (
                                    classname, args[k], label)
                            else:
                                old = label
                            cell.append('%s: %s' % (self._(k), old))
                            if k in current and current[k] is not None:
                                cell[-1] += ' -> %s' % current[k]
                                current[k] = old

                    elif isinstance(prop, hyperdb.Date) and args[k]:
                        if args[k] is None:
                            d = ''
                        else:
                            d = date.Date(
                                args[k],
                                translator=self._client).local(timezone)
                        cell.append('%s: %s' % (self._(k), str(d)))
                        if k in current and current[k] is not None:
                            cell[-1] += ' -> %s' % current[k]
                            current[k] = str(d)

                    elif isinstance(prop, hyperdb.Interval) and args[k]:
                        val = str(date.Interval(args[k],
                                                translator=self._client))
                        cell.append('%s: %s' % (self._(k), val))
                        if k in current and current[k] is not None:
                            cell[-1] += ' -> %s' % current[k]
                            current[k] = val

                    elif isinstance(prop, hyperdb.String) and args[k]:
                        val = html_escape(args[k])
                        cell.append('%s: %s' % (self._(k), val))
                        if k in current and current[k] is not None:
                            cell[-1] += ' -> %s' % current[k]
                            current[k] = val

                    elif isinstance(prop, hyperdb.Boolean) and args[k] is not None:
                        val = args[k] and ''"Yes" or ''"No"
                        cell.append('%s: %s' % (self._(k), val))
                        if k in current and current[k] is not None:
                            cell[-1] += ' -> %s' % current[k]
                            current[k] = val

                    elif isinstance(prop, hyperdb.Password) and args[k] is not None:
                        val = args[k].dummystr()
                        cell.append('%s: %s' % (self._(k), val))
                        if k in current and current[k] is not None:
                            cell[-1] += ' -> %s' % current[k]
                            current[k] = val

                    elif not args[k]:
                        if k in current and current[k] is not None:
                            cell.append('%s: %s' % (self._(k), current[k]))
                            current[k] = '(no value)'
                        else:
                            cell.append(self._('%s: (no value)') % self._(k))

                    else:
                        cell.append('%s: %s' % (self._(k), str(args[k])))
                        if k in current and current[k] is not None:
                            cell[-1] += ' -> %s' % current[k]
                            current[k] = str(args[k])

                arg_s = '<br />'.join(cell)
            else:
                if action in ('retired', 'restored'):
                    # args = None for these actions
                    pass
                else:
                    # unknown event!!
                    comments['unknown'] = self._(
                        "<strong><em>This event %s is not handled"
                        " by the history display!</em></strong>" % action)
                    arg_s = '<strong><em>' + str(args) + '</em></strong>'

            date_s = date_s.replace(' ', '&nbsp;')
            # if the user's an itemid, figure the username (older journals
            # have the username)
            if dre.match(user):
                user = self._db.user.get(user, 'username')
            l.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                date_s, html_escape(user), self._(action), arg_s))
        if comments:
            l.append(self._(
                '<tr><td colspan=4><strong>Note:</strong></td></tr>'))
        for entry in comments.values():
            l.append('<tr><td colspan=4>%s</td></tr>' % entry)

        if direction == 'ascending':
            l.reverse()

        l[0:0] = ['<table class="history table table-condensed table-striped">'
                  '<tr><th colspan="4" class="header">',
                  self._('History'),
                  '</th></tr><tr>',
                  self._('<th>Date</th>'),
                  self._('<th>User</th>'),
                  self._('<th>Action</th>'),
                  self._('<th>Args</th>'),
                  '</tr>']
        l.append('</table>')

        self._client.form_wins = orig_form_wins

        return '\n'.join(l)

    def renderQueryForm(self):
        """ Render this item, which is a query, as a search form.
        """
        # create a new request and override the specified args
        req = HTMLRequest(self._client)
        req.classname = self._klass.get(self._nodeid, 'klass')
        name = self._klass.get(self._nodeid, 'name')
        req.updateFromURL(self._klass.get(self._nodeid, 'url') +
                          '&@queryname=%s' % urllib_.quote(name))

        # new template, using the specified classname and request
        # [ ] the custom logic for search page doesn't belong to
        #     generic templating module (techtonik)
        tplname = self._client.selectTemplate(req.classname, 'search')
        pt = self._client.instance.templates.load(tplname)
        # The context for a search page should be the class, not any
        # node.
        self._client.nodeid = None

        # use our fabricated request
        return pt.render(self._client, req.classname, req)

    def download_url(self):
        """ Assume that this item is a FileClass and that it has a name
        and content. Construct a URL for the download of the content.
        """
        name = self._klass.get(self._nodeid, 'name')
        url = '%s%s/%s' % (self._classname, self._nodeid, name)
        return urllib_.quote(url)

    def copy_url(self, exclude=("messages", "files")):
        """Construct a URL for creating a copy of this item

        "exclude" is an optional list of properties that should
        not be copied to the new object.  By default, this list
        includes "messages" and "files" properties.  Note that
        "id" property cannot be copied.

        """
        exclude = ("id", "activity", "actor", "creation", "creator") \
            + tuple(exclude)
        query = {
            "@template": "item",
            "@note": self._("Copy of %(class)s %(id)s") % {
                "class": self._(self._classname), "id": self._nodeid},
        }
        for name in self._props.keys():
            if name not in exclude:
                prop = self._props[name]
                if not isinstance(prop, hyperdb.Multilink):
                    query[name] = self[name].plain()
                else:
                    query[name] = ",".join(self._klass.get(self._nodeid, name))

        return self._classname + "?" + "&".join(
            ["%s=%s" % (key, urllib_.quote(value))
                for key, value in query.items()])


class _HTMLUser(_HTMLItem):
    """Add ability to check for permissions on users.
    """
    _marker = ('_HTMLUserMarker')

    def hasPermission(self, permission, classname=_marker,
                      property=None, itemid=None):
        """Determine if the user has the Permission.

        The class being tested defaults to the template's class, but may
        be overidden for this test by suppling an alternate classname.
        """
        if classname is self._marker:
            classname = self._client.classname
        return self._db.security.hasPermission(
            permission, self._nodeid, classname, property, itemid)

    def hasRole(self, *rolenames):
        """Determine whether the user has any role in rolenames."""
        return self._db.user.has_role(self._nodeid, *rolenames)


def HTMLItem(client, classname, nodeid, anonymous=0):
    if classname == 'user':
        return _HTMLUser(client, classname, nodeid, anonymous)
    else:
        return _HTMLItem(client, classname, nodeid, anonymous)


class HTMLProperty(HTMLInputMixin, HTMLPermissions):
    """ String, Integer, Number, Date, Interval HTMLProperty

        Has useful attributes:

         _name  the name of the property
         _value the value of the property if any

        A wrapper object which may be stringified for the plain() behaviour.
    """
    def __init__(self, client, classname, nodeid, prop, name, value,
                 anonymous=0):
        self._client = client
        self._db = client.db
        self._ = client._
        self._classname = classname
        self._nodeid = nodeid
        self._prop = prop
        self._value = value
        self._anonymous = anonymous
        self._name = name
        if not anonymous:
            if nodeid:
                self._formname = '%s%s@%s' % (classname, nodeid, name)
            else:
                # This case occurs when creating a property for a
                # non-anonymous class.
                self._formname = '%s@%s' % (classname, name)
        else:
            self._formname = name

        # If no value is already present for this property, see if one
        # is specified in the current form.
        form = self._client.form
        try:
            is_in = self._formname in form
        except TypeError:
            is_in = False
        if is_in and (not self._value or self._client.form_wins):
            if isinstance(prop, hyperdb.Multilink):
                value = lookupIds(self._db, prop,
                                  handleListCGIValue(form[self._formname]),
                                  fail_ok=1)
            elif isinstance(prop, hyperdb.Link):
                value = form.getfirst(self._formname).strip()
                if value:
                    value = lookupIds(self._db, prop, [value],
                                      fail_ok=1)[0]
                else:
                    value = None
            else:
                value = form.getfirst(self._formname).strip() or None
            self._value = value

        # if self._value is None see if we have a default value
        if self._value is None:
            self._value = prop.get_default_value()

        HTMLInputMixin.__init__(self)

    def __repr__(self):
        classname = self.__class__.__name__
        return '<%s(0x%x) %s %r %r>' % (classname, id(self), self._formname,
                                        self._prop, self._value)

    def __str__(self):
        return self.plain()

    def __lt__(self, other):
        if isinstance(other, HTMLProperty):
            return self._value < other._value
        return self._value < other

    def __le__(self, other):
        if isinstance(other, HTMLProperty):
            return self._value <= other._value
        return self._value <= other

    def __eq__(self, other):
        if isinstance(other, HTMLProperty):
            return self._value == other._value
        return self._value == other

    def __ne__(self, other):
        if isinstance(other, HTMLProperty):
            return self._value != other._value
        return self._value != other

    def __gt__(self, other):
        if isinstance(other, HTMLProperty):
            return self._value > other._value
        return self._value > other

    def __ge__(self, other):
        if isinstance(other, HTMLProperty):
            return self._value >= other._value
        return self._value >= other

    def __bool__(self):
        return not not self._value
    # Python 2 compatibility:
    __nonzero__ = __bool__

    def isset(self):
        """Is my _value not None?"""
        return self._value is not None

    def is_edit_ok(self):
        """Should the user be allowed to use an edit form field for this
        property. Check "Create" for new items, or "Edit" for existing
        ones.
        """
        perm = self._db.security.hasPermission
        userid = self._client.userid
        if self._nodeid:
            if not perm('Web Access', userid):
                return False
            return perm('Edit', userid, self._classname, self._name,
                        self._nodeid)
        return perm('Create', userid, self._classname, self._name) or \
            perm('Register', userid, self._classname, self._name)

    def is_view_ok(self):
        """ Is the user allowed to View the current class?
        """
        perm = self._db.security.hasPermission
        if perm('Web Access',  self._client.userid) and perm(
                'View', self._client.userid, self._classname,
                self._name, self._nodeid):
            return 1
        return self.is_edit_ok()


class StringHTMLProperty(HTMLProperty):
    hyper_re = re.compile(r'''(
        (?P<url>
         (
          (ht|f)tp(s?)://                   # protocol
          ([\w]+(:\w+)?@)?                  # username/password
          ([\w\-]+)                         # hostname
          ((\.[\w-]+)+)?                    # .domain.etc
         |                                  # ... or ...
          ([\w]+(:\w+)?@)?                  # username/password
          www\.                             # "www."
          ([\w\-]+\.)+                      # hostname
          [\w]{2,5}                         # TLD
         )
         (:[\d]{1,5})?                     # port
         (/[\w\-$.+!*(),;:@&=?/~\\#%]*)?   # path etc.
        )|
        (?P<email>(?:mailto:)?[-+=%/\w\.]+@[\w\.\-]+)|
        (?P<item>(?P<class>[A-Za-z_]+)(\s*)(?P<id>\d+)(?P<fragment>\#[^][\#%^{}"<>\s]+)?)
    )''', re.X | re.I)
    protocol_re = re.compile('^(ht|f)tp(s?)://', re.I)

    # disable rst directives that have security implications
    rst_defaults = {'file_insertion_enabled': 0,
                    'raw_enabled': 0,
                    '_disable_config': 1}

    valid_schemes = {}

    def _hyper_repl(self, match):
        if match.group('url'):
            return self._hyper_repl_url(match, '<a href="%s" rel="nofollow noopener">%s</a>%s')
        elif match.group('email'):
            return self._hyper_repl_email(match, '<a href="mailto:%s">%s</a>')
        elif len(match.group('id')) < 10:
            return self._hyper_repl_item(
                match, '<a href="%(cls)s%(itemid)s%(fragment)s">%(item)s</a>')
        else:
            # just return the matched text
            return match.group(0)

    def _hyper_repl_url(self, match, replacement):
        u = s = match.group('url')
        if not self.protocol_re.search(s):
            u = 'http://' + s
        end = ''
        if '&gt;' in s:
            # catch an escaped ">" in the URL
            pos = s.find('&gt;')
            end = s[pos:]
            u = s = s[:pos]
        if s.endswith(tuple('.,;:!')):
            # don't include trailing punctuation
            end = s[-1:] + end
            u = s = s[:-1]
        if ')' in s and s.count('(') != s.count(')'):
            # don't include extraneous ')' in the link
            pos = s.rfind(')')
            end = s[pos:] + end
            u = s = s[:pos]
        return replacement % (u, s, end)

    def _hyper_repl_email(self, match, replacement):
        s = match.group('email')
        return replacement % (s, s)

    def _hyper_repl_item(self, match, replacement):
        item = match.group('item')
        cls = match.group('class').lower()
        itemid = match.group('id')
        fragment = match.group('fragment')
        if fragment is None:
            fragment = ""
        try:
            # make sure cls is a valid tracker classname
            cl = self._db.getclass(cls)
            if not cl.hasnode(itemid):
                return item
            return replacement % locals()
        except KeyError:
            return item

    def _hyper_repl_rst(self, match):
        if match.group('url'):
            s = match.group('url')
            return '`%s <%s>`_' % (s, s)
        elif match.group('email'):
            s = match.group('email')
            return '`%s <mailto:%s>`_' % (s, s)
        elif len(match.group('id')) < 10:
            return self._hyper_repl_item(match, '`%(item)s <%(cls)s%(itemid)s>`_')
        else:
            # just return the matched text
            return match.group(0)

    def _hyper_repl_markdown(self, match):
        for group in ['url', 'email']:
            if match.group(group):
                start = match.start(group) - 1
                end = match.end(group)
                if start >= 0:
                    prefix = match.string[start]
                    if end < len(match.string):
                        suffix = match.string[end]
                        if (prefix, suffix) in {
                                ('<', '>'),
                                ('(', ')'),
                                }:
                            continue
                    if prefix == '(' and ')' in match.group(group):
                        continue
                s = match.group(group)
                return '<%s>' % s
        if match.group('id') and len(match.group('id')) < 10:
            # Pass through markdown style links:
            #     [issue1](https://....)
            #     [issue1](issue1)
            # as 'issue1'. Don't convert issue1 into a link.
            # https://issues.roundup-tracker.org/issue2551108
            start = match.start('item') - 1
            end = match.end('item')
            if start >= 0:
                prefix = match.string[start]
                if end < len(match.string):
                    suffix = match.string[end]
                    if (prefix, suffix) in {('[', ']')}:
                        if match.string[end+1] == '(':  # find following (
                            return match.group(0)
                    if (prefix, suffix) in {('(', ')')}:
                        if match.string[start-1] == ']':
                            return match.group(0)
            return self._hyper_repl_item(match, '[%(item)s](%(cls)s%(itemid)s)')
        else:
            # just return the matched text
            return match.group(0)

    def url_quote(self):
        """ Return the string in plain format but escaped for use in a url """
        return urllib_.quote(self.plain())

    def hyperlinked(self):
        """ Render a "hyperlinked" version of the text """
        return self.plain(hyperlink=1)

    def plain(self, escape=0, hyperlink=0):
        """Render a "plain" representation of the property

        - "escape" turns on/off HTML quoting
        - "hyperlink" turns on/off in-text hyperlinking of URLs, email
          addresses and designators
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            return ''
        if escape:
            s = html_escape(str(self._value))
        else:
            s = str(self._value)
        if hyperlink:
            # no, we *must* escape this text
            if not escape:
                s = html_escape(s)
            s = self.hyper_re.sub(self._hyper_repl, s)
        return s

    def wrapped(self, escape=1, hyperlink=1, columns=80):
        """Render a "wrapped" representation of the property.

        We wrap long lines at 80 columns on the nearest whitespace. Lines
        with no whitespace are not broken to force wrapping.

        Note that unlike plain() we default wrapped() to have the escaping
        and hyperlinking turned on since that's the most common usage.

        - "escape" turns on/off HTML quoting
        - "hyperlink" turns on/off in-text hyperlinking of URLs, email
          addresses and designators
        - "columns" sets the column where the wrapping will occur.
          Default of 80.
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            return ''
        s = '\n'.join(textwrap.wrap(str(self._value), columns,
                                    break_long_words=False))
        if escape:
            s = html_escape(s)
        if hyperlink:
            # no, we *must* escape this text
            if not escape:
                s = html_escape(s)
            s = self.hyper_re.sub(self._hyper_repl, s)
        return s

    def rst(self, hyperlink=1):
        """ Render the value of the property as ReStructuredText.

            This requires docutils to be installed separately.
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if not ReStructuredText:
            return self.plain(escape=0, hyperlink=hyperlink)
        s = self.plain(escape=0, hyperlink=0)
        if hyperlink:
            s = self.hyper_re.sub(self._hyper_repl_rst, s)

        # disable javascript and possibly other url schemes from working
        from docutils.utils.urischemes import schemes
        for sch in _disable_url_schemes:
            # I catch KeyError but reraise if scheme didn't exist.
            # Safer to fail if a disabled scheme isn't found. It may
            # be a typo that keeps a bad scheme enabled. But this
            # function can be called multiple times. On the first call
            # the key will be deleted. On the second call the schemes
            # variable isn't re-initialized so the key is missing
            # causing a KeyError. So see if we removed it (and entered
            # it into valid_schemes). If we didn't raise KeyError.
            try:
                del (schemes[sch])
                self.valid_schemes[sch] = True
            except KeyError:
                if sch in self.valid_schemes:
                    pass
                else:
                    raise

        return u2s(ReStructuredText(
            s, writer_name="html",
            settings_overrides=self.rst_defaults)["html_body"])

    def markdown(self, hyperlink=1):
        """ Render the value of the property as markdown.

            This requires markdown2 or markdown to be installed separately.
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if not markdown:
            return self.plain(escape=0, hyperlink=hyperlink)
        s = self.plain(escape=0, hyperlink=0)
        if hyperlink:
            s = self.hyper_re.sub(self._hyper_repl_markdown, s)
        try:
            s = u2s(markdown(s2u(s), self._db.config))
        except Exception:  # when markdown formatting fails return markup
            return self.plain(escape=0, hyperlink=hyperlink)
        return s

    def field(self, **kwargs):
        """ Render the property as a field in HTML.

            If not editable, just display the value via plain().
        """
        if not self.is_edit_ok():
            return self.plain(escape=1)

        value = self._value
        if value is None:
            value = ''

        kwargs.setdefault("size", 30)
        kwargs.update({"name": self._formname, "value": value})
        return self.input(**kwargs)

    def multiline(self, escape=0, rows=5, cols=40, **kwargs):
        """ Render a multiline form edit field for the property.

            If not editable, just display the plain() value in a <pre> tag.
        """
        if not self.is_edit_ok():
            return '<pre>%s</pre>' % self.plain()

        if self._value is None:
            value = ''
        else:
            value = html_escape(str(self._value))

            value = '&quot;'.join(value.split('"'))
        name = self._formname
        passthrough_args = self.cgi_escape_attrs(**kwargs)
        return ('<textarea %(passthrough_args)s name="%(name)s" id="%(name)s"'
                ' rows="%(rows)s" cols="%(cols)s">'
                '%(value)s</textarea>') % locals()

    def email(self, escape=1):
        """ Render the value of the property as an obscured email address
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            value = ''
        else:
            value = str(self._value)
        split = value.split('@')
        if len(split) == 2:
            name, domain = split
            domain = ' '.join(domain.split('.')[:-1])
            name = name.replace('.', ' ')
            value = '%s at %s ...' % (name, domain)
        else:
            value = value.replace('.', ' ')
        if escape:
            value = html_escape(value)
        return value


class PasswordHTMLProperty(HTMLProperty):
    def plain(self, escape=0):
        """ Render a "plain" representation of the property
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            return ''
        try:
            value = self._value.dummystr()
        except AttributeError:
            value = self._('[hidden]')
        if escape:
            value = html_escape(value)
        return value

    def field(self, size=30, **kwargs):
        """ Render a form edit field for the property.

            If not editable, just display the value via plain().
        """
        if not self.is_edit_ok():
            return self.plain(escape=1)

        return self.input(type="password", name=self._formname, size=size,
                          **kwargs)

    def confirm(self, size=30):
        """ Render a second form edit field for the property, used for
            confirmation that the user typed the password correctly. Generates
            a field with name "@confirm@name".

            If not editable, display nothing.
        """
        if not self.is_edit_ok():
            return ''

        return self.input(type="password",
                          name="@confirm@%s" % self._formname,
                          id="%s-confirm" % self._formname,
                          size=size)


class NumberHTMLProperty(HTMLProperty):
    def plain(self, escape=0):
        """ Render a "plain" representation of the property
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            return ''

        return str(self._value)

    def pretty(self, format="%0.3f"):
        '''Pretty print number using printf format specifier.

           If value is not convertable, returns str(_value) or ""
           if None.
        '''
        try:
            return format % self._value
        except TypeError:
            value = self._value
            if value is None:
                return ''
            else:
                return str(value)

    def field(self, size=30, **kwargs):
        """ Render a form edit field for the property.

            If not editable, just display the value via plain().
        """
        if not self.is_edit_ok():
            return self.plain(escape=1)

        value = self._value
        if value is None:
            value = ''

        if self._client.db.config.WEB_USE_BROWSER_NUMBER_INPUT:
            kwargs.setdefault("type", "number")
        else:
            kwargs.setdefault("type", "text")
        return self.input(name=self._formname, value=value, size=size,
                          **kwargs)

    def __int__(self):
        """ Return an int of me
        """
        return int(self._value)

    def __float__(self):
        """ Return a float of me
        """
        return float(self._value)


class IntegerHTMLProperty(HTMLProperty):
    def plain(self, escape=0):
        """ Render a "plain" representation of the property
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            return ''

        return str(self._value)

    def field(self, size=30, **kwargs):
        """ Render a form edit field for the property.

            If not editable, just display the value via plain().
        """
        if not self.is_edit_ok():
            return self.plain(escape=1)

        value = self._value
        if value is None:
            value = ''

        if self._client.db.config.WEB_USE_BROWSER_NUMBER_INPUT:
            kwargs.setdefault("type", "number")
        else:
            kwargs.setdefault("type", "text")
        if kwargs['type'] == "number":
            kwargs.setdefault("step", "1")
        return self.input(name=self._formname, value=value, size=size, **kwargs)

    def __int__(self):
        """ Return an int of me
        """
        return int(self._value)


class BooleanHTMLProperty(HTMLProperty):
    def plain(self, escape=0):
        """ Render a "plain" representation of the property
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            return ''
        return self._value and self._("Yes") or self._("No")

    def field(self, labelfirst=False, y_label=None, n_label=None,
              u_label=None, **kwargs):
        """ Render a form edit field for the property

            If not editable, just display the value via plain().

            In addition to being able to set arbitrary html properties
            using prop=val arguments, the three arguments:

              y_label, n_label, u_label let you control the labels
              associated with the yes, no (and optionally unknown/empty)
              values.

           Also the labels can be placed before the radiobuttons by setting
           labelfirst=True.
        """
        if not self.is_edit_ok():
            return self.plain(escape=1)

        value = self._value
        if is_us(value):
            value = value.strip().lower() in ('checked', 'yes', 'true',
                                              'on', '1')

        if (not y_label):
            y_label = '<label class="rblabel" for="%s_%s">' % (
                self._formname, 'yes')
            y_label += self._('Yes')
            y_label += '</label>'

        if (not n_label):
            n_label = '<label class="rblabel" for="%s_%s">' % (
                self._formname, 'no')
            n_label += self._('No')
            n_label += '</label>'

        checked = value and "checked" or ""
        kwargs.setdefault("type", "radio")
        if value:
            y_rb = self.input(name=self._formname, value="yes",
                              checked="checked", id="%s_%s" % (
                                  self._formname, 'yes'), **kwargs)

            n_rb = self.input(name=self._formname,  value="no",
                              id="%s_%s" % (
                                  self._formname, 'no'), **kwargs)
        else:
            y_rb = self.input(name=self._formname, value="yes",
                              id="%s_%s" % (self._formname, 'yes'), **kwargs)

            n_rb = self.input(name=self._formname,  value="no",
                              checked="checked", id="%s_%s" % (
                                  self._formname, 'no'), **kwargs)

        if (u_label):
            if (u_label is True):  # it was set via u_label=True
                u_label = ''       # make it empty but a string not boolean
            u_rb = self.input(name=self._formname,  value="",
                              id="%s_%s" % (self._formname, 'unk'), **kwargs)
        else:
            # don't generate a trivalue radiobutton.
            u_label = ''
            u_rb = ''

        if (labelfirst):
            s = u_label + u_rb + y_label + y_rb + n_label + n_rb
        else:
            s = u_label + u_rb + y_rb + y_label + n_rb + n_label

        return s


class DateHTMLProperty(HTMLProperty):

    _marker = ('HTMLPropertyMarker')

    def __init__(self, client, classname, nodeid, prop, name, value,
                 anonymous=0, offset=None, display_time=None, format=None):
        HTMLProperty.__init__(self, client, classname, nodeid, prop, name,
                              value, anonymous=anonymous)
        if self._value and not is_us(self._value):
            self._value.setTranslator(self._client.translator)
        self._offset = offset
        if self._offset is None:
            self._offset = self._prop.offset(self._db)
        self.display_time = display_time
        if self.display_time is None:
            self.display_time = self._prop.display_time
        self.format = format or self._prop.format

    def plain(self, escape=0):
        """ Render a "plain" representation of the property
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            return ''
        if self._offset is None:
            offset = self._db.getUserTimezone()
        else:
            offset = self._offset
        try:
            return str(self._value.local(offset))
        except AttributeError:
            # not a date value, e.g. from unsaved form data
            return str(self._value)

    def now(self, str_interval=None):
        """ Return the current time.

            This is useful for defaulting a new value. Returns a
            DateHTMLProperty.
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        ret = date.Date('.', translator=self._client)

        if is_us(str_interval):
            sign = 1
            if str_interval[0] == '-':
                sign = -1
                str_interval = str_interval[1:]
            interval = date.Interval(str_interval, translator=self._client)
            if sign > 0:
                ret = ret + interval
            else:
                ret = ret - interval

        return DateHTMLProperty(self._client, self._classname, self._nodeid,
                                self._prop, self._formname, ret)


    def field(self, size=30, default=None, format=_marker, popcal=None,
              display_time=None, form='itemSynopsis', **kwargs):
        """Render a form edit field for the property

        If not editable, just display the value via plain().

        If a format is specified or the use_browser_date_input config
        option is set to 'no' we use a type="text" input. Otherwise we
        use a type="date" or type="datetime-local" input depending on
        the setting of display_time.

        If "popcal" then include the Javascript calendar editor.
        Default=yes for text input fields, otherwise no.

        The format string is a standard python strftime format string.
        """
        if format is self._marker and self.format is not None:
            format = self.format
        if not self.is_edit_ok():
            if format is self._marker:
                return self.plain(escape=1)
            else:
                return self.pretty(format)

        if display_time is None:
            display_time = self.display_time
        use_date = self._client.db.config.WEB_USE_BROWSER_DATE_INPUT

        # https://developer.mozilla.org/en-US/docs/Web/HTML/Date_and_time_formats#local_date_and_time_strings
        if format is not self._marker or not use_date:
            kwargs ['type'] = "text"
            # popcal is None by default, only when explicitly turned off
            # do we use no popcal
            popcal = popcal != False
            # emulate display_time with old-style input
            if not display_time and format is self._marker:
                format = '%Y-%m-%d'
        else:
            if display_time:
                kwargs ['type'] = "datetime-local"
                format = '%Y-%m-%dT%H:%M:%S'
            else:
                kwargs ['type'] = "date"
                format = '%Y-%m-%d'
            popcal = False

        value = self._value

        if value is None:
            if default is None:
                raw_value = None
            else:
                if is_us(default):
                    raw_value = date.Date(default, translator=self._client)
                elif isinstance(default, date.Date):
                    raw_value = default
                elif isinstance(default, DateHTMLProperty):
                    raw_value = default._value
                else:
                    raise ValueError(self._(
                        'default value for '
                        'DateHTMLProperty must be either DateHTMLProperty '
                        'or string date representation.'))
        elif is_us(value):
            # most likely erroneous input to be passed back to user
            value = us2s(value)
            s = self.input(name=self._formname, value=value, size=size,
                           **kwargs)
            if popcal:
                s += self.popcal(form=form)
            return s
        else:
            raw_value = value

        if raw_value is None:
            value = ''
        elif is_us(raw_value):
            if format is self._marker:
                value = raw_value
            else:
                value = date.Date(raw_value).pretty(format)
        else:
            if self._offset is None:
                offset = self._db.getUserTimezone()
            else:
                offset = self._offset
            value = raw_value.local(offset)
            if format is not self._marker:
                value = value.pretty(format)

        s = self.input(name=self._formname, value=value, size=size,
                       **kwargs)
        if popcal:
            s += self.popcal(form=form)
        return s

    def reldate(self, pretty=1):
        """ Render the interval between the date and now.

            If the "pretty" flag is true, then make the display pretty.
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if not self._value:
            return ''

        # figure the interval
        interval = self._value - date.Date('.', translator=self._client)
        if pretty:
            return interval.pretty()
        return str(interval)

    def pretty(self, format=_marker):
        """ Render the date in a pretty format (eg. month names, spaces).

            The format string is a standard python strftime format string.
            Note that if the day is zero, and appears at the start of the
            string, then it'll be stripped from the output. This is handy
            for the situation when a date only specifies a month and a year.
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._offset is None:
            offset = self._db.getUserTimezone()
        else:
            offset = self._offset

        try:
            if not self._value:
                return ''
            elif format is not self._marker:
                return self._value.local(offset).pretty(format)
            else:
                return self._value.local(offset).pretty()
        except AttributeError:
            # not a date value, e.g. from unsaved form data
            return str(self._value)

    def local(self, offset):
        """ Return the date/time as a local (timezone offset) date/time.
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        return DateHTMLProperty(self._client, self._classname, self._nodeid,
                                self._prop, self._formname, self._value,
                                offset=offset)

    def popcal(self, width=300, height=200, label="(cal)",
               form="itemSynopsis"):
        """Generate a link to a calendar pop-up window.

        item: HTMLProperty e.g.: context.deadline
        """
        if self.isset():
            date = "&date=%s" % self._value
        else:
            date = ""

        data_attr = {
            "data-calurl": '%s?@template=calendar&property=%s&form=%s%s' % (
                self._classname, self._name, form, date),
            "data-width": width,
            "data-height": height
        }

        return ('<a class="classhelp" %s href="javascript:help_window('
                "'%s?@template=calendar&amp;property=%s&amp;form=%s%s', %d, %d)"
                '">%s</a>' % (self.cgi_escape_attrs(**data_attr),
                              self._classname, self._name, form, date, width,
                              height, label))


class IntervalHTMLProperty(HTMLProperty):
    def __init__(self, client, classname, nodeid, prop, name, value,
                 anonymous=0):
        HTMLProperty.__init__(self, client, classname, nodeid, prop,
                              name, value, anonymous)
        if self._value and not is_us(self._value):
            self._value.setTranslator(self._client.translator)

    def plain(self, escape=0):
        """ Render a "plain" representation of the property
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            return ''
        return str(self._value)

    def pretty(self):
        """ Render the interval in a pretty format (eg. "yesterday")
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        return self._value.pretty()

    def field(self, size=30, **kwargs):
        """ Render a form edit field for the property

            If not editable, just display the value via plain().
        """
        if not self.is_edit_ok():
            return self.plain(escape=1)

        value = self._value
        if value is None:
            value = ''

        return self.input(name=self._formname, value=value, size=size,
                          **kwargs)


class LinkHTMLProperty(HTMLProperty):
    """ Link HTMLProperty
        Include the above as well as being able to access the class
        information. Stringifying the object itself results in the value
        from the item being displayed. Accessing attributes of this object
        result in the appropriate entry from the class being queried for the
        property accessed (so item/assignedto/name would look up the user
        entry identified by the assignedto property on item, and then the
        name property of that user)
    """
    def __init__(self, *args, **kw):
        HTMLProperty.__init__(self, *args, **kw)
        # if we're representing a form value, then the -1 from the form really
        # should be a None
        if str(self._value) == '-1':
            self._value = None

    def __getattr__(self, attr):
        """ return a new HTMLItem """
        if not self._value:
            # handle a special page templates lookup
            if attr == '__render_with_namespace__':
                def nothing(*args, **kw):
                    return ''
                return nothing
            msg = self._('Attempt to look up %(attr)s on a missing value')
            return MissingValue(msg % locals())
        i = HTMLItem(self._client, self._prop.classname, self._value)
        return getattr(i, attr)

    def __getitem__(self, item):
        """Explicitly define __getitem__ -- this used to work earlier
           due to __getattr__ returning the __getitem__ of HTMLItem -- this
           lookup doesn't work for new-style classes.
        """
        if not self._value:
            msg = self._('Attempt to look up %(item)s on a missing value')
            return MissingValue(msg % locals())
        i = HTMLItem(self._client, self._prop.classname, self._value)
        return i[item]

    def plain(self, escape=0):
        """ Render a "plain" representation of the property
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            return ''
        linkcl = self._db.classes[self._prop.classname]
        k = linkcl.labelprop(1)
        if num_re.match(self._value):
            try:
                value = str(linkcl.get(self._value, k,
                                       default=self._("[label is missing]")))
            except IndexError:
                value = self._value
        else:
            value = self._value
        if escape:
            value = html_escape(value)
        return value

    def field(self, showid=0, size=None, **kwargs):
        """ Render a form edit field for the property

            If not editable, just display the value via plain().
        """
        if not self.is_edit_ok():
            return self.plain(escape=1)

        # edit field
        linkcl = self._db.getclass(self._prop.classname)
        if self._value is None:
            value = ''
        else:
            k = linkcl.getkey()
            idparse = self._prop.try_id_parsing
            if k and num_re.match(self._value):
                try:
                    value = linkcl.get(self._value, k, allow_abort=False)
                except (IndexError, hyperdb.HyperdbValueError) as err:
                    if idparse:
                        self._client.add_error_message(str(err))
                    value = ''
            else:
                value = self._value
        return self.input(name=self._formname, value=value, size=size,
                          **kwargs)

    def menu(self, size=None, height=None, showid=0, additional=[], value=None,
             sort_on=None, html_kwargs={}, translate=True, showdef=None, **conditions):
        """ Render a form select list for this property

            "size" is used to limit the length of the list labels
            "height" is used to set the <select> tag's "size" attribute
            "showid" includes the item ids in the list labels
            "value" specifies which item is pre-selected
            "additional" lists properties which should be included in the
                label
            "sort_on" indicates the property to sort the list on as
                (direction, property) where direction is '+' or '-'. A
                single string with the direction prepended may be used.
                For example: ('-', 'order'), '+name'.
            "html_kwargs" specified additional html args for the
            generated html <select>
            "translate" indicates if we should do translation of labels
            using gettext -- this is often desired (e.g. for status
            labels) but sometimes not.
            "showdef" marks the default value with the string passed
                as the showdef argument. It is appended to the selected
                value so the user can reset the menu to the original value.
                Note that the marker may be removed if the length of
                the option label and the marker exceed the size.

            The remaining keyword arguments are used as conditions for
            filtering the items in the list - they're passed as the
            "filterspec" argument to a Class.filter() call.

            If not editable, just display the value via plain().
        """
        if not self.is_edit_ok():
            return self.plain(escape=1)

        # Since None indicates the default, we need another way to
        # indicate "no selection".  We use -1 for this purpose, as
        # that is the value we use when submitting a form without the
        # value set.
        if value is None:
            value = self._value
        elif value == '-1':
            value = None

        linkcl = self._db.getclass(self._prop.classname)
        html = ['<select %s>' % self.cgi_escape_attrs(name=self._formname,
                                                      **html_kwargs)]
        k = linkcl.labelprop(1)
        s = ''
        if value is None:
            s = 'selected="selected" '
        html.append(self._(
            '<option %svalue="-1">- no selection -</option>') % s)

        if sort_on is not None:
            if not isinstance(sort_on, tuple):
                if sort_on[0] in '+-':
                    sort_on = (sort_on[0], sort_on[1:])
                else:
                    sort_on = ('+', sort_on)
        else:
            sort_on = ('+', linkcl.orderprop())

        options = [opt
                   for opt in linkcl.filter(
                           None, conditions, sort_on, (None, None))
                   if self._db.security.hasPermission(
                           "View", self._client.userid, linkcl.classname,
                           itemid=opt)]

        # make sure we list the current value if it's retired
        if value and value not in options:
            options.insert(0, value)

        if additional:
            additional_fns = []
            props = linkcl.getprops()
            for propname in additional:
                prop = props[propname]
                if isinstance(prop, hyperdb.Link):
                    cl = self._db.getclass(prop.classname)
                    labelprop = cl.labelprop()
                    fn = lambda optionid, cl=cl, linkcl=linkcl, \
                                propname=propname, labelprop=labelprop: \
                            cl.get(linkcl.get(optionid, propname), labelprop)
                else:
                    fn = lambda optionid, linkcl=linkcl, propname=propname: \
                            linkcl.get(optionid, propname)
                additional_fns.append(fn)

        for optionid in options:
            # get the option value, and if it's None use an empty string
            try:
                option = linkcl.get(optionid, k) or ''
            except IndexError:
                # optionid does not exist. E.G.
                #   IndexError: no such queue z
                # can be set using ?queue=z in URL for
                # a new issue
                continue

            # figure if this option is selected
            s = ''
            # record the marker for the selected item if requested
            selected_mark = ''

            if value in [optionid, option]:
                s = 'selected="selected" '
                if (showdef):
                    selected_mark = showdef

            # figure the label
            if showid:
                lab = '%s%s: %s' % (self._prop.classname, optionid, option)
            elif not option:
                lab = '%s%s' % (self._prop.classname, optionid)
            else:
                lab = option

            lab = lab + selected_mark
            # truncate if it's too long
            if size is not None and len(lab) > size:
                lab = lab[:size-3] + '...'
            if additional:
                m = []
                for fn in additional_fns:
                    m.append(str(fn(optionid)))
                lab = lab + ' (%s)' % ', '.join(m)

            # and generate
            tr = str
            if translate:
                tr = self._
            lab = html_escape(tr(lab))
            html.append(
                '<option %svalue="%s">%s</option>' % (s, optionid, lab))
        html.append('</select>')
        return '\n'.join(html)

#    def checklist(self, ...)


class MultilinkHTMLProperty(HTMLProperty):
    """ Multilink HTMLProperty

        Also be iterable, returning a wrapper object like the Link case for
        each entry in the multilink.
    """
    def __init__(self, *args, **kwargs):
        HTMLProperty.__init__(self, *args, **kwargs)
        if self._value:
            display_value = lookupIds(self._db, self._prop, self._value,
                                      fail_ok=1, do_lookup=False)
            keyfun = make_key_function(self._db, self._prop.classname)
            # sorting fails if the value contains
            # items not yet stored in the database
            # ignore these errors to preserve user input
            try:
                display_value.sort(key=keyfun)
            except:
                pass
            self._value = display_value

    def __len__(self):
        """ length of the multilink """
        return len(self._value)

    def __getattr__(self, attr):
        """ no extended attribute accesses make sense here """
        raise AttributeError(attr)

    def viewableGenerator(self, values):
        """Used to iterate over only the View'able items in a class."""
        check = self._db.security.hasPermission
        userid = self._client.userid
        classname = self._prop.classname
        if check('Web Access', userid):
            for value in values:
                if check('View', userid, classname,
                         itemid=value,
                         property=self._db.getclass(classname).labelprop(default_to_id=1)):
                    yield HTMLItem(self._client, classname, value)

    def __iter__(self):
        """ iterate and return a new HTMLItem
        """
        return self.viewableGenerator(self._value)

    def reverse(self):
        """ return the list in reverse order
        """
        mylist = self._value[:]
        mylist.reverse()
        return self.viewableGenerator(mylist)

    def sorted(self, property, reverse=False, NoneFirst=False):
        """ Return this multilink sorted by the given property

            Set Nonefirst to True to sort None/unset property
            before a property with a valid value.

        """

        # use 2 if NoneFirst is False to sort None last
        # 0 to sort to sort None first
        # 1 is used to sort the integer values.
        NoneCode = (2, 0)[NoneFirst]

        value = list(self.__iter__())

        if not value:
            # return empty list, nothing to sort.
            return value

        # determine orderprop for property if property is a link or multilink
        prop = self._db.getclass(self._prop.classname).getprops()[property]
        if type(prop) in [hyperdb.Link, hyperdb.Multilink]:
            orderprop = value[0]._db.getclass(prop.classname).orderprop()
            sort_by_link = True
        else:
            orderprop = property
            sort_by_link = False

        def keyfunc(v):
            # Return tuples made of (group order (int), base python
            # type) to sort function.
            # Do not return v[property] as that returns an HTMLProperty
            # type/subtype that throws an exception when sorting
            # python type (int. str ...) against None.
            prop = v[property]
            if not prop._value:
                return (NoneCode, None)

            if sort_by_link:
                val = prop[orderprop]._value
            else:
                val = prop._value

            if val is None:   # verify orderprop is set to a value
                return (NoneCode, None)
            return (1, val)  # val should be base python type

        value.sort(key=keyfunc, reverse=reverse)
        return value

    def __contains__(self, value):
        """ Support the "in" operator. We have to make sure the passed-in
            value is a string first, not a HTMLProperty.
        """
        return str(value) in self._value

    def isset(self):
        """Is my _value not []?"""
        return self._value != []

    def plain(self, escape=0):
        """ Render a "plain" representation of the property
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        linkcl = self._db.classes[self._prop.classname]
        k = linkcl.labelprop(1)
        labels = []
        for v in self._value:
            if num_re.match(v):
                try:
                    label = linkcl.get(v, k,
                                       default=self._("[label is missing]"))
                except IndexError:
                    label = None
                # fall back to designator if label is None
                if label is None:
                    label = '%s%s' % (self._prop.classname, k)
            else:
                label = v
            labels.append(label)
        value = ', '.join(labels)
        if escape:
            value = html_escape(value)
        return value

    def field(self, size=30, showid=0, **kwargs):
        """ Render a form edit field for the property

            If not editable, just display the value via plain().
        """
        if not self.is_edit_ok():
            return self.plain(escape=1)

        linkcl = self._db.getclass(self._prop.classname)

        if 'value' not in kwargs:
            value = self._value[:]
            # map the id to the label property
            if not linkcl.getkey():
                showid = 1
            if not showid:
                k = linkcl.labelprop(1)
                try:
                    value = lookupKeys(linkcl, k, value)
                except (ValueError, IndexError) as err:
                    self._client.add_error_message (str(err))
            value = ','.join(value)
            kwargs["value"] = value

        return self.input(name=self._formname, size=size, **kwargs)

    def menu(self, size=None, height=None, showid=0, additional=[],
             value=None, sort_on=None, html_kwargs={}, translate=True,
             **conditions):
        """ Render a form <select> list for this property.

            "size" is used to limit the length of the list labels
            "height" is used to set the <select> tag's "size" attribute
            "showid" includes the item ids in the list labels
            "additional" lists properties which should be included in the
                label
            "value" specifies which item is pre-selected
            "sort_on" indicates the property to sort the list on as
                (direction, property) where direction is '+' or '-'. A
                single string with the direction prepended may be used.
                For example: ('-', 'order'), '+name'.

            The remaining keyword arguments are used as conditions for
            filtering the items in the list - they're passed as the
            "filterspec" argument to a Class.filter() call.

            If not editable, just display the value via plain().
        """
        if not self.is_edit_ok():
            return self.plain(escape=1)

        if value is None:
            value = self._value
        # When rendering from form contents, 'value' may contain
        # elements starting '-' from '- no selection -' having been
        # selected on a previous form submission.
        value = [v for v in value if not v.startswith('-')]

        linkcl = self._db.getclass(self._prop.classname)

        if sort_on is not None:
            if not isinstance(sort_on, tuple):
                if sort_on[0] in '+-':
                    sort_on = (sort_on[0], sort_on[1:])
                else:
                    sort_on = ('+', sort_on)
        else:
            sort_on = ('+', linkcl.orderprop())

        options = [opt
                   for opt in linkcl.filter(None, conditions, sort_on)
                   if self._db.security.hasPermission(
                           "View", self._client.userid, linkcl.classname,
                           itemid=opt)]

        # make sure we list the current values if they're retired
        for val in value:
            if val not in options:
                options.insert(0, val)

        if not height:
            height = len(options)
            if value:
                # The "no selection" option.
                height += 1
            height = min(height, 7)
        html = ['<select multiple %s>' % self.cgi_escape_attrs(
            name=self._formname, size=height, **html_kwargs)]
        k = linkcl.labelprop(1)

        if value:  # FIXME '- no selection -' mark for translation
            html.append('<option value="%s">- no selection -</option>'
                        % ','.join(['-' + v for v in value]))

        if additional:
            additional_fns = []
            props = linkcl.getprops()
            for propname in additional:
                prop = props[propname]
                if isinstance(prop, hyperdb.Link):
                    cl = self._db.getclass(prop.classname)
                    labelprop = cl.labelprop()
                    fn = lambda optionid, cl=cl, linkcl=linkcl, \
                                propname=propname, labelprop=labelprop: \
                            cl.get(linkcl.get(optionid, propname), labelprop)
                else:
                    fn = lambda optionid, linkcl=linkcl, propname=propname: \
                            linkcl.get(optionid, propname)
                additional_fns.append(fn)

        for optionid in options:
            # get the option value, and if it's None use an empty string
            option = linkcl.get(optionid, k) or ''

            # figure if this option is selected
            s = ''
            if optionid in value or option in value:
                s = 'selected="selected" '

            # figure the label
            if showid:
                lab = '%s%s: %s' % (self._prop.classname, optionid, option)
            else:
                lab = option
            # truncate if it's too long
            if size is not None and len(lab) > size:
                lab = lab[:size-3] + '...'
            if additional:
                m = []
                for fn in additional_fns:
                    m.append(str(fn(optionid)))
                lab = lab + ' (%s)' % ', '.join(m)

            # and generate
            tr = str
            if translate:
                tr = self._
            lab = html_escape(tr(lab))
            html.append('<option %svalue="%s">%s</option>' % (s, optionid,
                                                              lab))
        html.append('</select>')
        return '\n'.join(html)


# set the propclasses for HTMLItem
propclasses = [
    (hyperdb.String, StringHTMLProperty),
    (hyperdb.Number, NumberHTMLProperty),
    (hyperdb.Integer, IntegerHTMLProperty),
    (hyperdb.Boolean, BooleanHTMLProperty),
    (hyperdb.Date, DateHTMLProperty),
    (hyperdb.Interval, IntervalHTMLProperty),
    (hyperdb.Password, PasswordHTMLProperty),
    (hyperdb.Link, LinkHTMLProperty),
    (hyperdb.Multilink, MultilinkHTMLProperty),
]


def register_propclass(prop, cls):
    for index, propclass in enumerate(propclasses):
        p, c = propclass
        if prop == p:
            propclasses[index] = (prop, cls)
            break
    else:
        propclasses.append((prop, cls))


def make_key_function(db, classname, sort_on=None):
    """Make a sort key function for a given class.

    The list being sorted may contain mixed ids and labels.
    """
    linkcl = db.getclass(classname)
    if sort_on is None:
        sort_on = linkcl.orderprop()
    prop = linkcl.getprops()[sort_on]

    def keyfunc(a):
        if num_re.match(a):
            a = linkcl.get(a, sort_on, allow_abort=False)
            # In Python3 we may not compare numbers/strings and None
            if a is None:
                if isinstance(prop, (hyperdb.Number, hyperdb.Integer)):
                    return 0
                return ''
        return a
    return keyfunc


def handleListCGIValue(value):
    """ Value is either a single item or a list of items. Each item has a
        .value that we're actually interested in.
    """
    if isinstance(value, type([])):
        return [value.value for value in value]
    else:
        value = value.value.strip()
        if not value:
            return []
        return [v.strip() for v in value.split(',')]


class HTMLRequest(HTMLInputMixin):
    """The *request*, holding the CGI form and environment.

    - "form" the CGI form as a cgi.FieldStorage
    - "env" the CGI environment variables
    - "base" the base URL for this instance
    - "user" a HTMLItem instance for this user
    - "language" as determined by the browser or config
    - "classname" the current classname (possibly None)
    - "template" the current template (suffix, also possibly None)

    Index args:

    - "columns" dictionary of the columns to display in an index page
    - "show" a convenience access to columns - request/show/colname will
      be true if the columns should be displayed, false otherwise
    - "sort" index sort column (direction, column name)
    - "group" index grouping property (direction, column name)
    - "filter" properties to filter the index on
    - "filterspec" values to filter the index on
    - "search_text" text to perform a full-text search on for an index
    """
    def __repr__(self):
        return '<HTMLRequest %r>' % self.__dict__

    def __init__(self, client):
        # _client is needed by HTMLInputMixin
        self._client = self.client = client

        # easier access vars
        self.form = client.form
        self.env = client.env
        self.base = client.base
        self.user = HTMLItem(client, 'user', client.userid)
        self.language = client.language

        # store the current class name and action
        self.classname = client.classname
        self.nodeid = client.nodeid
        self.template = client.template

        # the special char to use for special vars
        self.special_char = '@'

        HTMLInputMixin.__init__(self)

        self._post_init()

    def current_url(self):
        url = self.base
        if self.classname:
            url += self.classname
            if self.nodeid:
                url += self.nodeid
        args = {}
        if self.template:
            args['@template'] = self.template
        return self.indexargs_url(url, args)

    def _parse_sort(self, var, name):
        """ Parse sort/group options. Append to var
        """
        fields = []
        dirs = []
        for special in '@:':
            idx = 0
            key = '%s%s%d' % (special, name, idx)
            while self._form_has_key(key):
                self.special_char = special
                fields.append(self.form.getfirst(key))
                dirkey = '%s%sdir%d' % (special, name, idx)
                if dirkey in self.form:
                    dirs.append(self.form.getfirst(dirkey))
                else:
                    dirs.append(None)
                idx += 1
                key = '%s%s%d' % (special, name, idx)
            # backward compatible (and query) URL format
            key = special + name
            dirkey = key + 'dir'
            if self._form_has_key(key) and not fields:
                fields = handleListCGIValue(self.form[key])
                if dirkey in self.form:
                    dirs.append(self.form.getfirst(dirkey))
            if fields:   # only try other special char if nothing found
                break

        # sometimes requests come in without a class
        # chances are they won't have any filter params,
        # in that case anyway but...
        if self.classname:
            cls = self.client.db.getclass(self.classname)
        for f, d in zip_longest(fields, dirs):
            if f.startswith('-'):
                direction, propname = '-', f[1:]
            elif d:
                direction, propname = '-', f
            else:
                direction, propname = '+', f
            # if no classname, just append the propname unchecked.
            # this may be valid for some actions that bypass classes.
            if self.classname and cls.get_transitive_prop(propname) is None:
                self.client.add_error_message("Unknown %s property %s" % (
                    name, propname))
            else:
                var.append((direction, propname))

    def _form_has_key(self, name):
        try:
            return name in self.form
        except TypeError:
            pass
        return False

    def _post_init(self):
        """ Set attributes based on self.form
        """
        # extract the index display information from the form
        self.columns = []
        for name in ':columns @columns'.split():
            if self._form_has_key(name):
                self.special_char = name[0]
                self.columns = handleListCGIValue(self.form[name])
                break
        self.show = support.TruthDict(self.columns)
        security = self._client.db.security
        userid = self._client.userid

        # sorting and grouping
        self.sort = []
        self.group = []
        self._parse_sort(self.sort, 'sort')
        self._parse_sort(self.group, 'group')
        self.sort = security.filterSortspec(userid, self.classname, self.sort)
        self.group = security.filterSortspec(userid, self.classname, self.group)

        # filtering
        self.filter = []
        for name in ':filter @filter'.split():
            if self._form_has_key(name):
                self.special_char = name[0]
                self.filter = handleListCGIValue(self.form[name])

        self.filterspec = {}
        db = self.client.db
        if self.classname is not None:
            cls = db.getclass(self.classname)
            for name in self.filter:
                if not self._form_has_key(name):
                    continue
                prop = cls.get_transitive_prop(name)
                fv = self.form[name]
                if (isinstance(prop, hyperdb.Link) or
                        isinstance(prop, hyperdb.Multilink)):
                    self.filterspec[name] = lookupIds(db, prop,
                                                      handleListCGIValue(fv))
                else:
                    if isinstance(fv, type([])):
                        self.filterspec[name] = [v.value for v in fv]
                    elif name == 'id':
                        # special case "id" property
                        self.filterspec[name] = handleListCGIValue(fv)
                    else:
                        self.filterspec[name] = fv.value
        self.filterspec = security.filterFilterspec(userid, self.classname,
                                                    self.filterspec)

        # full-text search argument
        self.search_text = None
        for name in ':search_text @search_text'.split():
            if self._form_has_key(name):
                self.special_char = name[0]
                self.search_text = self.form.getfirst(name)

        # pagination - size and start index
        # figure batch args
        self.pagesize = 50
        for name in ':pagesize @pagesize'.split():
            if self._form_has_key(name):
                self.special_char = name[0]
                try:
                    self.pagesize = int(self.form.getfirst(name))
                except ValueError:
                    # not an integer - ignore
                    pass

        self.startwith = 0
        for name in ':startwith @startwith'.split():
            if self._form_has_key(name):
                self.special_char = name[0]
                try:
                    self.startwith = int(self.form.getfirst(name))
                except ValueError:
                    # not an integer - ignore
                    pass

        # dispname
        if self._form_has_key('@dispname'):
            self.dispname = self.form.getfirst('@dispname')
        else:
            self.dispname = None

    def updateFromURL(self, url):
        """ Parse the URL for query args, and update my attributes using the
            values.
        """
        env = {'QUERY_STRING': url}
        self.form = cgi.FieldStorage(environ=env)

        self._post_init()

    def update(self, kwargs):
        """ Update my attributes using the keyword args
        """
        self.__dict__.update(kwargs)
        if 'columns' in kwargs:
            self.show = support.TruthDict(self.columns)

    def description(self):
        """ Return a description of the request - handle for the page title.
        """
        s = [self.client.db.config.TRACKER_NAME]
        if self.classname:
            if self.client.nodeid:
                s.append('- %s%s' % (self.classname, self.client.nodeid))
            else:
                if self.template == 'item':
                    s.append('- new %s' % self.classname)
                elif self.template == 'index':
                    s.append('- %s index' % self.classname)
                else:
                    s.append('- %s %s' % (self.classname, self.template))
        else:
            s.append('- home')
        return ' '.join(s)

    def __str__(self):
        d = {}
        d.update(self.__dict__)
        f = ''
        for k in self.form.keys():
            f += '\n      %r=%r' % (k, handleListCGIValue(self.form[k]))
        d['form'] = f
        e = ''
        for k, v in self.env.items():
            e += '\n     %r=%r' % (k, v)
        d['env'] = e
        return """
form: %(form)s
base: %(base)r
classname: %(classname)r
template: %(template)r
columns: %(columns)r
sort: %(sort)r
group: %(group)r
filter: %(filter)r
search_text: %(search_text)r
pagesize: %(pagesize)r
startwith: %(startwith)r
env: %(env)s
""" % d

    def indexargs_form(self, columns=1, sort=1, group=1, filter=1,
                       filterspec=1, search_text=1, exclude=[]):
        """ return the current index args as form elements

            This routine generates an html form with hidden elements.
            If you want to have visible form elements in your tal/jinja
            generated templates use the exclude array to list the names for
            these elements. This wll prevent the function from creating
            these elements in its output.
        """
        html = []
        sc = self.special_char

        def add(k, v):
            html.append(self.input(type="hidden", name=k, value=v))
        if columns and self.columns:
            add(sc+'columns', ','.join(self.columns))
        if sort:
            val = []
            for direction, attr in self.sort:
                if direction == '-':
                    val.append('-'+attr)
                else:
                    val.append(attr)
            add(sc+'sort', ','.join(val))
        if group:
            val = []
            for direction, attr in self.group:
                if direction == '-':
                    val.append('-'+attr)
                else:
                    val.append(attr)
            add(sc+'group', ','.join(val))
        if filter and self.filter:
            add(sc+'filter', ','.join(self.filter))
        if self.classname and filterspec:
            cls = self.client.db.getclass(self.classname)
            for k, v in self.filterspec.items():
                if k in exclude:
                    continue
                if isinstance(v, list):
                    # id's are stored as strings but should be treated
                    # as integers in lists.
                    if (isinstance(cls.get_transitive_prop(k), hyperdb.String)
                            and k != 'id'):
                        add(k, ' '.join(v))
                    else:
                        add(k, ','.join(v))
                else:
                    add(k, v)
        if search_text and self.search_text:
            add(sc+'search_text', self.search_text)
        add(sc+'pagesize', self.pagesize)
        add(sc+'startwith', self.startwith)
        return '\n'.join(html)

    def indexargs_url(self, url, args):
        """ Embed the current index args in a URL

            If the value of an arg (in args dict) is None,
            the argument is excluded from the url. If you want
            an empty value use an empty string '' as the value.
            Use this in templates to conditionally
            include an arg if it is set to a value. E.G.
            {..., '@queryname': request.dispname or None, ...}
            will include @queryname in the url if there is a
            dispname otherwise the parameter will be omitted
            from the url.
        """
        q = urllib_.quote
        sc = self.special_char
        l = ['%s=%s' % (k, is_us(v) and q(v) or v)
             for k, v in args.items() if v is not None]
        # pull out the special values (prefixed by @ or :)
        specials = {}
        for key in args.keys():
            if key[0] in '@:':
                specials[key[1:]] = args[key]

        # ok, now handle the specials we received in the request
        if self.columns and 'columns' not in specials:
            l.append(sc+'columns=%s' % (','.join(self.columns)))
        if self.sort and 'sort' not in specials:
            val = []
            for direction, attr in self.sort:
                if direction == '-':
                    val.append('-'+attr)
                else:
                    val.append(attr)
            l.append(sc+'sort=%s' % (','.join(val)))
        if self.group and 'group' not in specials:
            val = []
            for direction, attr in self.group:
                if direction == '-':
                    val.append('-'+attr)
                else:
                    val.append(attr)
            l.append(sc+'group=%s' % (','.join(val)))
        if self.filter and 'filter' not in specials:
            l.append(sc+'filter=%s' % (','.join(self.filter)))
        if self.search_text and 'search_text' not in specials:
            l.append(sc+'search_text=%s' % q(self.search_text))
        if 'pagesize' not in specials:
            l.append(sc+'pagesize=%s' % self.pagesize)
        if 'startwith' not in specials:
            l.append(sc+'startwith=%s' % self.startwith)

        # finally, the remainder of the filter args in the request
        if self.classname and self.filterspec:
            cls = self.client.db.getclass(self.classname)
            for k, v in self.filterspec.items():
                if k not in args:
                    if isinstance(v, list):
                        prop = cls.get_transitive_prop(k)
                        if k != 'id' and isinstance(prop, hyperdb.String):
                            l.append('%s=%s' % (
                                k, '%20'.join([q(i) for i in v])))
                        else:
                            l.append('%s=%s' % (
                                k, ','.join([q(i) for i in v])))
                    else:
                        l.append('%s=%s' % (k, q(v)))
        return '%s?%s' % (url, '&'.join(l))
    indexargs_href = indexargs_url

    def base_javascript(self):
        return """
<script nonce="%s" type="text/javascript">
submitted = false;
function submit_once() {
    if (submitted) {
        alert("Your request is being processed.\\nPlease be patient.");
        return false;
    }
    submitted = true;
    return true;
}

function help_window(helpurl, width, height) {
    HelpWin = window.open('%s' + helpurl, 'RoundupHelpWindow', 'scrollbars=yes,resizable=yes,toolbar=no,height='+height+',width='+width);
    HelpWin.focus ()
}
</script>
""" % (self._client.client_nonce, self.base)

    def batch(self, permission='View'):
        """ Return a batch object for results from the "current search"
        """
        check = self._client.db.security.hasPermission
        userid = self._client.userid
        if not check('Web Access', userid):
            return Batch(self.client, [], self.pagesize, self.startwith,
                         classname=self.classname)

        fspec = self.filterspec
        sort = self.sort
        group = self.group

        # get the list of ids we're batching over
        klass = self.client.db.getclass(self.classname)
        if self.search_text:
            indexer = self.client.db.indexer
            if indexer.query_language:
                try:
                    matches = indexer.search(
                        [self.search_text], klass)
                except Exception as e:
                    self.client.add_error_message(" ".join(e.args))
                    raise
            else:
                matches = indexer.search(
                    [u2s(w.upper()) for w in re.findall(
                        r'(?u)\b\w{%s,%s}\b' % (indexer.minlength,
                                                indexer.maxlength),
                        s2u(self.search_text, "replace")
                    )], klass)
        else:
            matches = None

        # filter for visibility
        allowed = klass.filter_with_permissions(
            matches, fspec, sort, group, permission=permission, userid=userid
        )

        # return the batch object, using IDs only
        return Batch(self.client, allowed, self.pagesize, self.startwith,
                     classname=self.classname)


# extend the standard ZTUtils Batch object to remove dependency on
# Acquisition and add a couple of useful methods
class Batch(ZTUtils.Batch):
    """ Use me to turn a list of items, or item ids of a given class, into a
        series of batches.

        ========= ========================================================
        Parameter  Usage
        ========= ========================================================
        sequence  a list of HTMLItems or item ids
        classname if sequence is a list of ids, this is the class of item
        size      how big to make the sequence.
        start     where to start (0-indexed) in the sequence.
        end       where to end (0-indexed) in the sequence.
        orphan    if the next batch would contain less items than this
                  value, then it is combined with this batch
        overlap   the number of items shared between adjacent batches
        ========= ========================================================

        Attributes: Note that the "start" attribute, unlike the
        argument, is a 1-based index (I know, lame).  "first" is the
        0-based index.  "length" is the actual number of elements in
        the batch.

        "sequence_length" is the length of the original, unbatched, sequence.
    """
    def __init__(self, client, sequence, size, start, end=0, orphan=0,
                 overlap=0, classname=None):
        self.client = client
        self.last_index = self.last_item = None
        self.current_item = None
        self.classname = classname
        self.sequence_length = len(sequence)
        ZTUtils.Batch.__init__(self, sequence, size, start, end, orphan,
                               overlap)

    # overwrite so we can late-instantiate the HTMLItem instance
    def __getitem__(self, index):
        if index < 0:
            if index + self.end < self.first:
                raise IndexError(index)
            return self._sequence[index + self.end]

        if index >= self.length:
            raise IndexError(index)

        # move the last_item along - but only if the fetched index changes
        # (for some reason, index 0 is fetched twice)
        if index != self.last_index:
            self.last_item = self.current_item
            self.last_index = index

        item = self._sequence[index + self.first]
        if self.classname:
            # map the item ids to instances
            item = HTMLItem(self.client, self.classname, item)
        self.current_item = item
        return item

    def propchanged(self, *properties):
        """ Detect if one of the properties marked as being a group
            property changed in the last iteration fetch
        """
        # we poke directly at the _value here since MissingValue can screw
        # us up and cause Nones to compare strangely
        if self.last_item is None:
            return 1
        for property in properties:
            if property == 'id' or property.endswith('.id')\
               or isinstance(self.last_item[property], list):
                if (str(self.last_item[property]) !=
                        str(self.current_item[property])):
                    return 1
            else:
                if (self.last_item[property]._value !=
                        self.current_item[property]._value):
                    return 1
        return 0

    # override these 'cos we don't have access to acquisition
    def previous(self):
        if self.start == 1:
            return None
        return Batch(self.client, self._sequence, self.size,
                     self.first - self._size + self.overlap, 0, self.orphan,
                     self.overlap)

    def next(self):
        try:
            self._sequence[self.end]
        except IndexError:
            return None
        return Batch(self.client, self._sequence, self.size,
                     self.end - self.overlap, 0, self.orphan, self.overlap)


class TemplatingUtils:
    """ Utilities for templating
    """
    def __init__(self, client):
        self.client = client
        self._ = self.client._

    def Batch(self, sequence, size, start, end=0, orphan=0, overlap=0):
        return Batch(self.client, sequence, size, start, end, orphan,
                     overlap)

    def anti_csrf_nonce(self, lifetime=None):
        return anti_csrf_nonce(self.client, lifetime=lifetime)

    def timestamp(self):
        return pack_timestamp()

    def url_quote(self, url):
        """URL-quote the supplied text."""
        return urllib_.quote(url)

    def html_quote(self, html):
        """HTML-quote the supplied text."""
        return html_escape(html)

    def __getattr__(self, name):
        """Try the tracker's templating_utils."""
        if not hasattr(self.client.instance, 'templating_utils'):
            # backwards-compatibility
            raise AttributeError(name)
        if name not in self.client.instance.templating_utils:
            raise AttributeError(name)
        return self.client.instance.templating_utils[name]

    def keywords_expressions(self, request):
        return render_keywords_expression_editor(request)

    def html_calendar(self, request):
        """Generate a HTML calendar.

        `request` - the roundup.request object
           - @template : name of the template
           - form      : name of the form to store back the date
           - property  : name of the property of the form to store
             back the date
           - date      : date marked as current value on calendar
           - display   : when browsing, specifies year and month

        html will simply be a table.
        """
        tz = request.client.db.getUserTimezone()
        current_date = date.Date(".").local(tz)
        date_str = request.form.getfirst("date", current_date)
        display = request.form.getfirst("display", date_str)
        template = request.form.getfirst("@template", "calendar")
        form = request.form.getfirst("form")
        aproperty = request.form.getfirst("property")
        curr_date = ""
        try:
            # date_str and display can be set to an invalid value
            # if user submits a value like "d4" and gets an edit error.
            # If either or both invalid just ignore that we can't parse it
            # and assign them to today.
            curr_date = date.Date(date_str)   # to highlight
            display = date.Date(display)      # to show
        except ValueError:
            # we couldn't parse the date
            # just let the calendar display
            curr_date = current_date
            display = current_date
        day = display.day

        # for navigation
        try:
            date_prev_month = display + date.Interval("-1m")
        except ValueError:
            date_prev_month = None
        try:
            date_next_month = display + date.Interval("+1m")
        except ValueError:
            date_next_month = None
        try:
            date_prev_year = display + date.Interval("-1y")
        except ValueError:
            date_prev_year = None
        try:
            date_next_year = display + date.Interval("+1y")
        except ValueError:
            date_next_year = None

        res = []

        base_link = "%s?@template=%s&property=%s&form=%s&date=%s" % \
                    (request.classname, template, aproperty, form, curr_date)

        # navigation
        # month
        res.append('<table class="calendar"><tr><td>')
        res.append(' <table width="100%" class="calendar_nav"><tr>')
        link = "&display=%s" % date_prev_month
        if date_prev_month:
            res.append('  <td><a href="%s&display=%s">&lt;</a></td>'
                       % (base_link, date_prev_month))
        else:
            res.append('  <td></td>')
        res.append('  <td>%s</td>' % calendar.month_name[display.month])
        if date_next_month:
            res.append('  <td><a href="%s&display=%s">&gt;</a></td>'
                       % (base_link, date_next_month))
        else:
            res.append('  <td></td>')
        # spacer
        res.append('  <td width="100%"></td>')
        # year
        if date_prev_year:
            res.append('  <td><a href="%s&display=%s">&lt;</a></td>'
                       % (base_link, date_prev_year))
        else:
            res.append('  <td></td>')
        res.append('  <td>%s</td>' % display.year)
        if date_next_year:
            res.append('  <td><a href="%s&display=%s">&gt;</a></td>'
                       % (base_link, date_next_year))
        else:
            res.append('  <td></td>')
        res.append(' </tr></table>')
        res.append(' </td></tr>')

        # the calendar
        res.append(' <tr><td><table class="calendar_display">')
        res.append('  <tr class="weekdays">')
        for day in calendar.weekheader(3).split():
            res.append('   <td>%s</td>' % day)
        res.append('  </tr>')
        for week in calendar.monthcalendar(display.year, display.month):
            res.append('  <tr>')
            for day in week:
                link = "javascript:form[field].value = '%d-%02d-%02d'; " \
                     "if ('createEvent' in document) { var evt = document.createEvent('HTMLEvents'); evt.initEvent('change', true, true); form[field].dispatchEvent(evt); } else { form[field].fireEvent('onchange'); }" \
                     "window.close ();" % (display.year, display.month, day)
                if (day == curr_date.day and display.month == curr_date.month
                        and display.year == curr_date.year):
                    # highlight
                    style = "today"
                else:
                    style = ""
                if day:
                    res.append('   <td class="%s"><a href="%s">%s</a></td>' % (
                        style, link, day))
                else:
                    res.append('   <td></td>')
            res.append('  </tr>')
        res.append('</table></td></tr></table>')
        return "\n".join(res)

    def readfile(self, name, optional=False):
        """Used to inline a file from the template directory.

           Used to inline file content into a template. If file
           is not found in the template directory and
           optional=False, it reports an error to the user via a
           NoTemplate exception. If optional=True it returns an
           empty string when it can't find the file.

           Useful for inlining JavaScript kept in an external
           file where you can use linters/minifiers and other
           tools on it.

           A TAL example::

             <script tal:attributes="nonce request/client/client_nonce"
             tal:content="python:utils.readfile('mylibrary.js')"></script>

           This method does not expands any tokens in the file.
           See expandfile() for replacing tokens in the file.
        """
        file_result = self.client.instance.templates._find(name)

        if file_result is None:
            if optional:
                return ""
            template_name = self.client.selectTemplate(
                self.client.classname, self.client.template)
            raise NoTemplate(self._(
                "Unable to read or expand file '%(name)s' "
                "in template '%(template)s'.") % {
                    "name": name, 'template': template_name})

        fullpath, name = file_result
        with open(fullpath) as f:
            contents = f.read()
        return contents

    def expandfile(self, name, values=None, optional=False):
        """Read a file and replace token placeholders.

           Given a file name and a dict of tokens and
           replacements, read the file from the tracker template
           directory. Then replace all tokens of the form
           '%(token_name)s' with the values in the dict. If the
           values dict is set to None, it acts like
           readfile(). In addition to values passed into the
           method, the value for the tracker base directory taken
           from TRACKER_WEB is available as the 'base' token. The
           client_nonce used for Content Security Policy (CSP) is
           available as 'client_nonce'.  If a token is not in the
           dict, an empty string is returned and an error log
           message is logged. See readfile for an usage example.
        """
        # readfile() raises NoTemplate if optional = false and
        # the file is not found. Returns empty string if file not
        # found and optional = true. File contents otherwise.
        contents = self.readfile(name, optional=optional)

        if values is None or not contents: # nothing to expand
            return contents
        tokens = {'base': self.client.db.config.TRACKER_WEB,
                  'client_nonce': self.client.client_nonce}
        tokens.update(values)
        try:
            return contents % tokens
        except KeyError as e:
            template_name = self.client.selectTemplate(
                self.client.classname, self.client.template)
            fullpath, name = self.client.instance.templates._find(name)
            logger.error(
                "When running expandfile('%(fullpath)s') in "
                "'%(template)s' there was no value for token: '%(token)s'.",
                {'fullpath': fullpath, 'token': e.args[0],
                 'template': template_name})
            return ""
        except ValueError as e:
            fullpath, name = self.client.instance.templates._find(name)
            logger.error(self._(
                "Found an incorrect token when expandfile applied "
                "string subsitution on '%(fullpath)s'. "
                "ValueError('%(issue)s') was raised. Check the format "
                "of your named conversion specifiers."),
                {'fullpath': fullpath, 'issue': e.args[0]})
            return ""

    def set_http_response(self, code):
        '''Set the HTTP response code to the integer `code`.
            Example::

              <tal:x
               tal:replace="python:utils.set_response(404);"
              />


            will make the template return code 404 (not found).
            '''
        self.client.response_code = code

class MissingValue(object):
    def __init__(self, description, **kwargs):
        self.__description = description
        for key, value in kwargs.items():
            self.__dict__[key] = value

    def __call__(self, *args, **kwargs): return MissingValue(self.__description)

    def __getattr__(self, name):
        # This allows assignments which assume all intermediate steps are Null
        # objects if they don't exist yet.
        #
        # For example (with just 'client' defined):
        #
        # client.db.config.TRACKER_WEB = 'BASE/'
        self.__dict__[name] = MissingValue(self.__description)
        return getattr(self, name)

    def __getitem__(self, key): return self
    def __bool__(self): return False
    # Python 2 compatibility:
    __nonzero__ = __bool__
    def __contains__(self, key): return False
    def __eq__(self, rhs): return False
    def __ne__(self, rhs): return False
    def __str__(self): return '[%s]' % self.__description
    def __repr__(self): return '<MissingValue 0x%x "%s">' % (
            id(self), self.__description)

    def gettext(self, str): return str
    _ = gettext

# vim: set et sts=4 sw=4 :
