import sys, cgi, urllib, os, re, os.path, time

from roundup import hyperdb, date
from roundup.i18n import _

try:
    import cPickle as pickle
except ImportError:
    import pickle
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO
try:
    import StructuredText
except ImportError:
    StructuredText = None

# Make sure these modules are loaded
# I need these to run PageTemplates outside of Zope :(
# If we're running in a Zope environment, these modules will be loaded
# already...
if not sys.modules.has_key('zLOG'):
    import zLOG
    sys.modules['zLOG'] = zLOG
if not sys.modules.has_key('MultiMapping'):
    import MultiMapping
    sys.modules['MultiMapping'] = MultiMapping
if not sys.modules.has_key('ComputedAttribute'):
    import ComputedAttribute
    sys.modules['ComputedAttribute'] = ComputedAttribute
if not sys.modules.has_key('ExtensionClass'):
    import ExtensionClass
    sys.modules['ExtensionClass'] = ExtensionClass
if not sys.modules.has_key('Acquisition'):
    import Acquisition
    sys.modules['Acquisition'] = Acquisition

# now it's safe to import PageTemplates, TAL and ZTUtils
from PageTemplates import PageTemplate
from PageTemplates.Expressions import getEngine
from TAL.TALInterpreter import TALInterpreter
import ZTUtils

# XXX WAH pagetemplates aren't pickleable :(
#def getTemplate(dir, name, classname=None, request=None):
#    ''' Interface to get a template, possibly loading a compiled template.
#    '''
#    # source
#    src = os.path.join(dir, name)
#
#    # see if we can get a compile from the template"c" directory (most
#    # likely is "htmlc"
#    split = list(os.path.split(dir))
#    split[-1] = split[-1] + 'c'
#    cdir = os.path.join(*split)
#    split.append(name)
#    cpl = os.path.join(*split)
#
#    # ok, now see if the source is newer than the compiled (or if the
#    # compiled even exists)
#    MTIME = os.path.stat.ST_MTIME
#    if (not os.path.exists(cpl) or os.stat(cpl)[MTIME] < os.stat(src)[MTIME]):
#        # nope, we need to compile
#        pt = RoundupPageTemplate()
#        pt.write(open(src).read())
#        pt.id = name
#
#        # save off the compiled template
#        if not os.path.exists(cdir):
#            os.makedirs(cdir)
#        f = open(cpl, 'wb')
#        pickle.dump(pt, f)
#        f.close()
#    else:
#        # yay, use the compiled template
#        f = open(cpl, 'rb')
#        pt = pickle.load(f)
#    return pt

templates = {}

def getTemplate(dir, name, classname=None, request=None):
    ''' Interface to get a template, possibly loading a compiled template.
    '''
    # find the source, figure the time it was last modified
    src = os.path.join(dir, name)
    stime = os.stat(src)[os.path.stat.ST_MTIME]

    key = (dir, name)
    if templates.has_key(key) and stime < templates[key].mtime:
        # compiled template is up to date
        return templates[key]

    # compile the template
    templates[key] = pt = RoundupPageTemplate()
    pt.write(open(src).read())
    pt.id = name
    pt.mtime = time.time()
    return pt

class RoundupPageTemplate(PageTemplate.PageTemplate):
    ''' A Roundup-specific PageTemplate.

        Interrogate the client to set up the various template variables to
        be available:

        *class*
          The current class of node being displayed as an HTMLClass
          instance.
        *item*
          The current node from the database, if we're viewing a specific
          node, as an HTMLItem instance. If it doesn't exist, then we're
          on a new item page.
        (*classname*)
          this is one of two things:

          1. the *item* is also available under its classname, so a *user*
             node would also be available under the name *user*. This is
             also an HTMLItem instance.
          2. if there's no *item* then the current class is available
             through this name, thus "user/name" and "user/name/menu" will
             still work - the latter will pull information from the form
             if it can.
        *form*
          The current CGI form information as a mapping of form argument
          name to value
        *request*
          Includes information about the current request, including:
           - the url
           - the current index information (``filterspec``, ``filter`` args,
             ``properties``, etc) parsed out of the form. 
           - methods for easy filterspec link generation
           - *user*, the current user node as an HTMLItem instance
        *instance*
          The current instance
        *db*
          The current database, through which db.config may be reached.

        Maybe also:

        *modules*
          python modules made available (XXX: not sure what's actually in
          there tho)
    '''
    def getContext(self, client, classname, request):
        c = {
             'klass': HTMLClass(client, classname),
             'options': {},
             'nothing': None,
             'request': request,
             'content': client.content,
             'db': HTMLDatabase(client),
             'instance': client.instance
        }
        # add in the item if there is one
        if client.nodeid:
            c['item'] = HTMLItem(client.db, classname, client.nodeid)
            c[classname] = c['item']
        else:
            c[classname] = c['klass']
        return c

    def render(self, client, classname, request, **options):
        """Render this Page Template"""

        if not self._v_cooked:
            self._cook()

        __traceback_supplement__ = (PageTemplate.PageTemplateTracebackSupplement, self)

        if self._v_errors:
            raise PTRuntimeError, 'Page Template %s has errors.' % self.id

        # figure the context
        classname = classname or client.classname
        request = request or HTMLRequest(client)
        c = self.getContext(client, classname, request)
        c.update({'options': options})

        # and go
        output = StringIO.StringIO()
        TALInterpreter(self._v_program, self._v_macros,
            getEngine().getContext(c), output, tal=1, strictinsert=0)()
        return output.getvalue()

