# $Id: htmltemplate.py,v 1.5 2001-07-28 08:17:09 richard Exp $

import os, re, StringIO, urllib, cgi, errno

import hyperdb, date

class Base:
    def __init__(self, db, templates, classname, nodeid=None, form=None):
        # TODO: really not happy with the way templates is passed on here
        self.db, self.templates = db, templates
        self.classname, self.nodeid = classname, nodeid
        self.form = form
        self.cl = self.db.classes[self.classname]
        self.properties = self.cl.getprops()

class Plain(Base):
    ''' display a String property directly;

        display a Date property in a specified time zone with an option to
        omit the time from the date stamp;

        for a Link or Multilink property, display the key strings of the
        linked nodes (or the ids if the linked class has no key property)
    '''
    def __call__(self, property):
        if not self.nodeid and self.form is None:
            return '[Field: not called from item]'
        propclass = self.properties[property]
        if self.nodeid:
            value = self.cl.get(self.nodeid, property)
        else:
            # TODO: pull the value from the form
            if propclass.isMultilinkType: value = []
            else: value = ''
        if propclass.isStringType:
            if value is None: value = ''
            else: value = str(value)
        elif propclass.isDateType:
            value = str(value)
        elif propclass.isIntervalType:
            value = str(value)
        elif propclass.isLinkType:
            linkcl = self.db.classes[propclass.classname]
            k = linkcl.getkey()
            # if the linked-to class doesn't have a key property, then try
            # 'name', then 'title' and then just use a random one.
            if not k:
                linkprops = linkcl.getprops()
                if linkprops.has_key('name'):
                    k = 'name'
                elif linkprops.has_key('title'):
                    k = 'title'
                else: 
                    k = linkprops.keys()[0]
            if value: value = str(linkcl.get(value, k))
            else: value = '[unselected]'
        elif propclass.isMultilinkType:
            linkcl = self.db.classes[propclass.classname]
            k = linkcl.getkey()
            # if the linked-to class doesn't have a key property, then try
            # 'name', then 'title' and then just use a random one.
            if not k:
                linkprops = linkcl.getprops()
                if linkprops.has_key('name'):
                    k = 'name'
                elif linkprops.has_key('title'):
                    k = 'title'
                else: 
                    k = linkprops.keys()[0]
            value = ', '.join([linkcl.get(i, k) for i in value])
        else:
            s = 'Plain: bad propclass "%s"'%propclass
        return value

class Field(Base):
    ''' display a property like the plain displayer, but in a text field
        to be edited
    '''
    def __call__(self, property, size=None, height=None, showid=0):
        if not self.nodeid and self.form is None:
            return '[Field: not called from item]'
        propclass = self.properties[property]
        if self.nodeid:
            value = self.cl.get(self.nodeid, property)
        else:
            # TODO: pull the value from the form
            if propclass.isMultilinkType: value = []
            else: value = ''
        if (propclass.isStringType or propclass.isDateType or
                propclass.isIntervalType):
            size = size or 30
            if value is None:
                value = ''
            else:
                value = cgi.escape(value)
                value = '&quot;'.join(value.split('"'))
            s = '<input name="%s" value="%s" size="%s">'%(property, value, size)
        elif propclass.isLinkType:
            linkcl = self.db.classes[propclass.classname]
            l = ['<select name="%s">'%property]
            k = linkcl.getkey()
            # if the linked-to class doesn't have a key property, then try
            # 'name', then 'title' and then just use a random one.
            if not k:
                linkprops = linkcl.getprops()
                if linkprops.has_key('name'):
                    k = 'name'
                elif linkprops.has_key('title'):
                    k = 'title'
                else: 
                    k = linkprops.keys()[0]
            for optionid in linkcl.list():
                option = linkcl.get(optionid, k)
                s = ''
                if optionid == value:
                    s = 'selected '
                if showid:
                    lab = '%s%s: %s'%(propclass.classname, optionid, option)
                else:
                    lab = option
                if size is not None and len(lab) > size:
                    lab = lab[:size-3] + '...'
                l.append('<option %svalue="%s">%s</option>'%(s, optionid, lab))
            l.append('</select>')
            s = '\n'.join(l)
        elif propclass.isMultilinkType:
            linkcl = self.db.classes[propclass.classname]
            list = linkcl.list()
            height = height or min(len(list), 7)
            l = ['<select multiple name="%s" size="%s">'%(property, height)]
            k = linkcl.getkey()
            # if the linked-to class doesn't have a key property, then try
            # 'name', then 'title' and then just use a random one.
            if not k:
                linkprops = linkcl.getprops()
                if linkprops.has_key('name'):
                    k = 'name'
                elif linkprops.has_key('title'):
                    k = 'title'
                else: 
                    k = linkprops.keys()[0]
            for optionid in list:
                option = linkcl.get(optionid, k)
                s = ''
                if optionid in value:
                    s = 'selected '
                if showid:
                    lab = '%s%s: %s'%(propclass.classname, optionid, option)
                else:
                    lab = option
                if size is not None and len(lab) > size:
                    lab = lab[:size-3] + '...'
                l.append('<option %svalue="%s">%s</option>'%(s, optionid, lab))
            l.append('</select>')
            s = '\n'.join(l)
        else:
            s = 'Plain: bad propclass "%s"'%propclass
        return s

