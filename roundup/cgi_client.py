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
# $Id: cgi_client.py,v 1.90 2002-01-08 03:56:55 richard Exp $

__doc__ = """
WWW request handler (also used in the stand-alone server).
"""

import os, cgi, pprint, StringIO, urlparse, re, traceback, mimetypes
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


    Customisation
    -------------
      FILTER_POSITION - one of 'top', 'bottom', 'top and bottom'
      ANONYMOUS_ACCESS - one of 'deny', 'allow'
      ANONYMOUS_REGISTER - one of 'deny', 'allow'

    from the roundup class:
      INSTANCE_NAME - defaults to 'Roundup issue tracker'

    '''
    FILTER_POSITION = 'bottom'       # one of 'top', 'bottom', 'top and bottom'
    ANONYMOUS_ACCESS = 'deny'        # one of 'deny', 'allow'
    ANONYMOUS_REGISTER = 'deny'      # one of 'deny', 'allow'

    def __init__(self, instance, request, env, form=None):
        self.instance = instance
        self.request = request
        self.env = env
        self.path = env['PATH_INFO']
        self.split_path = self.path.split('/')

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
        return self.db.user.lookup(self.user)

    def header(self, headers={'Content-Type':'text/html'}):
        '''Put up the appropriate header.
        '''
        if not headers.has_key('Content-Type'):
            headers['Content-Type'] = 'text/html'
        self.request.send_response(200)
        for entry in headers.items():
            self.request.send_header(*entry)
        self.request.end_headers()
        self.headers_done = 1
        if self.debug:
            self.headers_sent = headers

    def pagehead(self, title, message=None):
        url = self.env['SCRIPT_NAME'] + '/'
        machine = self.env['SERVER_NAME']
        port = self.env['SERVER_PORT']
        if port != '80': machine = machine + ':' + port
        base = urlparse.urlunparse(('http', machine, url, None, None, None))
        if message is not None:
            message = _('<div class="system-msg">%(message)s</div>')%locals()
        else:
            message = ''
        style = open(os.path.join(self.TEMPLATES, 'style.css')).read()
        user_name = self.user or ''
        if self.user == 'admin':
            admin_links = _(' | <a href="list_classes">Class List</a>' \
                          ' | <a href="user">User List</a>' \
                          ' | <a href="newuser">Add User</a>')
        else:
            admin_links = ''
        if self.user not in (None, 'anonymous'):
            userid = self.db.user.lookup(self.user)
            user_info = _('''
<a href="issue?assignedto=%(userid)s&status=-1,unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:filter=status,assignedto&:sort=-activity&:columns=id,activity,status,title,assignedto&:group=priority&show_customization=1">My Issues</a> |
<a href="user%(userid)s">My Details</a> | <a href="logout">Logout</a>
''')%locals()
        else:
            user_info = _('<a href="login">Login</a>')
        if self.user is not None:
            add_links = _('''
| Add
<a href="newissue">Issue</a>
''')
        else:
            add_links = ''
        self.write(_('''<html><head>