class HTMLDatabase:
    ''' Return HTMLClasses for valid class fetches
    '''
    def __init__(self, client):
        self.client = client
        self.config = client.db.config
    def __getattr__(self, attr):
        self.client.db.getclass(attr)
        return HTMLClass(self.client, attr)
    def classes(self):
        l = self.client.db.classes.keys()
        l.sort()
        return [HTMLClass(self.client, cn) for cn in l]
        
class HTMLClass:
    ''' Accesses through a class (either through *class* or *db.<classname>*)
    '''
    def __init__(self, client, classname):
        self.client = client
        self.db = client.db
        self.classname = classname
        if classname is not None:
            self.klass = self.db.getclass(self.classname)
            self.props = self.klass.getprops()

    def __repr__(self):
        return '<HTMLClass(0x%x) %s>'%(id(self), self.classname)

    def __getitem__(self, item):
        ''' return an HTMLItem instance'''
        #print 'getitem', (self, attr)
        if item == 'creator':
            return HTMLUser(self.client)

        if not self.props.has_key(item):
            raise KeyError, item
        prop = self.props[item]

        # look up the correct HTMLProperty class
        for klass, htmlklass in propclasses:
            if isinstance(prop, hyperdb.Multilink):
                value = []
            else:
                value = None
            if isinstance(prop, klass):
                return htmlklass(self.db, '', prop, item, value)

        # no good
        raise KeyError, item

    def __getattr__(self, attr):
        ''' convenience access '''
        try:
            return self[attr]
        except KeyError:
            raise AttributeError, attr

    def properties(self):
        ''' Return HTMLProperty for all props
        '''
        l = []
        for name, prop in self.props.items():
            for klass, htmlklass in propclasses:
                if isinstance(prop, hyperdb.Multilink):
                    value = []
                else:
                    value = None
                if isinstance(prop, klass):
                    l.append(htmlklass(self.db, '', prop, name, value))
        return l

    def list(self):
        l = [HTMLItem(self.db, self.classname, x) for x in self.klass.list()]
        return l

    def filter(self, request=None):
        ''' Return a list of items from this class, filtered and sorted
            by the current requested filterspec/filter/sort/group args
        '''
        if request is not None:
            filterspec = request.filterspec
            sort = request.sort
            group = request.group
        l = [HTMLItem(self.db, self.classname, x)
             for x in self.klass.filter(None, filterspec, sort, group)]
        return l

    def classhelp(self, properties, label='?', width='400', height='400'):
        '''pop up a javascript window with class help

           This generates a link to a popup window which displays the 
           properties indicated by "properties" of the class named by
           "classname". The "properties" should be a comma-separated list
           (eg. 'id,name,description').

           You may optionally override the label displayed, the width and
           height. The popup window will be resizable and scrollable.
        '''
        return '<a href="javascript:help_window(\'classhelp?classname=%s&' \
            'properties=%s\', \'%s\', \'%s\')"><b>(%s)</b></a>'%(self.classname,
            properties, width, height, label)

    def submit(self, label="Submit New Entry"):
        ''' Generate a submit button (and action hidden element)
        '''
        return '  <input type="hidden" name=":action" value="new">\n'\
        '  <input type="submit" name="submit" value="%s">'%label

    def history(self):
        return 'New node - no history'

    def renderWith(self, name, **kwargs):
        ''' Render this class with the given template.
        '''
        # create a new request and override the specified args
        req = HTMLRequest(self.client)
        req.classname = self.classname
        req.update(kwargs)

        # new template, using the specified classname and request
        name = self.classname + '.' + name
        pt = getTemplate(self.db.config.TEMPLATES, name)

        # XXX handle PT rendering errors here nicely
        try:
            # use our fabricated request
            return pt.render(self.client, self.classname, req)
        except PageTemplate.PTRuntimeError, message:
            return '<strong>%s</strong><ol>%s</ol>'%(message,
                cgi.escape('<li>'.join(pt._v_errors)))