class Menu(Base):
    ''' for a Link property, display a menu of the available choices
    '''
    def __call__(self, property, size=None, height=None, showid=0):
        propclass = self.properties[property]
        if self.nodeid:
            value = self.cl.get(self.nodeid, property)
        else:
            # TODO: pull the value from the form
            if propclass.isMultilinkType: value = []
            else: value = None
        if propclass.isLinkType:
            linkcl = self.db.classes[propclass.classname]
            l = ['<select name="%s">'%property]
            k = linkcl.getkey()
            # if the linked-to class doesn't have a key property, then try
            # 'name', then 'title' and then just use a random one.
            if not k:
                linkprops = linkcl.getprops()
                if linkprops.has_key('name'):
                    k = 'name'
                elif linkprops.has_key('title'):
                    k = 'title'
                else: 
                    k = linkprops.keys()[0]
            for optionid in linkcl.list():
                option = linkcl.get(optionid, k)
                s = ''
                if optionid == value:
                    s = 'selected '
                l.append('<option %svalue="%s">%s</option>'%(s, optionid, option))
            l.append('</select>')
            return '\n'.join(l)
        if propclass.isMultilinkType:
            linkcl = self.db.classes[propclass.classname]
            list = linkcl.list()
            height = height or min(len(list), 7)
            l = ['<select multiple name="%s" size="%s">'%(property, height)]
            k = linkcl.getkey()
            # if the linked-to class doesn't have a key property, then try
            # 'name', then 'title' and then just use a random one.
            if not k:
                linkprops = linkcl.getprops()
                if linkprops.has_key('name'):
                    k = 'name'
                elif linkprops.has_key('title'):
                    k = 'title'
                else: 
                    k = linkprops.keys()[0]
            for optionid in list:
                option = linkcl.get(optionid, k)
                s = ''
                if optionid in value:
                    s = 'selected '
                if showid:
                    lab = '%s%s: %s'%(propclass.classname, optionid, option)
                else:
                    lab = option
                if size is not None and len(lab) > size:
                    lab = lab[:size-3] + '...'
                l.append('<option %svalue="%s">%s</option>'%(s, optionid, option))
            l.append('</select>')
            return '\n'.join(l)
        return '[Menu: not a link]'

