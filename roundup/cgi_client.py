#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
# 
# $Id: cgi_client.py,v 1.134 2002-07-09 04:19:09 richard Exp $

__doc__ = """
WWW request handler (also used in the stand-alone server).
"""

import os, cgi, StringIO, urlparse, re, traceback, mimetypes, urllib
import binascii, Cookie, time, random

import roundupdb, htmltemplate, date, hyperdb, password
from roundup.i18n import _

class Unauthorised(ValueError):
    pass

class NotFound(ValueError):
    pass

class Client:
    '''
    A note about login
    ------------------

    If the user has no login cookie, then they are anonymous. There
    are two levels of anonymous use. If there is no 'anonymous' user, there
    is no login at all and the database is opened in read-only mode. If the
    'anonymous' user exists, the user is logged in using that user (though
    there is no cookie). This allows them to modify the database, and all
    modifications are attributed to the 'anonymous' user.
    '''

    def __init__(self, instance, request, env, form=None):
        hyperdb.traceMark()
        self.instance = instance
        self.request = request
        self.env = env
        self.path = env['PATH_INFO']
        self.split_path = self.path.split('/')
        self.instance_path_name = env['INSTANCE_NAME']
        url = self.env['SCRIPT_NAME'] + '/'
        machine = self.env['SERVER_NAME']
        port = self.env['SERVER_PORT']
        if port != '80': machine = machine + ':' + port
        self.base = urlparse.urlunparse(('http', env['HTTP_HOST'], url,
            None, None, None))

        if form is None:
            self.form = cgi.FieldStorage(environ=env)
        else:
            self.form = form
        self.headers_done = 0
        try:
            self.debug = int(env.get("ROUNDUP_DEBUG", 0))
        except ValueError:
            # someone gave us a non-int debug level, turn it off
            self.debug = 0

    def getuid(self):
        try:
            return self.db.user.lookup(self.user)
        except KeyError:
            if self.user is None:
                # user is not logged in and username 'anonymous' doesn't
                # exist in the database
                err = _('anonymous users have read-only access only')
            else:
                err = _("sanity check: unknown user name `%s'")%self.user
            raise Unauthorised, errmsg

    def header(self, headers=None):
        '''Put up the appropriate header.
        '''
        if headers is None:
            headers = {'Content-Type':'text/html'}
        if not headers.has_key('Content-Type'):
            headers['Content-Type'] = 'text/html'
        self.request.send_response(200)
        for entry in headers.items():
            self.request.send_header(*entry)
        self.request.end_headers()
        self.headers_done = 1
        if self.debug:
            self.headers_sent = headers

    global_javascript = '''
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
    HelpWin = window.open('%(base)s%(instance_path_name)s/' + helpurl, 'HelpWindow', 'scrollbars=yes,resizable=yes,toolbar=no,height='+height+',width='+width);
}

</script>
'''
    def make_index_link(self, name):
        '''Turn a configuration entry into a hyperlink...
        '''
        # get the link label and spec
        spec = getattr(self.instance, name+'_INDEX')

        d = {}
        d[':sort'] = ','.join(map(urllib.quote, spec['SORT']))
        d[':group'] = ','.join(map(urllib.quote, spec['GROUP']))
        d[':filter'] = ','.join(map(urllib.quote, spec['FILTER']))
        d[':columns'] = ','.join(map(urllib.quote, spec['COLUMNS']))
        d[':pagesize'] = spec.get('PAGESIZE','50')

        # snarf the filterspec
        filterspec = spec['FILTERSPEC'].copy()

        # now format the filterspec
        for k, l in filterspec.items():
            # fix up the CURRENT USER if needed (handle None too since that's
            # the old flag value)
            if l in (None, 'CURRENT USER'):
                if not self.user:
                    continue
                l = [self.db.user.lookup(self.user)]

            # add
            d[urllib.quote(k)] = ','.join(map(urllib.quote, l))

        # finally, format the URL
        return '<a href="%s?%s">%s</a>'%(spec['CLASS'],
            '&'.join([k+'='+v for k,v in d.items()]), spec['LABEL'])


    def pagehead(self, title, message=None):
        '''Display the page heading, with information about the tracker and
            links to more information
        '''

        # include any important message
        if message is not None:
            message = _('<div class="system-msg">%(message)s</div>')%locals()
        else:
            message = ''

        # style sheet (CSS)
        style = open(os.path.join(self.instance.TEMPLATES, 'style.css')).read()

        # figure who the user is
        user_name = self.user or ''
        if user_name not in ('', 'anonymous'):
            userid = self.db.user.lookup(self.user)
        else:
            userid = None

        # figure all the header links
        if hasattr(self.instance, 'HEADER_INDEX_LINKS'):
            links = []
            for name in self.instance.HEADER_INDEX_LINKS:
                spec = getattr(self.instance, name + '_INDEX')
                # skip if we need to fill in the logged-in user id there's
                # no user logged in
                if (spec['FILTERSPEC'].has_key('assignedto') and
                        spec['FILTERSPEC']['assignedto'] in ('CURRENT USER',
                        None) and userid is None):
                    continue
                links.append(self.make_index_link(name))
        else:
            # no config spec - hard-code
            links = [
                _('All <a href="issue?status=-1,unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=-activity&:filter=status&:columns=id,activity,status,title,assignedto&:group=priority&show_customization=1">Issues</a>'),
                _('Unassigned <a href="issue?assignedto=-1&status=-1,unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=-activity&:filter=status,assignedto&:columns=id,activity,status,title,assignedto&:group=priority&show_customization=1">Issues</a>')
            ]

        # if they're logged in, include links to their information, and the
        # ability to add an issue
        if user_name not in ('', 'anonymous'):
            user_info = _('''
<a href="user%(userid)s">My Details</a> | <a href="logout">Logout</a>
''')%locals()

            # figure the "add class" links
            if hasattr(self.instance, 'HEADER_ADD_LINKS'):
                classes = self.instance.HEADER_ADD_LINKS
            else:
                classes = ['issue']
            l = []
            for class_name in classes:
                cap_class = class_name.capitalize()
                links.append(_('Add <a href="new%(class_name)s">'
                    '%(cap_class)s</a>')%locals())

            # if there's no config header link spec, force a user link here
            if not hasattr(self.instance, 'HEADER_INDEX_LINKS'):
                links.append(_('<a href="issue?assignedto=%(userid)s&status=-1,unread,chatting,open,pending&:filter=status,resolution,assignedto&:sort=-activity&:columns=id,activity,status,resolution,title,creator&:group=type&show_customization=1">My Issues</a>')%locals())
        else:
            user_info = _('<a href="login">Login</a>')
            add_links = ''

        # if the user is admin, include admin links
        admin_links = ''
        if user_name == 'admin':
            links.append(_('<a href="list_classes">Class List</a>'))
            links.append(_('<a href="user">User List</a>'))
            links.append(_('<a href="newuser">Add User</a>'))

        # add the search links
        if hasattr(self.instance, 'HEADER_SEARCH_LINKS'):
            classes = self.instance.HEADER_SEARCH_LINKS
        else:
            classes = ['issue']
        l = []
        for class_name in classes:
            cap_class = class_name.capitalize()
            links.append(_('Search <a href="search%(class_name)s">'
                '%(cap_class)s</a>')%locals())

        # now we have all the links, join 'em
        links = '\n | '.join(links)

        # include the javascript bit
        global_javascript = self.global_javascript%self.__dict__

        # finally, format the header
        self.write(_('''<html><head>
<title>%(title)s</title>
<style type="text/css">%(style)s</style>
</head>
%(global_javascript)s
<body bgcolor=#ffffff>
%(message)s
<table width=100%% border=0 cellspacing=0 cellpadding=2>
<tr class="location-bar"><td><big><strong>%(title)s</strong></big></td>
<td align=right valign=bottom>%(user_name)s</td></tr>
<tr class="location-bar">
<td align=left>%(links)s</td>
<td align=right>%(user_info)s</td>
</table><br>
''')%locals())

    def pagefoot(self):
        if self.debug:
            self.write(_('<hr><small><dl><dt><b>Path</b></dt>'))
            self.write('<dd>%s</dd>'%(', '.join(map(repr, self.split_path))))
            keys = self.form.keys()
            keys.sort()
            if keys:
                self.write(_('<dt><b>Form entries</b></dt>'))
                for k in self.form.keys():
                    v = self.form.getvalue(k, "<empty>")
                    if type(v) is type([]):
                        # Multiple username fields specified
                        v = "|".join(v)
                    self.write('<dd><em>%s</em>=%s</dd>'%(k, cgi.escape(v)))
            keys = self.headers_sent.keys()
            keys.sort()
            self.write(_('<dt><b>Sent these HTTP headers</b></dt>'))
            for k in keys:
                v = self.headers_sent[k]
                self.write('<dd><em>%s</em>=%s</dd>'%(k, cgi.escape(v)))
            keys = self.env.keys()
            keys.sort()
            self.write(_('<dt><b>CGI environment</b></dt>'))
            for k in keys:
                v = self.env[k]
                self.write('<dd><em>%s</em>=%s</dd>'%(k, cgi.escape(v)))
            self.write('</dl></small>')
        self.write('</body></html>')

    def write(self, content):
        if not self.headers_done:
            self.header()
        self.request.wfile.write(content)

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

    def index_sort(self):
        # first try query string
        x = self.index_arg(':sort')
        if x:
            return x
        # nope - get the specs out of the form
        specs = []
        for colnm in self.db.getclass(self.classname).getprops().keys():
            desc = ''
            try:
                spec = self.form[':%s_ss' % colnm]
            except KeyError:
                continue
            spec = spec.value
            if spec:
                if spec[-1] == '-':
                    desc='-'
                    spec = spec[0]
                specs.append((int(spec), colnm, desc))
        specs.sort()
        x = []
        for _, colnm, desc in specs:
            x.append('%s%s' % (desc, colnm))
        return x
    
    def index_filterspec(self, filter):
        ''' pull the index filter spec from the form

        Links and multilinks want to be lists - the rest are straight
        strings.
        '''
        filterspec = {}
        props = self.db.classes[self.classname].getprops()
        for colnm in filter:
            widget = ':%s_fs' % colnm
            try:
                val = self.form[widget]
            except KeyError:
                try:
                    val = self.form[colnm]
                except KeyError:
                    # they checked the filter box but didn't enter a value
                    continue
            propdescr = props.get(colnm, None)
            if propdescr is None:
                print "huh? %r is in filter & form, but not in Class!" % colnm
                raise "butthead programmer"
            if (isinstance(propdescr, hyperdb.Link) or
                isinstance(propdescr, hyperdb.Multilink)):
                if type(val) == type([]):
                    val = [arg.value for arg in val]
                else:
                    val = val.value.split(',')
                l = filterspec.get(colnm, [])
                l = l + val
                filterspec[colnm] = l
            else:
                filterspec[colnm] = val.value
            
        return filterspec
    
    def customization_widget(self):
        ''' The customization widget is visible by default. The widget
            visibility is remembered by show_customization.  Visibility
            is not toggled if the action value is "Redisplay"
        '''
        if not self.form.has_key('show_customization'):
            visible = 1
        else:
            visible = int(self.form['show_customization'].value)
            if self.form.has_key('action'):
                if self.form['action'].value != 'Redisplay':
                    visible = self.form['action'].value == '+'
            
        return visible

    # TODO: make this go away some day...
    default_index_sort = ['-activity']
    default_index_group = ['priority']
    default_index_filter = ['status']
    default_index_columns = ['id','activity','title','status','assignedto']
    default_index_filterspec = {'status': ['1', '2', '3', '4', '5', '6', '7']}
    default_pagesize = '50'

    def _get_customisation_info(self):
        # see if the web has supplied us with any customisation info
        defaults = 1
        for key in ':sort', ':group', ':filter', ':columns', ':pagesize':
            if self.form.has_key(key):
                defaults = 0
                break
        if defaults:
            # try the instance config first
            if hasattr(self.instance, 'DEFAULT_INDEX'):
                d = self.instance.DEFAULT_INDEX
                self.classname = d['CLASS']
                sort = d['SORT']
                group = d['GROUP']
                filter = d['FILTER']
                columns = d['COLUMNS']
                filterspec = d['FILTERSPEC']
                pagesize = d.get('PAGESIZE', '50')

            else:
                # nope - fall back on the old way of doing it
                self.classname = 'issue'
                sort = self.default_index_sort
                group = self.default_index_group
                filter = self.default_index_filter
                columns = self.default_index_columns
                filterspec = self.default_index_filterspec
                pagesize = self.default_pagesize
        else:
            # make list() extract the info from the CGI environ
            self.classname = 'issue'
            sort = group = filter = columns = filterspec = pagesize = None
        return columns, filter, group, sort, filterspec, pagesize

    def index(self):
        ''' put up an index - no class specified
        '''
        columns, filter, group, sort, filterspec, pagesize = \
            self._get_customisation_info()
        return self.list(columns=columns, filter=filter, group=group,
            sort=sort, filterspec=filterspec, pagesize=pagesize)

    def searchnode(self):
        columns, filter, group, sort, filterspec, pagesize = \
            self._get_customisation_info()