class HTMLItem:
    ''' Accesses through an *item*
    '''
    def __init__(self, db, classname, nodeid):
        self.db = db
        self.classname = classname
        self.nodeid = nodeid
        self.klass = self.db.getclass(classname)
        self.props = self.klass.getprops()

    def __repr__(self):
        return '<HTMLItem(0x%x) %s %s>'%(id(self), self.classname, self.nodeid)

    def __getitem__(self, item):
        ''' return an HTMLItem instance'''
        if item == 'id':
            return self.nodeid
        if not self.props.has_key(item):
            raise KeyError, item
        prop = self.props[item]

        # get the value, handling missing values
        value = self.klass.get(self.nodeid, item, None)
        if value is None:
            if isinstance(self.props[item], hyperdb.Multilink):
                value = []

        # look up the correct HTMLProperty class
        for klass, htmlklass in propclasses:
            if isinstance(prop, klass):
                return htmlklass(self.db, self.nodeid, prop, item, value)

        raise KeyErorr, item

    def __getattr__(self, attr):
        ''' convenience access to properties '''
        try:
            return self[attr]
        except KeyError:
            raise AttributeError, attr
    
    def submit(self, label="Submit Changes"):
        ''' Generate a submit button (and action hidden element)
        '''
        return '  <input type="hidden" name=":action" value="edit">\n'\
        '  <input type="submit" name="submit" value="%s">'%label

    # XXX this probably should just return the history items, not the HTML
    def history(self, direction='descending'):
        l = ['<table width=100% border=0 cellspacing=0 cellpadding=2>',
            '<tr class="list-header">',
            _('<th align=left><span class="list-item">Date</span></th>'),
            _('<th align=left><span class="list-item">User</span></th>'),
            _('<th align=left><span class="list-item">Action</span></th>'),
            _('<th align=left><span class="list-item">Args</span></th>'),
            '</tr>']
        comments = {}
        history = self.klass.history(self.nodeid)
        history.sort()
        if direction == 'descending':
            history.reverse()
        for id, evt_date, user, action, args in history:
            date_s = str(evt_date).replace("."," ")
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
                        prop = self.props[k]
                    except KeyError:
                        prop = None
                    if prop is not None:
                        if args[k] and (isinstance(prop, hyperdb.Multilink) or
                                isinstance(prop, hyperdb.Link)):
                            # figure what the link class is
                            classname = prop.classname
                            try:
                                linkcl = self.db.getclass(classname)
                            except KeyError:
                                labelprop = None
                                comments[classname] = _('''The linked class
                                    %(classname)s no longer exists''')%locals()
                            labelprop = linkcl.labelprop(1)
                            hrefable = os.path.exists(
                                os.path.join(self.db.config.TEMPLATES,
                                classname+'.item'))

                        if isinstance(prop, hyperdb.Multilink) and \
                                len(args[k]) > 0:
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
                                        if labelprop is not None:
                                            label = linkcl.get(linkid, labelprop)
                                    except IndexError:
                                        comments['no_link'] = _('''<strike>The
                                            linked node no longer
                                            exists</strike>''')
                                        subml.append('<strike>%s</strike>'%label)
                                    else:
                                        if hrefable:
                                            subml.append('<a href="%s%s">%s</a>'%(
                                                classname, linkid, label))
                                ml.append(sublabel + ', '.join(subml))
                            cell.append('%s:\n  %s'%(k, ', '.join(ml)))
                        elif isinstance(prop, hyperdb.Link) and args[k]:
                            label = classname + args[k]
                            # if we have a label property, try to use it
                            # TODO: test for node existence even when
                            # there's no labelprop!
                            if labelprop is not None:
                                try:
                                    label = linkcl.get(args[k], labelprop)
                                except IndexError:
                                    comments['no_link'] = _('''<strike>The
                                        linked node no longer
                                        exists</strike>''')
                                    cell.append(' <strike>%s</strike>,\n'%label)
                                    # "flag" this is done .... euwww
                                    label = None
                            if label is not None:
                                if hrefable:
                                    cell.append('%s: <a href="%s%s">%s</a>\n'%(k,
                                        classname, args[k], label))
                                else:
                                    cell.append('%s: %s' % (k,label))

                        elif isinstance(prop, hyperdb.Date) and args[k]:
                            d = date.Date(args[k])
                            cell.append('%s: %s'%(k, str(d)))

                        elif isinstance(prop, hyperdb.Interval) and args[k]:
                            d = date.Interval(args[k])
                            cell.append('%s: %s'%(k, str(d)))

                        elif isinstance(prop, hyperdb.String) and args[k]:
                            cell.append('%s: %s'%(k, cgi.escape(args[k])))

                        elif not args[k]:
                            cell.append('%s: (no value)\n'%k)

                        else:
                            cell.append('%s: %s\n'%(k, str(args[k])))
                    else:
                        # property no longer exists
                        comments['no_exist'] = _('''<em>The indicated property
                            no longer exists</em>''')
                        cell.append('<em>%s: %s</em>\n'%(k, str(args[k])))
                arg_s = '<br />'.join(cell)
            else:
                # unkown event!!
                comments['unknown'] = _('''<strong><em>This event is not
                    handled by the history display!</em></strong>''')
                arg_s = '<strong><em>' + str(args) + '</em></strong>'
            date_s = date_s.replace(' ', '&nbsp;')
            l.append('<tr><td nowrap valign=top>%s</td><td valign=top>%s</td>'
                '<td valign=top>%s</td><td valign=top>%s</td></tr>'%(date_s,
                user, action, arg_s))
        if comments:
            l.append(_('<tr><td colspan=4><strong>Note:</strong></td></tr>'))
        for entry in comments.values():
            l.append('<tr><td colspan=4>%s</td></tr>'%entry)
        l.append('</table>')
        return '\n'.join(l)

    def remove(self):
        # XXX do what?
        return ''

