import hyperdb, date, password
from i18n import _
import htmltemplate
import cgi, os, StringIO, urllib, types


def do_plain(client, classname, cl, props, nodeid, filterspec, property, escape=0, lookup=1):
    ''' display a String property directly;

        display a Date property in a specified time zone with an option to
        omit the time from the date stamp;

        for a Link or Multilink property, display the key strings of the
        linked nodes (or the ids if the linked class has no key property)
        when the lookup argument is true, otherwise just return the
        linked ids
    '''
    if not nodeid and client.form is None:
        return _('[Field: not called from item]')
    propclass = props[property]
    value = determine_value(cl, props, nodeid, filterspec, property)
        
    if isinstance(propclass, hyperdb.Password):
        value = _('*encrypted*')
    elif isinstance(propclass, hyperdb.Boolean):
        value = value and "Yes" or "No"
    elif isinstance(propclass, hyperdb.Link):
        if value:
            if lookup:
                linkcl = client.db.classes[propclass.classname]
                k = linkcl.labelprop(1)
                value = linkcl.get(value, k)
        else:
            value = _('[unselected]')
    elif isinstance(propclass, hyperdb.Multilink):
        if value:
            if lookup:
                linkcl = client.db.classes[propclass.classname]
                k = linkcl.labelprop(1)
                labels = []
                for v in value:
                    labels.append(linkcl.get(v, k))
                value = ', '.join(labels)
            else:
                value = ', '.join(value)
        else:
            value = ''
    else:
        value = str(value)
            
    if escape:
        value = cgi.escape(value)
    return value

def do_stext(client, classname, cl, props, nodeid, filterspec, property, escape=0):
    '''Render as structured text using the StructuredText module
       (see above for details)
    '''
    s = do_plain(client, classname, cl, props, nodeid, filterspec, property, escape=escape)
    if not StructuredText:
        return s
    return StructuredText(s,level=1,header=0)

def determine_value(cl, props, nodeid, filterspec, property):
    '''determine the value of a property using the node, form or
       filterspec
    '''
    if nodeid:
        value = cl.get(nodeid, property, None)
        if value is None:
            if isinstance(props[property], hyperdb.Multilink):
                return []
            return ''
        return value
    elif filterspec is not None:
        if isinstance(props[property], hyperdb.Multilink):
            return filterspec.get(property, [])
        else:
            return filterspec.get(property, '')
    # TODO: pull the value from the form
    if isinstance(props[property], hyperdb.Multilink):
        return []
    else:
        return ''

def make_sort_function(client, filterspec, classname):
    '''Make a sort function for a given class
    '''
    linkcl = client.db.getclass(classname)
    if linkcl.getprops().has_key('order'):
        sort_on = 'order'
    else:
        sort_on = linkcl.labelprop()
    def sortfunc(a, b, linkcl=linkcl, sort_on=sort_on):
        return cmp(linkcl.get(a, sort_on), linkcl.get(b, sort_on))
    return sortfunc

def do_field(client, classname, cl, props, nodeid, filterspec, property, size=None, showid=0):
    ''' display a property like the plain displayer, but in a text field
        to be edited

        Note: if you would prefer an option list style display for
        link or multilink editing, use menu().
    '''
    if not nodeid and client.form is None and filterspec is None:
        return _('[Field: not called from item]')
    if size is None:
        size = 30

    propclass = props[property]

    # get the value
    value = determine_value(cl, props, nodeid, filterspec, property)
    # now display
    if (isinstance(propclass, hyperdb.String) or
            isinstance(propclass, hyperdb.Date) or
            isinstance(propclass, hyperdb.Interval)):
        if value is None:
            value = ''
        else:
            value = cgi.escape(str(value))
            value = '&quot;'.join(value.split('"'))
        s = '<input name="%s" value="%s" size="%s">'%(property, value, size)
    elif isinstance(propclass, hyperdb.Boolean):
        checked = value and "checked" or ""
        s = '<input type="radio" name="%s" value="yes" %s>Yes'%(property, checked)
        if checked:
            checked = ""
        else:
            checked = "checked"
        s += '<input type="radio" name="%s" value="no" %s>No'%(property, checked)
    elif isinstance(propclass, hyperdb.Number):
        s = '<input name="%s" value="%s" size="%s">'%(property, value, size)
    elif isinstance(propclass, hyperdb.Password):
        s = '<input type="password" name="%s" size="%s">'%(property, size)
    elif isinstance(propclass, hyperdb.Link):
        linkcl = client.db.getclass(propclass.classname)
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
                lab = '%s%s: %s'%(propclass.classname, optionid, option)
            else:
                lab = option
            if size is not None and len(lab) > size:
                lab = lab[:size-3] + '...'
            lab = cgi.escape(lab)
            l.append('<option %svalue="%s">%s</option>'%(s, optionid, lab))
        l.append('</select>')
        s = '\n'.join(l)
    elif isinstance(propclass, hyperdb.Multilink):
        sortfunc = make_sort_function(client, filterspec, propclass.classname)
        linkcl = client.db.getclass(propclass.classname)
        if value:
            value.sort(sortfunc)
        # map the id to the label property
        if not showid:
            k = linkcl.labelprop(1)
            value = [linkcl.get(v, k) for v in value]
        value = cgi.escape(','.join(value))
        s = '<input name="%s" size="%s" value="%s">'%(property, size, value)
    else:
        s = _('Plain: bad propclass "%(propclass)s"')%locals()
    return s

