from __future__ import nested_scopes

"""Implements the API used in the HTML templating for the web interface.
"""

todo = """
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


import cgi, urllib, re, os.path, mimetypes, csv
import calendar, textwrap

from roundup import hyperdb, date, support
from roundup import i18n
from roundup.i18n import _

from KeywordsExpr import render_keywords_expression_editor

try:
    import cPickle as pickle
except ImportError:
    import pickle
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO
try:
    from StructuredText.StructuredText import HTML as StructuredText
except ImportError:
    try: # older version
        import StructuredText
    except ImportError:
        StructuredText = None
try:
    from docutils.core import publish_parts as ReStructuredText
except ImportError:
    ReStructuredText = None

# bring in the templating support
from roundup.cgi import TranslationService, ZTUtils

### i18n services
# this global translation service is not thread-safe.
# it is left here for backward compatibility
# until all Web UI translations are done via client.translator object
translationService = TranslationService.get_translation()

### templating

class NoTemplate(Exception):
    pass

class Unauthorised(Exception):
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

def find_template(dir, name, view):
    """ Find a template in the nominated dir
    """
    # find the source
    if view:
        filename = '%s.%s'%(name, view)
    else:
        filename = name

    # try old-style
    src = os.path.join(dir, filename)
    if os.path.exists(src):
        return (src, filename)

    # try with a .html or .xml extension (new-style)
    for extension in '.html', '.xml':
        f = filename + extension
        src = os.path.join(dir, f)
        if os.path.exists(src):
            return (src, f)

    # no view == no generic template is possible
    if not view:
        raise NoTemplate, 'Template file "%s" doesn\'t exist'%name

    # try for a _generic template
    generic = '_generic.%s'%view
    src = os.path.join(dir, generic)
    if os.path.exists(src):
        return (src, generic)

    # finally, try _generic.html
    generic = generic + '.html'
    src = os.path.join(dir, generic)
    if os.path.exists(src):
        return (src, generic)

    raise NoTemplate('No template file exists for templating "%s" '
        'with template "%s" (neither "%s" nor "%s")'%(name, view,
        filename, generic))

class TemplatesBase:
    """Base for engine-specific Templates class."""
    def precompileTemplates(self):
        """ Go through a directory and precompile all the templates therein
        """
        for filename in os.listdir(self.dir):
            # skip subdirs
            if os.path.isdir(filename):
                continue

            # skip files without ".html" or ".xml" extension - .css, .js etc.
            for extension in '.html', '.xml':
                if filename.endswith(extension):
                    break
            else:
                continue

            # remove extension
            filename = filename[:-len(extension)]

            # load the template
            if '.' in filename:
                name, extension = filename.split('.', 1)
                self.get(name, extension)
            else:
                self.get(filename, None)

    def __getitem__(self, name):
        name, extension = os.path.splitext(name)
        if extension:
            extension = extension[1:]
        try:
            return self.get(name, extension)
        except NoTemplate, message:
            raise KeyError, message

def get_templates(dir, engine_name):
    if engine_name == 'chameleon':
        import engine_chameleon as engine
    else:
        import engine_zopetal as engine
    return engine.Templates(dir)

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
    elif client.db.classes.has_key(classname):
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
            raise AttributeError, attr

    def classes(self):
        l = self._client.db.classes.keys()
        l.sort()
        m = []
        for item in l:
            m.append(HTMLClass(self._client, item))
        return m

num_re = re.compile('^-?\d+$')

def lookupIds(db, prop, ids, fail_ok=0, num_re=num_re, do_lookup=True):
    """ "fail_ok" should be specified if we wish to pass through bad values
        (most likely form values that we wish to represent back to the user)
        "do_lookup" is there for preventing lookup by key-value (if we
        know that the value passed *is* an id)
    """
    cl = db.getclass(prop.classname)
    l = []
    for entry in ids:
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
        if fail_ok or num_re.match(entry):
            l.append(entry)
    return l

def lookupKeys(linkcl, key, ids, num_re=num_re):
    """ Look up the "key" values for "ids" list - though some may already
    be key values, not ids.
    """
    l = []
    for entry in ids:
        if num_re.match(entry):
            label = linkcl.get(entry, key)
            # fall back to designator if label is None
            if label is None: label = '%s%s'%(linkcl.classname, entry)
            l.append(label)
        else:
            l.append(entry)
    return l

def _set_input_default_args(dic):
    # 'text' is the default value anyway --
    # but for CSS usage it should be present
    dic.setdefault('type', 'text')
    # useful e.g for HTML LABELs:
    if not dic.has_key('id'):
        try:
            if dic['text'] in ('radio', 'checkbox'):
                dic['id'] = '%(name)s-%(value)s' % dic
            else:
                dic['id'] = dic['name']
        except KeyError:
            pass

def cgi_escape_attrs(**attrs):
    return ' '.join(['%s="%s"'%(k,cgi.escape(str(v), True))
        for k,v in attrs.items()])

def input_html4(**attrs):
    """Generate an 'input' (html4) element with given attributes"""
    _set_input_default_args(attrs)
    return '<input %s>'%cgi_escape_attrs(**attrs)

def input_xhtml(**attrs):
    """Generate an 'input' (xhtml) element with given attributes"""
    _set_input_default_args(attrs)
    return '<input %s/>'%cgi_escape_attrs(**attrs)

class HTMLInputMixin:
    """ requires a _client property """
    def __init__(self):
        html_version = 'html4'
        if hasattr(self._client.instance.config, 'HTML_VERSION'):
            html_version = self._client.instance.config.HTML_VERSION
        if html_version == 'xhtml':
            self.input = input_xhtml
        else:
            self.input = input_html4
        # self._context is used for translations.
        # will be initialized by the first call to .gettext()
        self._context = None

    def gettext(self, msgid):
        """Return the localized translation of msgid"""
        if self._context is None:
            self._context = context(self._client)
        return self._client.translator.translate(domain="roundup",
            msgid=msgid, context=self._context)

    _ = gettext

class HTMLPermissions:

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
        return perm('Web Access', self._client.userid) and perm('Create',
            self._client.userid, self._classname)

    def is_retire_ok(self):
        """ Is the user allowed to retire items of the current class?
        """
        perm = self._db.security.hasPermission
        return perm('Web Access', self._client.userid) and perm('Retire',
            self._client.userid, self._classname)

    def is_view_ok(self):
        """ Is the user allowed to View the current class?
        """
        perm = self._db.security.hasPermission
        return perm('Web Access', self._client.userid) and perm('View',
            self._client.userid, self._classname)

    def is_only_view_ok(self):
        """ Is the user only allowed to View (ie. not Create) the current class?
        """
        return self.is_view_ok() and not self.is_edit_ok()

    def __repr__(self):
        return '<HTMLClass(0x%x) %s>'%(id(self), self.classname)

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
            raise KeyError, 'No such property "%s" on %s'%(item, self.classname)

        # look up the correct HTMLProperty class
        form = self._client.form
        for klass, htmlklass in propclasses:
            if not isinstance(prop, klass):
                continue
            value = prop.get_default_value()
            return htmlklass(self._client, self._classname, None, prop, item,
                value, self._anonymous)

        # no good
        raise KeyError, item

    def __getattr__(self, attr):
        """ convenience access """
        try:
            return self[attr]
        except KeyError:
            raise AttributeError, attr

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

    def properties(self, sort=1):
        """ Return HTMLProperty for all of this class' properties.
        """
        l = []
        for name, prop in self._props.items():
            for klass, htmlklass in propclasses:
                if isinstance(prop, klass):
                    value = prop.get_default_value()
                    l.append(htmlklass(self._client, self._classname, '',
                                       prop, name, value, self._anonymous))
        if sort:
            l.sort(lambda a,b:cmp(a._name, b._name))
        return l

    def list(self, sort_on=None):
        """ List all items in this class.
        """
        # get the list and sort it nicely
        l = self._klass.list()
        sortfunc = make_sort_function(self._db, self._classname, sort_on)
        l.sort(sortfunc)

        # check perms
        check = self._client.db.security.hasPermission
        userid = self._client.userid
        if not check('Web Access', userid):
            return []

        l = [HTMLItem(self._client, self._classname, id) for id in l
            if check('View', userid, self._classname, itemid=id)]

        return l

    def csv(self):
        """ Return the items of this class as a chunk of CSV text.
        """
        props = self.propnames()
        s = StringIO.StringIO()
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
        idlessprops = self._klass.getprops(protected=0).keys()
        idlessprops.sort()
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

        l = [HTMLItem(self._client, self.classname, id)
             for id in self._klass.filter(None, filterspec, sort, group)
             if check('View', userid, self.classname, itemid=id)]
        return l

    def classhelp(self, properties=None, label=''"(list)", width='500',
            height='400', property='', form='itemSynopsis',
            pagesize=50, inputtype="checkbox", sort=None, filter=None):
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
            properties = self._klass.getprops(protected=0).keys()
            properties.sort()
            properties = ','.join(properties)
        if sort is None:
            if 'username' in properties.split( ',' ):
                sort = 'username'
            else:
                sort = self._klass.orderprop()
        sort = '&amp;@sort=' + sort
        if property:
            property = '&amp;property=%s'%property
        if form:
            form = '&amp;form=%s'%form
        if inputtype:
            type= '&amp;type=%s'%inputtype
        if filter:
            filterprops = filter.split(';')
            filtervalues = []
            names = []
            for x in filterprops:
                (name, values) = x.split('=')
                names.append(name)
                filtervalues.append('&amp;%s=%s' % (name, urllib.quote(values)))
            filter = '&amp;@filter=%s%s' % (','.join(names), ''.join(filtervalues))
        else:
           filter = ''
        help_url = "%s?@startwith=0&amp;@template=help&amp;"\
                   "properties=%s%s%s%s%s&amp;@pagesize=%s%s" % \
                   (self.classname, properties, property, form, type,
                   sort, pagesize, filter)
        onclick = "javascript:help_window('%s', '%s', '%s');return false;" % \
                  (help_url, width, height)
        return '<a class="classhelp" href="%s" onclick="%s">%s</a>' % \
               (help_url, onclick, self._(label))

    def submit(self, label=''"Submit New Entry", action="new"):
        """ Generate a submit button (and action hidden element)

        Generate nothing if we're not editable.
        """
        if not self.is_edit_ok():
            return ''

        return self.input(type="hidden", name="@action", value=action) + \
            '\n' + \
            self.input(type="submit", name="submit_button", value=self._(label))

    def history(self):
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
        pt = self._client.instance.templates.get(self.classname, name)

        # use our fabricated request
        args = {
            'ok_message': self._client.ok_message,
            'error_message': self._client.error_message
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
        return perm('Web Access', self._client.userid) and perm('Edit',
            self._client.userid, self._classname, itemid=self._nodeid)

    def is_retire_ok(self):
        """ Is the user allowed to Reture this item?
        """
        perm = self._db.security.hasPermission
        return perm('Web Access', self._client.userid) and perm('Retire',
            self._client.userid, self._classname, itemid=self._nodeid)

    def is_view_ok(self):
        """ Is the user allowed to View this item?
        """
        perm = self._db.security.hasPermission
        if perm('Web Access', self._client.userid) and perm('View',
                self._client.userid, self._classname, itemid=self._nodeid):
            return 1
        return self.is_edit_ok()

    def is_only_view_ok(self):
        """ Is the user only allowed to View (ie. not Edit) this item?
        """
        return self.is_view_ok() and not self.is_edit_ok()

    def __repr__(self):
        return '<HTMLItem(0x%x) %s %s>'%(id(self), self._classname,
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
            raise KeyError, item

        # get the value, handling missing values
        value = None
        if int(self._nodeid) > 0:
            value = self._klass.get(self._nodeid, items[0], None)
        if value is None:
            if isinstance(prop, hyperdb.Multilink):
                value = []

        # look up the correct HTMLProperty class
        htmlprop = None
        for klass, htmlklass in propclasses:
            if isinstance(prop, klass):
                htmlprop = htmlklass(self._client, self._classname,
                    self._nodeid, prop, items[0], value, self._anonymous)
        if htmlprop is not None:
            if has_rest:
                if isinstance(htmlprop, MultilinkHTMLProperty):
                    return [h[items[1]] for h in htmlprop]
                return htmlprop[items[1]]
            return htmlprop

        raise KeyError, item

    def __getattr__(self, attr):
        """ convenience access to properties """
        try:
            return self[attr]
        except KeyError:
            raise AttributeError, attr

    def designator(self):
        """Return this item's designator (classname + id)."""
        return '%s%s'%(self._classname, self._nodeid)

    def is_retired(self):
        """Is this item retired?"""
        return self._klass.is_retired(self._nodeid)

    def submit(self, label=''"Submit Changes", action="edit"):
        """Generate a submit button.

        Also sneak in the lastactivity and action hidden elements.
        """
        return self.input(type="hidden", name="@lastactivity",
            value=self.activity.local(0)) + '\n' + \
            self.input(type="hidden", name="@action", value=action) + '\n' + \
            self.input(type="submit", name="submit_button", value=self._(label))

    def journal(self, direction='descending'):
        """ Return a list of HTMLJournalEntry instances.
        """
        # XXX do this
        return []

    def history(self, direction='descending', dre=re.compile('^\d+$'),
            limit=None):
        if not self.is_view_ok():
            return self._('[hidden]')

        # pre-load the history with the current state
        current = {}
        for prop_n in self._props.keys():
            prop = self[prop_n]
            if not isinstance(prop, HTMLProperty):
                continue
            current[prop_n] = prop.plain(escape=1)
            # make link if hrefable
            if (self._props.has_key(prop_n) and
                    isinstance(self._props[prop_n], hyperdb.Link)):
                classname = self._props[prop_n].classname
                try:
                    template = find_template(self._db.config.TEMPLATES,
                        classname, 'item')
                    if template[1].startswith('_generic'):
                        raise NoTemplate, 'not really...'
                except NoTemplate:
                    pass
                else:
                    id = self._klass.get(self._nodeid, prop_n, None)
                    current[prop_n] = '<a href="%s%s">%s</a>'%(
                        classname, id, current[prop_n])

        # get the journal, sort and reverse
        history = self._klass.history(self._nodeid)
        history.sort()
        history.reverse()

        # restrict the volume
        if limit:
            history = history[:limit]

        timezone = self._db.getUserTimezone()
        l = []
        comments = {}
        for id, evt_date, user, action, args in history:
            date_s = str(evt_date.local(timezone)).replace("."," ")
            arg_s = ''
            if action == 'link' and type(args) == type(()):
                if len(args) == 3:
                    linkcl, linkid, key = args
                    arg_s += '<a href="%s%s">%s%s %s</a>'%(linkcl, linkid,
                        linkcl, linkid, key)
                else:
                    arg_s = str(args)

            elif action == 'unlink' and type(args) == type(()):
                if len(args) == 3:
                    linkcl, linkid, key = args
                    arg_s += '<a href="%s%s">%s%s %s</a>'%(linkcl, linkid,
                        linkcl, linkid, key)
                else:
                    arg_s = str(args)

            elif type(args) == type({}):
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
                        cell.append(self._('<em>%s: %s</em>\n')
                            % (self._(k), str(args[k])))
                        continue

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
                            template = find_template(self._db.config.TEMPLATES,
                                classname, 'item')
                            if template[1].startswith('_generic'):
                                raise NoTemplate, 'not really...'
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
                                label = classname + linkid
                                # if we have a label property, try to use it
                                # TODO: test for node existence even when
                                # there's no labelprop!
                                try:
                                    if labelprop is not None and \
                                            labelprop != 'id':
                                        label = linkcl.get(linkid, labelprop)
                                        label = cgi.escape(label)
                                except IndexError:
                                    comments['no_link'] = self._(
                                        "<strike>The linked node"
                                        " no longer exists</strike>")
                                    subml.append('<strike>%s</strike>'%label)
                                else:
                                    if hrefable:
                                        subml.append('<a href="%s%s">%s</a>'%(
                                            classname, linkid, label))
                                    elif label is None:
                                        subml.append('%s%s'%(classname,
                                            linkid))
                                    else:
                                        subml.append(label)
                            ml.append(sublabel + ', '.join(subml))
                        cell.append('%s:\n  %s'%(self._(k), ', '.join(ml)))
                    elif isinstance(prop, hyperdb.Link) and args[k]:
                        label = classname + args[k]
                        # if we have a label property, try to use it
                        # TODO: test for node existence even when
                        # there's no labelprop!
                        if labelprop is not None and labelprop != 'id':
                            try:
                                label = cgi.escape(linkcl.get(args[k],
                                    labelprop))
                            except IndexError:
                                comments['no_link'] = self._(
                                    "<strike>The linked node"
                                    " no longer exists</strike>")
                                cell.append(' <strike>%s</strike>,\n'%label)
                                # "flag" this is done .... euwww
                                label = None
                        if label is not None:
                            if hrefable:
                                old = '<a href="%s%s">%s</a>'%(classname,
                                    args[k], label)
                            else:
                                old = label;
                            cell.append('%s: %s' % (self._(k), old))
                            if current.has_key(k):
                                cell[-1] += ' -> %s'%current[k]
                                current[k] = old

                    elif isinstance(prop, hyperdb.Date) and args[k]:
                        if args[k] is None:
                            d = ''
                        else:
                            d = date.Date(args[k],
                                translator=self._client).local(timezone)
                        cell.append('%s: %s'%(self._(k), str(d)))
                        if current.has_key(k):
                            cell[-1] += ' -> %s' % current[k]
                            current[k] = str(d)

                    elif isinstance(prop, hyperdb.Interval) and args[k]:
                        val = str(date.Interval(args[k],
                            translator=self._client))
                        cell.append('%s: %s'%(self._(k), val))
                        if current.has_key(k):
                            cell[-1] += ' -> %s'%current[k]
                            current[k] = val

                    elif isinstance(prop, hyperdb.String) and args[k]:
                        val = cgi.escape(args[k])
                        cell.append('%s: %s'%(self._(k), val))
                        if current.has_key(k):
                            cell[-1] += ' -> %s'%current[k]
                            current[k] = val

                    elif isinstance(prop, hyperdb.Boolean) and args[k] is not None:
                        val = args[k] and ''"Yes" or ''"No"
                        cell.append('%s: %s'%(self._(k), val))
                        if current.has_key(k):
                            cell[-1] += ' -> %s'%current[k]
                            current[k] = val

                    elif isinstance(prop, hyperdb.Password) and args[k] is not None:
                        val = args[k].dummystr()
                        cell.append('%s: %s'%(self._(k), val))
                        if current.has_key(k):
                            cell[-1] += ' -> %s'%current[k]
                            current[k] = val

                    elif not args[k]:
                        if current.has_key(k):
                            cell.append('%s: %s'%(self._(k), current[k]))
                            current[k] = '(no value)'
                        else:
                            cell.append(self._('%s: (no value)')%self._(k))

                    else:
                        cell.append('%s: %s'%(self._(k), str(args[k])))
                        if current.has_key(k):
                            cell[-1] += ' -> %s'%current[k]
                            current[k] = str(args[k])

                arg_s = '<br />'.join(cell)
            else:
                # unkown event!!
                comments['unknown'] = self._(
                    "<strong><em>This event is not handled"
                    " by the history display!</em></strong>")
                arg_s = '<strong><em>' + str(args) + '</em></strong>'
            date_s = date_s.replace(' ', '&nbsp;')
            # if the user's an itemid, figure the username (older journals
            # have the username)
            if dre.match(user):
                user = self._db.user.get(user, 'username')
            l.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(
                date_s, cgi.escape(user), self._(action), arg_s))
        if comments:
            l.append(self._(
                '<tr><td colspan=4><strong>Note:</strong></td></tr>'))
        for entry in comments.values():
            l.append('<tr><td colspan=4>%s</td></tr>'%entry)

        if direction == 'ascending':
            l.reverse()

        l[0:0] = ['<table class="history">'
             '<tr><th colspan="4" class="header">',
             self._('History'),
             '</th></tr><tr>',
             self._('<th>Date</th>'),
             self._('<th>User</th>'),
             self._('<th>Action</th>'),
             self._('<th>Args</th>'),
            '</tr>']
        l.append('</table>')
        return '\n'.join(l)

    def renderQueryForm(self):
        """ Render this item, which is a query, as a search form.
        """
        # create a new request and override the specified args
        req = HTMLRequest(self._client)
        req.classname = self._klass.get(self._nodeid, 'klass')
        name = self._klass.get(self._nodeid, 'name')
        req.updateFromURL(self._klass.get(self._nodeid, 'url') +
            '&@queryname=%s'%urllib.quote(name))

        # new template, using the specified classname and request
        pt = self._client.instance.templates.get(req.classname, 'search')
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
        url = '%s%s/%s'%(self._classname, self._nodeid, name)
        return urllib.quote(url)

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
                query[name] = self[name].plain()
        return self._classname + "?" + "&".join(
            ["%s=%s" % (key, urllib.quote(value))
                for key, value in query.items()])