class HTMLUser(HTMLItem):
    ''' Accesses through the *user* (a special case of item)
    '''
    def __init__(self, client):
        HTMLItem.__init__(self, client.db, 'user', client.userid)
        self.default_classname = client.classname
        self.userid = client.userid

        # used for security checks
        self.security = client.db.security
    _marker = []
    def hasPermission(self, role, classname=_marker):
        ''' Determine if the user has the Role.

            The class being tested defaults to the template's class, but may
            be overidden for this test by suppling an alternate classname.
        '''
        if classname is self._marker:
            classname = self.default_classname
        return self.security.hasPermission(role, self.userid, classname)

class HTMLProperty:
    ''' String, Number, Date, Interval HTMLProperty

        A wrapper object which may be stringified for the plain() behaviour.
    '''
    def __init__(self, db, nodeid, prop, name, value):
        self.db = db
        self.nodeid = nodeid
        self.prop = prop
        self.name = name
        self.value = value
    def __repr__(self):
        return '<HTMLProperty(0x%x) %s %r %r>'%(id(self), self.name, self.prop, self.value)
    def __str__(self):
        return self.plain()
    def __cmp__(self, other):
        if isinstance(other, HTMLProperty):
            return cmp(self.value, other.value)
        return cmp(self.value, other)

class StringHTMLProperty(HTMLProperty):
    def plain(self, escape=0):
        if self.value is None:
            return ''
        if escape:
            return cgi.escape(str(self.value))
        return str(self.value)

    def stext(self, escape=0):
        s = self.plain(escape=escape)
        if not StructuredText:
            return s
        return StructuredText(s,level=1,header=0)

    def field(self, size = 30):
        if self.value is None:
            value = ''
        else:
            value = cgi.escape(str(self.value))
            value = '&quot;'.join(value.split('"'))
        return '<input name="%s" value="%s" size="%s">'%(self.name, value, size)

    def multiline(self, escape=0, rows=5, cols=40):
        if self.value is None:
            value = ''
        else:
            value = cgi.escape(str(self.value))
            value = '&quot;'.join(value.split('"'))
        return '<textarea name="%s" rows="%s" cols="%s">%s</textarea>'%(
            self.name, rows, cols, value)

    def email(self, escape=1):
        ''' fudge email '''
        if self.value is None: value = ''
        else: value = str(self.value)
        value = value.replace('@', ' at ')
        value = value.replace('.', ' ')
        if escape:
            value = cgi.escape(value)
        return value

class PasswordHTMLProperty(HTMLProperty):
    def plain(self):
        if self.value is None:
            return ''
        return _('*encrypted*')

    def field(self, size = 30):
        return '<input type="password" name="%s" size="%s">'%(self.name, size)

class NumberHTMLProperty(HTMLProperty):
    def plain(self):
        return str(self.value)

    def field(self, size = 30):
        if self.value is None:
            value = ''
        else:
            value = cgi.escape(str(self.value))
            value = '&quot;'.join(value.split('"'))
        return '<input name="%s" value="%s" size="%s">'%(self.name, value, size)