def do_multiline(client, classname, cl, props, nodeid, filterspec, property, rows=5, cols=40):
    ''' display a string property in a multiline text edit field
    '''
    if not nodeid and client.form is None and filterspec is None:
        return _('[Multiline: not called from item]')

    propclass = props[property]

    # make sure this is a link property
    if not isinstance(propclass, hyperdb.String):
        return _('[Multiline: not a string]')

    # get the value
    value = determine_value(cl, props, nodeid, filterspec, property)
    if value is None:
        value = ''

    # display
    return '<textarea name="%s" rows="%s" cols="%s">%s</textarea>'%(
        property, rows, cols, value)

def do_menu(client, classname, cl, props, nodeid, filterspec, property, size=None, height=None, showid=0,
        additional=[], **conditions):
    ''' For a Link/Multilink property, display a menu of the available
        choices

        If the additional properties are specified, they will be
        included in the text of each option in (brackets, with, commas).
    '''
    if not nodeid and client.form is None and filterspec is None:
        return _('[Field: not called from item]')

    propclass = props[property]

    # make sure this is a link property
    if not (isinstance(propclass, hyperdb.Link) or
            isinstance(propclass, hyperdb.Multilink)):
        return _('[Menu: not a link]')

    # sort function
    sortfunc = make_sort_function(client, filterspec, propclass.classname)

    # get the value
    value = determine_value(cl, props, nodeid, filterspec, property)

    # display
    if isinstance(propclass, hyperdb.Multilink):
        linkcl = client.db.getclass(propclass.classname)
        if linkcl.getprops().has_key('order'):  
            sort_on = 'order'  
        else:  
            sort_on = linkcl.labelprop()
        options = linkcl.filter(None, conditions, [sort_on], []) 
        height = height or min(len(options), 7)
        l = ['<select multiple name="%s" size="%s">'%(property, height)]
        k = linkcl.labelprop(1)
        for optionid in options:
            option = linkcl.get(optionid, k)
            s = ''
            if optionid in value or option in value:
                s = 'selected '
            if showid:
                lab = '%s%s: %s'%(propclass.classname, optionid, option)
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
    if isinstance(propclass, hyperdb.Link):
        # force the value to be a single choice
        if type(value) is types.ListType:
            value = value[0]
        linkcl = client.db.getclass(propclass.classname)
        l = ['<select name="%s">'%property]
        k = linkcl.labelprop(1)
        s = ''
        if value is None:
            s = 'selected '
        l.append(_('<option %svalue="-1">- no selection -</option>')%s)
        if linkcl.getprops().has_key('order'):  
            sort_on = 'order'  
        else:  
            sort_on = linkcl.labelprop() 
        options = linkcl.filter(None, conditions, [sort_on], []) 
        for optionid in options:
            option = linkcl.get(optionid, k)
            s = ''
            if value in [optionid, option]:
                s = 'selected '
            if showid:
                lab = '%s%s: %s'%(propclass.classname, optionid, option)
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
    return _('[Menu: not a link]')