#XXX deviates from spec
class Link(Base):
    ''' for a Link or Multilink property, display the names of the linked
        nodes, hyperlinked to the item views on those nodes
        for other properties, link to this node with the property as the text
    '''
    def __call__(self, property=None, **args):
        if not self.nodeid and self.form is None:
            return '[Link: not called from item]'
        propclass = self.properties[property]
        if self.nodeid:
            value = self.cl.get(self.nodeid, property)
        else:
            if propclass.isMultilinkType: value = []
            else: value = ''
        if propclass.isLinkType:
            linkcl = self.db.classes[propclass.classname]
            k = linkcl.getkey()
            # if the linked-to class doesn't have a key property, then try
            # 'name', then 'title' and then just use a random one.
            if not k:
                linkprops = linkcl.getprops()
                if linkprops.has_key('name'):
                    k = 'name'
                elif linkprops.has_key('title'):
                    k = 'title'
                else: 
                    k = linkprops.keys()[0]
            linkvalue = linkcl.get(value, k)
            return '<a href="%s%s">%s</a>'%(linkcl, value, linkvalue)
        if propclass.isMultilinkType:
            linkcl = self.db.classes[propclass.classname]
            k = linkcl.getkey()
            # if the linked-to class doesn't have a key property, then try
            # 'name', then 'title' and then just use a random one.
            if not k:
                linkprops = linkcl.getprops()
                if linkprops.has_key('name'):
                    k = 'name'
                elif linkprops.has_key('title'):
                    k = 'title'
                else: 
                    k = linkprops.keys()[0]
            l = []
            for value in value:
                linkvalue = linkcl.get(value, k)
                l.append('<a href="%s%s">%s</a>'%(linkcl, value, linkvalue))
            return ', '.join(l)
        return '<a href="%s%s">%s</a>'%(self.classname, self.nodeid, value)

class Count(Base):
    ''' for a Multilink property, display a count of the number of links in
        the list
    '''
    def __call__(self, property, **args):
        if not self.nodeid:
            return '[Count: not called from item]'
        propclass = self.properties[property]
        value = self.cl.get(self.nodeid, property)
        if propclass.isMultilinkType:
            return str(len(value))
        return '[Count: not a Multilink]'

# XXX pretty is definitely new ;)
class Reldate(Base):
    ''' display a Date property in terms of an interval relative to the
        current date (e.g. "+ 3w", "- 2d").

        with the 'pretty' flag, make it pretty
    '''
    def __call__(self, property, pretty=0):
        if not self.nodeid and self.form is None:
            return '[Reldate: not called from item]'
        propclass = self.properties[property]
        if not propclass.isDateType:
            return '[Reldate: not a Date]'
        if self.nodeid:
            value = self.cl.get(self.nodeid, property)
        else:
            value = date.Date('.')
        interval = value - date.Date('.')
        if pretty:
            if not self.nodeid:
                return 'now'
            pretty = interval.pretty()
            if pretty is None:
                pretty = value.pretty()
            return pretty
        return str(interval)

class Download(Base):
    ''' show a Link("file") or Multilink("file") property using links that
        allow you to download files
    '''
    def __call__(self, property, **args):
        if not self.nodeid:
            return '[Download: not called from item]'
        propclass = self.properties[property]
        value = self.cl.get(self.nodeid, property)
        if propclass.isLinkType:
            linkcl = self.db.classes[propclass.classname]
            linkvalue = linkcl.get(value, k)
            return '<a href="%s%s">%s</a>'%(linkcl, value, linkvalue)
        if propclass.isMultilinkType:
            linkcl = self.db.classes[propclass.classname]
            l = []
            for value in value:
                linkvalue = linkcl.get(value, k)
                l.append('<a href="%s%s">%s</a>'%(linkcl, value, linkvalue))
            return ', '.join(l)
        return '[Download: not a link]'


class Checklist(Base):
    ''' for a Link or Multilink property, display checkboxes for the available
        choices to permit filtering
    '''
    def __call__(self, property, **args):
        propclass = self.properties[property]
        if self.nodeid:
            value = self.cl.get(self.nodeid, property)
        else:
            value = []
        if propclass.isLinkType or propclass.isMultilinkType:
            linkcl = self.db.classes[propclass.classname]
            l = []
            k = linkcl.getkey()
            # if the linked-to class doesn't have a key property, then try
            # 'name', then 'title' and then just use a random one.
            if not k:
                linkprops = linkcl.getprops()
                if linkprops.has_key('name'):
                    k = 'name'
                elif linkprops.has_key('title'):
                    k = 'title'
                else: 
                    k = linkprops.keys()[0]
            for optionid in linkcl.list():
                option = linkcl.get(optionid, k)
                if optionid in value:
                    checked = 'checked'
                else:
                    checked = ''
                l.append('%s:<input type="checkbox" %s name="%s" value="%s">'%(
                    option, checked, propclass.classname, option))
            return '\n'.join(l)
        return '[Checklist: not a link]'