class BooleanHTMLProperty(HTMLProperty):
    def plain(self):
        if self.value is None:
            return ''
        return self.value and "Yes" or "No"

    def field(self):
        checked = self.value and "checked" or ""
        s = '<input type="radio" name="%s" value="yes" %s>Yes'%(self.name,
            checked)
        if checked:
            checked = ""
        else:
            checked = "checked"
        s += '<input type="radio" name="%s" value="no" %s>No'%(self.name,
            checked)
        return s

class DateHTMLProperty(HTMLProperty):
    def plain(self):
        if self.value is None:
            return ''
        return str(self.value)

    def field(self, size = 30):
        if self.value is None:
            value = ''
        else:
            value = cgi.escape(str(self.value))
            value = '&quot;'.join(value.split('"'))
        return '<input name="%s" value="%s" size="%s">'%(self.name, value, size)

    def reldate(self, pretty=1):
        if not self.value:
            return ''

        # figure the interval
        interval = date.Date('.') - self.value
        if pretty:
            return interval.pretty()
        return str(interval)

class IntervalHTMLProperty(HTMLProperty):
    def plain(self):
        if self.value is None:
            return ''
        return str(self.value)

    def pretty(self):
        return self.value.pretty()

    def field(self, size = 30):
        if self.value is None:
            value = ''
        else:
            value = cgi.escape(str(self.value))
            value = '&quot;'.join(value.split('"'))
        return '<input name="%s" value="%s" size="%s">'%(self.name, value, size)

class LinkHTMLProperty(HTMLProperty):
    ''' Link HTMLProperty
        Include the above as well as being able to access the class
        information. Stringifying the object itself results in the value
        from the item being displayed. Accessing attributes of this object
        result in the appropriate entry from the class being queried for the
        property accessed (so item/assignedto/name would look up the user
        entry identified by the assignedto property on item, and then the
        name property of that user)
    '''
    def __getattr__(self, attr):
        ''' return a new HTMLItem '''
        #print 'getattr', (self, attr, self.value)
        if not self.value:
            raise AttributeError, "Can't access missing value"
        i = HTMLItem(self.db, self.prop.classname, self.value)
        return getattr(i, attr)

    def plain(self, escape=0):
        if self.value is None:
            return _('[unselected]')
        linkcl = self.db.classes[self.prop.classname]
        k = linkcl.labelprop(1)
        value = str(linkcl.get(self.value, k))
        if escape:
            value = cgi.escape(value)
        return value

    # XXX most of the stuff from here down is of dubious utility - it's easy
    # enough to do in the template by hand (and in some cases, it's shorter
    # and clearer...

    def field(self):
        linkcl = self.db.getclass(self.prop.classname)
        if linkcl.getprops().has_key('order'):  
            sort_on = 'order'  
        else:  
            sort_on = linkcl.labelprop()  
        options = linkcl.filter(None, {}, [sort_on], []) 
        # TODO: make this a field display, not a menu one!
        l = ['<select name="%s">'%property]
        k = linkcl.labelprop(1)
        if value is None:
            s = 'selected '
        else:
            s = ''
        l.append(_('<option %svalue="-1">- no selection -</option>')%s)
        for optionid in options:
            option = linkcl.get(optionid, k)
            s = ''
            if optionid == value:
                s = 'selected '
            if showid:
                lab = '%s%s: %s'%(self.prop.classname, optionid, option)
            else:
                lab = option
            if size is not None and len(lab) > size:
                lab = lab[:size-3] + '...'
            lab = cgi.escape(lab)
            l.append('<option %svalue="%s">%s</option>'%(s, optionid, lab))
        l.append('</select>')
        return '\n'.join(l)

    def download(self, showid=0):
        linkname = self.prop.classname
        linkcl = self.db.getclass(linkname)
        k = linkcl.labelprop(1)
        linkvalue = cgi.escape(str(linkcl.get(self.value, k)))
        if showid:
            label = value
            title = ' title="%s"'%linkvalue
            # note ... this should be urllib.quote(linkcl.get(value, k))
        else:
            label = linkvalue
            title = ''
        return '<a href="%s%s/%s"%s>%s</a>'%(linkname, self.value,
            linkvalue, title, label)

    def menu(self, size=None, height=None, showid=0, additional=[],
            **conditions):
        value = self.value

        # sort function
        sortfunc = make_sort_function(self.db, self.prop.classname)

        # force the value to be a single choice
        if isinstance(value, type('')):
            value = value[0]
        linkcl = self.db.getclass(self.prop.classname)
        l = ['<select name="%s">'%self.name]
        k = linkcl.labelprop(1)
        s = ''
        if value is None:
            s = 'selected '
        l.append(_('<option %svalue="-1">- no selection -</option>')%s)
        if linkcl.getprops().has_key('order'):  
            sort_on = ('+', 'order')
        else:  
            sort_on = ('+', linkcl.labelprop())
        options = linkcl.filter(None, conditions, sort_on, (None, None))
        for optionid in options:
            option = linkcl.get(optionid, k)
            s = ''
            if value in [optionid, option]:
                s = 'selected '
            if showid:
                lab = '%s%s: %s'%(self.prop.classname, optionid, option)
            else:
                lab = option
            if size is not None and len(lab) > size:
                lab = lab[:size-3] + '...'
            if additional:
                m = []
                for propname in additional:
                    m.append(linkcl.get(optionid, propname))
                lab = lab + ' (%s)'%', '.join(map(str, m))
            lab = cgi.escape(lab)
            l.append('<option %svalue="%s">%s</option>'%(s, optionid, lab))
        l.append('</select>')
        return '\n'.join(l)