#XXX deviates from spec
def do_link(client, classname, cl, props, nodeid, filterspec, property=None, is_download=0, showid=0):
    '''For a Link or Multilink property, display the names of the linked
       nodes, hyperlinked to the item views on those nodes.
       For other properties, link to this node with the property as the
       text.

       If is_download is true, append the property value to the generated
       URL so that the link may be used as a download link and the
       downloaded file name is correct.
    '''
    if not nodeid and client.form is None:
        return _('[Link: not called from item]')

    # get the value
    value = determine_value(cl, props, nodeid, filterspec, property)
    propclass = props[property]
    if isinstance(propclass, hyperdb.Boolean):
        value = value and "Yes" or "No"
    elif isinstance(propclass, hyperdb.Link):
        if value in ('', None, []):
            return _('[no %(propname)s]')%{'propname':property.capitalize()}
        linkname = propclass.classname
        linkcl = client.db.getclass(linkname)
        k = linkcl.labelprop(1)
        linkvalue = cgi.escape(str(linkcl.get(value, k)))
        if showid:
            label = value
            title = ' title="%s"'%linkvalue
            # note ... this should be urllib.quote(linkcl.get(value, k))
        else:
            label = linkvalue
            title = ''
        if is_download:
            return '<a href="%s%s/%s"%s>%s</a>'%(linkname, value,
                linkvalue, title, label)
        else:
            return '<a href="%s%s"%s>%s</a>'%(linkname, value, title, label)
    elif isinstance(propclass, hyperdb.Multilink):
        if value in ('', None, []):
            return _('[no %(propname)s]')%{'propname':property.capitalize()}
        linkname = propclass.classname
        linkcl = client.db.getclass(linkname)
        k = linkcl.labelprop(1)
        l = []
        for value in value:
            linkvalue = cgi.escape(str(linkcl.get(value, k)))
            if showid:
                label = value
                title = ' title="%s"'%linkvalue
                # note ... this should be urllib.quote(linkcl.get(value, k))
            else:
                label = linkvalue
                title = ''
            if is_download:
                l.append('<a href="%s%s/%s"%s>%s</a>'%(linkname, value,
                    linkvalue, title, label))
            else:
                l.append('<a href="%s%s"%s>%s</a>'%(linkname, value,
                    title, label))
        return ', '.join(l)
    if is_download:
        if value in ('', None, []):
            return _('[no %(propname)s]')%{'propname':property.capitalize()}
        return '<a href="%s%s/%s">%s</a>'%(classname, nodeid,
            value, value)
    else:
        if value in ('', None, []):
            value =  _('[no %(propname)s]')%{'propname':property.capitalize()}
        return '<a href="%s%s">%s</a>'%(classname, nodeid, value)

def do_count(client, classname, cl, props, nodeid, filterspec, property, **args):
    ''' for a Multilink property, display a count of the number of links in
        the list
    '''
    if not nodeid:
        return _('[Count: not called from item]')

    propclass = props[property]
    if not isinstance(propclass, hyperdb.Multilink):
        return _('[Count: not a Multilink]')

    # figure the length then...
    value = cl.get(nodeid, property)
    return str(len(value))

# XXX pretty is definitely new ;)
def do_reldate(client, classname, cl, props, nodeid, filterspec, property, pretty=0):
    ''' display a Date property in terms of an interval relative to the
        current date (e.g. "+ 3w", "- 2d").

        with the 'pretty' flag, make it pretty
    '''
    if not nodeid and client.form is None:
        return _('[Reldate: not called from item]')

    propclass = props[property]
    if not isinstance(propclass, hyperdb.Date):
        return _('[Reldate: not a Date]')

    if nodeid:
        value = cl.get(nodeid, property)
    else:
        return ''
    if not value:
        return ''

    # figure the interval
    interval = date.Date('.') - value
    if pretty:
        if not nodeid:
            return _('now')
        return interval.pretty()
    return str(interval)

def do_download(client, classname, cl, props, nodeid, filterspec, property, **args):
    ''' show a Link("file") or Multilink("file") property using links that
        allow you to download files
    '''
    if not nodeid:
        return _('[Download: not called from item]')
    return do_link(client, classname, cl, props, nodeid, filterspec, property, is_download=1)