class _HTMLUser(_HTMLItem):
    """Add ability to check for permissions on users.
    """
    _marker = []
    def hasPermission(self, permission, classname=_marker,
            property=None, itemid=None):
        """Determine if the user has the Permission.

        The class being tested defaults to the template's class, but may
        be overidden for this test by suppling an alternate classname.
        """
        if classname is self._marker:
            classname = self._client.classname
        return self._db.security.hasPermission(permission,
            self._nodeid, classname, property, itemid)

    def hasRole(self, *rolenames):
        """Determine whether the user has any role in rolenames."""
        return self._db.user.has_role(self._nodeid, *rolenames)

def HTMLItem(client, classname, nodeid, anonymous=0):
    if classname == 'user':
        return _HTMLUser(client, classname, nodeid, anonymous)
    else:
        return _HTMLItem(client, classname, nodeid, anonymous)

class HTMLProperty(HTMLInputMixin, HTMLPermissions):
    """ String, Number, Date, Interval HTMLProperty

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
                self._formname = '%s%s@%s'%(classname, nodeid, name)
            else:
                # This case occurs when creating a property for a
                # non-anonymous class.
                self._formname = '%s@%s'%(classname, name)
        else:
            self._formname = name

        # If no value is already present for this property, see if one
        # is specified in the current form.
        form = self._client.form
        if not self._value and form.has_key(self._formname):
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

        HTMLInputMixin.__init__(self)

    def __repr__(self):
        classname = self.__class__.__name__
        return '<%s(0x%x) %s %r %r>'%(classname, id(self), self._formname,
                                      self._prop, self._value)
    def __str__(self):
        return self.plain()
    def __cmp__(self, other):
        if isinstance(other, HTMLProperty):
            return cmp(self._value, other._value)
        return cmp(self._value, other)

    def __nonzero__(self):
        return not not self._value

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
        if perm('Web Access',  self._client.userid) and perm('View',
                self._client.userid, self._classname, self._name, self._nodeid):
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
        (?P<email>[-+=%/\w\.]+@[\w\.\-]+)|
        (?P<item>(?P<class>[A-Za-z_]+)(\s*)(?P<id>\d+))
    )''', re.X | re.I)
    protocol_re = re.compile('^(ht|f)tp(s?)://', re.I)



    def _hyper_repl(self, match):
        if match.group('url'):
            return self._hyper_repl_url(match, '<a href="%s">%s</a>%s')
        elif match.group('email'):
            return self._hyper_repl_email(match, '<a href="mailto:%s">%s</a>')
        elif len(match.group('id')) < 10:
            return self._hyper_repl_item(match,
                '<a href="%(cls)s%(id)s">%(item)s</a>')
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
        id = match.group('id')
        try:
            # make sure cls is a valid tracker classname
            cl = self._db.getclass(cls)
            if not cl.hasnode(id):
                return item
            return replacement % locals()
        except KeyError:
            return item


    def _hyper_repl_rst(self, match):
        if match.group('url'):
            s = match.group('url')
            return '`%s <%s>`_'%(s, s)
        elif match.group('email'):
            s = match.group('email')
            return '`%s <mailto:%s>`_'%(s, s)
        elif len(match.group('id')) < 10:
            return self._hyper_repl_item(match,'`%(item)s <%(cls)s%(id)s>`_')
        else:
            # just return the matched text
            return match.group(0)

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
            s = cgi.escape(str(self._value))
        else:
            s = str(self._value)
        if hyperlink:
            # no, we *must* escape this text
            if not escape:
                s = cgi.escape(s)
            s = self.hyper_re.sub(self._hyper_repl, s)
        return s

    def wrapped(self, escape=1, hyperlink=1):
        """Render a "wrapped" representation of the property.

        We wrap long lines at 80 columns on the nearest whitespace. Lines
        with no whitespace are not broken to force wrapping.

        Note that unlike plain() we default wrapped() to have the escaping
        and hyperlinking turned on since that's the most common usage.

        - "escape" turns on/off HTML quoting
        - "hyperlink" turns on/off in-text hyperlinking of URLs, email
          addresses and designators
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            return ''
        s = support.wrap(str(self._value), width=80)
        if escape:
            s = cgi.escape(s)
        if hyperlink:
            # no, we *must* escape this text
            if not escape:
                s = cgi.escape(s)
            s = self.hyper_re.sub(self._hyper_repl, s)
        return s

    def stext(self, escape=0, hyperlink=1):
        """ Render the value of the property as StructuredText.

            This requires the StructureText module to be installed separately.
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        s = self.plain(escape=escape, hyperlink=hyperlink)
        if not StructuredText:
            return s
        return StructuredText(s,level=1,header=0)

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
        return ReStructuredText(s, writer_name="html")["html_body"].encode("utf-8",
            "replace")

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
            return '<pre>%s</pre>'%self.plain()

        if self._value is None:
            value = ''
        else:
            value = cgi.escape(str(self._value))

            value = '&quot;'.join(value.split('"'))
        name = self._formname
        passthrough_args = cgi_escape_attrs(**kwargs)
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
            value = '%s at %s ...'%(name, domain)
        else:
            value = value.replace('.', ' ')
        if escape:
            value = cgi.escape(value)
        return value

class PasswordHTMLProperty(HTMLProperty):
    def plain(self, escape=0):
        """ Render a "plain" representation of the property
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            return ''
        value = self._value.dummystr()
        if escape:
            value = cgi.escape(value)
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
            name="@confirm@%s"%self._formname,
            id="%s-confirm"%self._formname,
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

    def field(self, size=30, **kwargs):
        """ Render a form edit field for the property.

            If not editable, just display the value via plain().
        """
        if not self.is_edit_ok():
            return self.plain(escape=1)

        value = self._value
        if value is None:
            value = ''

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