<title>%(title)s</title>
<style type="text/css">%(style)s</style>
</head>
<body bgcolor=#ffffff>
%(message)s
<table width=100%% border=0 cellspacing=0 cellpadding=2>
<tr class="location-bar"><td><big><strong>%(title)s</strong></big></td>
<td align=right valign=bottom>%(user_name)s</td></tr>
<tr class="location-bar">
<td align=left>All
<a href="issue?status=-1,unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=-activity&:filter=status&:columns=id,activity,status,title,assignedto&:group=priority&show_customization=1">Issues</a>
| Unassigned
<a href="issue?assignedto=-1&status=-1,unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=-activity&:filter=status,assignedto&:columns=id,activity,status,title,assignedto&:group=priority&show_customization=1">Issues</a>
%(add_links)s
%(admin_links)s</td>
<td align=right>%(user_info)s</td>
</table>
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

    def index_filterspec(self, filter):
        ''' pull the index filter spec from the form

        Links and multilinks want to be lists - the rest are straight
        strings.
        '''
        props = self.db.classes[self.classname].getprops()
        # all the form args not starting with ':' are filters
        filterspec = {}
        for key in self.form.keys():
            if key[0] == ':': continue
            if not props.has_key(key): continue
            if key not in filter: continue
            prop = props[key]
            value = self.form[key]
            if (isinstance(prop, hyperdb.Link) or
                    isinstance(prop, hyperdb.Multilink)):
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

    default_index_sort = ['-activity']
    default_index_group = ['priority']
    default_index_filter = ['status']
    default_index_columns = ['id','activity','title','status','assignedto']
    default_index_filterspec = {'status': ['1', '2', '3', '4', '5', '6', '7']}
    def index(self):
        ''' put up an index
        '''
        self.classname = 'issue'
        # see if the web has supplied us with any customisation info
        defaults = 1
        for key in ':sort', ':group', ':filter', ':columns':
            if self.form.has_key(key):
                defaults = 0
                break
        if defaults:
            # no info supplied - use the defaults
            sort = self.default_index_sort
            group = self.default_index_group
            filter = self.default_index_filter
            columns = self.default_index_columns
            filterspec = self.default_index_filterspec
        else:
            sort = self.index_arg(':sort')
            group = self.index_arg(':group')
            filter = self.index_arg(':filter')
            columns = self.index_arg(':columns')
            filterspec = self.index_filterspec(filter)
        return self.list(columns=columns, filter=filter, group=group,
            sort=sort, filterspec=filterspec)

    # XXX deviates from spec - loses the '+' (that's a reserved character
    # in URLS
    def list(self, sort=None, group=None, filter=None, columns=None,
            filterspec=None, show_customization=None):
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
            'classname': cn, 'instancename': self.INSTANCE_NAME})
        if sort is None: sort = self.index_arg(':sort')
        if group is None: group = self.index_arg(':group')
        if filter is None: filter = self.index_arg(':filter')
        if columns is None: columns = self.index_arg(':columns')
        if filterspec is None: filterspec = self.index_filterspec(filter)
        if show_customization is None:
            show_customization = self.customization_widget()

        index = htmltemplate.IndexTemplate(self, self.TEMPLATES, cn)
        index.render(filterspec, filter, columns, sort, group,
            show_customization=show_customization)
        self.pagefoot()

    def shownode(self, message=None):
        ''' display an item
        '''
        cn = self.classname
        cl = self.db.classes[cn]

        # possibly perform an edit
        keys = self.form.keys()
        num_re = re.compile('^\d+$')
        # don't try to set properties if the user has just logged in
        if keys and not self.form.has_key('__login_name'):
            try:
                props, changed = parsePropsFromForm(self.db, cl, self.form,
                    self.nodeid)
                # make changes to the node
                self._changenode(props)
                # handle linked nodes 
                self._post_editnode(self.nodeid)
                # and some nice feedback for the user
                if changed:
                    message = _('%(changes)s edited ok')%{'changes':
                        ', '.join(changed.keys())}
                elif self.form.has_key('__note') and self.form['__note'].value:
                    message = _('note added')
                elif self.form.has_key('__file'):
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
        self.pagehead('%s: %s'%(self.classname.capitalize(), id), message)

        nodeid = self.nodeid

        # use the template to display the item
        item = htmltemplate.ItemTemplate(self, self.TEMPLATES, self.classname)
        item.render(nodeid)

        self.pagefoot()
    showissue = shownode
    showmsg = shownode

    def _add_assignedto_to_nosy(self, props):
        ''' add the assignedto value from the props to the nosy list
        '''
        if not props.has_key('assignedto'):
            return
        assignedto_id = props['assignedto']
        if props.has_key('nosy') and assignedto_id not in props['nosy']:
            props['nosy'].append(assignedto_id)
        else:
            props['nosy'] = cl.get(self.nodeid, 'nosy')
            props['nosy'].append(assignedto_id)

    def _changenode(self, props):
        ''' change the node based on the contents of the form
        '''
        cl = self.db.classes[self.classname]
        # set status to chatting if 'unread' or 'resolved'
        try:
            # determine the id of 'unread','resolved' and 'chatting'
            unread_id = self.db.status.lookup('unread')
            resolved_id = self.db.status.lookup('resolved')
            chatting_id = self.db.status.lookup('chatting')
            current_status = cl.get(self.nodeid, 'status')
            if props.has_key('status'):
                new_status = props['status']
            else:
                # apparently there's a chance that some browsers don't
                # send status...
                new_status = current_status
        except KeyError:
            pass
        else:
            if new_status == unread_id or (new_status == resolved_id
                    and current_status == resolved_id):
                props['status'] = chatting_id

        self._add_assignedto_to_nosy(props)

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
        props, dummy = parsePropsFromForm(self.db, cl, self.form)

        # set status to 'unread' if not specified - a status of '- no
        # selection -' doesn't make sense
        if not props.has_key('status'):
            try:
                unread_id = self.db.status.lookup('unread')
            except KeyError:
                pass
            else:
                props['status'] = unread_id

        self._add_assignedto_to_nosy(props)

        # check for messages and files
        message, files = self._handle_message()
        if message:
            props['messages'] = [message]
        if files:
            props['files'] = files
        # create the node and return it's id
        return cl.create(**props)

    def _handle_message(self):
        ''' generate and edit message
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
            note = self.form['__note'].value
        if not props.has_key('messages'):
            return None, files
        if not isinstance(props['messages'], hyperdb.Multilink):
            return None, files
        if not props['messages'].classname == 'msg':
            return None, files
        if not (self.form.has_key('nosy') or note):
            return None, files

        # handle the note
        if note:
            if '\n' in note:
                summary = re.split(r'\n\r?', note)[0]
            else:
                summary = note
            m = ['%s\n'%note]
        elif not files:
            # don't generate a useless message
            return None, files

        # handle the messageid
        # TODO: handle inreplyto
        messageid = "%s.%s.%s-%s"%(time.time(), random.random(),
            self.classname, self.MAIL_DOMAIN)

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
                    value = link.get(nodeid, property)
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
                item = htmltemplate.ItemTemplate(self, self.TEMPLATES, 
                    self.classname)
                item.render(nid)
                self.pagefoot()
                return
            except:
                self.db.rollback()
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                message = '<pre>%s</pre>'%cgi.escape(s.getvalue())
        self.pagehead(_('New %(classname)s')%{'classname':
            self.classname.capitalize()}, message)

        # call the template
        newitem = htmltemplate.NewItemTemplate(self, self.TEMPLATES,
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
                props, dummy = parsePropsFromForm(self.db, cl, self.form)
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
        newitem = htmltemplate.NewItemTemplate(self, self.TEMPLATES,
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

        # possibly perform a create
        keys = self.form.keys()
        if [i for i in keys if i[0] != ':']:
            try:
                file = self.form['content']
                mime_type = mimetypes.guess_type(file.filename)[0]
                if not mime_type:
                    mime_type = "application/octet-stream"
                # save the file
                nid = cl.create(content=file.file.read(), type=mime_type,
                    name=file.filename)
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
        newitem = htmltemplate.NewItemTemplate(self, self.TEMPLATES,
            self.classname)
        newitem.render(self.form)
        self.pagefoot()

    def showuser(self, message=None):
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
        num_re = re.compile('^\d+$')
        if keys:
            try:
                props, changed = parsePropsFromForm(self.db, user, self.form,
                    self.nodeid)
                set_cookie = 0
                if self.nodeid == self.getuid() and changed.has_key('password'):
                    password = self.form['password'].value.strip()
                    if password:
                        set_cookie = password
                    else:
                        # no password was supplied - don't change it
                        del props['password']
                        del changed['password']
                user.set(self.nodeid, **props)
                # and some feedback for the user
                message = _('%(changes)s edited ok')%{'changes':
                    ', '.join(changed.keys())}
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
        item = htmltemplate.ItemTemplate(self, self.TEMPLATES, 'user')
        item.render(self.nodeid)
        self.pagefoot()

    def showfile(self):
        ''' display a file
        '''
        nodeid = self.nodeid
        cl = self.db.file
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

    def login(self, message=None, newuser_form=None, action='index'):
        '''Display a login page.
        '''
        self.pagehead(_('Login to roundup'), message)
        self.write(_('''