def do_checklist(client, classname, cl, props, nodeid, filterspec, property, sortby=None):
    ''' for a Link or Multilink property, display checkboxes for the
        available choices to permit filtering

        sort the checklist by the argument (+/- property name)
    '''
    propclass = props[property]
    if (not isinstance(propclass, hyperdb.Link) and not
            isinstance(propclass, hyperdb.Multilink)):
        return _('[Checklist: not a link]')

    # get our current checkbox state
    if nodeid:
        # get the info from the node - make sure it's a list
        if isinstance(propclass, hyperdb.Link):
            value = [cl.get(nodeid, property)]
        else:
            value = cl.get(nodeid, property)
    elif filterspec is not None:
        # get the state from the filter specification (always a list)
        value = filterspec.get(property, [])
    else:
        # it's a new node, so there's no state
        value = []

    # so we can map to the linked node's "lable" property
    linkcl = client.db.getclass(propclass.classname)
    l = []
    k = linkcl.labelprop(1)

    # build list of options and then sort it, either
    # by id + label or <sortby>-value + label;
    # a minus reverses the sort order, while + or no
    # prefix sort in increasing order
    reversed = 0
    if sortby:
        if sortby[0] == '-':
            reversed = 1
            sortby = sortby[1:]
        elif sortby[0] == '+':
            sortby = sortby[1:]
    options = []
    for optionid in linkcl.list():
        if sortby:
            sortval = linkcl.get(optionid, sortby)
        else:
            sortval = int(optionid)
        option = cgi.escape(str(linkcl.get(optionid, k)))
        options.append((sortval, option, optionid))
    options.sort()
    if reversed:
        options.reverse()

    # build checkboxes
    for sortval, option, optionid in options:
        if optionid in value or option in value:
            checked = 'checked'
        else:
            checked = ''
        l.append('%s:<input type="checkbox" %s name="%s" value="%s">'%(
            option, checked, property, option))

    # for Links, allow the "unselected" option too
    if isinstance(propclass, hyperdb.Link):
        if value is None or '-1' in value:
            checked = 'checked'
        else:
            checked = ''
        l.append(_('[unselected]:<input type="checkbox" %s name="%s" '
            'value="-1">')%(checked, property))
    return '\n'.join(l)

def do_note(client, classname, cl, props, nodeid, filterspec, rows=5, cols=80):
    ''' display a "note" field, which is a text area for entering a note to
        go along with a change. 
    '''
    # TODO: pull the value from the form
    return '<textarea name="__note" wrap="hard" rows=%s cols=%s>'\
        '</textarea>'%(rows, cols)

# XXX new function
def do_list(client, classname, cl, props, nodeid, filterspec, property, reverse=0, xtracols=None):
    ''' list the items specified by property using the standard index for
        the class
    '''
    propcl = props[property]
    if not isinstance(propcl, hyperdb.Multilink):
        return _('[List: not a Multilink]')

    value = determine_value(cl, props, nodeid, filterspec, property)
    if not value:
        return ''

    # sort, possibly revers and then re-stringify
    value = map(int, value)
    value.sort()
    if reverse:
        value.reverse()
    value = map(str, value)

    # render the sub-index into a string
    fp = StringIO.StringIO()
    try:
        write_save = client.write
        client.write = fp.write
        client.listcontext = ('%s%s' % (classname, nodeid), property)
        index = htmltemplate.IndexTemplate(client, client.instance.TEMPLATES, propcl.classname)
        index.render(nodeids=value, show_display_form=0, xtracols=xtracols)
    finally:
        client.listcontext = None
        client.write = write_save

    return fp.getvalue()

# XXX new function
def do_history(client, classname, cl, props, nodeid, filterspec, direction='descending'):
    ''' list the history of the item

        If "direction" is 'descending' then the most recent event will
        be displayed first. If it is 'ascending' then the oldest event
        will be displayed first.
    '''
    if nodeid is None:
        return _("[History: node doesn't exist]")

    l = ['<table width=100% border=0 cellspacing=0 cellpadding=2>',
        '<tr class="list-header">',
        _('<th align=left><span class="list-item">Date</span></th>'),
        _('<th align=left><span class="list-item">User</span></th>'),
        _('<th align=left><span class="list-item">Action</span></th>'),
        _('<th align=left><span class="list-item">Args</span></th>'),
        '</tr>']
    comments = {}
    history = cl.history(nodeid)
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
                    prop = props[k]
                except:
                    prop = None
                if prop is not None:
                    if args[k] and (isinstance(prop, hyperdb.Multilink) or
                            isinstance(prop, hyperdb.Link)):
                        # figure what the link class is
                        classname = prop.classname
                        try:
                            linkcl = client.db.getclass(classname)
                        except KeyError:
                            labelprop = None
                            comments[classname] = _('''The linked class
                                %(classname)s no longer exists''')%locals()
                        labelprop = linkcl.labelprop(1)
                        hrefable = os.path.exists(
                            os.path.join(client.instance.TEMPLATES, classname+'.item'))

                    if isinstance(prop, hyperdb.Multilink) and \
                            len(args[k]) > 0:
                        ml = []
                        for linkid in args[k]:
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
                                ml.append('<strike>%s</strike>'%label)
                            else:
                                if hrefable:
                                    ml.append('<a href="%s%s">%s</a>'%(
                                        classname, linkid, label))
                                else:
                                    ml.append(label)
                        cell.append('%s:\n  %s'%(k, ',\n  '.join(ml)))
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