class Note(Base):
    ''' display a "note" field, which is a text area for entering a note to
        go along with a change. 
    '''
    def __call__(self, rows=5, cols=80):
       # TODO: pull the value from the form
        return '<textarea name="__note" rows=%s cols=%s></textarea>'%(rows,
            cols)

# XXX new function
class List(Base):
    ''' list the items specified by property using the standard index for
        the class
    '''
    def __call__(self, property, **args):
        propclass = self.properties[property]
        if not propclass.isMultilinkType:
            return '[List: not a Multilink]'
        fp = StringIO.StringIO()
        args['show_display_form'] = 0
        value = self.cl.get(self.nodeid, property)
        # TODO: really not happy with the way templates is passed on here
        index(fp, self.templates, self.db, propclass.classname, nodeids=value,
            show_display_form=0)
        return fp.getvalue()

# XXX new function
class History(Base):
    ''' list the history of the item
    '''
    def __call__(self, **args):
        l = ['<table width=100% border=0 cellspacing=0 cellpadding=2>',
            '<tr class="list-header">',
            '<td><span class="list-item"><strong>Date</strong></span></td>',
            '<td><span class="list-item"><strong>User</strong></span></td>',
            '<td><span class="list-item"><strong>Action</strong></span></td>',
            '<td><span class="list-item"><strong>Args</strong></span></td>']

        for id, date, user, action, args in self.cl.history(self.nodeid):
            l.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(
               date, user, action, args))
        l.append('</table>')
        return '\n'.join(l)

# XXX new function
class Submit(Base):
    ''' add a submit button for the item
    '''
    def __call__(self):
        if self.nodeid:
            return '<input type="submit" value="Submit Changes">'
        elif self.form is not None:
            return '<input type="submit" value="Submit New Entry">'
        else:
            return '[Submit: not called from item]'


#
#   INDEX TEMPLATES
#
class IndexTemplateReplace:
    def __init__(self, globals, locals, props):
        self.globals = globals
        self.locals = locals
        self.props = props

    def go(self, text, replace=re.compile(
            r'((<property\s+name="(?P<name>[^>]+)">(?P<text>.+?)</property>)|'
            r'(?P<display><display\s+call="(?P<command>[^"]+)">))', re.I|re.S)):
        return replace.sub(self, text)
        
    def __call__(self, m, filter=None, columns=None, sort=None, group=None):
        if m.group('name'):
            if m.group('name') in self.props:
                text = m.group('text')
                replace = IndexTemplateReplace(self.globals, {}, self.props)
                return replace.go(m.group('text'))
            else:
                return ''
        if m.group('display'):
            command = m.group('command')
            return eval(command, self.globals, self.locals)
        print '*** unhandled match', m.groupdict()

def sortby(sort_name, columns, filter, sort, group, filterspec):
    l = []
    w = l.append
    for k, v in filterspec.items():
        k = urllib.quote(k)
        if type(v) == type([]):
            w('%s=%s'%(k, ','.join(map(urllib.quote, v))))
        else:
            w('%s=%s'%(k, urllib.quote(v)))
    if columns:
        w(':columns=%s'%','.join(map(urllib.quote, columns)))
    if filter:
        w(':filter=%s'%','.join(map(urllib.quote, filter)))
    if group:
        w(':group=%s'%','.join(map(urllib.quote, group)))
    m = []
    s_dir = ''
    for name in sort:
        dir = name[0]
        if dir == '-':
            dir = ''
        else:
            name = name[1:]
        if sort_name == name:
            if dir == '':
                s_dir = '-'
            elif dir == '-':
                s_dir = ''
        else:
            m.append(dir+urllib.quote(name))
    m.insert(0, s_dir+urllib.quote(sort_name))
    # so things don't get completely out of hand, limit the sort to two columns
    w(':sort=%s'%','.join(m[:2]))
    return '&'.join(l)