class BooleanHTMLProperty(HTMLProperty):
    def plain(self, escape=0):
        """ Render a "plain" representation of the property
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        if self._value is None:
            return ''
        return self._value and self._("Yes") or self._("No")

    def field(self, **kwargs):
        """ Render a form edit field for the property

            If not editable, just display the value via plain().
        """
        if not self.is_edit_ok():
            return self.plain(escape=1)

        value = self._value
        if isinstance(value, str) or isinstance(value, unicode):
            value = value.strip().lower() in ('checked', 'yes', 'true',
                'on', '1')

        checked = value and "checked" or ""
        if value:
            s = self.input(type="radio", name=self._formname, value="yes",
                checked="checked", **kwargs)
            s += self._('Yes')
            s +=self.input(type="radio", name=self._formname,  value="no",
                           **kwargs)
            s += self._('No')
        else:
            s = self.input(type="radio", name=self._formname,  value="yes",
                           **kwargs)
            s += self._('Yes')
            s +=self.input(type="radio", name=self._formname, value="no",
                checked="checked", **kwargs)
            s += self._('No')
        return s

class DateHTMLProperty(HTMLProperty):

    _marker = []

    def __init__(self, client, classname, nodeid, prop, name, value,
            anonymous=0, offset=None):
        HTMLProperty.__init__(self, client, classname, nodeid, prop, name,
                value, anonymous=anonymous)
        if self._value and not (isinstance(self._value, str) or
                isinstance(self._value, unicode)):
            self._value.setTranslator(self._client.translator)
        self._offset = offset
        if self._offset is None :
            self._offset = self._prop.offset (self._db)

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
        return str(self._value.local(offset))

    def now(self, str_interval=None):
        """ Return the current time.

            This is useful for defaulting a new value. Returns a
            DateHTMLProperty.
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        ret = date.Date('.', translator=self._client)

        if isinstance(str_interval, basestring):
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

    def field(self, size=30, default=None, format=_marker, popcal=True,
              **kwargs):
        """Render a form edit field for the property

        If not editable, just display the value via plain().

        If "popcal" then include the Javascript calendar editor.
        Default=yes.

        The format string is a standard python strftime format string.
        """
        if not self.is_edit_ok():
            if format is self._marker:
                return self.plain(escape=1)
            else:
                return self.pretty(format)

        value = self._value

        if value is None:
            if default is None:
                raw_value = None
            else:
                if isinstance(default, basestring):
                    raw_value = date.Date(default, translator=self._client)
                elif isinstance(default, date.Date):
                    raw_value = default
                elif isinstance(default, DateHTMLProperty):
                    raw_value = default._value
                else:
                    raise ValueError, self._('default value for '
                        'DateHTMLProperty must be either DateHTMLProperty '
                        'or string date representation.')
        elif isinstance(value, str) or isinstance(value, unicode):
            # most likely erroneous input to be passed back to user
            if isinstance(value, unicode): value = value.encode('utf8')
            return self.input(name=self._formname, value=value, size=size,
                              **kwargs)
        else:
            raw_value = value

        if raw_value is None:
            value = ''
        elif isinstance(raw_value, str) or isinstance(raw_value, unicode):
            if format is self._marker:
                value = raw_value
            else:
                value = date.Date(raw_value).pretty(format)
        else:
            if self._offset is None :
                offset = self._db.getUserTimezone()
            else :
                offset = self._offset
            value = raw_value.local(offset)
            if format is not self._marker:
                value = value.pretty(format)

        s = self.input(name=self._formname, value=value, size=size,
                       **kwargs)
        if popcal:
            s += self.popcal()
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

        if not self._value:
            return ''
        elif format is not self._marker:
            return self._value.local(offset).pretty(format)
        else:
            return self._value.local(offset).pretty()

    def local(self, offset):
        """ Return the date/time as a local (timezone offset) date/time.
        """
        if not self.is_view_ok():
            return self._('[hidden]')

        return DateHTMLProperty(self._client, self._classname, self._nodeid,
            self._prop, self._formname, self._value, offset=offset)

    def popcal(self, width=300, height=200, label="(cal)",
            form="itemSynopsis"):
        """Generate a link to a calendar pop-up window.

        item: HTMLProperty e.g.: context.deadline
        """
        if self.isset():
            date = "&date=%s"%self._value
        else :
            date = ""
        return ('<a class="classhelp" href="javascript:help_window('
            "'%s?@template=calendar&amp;property=%s&amp;form=%s%s', %d, %d)"
            '">%s</a>'%(self._classname, self._name, form, date, width,
            height, label))