# XXX new function
def do_submit(client, classname, cl, props, nodeid, filterspec, value=None):
    ''' add a submit button for the item
    '''
    if value is None:
        if nodeid:
            value = "Submit Changes"
        else:
            value = "Submit New Entry"
    if nodeid or client.form is not None:
        return _('<input type="submit" name="submit" value="%s">' % value)
    else:
        return _('[Submit: not called from item]')

def do_classhelp(client, classname, cl, props, nodeid, filterspec, clname, properties, label='?', width='400',
        height='400'):
    '''pop up a javascript window with class help

       This generates a link to a popup window which displays the 
       properties indicated by "properties" of the class named by
       "classname". The "properties" should be a comma-separated list
       (eg. 'id,name,description').

       You may optionally override the label displayed, the width and
       height. The popup window will be resizable and scrollable.
    '''
    return '<a href="javascript:help_window(\'classhelp?classname=%s&' \
        'properties=%s\', \'%s\', \'%s\')"><b>(%s)</b></a>'%(clname,
        properties, width, height, label)

def do_email(client, classname, cl, props, nodeid, filterspec, property, escape=0):
    '''display the property as one or more "fudged" email addrs
    '''
    
    if not nodeid and client.form is None:
        return _('[Email: not called from item]')
    propclass = props[property]
    if nodeid:
        # get the value for this property
        try:
            value = cl.get(nodeid, property)
        except KeyError:
            # a KeyError here means that the node doesn't have a value
            # for the specified property
            value = ''
    else:
        value = ''
    if isinstance(propclass, hyperdb.String):
        if value is None: value = ''
        else: value = str(value)
        value = value.replace('@', ' at ')
        value = value.replace('.', ' ')
    else:
        value = _('[Email: not a string]')%locals()
    if escape:
        value = cgi.escape(value)
    return value

def do_filterspec(client, classname, cl, props, nodeid, filterspec, classprop, urlprop):
    qs = cl.get(nodeid, urlprop)
    classname = cl.get(nodeid, classprop)
    filterspec = {}
    query = cgi.parse_qs(qs)
    for k,v in query.items():
        query[k] = v[0].split(',')
    pagesize = query.get(':pagesize',['25'])[0]
    search_text = query.get('search_text', [''])[0]
    search_text = urllib.unquote(search_text)
    for k,v in query.items():
        if k[0] != ':':
            filterspec[k] = v
    ixtmplt = htmltemplate.IndexTemplate(client, client.instance.TEMPLATES, classname)
    qform = '<form onSubmit="return submit_once()" action="%s%s">\n'%(
        classname,nodeid)
    qform += ixtmplt.filter_form(search_text,
                                 query.get(':filter', []),
                                 query.get(':columns', []),
                                 query.get(':group', []),
                                 [],
                                 query.get(':sort',[]),
                                 filterspec,
                                 pagesize)
    return qform + '</table>\n'

def do_href(client, classname, cl, props, nodeid, filterspec, property, prefix='', suffix='', label=''):
    value = determine_value(cl, props, nodeid, filterspec, property)
    return '<a href="%s%s%s">%s</a>' % (prefix, value, suffix, label)

def do_remove(client, classname, cl, props, nodeid, filterspec):
    ''' put a remove href for an item in a list '''
    if not nodeid:
        return _('[Remove not called from item]')
    try:
        parentdesignator, mlprop = client.listcontext
    except (AttributeError, TypeError):
        return _('[Remove not called form listing of multilink]')
    return '<a href="remove?:target=%s%s&:multilink=%s:%s">[Remove]</a>' % (classname, nodeid, parentdesignator, mlprop)

    
    