def index(client, templates, db, classname, filterspec={}, filter=[],
        columns=[], sort=[], group=[], show_display_form=1, nodeids=None,
        col_re=re.compile(r'<property\s+name="([^>]+)">')):
    globals = {
        'plain': Plain(db, templates, classname, form={}),
        'field': Field(db, templates, classname, form={}),
        'menu': Menu(db, templates, classname, form={}),
        'link': Link(db, templates, classname, form={}),
        'count': Count(db, templates, classname, form={}),
        'reldate': Reldate(db, templates, classname, form={}),
        'download': Download(db, templates, classname, form={}),
        'checklist': Checklist(db, templates, classname, form={}),
        'list': List(db, templates, classname, form={}),
        'history': History(db, templates, classname, form={}),
        'submit': Submit(db, templates, classname, form={}),
        'note': Note(db, templates, classname, form={})
    }
    cl = db.classes[classname]
    properties = cl.getprops()
    w = client.write

    try:
        template = open(os.path.join(templates, classname+'.filter')).read()
        all_filters = col_re.findall(template)
    except IOError, error:
        if error.errno != errno.ENOENT: raise
        template = None
        all_filters = []
    if template and filter:
        # display the filter section
        w('<form>')
        w('<table width=100% border=0 cellspacing=0 cellpadding=2>')
        w('<tr class="location-bar">')
        w(' <th align="left" colspan="2">Filter specification...</th>')
        w('</tr>')
        replace = IndexTemplateReplace(globals, locals(), filter)
        w(replace.go(template))
        if columns:
            w('<input type="hidden" name=":columns" value="%s">'%','.join(columns))
        if filter:
            w('<input type="hidden" name=":filter" value="%s">'%','.join(filter))
        if sort:
            w('<input type="hidden" name=":sort" value="%s">'%','.join(sort))
        if group:
            w('<input type="hidden" name=":group" value="%s">'%','.join(group))
        for k, v in filterspec.items():
            if type(v) == type([]): v = ','.join(v)
            w('<input type="hidden" name="%s" value="%s">'%(k, v))
        w('<tr class="location-bar"><td width="1%%">&nbsp;</td>')
        w('<td><input type="submit" value="Redisplay"></td></tr>')
        w('</table>')
        w('</form>')

    # XXX deviate from spec here ...
    # load the index section template and figure the default columns from it
    template = open(os.path.join(templates, classname+'.index')).read()
    all_columns = col_re.findall(template)
    if not columns:
        columns = []
        for name in all_columns:
            columns.append(name)
    else:
        # re-sort columns to be the same order as all_columns
        l = []
        for name in all_columns:
            if name in columns:
                l.append(name)
        columns = l

    # now display the index section
    w('<table width=100% border=0 cellspacing=0 cellpadding=2>')
    w('<tr class="list-header">')
    for name in columns:
        cname = name.capitalize()
        if show_display_form:
            anchor = "%s?%s"%(classname, sortby(name, columns, filter,
                sort, group, filterspec))
            w('<td><span class="list-item"><a href="%s">%s</a></span></td>'%(
                anchor, cname))
        else:
            w('<td><span class="list-item">%s</span></td>'%cname)
    w('</tr>')

    # this stuff is used for group headings - optimise the group names
    old_group = None
    group_names = []
    if group:
        for name in group:
            if name[0] == '-': group_names.append(name[1:])
            else: group_names.append(name)

    # now actually loop through all the nodes we get from the filter and
    # apply the template
    if nodeids is None:
        nodeids = cl.filter(filterspec, sort, group)
    for nodeid in nodeids:
        # check for a group heading
        if group_names:
            this_group = [cl.get(nodeid, name) for name in group_names]
            if this_group != old_group:
                l = []
                for name in group_names:
                    prop = properties[name]
                    if prop.isLinkType:
                        group_cl = db.classes[prop.classname]
                        key = group_cl.getkey()
                        value = cl.get(nodeid, name)
                        if value is None:
                            l.append('[unselected %s]'%prop.classname)
                        else:
                            l.append(group_cl.get(cl.get(nodeid, name), key))
                    elif prop.isMultilinkType:
                        group_cl = db.classes[prop.classname]
                        key = group_cl.getkey()
                        for value in cl.get(nodeid, name):
                            l.append(group_cl.get(value, key))
                    else:
                        value = cl.get(nodeid, name)
                        if value is None:
                            value = '[empty %s]'%name
                        l.append(value)
                w('<tr class="section-bar">'
                  '<td align=middle colspan=%s><strong>%s</strong></td></tr>'%(
                    len(columns), ', '.join(l)))
                old_group = this_group

        # display this node's row
        for value in globals.values():
            if hasattr(value, 'nodeid'):
                value.nodeid = nodeid
        replace = IndexTemplateReplace(globals, locals(), columns)
        w(replace.go(template))

    w('</table>')

    if not show_display_form:
        return

    # now add in the filter/columns/group/etc config table form
    w('<p><form>')
    w('<table width=100% border=0 cellspacing=0 cellpadding=2>')
    for k,v in filterspec.items():
        if type(v) == type([]): v = ','.join(v)
        w('<input type="hidden" name="%s" value="%s">'%(k, v))
    if sort:
        w('<input type="hidden" name=":sort" value="%s">'%','.join(sort))
    names = []
    for name in cl.getprops().keys():
        if name in all_filters or name in all_columns:
            names.append(name)
    w('<tr class="location-bar">')
    w('<th align="left" colspan=%s>View customisation...</th></tr>'%
        (len(names)+1))
    w('<tr class="location-bar"><th>&nbsp;</th>')
    for name in names:
        w('<th>%s</th>'%name.capitalize())
    w('</tr>')

    # filter
    if all_filters:
        w('<tr><th width="1%" align=right class="location-bar">Filters</th>')
        for name in names:
            if name not in all_filters:
                w('<td>&nbsp;</td>')
                continue
            if name in filter: checked=' checked'
            else: checked=''
            w('<td align=middle>')
            w('<input type="checkbox" name=":filter" value="%s" %s></td>'%(name,
                checked))
        w('</tr>')

    # columns
    if all_columns:
        w('<tr><th width="1%" align=right class="location-bar">Columns</th>')
        for name in names:
            if name not in all_columns:
                w('<td>&nbsp;</td>')
                continue
            if name in columns: checked=' checked'
            else: checked=''
            w('<td align=middle>')
            w('<input type="checkbox" name=":columns" value="%s" %s></td>'%(
                name, checked))
        w('</tr>')

        # group
        w('<tr><th width="1%" align=right class="location-bar">Grouping</th>')
        for name in names:
            prop = properties[name]
            if name not in all_columns:
                w('<td>&nbsp;</td>')
                continue
            if name in group: checked=' checked'
            else: checked=''
            w('<td align=middle>')
            w('<input type="checkbox" name=":group" value="%s" %s></td>'%(
                name, checked))
        w('</tr>')

    w('<tr class="location-bar"><td width="1%">&nbsp;</td>')
    w('<td colspan="%s">'%len(names))
    w('<input type="submit" value="Redisplay"></td></tr>')
    w('</table>')
    w('</form>')