<table>
<tr><td colspan=2 class="strong-header">Existing User Login</td></tr>
<form action="login_action" method=POST>
<input type="hidden" name="__destination_url" value="%(action)s">
<tr><td align=right>Login name: </td>
    <td><input name="__login_name"></td></tr>
<tr><td align=right>Password: </td>
    <td><input type="password" name="__login_password"></td></tr>
<tr><td></td>
    <td><input type="submit" value="Log In"></td></tr>
</form>
''')%locals())
        if self.user is None and self.ANONYMOUS_REGISTER == 'deny':
            self.write('</table>')
            self.pagefoot()
            return
        values = {'realname': '', 'organisation': '', 'address': '',
            'phone': '', 'username': '', 'password': '', 'confirm': '',
            'action': action}
        if newuser_form is not None:
            for key in newuser_form.keys():
                values[key] = newuser_form[key].value
        self.write(_('''
<p>
<tr><td colspan=2 class="strong-header">New User Registration</td></tr>
<tr><td colspan=2><em>marked items</em> are optional...</td></tr>
<form action="newuser_action" method=POST>
<input type="hidden" name="__destination_url" value="%(action)s">
<tr><td align=right><em>Name: </em></td>
    <td><input name="realname" value="%(realname)s"></td></tr>
<tr><td align=right><em>Organisation: </em></td>
    <td><input name="organisation" value="%(organisation)s"></td></tr>