#    def checklist(self, ...)

class MultilinkHTMLProperty(HTMLProperty):
    ''' Multilink HTMLProperty

        Also be iterable, returning a wrapper object like the Link case for
        each entry in the multilink.
    '''
    def __len__(self):
        ''' length of the multilink '''
        return len(self.value)

    def __getattr__(self, attr):
        ''' no extended attribute accesses make sense here '''
        raise AttributeError, attr

    def __getitem__(self, num):
        ''' iterate and return a new HTMLItem '''
        #print 'getitem', (self, num)
        value = self.value[num]
        return HTMLItem(self.db, self.prop.classname, value)

    def reverse(self):
        ''' return the list in reverse order '''
        l = self.value[:]
        l.reverse()
        return [HTMLItem(self.db, self.prop.classname, value) for value in l]

    def plain(self, escape=0):
        linkcl = self.db.classes[self.prop.classname]
        k = linkcl.labelprop(1)
        labels = []
        for v in self.value:
            labels.append(linkcl.get(v, k))
        value = ', '.join(labels)
        if escape:
            value = cgi.escape(value)
        return value

    # XXX most of the stuff from here down is of dubious utility - it's easy
    # enough to do in the template by hand (and in some cases, it's shorter
    # and clearer...

    def field(self, size=30, showid=0):
        sortfunc = make_sort_function(self.db, self.prop.classname)
        linkcl = self.db.getclass(self.prop.classname)
        value = self.value[:]
        if value:
            value.sort(sortfunc)
        # map the id to the label property
        if not showid:
            k = linkcl.labelprop(1)
            value = [linkcl.get(v, k) for v in value]
        value = cgi.escape(','.join(value))
        return '<input name="%s" size="%s" value="%s">'%(self.name, size, value)

    def menu(self, size=None, height=None, showid=0, additional=[],
            **conditions):
        value = self.value

        # sort function
        sortfunc = make_sort_function(self.db, self.prop.classname)

        linkcl = self.db.getclass(self.prop.classname)
        if linkcl.getprops().has_key('order'):  
            sort_on = ('+', 'order')
        else:  
            sort_on = ('+', linkcl.labelprop())
        options = linkcl.filter(None, conditions, sort_on, (None,None)) 
        height = height or min(len(options), 7)
        l = ['<select multiple name="%s" size="%s">'%(self.name, height)]
        k = linkcl.labelprop(1)
        for optionid in options:
            option = linkcl.get(optionid, k)
            s = ''
            if optionid in value or option in value:
                s = 'selected '
            if showid:
                lab = '%s%s: %s'%(self.prop.classname, optionid, option)
            else:
                lab = option
            if size is not None and len(lab) > size:
                lab = lab[:size-3] + '...'
            if additional:
                m = []
                for propname in additional:
                    m.append(linkcl.get(optionid, propname))
                lab = lab + ' (%s)'%', '.join(m)
            lab = cgi.escape(lab)
            l.append('<option %svalue="%s">%s</option>'%(s, optionid,
                lab))
        l.append('</select>')
        return '\n'.join(l)

# set the propclasses for HTMLItem
propclasses = (
    (hyperdb.String, StringHTMLProperty),
    (hyperdb.Number, NumberHTMLProperty),
    (hyperdb.Boolean, BooleanHTMLProperty),
    (hyperdb.Date, DateHTMLProperty),
    (hyperdb.Interval, IntervalHTMLProperty),
    (hyperdb.Password, PasswordHTMLProperty),
    (hyperdb.Link, LinkHTMLProperty),
    (hyperdb.Multilink, MultilinkHTMLProperty),
)