##        show_nodes = 1
##        if len(self.form.keys()) == 0:
##            # get the default search filters from instance_config
##            if hasattr(self.instance, 'SEARCH_FILTERS'):
##                for f in self.instance.SEARCH_FILTERS:
##                    spec = getattr(self.instance, f)
##                    if spec['CLASS'] == self.classname:
##                        filter = spec['FILTER']
##                
##            show_nodes = 0
##            show_customization = 1
##        return self.list(columns=columns, filter=filter, group=group,
##            sort=sort, filterspec=filterspec,
##            show_customization=show_customization, show_nodes=show_nodes,
##            pagesize=pagesize)
        cn = self.classname
        self.pagehead(_('%(instancename)s: Index of %(classname)s')%{
            'classname': cn, 'instancename': self.instance.INSTANCE_NAME})
        index = htmltemplate.IndexTemplate(self, self.instance.TEMPLATES, cn)
        self.write('<form onSubmit="return submit_once()" action="%s">\n'%self.classname)
        all_columns = self.db.getclass(cn).getprops().keys()
        all_columns.sort()
        index.filter_section('', filter, columns, group, all_columns, sort,
                             filterspec, pagesize, 0)
        self.pagefoot()
        index.db = index.cl = index.properties = None
        index.clear()

    # XXX deviates from spec - loses the '+' (that's a reserved character
    # in URLS
    def list(self, sort=None, group=None, filter=None, columns=None,
            filterspec=None, show_customization=None, show_nodes=1, pagesize=None):
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
        cl = self.db.classes[cn]
        self.pagehead(_('%(instancename)s: Index of %(classname)s')%{
            'classname': cn, 'instancename': self.instance.INSTANCE_NAME})
        if sort is None: sort = self.index_sort()
        if group is None: group = self.index_arg(':group')
        if filter is None: filter = self.index_arg(':filter')
        if columns is None: columns = self.index_arg(':columns')
        if filterspec is None: filterspec = self.index_filterspec(filter)
        if show_customization is None:
            show_customization = self.customization_widget()
        if self.form.has_key('search_text'):
            search_text = self.form['search_text'].value
        else:
            search_text = ''
        if pagesize is None:
            if self.form.has_key(':pagesize'):
                pagesize = self.form[':pagesize'].value
            else:
                pagesize = '50'
        pagesize = int(pagesize)
        if self.form.has_key(':startwith'):
            startwith = int(self.form[':startwith'].value)
        else:
            startwith = 0

        index = htmltemplate.IndexTemplate(self, self.instance.TEMPLATES, cn)
        try:
            index.render(filterspec, search_text, filter, columns, sort, 
                group, show_customization=show_customization, 
                show_nodes=show_nodes, pagesize=pagesize, startwith=startwith)
        except htmltemplate.MissingTemplateError:
            self.basicClassEditPage()
        self.pagefoot()

    def basicClassEditPage(self):
        '''Display a basic edit page that allows simple editing of the
           nodes of the current class
        '''
        if self.user != 'admin':
            raise Unauthorised
        w = self.write
        cn = self.classname
        cl = self.db.classes[cn]
        idlessprops = cl.getprops(protected=0).keys()
        props = ['id'] + idlessprops


        # get the CSV module
        try:
            import csv
        except ImportError:
            w(_('Sorry, you need the csv module to use this function.<br>\n'
                'Get it from: <a href="http://www.object-craft.com.au/projects/csv/">http://www.object-craft.com.au/projects/csv/'))
            return

        # do the edit
        if self.form.has_key('rows'):
            rows = self.form['rows'].value.splitlines()
            p = csv.parser()
            found = {}
            line = 0
            for row in rows:
                line += 1
                values = p.parse(row)
                # not a complete row, keep going
                if not values: continue

                # extract the nodeid
                nodeid, values = values[0], values[1:]
                found[nodeid] = 1

                # confirm correct weight
                if len(idlessprops) != len(values):
                    w(_('Not enough values on line %(line)s'%{'line':line}))
                    return

                # extract the new values
                d = {}
                for name, value in zip(idlessprops, values):
                    d[name] = value.strip()

                # perform the edit
                if cl.hasnode(nodeid):
                    # edit existing
                    cl.set(nodeid, **d)
                else:
                    # new node
                    found[cl.create(**d)] = 1

            # retire the removed entries
            for nodeid in cl.list():
                if not found.has_key(nodeid):
                    cl.retire(nodeid)

        w(_('''<p class="form-help">You may edit the contents of the
        "%(classname)s" class using this form. The lines are full-featured
        Comma-Separated-Value lines, so you may include commas and even
        newlines by enclosing the values in double-quotes ("). Double
        quotes themselves must be quoted by doubling ("").</p>
        <p class="form-help">Remove entries by deleting their line. Add
        new entries by appending
        them to the table - put an X in the id column.</p>''')%{'classname':cn})

        l = []
        for name in props:
            l.append(name)
        w('<tt>')
        w(', '.join(l) + '\n')
        w('</tt>')

        w('<form onSubmit="return submit_once()" method="POST">')
        w('<textarea name="rows" cols=80 rows=15>')
        p = csv.parser()
        for nodeid in cl.list():
            l = []
            for name in props:
                l.append(cgi.escape(str(cl.get(nodeid, name))))
            w(p.join(l) + '\n')

        w(_('</textarea><br><input type="submit" value="Save Changes"></form>'))

    def classhelp(self):
        '''Display a table of class info
        '''
        w = self.write
        cn = self.form['classname'].value
        cl = self.db.classes[cn]
        props = self.form['properties'].value.split(',')
        if cl.labelprop(1) in props:
            sort = [cl.labelprop(1)]
        else:
            sort = props[0]

        w('<table border=1 cellspacing=0 cellpaddin=2>')
        w('<tr>')
        for name in props:
            w('<th align=left>%s</th>'%name)
        w('</tr>')
        for nodeid in cl.filter(None, {}, sort, []): #cl.list():
            w('<tr>')
            for name in props:
                value = cgi.escape(str(cl.get(nodeid, name)))
                w('<td align="left" valign="top">%s</td>'%value)
            w('</tr>')
        w('</table>')

    def shownode(self, message=None, num_re=re.compile('^\d+$')):
        ''' display an item
        '''
        cn = self.classname
        cl = self.db.classes[cn]
        if self.form.has_key(':multilink'):
            link = self.form[':multilink'].value
            designator, linkprop = link.split(':')
            xtra = ' for <a href="%s">%s</a>' % (designator, designator)
        else:
            xtra = ''

        # possibly perform an edit
        keys = self.form.keys()
        # don't try to set properties if the user has just logged in
        if keys and not self.form.has_key('__login_name'):
            try:
                props = parsePropsFromForm(self.db, cl, self.form, self.nodeid)
                # make changes to the node
                self._changenode(props)
                # handle linked nodes 
                self._post_editnode(self.nodeid)
                # and some nice feedback for the user
                if props:
                    message = _('%(changes)s edited ok')%{'changes':
                        ', '.join(props.keys())}
                elif self.form.has_key('__note') and self.form['__note'].value:
                    message = _('note added')
                elif (self.form.has_key('__file') and
                        self.form['__file'].filename):
                    message = _('file added')
                else:
                    message = _('nothing changed')
            except:
                self.db.rollback()
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                message = '<pre>%s</pre>'%cgi.escape(s.getvalue())

        # now the display
        id = self.nodeid
        if cl.getkey():
            id = cl.get(id, cl.getkey())
        self.pagehead('%s: %s %s'%(self.classname.capitalize(), id, xtra), message)

        nodeid = self.nodeid

        # use the template to display the item
        item = htmltemplate.ItemTemplate(self, self.instance.TEMPLATES,
            self.classname)
        item.render(nodeid)

        self.pagefoot()
    showissue = shownode
    showmsg = shownode
    searchissue = searchnode

    def _changenode(self, props):
        ''' change the node based on the contents of the form
        '''
        cl = self.db.classes[self.classname]

        # create the message
        message, files = self._handle_message()
        if message:
            props['messages'] = cl.get(self.nodeid, 'messages') + [message]
        if files:
            props['files'] = cl.get(self.nodeid, 'files') + files

        # make the changes
        cl.set(self.nodeid, **props)

    def _createnode(self):
        ''' create a node based on the contents of the form
        '''
        cl = self.db.classes[self.classname]
        props = parsePropsFromForm(self.db, cl, self.form)

        # check for messages and files
        message, files = self._handle_message()
        if message:
            props['messages'] = [message]
        if files:
            props['files'] = files
        # create the node and return it's id
        return cl.create(**props)

    def _handle_message(self):
        ''' generate an edit message
        '''
        # handle file attachments 
        files = []
        if self.form.has_key('__file'):
            file = self.form['__file']
            if file.filename:
                filename = file.filename.split('\\')[-1]
                mime_type = mimetypes.guess_type(filename)[0]
                if not mime_type:
                    mime_type = "application/octet-stream"
                # create the new file entry
                files.append(self.db.file.create(type=mime_type,
                    name=filename, content=file.file.read()))

        # we don't want to do a message if none of the following is true...
        cn = self.classname
        cl = self.db.classes[self.classname]
        props = cl.getprops()
        note = None
        # in a nutshell, don't do anything if there's no note or there's no
        # NOSY
        if self.form.has_key('__note'):
            note = self.form['__note'].value.strip()
        if not note:
            return None, files
        if not props.has_key('messages'):
            return None, files
        if not isinstance(props['messages'], hyperdb.Multilink):
            return None, files
        if not props['messages'].classname == 'msg':
            return None, files
        if not (self.form.has_key('nosy') or note):
            return None, files

        # handle the note
        if '\n' in note:
            summary = re.split(r'\n\r?', note)[0]
        else:
            summary = note
        m = ['%s\n'%note]

        # handle the messageid
        # TODO: handle inreplyto
        messageid = "<%s.%s.%s@%s>"%(time.time(), random.random(),
            self.classname, self.instance.MAIL_DOMAIN)

        # now create the message, attaching the files
        content = '\n'.join(m)
        message_id = self.db.msg.create(author=self.getuid(),
            recipients=[], date=date.Date('.'), summary=summary,
            content=content, files=files, messageid=messageid)

        # update the messages property
        return message_id, files

    def _post_editnode(self, nid):
        '''Do the linking part of the node creation.

           If a form element has :link or :multilink appended to it, its
           value specifies a node designator and the property on that node
           to add _this_ node to as a link or multilink.

           This is typically used on, eg. the file upload page to indicated
           which issue to link the file to.

           TODO: I suspect that this and newfile will go away now that
           there's the ability to upload a file using the issue __file form
           element!
        '''
        cn = self.classname
        cl = self.db.classes[cn]
        # link if necessary
        keys = self.form.keys()
        for key in keys:
            if key == ':multilink':
                value = self.form[key].value
                if type(value) != type([]): value = [value]
                for value in value:
                    designator, property = value.split(':')
                    link, nodeid = roundupdb.splitDesignator(designator)
                    link = self.db.classes[link]
                    # take a dupe of the list so we're not changing the cache
                    value = link.get(nodeid, property)[:]
                    value.append(nid)
                    link.set(nodeid, **{property: value})
            elif key == ':link':
                value = self.form[key].value
                if type(value) != type([]): value = [value]
                for value in value:
                    designator, property = value.split(':')
                    link, nodeid = roundupdb.splitDesignator(designator)
                    link = self.db.classes[link]
                    link.set(nodeid, **{property: nid})

    def newnode(self, message=None):
        ''' Add a new node to the database.
        
        The form works in two modes: blank form and submission (that is,
        the submission goes to the same URL). **Eventually this means that
        the form will have previously entered information in it if
        submission fails.

        The new node will be created with the properties specified in the
        form submission. For multilinks, multiple form entries are handled,
        as are prop=value,value,value. You can't mix them though.

        If the new node is to be referenced from somewhere else immediately
        (ie. the new node is a file that is to be attached to a support
        issue) then supply one of these arguments in addition to the usual
        form entries:
            :link=designator:property
            :multilink=designator:property
        ... which means that once the new node is created, the "property"
        on the node given by "designator" should now reference the new
        node's id. The node id will be appended to the multilink.
        '''
        cn = self.classname
        cl = self.db.classes[cn]
        if self.form.has_key(':multilink'):
            link = self.form[':multilink'].value
            designator, linkprop = link.split(':')
            xtra = ' for <a href="%s">%s</a>' % (designator, designator)
        else:
            xtra = ''

        # possibly perform a create
        keys = self.form.keys()
        if [i for i in keys if i[0] != ':']:
            props = {}
            try:
                nid = self._createnode()
                # handle linked nodes 
                self._post_editnode(nid)
                # and some nice feedback for the user
                message = _('%(classname)s created ok')%{'classname': cn}

                # render the newly created issue
                self.db.commit()
                self.nodeid = nid
                self.pagehead('%s: %s'%(self.classname.capitalize(), nid),
                    message)
                item = htmltemplate.ItemTemplate(self, self.instance.TEMPLATES, 
                    self.classname)
                item.render(nid)
                self.pagefoot()
                return
            except:
                self.db.rollback()
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                message = '<pre>%s</pre>'%cgi.escape(s.getvalue())
        self.pagehead(_('New %(classname)s %(xtra)s')%{
                'classname': self.classname.capitalize(),
                'xtra': xtra }, message)

        # call the template
        newitem = htmltemplate.NewItemTemplate(self, self.instance.TEMPLATES,
            self.classname)
        newitem.render(self.form)

        self.pagefoot()
    newissue = newnode

    def newuser(self, message=None):
        ''' Add a new user to the database.

            Don't do any of the message or file handling, just create the node.
        '''
        cn = self.classname
        cl = self.db.classes[cn]

        # possibly perform a create
        keys = self.form.keys()
        if [i for i in keys if i[0] != ':']:
            try:
                props = parsePropsFromForm(self.db, cl, self.form)
                nid = cl.create(**props)
                # handle linked nodes 
                self._post_editnode(nid)
                # and some nice feedback for the user
                message = _('%(classname)s created ok')%{'classname': cn}
            except:
                self.db.rollback()
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                message = '<pre>%s</pre>'%cgi.escape(s.getvalue())
        self.pagehead(_('New %(classname)s')%{'classname':
             self.classname.capitalize()}, message)

        # call the template
        newitem = htmltemplate.NewItemTemplate(self, self.instance.TEMPLATES,
            self.classname)
        newitem.render(self.form)

        self.pagefoot()

    def newfile(self, message=None):
        ''' Add a new file to the database.
        
        This form works very much the same way as newnode - it just has a
        file upload.
        '''
        cn = self.classname
        cl = self.db.classes[cn]
        props = parsePropsFromForm(self.db, cl, self.form)
        if self.form.has_key(':multilink'):
            link = self.form[':multilink'].value
            designator, linkprop = link.split(':')
            xtra = ' for <a href="%s">%s</a>' % (designator, designator)
        else:
            xtra = ''

        # possibly perform a create
        keys = self.form.keys()
        if [i for i in keys if i[0] != ':']:
            try:
                file = self.form['content']
                mime_type = mimetypes.guess_type(file.filename)[0]
                if not mime_type:
                    mime_type = "application/octet-stream"
                # save the file
                props['type'] = mime_type
                props['name'] = file.filename
                props['content'] = file.file.read()
                nid = cl.create(**props)
                # handle linked nodes
                self._post_editnode(nid)
                # and some nice feedback for the user
                message = _('%(classname)s created ok')%{'classname': cn}
            except:
                self.db.rollback()
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                message = '<pre>%s</pre>'%cgi.escape(s.getvalue())

        self.pagehead(_('New %(classname)s %(xtra)s')%{
                'classname': self.classname.capitalize(),
                'xtra': xtra }, message)
        newitem = htmltemplate.NewItemTemplate(self, self.instance.TEMPLATES,
            self.classname)
        newitem.render(self.form)
        self.pagefoot()

    def showuser(self, message=None, num_re=re.compile('^\d+$')):
        '''Display a user page for editing. Make sure the user is allowed
            to edit this node, and also check for password changes.
        '''
        if self.user == 'anonymous':
            raise Unauthorised

        user = self.db.user

        # get the username of the node being edited
        node_user = user.get(self.nodeid, 'username')

        if self.user not in ('admin', node_user):
            raise Unauthorised

        #
        # perform any editing
        #
        keys = self.form.keys()
        if keys:
            try:
                props = parsePropsFromForm(self.db, user, self.form,
                    self.nodeid)
                set_cookie = 0
                if props.has_key('password'):
                    password = self.form['password'].value.strip()
                    if not password:
                        # no password was supplied - don't change it
                        del props['password']
                    elif self.nodeid == self.getuid():
                        # this is the logged-in user's password
                        set_cookie = password
                user.set(self.nodeid, **props)
                # and some feedback for the user
                message = _('%(changes)s edited ok')%{'changes':
                    ', '.join(props.keys())}
            except:
                self.db.rollback()
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                message = '<pre>%s</pre>'%cgi.escape(s.getvalue())
        else:
            set_cookie = 0

        # fix the cookie if the password has changed
        if set_cookie:
            self.set_cookie(self.user, set_cookie)

        #
        # now the display
        #
        self.pagehead(_('User: %(user)s')%{'user': node_user}, message)

        # use the template to display the item
        item = htmltemplate.ItemTemplate(self, self.instance.TEMPLATES, 'user')
        item.render(self.nodeid)
        self.pagefoot()

    def showfile(self):
        ''' display a file
        '''
        nodeid = self.nodeid
        cl = self.db.classes[self.classname]
        mime_type = cl.get(nodeid, 'type')
        if mime_type == 'message/rfc822':
            mime_type = 'text/plain'
        self.header(headers={'Content-Type': mime_type})
        self.write(cl.get(nodeid, 'content'))

    def classes(self, message=None):
        ''' display a list of all the classes in the database
        '''
        if self.user == 'admin':
            self.pagehead(_('Table of classes'), message)
            classnames = self.db.classes.keys()
            classnames.sort()
            self.write('<table border=0 cellspacing=0 cellpadding=2>\n')
            for cn in classnames:
                cl = self.db.getclass(cn)
                self.write('<tr class="list-header"><th colspan=2 align=left>'
                    '<a href="%s">%s</a></th></tr>'%(cn, cn.capitalize()))
                for key, value in cl.properties.items():
                    if value is None: value = ''
                    else: value = str(value)
                    self.write('<tr><th align=left>%s</th><td>%s</td></tr>'%(
                        key, cgi.escape(value)))
            self.write('</table>')
            self.pagefoot()
        else:
            raise Unauthorised

    def login(self, message=None, newuser_form=None, action='index'):
        '''Display a login page.
        '''
        self.pagehead(_('Login to roundup'), message)
        self.write(_('''
<table>
<tr><td colspan=2 class="strong-header">Existing User Login</td></tr>
<form onSubmit="return submit_once()" action="login_action" method=POST>
<input type="hidden" name="__destination_url" value="%(action)s">
<tr><td align=right>Login name: </td>
    <td><input name="__login_name"></td></tr>
<tr><td align=right>Password: </td>
    <td><input type="password" name="__login_password"></td></tr>
<tr><td></td>
    <td><input type="submit" value="Log In"></td></tr>
</form>
''')%locals())
        if self.user is None and self.instance.ANONYMOUS_REGISTER == 'deny':
            self.write('</table>')
            self.pagefoot()
            return
        values = {'realname': '', 'organisation': '', 'address': '',
            'phone': '', 'username': '', 'password': '', 'confirm': '',
            'action': action, 'alternate_addresses': ''}
        if newuser_form is not None:
            for key in newuser_form.keys():
                values[key] = newuser_form[key].value
        self.write(_('''
<p>
<tr><td colspan=2 class="strong-header">New User Registration</td></tr>
<tr><td colspan=2><em>marked items</em> are optional...</td></tr>
<form onSubmit="return submit_once()" action="newuser_action" method=POST>
<input type="hidden" name="__destination_url" value="%(action)s">
<tr><td align=right><em>Name: </em></td>
    <td><input name="realname" value="%(realname)s" size=40></td></tr>
<tr><td align=right><em>Organisation: </em></td>
    <td><input name="organisation" value="%(organisation)s" size=40></td></tr>
<tr><td align=right>E-Mail Address: </td>
    <td><input name="address" value="%(address)s" size=40></td></tr>
<tr><td align=right><em>Alternate E-mail Addresses: </em></td>
    <td><textarea name="alternate_addresses" rows=5 cols=40>%(alternate_addresses)s</textarea></td></tr>
<tr><td align=right><em>Phone: </em></td>
    <td><input name="phone" value="%(phone)s"></td></tr>
<tr><td align=right>Preferred Login name: </td>
    <td><input name="username" value="%(username)s"></td></tr>
<tr><td align=right>Password: </td>
    <td><input type="password" name="password" value="%(password)s"></td></tr>
<tr><td align=right>Password Again: </td>
    <td><input type="password" name="confirm" value="%(confirm)s"></td></tr>
<tr><td></td>
    <td><input type="submit" value="Register"></td></tr>
</form>
</table>
''')%values)
        self.pagefoot()

    def login_action(self, message=None):
        '''Attempt to log a user in and set the cookie

        returns 0 if a page is generated as a result of this call, and
        1 if not (ie. the login is successful
        '''
        if not self.form.has_key('__login_name'):
            self.login(message=_('Username required'))
            return 0
        self.user = self.form['__login_name'].value
        if self.form.has_key('__login_password'):
            password = self.form['__login_password'].value
        else:
            password = ''
        # make sure the user exists
        try:
            uid = self.db.user.lookup(self.user)
        except KeyError:
            name = self.user
            self.make_user_anonymous()
            action = self.form['__destination_url'].value
            self.login(message=_('No such user "%(name)s"')%locals(),
                action=action)
            return 0

        # and that the password is correct
        pw = self.db.user.get(uid, 'password')
        if password != pw:
            self.make_user_anonymous()
            action = self.form['__destination_url'].value
            self.login(message=_('Incorrect password'), action=action)
            return 0

        self.set_cookie(self.user, password)
        return 1

    def newuser_action(self, message=None):
        '''Attempt to create a new user based on the contents of the form
        and then set the cookie.

        return 1 on successful login
        '''
        # re-open the database as "admin"
        self.db = self.instance.open('admin')

        # TODO: pre-check the required fields and username key property
        cl = self.db.user
        try:
            props = parsePropsFromForm(self.db, cl, self.form)
            uid = cl.create(**props)
        except ValueError, message:
            action = self.form['__destination_url'].value
            self.login(message, action=action)
            return 0
        self.user = cl.get(uid, 'username')
        password = cl.get(uid, 'password')
        self.set_cookie(self.user, self.form['password'].value)
        return 1

    def set_cookie(self, user, password):
        # construct the cookie
        user = binascii.b2a_base64('%s:%s'%(user, password)).strip()
        if user[-1] == '=':
          if user[-2] == '=':
            user = user[:-2]
          else:
            user = user[:-1]
        expire = Cookie._getdate(86400*365)
        path = '/'.join((self.env['SCRIPT_NAME'], self.env['INSTANCE_NAME']))
        self.header({'Set-Cookie': 'roundup_user=%s; expires=%s; Path=%s;' % (
            user, expire, path)})

    def make_user_anonymous(self):
        # make us anonymous if we can
        try:
            self.db.user.lookup('anonymous')
            self.user = 'anonymous'
        except KeyError:
            self.user = None

    def logout(self, message=None):
        self.make_user_anonymous()
        # construct the logout cookie
        now = Cookie._getdate()
        path = '/'.join((self.env['SCRIPT_NAME'], self.env['INSTANCE_NAME']))
        self.header({'Set-Cookie':
            'roundup_user=deleted; Max-Age=0; expires=%s; Path=%s;'%(now,
            path)})
        self.login()

    def main(self):
        '''Wrap the database accesses so we can close the database cleanly
        '''
        # determine the uid to use
        self.db = self.instance.open('admin')
        cookie = Cookie.Cookie(self.env.get('HTTP_COOKIE', ''))
        user = 'anonymous'
        if (cookie.has_key('roundup_user') and
                cookie['roundup_user'].value != 'deleted'):
            cookie = cookie['roundup_user'].value
            if len(cookie)%4:
              cookie = cookie + '='*(4-len(cookie)%4)
            try:
                user, password = binascii.a2b_base64(cookie).split(':')
            except (TypeError, binascii.Error, binascii.Incomplete):
                # damaged cookie!
                user, password = 'anonymous', ''

            # make sure the user exists
            try:
                uid = self.db.user.lookup(user)
                # now validate the password
                if password != self.db.user.get(uid, 'password'):
                    user = 'anonymous'
            except KeyError:
                user = 'anonymous'

        # make sure the anonymous user is valid if we're using it
        if user == 'anonymous':
            self.make_user_anonymous()
        else:
            self.user = user

        # re-open the database for real, using the user
        self.db = self.instance.open(self.user)

        # now figure which function to call
        path = self.split_path

        # default action to index if the path has no information in it
        if not path or path[0] in ('', 'index'):
            action = 'index'
        else:
            action = path[0]

        # Everthing ignores path[1:]
        #  - The file download link generator actually relies on this - it
        #    appends the name of the file to the URL so the download file name
        #    is correct, but doesn't actually use it.

        # everyone is allowed to try to log in
        if action == 'login_action':
            # try to login
            if not self.login_action():
                return
            # figure the resulting page
            action = self.form['__destination_url'].value
            if not action:
                action = 'index'
            self.do_action(action)
            return

        # allow anonymous people to register
        if action == 'newuser_action':
            # if we don't have a login and anonymous people aren't allowed to
            # register, then spit up the login form
            if self.instance.ANONYMOUS_REGISTER == 'deny' and self.user is None:
                if action == 'login':
                    self.login()         # go to the index after login
                else:
                    self.login(action=action)
                return
            # try to add the user
            if not self.newuser_action():
                return
            # figure the resulting page
            action = self.form['__destination_url'].value
            if not action:
                action = 'index'

        # no login or registration, make sure totally anonymous access is OK
        elif self.instance.ANONYMOUS_ACCESS == 'deny' and self.user is None:
            if action == 'login':
                self.login()             # go to the index after login
            else:
                self.login(action=action)
            return

        # just a regular action
        self.do_action(action)

        # commit all changes to the database
        self.db.commit()

    def do_action(self, action, dre=re.compile(r'([^\d]+)(\d+)'),
            nre=re.compile(r'new(\w+)'), sre=re.compile(r'search(\w+)')):
        '''Figure the user's action and do it.
        '''
        # here be the "normal" functionality
        if action == 'index':
            self.index()
            return
        if action == 'list_classes':
            self.classes()
            return
        if action == 'classhelp':
            self.classhelp()
            return
        if action == 'login':
            self.login()
            return
        if action == 'logout':
            self.logout()
            return

        # see if we're to display an existing node
        m = dre.match(action)
        if m:
            self.classname = m.group(1)
            self.nodeid = m.group(2)
            try:
                cl = self.db.classes[self.classname]
            except KeyError:
                raise NotFound, self.classname
            try:
                cl.get(self.nodeid, 'id')
            except IndexError:
                raise NotFound, self.nodeid
            try:
                func = getattr(self, 'show%s'%self.classname)
            except AttributeError:
                raise NotFound, 'show%s'%self.classname
            func()
            return

        # see if we're to put up the new node page
        m = nre.match(action)
        if m:
            self.classname = m.group(1)
            try:
                func = getattr(self, 'new%s'%self.classname)
            except AttributeError:
                raise NotFound, 'new%s'%self.classname
            func()
            return

        # see if we're to put up the new node page
        m = sre.match(action)
        if m:
            self.classname = m.group(1)
            try:
                func = getattr(self, 'search%s'%self.classname)
            except AttributeError:
                raise NotFound
            func()
            return

        # otherwise, display the named class
        self.classname = action
        try:
            self.db.getclass(self.classname)
        except KeyError:
            raise NotFound, self.classname
        self.list()


