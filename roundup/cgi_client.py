# $Id: cgi_client.py,v 1.11 2001-07-30 06:17:45 richard Exp $

import os, cgi, pprint, StringIO, urlparse, re, traceback

import roundupdb, htmltemplate, date

class Unauthorised(ValueError):
    pass

class Client:
    def __init__(self, out, db, env, user):
        self.out = out
        self.db = db
        self.env = env
        self.user = user
        self.path = env['PATH_INFO']
        self.split_path = self.path.split('/')

        self.headers_done = 0
        self.form = cgi.FieldStorage(environ=env)
        self.headers_done = 0
        self.debug = 0

    def header(self, headers={'Content-Type':'text/html'}):
        if not headers.has_key('Content-Type'):
            headers['Content-Type'] = 'text/html'
        for entry in headers.items():
            self.out.write('%s: %s\n'%entry)
        self.out.write('\n')
        self.headers_done = 1

    def pagehead(self, title, message=None):
        url = self.env['SCRIPT_NAME'] + '/' #self.env.get('PATH_INFO', '/')
        machine = self.env['SERVER_NAME']
        port = self.env['SERVER_PORT']
        if port != '80': machine = machine + ':' + port
        base = urlparse.urlunparse(('http', machine, url, None, None, None))
        if message is not None:
            message = '<div class="system-msg">%s</div>'%message
        else:
            message = ''
        style = open(os.path.join(self.TEMPLATES, 'style.css')).read()
        userid = self.db.user.lookup(self.user)
        self.write('''<html><head>
<title>%s</title>
<style type="text/css">%s</style>
</head>
<body bgcolor=#ffffff>
%s
<table width=100%% border=0 cellspacing=0 cellpadding=2>
<tr class="location-bar"><td><big><strong>%s</strong></big>
(login: <a href="user%s">%s</a>)</td></tr>
</table>
'''%(title, style, message, title, userid, self.user))

    def pagefoot(self):
        if self.debug:
            self.write('<hr><small><dl>')
            self.write('<dt><b>Path</b></dt>')
            self.write('<dd>%s</dd>'%(', '.join(map(repr, self.split_path))))
            keys = self.form.keys()
            keys.sort()
            if keys:
                self.write('<dt><b>Form entries</b></dt>')
                for k in self.form.keys():
                    v = str(self.form[k].value)
                    self.write('<dd><em>%s</em>:%s</dd>'%(k, cgi.escape(v)))
            keys = self.env.keys()
            keys.sort()
            self.write('<dt><b>CGI environment</b></dt>')
            for k in keys:
                v = self.env[k]
                self.write('<dd><em>%s</em>:%s</dd>'%(k, cgi.escape(v)))
            self.write('</dl></small>')
        self.write('</body></html>')

    def write(self, content):
        if not self.headers_done:
            self.header()
        self.out.write(content)

    def index_arg(self, arg):
        ''' handle the args to index - they might be a list from the form
            (ie. submitted from a form) or they might be a command-separated
            single string (ie. manually constructed GET args)
        '''
        if self.form.has_key(arg):
            arg =  self.form[arg]
            if type(arg) == type([]):
                return [arg.value for arg in arg]
            return arg.value.split(',')
        return []

    def index_filterspec(self):
        ''' pull the index filter spec from the form

        Links and multilinks want to be lists - the rest are straight
        strings.
        '''
        props = self.db.classes[self.classname].getprops()
        # all the form args not starting with ':' are filters
        filterspec = {}
        for key in self.form.keys():
            if key[0] == ':': continue
            prop = props[key]
            value = self.form[key]
            if prop.isLinkType or prop.isMultilinkType:
                if type(value) == type([]):
                    value = [arg.value for arg in value]
                else:
                    value = value.value.split(',')
                l = filterspec.get(key, [])
                l = l + value
                filterspec[key] = l
            else:
                filterspec[key] = value.value
        return filterspec

    default_index_sort = ['-activity']
    default_index_group = ['priority']
    default_index_filter = []
    default_index_columns = ['id','activity','title','status','assignedto']
    default_index_filterspec = {'status': ['1', '2', '3', '4', '5', '6', '7']}
    def index(self):
        ''' put up an index
        '''
        self.classname = 'issue'
        if self.form.has_key(':sort'): sort = self.index_arg(':sort')
        else: sort = self.default_index_sort
        if self.form.has_key(':group'): group = self.index_arg(':group')
        else: group = self.default_index_group
        if self.form.has_key(':filter'): filter = self.index_arg(':filter')
        else: filter = self.default_index_filter
        if self.form.has_key(':columns'): columns = self.index_arg(':columns')
        else: columns = self.default_index_columns
        filterspec = self.index_filterspec()
        if not filterspec:
            filterspec = self.default_index_filterspec
        return self.list(columns=columns, filter=filter, group=group,
            sort=sort, filterspec=filterspec)

    # XXX deviates from spec - loses the '+' (that's a reserved character
    # in URLS
    def list(self, sort=None, group=None, filter=None, columns=None,
            filterspec=None):
        ''' call the template index with the args

            :sort    - sort by prop name, optionally preceeded with '-'
                     to give descending or nothing for ascending sorting.
            :group   - group by prop name, optionally preceeded with '-' or
                     to sort in descending or nothing for ascending order.
            :filter  - selects which props should be displayed in the filter
                     section. Default is all.
            :columns - selects the columns that should be displayed.
                     Default is all.

        '''
        cn = self.classname
        self.pagehead('Index of %s'%cn)
        if sort is None: sort = self.index_arg(':sort')
        if group is None: group = self.index_arg(':group')
        if filter is None: filter = self.index_arg(':filter')
        if columns is None: columns = self.index_arg(':columns')
        if filterspec is None: filterspec = self.index_filterspec()

        htmltemplate.index(self, self.TEMPLATES, self.db, cn, filterspec,
            filter, columns, sort, group)
        self.pagefoot()

    def showitem(self, message=None):
        ''' display an item
        '''
        cn = self.classname
        cl = self.db.classes[cn]

        # possibly perform an edit
        keys = self.form.keys()
        num_re = re.compile('^\d+$')
        if keys:
            changed = []
            props = {}
            try:
                keys = self.form.keys()
                for key in keys:
                    if not cl.properties.has_key(key):
                        continue
                    proptype = cl.properties[key]
                    if proptype.isStringType:
                        value = str(self.form[key].value).strip()
                    elif proptype.isDateType:
                        value = date.Date(str(self.form[key].value))
                    elif proptype.isIntervalType:
                        value = date.Interval(str(self.form[key].value))
                    elif proptype.isLinkType:
                        value = str(self.form[key].value).strip()
                        # handle key values
                        link = cl.properties[key].classname
                        if not num_re.match(value):
                            try:
                                value = self.db.classes[link].lookup(value)
                            except:
                                raise ValueError, 'property "%s": %s not a %s'%(
                                    key, value, link)
                    elif proptype.isMultilinkType:
                        value = self.form[key]
                        if type(value) != type([]):
                            value = [i.strip() for i in str(value.value).split(',')]
                        else:
                            value = [str(i.value).strip() for i in value]
                        link = cl.properties[key].classname
                        l = []
                        for entry in map(str, value):
                            if not num_re.match(entry):
                                try:
                                    entry = self.db.classes[link].lookup(entry)
                                except:
                                    raise ValueError, \
                                        'property "%s": %s not a %s'%(key,
                                        entry, link)
                            l.append(entry)
                        l.sort()
                        value = l
                    # if changed, set it
                    if value != cl.get(self.nodeid, key):
                        changed.append(key)
                        props[key] = value
                cl.set(self.nodeid, **props)

                # if this item has messages, generate an edit message
                # TODO: don't send the edit message to the person who
                # performed the edit
                if (cl.getprops().has_key('messages') and
                        cl.getprops()['messages'].isMultilinkType and
                        cl.getprops()['messages'].classname == 'msg'):
                    nid = self.nodeid
                    m = []
                    for name, prop in cl.getprops().items():
                        # TODO: the None default is only here because we
                        # don't have schema migration :(
                        if prop.isMultilinkType:
                            value = cl.get(nid, name, [])
                        else:
                            value = cl.get(nid, name, None)
                        if prop.isLinkType:
                            link = self.db.classes[prop.classname]
                            key = link.getkey()
                            if value is not None and key:
                                value = link.get(value, key)
                            else:
                                value = '-'
                        elif prop.isMultilinkType:
                            l = []
                            link = self.db.classes[prop.classname]
                            for entry in value:
                                key = link.getkey()
                                if key:
                                    l.append(link.get(entry, link.getkey()))
                                else:
                                    l.append(entry)
                            value = ', '.join(l)
                        if name in changed:
                            chg = '*'
                        else:
                            chg = ' '
                        m.append('%s %s: %s'%(chg, name, value))

                    # handle the note
                    if self.form.has_key('__note'):
                        note = self.form['__note'].value
                        if '\n' in note:
                            summary = re.split(r'\n\r?', note)[0]
                        else:
                            summary = note
                        m.insert(0, '%s\n\n'%note)
                    else:
                        if len(changed) > 1:
                            plural = 's were'
                        else:
                            plural = ' was'
                        summary = 'This %s has been edited through the web '\
                            'and the %s value%s changed.'%(cn,
                            ', '.join(changed), plural)
                        m.insert(0, '%s\n\n'%summary)

                    # now create the message
                    content = '\n'.join(m)
                    message_id = self.db.msg.create(author='1', recipients=[],
                        date=date.Date('.'), summary=summary, content=content)
                    messages = cl.get(nid, 'messages')
                    messages.append(message_id)
                    props = {'messages': messages}
                    cl.set(nid, **props)

                # and some nice feedback for the user
                message = '%s edited ok'%', '.join(changed)
            except:
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                message = '<pre>%s</pre>'%cgi.escape(s.getvalue())

        # now the display
        id = self.nodeid
        if cl.getkey():
            id = cl.get(id, cl.getkey())
        self.pagehead('%s: %s'%(self.classname.capitalize(), id), message)

        nodeid = self.nodeid

        # use the template to display the item
        htmltemplate.item(self, self.TEMPLATES, self.db, self.classname, nodeid)
        self.pagefoot()
    showissue = showitem
    showmsg = showitem

    def newissue(self, message=None):
        ''' add an issue
        '''
        cn = self.classname
        cl = self.db.classes[cn]

        # possibly perform a create
        keys = self.form.keys()
        num_re = re.compile('^\d+$')
        if [i for i in keys if i[0] != ':']:
            props = {}
            try:
                keys = self.form.keys()
                for key in keys:
                    if not cl.properties.has_key(key):
                        continue
                    proptype = cl.properties[key]
                    if proptype.isStringType:
                        value = self.form[key].value.strip()
                    elif proptype.isDateType:
                        value = date.Date(self.form[key].value.strip())
                    elif proptype.isIntervalType:
                        value = date.Interval(self.form[key].value.strip())
                    elif proptype.isLinkType:
                        value = self.form[key].value.strip()
                        # handle key values
                        link = cl.properties[key].classname
                        if not num_re.match(value):
                            try:
                                value = self.db.classes[link].lookup(value)
                            except:
                                raise ValueError, 'property "%s": %s not a %s'%(
                                    key, value, link)
                    elif proptype.isMultilinkType:
                        value = self.form[key]
                        if type(value) != type([]):
                            value = [i.strip() for i in value.value.split(',')]
                        else:
                            value = [i.value.strip() for i in value]
                        link = cl.properties[key].classname
                        l = []
                        for entry in map(str, value):
                            if not num_re.match(entry):
                                try:
                                    entry = self.db.classes[link].lookup(entry)
                                except:
                                    raise ValueError, \
                                        'property "%s": %s not a %s'%(key,
                                        entry, link)
                            l.append(entry)
                        l.sort()
                        value = l
                    props[key] = value
                nid = cl.create(**props)

                # link if necessary
                for key in keys:
                    print key,
                    if key == ':multilink':
                        value = self.form[key].value
                        if type(value) != type([]): value = [value]
                        for value in value:
                            designator, property = value.split(':')
                            print 'miltilinking to ', designator, property
                            link, nodeid = roundupdb.splitDesignator(designator)
                            link = self.db.classes[link]
                            value = link.get(nodeid, property)
                            value.append(nid)
                            link.set(nodeid, **{property: value})
                    elif key == ':link':
                        value = self.form[key].value
                        if type(value) != type([]): value = [value]
                        for value in value:
                            designator, property = value.split(':')
                            print 'linking to ', designator, property
                            link, nodeid = roundupdb.splitDesignator(designator)
                            link = self.db.classes[link]
                            link.set(nodeid, **{property: nid})
                    else:
                        print 'ignoring'

                # if this item has messages, 
                if (cl.getprops().has_key('messages') and
                        cl.getprops()['messages'].isMultilinkType and
                        cl.getprops()['messages'].classname == 'msg'):
                    # generate an edit message - nosyreactor will send it
                    m = []
                    for name, prop in cl.getprops().items():
                        value = cl.get(nid, name)
                        if prop.isLinkType:
                            link = self.db.classes[prop.classname]
                            key = link.getkey()
                            if value is not None and key:
                                value = link.get(value, key)
                            else:
                                value = '-'
                        elif prop.isMultilinkType:
                            l = []
                            link = self.db.classes[prop.classname]
                            for entry in value:
                                key = link.getkey()
                                if key:
                                    l.append(link.get(entry, link.getkey()))
                                else:
                                    l.append(entry)
                            value = ', '.join(l)
                        m.append('%s: %s'%(name, value))

                    # handle the note
                    note = None
                    if self.form.has_key('__note'):
                        note = self.form['__note']
                    if note and note.value:
                        note = note.value
                        if '\n' in note:
                            summary = re.split(r'\n\r?', note)[0]
                        else:
                            summary = note
                        m.append('\n%s\n'%note)
                    else:
                        summary = 'This %s has been created through the web.'%cn
                        m.append('\n%s\s'%summary)

                    # now create the message
                    content = '\n'.join(m)
                    message_id = self.db.msg.create(author='1', recipients=[],
                        date=date.Date('.'), summary=summary, content=content)
                    messages = cl.get(nid, 'messages')
                    messages.append(message_id)
                    props = {'messages': messages}
                    cl.set(nid, **props)

                # and some nice feedback for the user
                message = '%s created ok'%cn
            except:
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                message = '<pre>%s</pre>'%cgi.escape(s.getvalue())
        self.pagehead('New %s'%self.classname.capitalize(), message)
        htmltemplate.newitem(self, self.TEMPLATES, self.db, self.classname,
            self.form)
        self.pagefoot()
    newuser = newissue

    def showuser(self, message=None):
        ''' display an item
        '''
        if self.user in ('admin', self.db.user.get(self.nodeid, 'username')):
            self.showitem(message)
        else:
            raise Unauthorised

    def showfile(self):
        ''' display a file
        '''
        nodeid = self.nodeid
        cl = self.db.file
        type = cl.get(nodeid, 'type')
        if type == 'message/rfc822':
            type = 'text/plain'
        self.header(headers={'Content-Type': type})
        self.write(cl.get(nodeid, 'content'))

    def classes(self, message=None):
        ''' display a list of all the classes in the database
        '''
        if self.user == 'admin':
            self.pagehead('Table of classes', message)
            classnames = self.db.classes.keys()
            classnames.sort()
            self.write('<table border=0 cellspacing=0 cellpadding=2>\n')
            for cn in classnames:
                cl = self.db.getclass(cn)
                self.write('<tr class="list-header"><th colspan=2 align=left>%s</th></tr>'%cn.capitalize())
                for key, value in cl.properties.items():
                    if value is None: value = ''
                    else: value = str(value)
                    self.write('<tr><th align=left>%s</th><td>%s</td></tr>'%(
                        key, cgi.escape(value)))
            self.write('</table>')
            self.pagefoot()
        else:
            raise Unauthorised

    def main(self, dre=re.compile(r'([^\d]+)(\d+)'), nre=re.compile(r'new(\w+)')):
        path = self.split_path
        if not path or path[0] in ('', 'index'):
            self.index()
        elif len(path) == 1:
            if path[0] == 'list_classes':
                self.classes()
                return
            m = dre.match(path[0])
            if m:
                self.classname = m.group(1)
                self.nodeid = m.group(2)
                getattr(self, 'show%s'%self.classname)()
                return
            m = nre.match(path[0])
            if m:
                self.classname = m.group(1)
                getattr(self, 'new%s'%self.classname)()
                return
            self.classname = path[0]
            self.list()
        else:
            raise 'ValueError', 'Path not understood'

    def __del__(self):
        self.db.close()

#
# $Log: not supported by cvs2svn $
# Revision 1.10  2001/07/30 02:37:34  richard
# Temporary measure until we have decent schema migration...
#
# Revision 1.9  2001/07/30 01:25:07  richard
# Default implementation is now "classic" rather than "extended" as one would
# expect.
#
# Revision 1.8  2001/07/29 08:27:40  richard
# Fixed handling of passed-in values in form elements (ie. during a
# drill-down)
#
# Revision 1.7  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.6  2001/07/29 04:04:00  richard
# Moved some code around allowing for subclassing to change behaviour.
#
# Revision 1.5  2001/07/28 08:16:52  richard
# New issue form handles lack of note better now.
#
# Revision 1.4  2001/07/28 00:34:34  richard
# Fixed some non-string node ids.
#
# Revision 1.3  2001/07/23 03:56:30  richard
# oops, missed a config removal
#
# Revision 1.2  2001/07/22 12:09:32  richard
# Final commit of Grande Splite
#
# Revision 1.1  2001/07/22 11:58:35  richard
# More Grande Splite
#
#
# vim: set filetype=python ts=4 sw=4 et si