def make_sort_function(db, classname):
    '''Make a sort function for a given class
    '''
    linkcl = db.getclass(classname)
    if linkcl.getprops().has_key('order'):
        sort_on = 'order'
    else:
        sort_on = linkcl.labelprop()
    def sortfunc(a, b, linkcl=linkcl, sort_on=sort_on):
        return cmp(linkcl.get(a, sort_on), linkcl.get(b, sort_on))
    return sortfunc

def handleListCGIValue(value):
    ''' Value is either a single item or a list of items. Each item has a
        .value that we're actually interested in.
    '''
    if isinstance(value, type([])):
        return [value.value for value in value]
    else:
        return value.value.split(',')

class ShowDict:
    ''' A convenience access to the :columns index parameters
    '''
    def __init__(self, columns):
        self.columns = {}
        for col in columns:
            self.columns[col] = 1
    def __getitem__(self, name):
        return self.columns.has_key(name)

class HTMLRequest:
    ''' The *request*, holding the CGI form and environment.

        "form" the CGI form as a cgi.FieldStorage
        "env" the CGI environment variables
        "url" the current URL path for this request
        "base" the base URL for this instance
        "user" a HTMLUser instance for this user
        "classname" the current classname (possibly None)
        "template_type" the current template type (suffix, also possibly None)

        Index args:
        "columns" dictionary of the columns to display in an index page
        "show" a convenience access to columns - request/show/colname will
               be true if the columns should be displayed, false otherwise
        "sort" index sort column (direction, column name)
        "group" index grouping property (direction, column name)
        "filter" properties to filter the index on
        "filterspec" values to filter the index on
        "search_text" text to perform a full-text search on for an index

    '''
    def __init__(self, client):
        self.client = client

        # easier access vars
        self.form = client.form
        self.env = client.env
        self.base = client.base
        self.url = client.url
        self.user = HTMLUser(client)

        # store the current class name and action
        self.classname = client.classname
        self.template_type = client.template_type

        # extract the index display information from the form
        self.columns = []
        if self.form.has_key(':columns'):
            self.columns = handleListCGIValue(self.form[':columns'])
        self.show = ShowDict(self.columns)

        # sorting
        self.sort = (None, None)
        if self.form.has_key(':sort'):
            sort = self.form[':sort'].value
            if sort.startswith('-'):
                self.sort = ('-', sort[1:])
            else:
                self.sort = ('+', sort)
        if self.form.has_key(':sortdir'):
            self.sort = ('-', self.sort[1])

        # grouping
        self.group = (None, None)
        if self.form.has_key(':group'):
            group = self.form[':group'].value
            if group.startswith('-'):
                self.group = ('-', group[1:])
            else:
                self.group = ('+', group)
        if self.form.has_key(':groupdir'):
            self.group = ('-', self.group[1])

        # filtering
        self.filter = []
        if self.form.has_key(':filter'):
            self.filter = handleListCGIValue(self.form[':filter'])
        self.filterspec = {}
        if self.classname is not None:
            props = self.client.db.getclass(self.classname).getprops()
            for name in self.filter:
                if self.form.has_key(name):
                    prop = props[name]
                    fv = self.form[name]
                    if (isinstance(prop, hyperdb.Link) or
                            isinstance(prop, hyperdb.Multilink)):
                        self.filterspec[name] = handleListCGIValue(fv)
                    else:
                        self.filterspec[name] = fv.value

        # full-text search argument
        self.search_text = None
        if self.form.has_key(':search_text'):
            self.search_text = self.form[':search_text'].value

        # pagination - size and start index
        # figure batch args
        if self.form.has_key(':pagesize'):
            self.pagesize = int(self.form[':pagesize'].value)
        else:
            self.pagesize = 50
        if self.form.has_key(':startwith'):
            self.startwith = int(self.form[':startwith'].value)
        else:
            self.startwith = 0

    def update(self, kwargs):
        self.__dict__.update(kwargs)
        if kwargs.has_key('columns'):
            self.show = ShowDict(self.columns)

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
        return '''
form: %(form)s
url: %(url)r
base: %(base)r
classname: %(classname)r
template_type: %(template_type)r
columns: %(columns)r
sort: %(sort)r
group: %(group)r
filter: %(filter)r
search_text: %(search_text)r
pagesize: %(pagesize)r
startwith: %(startwith)r
env: %(env)s
'''%d

    def indexargs_form(self, columns=1, sort=1, group=1, filter=1,
            filterspec=1):
        ''' return the current index args as form elements '''
        l = []
        s = '<input type="hidden" name="%s" value="%s">'
        if columns and self.columns:
            l.append(s%(':columns', ','.join(self.columns)))
        if sort and self.sort[1] is not None:
            if self.sort[0] == '-':
                val = '-'+self.sort[1]
            else:
                val = self.sort[1]
            l.append(s%(':sort', val))
        if group and self.group[1] is not None:
            if self.group[0] == '-':
                val = '-'+self.group[1]
            else:
                val = self.group[1]
            l.append(s%(':group', val))
        if filter and self.filter:
            l.append(s%(':filter', ','.join(self.filter)))
        if filterspec:
            for k,v in self.filterspec.items():
                l.append(s%(k, ','.join(v)))
        if self.search_text:
            l.append(s%(':search_text', self.search_text))
        l.append(s%(':pagesize', self.pagesize))
        l.append(s%(':startwith', self.startwith))
        return '\n'.join(l)

    def indexargs_href(self, url, args):
        ''' embed the current index args in a URL '''
        l = ['%s=%s'%(k,v) for k,v in args.items()]
        if self.columns:
            l.append(':columns=%s'%(','.join(self.columns)))
        if self.sort[1] is not None:
            if self.sort[0] == '-':
                val = '-'+self.sort[1]
            else:
                val = self.sort[1]
            l.append(':sort=%s'%val)
        if self.group[1] is not None:
            if self.group[0] == '-':
                val = '-'+self.group[1]
            else:
                val = self.group[1]
            l.append(':group=%s'%val)
        if self.filter:
            l.append(':filter=%s'%(','.join(self.filter)))
        for k,v in self.filterspec.items():
            l.append('%s=%s'%(k, ','.join(v)))
        if self.search_text:
            l.append(':search_text=%s'%self.search_text)
        l.append(':pagesize=%s'%self.pagesize)
        l.append(':startwith=%s'%self.startwith)
        return '%s?%s'%(url, '&'.join(l))

    def base_javascript(self):
        return '''
<script language="javascript">
submitted = false;
function submit_once() {
    if (submitted) {
        alert("Your request is being processed.\\nPlease be patient.");
        return 0;
    }
    submitted = true;
    return 1;
}

function help_window(helpurl, width, height) {
    HelpWin = window.open('%s/' + helpurl, 'RoundupHelpWindow', 'scrollbars=yes,resizable=yes,toolbar=no,height='+height+',width='+width);
}
</script>
'''%self.base

    def batch(self):
        ''' Return a batch object for results from the "current search"
        '''
        filterspec = self.filterspec
        sort = self.sort
        group = self.group

        # get the list of ids we're batching over
        klass = self.client.db.getclass(self.classname)
        if self.search_text:
            matches = self.client.db.indexer.search(
                re.findall(r'\b\w{2,25}\b', self.search_text), klass)
        else:
            matches = None
        l = klass.filter(matches, filterspec, sort, group)

        # return the batch object
        return Batch(self.client, self.classname, l, self.pagesize,
            self.startwith)


