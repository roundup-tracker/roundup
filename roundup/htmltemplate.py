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
# $Id: htmltemplate.py,v 1.82 2002-02-21 23:11:45 richard Exp $

__doc__ = """
Template engine.
"""

import os, re, StringIO, urllib, cgi, errno, types

import hyperdb, date, password
from i18n import _

# This imports the StructureText functionality for the do_stext function
# get it from http://dev.zope.org/Members/jim/StructuredTextWiki/NGReleases
try:
    from StructuredText.StructuredText import HTML as StructuredText
except ImportError:
    StructuredText = None

class MissingTemplateError(ValueError):
    pass

class TemplateFunctions:
    def __init__(self):
        self.form = None
        self.nodeid = None
        self.filterspec = None
        self.globals = {}
        for key in TemplateFunctions.__dict__.keys():
            if key[:3] == 'do_':
                self.globals[key[3:]] = getattr(self, key)

    def do_plain(self, property, escape=0):
        ''' display a String property directly;

            display a Date property in a specified time zone with an option to
            omit the time from the date stamp;

            for a Link or Multilink property, display the key strings of the
            linked nodes (or the ids if the linked class has no key property)
        '''
        if not self.nodeid and self.form is None:
            return _('[Field: not called from item]')
        propclass = self.properties[property]
        if self.nodeid:
            # make sure the property is a valid one
            # TODO: this tests, but we should handle the exception
            prop_test = self.cl.getprops()[property]

            # get the value for this property
            try:
                value = self.cl.get(self.nodeid, property)
            except KeyError:
                # a KeyError here means that the node doesn't have a value
                # for the specified property
                if isinstance(propclass, hyperdb.Multilink): value = []
                else: value = ''
        else:
            # TODO: pull the value from the form
            if isinstance(propclass, hyperdb.Multilink): value = []
            else: value = ''
        if isinstance(propclass, hyperdb.String):
            if value is None: value = ''
            else: value = str(value)
        elif isinstance(propclass, hyperdb.Password):
            if value is None: value = ''
            else: value = _('*encrypted*')
        elif isinstance(propclass, hyperdb.Date):
            # this gives "2002-01-17.06:54:39", maybe replace the "." by a " ".
            value = str(value)
        elif isinstance(propclass, hyperdb.Interval):
            value = str(value)
        elif isinstance(propclass, hyperdb.Link):
            linkcl = self.db.classes[propclass.classname]
            k = linkcl.labelprop()
            if value:
                value = linkcl.get(value, k)
            else:
                value = _('[unselected]')
        elif isinstance(propclass, hyperdb.Multilink):
            linkcl = self.db.classes[propclass.classname]
            k = linkcl.labelprop()
            value = ', '.join(value)
        else:
            s = _('Plain: bad propclass "%(propclass)s"')%locals()
        if escape:
            value = cgi.escape(value)
        return value

    def do_stext(self, property, escape=0):
        '''Render as structured text using the StructuredText module
           (see above for details)
        '''
        s = self.do_plain(property, escape=escape)
        if not StructuredText:
            return s
        return StructuredText(s,level=1,header=0)

    def determine_value(self, property):
        '''determine the value of a property using the node, form or
           filterspec
        '''
        propclass = self.properties[property]
        if self.nodeid:
            value = self.cl.get(self.nodeid, property, None)
            if isinstance(propclass, hyperdb.Multilink) and value is None:
                return []
            return value
        elif self.filterspec is not None:
            if isinstance(propclass, hyperdb.Multilink):
                return self.filterspec.get(property, [])
            else:
                return self.filterspec.get(property, '')
        # TODO: pull the value from the form
        if isinstance(propclass, hyperdb.Multilink):
            return []
        else:
            return ''

    def make_sort_function(self, classname):
        '''Make a sort function for a given class
        '''
        linkcl = self.db.classes[classname]
        if linkcl.getprops().has_key('order'):
            sort_on = 'order'
        else:
            sort_on = linkcl.labelprop()
        def sortfunc(a, b, linkcl=linkcl, sort_on=sort_on):
            return cmp(linkcl.get(a, sort_on), linkcl.get(b, sort_on))
        return sortfunc

    def do_field(self, property, size=None, showid=0):
        ''' display a property like the plain displayer, but in a text field
            to be edited

            Note: if you would prefer an option list style display for
            link or multilink editing, use menu().
        '''
        if not self.nodeid and self.form is None and self.filterspec is None:
            return _('[Field: not called from item]')

        if size is None:
            size = 30

        propclass = self.properties[property]

        # get the value
        value = self.determine_value(property)

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
        elif isinstance(propclass, hyperdb.Password):
            s = '<input type="password" name="%s" size="%s">'%(property, size)
        elif isinstance(propclass, hyperdb.Link):
            sortfunc = self.make_sort_function(propclass.classname)
            linkcl = self.db.classes[propclass.classname]
            options = linkcl.list()
            options.sort(sortfunc)
            # TODO: make this a field display, not a menu one!
            l = ['<select name="%s">'%property]
            k = linkcl.labelprop()
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
            sortfunc = self.make_sort_function(propclass.classname)
            linkcl = self.db.classes[propclass.classname]
            list = linkcl.list()
            list.sort(sortfunc)
            l = []
            # map the id to the label property
            if not showid:
                k = linkcl.labelprop()
                value = [linkcl.get(v, k) for v in value]
            value = cgi.escape(','.join(value))
            s = '<input name="%s" size="%s" value="%s">'%(property, size, value)
        else:
            s = _('Plain: bad propclass "%(propclass)s"')%locals()
        return s

    def do_multiline(self, property, rows=5, cols=40):
        ''' display a string property in a multiline text edit field
        '''
        if not self.nodeid and self.form is None and self.filterspec is None:
            return _('[Multiline: not called from item]')

        propclass = self.properties[property]

        # make sure this is a link property
        if not isinstance(propclass, hyperdb.String):
            return _('[Multiline: not a string]')

        # get the value
        value = self.determine_value(property)
        if value is None:
            value = ''

        # display
        return '<textarea name="%s" rows="%s" cols="%s">%s</textarea>'%(
            property, rows, cols, value)

    def do_menu(self, property, size=None, height=None, showid=0):
        ''' for a Link property, display a menu of the available choices
        '''
        if not self.nodeid and self.form is None and self.filterspec is None:
            return _('[Field: not called from item]')

        propclass = self.properties[property]

        # make sure this is a link property
        if not (isinstance(propclass, hyperdb.Link) or
                isinstance(propclass, hyperdb.Multilink)):
            return _('[Menu: not a link]')

        # sort function
        sortfunc = self.make_sort_function(propclass.classname)

        # get the value
        value = self.determine_value(property)

        # display
        if isinstance(propclass, hyperdb.Multilink):
            linkcl = self.db.classes[propclass.classname]
            options = linkcl.list()
            options.sort(sortfunc)
            height = height or min(len(options), 7)
            l = ['<select multiple name="%s" size="%s">'%(property, height)]
            k = linkcl.labelprop()
            for optionid in options:
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
                lab = cgi.escape(lab)
                l.append('<option %svalue="%s">%s</option>'%(s, optionid,
                    lab))
            l.append('</select>')
            return '\n'.join(l)
        if isinstance(propclass, hyperdb.Link):
            # force the value to be a single choice
            if type(value) is types.ListType:
                value = value[0]
            linkcl = self.db.classes[propclass.classname]
            l = ['<select name="%s">'%property]
            k = linkcl.labelprop()
            s = ''
            if value is None:
                s = 'selected '
            l.append(_('<option %svalue="-1">- no selection -</option>')%s)
            options = linkcl.list()
            options.sort(sortfunc)
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
            return '\n'.join(l)
        return _('[Menu: not a link]')

    #XXX deviates from spec
    def do_link(self, property=None, is_download=0):
        '''For a Link or Multilink property, display the names of the linked
           nodes, hyperlinked to the item views on those nodes.
           For other properties, link to this node with the property as the
           text.

           If is_download is true, append the property value to the generated
           URL so that the link may be used as a download link and the
           downloaded file name is correct.
        '''
        if not self.nodeid and self.form is None:
            return _('[Link: not called from item]')

        # get the value
        value = self.determine_value(property)
        if not value:
            return _('[no %(propname)s]')%{'propname':property.capitalize()}

        propclass = self.properties[property]
        if isinstance(propclass, hyperdb.Link):
            linkname = propclass.classname
            linkcl = self.db.classes[linkname]
            k = linkcl.labelprop()
            linkvalue = cgi.escape(linkcl.get(value, k))
            if is_download:
                return '<a href="%s%s/%s">%s</a>'%(linkname, value,
                    linkvalue, linkvalue)
            else:
                return '<a href="%s%s">%s</a>'%(linkname, value, linkvalue)
        if isinstance(propclass, hyperdb.Multilink):
            linkname = propclass.classname
            linkcl = self.db.classes[linkname]
            k = linkcl.labelprop()
            l = []
            for value in value:
                linkvalue = cgi.escape(linkcl.get(value, k))
                if is_download:
                    l.append('<a href="%s%s/%s">%s</a>'%(linkname, value,
                        linkvalue, linkvalue))
                else:
                    l.append('<a href="%s%s">%s</a>'%(linkname, value,
                        linkvalue))
            return ', '.join(l)
        if is_download:
            return '<a href="%s%s/%s">%s</a>'%(self.classname, self.nodeid,
                value, value)
        else:
            return '<a href="%s%s">%s</a>'%(self.classname, self.nodeid, value)

    def do_count(self, property, **args):
        ''' for a Multilink property, display a count of the number of links in
            the list
        '''
        if not self.nodeid:
            return _('[Count: not called from item]')

        propclass = self.properties[property]
        if not isinstance(propclass, hyperdb.Multilink):
            return _('[Count: not a Multilink]')

        # figure the length then...
        value = self.cl.get(self.nodeid, property)
        return str(len(value))

    # XXX pretty is definitely new ;)
    def do_reldate(self, property, pretty=0):
        ''' display a Date property in terms of an interval relative to the
            current date (e.g. "+ 3w", "- 2d").

            with the 'pretty' flag, make it pretty
        '''
        if not self.nodeid and self.form is None:
            return _('[Reldate: not called from item]')

        propclass = self.properties[property]
        if not isinstance(propclass, hyperdb.Date):
            return _('[Reldate: not a Date]')

        if self.nodeid:
            value = self.cl.get(self.nodeid, property)
        else:
            return ''
        if not value:
            return ''

        # figure the interval
        interval = date.Date('.') - value
        if pretty:
            if not self.nodeid:
                return _('now')
            pretty = interval.pretty()
            if pretty is None:
                pretty = value.pretty()
            return pretty
        return str(interval)

    def do_download(self, property, **args):
        ''' show a Link("file") or Multilink("file") property using links that
            allow you to download files
        '''
        if not self.nodeid:
            return _('[Download: not called from item]')
        return self.do_link(property, is_download=1)


    def do_checklist(self, property, **args):
        ''' for a Link or Multilink property, display checkboxes for the
            available choices to permit filtering
        '''
        propclass = self.properties[property]
        if (not isinstance(propclass, hyperdb.Link) and not
                isinstance(propclass, hyperdb.Multilink)):
            return _('[Checklist: not a link]')

        # get our current checkbox state
        if self.nodeid:
            # get the info from the node - make sure it's a list
            if isinstance(propclass, hyperdb.Link):
                value = [self.cl.get(self.nodeid, property)]
            else:
                value = self.cl.get(self.nodeid, property)
        elif self.filterspec is not None:
            # get the state from the filter specification (always a list)
            value = self.filterspec.get(property, [])
        else:
            # it's a new node, so there's no state
            value = []

        # so we can map to the linked node's "lable" property
        linkcl = self.db.classes[propclass.classname]
        l = []
        k = linkcl.labelprop()
        for optionid in linkcl.list():
            option = cgi.escape(linkcl.get(optionid, k))
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

    def do_note(self, rows=5, cols=80):
        ''' display a "note" field, which is a text area for entering a note to
            go along with a change. 
        '''
        # TODO: pull the value from the form
        return '<textarea name="__note" wrap="hard" rows=%s cols=%s>'\
            '</textarea>'%(rows, cols)

    # XXX new function
    def do_list(self, property, reverse=0):
        ''' list the items specified by property using the standard index for
            the class
        '''
        propcl = self.properties[property]
        if not isinstance(propcl, hyperdb.Multilink):
            return _('[List: not a Multilink]')

        value = self.determine_value(property)
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
            write_save = self.client.write
            self.client.write = fp.write
            index = IndexTemplate(self.client, self.templates, propcl.classname)
            index.render(nodeids=value, show_display_form=0)
        finally:
            self.client.write = write_save

        return fp.getvalue()

    # XXX new function
    def do_history(self, direction='descending'):
        ''' list the history of the item

            If "direction" is 'descending' then the most recent event will
            be displayed first. If it is 'ascending' then the oldest event
            will be displayed first.
        '''
        if self.nodeid is None:
            return _("[History: node doesn't exist]")

        l = ['<table width=100% border=0 cellspacing=0 cellpadding=2>',
            '<tr class="list-header">',
            _('<th align=left><span class="list-item">Date</span></th>'),
            _('<th align=left><span class="list-item">User</span></th>'),
            _('<th align=left><span class="list-item">Action</span></th>'),
            _('<th align=left><span class="list-item">Args</span></th>'),
            '</tr>']

        comments = {}
        history = self.cl.history(self.nodeid)
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
                    arg_s = str(arg)

            elif action == 'unlink' and type(args) == type(()):
                if len(args) == 3:
                    linkcl, linkid, key = args
                    arg_s += '<a href="%s%s">%s%s %s</a>'%(linkcl, linkid,
                        linkcl, linkid, key)
                else:
                    arg_s = str(arg)

            elif type(args) == type({}):
                cell = []
                for k in args.keys():
                    # try to get the relevant property and treat it
                    # specially
                    try:
                        prop = self.properties[k]
                    except:
                        prop = None
                    if prop is not None:
                        if args[k] and (isinstance(prop, hyperdb.Multilink) or
                                isinstance(prop, hyperdb.Link)):
                            # figure what the link class is
                            classname = prop.classname
                            try:
                                linkcl = self.db.classes[classname]
                            except KeyError, message:
                                labelprop = None
                                comments[classname] = _('''The linked class
                                    %(classname)s no longer exists''')%locals()
                            labelprop = linkcl.labelprop()

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
                                    ml.append('<a href="%s%s">%s</a>'%(
                                        classname, linkid, label))
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
                                cell.append('%s: <a href="%s%s">%s</a>\n'%(k,
                                    classname, args[k], label))

                        elif isinstance(prop, hyperdb.Date) and args[k]:
                            d = date.Date(args[k])
                            cell.append('%s: %s'%(k, str(d)))

                        elif isinstance(prop, hyperdb.Interval) and args[k]:
                            d = date.Interval(args[k])
                            cell.append('%s: %s'%(k, str(d)))

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
    def do_submit(self):
        ''' add a submit button for the item
        '''
        if self.nodeid:
            return _('<input type="submit" name="submit" value="Submit Changes">')
        elif self.form is not None:
            return _('<input type="submit" name="submit" value="Submit New Entry">')
        else:
            return _('[Submit: not called from item]')

    def do_classhelp(self, classname, properties, label='?', width='400',
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
            'properties=%s\', \'%s\', \'%s\')"><b>(%s)</b></a>'%(classname,
            properties, width, height, label)
#
#   INDEX TEMPLATES
#
class IndexTemplateReplace:
    def __init__(self, globals, locals, props):
        self.globals = globals
        self.locals = locals
        self.props = props

    replace=re.compile(
        r'((<property\s+name="(?P<name>[^>]+)">(?P<text>.+?)</property>)|'
        r'(?P<display><display\s+call="(?P<command>[^"]+)">))', re.I|re.S)
    def go(self, text):
        return self.replace.sub(self, text)

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

class IndexTemplate(TemplateFunctions):
    def __init__(self, client, templates, classname):
        self.client = client
        self.instance = client.instance
        self.templates = templates
        self.classname = classname

        # derived
        self.db = self.client.db
        self.cl = self.db.classes[self.classname]
        self.properties = self.cl.getprops()

        TemplateFunctions.__init__(self)

    col_re=re.compile(r'<property\s+name="([^>]+)">')
    def render(self, filterspec={}, filter=[], columns=[], sort=[], group=[],
            show_display_form=1, nodeids=None, show_customization=1):
        self.filterspec = filterspec

        w = self.client.write

        # get the filter template
        try:
            filter_template = open(os.path.join(self.templates,
                self.classname+'.filter')).read()
            all_filters = self.col_re.findall(filter_template)
        except IOError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise
            filter_template = None
            all_filters = []

        # XXX deviate from spec here ...
        # load the index section template and figure the default columns from it
        try:
            template = open(os.path.join(self.templates,
                self.classname+'.index')).read()
        except IOError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise
            raise MissingTemplateError, self.classname+'.index'
        all_columns = self.col_re.findall(template)
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

        # display the filter section
        if (show_display_form and 
                self.instance.FILTER_POSITION in ('top and bottom', 'top')):
            w('<form onSubmit="return submit_once()" action="%s">\n'%self.classname)
            self.filter_section(filter_template, filter, columns, group,
                all_filters, all_columns, show_customization)
            # make sure that the sorting doesn't get lost either
            if sort:
                w('<input type="hidden" name=":sort" value="%s">'%
                    ','.join(sort))
            w('</form>\n')


        # now display the index section
        w('<table width=100% border=0 cellspacing=0 cellpadding=2>\n')
        w('<tr class="list-header">\n')
        for name in columns:
            cname = name.capitalize()
            if show_display_form:
                sb = self.sortby(name, filterspec, columns, filter, group, sort)
                anchor = "%s?%s"%(self.classname, sb)
                w('<td><span class="list-header"><a href="%s">%s</a></span></td>\n'%(
                    anchor, cname))
            else:
                w('<td><span class="list-header">%s</span></td>\n'%cname)
        w('</tr>\n')

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
            nodeids = self.cl.filter(filterspec, sort, group)
        for nodeid in nodeids:
            # check for a group heading
            if group_names:
                this_group = [self.cl.get(nodeid, name, _('[no value]'))
                    for name in group_names]
                if this_group != old_group:
                    l = []
                    for name in group_names:
                        prop = self.properties[name]
                        if isinstance(prop, hyperdb.Link):
                            group_cl = self.db.classes[prop.classname]
                            key = group_cl.getkey()
                            value = self.cl.get(nodeid, name)
                            if value is None:
                                l.append(_('[unselected %(classname)s]')%{
                                    'classname': prop.classname})
                            else:
                                l.append(group_cl.get(self.cl.get(nodeid,
                                    name), key))
                        elif isinstance(prop, hyperdb.Multilink):
                            group_cl = self.db.classes[prop.classname]
                            key = group_cl.getkey()
                            for value in self.cl.get(nodeid, name):
                                l.append(group_cl.get(value, key))
                        else:
                            value = self.cl.get(nodeid, name, _('[no value]'))
                            if value is None:
                                value = _('[empty %(name)s]')%locals()
                            else:
                                value = str(value)
                            l.append(value)
                    w('<tr class="section-bar">'
                      '<td align=middle colspan=%s><strong>%s</strong></td></tr>'%(
                        len(columns), ', '.join(l)))
                    old_group = this_group

            # display this node's row
            replace = IndexTemplateReplace(self.globals, locals(), columns)
            self.nodeid = nodeid
            w(replace.go(template))
            self.nodeid = None

        w('</table>')

        # display the filter section
        if (show_display_form and hasattr(self.instance, 'FILTER_POSITION') and
                self.instance.FILTER_POSITION in ('top and bottom', 'bottom')):
            w('<form onSubmit="return submit_once()" action="%s">\n'%self.classname)
            self.filter_section(filter_template, filter, columns, group,
                all_filters, all_columns, show_customization)
            # make sure that the sorting doesn't get lost either
            if sort:
                w('<input type="hidden" name=":sort" value="%s">'%
                    ','.join(sort))
            w('</form>\n')


    def filter_section(self, template, filter, columns, group, all_filters,
            all_columns, show_customization):

        w = self.client.write

        # wrap the template in a single table to ensure the whole widget
        # is displayed at once
        w('<table><tr><td>')

        if template and filter:
            # display the filter section
            w('<table width=100% border=0 cellspacing=0 cellpadding=2>')
            w('<tr class="location-bar">')
            w(_(' <th align="left" colspan="2">Filter specification...</th>'))
            w('</tr>')
            replace = IndexTemplateReplace(self.globals, locals(), filter)
            w(replace.go(template))
            w('<tr class="location-bar"><td width="1%%">&nbsp;</td>')
            w(_('<td><input type="submit" name="action" value="Redisplay"></td></tr>'))
            w('</table>')

        # now add in the filter/columns/group/etc config table form
        w('<input type="hidden" name="show_customization" value="%s">' %
            show_customization )
        w('<table width=100% border=0 cellspacing=0 cellpadding=2>\n')
        names = []
        seen = {}
        for name in all_filters + all_columns:
            if self.properties.has_key(name) and not seen.has_key(name):
                names.append(name)
            seen[name] = 1
        if show_customization:
            action = '-'
        else:
            action = '+'
            # hide the values for filters, columns and grouping in the form
            # if the customization widget is not visible
            for name in names:
                if all_filters and name in filter:
                    w('<input type="hidden" name=":filter" value="%s">' % name)
                if all_columns and name in columns:
                    w('<input type="hidden" name=":columns" value="%s">' % name)
                if all_columns and name in group:
                    w('<input type="hidden" name=":group" value="%s">' % name)

        # TODO: The widget style can go into the stylesheet
        w(_('<th align="left" colspan=%s>'
          '<input style="height : 1em; width : 1em; font-size: 12pt" type="submit" name="action" value="%s">&nbsp;View '
          'customisation...</th></tr>\n')%(len(names)+1, action))

        if not show_customization:
            w('</table>\n')
            return

        w('<tr class="location-bar"><th>&nbsp;</th>')
        for name in names:
            w('<th>%s</th>'%name.capitalize())
        w('</tr>\n')

        # Filter
        if all_filters:
            w(_('<tr><th width="1%" align=right class="location-bar">Filters</th>\n'))
            for name in names:
                if name not in all_filters:
                    w('<td>&nbsp;</td>')
                    continue
                if name in filter: checked=' checked'
                else: checked=''
                w('<td align=middle>\n')
                w(' <input type="checkbox" name=":filter" value="%s" '
                  '%s></td>\n'%(name, checked))
            w('</tr>\n')

        # Columns
        if all_columns:
            w(_('<tr><th width="1%" align=right class="location-bar">Columns</th>\n'))
            for name in names:
                if name not in all_columns:
                    w('<td>&nbsp;</td>')
                    continue
                if name in columns: checked=' checked'
                else: checked=''
                w('<td align=middle>\n')
                w(' <input type="checkbox" name=":columns" value="%s"'
                  '%s></td>\n'%(name, checked))
            w('</tr>\n')

            # Grouping
            w(_('<tr><th width="1%" align=right class="location-bar">Grouping</th>\n'))
            for name in names:
                prop = self.properties[name]
                if name not in all_columns:
                    w('<td>&nbsp;</td>')
                    continue
                if name in group: checked=' checked'
                else: checked=''
                w('<td align=middle>\n')
                w(' <input type="checkbox" name=":group" value="%s"'
                  '%s></td>\n'%(name, checked))
            w('</tr>\n')

        w('<tr class="location-bar"><td width="1%">&nbsp;</td>')
        w('<td colspan="%s">'%len(names))
        w(_('<input type="submit" name="action" value="Redisplay"></td>'))
        w('</tr>\n')
        w('</table>\n')

        # and the outer table
        w('</td></tr></table>')


    def sortby(self, sort_name, filterspec, columns, filter, group, sort):
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
                name = name[1:]
            else:
                dir = ''
            if sort_name == name:
                if dir == '-':
                    s_dir = ''
                else:
                    s_dir = '-'
            else:
                m.append(dir+urllib.quote(name))
        m.insert(0, s_dir+urllib.quote(sort_name))
        # so things don't get completely out of hand, limit the sort to
        # two columns
        w(':sort=%s'%','.join(m[:2]))
        return '&'.join(l)

#
#   ITEM TEMPLATES
#
class ItemTemplateReplace:
    def __init__(self, globals, locals, cl, nodeid):
        self.globals = globals
        self.locals = locals
        self.cl = cl
        self.nodeid = nodeid

    replace=re.compile(
        r'((<property\s+name="(?P<name>[^>]+)">(?P<text>.+?)</property>)|'
        r'(?P<display><display\s+call="(?P<command>[^"]+)">))', re.I|re.S)
    def go(self, text):
        return self.replace.sub(self, text)

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


class ItemTemplate(TemplateFunctions):
    def __init__(self, client, templates, classname):
        self.client = client
        self.instance = client.instance
        self.templates = templates
        self.classname = classname

        # derived
        self.db = self.client.db
        self.cl = self.db.classes[self.classname]
        self.properties = self.cl.getprops()

        TemplateFunctions.__init__(self)

    def render(self, nodeid):
        self.nodeid = nodeid

        if (self.properties.has_key('type') and
                self.properties.has_key('content')):
            pass
            # XXX we really want to return this as a downloadable...
            #  currently I handle this at a higher level by detecting 'file'
            #  designators...

        w = self.client.write
        w('<form onSubmit="return submit_once()" action="%s%s" method="POST" enctype="multipart/form-data">'%(
            self.classname, nodeid))
        s = open(os.path.join(self.templates, self.classname+'.item')).read()
        replace = ItemTemplateReplace(self.globals, locals(), self.cl, nodeid)
        w(replace.go(s))
        w('</form>')


class NewItemTemplate(TemplateFunctions):
    def __init__(self, client, templates, classname):
        self.client = client
        self.instance = client.instance
        self.templates = templates
        self.classname = classname

        # derived
        self.db = self.client.db
        self.cl = self.db.classes[self.classname]
        self.properties = self.cl.getprops()

        TemplateFunctions.__init__(self)

    def render(self, form):
        self.form = form
        w = self.client.write
        c = self.classname
        try:
            s = open(os.path.join(self.templates, c+'.newitem')).read()
        except IOError:
            s = open(os.path.join(self.templates, c+'.item')).read()
        w('<form onSubmit="return submit_once()" action="new%s" method="POST" enctype="multipart/form-data">'%c)
        for key in form.keys():
            if key[0] == ':':
                value = form[key].value
                if type(value) != type([]): value = [value]
                for value in value:
                    w('<input type="hidden" name="%s" value="%s">'%(key, value))
        replace = ItemTemplateReplace(self.globals, locals(), None, None)
        w(replace.go(s))
        w('</form>')

#
# $Log: not supported by cvs2svn $
# Revision 1.81  2002/02/21 07:21:38  richard
# docco
#
# Revision 1.80  2002/02/21 07:19:08  richard
# ... and label, width and height control for extra flavour!
#
# Revision 1.79  2002/02/21 06:57:38  richard
#  . Added popup help for classes using the classhelp html template function.
#    - add <display call="classhelp('priority', 'id,name,description')">
#      to an item page, and it generates a link to a popup window which displays
#      the id, name and description for the priority class. The description
#      field won't exist in most installations, but it will be added to the
#      default templates.
#
# Revision 1.78  2002/02/21 06:23:00  richard
# *** empty log message ***
#
# Revision 1.77  2002/02/20 05:05:29  richard
#  . Added simple editing for classes that don't define a templated interface.
#    - access using the admin "class list" interface
#    - limited to admin-only
#    - requires the csv module from object-craft (url given if it's missing)
#
# Revision 1.76  2002/02/16 09:10:52  richard
# oops
#
# Revision 1.75  2002/02/16 08:43:23  richard
#  . #517906 ] Attribute order in "View customisation"
#
# Revision 1.74  2002/02/16 08:39:42  richard
#  . #516854 ] "My Issues" and redisplay
#
# Revision 1.73  2002/02/15 07:08:44  richard
#  . Alternate email addresses are now available for users. See the MIGRATION
#    file for info on how to activate the feature.
#
# Revision 1.72  2002/02/14 23:39:18  richard
# . All forms now have "double-submit" protection when Javascript is enabled
#   on the client-side.
#
# Revision 1.71  2002/01/23 06:15:24  richard
# real (non-string, duh) sorting of lists by node id
#
# Revision 1.70  2002/01/23 05:47:57  richard
# more HTML template cleanup and unit tests
#
# Revision 1.69  2002/01/23 05:10:27  richard
# More HTML template cleanup and unit tests.
#  - download() now implemented correctly, replacing link(is_download=1) [fixed in the
#    templates, but link(is_download=1) will still work for existing templates]
#
# Revision 1.68  2002/01/22 22:55:28  richard
#  . htmltemplate list() wasn't sorting...
#
# Revision 1.67  2002/01/22 22:46:22  richard
# more htmltemplate cleanups and unit tests
#
# Revision 1.66  2002/01/22 06:35:40  richard
# more htmltemplate tests and cleanup
#
# Revision 1.65  2002/01/22 00:12:06  richard
# Wrote more unit tests for htmltemplate, and while I was at it, I polished
# off the implementation of some of the functions so they behave sanely.
#
# Revision 1.64  2002/01/21 03:25:59  richard
# oops
#
# Revision 1.63  2002/01/21 02:59:10  richard
# Fixed up the HTML display of history so valid links are actually displayed.
# Oh for some unit tests! :(
#
# Revision 1.62  2002/01/18 08:36:12  grubert
#  . add nowrap to history table date cell i.e. <td nowrap ...
#
# Revision 1.61  2002/01/17 23:04:53  richard
#  . much nicer history display (actualy real handling of property types etc)
#
# Revision 1.60  2002/01/17 08:48:19  grubert
#  . display superseder as html link in history.
#
# Revision 1.59  2002/01/17 07:58:24  grubert
#  . display links a html link in history.
#
# Revision 1.58  2002/01/15 00:50:03  richard
# #502949 ] index view for non-issues and redisplay
#
# Revision 1.57  2002/01/14 23:31:21  richard
# reverted the change that had plain() hyperlinking the link displays -
# that's what link() is for!
#
# Revision 1.56  2002/01/14 07:04:36  richard
#  . plain rendering of links in the htmltemplate now generate a hyperlink to
#    the linked node's page.
#    ... this allows a display very similar to bugzilla's where you can actually
#    find out information about the linked node.
#
# Revision 1.55  2002/01/14 06:45:03  richard
#  . #502953 ] nosy-like treatment of other multilinks
#    ... had to revert most of the previous change to the multilink field
#    display... not good.
#
# Revision 1.54  2002/01/14 05:16:51  richard
# The submit buttons need a name attribute or mozilla won't submit without a
# file upload. Yeah, that's bloody obscure. Grr.
#
# Revision 1.53  2002/01/14 04:03:32  richard
# How about that ... date fields have never worked ...
#
# Revision 1.52  2002/01/14 02:20:14  richard
#  . changed all config accesses so they access either the instance or the
#    config attriubute on the db. This means that all config is obtained from
#    instance_config instead of the mish-mash of classes. This will make
#    switching to a ConfigParser setup easier too, I hope.
#
# At a minimum, this makes migration a _little_ easier (a lot easier in the
# 0.5.0 switch, I hope!)
#
# Revision 1.51  2002/01/10 10:02:15  grubert
# In do_history: replace "." in date by " " so html wraps more sensible.
# Should this be done in date's string converter ?
#
# Revision 1.50  2002/01/05 02:35:10  richard
# I18N'ification
#
# Revision 1.49  2001/12/20 15:43:01  rochecompaan
# Features added:
#  .  Multilink properties are now displayed as comma separated values in
#     a textbox
#  .  The add user link is now only visible to the admin user
#  .  Modified the mail gateway to reject submissions from unknown
#     addresses if ANONYMOUS_ACCESS is denied
#
# Revision 1.48  2001/12/20 06:13:24  rochecompaan
# Bugs fixed:
#   . Exception handling in hyperdb for strings-that-look-like numbers got
#     lost somewhere
#   . Internet Explorer submits full path for filename - we now strip away
#     the path
# Features added:
#   . Link and multilink properties are now displayed sorted in the cgi
#     interface
#
# Revision 1.47  2001/11/26 22:55:56  richard
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
# Revision 1.46  2001/11/24 00:53:12  jhermann
# "except:" is bad, bad , bad!
#
# Revision 1.45  2001/11/22 15:46:42  jhermann
# Added module docstrings to all modules.
#
# Revision 1.44  2001/11/21 23:35:45  jhermann
# Added globbing for win32, and sample marking in a 2nd file to test it
#
# Revision 1.43  2001/11/21 04:04:43  richard
# *sigh* more missing value handling
#
# Revision 1.42  2001/11/21 03:40:54  richard
# more new property handling
#
# Revision 1.41  2001/11/15 10:26:01  richard
#  . missing "return" in filter_section (thanks Roch'e Compaan)
#
# Revision 1.40  2001/11/03 01:56:51  richard
# More HTML compliance fixes. This will probably fix the Netscape problem
# too.
#
# Revision 1.39  2001/11/03 01:43:47  richard
# Ahah! Fixed the lynx problem - there was a hidden input field misplaced.
#
# Revision 1.38  2001/10/31 06:58:51  richard
# Added the wrap="hard" attribute to the textarea of the note field so the
# messages wrap sanely.
#
# Revision 1.37  2001/10/31 06:24:35  richard
# Added do_stext to htmltemplate, thanks Brad Clements.
#
# Revision 1.36  2001/10/28 22:51:38  richard
# Fixed ENOENT/WindowsError thing, thanks Juergen Hermann
#
# Revision 1.35  2001/10/24 00:04:41  richard
# Removed the "infinite authentication loop", thanks Roch'e
#
# Revision 1.34  2001/10/23 22:56:36  richard
# Bugfix in filter "widget" placement, thanks Roch'e
#
# Revision 1.33  2001/10/23 01:00:18  richard
# Re-enabled login and registration access after lopping them off via
# disabling access for anonymous users.
# Major re-org of the htmltemplate code, cleaning it up significantly. Fixed
# a couple of bugs while I was there. Probably introduced a couple, but
# things seem to work OK at the moment.
#
# Revision 1.32  2001/10/22 03:25:01  richard
# Added configuration for:
#  . anonymous user access and registration (deny/allow)
#  . filter "widget" location on index page (top, bottom, both)
# Updated some documentation.
#
# Revision 1.31  2001/10/21 07:26:35  richard
# feature #473127: Filenames. I modified the file.index and htmltemplate
#  source so that the filename is used in the link and the creation
#  information is displayed.
#
# Revision 1.30  2001/10/21 04:44:50  richard
# bug #473124: UI inconsistency with Link fields.
#    This also prompted me to fix a fairly long-standing usability issue -
#    that of being able to turn off certain filters.
#
# Revision 1.29  2001/10/21 00:17:56  richard
# CGI interface view customisation section may now be hidden (patch from
#  Roch'e Compaan.)
#
# Revision 1.28  2001/10/21 00:00:16  richard
# Fixed Checklist function - wasn't always working on a list.
#
# Revision 1.27  2001/10/20 12:13:44  richard
# Fixed grouping of non-str properties (thanks Roch'e Compaan)
#
# Revision 1.26  2001/10/14 10:55:00  richard
# Handle empty strings in HTML template Link function
#
# Revision 1.25  2001/10/09 07:25:59  richard
# Added the Password property type. See "pydoc roundup.password" for
# implementation details. Have updated some of the documentation too.
#
# Revision 1.24  2001/09/27 06:45:58  richard
# *gak* ... xmp is Old Skool apparently. Am using pre again by have the option
# on the plain() template function to escape the text for HTML.
#
# Revision 1.23  2001/09/10 09:47:18  richard
# Fixed bug in the generation of links to Link/Multilink in indexes.
#   (thanks Hubert Hoegl)
# Added AssignedTo to the "classic" schema's item page.
#
# Revision 1.22  2001/08/30 06:01:17  richard
# Fixed missing import in mailgw :(
#
# Revision 1.21  2001/08/16 07:34:59  richard
# better CGI text searching - but hidden filter fields are disappearing...
#
# Revision 1.20  2001/08/15 23:43:18  richard
# Fixed some isFooTypes that I missed.
# Refactored some code in the CGI code.
#
# Revision 1.19  2001/08/12 06:32:36  richard
# using isinstance(blah, Foo) now instead of isFooType
#
# Revision 1.18  2001/08/07 00:24:42  richard
# stupid typo
#
# Revision 1.17  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.16  2001/08/01 03:52:23  richard
# Checklist was using wrong name.
#
# Revision 1.15  2001/07/30 08:12:17  richard
# Added time logging and file uploading to the templates.
#
# Revision 1.14  2001/07/30 06:17:45  richard
# Features:
#  . Added ability for cgi newblah forms to indicate that the new node
#    should be linked somewhere.
# Fixed:
#  . Fixed the agument handling for the roundup-admin find command.
#  . Fixed handling of summary when no note supplied for newblah. Again.
#  . Fixed detection of no form in htmltemplate Field display.
#
# Revision 1.13  2001/07/30 02:37:53  richard
# Temporary measure until we have decent schema migration.
#
# Revision 1.12  2001/07/30 01:24:33  richard
# Handles new node display now.
#
# Revision 1.11  2001/07/29 09:31:35  richard
# oops
#
# Revision 1.10  2001/07/29 09:28:23  richard
# Fixed sorting by clicking on column headings.
#
# Revision 1.9  2001/07/29 08:27:40  richard
# Fixed handling of passed-in values in form elements (ie. during a
# drill-down)
#
# Revision 1.8  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.7  2001/07/29 05:36:14  richard
# Cleanup of the link label generation.
#
# Revision 1.6  2001/07/29 04:06:42  richard
# Fixed problem in link display when Link value is None.
#
# Revision 1.5  2001/07/28 08:17:09  richard
# fixed use of stylesheet
#
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
#
# vim: set filetype=python ts=4 sw=4 et si