class ExtendedClient(Client): 
    '''Includes pages and page heading information that relate to the
       extended schema.
    ''' 
    showsupport = Client.shownode
    showtimelog = Client.shownode
    newsupport = Client.newnode
    newtimelog = Client.newnode
    searchsupport = Client.searchnode

    default_index_sort = ['-activity']
    default_index_group = ['priority']
    default_index_filter = ['status']
    default_index_columns = ['activity','status','title','assignedto']
    default_index_filterspec = {'status': ['1', '2', '3', '4', '5', '6', '7']}
    default_pagesize = '50'

def parsePropsFromForm(db, cl, form, nodeid=0, num_re=re.compile('^\d+$')):
    '''Pull properties for the given class out of the form.
    '''
    props = {}
    keys = form.keys()
    for key in keys:
        if not cl.properties.has_key(key):
            continue
        proptype = cl.properties[key]
        if isinstance(proptype, hyperdb.String):
            value = form[key].value.strip()
        elif isinstance(proptype, hyperdb.Password):
            value = password.Password(form[key].value.strip())
        elif isinstance(proptype, hyperdb.Date):
            value = form[key].value.strip()
            if value:
                value = date.Date(form[key].value.strip())
            else:
                value = None
        elif isinstance(proptype, hyperdb.Interval):
            value = form[key].value.strip()
            if value:
                value = date.Interval(form[key].value.strip())
            else:
                value = None
        elif isinstance(proptype, hyperdb.Link):
            value = form[key].value.strip()
            # see if it's the "no selection" choice
            if value == '-1':
                # don't set this property
                continue
            else:
                # handle key values
                link = cl.properties[key].classname
                if not num_re.match(value):
                    try:
                        value = db.classes[link].lookup(value)
                    except KeyError:
                        raise ValueError, _('property "%(propname)s": '
                            '%(value)s not a %(classname)s')%{'propname':key, 
                            'value': value, 'classname': link}
        elif isinstance(proptype, hyperdb.Multilink):
            value = form[key]
            if type(value) != type([]):
                value = [i.strip() for i in value.value.split(',')]
            else:
                value = [i.value.strip() for i in value]
            link = cl.properties[key].classname
            l = []
            for entry in map(str, value):
                if entry == '': continue
                if not num_re.match(entry):
                    try:
                        entry = db.classes[link].lookup(entry)
                    except KeyError:
                        raise ValueError, _('property "%(propname)s": '
                            '"%(value)s" not an entry of %(classname)s')%{
                            'propname':key, 'value': entry, 'classname': link}
                l.append(entry)
            l.sort()
            value = l

        # get the old value
        if nodeid:
            try:
                existing = cl.get(nodeid, key)
            except KeyError:
                # this might be a new property for which there is no existing
                # value
                if not cl.properties.has_key(key): raise

            # if changed, set it
            if value != existing:
                props[key] = value
        else:
            props[key] = value
    return props