<tr><td align=right>E-Mail Address: </td>
    <td><input name="address" value="%(address)s"></td></tr>
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
            props, dummy = parsePropsFromForm(self.db, cl, self.form)
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
            if self.ANONYMOUS_REGISTER == 'deny' and self.user is None:
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
        elif self.ANONYMOUS_ACCESS == 'deny' and self.user is None:
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
            nre=re.compile(r'new(\w+)')):
        '''Figure the user's action and do it.
        '''
        # here be the "normal" functionality
        if action == 'index':
            self.index()
            return
        if action == 'list_classes':
            self.classes()
            return
        if action == 'login':
            self.login()
            return
        if action == 'logout':
            self.logout()
            return
        m = dre.match(action)
        if m:
            self.classname = m.group(1)
            self.nodeid = m.group(2)
            try:
                cl = self.db.classes[self.classname]
            except KeyError:
                raise NotFound
            try:
                cl.get(self.nodeid, 'id')
            except IndexError:
                raise NotFound
            try:
                func = getattr(self, 'show%s'%self.classname)
            except AttributeError:
                raise NotFound
            func()
            return
        m = nre.match(action)
        if m:
            self.classname = m.group(1)
            try:
                func = getattr(self, 'new%s'%self.classname)
            except AttributeError:
                raise NotFound
            func()
            return
        self.classname = action
        try:
            self.db.getclass(self.classname)
        except KeyError:
            raise NotFound
        self.list()