#
#   ITEM TEMPLATES
#
class ItemTemplateReplace:
    def __init__(self, globals, locals, cl, nodeid):
        self.globals = globals
        self.locals = locals
        self.cl = cl
        self.nodeid = nodeid

    def go(self, text, replace=re.compile(
            r'((<property\s+name="(?P<name>[^>]+)">(?P<text>.+?)</property>)|'
            r'(?P<display><display\s+call="(?P<command>[^"]+)">))', re.I|re.S)):
        return replace.sub(self, text)

    def __call__(self, m, filter=None, columns=None, sort=None, group=None):
        if m.group('name'):
            if self.nodeid and self.cl.get(self.nodeid, m.group('name')):
                replace = ItemTemplateReplace(self.globals, {}, self.cl,
                    self.nodeid)
                return replace.go(m.group('text'))
            else:
                return ''
        if m.group('display'):
            command = m.group('command')
            return eval(command, self.globals, self.locals)
        print '*** unhandled match', m.groupdict()

def item(client, templates, db, classname, nodeid, replace=re.compile(
            r'((?P<prop><property\s+name="(?P<propname>[^>]+)">)|'
            r'(?P<endprop></property>)|'
            r'(?P<display><display\s+call="(?P<command>[^"]+)">))', re.I)):

    globals = {
        'plain': Plain(db, templates, classname, nodeid),
        'field': Field(db, templates, classname, nodeid),
        'menu': Menu(db, templates, classname, nodeid),
        'link': Link(db, templates, classname, nodeid),
        'count': Count(db, templates, classname, nodeid),
        'reldate': Reldate(db, templates, classname, nodeid),
        'download': Download(db, templates, classname, nodeid),
        'checklist': Checklist(db, templates, classname, nodeid),
        'list': List(db, templates, classname, nodeid),
        'history': History(db, templates, classname, nodeid),
        'submit': Submit(db, templates, classname, nodeid),
        'note': Note(db, templates, classname, nodeid)
    }

    cl = db.classes[classname]
    properties = cl.getprops()

    if properties.has_key('type') and properties.has_key('content'):
        pass
        # XXX we really want to return this as a downloadable...
        #  currently I handle this at a higher level by detecting 'file'
        #  designators...

    w = client.write
    w('<form action="%s%s">'%(classname, nodeid))
    s = open(os.path.join(templates, classname+'.item')).read()
    replace = ItemTemplateReplace(globals, locals(), cl, nodeid)
    w(replace.go(s))
    w('</form>')