#
# $Log: not supported by cvs2svn $
# Revision 1.133  2002/07/08 15:32:05  gmcm
# Pagination of index pages.
# New search form.
#
# Revision 1.132  2002/07/08 07:26:14  richard
# ehem
#
# Revision 1.131  2002/07/08 06:53:57  richard
# Not sure why the cgi_client had an indexer argument.
#
# Revision 1.130  2002/06/27 12:01:53  gmcm
# If the form has a :multilink, put a back href in the pageheader (back to the linked-to node).
# Some minor optimizations (only compile regexes once).
#
# Revision 1.129  2002/06/20 23:52:11  richard
# Better handling of unauth attempt to edit stuff
#
# Revision 1.128  2002/06/12 21:28:25  gmcm
# Allow form to set user-properties on a Fileclass.
# Don't assume that a Fileclass is named "files".
#
# Revision 1.127  2002/06/11 06:38:24  richard
#  . #565996 ] The "Attach a File to this Issue" fails
#
# Revision 1.126  2002/05/29 01:16:17  richard
# Sorry about this huge checkin! It's fixing a lot of related stuff in one go
# though.
#
# . #541941 ] changing multilink properties by mail
# . #526730 ] search for messages capability
# . #505180 ] split MailGW.handle_Message
#   - also changed cgi client since it was duplicating the functionality
# . build htmlbase if tests are run using CVS checkout (removed note from
#   installation.txt)
# . don't create an empty message on email issue creation if the email is empty
#
# Revision 1.125  2002/05/25 07:16:24  rochecompaan
# Merged search_indexing-branch with HEAD
#
# Revision 1.124  2002/05/24 02:09:24  richard
# Nothing like a live demo to show up the bugs ;)
#
# Revision 1.123  2002/05/22 05:04:13  richard
# Oops
#
# Revision 1.122  2002/05/22 04:12:05  richard
#  . applied patch #558876 ] cgi client customization
#    ... with significant additions and modifications ;)
#    - extended handling of ML assignedto to all places it's handled
#    - added more NotFound info
#
# Revision 1.121  2002/05/21 06:08:10  richard
# Handle migration
#
# Revision 1.120  2002/05/21 06:05:53  richard
#  . #551483 ] assignedto in Client.make_index_link
#
# Revision 1.119  2002/05/15 06:21:21  richard
#  . node caching now works, and gives a small boost in performance
#
# As a part of this, I cleaned up the DEBUG output and implemented TRACE
# output (HYPERDBTRACE='file to trace to') with checkpoints at the start of
# CGI requests. Run roundup with python -O to skip all the DEBUG/TRACE stuff
# (using if __debug__ which is compiled out with -O)
#
# Revision 1.118  2002/05/12 23:46:33  richard
# ehem, part 2
#
# Revision 1.117  2002/05/12 23:42:29  richard
# ehem
#
# Revision 1.116  2002/05/02 08:07:49  richard
# Added the ADD_AUTHOR_TO_NOSY handling to the CGI interface.
#
# Revision 1.115  2002/04/02 01:56:10  richard
#  . stop sending blank (whitespace-only) notes
#
# Revision 1.114.2.4  2002/05/02 11:49:18  rochecompaan
# Allow customization of the search filters that should be displayed
# on the search page.
#
# Revision 1.114.2.3  2002/04/20 13:23:31  rochecompaan
# We now have a separate search page for nodes.  Search links for
# different classes can be customized in instance_config similar to
# index links.
#
# Revision 1.114.2.2  2002/04/19 19:54:42  rochecompaan
# cgi_client.py
#     removed search link for the time being
#     moved rendering of matches to htmltemplate
# hyperdb.py
#     filtering of nodes on full text search incorporated in filter method
# roundupdb.py
#     added paramater to call of filter method
# roundup_indexer.py
#     added search method to RoundupIndexer class
#
# Revision 1.114.2.1  2002/04/03 11:55:57  rochecompaan
#  . Added feature #526730 - search for messages capability
#
# Revision 1.114  2002/03/17 23:06:05  richard
# oops
#
# Revision 1.113  2002/03/14 23:59:24  richard
#  . #517734 ] web header customisation is obscure
#
# Revision 1.112  2002/03/12 22:52:26  richard
# more pychecker warnings removed
#
# Revision 1.111  2002/02/25 04:32:21  richard
# ahem
#
# Revision 1.110  2002/02/21 07:19:08  richard
# ... and label, width and height control for extra flavour!
#
# Revision 1.109  2002/02/21 07:08:19  richard
# oops
#
# Revision 1.108  2002/02/21 07:02:54  richard
# The correct var is "HTTP_HOST"
#
# Revision 1.107  2002/02/21 06:57:38  richard
#  . Added popup help for classes using the classhelp html template function.
#    - add <display call="classhelp('priority', 'id,name,description')">
#      to an item page, and it generates a link to a popup window which displays
#      the id, name and description for the priority class. The description
#      field won't exist in most installations, but it will be added to the
#      default templates.
#
# Revision 1.106  2002/02/21 06:23:00  richard
# *** empty log message ***
#
# Revision 1.105  2002/02/20 05:52:10  richard
# better error handling
#
# Revision 1.104  2002/02/20 05:45:17  richard
# Use the csv module for generating the form entry so it's correct.
# [also noted the sf.net feature request id in the change log]
#
# Revision 1.103  2002/02/20 05:05:28  richard
#  . Added simple editing for classes that don't define a templated interface.
#    - access using the admin "class list" interface
#    - limited to admin-only
#    - requires the csv module from object-craft (url given if it's missing)
#
# Revision 1.102  2002/02/15 07:08:44  richard
#  . Alternate email addresses are now available for users. See the MIGRATION
#    file for info on how to activate the feature.
#
# Revision 1.101  2002/02/14 23:39:18  richard
# . All forms now have "double-submit" protection when Javascript is enabled
#   on the client-side.
#
# Revision 1.100  2002/01/16 07:02:57  richard
#  . lots of date/interval related changes:
#    - more relaxed date format for input
#
# Revision 1.99  2002/01/16 03:02:42  richard
# #503793 ] changing assignedto resets nosy list
#
# Revision 1.98  2002/01/14 02:20:14  richard
#  . changed all config accesses so they access either the instance or the
#    config attriubute on the db. This means that all config is obtained from
#    instance_config instead of the mish-mash of classes. This will make
#    switching to a ConfigParser setup easier too, I hope.
#
# At a minimum, this makes migration a _little_ easier (a lot easier in the
# 0.5.0 switch, I hope!)
#
# Revision 1.97  2002/01/11 23:22:29  richard
#  . #502437 ] rogue reactor and unittest
#    in short, the nosy reactor was modifying the nosy list. That code had
#    been there for a long time, and I suspsect it was there because we
#    weren't generating the nosy list correctly in other places of the code.
#    We're now doing that, so the nosy-modifying code can go away from the
#    nosy reactor.
#
# Revision 1.96  2002/01/10 05:26:10  richard
# missed a parsePropsFromForm in last update
#
# Revision 1.95  2002/01/10 03:39:45  richard
#  . fixed some problems with web editing and change detection
#
# Revision 1.94  2002/01/09 13:54:21  grubert
# _add_assignedto_to_nosy did set nosy to assignedto only, no adding.
#
# Revision 1.93  2002/01/08 11:57:12  richard
# crying out for real configuration handling... :(
#
# Revision 1.92  2002/01/08 04:12:05  richard
# Changed message-id format to "<%s.%s.%s%s@%s>" so it complies with RFC822
#
# Revision 1.91  2002/01/08 04:03:47  richard
# I mucked the intent of the code up.
#
# Revision 1.90  2002/01/08 03:56:55  richard
# Oops, missed this before the beta:
#  . #495392 ] empty nosy -patch
#
# Revision 1.89  2002/01/07 20:24:45  richard
# *mutter* stupid cutnpaste
#
# Revision 1.88  2002/01/02 02:31:38  richard
# Sorry for the huge checkin message - I was only intending to implement #496356
# but I found a number of places where things had been broken by transactions:
#  . modified ROUNDUPDBSENDMAILDEBUG to be SENDMAILDEBUG and hold a filename
#    for _all_ roundup-generated smtp messages to be sent to.
#  . the transaction cache had broken the roundupdb.Class set() reactors
#  . newly-created author users in the mailgw weren't being committed to the db
#
# Stuff that made it into CHANGES.txt (ie. the stuff I was actually working
# on when I found that stuff :):
#  . #496356 ] Use threading in messages
#  . detectors were being registered multiple times
#  . added tests for mailgw
#  . much better attaching of erroneous messages in the mail gateway
#
# Revision 1.87  2001/12/23 23:18:49  richard
# We already had an admin-specific section of the web heading, no need to add
# another one :)
#
# Revision 1.86  2001/12/20 15:43:01  rochecompaan
# Features added:
#  .  Multilink properties are now displayed as comma separated values in
#     a textbox
#  .  The add user link is now only visible to the admin user
#  .  Modified the mail gateway to reject submissions from unknown
#     addresses if ANONYMOUS_ACCESS is denied
#
# Revision 1.85  2001/12/20 06:13:24  rochecompaan
# Bugs fixed:
#   . Exception handling in hyperdb for strings-that-look-like numbers got
#     lost somewhere
#   . Internet Explorer submits full path for filename - we now strip away
#     the path
# Features added:
#   . Link and multilink properties are now displayed sorted in the cgi
#     interface
#
# Revision 1.84  2001/12/18 15:30:30  rochecompaan
# Fixed bugs:
#  .  Fixed file creation and retrieval in same transaction in anydbm
#     backend
#  .  Cgi interface now renders new issue after issue creation
#  .  Could not set issue status to resolved through cgi interface
#  .  Mail gateway was changing status back to 'chatting' if status was
#     omitted as an argument
#
# Revision 1.83  2001/12/15 23:51:01  richard
# Tested the changes and fixed a few problems:
#  . files are now attached to the issue as well as the message
#  . newuser is a real method now since we don't want to do the message/file
#    stuff for it
#  . added some documentation
# The really big changes in the diff are a result of me moving some code
# around to keep like methods together a bit better.
#
# Revision 1.82  2001/12/15 19:24:39  rochecompaan
#  . Modified cgi interface to change properties only once all changes are
#    collected, files created and messages generated.
#  . Moved generation of change note to nosyreactors.
#  . We now check for changes to "assignedto" to ensure it's added to the
#    nosy list.
#
# Revision 1.81  2001/12/12 23:55:00  richard
# Fixed some problems with user editing
#
# Revision 1.80  2001/12/12 23:27:14  richard
# Added a Zope frontend for roundup.
#
# Revision 1.79  2001/12/10 22:20:01  richard
# Enabled transaction support in the bsddb backend. It uses the anydbm code
# where possible, only replacing methods where the db is opened (it uses the
# btree opener specifically.)
# Also cleaned up some change note generation.
# Made the backends package work with pydoc too.
#
# Revision 1.78  2001/12/07 05:59:27  rochecompaan
# Fixed small bug that prevented adding issues through the web.
#
# Revision 1.77  2001/12/06 22:48:29  richard
# files multilink was being nuked in post_edit_node
#
# Revision 1.76  2001/12/05 14:26:44  rochecompaan
# Removed generation of change note from "sendmessage" in roundupdb.py.
# The change note is now generated when the message is created.
#
# Revision 1.75  2001/12/04 01:25:08  richard
# Added some rollbacks where we were catching exceptions that would otherwise
# have stopped committing.
#
# Revision 1.74  2001/12/02 05:06:16  richard
# . We now use weakrefs in the Classes to keep the database reference, so
#   the close() method on the database is no longer needed.
#   I bumped the minimum python requirement up to 2.1 accordingly.
# . #487480 ] roundup-server
# . #487476 ] INSTALL.txt
#
# I also cleaned up the change message / post-edit stuff in the cgi client.
# There's now a clearly marked "TODO: append the change note" where I believe
# the change note should be added there. The "changes" list will obviously
# have to be modified to be a dict of the changes, or somesuch.
#
# More testing needed.
#
# Revision 1.73  2001/12/01 07:17:50  richard
# . We now have basic transaction support! Information is only written to
#   the database when the commit() method is called. Only the anydbm
#   backend is modified in this way - neither of the bsddb backends have been.
#   The mail, admin and cgi interfaces all use commit (except the admin tool
#   doesn't have a commit command, so interactive users can't commit...)
# . Fixed login/registration forwarding the user to the right page (or not,
#   on a failure)
#
# Revision 1.72  2001/11/30 20:47:58  rochecompaan
# Links in page header are now consistent with default sort order.
#
# Fixed bugs:
#     - When login failed the list of issues were still rendered.
#     - User was redirected to index page and not to his destination url
#       if his first login attempt failed.
#
# Revision 1.71  2001/11/30 20:28:10  rochecompaan
# Property changes are now completely traceable, whether changes are
# made through the web or by email
#
# Revision 1.70  2001/11/30 00:06:29  richard
# Converted roundup/cgi_client.py to use _()
# Added the status file, I18N_PROGRESS.txt
#
# Revision 1.69  2001/11/29 23:19:51  richard
# Removed the "This issue has been edited through the web" when a valid
# change note is supplied.
#
# Revision 1.68  2001/11/29 04:57:23  richard
# a little comment
#
# Revision 1.67  2001/11/28 21:55:35  richard
#  . login_action and newuser_action return values were being ignored
#  . Woohoo! Found that bloody re-login bug that was killing the mail
#    gateway.
#  (also a minor cleanup in hyperdb)
#
# Revision 1.66  2001/11/27 03:00:50  richard
# couple of bugfixes from latest patch integration
#
# Revision 1.65  2001/11/26 23:00:53  richard
# This config stuff is getting to be a real mess...
#
# Revision 1.64  2001/11/26 22:56:35  richard
# typo
#
# Revision 1.63  2001/11/26 22:55:56  richard
# Feature:
#  . Added INSTANCE_NAME to configuration - used in web and email to identify
#    the instance.
#  . Added EMAIL_SIGNATURE_POSITION to indicate where to place the roundup
#    signature info in e-mails.
#  . Some more flexibility in the mail gateway and more error handling.
#  . Login now takes you to the page you back to the were denied access to.
#
# Fixed:
#  . Lots of bugs, thanks Roché and others on the devel mailing list!
#
# Revision 1.62  2001/11/24 00:45:42  jhermann
# typeof() instead of type(): avoid clash with database field(?) "type"
#
# Fixes this traceback:
#
# Traceback (most recent call last):
#   File "roundup\cgi_client.py", line 535, in newnode
#     self._post_editnode(nid)
#   File "roundup\cgi_client.py", line 415, in _post_editnode
#     if type(value) != type([]): value = [value]
# UnboundLocalError: local variable 'type' referenced before assignment
#
# Revision 1.61  2001/11/22 15:46:42  jhermann
# Added module docstrings to all modules.
#
# Revision 1.60  2001/11/21 22:57:28  jhermann
# Added dummy hooks for I18N and some preliminary (test) markup of
# translatable messages
#
# Revision 1.59  2001/11/21 03:21:13  richard
# oops
#
# Revision 1.58  2001/11/21 03:11:28  richard
# Better handling of new properties.
#
# Revision 1.57  2001/11/15 10:24:27  richard
# handle the case where there is no file attached
#
# Revision 1.56  2001/11/14 21:35:21  richard
#  . users may attach files to issues (and support in ext) through the web now
#
# Revision 1.55  2001/11/07 02:34:06  jhermann
# Handling of damaged login cookies
#
# Revision 1.54  2001/11/07 01:16:12  richard
# Remove the '=' padding from cookie value so quoting isn't an issue.
#
# Revision 1.53  2001/11/06 23:22:05  jhermann
# More IE fixes: it does not like quotes around cookie values; in the
# hope this does not break anything for other browser; if it does, we
# need to check HTTP_USER_AGENT
#
# Revision 1.52  2001/11/06 23:11:22  jhermann
# Fixed debug output in page footer; added expiry date to the login cookie
# (expires 1 year in the future) to prevent probs with certain versions
# of IE
#
# Revision 1.51  2001/11/06 22:00:34  jhermann
# Get debug level from ROUNDUP_DEBUG env var
#
# Revision 1.50  2001/11/05 23:45:40  richard
# Fixed newuser_action so it sets the cookie with the unencrypted password.
# Also made it present nicer error messages (not tracebacks).
#
# Revision 1.49  2001/11/04 03:07:12  richard
# Fixed various cookie-related bugs:
#  . bug #477685 ] base64.decodestring breaks
#  . bug #477837 ] lynx does not like the cookie
#  . bug #477892 ] Password edit doesn't fix login cookie
# Also closed a security hole - a logged-in user could edit another user's
# details.
#
# Revision 1.48  2001/11/03 01:30:18  richard
# Oops. uses pagefoot now.
#
# Revision 1.47  2001/11/03 01:29:28  richard
# Login page didn't have all close tags.
#
# Revision 1.46  2001/11/03 01:26:55  richard
# possibly fix truncated base64'ed user:pass
#
# Revision 1.45  2001/11/01 22:04:37  richard
# Started work on supporting a pop3-fetching server
# Fixed bugs:
#  . bug #477104 ] HTML tag error in roundup-server
#  . bug #477107 ] HTTP header problem
#
# Revision 1.44  2001/10/28 23:03:08  richard
# Added more useful header to the classic schema.
#
# Revision 1.43  2001/10/24 00:01:42  richard
# More fixes to lockout logic.
#
# Revision 1.42  2001/10/23 23:56:03  richard
# HTML typo
#
# Revision 1.41  2001/10/23 23:52:35  richard
# Fixed lock-out logic, thanks Roch'e for pointing out the problems.
#
# Revision 1.40  2001/10/23 23:06:39  richard
# Some cleanup.
#
# Revision 1.39  2001/10/23 01:00:18  richard
# Re-enabled login and registration access after lopping them off via
# disabling access for anonymous users.
# Major re-org of the htmltemplate code, cleaning it up significantly. Fixed
# a couple of bugs while I was there. Probably introduced a couple, but
# things seem to work OK at the moment.
#
# Revision 1.38  2001/10/22 03:25:01  richard
# Added configuration for:
#  . anonymous user access and registration (deny/allow)
#  . filter "widget" location on index page (top, bottom, both)
# Updated some documentation.
#
# Revision 1.37  2001/10/21 07:26:35  richard
# feature #473127: Filenames. I modified the file.index and htmltemplate
#  source so that the filename is used in the link and the creation
#  information is displayed.
#
# Revision 1.36  2001/10/21 04:44:50  richard
# bug #473124: UI inconsistency with Link fields.
#    This also prompted me to fix a fairly long-standing usability issue -
#    that of being able to turn off certain filters.
#
# Revision 1.35  2001/10/21 00:17:54  richard
# CGI interface view customisation section may now be hidden (patch from
#  Roch'e Compaan.)
#
# Revision 1.34  2001/10/20 11:58:48  richard
# Catch errors in login - no username or password supplied.
# Fixed editing of password (Password property type) thanks Roch'e Compaan.
#
# Revision 1.33  2001/10/17 00:18:41  richard
# Manually constructing cookie headers now.
#
# Revision 1.32  2001/10/16 03:36:21  richard
# CGI interface wasn't handling checkboxes at all.
#
# Revision 1.31  2001/10/14 10:55:00  richard
# Handle empty strings in HTML template Link function
#
# Revision 1.30  2001/10/09 07:38:58  richard
# Pushed the base code for the extended schema CGI interface back into the
# code cgi_client module so that future updates will be less painful.
# Also removed a debugging print statement from cgi_client.
#
# Revision 1.29  2001/10/09 07:25:59  richard
# Added the Password property type. See "pydoc roundup.password" for
# implementation details. Have updated some of the documentation too.
#
# Revision 1.28  2001/10/08 00:34:31  richard
# Change message was stuffing up for multilinks with no key property.
#
# Revision 1.27  2001/10/05 02:23:24  richard
#  . roundup-admin create now prompts for property info if none is supplied
#    on the command-line.
#  . hyperdb Class getprops() method may now return only the mutable
#    properties.
#  . Login now uses cookies, which makes it a whole lot more flexible. We can
#    now support anonymous user access (read-only, unless there's an
#    "anonymous" user, in which case write access is permitted). Login
#    handling has been moved into cgi_client.Client.main()
#  . The "extended" schema is now the default in roundup init.
#  . The schemas have had their page headings modified to cope with the new
#    login handling. Existing installations should copy the interfaces.py
#    file from the roundup lib directory to their instance home.
#  . Incorrectly had a Bizar Software copyright on the cgitb.py module from
#    Ping - has been removed.
#  . Fixed a whole bunch of places in the CGI interface where we should have
#    been returning Not Found instead of throwing an exception.
#  . Fixed a deviation from the spec: trying to modify the 'id' property of
#    an item now throws an exception.
#
# Revision 1.26  2001/09/12 08:31:42  richard
# handle cases where mime type is not guessable
#
# Revision 1.25  2001/08/29 05:30:49  richard
# change messages weren't being saved when there was no-one on the nosy list.
#
# Revision 1.24  2001/08/29 04:49:39  richard
# didn't clean up fully after debugging :(
#
# Revision 1.23  2001/08/29 04:47:18  richard
# Fixed CGI client change messages so they actually include the properties
# changed (again).
#
# Revision 1.22  2001/08/17 00:08:10  richard
# reverted back to sending messages always regardless of who is doing the web
# edit. change notes weren't being saved. bleah. hackish.
#
# Revision 1.21  2001/08/15 23:43:18  richard
# Fixed some isFooTypes that I missed.
# Refactored some code in the CGI code.
#
# Revision 1.20  2001/08/12 06:32:36  richard
# using isinstance(blah, Foo) now instead of isFooType
#
# Revision 1.19  2001/08/07 00:24:42  richard
# stupid typo
#
# Revision 1.18  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.17  2001/08/02 06:38:17  richard
# Roundupdb now appends "mailing list" information to its messages which
# include the e-mail address and web interface address. Templates may
# override this in their db classes to include specific information (support
# instructions, etc).
#
# Revision 1.16  2001/08/02 05:55:25  richard
# Web edit messages aren't sent to the person who did the edit any more. No
# message is generated if they are the only person on the nosy list.
#
# Revision 1.15  2001/08/02 00:34:10  richard
# bleah syntax error
#
# Revision 1.14  2001/08/02 00:26:16  richard
# Changed the order of the information in the message generated by web edits.
#
# Revision 1.13  2001/07/30 08:12:17  richard
# Added time logging and file uploading to the templates.
#
# Revision 1.12  2001/07/30 06:26:31  richard
# Added some documentation on how the newblah works.
#
# Revision 1.11  2001/07/30 06:17:45  richard
# Features:
#  . Added ability for cgi newblah forms to indicate that the new node
#    should be linked somewhere.
# Fixed:
#  . Fixed the agument handling for the roundup-admin find command.
#  . Fixed handling of summary when no note supplied for newblah. Again.
#  . Fixed detection of no form in htmltemplate Field display.
#
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