# extend the standard ZTUtils Batch object to remove dependency on
# Acquisition and add a couple of useful methods
class Batch(ZTUtils.Batch):
    def __init__(self, client, classname, l, size, start, end=0, orphan=0, overlap=0):
        self.client = client
        self.classname = classname
        self.last_index = self.last_item = None
        self.current_item = None
        ZTUtils.Batch.__init__(self, l, size, start, end, orphan, overlap)

    # overwrite so we can late-instantiate the HTMLItem instance
    def __getitem__(self, index):
        if index < 0:
            if index + self.end < self.first: raise IndexError, index
            return self._sequence[index + self.end]
        
        if index >= self.length: raise IndexError, index

        # move the last_item along - but only if the fetched index changes
        # (for some reason, index 0 is fetched twice)
        if index != self.last_index:
            self.last_item = self.current_item
            self.last_index = index

        # wrap the return in an HTMLItem
        self.current_item = HTMLItem(self.client.db, self.classname,
            self._sequence[index+self.first])
        return self.current_item

    def propchanged(self, property):
        ''' Detect if the property marked as being the group property
            changed in the last iteration fetch
        '''
        if (self.last_item is None or
                self.last_item[property] != self.current_item[property]):
            return 1
        return 0

    # override these 'cos we don't have access to acquisition
    def previous(self):
        if self.start == 1:
            return None
        return Batch(self.client, self.classname, self._sequence, self._size,
            self.first - self._size + self.overlap, 0, self.orphan,
            self.overlap)

    def next(self):
        try:
            self._sequence[self.end]
        except IndexError:
            return None
        return Batch(self.client, self.classname, self._sequence, self._size,
            self.end - self.overlap, 0, self.orphan, self.overlap)

    def length(self):
        self.sequence_length = l = len(self._sequence)
        return l