class ExtendedClient(Client): 
    '''Includes pages and page heading information that relate to the
       extended schema.
    ''' 
    showsupport = Client.shownode
    showtimelog = Client.shownode
    newsupport = Client.newnode
    newtimelog = Client.newnode

    default_index_sort = ['-activity']
    default_index_group = ['priority']
    default_index_filter = ['status']
    default_index_columns = ['activity','status','title','assignedto']
    default_index_filterspec = {'status': ['1', '2', '3', '4', '5', '6', '7']}

    def pagehead(self, title, message=None):
        url = self.env['SCRIPT_NAME'] + '/' #self.env.get('PATH_INFO', '/')
        machine = self.env['SERVER_NAME']
        port = self.env['SERVER_PORT']
        if port != '80': machine = machine + ':' + port
        base = urlparse.urlunparse(('http', machine, url, None, None, None))
        if message is not None:
            message = _('<div class="system-msg">%(message)s</div>')%locals()
        else:
            message = ''
        style = open(os.path.join(self.TEMPLATES, 'style.css')).read()
        user_name = self.user or ''
        if self.user == 'admin':
            admin_links = _(' | <a href="list_classes">Class List</a>' \
                          ' | <a href="user">User List</a>' \
                          ' | <a href="newuser">Add User</a>')
        else:
            admin_links = ''
        if self.user not in (None, 'anonymous'):
            userid = self.db.user.lookup(self.user)
            user_info = _('''
<a href="issue?assignedto=%(userid)s&status=-1,unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:filter=status,assignedto&:sort=-activity&:columns=id,activity,status,title,assignedto&:group=priority&show_customization=1">My Issues</a> |
<a href="support?assignedto=%(userid)s&status=-1,unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:filter=status,assignedto&:sort=-activity&:columns=id,activity,status,title,assignedto&:group=customername&show_customization=1">My Support</a> |
<a href="user%(userid)s">My Details</a> | <a href="logout">Logout</a>
''')%locals()
        else:
            user_info = _('<a href="login">Login</a>')
        if self.user is not None:
            add_links = _('''
| Add
<a href="newissue">Issue</a>,
<a href="newsupport">Support</a>,
''')
        else:
            add_links = ''
        self.write(_('''<html><head>
<title>%(title)s</title>
<style type="text/css">%(style)s</style>
</head>
<body bgcolor=#ffffff>
%(message)s
<table width=100%% border=0 cellspacing=0 cellpadding=2>
<tr class="location-bar"><td><big><strong>%(title)s</strong></big></td>
<td align=right valign=bottom>%(user_name)s</td></tr>
<tr class="location-bar">
<td align=left>All
<a href="issue?status=-1,unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=activity&:filter=status&:columns=id,activity,status,title,assignedto&:group=priority&show_customization=1">Issues</a>,
<a href="support?status=-1,unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=activity&:filter=status&:columns=id,activity,status,title,assignedto&:group=customername&show_customization=1">Support</a>
| Unassigned
<a href="issue?assignedto=-1&status=-1,unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=-activity&:filter=status,assignedto&:columns=id,activity,status,title,assignedto&:group=priority&show_customization=1">Issues</a>,
<a href="support?assignedto=-1&status=-1,unread,deferred,chatting,need-eg,in-progress,testing,done-cbb&:sort=-activity&:filter=status,assignedto&:columns=id,activity,status,title,assignedto&:group=customername&show_customization=1">Support</a>
%(add_links)s
%(admin_links)s</td>
<td align=right>%(user_info)s</td>
</table>
''')%locals())

def parsePropsFromForm(db, cl, form, nodeid=0):
    '''Pull properties for the given class out of the form.
    '''
    props = {}
    changed = {}
    keys = form.keys()
    num_re = re.compile('^\d+$')
    for key in keys:
        if not cl.properties.has_key(key):
            continue
        proptype = cl.properties[key]
        if isinstance(proptype, hyperdb.String):
            value = form[key].value.strip()
        elif isinstance(proptype, hyperdb.Password):
            value = password.Password(form[key].value.strip())
        elif isinstance(proptype, hyperdb.Date):
            value = date.Date(form[key].value.strip())
        elif isinstance(proptype, hyperdb.Interval):
            value = date.Interval(form[key].value.strip())
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
        props[key] = value

        # get the old value
        if nodeid:
            try:
                existing = cl.get(nodeid, key)
            except KeyError:
                # this might be a new property for which there is no existing
                # value
                if not cl.properties.has_key(key): raise

        # if changed, set it
        if nodeid and value != existing:
            changed[key] = value
            props[key] = value
    return props, changed

#
# $Log: not supported by cvs2svn $
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