class IntervalHTMLProperty(HTMLProperty):
    def __init__(self, client, classname, nodeid, prop, name, value,
            anonymous=0):
        HTMLProperty.__init__(self, client, classname, nodeid, prop,
            name, value, anonymous)
        if self._value and not isinstance(self._value, (str, unicode)):
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
            return MissingValue(msg%locals())
        i = HTMLItem(self._client, self._prop.classname, self._value)
        return getattr(i, attr)

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
                value = str(linkcl.get(self._value, k))
            except IndexError:
                value = self._value
        else :
            value = self._value
        if escape:
            value = cgi.escape(value)
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
            if k and num_re.match(self._value):
                value = linkcl.get(self._value, k)
            else:
                value = self._value
        return self.input(name=self._formname, value=value, size=size,
                          **kwargs)

    def menu(self, size=None, height=None, showid=0, additional=[], value=None,
             sort_on=None, html_kwargs={}, translate=True, **conditions):
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
        l = ['<select %s>'%cgi_escape_attrs(name = self._formname,
                                            **html_kwargs)]
        k = linkcl.labelprop(1)
        s = ''
        if value is None:
            s = 'selected="selected" '
        l.append(self._('<option %svalue="-1">- no selection -</option>')%s)

        if sort_on is not None:
            if not isinstance(sort_on, tuple):
                if sort_on[0] in '+-':
                    sort_on = (sort_on[0], sort_on[1:])
                else:
                    sort_on = ('+', sort_on)
        else:
            sort_on = ('+', linkcl.orderprop())

        options = [opt
            for opt in linkcl.filter(None, conditions, sort_on, (None, None))
            if self._db.security.hasPermission("View", self._client.userid,
                linkcl.classname, itemid=opt)]

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
                    fn = lambda optionid: cl.get(linkcl.get(optionid,
                                                            propname),
                                                 labelprop)
                else:
                    fn = lambda optionid: linkcl.get(optionid, propname)
            additional_fns.append(fn)

        for optionid in options:
            # get the option value, and if it's None use an empty string
            option = linkcl.get(optionid, k) or ''

            # figure if this option is selected
            s = ''
            if value in [optionid, option]:
                s = 'selected="selected" '

            # figure the label
            if showid:
                lab = '%s%s: %s'%(self._prop.classname, optionid, option)
            elif not option:
                lab = '%s%s'%(self._prop.classname, optionid)
            else:
                lab = option

            # truncate if it's too long
            if size is not None and len(lab) > size:
                lab = lab[:size-3] + '...'
            if additional:
                m = []
                for fn in additional_fns:
                    m.append(str(fn(optionid)))
                lab = lab + ' (%s)'%', '.join(m)

            # and generate
            tr = str
            if translate:
                tr = self._
            lab = cgi.escape(tr(lab))
            l.append('<option %svalue="%s">%s</option>'%(s, optionid, lab))
        l.append('</select>')
        return '\n'.join(l)
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
            sortfun = make_sort_function(self._db, self._prop.classname)
            # sorting fails if the value contains
            # items not yet stored in the database
            # ignore these errors to preserve user input
            try:
                display_value.sort(sortfun)
            except:
                pass
            self._value = display_value

    def __len__(self):
        """ length of the multilink """
        return len(self._value)

    def __getattr__(self, attr):
        """ no extended attribute accesses make sense here """
        raise AttributeError, attr

    def viewableGenerator(self, values):
        """Used to iterate over only the View'able items in a class."""
        check = self._db.security.hasPermission
        userid = self._client.userid
        classname = self._prop.classname
        if check('Web Access', userid):
            for value in values:
                if check('View', userid, classname, itemid=value):
                    yield HTMLItem(self._client, classname, value)

    def __iter__(self):
        """ iterate and return a new HTMLItem
        """
        return self.viewableGenerator(self._value)

    def reverse(self):
        """ return the list in reverse order
        """
        l = self._value[:]
        l.reverse()
        return self.viewableGenerator(l)

    def sorted(self, property):
        """ Return this multilink sorted by the given property """
        value = list(self.__iter__())
        value.sort(lambda a,b:cmp(a[property], b[property]))
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
                    label = linkcl.get(v, k)
                except IndexError:
                    label = None
                # fall back to designator if label is None
                if label is None: label = '%s%s'%(self._prop.classname, k)
            else:
                label = v
            labels.append(label)
        value = ', '.join(labels)
        if escape:
            value = cgi.escape(value)
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
                showid=1
            if not showid:
                k = linkcl.labelprop(1)
                value = lookupKeys(linkcl, k, value)
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
            if self._db.security.hasPermission("View", self._client.userid,
                linkcl.classname, itemid=opt)]

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
        l = ['<select multiple %s>'%cgi_escape_attrs(name = self._formname,
                                                     size = height,
                                                     **html_kwargs)]
        k = linkcl.labelprop(1)

        if value:
            l.append('<option value="%s">- no selection -</option>'
                     % ','.join(['-' + v for v in value]))

        if additional:
            additional_fns = []
            props = linkcl.getprops()
            for propname in additional:
                prop = props[propname]
                if isinstance(prop, hyperdb.Link):
                    cl = self._db.getclass(prop.classname)
                    labelprop = cl.labelprop()
                    fn = lambda optionid: cl.get(linkcl.get(optionid,
                                                            propname),
                                                 labelprop)
                else:
                    fn = lambda optionid: linkcl.get(optionid, propname)
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
                lab = '%s%s: %s'%(self._prop.classname, optionid, option)
            else:
                lab = option
            # truncate if it's too long
            if size is not None and len(lab) > size:
                lab = lab[:size-3] + '...'
            if additional:
                m = []
                for fn in additional_fns:
                    m.append(str(fn(optionid)))
                lab = lab + ' (%s)'%', '.join(m)

            # and generate
            tr = str
            if translate:
                tr = self._
            lab = cgi.escape(tr(lab))
            l.append('<option %svalue="%s">%s</option>'%(s, optionid,
                lab))
        l.append('</select>')
        return '\n'.join(l)