def newitem(client, templates, db, classname, form, replace=re.compile(
            r'((?P<prop><property\s+name="(?P<propname>[^>]+)">)|'
            r'(?P<endprop></property>)|'
            r'(?P<display><display\s+call="(?P<command>[^"]+)">))', re.I)):
    globals = {
        'plain': Plain(db, templates, classname, form=form),
        'field': Field(db, templates, classname, form=form),
        'menu': Menu(db, templates, classname, form=form),
        'link': Link(db, templates, classname, form=form),
        'count': Count(db, templates, classname, form=form),
        'reldate': Reldate(db, templates, classname, form=form),
        'download': Download(db, templates, classname, form=form),
        'checklist': Checklist(db, templates, classname, form=form),
        'list': List(db, templates, classname, form=form),
        'history': History(db, templates, classname, form=form),
        'submit': Submit(db, templates, classname, form=form),
        'note': Note(db, templates, classname, form=form)
    }

    cl = db.classes[classname]
    properties = cl.getprops()

    w = client.write
    try:
        s = open(os.path.join(templates, classname+'.newitem')).read()
    except:
        s = open(os.path.join(templates, classname+'.item')).read()
    w('<form action="new%s">'%classname)
    replace = ItemTemplateReplace(globals, locals(), None, None)
    w(replace.go(s))
    w('</form>')

#
# $Log: not supported by cvs2svn $
# Revision 1.4  2001/07/28 07:59:53  richard
# Replaced errno integers with their module values.
# De-tabbed templatebuilder.py
#
# Revision 1.3  2001/07/25 03:39:47  richard
# Hrm - displaying links to classes that don't specify a key property. I've
# got it defaulting to 'name', then 'title' and then a "random" property (first
# one returned by getprops().keys().
# Needs to be moved onto the Class I think...
#
# Revision 1.2  2001/07/22 12:09:32  richard
# Final commit of Grande Splite
#
# Revision 1.1  2001/07/22 11:58:35  richard
# More Grande Splite
#