# set the propclasses for HTMLItem
propclasses = [
    (hyperdb.String, StringHTMLProperty),
    (hyperdb.Number, NumberHTMLProperty),
    (hyperdb.Boolean, BooleanHTMLProperty),
    (hyperdb.Date, DateHTMLProperty),
    (hyperdb.Interval, IntervalHTMLProperty),
    (hyperdb.Password, PasswordHTMLProperty),
    (hyperdb.Link, LinkHTMLProperty),
    (hyperdb.Multilink, MultilinkHTMLProperty),
]

def register_propclass(prop, cls):
    for index,propclass in enumerate(propclasses):
        p, c = propclass
        if prop == p:
            propclasses[index] = (prop, cls)
            break
    else:
        propclasses.append((prop, cls))


def make_sort_function(db, classname, sort_on=None):
    """Make a sort function for a given class.

    The list being sorted may contain mixed ids and labels.
    """
    linkcl = db.getclass(classname)
    if sort_on is None:
        sort_on = linkcl.orderprop()
    def sortfunc(a, b):
        if num_re.match(a):
            a = linkcl.get(a, sort_on)
        if num_re.match(b):
            b = linkcl.get(b, sort_on)
        return cmp(a, b)
    return sortfunc

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
        return '<HTMLRequest %r>'%self.__dict__

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
            key = '%s%s%d'%(special, name, idx)
            while key in self.form:
                self.special_char = special
                fields.append(self.form.getfirst(key))
                dirkey = '%s%sdir%d'%(special, name, idx)
                if dirkey in self.form:
                    dirs.append(self.form.getfirst(dirkey))
                else:
                    dirs.append(None)
                idx += 1
                key = '%s%s%d'%(special, name, idx)
            # backward compatible (and query) URL format
            key = special + name
            dirkey = key + 'dir'
            if key in self.form and not fields:
                fields = handleListCGIValue(self.form[key])
                if dirkey in self.form:
                    dirs.append(self.form.getfirst(dirkey))
            if fields: # only try other special char if nothing found
                break
        for f, d in map(None, fields, dirs):
            if f.startswith('-'):
                var.append(('-', f[1:]))
            elif d:
                var.append(('-', f))
            else:
                var.append(('+', f))

    def _post_init(self):
        """ Set attributes based on self.form
        """
        # extract the index display information from the form
        self.columns = []
        for name in ':columns @columns'.split():
            if self.form.has_key(name):
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
            if self.form.has_key(name):
                self.special_char = name[0]
                self.filter = handleListCGIValue(self.form[name])

        self.filterspec = {}
        db = self.client.db
        if self.classname is not None:
            cls = db.getclass (self.classname)
            for name in self.filter:
                if not self.form.has_key(name):
                    continue
                prop = cls.get_transitive_prop (name)
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
            if self.form.has_key(name):
                self.special_char = name[0]
                self.search_text = self.form.getfirst(name)

        # pagination - size and start index
        # figure batch args
        self.pagesize = 50
        for name in ':pagesize @pagesize'.split():
            if self.form.has_key(name):
                self.special_char = name[0]
                try:
                    self.pagesize = int(self.form.getfirst(name))
                except ValueError:
                    # not an integer - ignore
                    pass

        self.startwith = 0
        for name in ':startwith @startwith'.split():
            if self.form.has_key(name):
                self.special_char = name[0]
                try:
                    self.startwith = int(self.form.getfirst(name))
                except ValueError:
                    # not an integer - ignore
                    pass

        # dispname
        if self.form.has_key('@dispname'):
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
        if kwargs.has_key('columns'):
            self.show = support.TruthDict(self.columns)

    def description(self):
        """ Return a description of the request - handle for the page title.
        """
        s = [self.client.db.config.TRACKER_NAME]
        if self.classname:
            if self.client.nodeid:
                s.append('- %s%s'%(self.classname, self.client.nodeid))
            else:
                if self.template == 'item':
                    s.append('- new %s'%self.classname)
                elif self.template == 'index':
                    s.append('- %s index'%self.classname)
                else:
                    s.append('- %s %s'%(self.classname, self.template))
        else:
            s.append('- home')
        return ' '.join(s)

    def __str__(self):
        d = {}
        d.update(self.__dict__)
        f = ''
        for k in self.form.keys():
            f += '\n      %r=%r'%(k,handleListCGIValue(self.form[k]))
        d['form'] = f
        e = ''
        for k,v in self.env.items():
            e += '\n     %r=%r'%(k, v)
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
"""%d

    def indexargs_form(self, columns=1, sort=1, group=1, filter=1,
            filterspec=1, search_text=1):
        """ return the current index args as form elements """
        l = []
        sc = self.special_char
        def add(k, v):
            l.append(self.input(type="hidden", name=k, value=v))
        if columns and self.columns:
            add(sc+'columns', ','.join(self.columns))
        if sort:
            val = []
            for dir, attr in self.sort:
                if dir == '-':
                    val.append('-'+attr)
                else:
                    val.append(attr)
            add(sc+'sort', ','.join (val))
        if group:
            val = []
            for dir, attr in self.group:
                if dir == '-':
                    val.append('-'+attr)
                else:
                    val.append(attr)
            add(sc+'group', ','.join (val))
        if filter and self.filter:
            add(sc+'filter', ','.join(self.filter))
        if self.classname and filterspec:
            cls = self.client.db.getclass(self.classname)
            for k,v in self.filterspec.items():
                if type(v) == type([]):
                    if isinstance(cls.get_transitive_prop(k), hyperdb.String):
                        add(k, ' '.join(v))
                    else:
                        add(k, ','.join(v))
                else:
                    add(k, v)
        if search_text and self.search_text:
            add(sc+'search_text', self.search_text)
        add(sc+'pagesize', self.pagesize)
        add(sc+'startwith', self.startwith)
        return '\n'.join(l)

    def indexargs_url(self, url, args):
        """ Embed the current index args in a URL
        """
        q = urllib.quote
        sc = self.special_char
        l = ['%s=%s'%(k,v) for k,v in args.items()]

        # pull out the special values (prefixed by @ or :)
        specials = {}
        for key in args.keys():
            if key[0] in '@:':
                specials[key[1:]] = args[key]

        # ok, now handle the specials we received in the request
        if self.columns and not specials.has_key('columns'):
            l.append(sc+'columns=%s'%(','.join(self.columns)))
        if self.sort and not specials.has_key('sort'):
            val = []
            for dir, attr in self.sort:
                if dir == '-':
                    val.append('-'+attr)
                else:
                    val.append(attr)
            l.append(sc+'sort=%s'%(','.join(val)))
        if self.group and not specials.has_key('group'):
            val = []
            for dir, attr in self.group:
                if dir == '-':
                    val.append('-'+attr)
                else:
                    val.append(attr)
            l.append(sc+'group=%s'%(','.join(val)))
        if self.filter and not specials.has_key('filter'):
            l.append(sc+'filter=%s'%(','.join(self.filter)))
        if self.search_text and not specials.has_key('search_text'):
            l.append(sc+'search_text=%s'%q(self.search_text))
        if not specials.has_key('pagesize'):
            l.append(sc+'pagesize=%s'%self.pagesize)
        if not specials.has_key('startwith'):
            l.append(sc+'startwith=%s'%self.startwith)

        # finally, the remainder of the filter args in the request
        if self.classname and self.filterspec:
            cls = self.client.db.getclass(self.classname)
            for k,v in self.filterspec.items():
                if not args.has_key(k):
                    if type(v) == type([]):
                        prop = cls.get_transitive_prop(k)
                        if k != 'id' and isinstance(prop, hyperdb.String):
                            l.append('%s=%s'%(k, '%20'.join([q(i) for i in v])))
                        else:
                            l.append('%s=%s'%(k, ','.join([q(i) for i in v])))
                    else:
                        l.append('%s=%s'%(k, q(v)))
        return '%s?%s'%(url, '&'.join(l))
    indexargs_href = indexargs_url

    def base_javascript(self):
        return """
<script type="text/javascript">
submitted = false;
function submit_once() {
    if (submitted) {
        alert("Your request is being processed.\\nPlease be patient.");
        event.returnValue = 0;    // work-around for IE
        return 0;
    }
    submitted = true;
    return 1;
}

function help_window(helpurl, width, height) {
    HelpWin = window.open('%s' + helpurl, 'RoundupHelpWindow', 'scrollbars=yes,resizable=yes,toolbar=no,height='+height+',width='+width);
}
</script>
"""%self.base

    def batch(self, permission='View'):
        """ Return a batch object for results from the "current search"
        """
        check = self._client.db.security.hasPermission
        userid = self._client.userid
        if not check('Web Access', userid):
            return Batch(self.client, [], self.pagesize, self.startwith,
                classname=self.classname)

        filterspec = self.filterspec
        sort = self.sort
        group = self.group

        # get the list of ids we're batching over
        klass = self.client.db.getclass(self.classname)
        if self.search_text:
            matches = self.client.db.indexer.search(
                [w.upper().encode("utf-8", "replace") for w in re.findall(
                    r'(?u)\b\w{2,25}\b',
                    unicode(self.search_text, "utf-8", "replace")
                )], klass)
        else:
            matches = None

        # filter for visibility
        l = [id for id in klass.filter(matches, filterspec, sort, group)
            if check(permission, userid, self.classname, itemid=id)]

        # return the batch object, using IDs only
        return Batch(self.client, l, self.pagesize, self.startwith,
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
            if index + self.end < self.first: raise IndexError, index
            return self._sequence[index + self.end]

        if index >= self.length:
            raise IndexError, index

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
            if property == 'id' or isinstance (self.last_item[property], list):
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
        return Batch(self.client, self._sequence, self._size,
            self.first - self._size + self.overlap, 0, self.orphan,
            self.overlap)

    def next(self):
        try:
            self._sequence[self.end]
        except IndexError:
            return None
        return Batch(self.client, self._sequence, self._size,
            self.end - self.overlap, 0, self.orphan, self.overlap)

class TemplatingUtils:
    """ Utilities for templating
    """
    def __init__(self, client):
        self.client = client
    def Batch(self, sequence, size, start, end=0, orphan=0, overlap=0):
        return Batch(self.client, sequence, size, start, end, orphan,
            overlap)

    def url_quote(self, url):
        """URL-quote the supplied text."""
        return urllib.quote(url)

    def html_quote(self, html):
        """HTML-quote the supplied text."""
        return cgi.escape(html)

    def __getattr__(self, name):
        """Try the tracker's templating_utils."""
        if not hasattr(self.client.instance, 'templating_utils'):
            # backwards-compatibility
            raise AttributeError, name
        if not self.client.instance.templating_utils.has_key(name):
            raise AttributeError, name
        return self.client.instance.templating_utils[name]

    def keywords_expressions(self, request):
        return render_keywords_expression_editor(request)

    def html_calendar(self, request):
        """Generate a HTML calendar.

        `request`  the roundup.request object
                   - @template : name of the template
                   - form      : name of the form to store back the date
                   - property  : name of the property of the form to store
                                 back the date
                   - date      : current date
                   - display   : when browsing, specifies year and month

        html will simply be a table.
        """
        tz = request.client.db.getUserTimezone()
        current_date = date.Date(".").local(tz)
        date_str  = request.form.getfirst("date", current_date)
        display   = request.form.getfirst("display", date_str)
        template  = request.form.getfirst("@template", "calendar")
        form      = request.form.getfirst("form")
        property  = request.form.getfirst("property")
        curr_date = date.Date(date_str) # to highlight
        display   = date.Date(display)  # to show
        day       = display.day

        # for navigation
        date_prev_month = display + date.Interval("-1m")
        date_next_month = display + date.Interval("+1m")
        date_prev_year  = display + date.Interval("-1y")
        date_next_year  = display + date.Interval("+1y")

        res = []

        base_link = "%s?@template=%s&property=%s&form=%s&date=%s" % \
                    (request.classname, template, property, form, curr_date)

        # navigation
        # month
        res.append('<table class="calendar"><tr><td>')
        res.append(' <table width="100%" class="calendar_nav"><tr>')
        link = "&display=%s"%date_prev_month
        res.append('  <td><a href="%s&display=%s">&lt;</a></td>'%(base_link,
            date_prev_month))
        res.append('  <td>%s</td>'%calendar.month_name[display.month])
        res.append('  <td><a href="%s&display=%s">&gt;</a></td>'%(base_link,
            date_next_month))
        # spacer
        res.append('  <td width="100%"></td>')
        # year
        res.append('  <td><a href="%s&display=%s">&lt;</a></td>'%(base_link,
            date_prev_year))
        res.append('  <td>%s</td>'%display.year)
        res.append('  <td><a href="%s&display=%s">&gt;</a></td>'%(base_link,
            date_next_year))
        res.append(' </tr></table>')
        res.append(' </td></tr>')

        # the calendar
        res.append(' <tr><td><table class="calendar_display">')
        res.append('  <tr class="weekdays">')
        for day in calendar.weekheader(3).split():
            res.append('   <td>%s</td>'%day)
        res.append('  </tr>')
        for week in calendar.monthcalendar(display.year, display.month):
            res.append('  <tr>')
            for day in week:
                link = "javascript:form[field].value = '%d-%02d-%02d'; " \
                      "window.close ();"%(display.year, display.month, day)
                if (day == curr_date.day and display.month == curr_date.month
                        and display.year == curr_date.year):
                    # highlight
                    style = "today"
                else :
                    style = ""
                if day:
                    res.append('   <td class="%s"><a href="%s">%s</a></td>'%(
                        style, link, day))
                else :
                    res.append('   <td></td>')
            res.append('  </tr>')
        res.append('</table></td></tr></table>')
        return "\n".join(res)

class MissingValue:
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
    def __nonzero__(self): return 0
    def __str__(self): return '[%s]'%self.__description
    def __repr__(self): return '<MissingValue 0x%x "%s">'%(id(self),
        self.__description)
    def gettext(self, str): return str
    _ = gettext

# vim: set et sts=4 sw=4 :
