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
# $Id: htmltemplate.py,v 1.112 2002-08-19 00:21:37 richard Exp $

__doc__ = """
Template engine.

Three types of template files exist:
  .index           used by IndexTemplate
  .item            used by ItemTemplate and NewItemTemplate
  .filter          used by IndexTemplate

Templating works by instantiating one of the *Template classes above,
passing in a handle to the cgi client, identifying the class and the
template source directory.

The *Template class reads in the parsed template (parsing and caching
as needed). When the render() method is called, the parse tree is
traversed. Each node is either text (immediately output), a Require
instance (resulting in a call to _test()), a Property instance (treated
differently by .item and .index) or a Diplay instance (resulting in
a call to one of the template_funcs.py functions).

In a .index list, Property tags are used to determine columns, and
disappear before the actual rendering. Note that the template will
be rendered many times in a .index.

In a .item, Property tags check if the node has the property.

Templating is tested by the test_htmltemplate unit test suite. If you add
a template function, add a test for all data types or the angry pink bunny
will hunt you down.
"""
import weakref, os, types, cgi, sys, urllib, re, traceback
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO
try:
    import cPickle as pickle
except ImportError:
    import pickle
from template_parser import RoundupTemplate, Display, Property, Require
from i18n import _
import hyperdb, template_funcs

MTIME = os.path.stat.ST_MTIME

class MissingTemplateError(ValueError):
    '''Error raised when a template file is missing
    '''
    pass

# what a <require> tag results in
def _test(attributes, client, classname, nodeid):
    tests = {}
    for nm, val in attributes:
        tests[nm] = val
    userid = client.db.user.lookup(client.user)
    security = client.db.security
    perms = tests.get('permission', None)
    if perms:
        del tests['permission']
        perms = perms.split(',')
        for value in perms:
            if security.hasPermission(value, userid, classname):
                # just passing the permission is OK
                return 1
    # try the attr conditions until one is met
    if nodeid is None:
        return 0
    if not tests:
        return 0
    for propname, value in tests.items():
        if value == '$userid':
            tests[propname] = userid
    return security.hasNodePermission(classname, nodeid, **tests)

# what a <display> tag results in
def _display(attributes, client, classname, cl, props, nodeid, filterspec=None):
    call = attributes[0][1]    #eg "field('prop2')"
    pos = call.find('(')
    funcnm = call[:pos]
    func = templatefuncs.get(funcnm, None)
    if func:
        argstr = call[pos:]
        args, kws = eval('splitargs'+argstr)
        args = (client, classname, cl, props, nodeid, filterspec) + args
        rslt = func(*args, **kws)
    else:
        rslt = _('no template function %s' % funcnm)
    client.write(rslt)

# what a <property> tag results in    
def _exists(attributes, cl, props, nodeid):
    nm = attributes[0][1]
    if nodeid:
        return cl.get(nodeid, nm)
    return props.get(nm, 0)

class Template:
    ''' base class of all templates.

        knows how to compile & load a template.
        knows how to render one item. '''
    def __init__(self, client, templates, classname):
        if isinstance(client, weakref.ProxyType):
            self.client = client
        else:
            self.client = weakref.proxy(client)
        self.templatedir = templates
        self.compiledtemplatedir = self.templatedir + 'c'
        self.classname = classname
        self.cl = self.client.db.getclass(self.classname)
        self.properties = self.cl.getprops()
        self.template = self._load()
        self.filterspec = None
        self.columns = None
        self.nodeid = None

    def _load(self):
        ''' Load a template from disk and parse it.

            Once parsed, the template is stored as a pickle in the
            "htmlc" directory of the instance. If the file in there is
            newer than the source template file, it's used in preference so
            we don't have to re-parse.
        '''
        # figure where the template source is
        src = os.path.join(self.templatedir, self.classname + self.extension)

        if not os.path.exists(src):
            # hrm, nothing exactly matching what we're after, see if we can
            # fall back on another template
            if hasattr(self, 'fallbackextension'):
                self.extension = self.fallbackextension
                return self._load()
            raise MissingTemplateError, self.classname + self.extension

        # figure where the compiled template should be
        cpl = os.path.join(self.compiledtemplatedir,
            self.classname + self.extension)

        if (not os.path.exists(cpl)
             or os.stat(cpl)[MTIME] < os.stat(src)[MTIME]):
            # there's either no compiled template, or it's out of date
            parser = RoundupTemplate()
            parser.feed(open(src, 'r').read())
            tmplt = parser.structure
            try:
                if not os.path.exists(self.compiledtemplatedir):
                    os.makedirs(self.compiledtemplatedir)
                f = open(cpl, 'wb')
                pickle.dump(tmplt, f)
                f.close()
            except Exception, e:
                print "ouch in pickling: got a %s %r" % (e, e.args)
                pass
        else:
            # load the compiled template
            f = open(cpl, 'rb')
            tmplt = pickle.load(f)
        return tmplt

    def _render(self, tmplt=None, test=_test, display=_display, exists=_exists):
        ''' Render the template
        '''
        if tmplt is None:
            tmplt = self.template

        # go through the list of template "commands"
        for entry in tmplt:
            if isinstance(entry, type('')):
                # string - just write it out
                self.client.write(entry)

            elif isinstance(entry, Require):
                # a <require> tag
                if test(entry.attributes, self.client, self.classname,
                        self.nodeid):
                    # require test passed, render the ok clause
                    self._render(entry.ok)
                elif entry.fail:
                    # if there's a fail clause, render it
                    self._render(entry.fail)

            elif isinstance(entry, Display):
                # execute the <display> function
                display(entry.attributes, self.client, self.classname,
                    self.cl, self.properties, self.nodeid, self.filterspec)

            elif isinstance(entry, Property):
                # do a <property> test
                if self.columns is None:
                    # doing an Item - see if the property is present
                    if exists(entry.attributes, self.cl, self.properties,
                            self.nodeid):
                        self._render(entry.ok)
                # XXX erm, should this be commented out?
                #elif entry.attributes[0][1] in self.columns:
                else:
                    self._render(entry.ok)

class IndexTemplate(Template):
    ''' renders lists of items

        shows filter form (for new queries / to refine queries)
        has clickable column headers (sort by this column / sort reversed)
        has group by lines
        has full text search match lines '''
    extension = '.index'

    def __init__(self, client, templates, classname):
        Template.__init__(self, client, templates, classname)

    def render(self, **kw):
        ''' Render the template - well, wrap the rendering in a try/finally
            so we're guaranteed to clean up after ourselves
        '''
        try:
            self.renderInner(**kw)
        finally:
            self.cl = self.properties = self.client = None
        
    def renderInner(self, filterspec={}, search_text='', filter=[], columns=[], 
            sort=[], group=[], show_display_form=1, nodeids=None,
            show_customization=1, show_nodes=1, pagesize=50, startwith=0,
            simple_search=1, xtracols=None):
        ''' Take all the index arguments and render some HTML
        '''

        self.filterspec = filterspec        
        w = self.client.write
        cl = self.cl
        properties = self.properties
        if xtracols is None:
            xtracols = []

        # XXX deviate from spec here ...
        # load the index section template and figure the default columns from it
        displayable_props = []
        all_columns = []
        for node in self.template:
            if isinstance(node, Property):
                colnm = node.attributes[0][1]
                if properties.has_key(colnm):
                    displayable_props.append(colnm)
                    all_columns.append(colnm)
                elif colnm in xtracols:
                    all_columns.append(colnm)
        if not columns:
            columns = all_columns
        else:
            # re-sort columns to be the same order as displayable_props
            l = []
            for name in all_columns:
                if name in columns:
                    l.append(name)
            columns = l
        self.columns = columns

        # optimize the template
        self.template = self._optimize(self.template)
        
        # display the filter section
        if (show_display_form and
                self.client.instance.FILTER_POSITION.startswith('top')):
            w('<form onSubmit="return submit_once()" action="%s">\n'%
                self.client.classname)
            self.filter_section(search_text, filter, columns, group,
                displayable_props, sort, filterspec, pagesize, startwith,
                simple_search)

        # now display the index section
        w('<table width=100% border=0 cellspacing=0 cellpadding=2>\n')
        w('<tr class="list-header">\n')
        for name in columns:
            cname = name.capitalize()
            if show_display_form and not cname in xtracols:
                sb = self.sortby(name, search_text, filterspec, columns, filter, 
                        group, sort, pagesize)
                anchor = "%s?%s"%(self.client.classname, sb)
                w('<td><span class="list-header"><a href="%s">%s</a>'
                    '</span></td>\n'%(anchor, cname))
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
        if show_nodes:
            matches = None
            if nodeids is None:
                if search_text != '':
                    matches = self.client.db.indexer.search(
                        re.findall(r'\b\w{2,25}\b', search_text), cl)
                nodeids = cl.filter(matches, filterspec, sort, group)
            linecount = 0
            for nodeid in nodeids[startwith:startwith+pagesize]:
                # check for a group heading
                if group_names:
                    this_group = [cl.get(nodeid, name, _('[no value]'))
                        for name in group_names]
                    if this_group != old_group:
                        l = []
                        for name in group_names:
                            prop = properties[name]
                            if isinstance(prop, hyperdb.Link):
                                group_cl = self.client.db.getclass(prop.classname)
                                key = group_cl.getkey()
                                if key is None:
                                    key = group_cl.labelprop()
                                value = cl.get(nodeid, name)
                                if value is None:
                                    l.append(_('[unselected %(classname)s]')%{
                                        'classname': prop.classname})
                                else:
                                    l.append(group_cl.get(value, key))
                            elif isinstance(prop, hyperdb.Multilink):
                                group_cl = self.client.db.getclass(prop.classname)
                                key = group_cl.getkey()
                                for value in cl.get(nodeid, name):
                                    l.append(group_cl.get(value, key))
                            else:
                                value = cl.get(nodeid, name, 
                                    _('[no value]'))
                                if value is None:
                                    value = _('[empty %(name)s]')%locals()
                                else:
                                    value = str(value)
                                l.append(value)
                        w('<tr class="section-bar">'
                        '<td align=middle colspan=%s>'
                        '<strong>%s</strong></td></tr>\n'%(
                            len(columns), ', '.join(l)))
                        old_group = this_group

                # display this node's row
                self.nodeid = nodeid 
                self._render()
                if matches:
                    self.node_matches(matches[nodeid], len(columns))
                self.nodeid = None

        w('</table>\n')
        # the previous and next links
        if nodeids:
            baseurl = self.buildurl(filterspec, search_text, filter,
                columns, sort, group, pagesize)
            if startwith > 0:
                prevurl = '<a href="%s&:startwith=%s">&lt;&lt; '\
                    'Previous page</a>'%(baseurl, max(0, startwith-pagesize)) 
            else:
                prevurl = "" 
            if startwith + pagesize < len(nodeids):
                nexturl = '<a href="%s&:startwith=%s">Next page '\
                    '&gt;&gt;</a>'%(baseurl, startwith+pagesize)
            else:
                nexturl = ""
            if prevurl or nexturl:
                w('''<table width="100%%"><tr>
                      <td width="50%%" align="center">%s</td>
                      <td width="50%%" align="center">%s</td>
                     </tr></table>\n'''%(prevurl, nexturl))

        # display the filter section
        if (show_display_form and hasattr(self.client.instance,
                'FILTER_POSITION') and
                self.client.instance.FILTER_POSITION.endswith('bottom')):
            w('<form onSubmit="return submit_once()" action="%s">\n'%
                self.client.classname)
            self.filter_section(search_text, filter, columns, group,
                displayable_props, sort, filterspec, pagesize, startwith,
                simple_search)

    def _optimize(self, tmplt):
        columns = self.columns
        t = []
        for entry in tmplt:
            if isinstance(entry, Property):
                if entry.attributes[0][1] in columns:
                    t.extend(entry.ok)
            else:
                t.append(entry)
        return t
    
    def buildurl(self, filterspec, search_text, filter, columns, sort, group,
            pagesize):
        d = {'pagesize':pagesize, 'pagesize':pagesize,
             'classname':self.classname}
        if search_text:
            d['searchtext'] = 'search_text=%s&' % search_text
        else:
            d['searchtext'] = ''
        d['filter'] = ','.join(map(urllib.quote,filter))
        d['columns'] = ','.join(map(urllib.quote,columns))
        d['sort'] = ','.join(map(urllib.quote,sort))
        d['group'] = ','.join(map(urllib.quote,group))
        tmp = []
        for col, vals in filterspec.items():
            vals = ','.join(map(urllib.quote,vals))
            tmp.append('%s=%s' % (col, vals))
        d['filters'] = '&'.join(tmp)
        return ('%(classname)s?%(searchtext)s%(filters)s&:sort=%(sort)s&'
                ':filter=%(filter)s&:group=%(group)s&:columns=%(columns)s&'
                ':pagesize=%(pagesize)s'%d)

    def node_matches(self, match, colspan):
        ''' display the files and messages for a node that matched a
            full text search
        '''
        w = self.client.write
        db = self.client.db
        message_links = []
        file_links = []
        if match.has_key('messages'):
            for msgid in match['messages']:
                k = db.msg.labelprop(1)
                lab = db.msg.get(msgid, k)
                msgpath = 'msg%s'%msgid
                message_links.append('<a href="%(msgpath)s">%(lab)s</a>'
                    %locals())
            w(_('<tr class="row-hilite"><td colspan="%s">'
                '&nbsp;&nbsp;Matched messages: %s</td></tr>\n')%(
                    colspan, ', '.join(message_links)))

        if match.has_key('files'):
            for fileid in match['files']:
                filename = db.file.get(fileid, 'name')
                filepath = 'file%s/%s'%(fileid, filename)
                file_links.append('<a href="%(filepath)s">%(filename)s</a>'
                    %locals())
            w(_('<tr class="row-hilite"><td colspan="%s">'
                '&nbsp;&nbsp;Matched files: %s</td></tr>\n')%(
                    colspan, ', '.join(file_links)))

    def filter_form(self, search_text, filter, columns, group, all_columns,
            sort, filterspec, pagesize):
        sortspec = {}
        for i in range(len(sort)):
            mod = ''
            colnm = sort[i]
            if colnm[0] == '-':
                mod = '-'
                colnm = colnm[1:]
            sortspec[colnm] = '%d%s' % (i+1, mod)
            
        startwith = 0
        rslt = []
        w = rslt.append

        # display the filter section
        w(  '<br>')
        w(  '<table border=0 cellspacing=0 cellpadding=1>')
        w(  '<tr class="list-header">')
        w(_(' <th align="left" colspan="7">Filter specification...</th>'))
        w(  '</tr>')
        # see if we have any indexed properties
        if self.client.classname in self.client.db.config.HEADER_SEARCH_LINKS:
            w('<tr class="location-bar">')
            w(' <td align="right" class="form-label"><b>Search Terms</b></td>')
            w(' <td colspan=6 class="form-text">&nbsp;&nbsp;&nbsp;'
              '<input type="text"name="search_text" value="%s" size="50">'
              '</td>'%search_text)
            w('</tr>')
        w(  '<tr class="location-bar">')
        w(  ' <th align="center" width="20%">&nbsp;</th>')
        w(_(' <th align="center" width="10%">Show</th>'))
        w(_(' <th align="center" width="10%">Group</th>'))
        w(_(' <th align="center" width="10%">Sort</th>'))
        w(_(' <th colspan="3" align="center">Condition</th>'))
        w(  '</tr>')

        properties =  self.client.db.getclass(self.classname).getprops()       
        all_columns = properties.keys()
        all_columns.sort()
        for nm in all_columns:
            propdescr = properties.get(nm, None)
            if not propdescr:
                print "hey sysadmin - %s is not a property of %r" % (nm, self.classname)
                continue
            w(  '<tr class="location-bar">')
            w(_(' <td align="right" class="form-label"><b>%s</b></td>' % nm.capitalize()))
            # show column - can't show multilinks
            if isinstance(propdescr, hyperdb.Multilink):
                w(' <td></td>')
            else:
                checked = columns and nm in columns or 0
                checked = ('', 'checked')[checked]
                w(' <td align="center" class="form-text"><input type="checkbox" name=":columns"'
                  'value="%s" %s></td>' % (nm, checked) )
            # can only group on Link 
            if isinstance(propdescr, hyperdb.Link):
                checked = group and nm in group or 0
                checked = ('', 'checked')[checked]
                w(' <td align="center" class="form-text"><input type="checkbox" name=":group"'
                  'value="%s" %s></td>' % (nm, checked) )
            else:
                w(' <td></td>')
            # sort - no sort on Multilinks
            if isinstance(propdescr, hyperdb.Multilink):
                w('<td></td>')
            else:
                val = sortspec.get(nm, '')
                w('<td align="center" class="form-text"><input type="text" name=":%s_ss" size="3"'
                  'value="%s"></td>' % (nm,val))
            # condition
            val = ''
            if isinstance(propdescr, hyperdb.Link):
                op = "is in&nbsp;"
                xtra = '<a href="javascript:help_window(\'classhelp?classname=%s&properties=id,%s\', \'200\', \'400\')"><b>(list)</b></a>' \
                       % (propdescr.classname, self.client.db.getclass(propdescr.classname).labelprop())
                val = ','.join(filterspec.get(nm, ''))
            elif isinstance(propdescr, hyperdb.Multilink):
                op = "contains&nbsp;"
                xtra = '<a href="javascript:help_window(\'classhelp?classname=%s&properties=id,%s\', \'200\', \'400\')"><b>(list)</b></a>' \
                       % (propdescr.classname, self.client.db.getclass(propdescr.classname).labelprop())
                val = ','.join(filterspec.get(nm, ''))
            elif isinstance(propdescr, hyperdb.String) and nm != 'id':
                op = "equals&nbsp;"
                xtra = ""
                val = filterspec.get(nm, '')
            elif isinstance(propdescr, hyperdb.Boolean):
                op = "is&nbsp;"
                xtra = ""
                val = filterspec.get(nm, None)
                if val is not None:
                    val = 'True' and val or 'False'
                else:
                    val = ''
            elif isinstance(propdescr, hyperdb.Number):
                op = "equals&nbsp;"
                xtra = ""
                val = str(filterspec.get(nm, ''))
            else:
                w('<td></td><td></td><td></td></tr>')
                continue
            checked = filter and nm in filter or 0
            checked = ('', 'checked')[checked]
            w(  ' <td class="form-text"><input type="checkbox" name=":filter" value="%s" %s></td>' \
                % (nm, checked))
            w(_(' <td class="form-label" nowrap>%s</td><td class="form-text" nowrap>'
                '<input type="text" name=":%s_fs" value="%s" size=50>%s</td>' % (op, nm, val, xtra)))
            w(  '</tr>')
        w('<tr class="location-bar">')
        w(' <td colspan=7><hr></td>')
        w('</tr>')
        w('<tr class="location-bar">')
        w(_(' <td align="right" class="form-label">Pagesize</td>'))
        w(' <td colspan=2 align="center" class="form-text"><input type="text" name=":pagesize"'
          'size="3" value="%s"></td>' % pagesize)
        w(' <td colspan=4></td>')
        w('</tr>')
        w('<tr class="location-bar">')
        w(_(' <td align="right" class="form-label">Start With</td>'))
        w(' <td colspan=2 align="center" class="form-text"><input type="text" name=":startwith"'
          'size="3" value="%s"></td>' % startwith)
        w(' <td colspan=3></td>')
        w(' <td></td>')
        w('</tr>')
        w('<input type=hidden name=":advancedsearch" value="1">')

        return '\n'.join(rslt)
    
    def simple_filter_form(self, search_text, filter, columns, group, all_columns,
            sort, filterspec, pagesize):
        
        startwith = 0
        rslt = []
        w = rslt.append

        # display the filter section
        w(  '<br>')
        w(  '<table border=0 cellspacing=0 cellpadding=1>')
        w(  '<tr class="list-header">')
        w(_(' <th align="left" colspan="7">Query modifications...</th>'))
        w(  '</tr>')

        if group:
            selectedgroup = group[0]
            groupopts = ['<select name=":group">','<option value="">--no selection--</option>']
        else:
            selectedgroup = None
            groupopts = ['<select name=":group">','<option value="" selected>--no selection--</option>']
        descending = 0
        if sort:
            selectedsort = sort[0]
            if selectedsort[0] == '-':
                selectedsort = selectedsort[1:]
                descending = 1
            sortopts = ['<select name=":sort">', '<option value="">--no selection--</option>']
        else:
            selectedsort = None
            sortopts = ['<select name=":sort">', '<option value="" selected>--no selection--</option>']
            
        for nm in all_columns:
            propdescr = self.client.db.getclass(self.client.classname).getprops().get(nm, None)
            if not propdescr:
                print "hey sysadmin - %s is not a property of %r" % (nm, self.classname)
                continue
            if isinstance(propdescr, hyperdb.Link):
                selected = ''
                if nm == selectedgroup:
                    selected = 'selected'
                groupopts.append('<option value="%s" %s>%s</option>' % (nm, selected, nm.capitalize()))
            selected = ''
            if nm == selectedsort:
                selected = 'selected'
            sortopts.append('<option value="%s" %s>%s</option>' % (nm, selected, nm.capitalize()))
        if len(groupopts) > 2:
            groupopts.append('</select>')
            groupopts = '\n'.join(groupopts)
            w('<tr class="location-bar">')
            w(' <td align="right" class="form-label"><b>Group</b></td>')
            w(' <td class="form-text">%s</td>' % groupopts)
            w('</tr>')
        if len(sortopts) > 2:
            sortopts.append('</select>')
            sortopts = '\n'.join(sortopts)
            w('<tr class="location-bar">')
            w(' <td align="right" class="form-label"><b>Sort</b></td>')
            checked = descending and 'checked' or ''
            w(' <td class="form-text">%s&nbsp;<span class="form-label">Descending</span>'
              '<input type=checkbox name=":descending" value="1" %s></td>' % (sortopts, checked))
            w('</tr>')
        w('<input type=hidden name="search_text" value="%s">' % urllib.quote(search_text))
        w('<input type=hidden name=":filter" value="%s">' % ','.join(filter))
        w('<input type=hidden name=":columns" value="%s">' % ','.join(columns))
        for nm in filterspec.keys():
            w('<input type=hidden name=":%s_fs" value="%s">' % (nm, ','.join(filterspec[nm])))
        w('<input type=hidden name=":pagesize" value="%s">' % pagesize)            
        
        return '\n'.join(rslt)

    def filter_section(self, search_text, filter, columns, group, all_columns,
            sort, filterspec, pagesize, startwith, simpleform=1):
        w = self.client.write
        if simpleform:
            w(self.simple_filter_form(search_text, filter, columns, group,
                all_columns, sort, filterspec, pagesize))
        else:
            w(self.filter_form(search_text, filter, columns, group, all_columns,
                sort, filterspec, pagesize))
        w(' <tr class="location-bar">\n')
        w('  <td colspan=7><hr></td>\n')
        w(' </tr>\n')
        w(' <tr class="location-bar">\n')
        w('  <td>&nbsp;</td>\n')
        w('  <td colspan=6><input type="submit" name="Query" value="Redisplay"></td>\n')
        w(' </tr>\n')
        if (not simpleform 
            and self.client.db.getclass('user').getprops().has_key('queries')
            and not self.client.user in (None, "anonymous")):
            w(' <tr class="location-bar">\n')
            w('  <td colspan=7><hr></td>\n')
            w(' </tr>\n')
            w(' <tr class="location-bar">\n')
            w('  <td align=right class="form-label">Name</td>\n')
            w('  <td colspan=2 class="form-text"><input type="text" name=":name" value=""></td>\n')
            w('  <td colspan=4 rowspan=2 class="form-help">If you give the query a name '
              'and click <b>Save</b>, it will appear on your menu. Saved queries may be '
              'edited by going to <b>My Details</b> and clicking on the query name.</td>')
            w(' </tr>\n')
            w(' <tr class="location-bar">\n')
            w('  <td>&nbsp;</td><input type="hidden" name=":classname" value="%s">\n' % self.classname)
            w('  <td colspan=2><input type="submit" name="Query" value="Save"></td>\n')
            w(' </tr>\n')
        w('</table>\n')

    def sortby(self, sort_name, search_text, filterspec, columns, filter,
            group, sort, pagesize):
        ''' Figure the link for a column heading so we can sort by that
            column
        '''
        l = []
        w = l.append
        if search_text:
            w('search_text=%s' % search_text)
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
        w(':pagesize=%s' % pagesize)
        w(':startwith=0')

        # handle the sorting - if we're already sorting by this column,
        # then reverse the sorting, otherwise set the sorting to be this
        # column only
        sorting = None
        if len(sort) == 1:
            name = sort[0]
            dir = name[0]
            if dir == '-' and name[1:] == sort_name:
                sorting = ':sort=%s'%sort_name
            elif name == sort_name:
                sorting = ':sort=-%s'%sort_name
        if sorting is None:
            sorting = ':sort=%s'%sort_name
        w(sorting)

        return '&'.join(l)

class ItemTemplate(Template):
    ''' show one node as a form '''    
    extension = '.item'
    def __init__(self, client, templates, classname):
        Template.__init__(self, client, templates, classname)
        self.nodeid = client.nodeid
    def render(self, nodeid):
        try:
            cl = self.cl
            properties = self.properties
            if (properties.has_key('type') and
                    properties.has_key('content')):
                pass
                # XXX we really want to return this as a downloadable...
                #  currently I handle this at a higher level by detecting 'file'
                #  designators...

            w = self.client.write
            w('<form onSubmit="return submit_once()" action="%s%s" '
                'method="POST" enctype="multipart/form-data">'%(self.classname,
                nodeid))
            try:
                self._render()
            except:
                # make sure we don't commit any changes
                self.client.db.rollback()
                s = StringIO.StringIO()
                traceback.print_exc(None, s)
                w('<pre class="system-msg">%s</pre>'%cgi.escape(s.getvalue()))
            w('</form>')
        finally:
            self.cl = self.properties = self.client = None

class NewItemTemplate(Template):
    ''' display a form for creating a new node '''
    extension = '.newitem'
    fallbackextension = '.item'
    def __init__(self, client, templates, classname):
        Template.__init__(self, client, templates, classname)
    def render(self, form):
        try:
            self.form = form
            w = self.client.write
            c = self.client.classname
            w('<form onSubmit="return submit_once()" action="new%s" '
                'method="POST" enctype="multipart/form-data">'%c)
            for key in form.keys():
                if key[0] == ':':
                    value = form[key].value
                    if type(value) != type([]): value = [value]
                    for value in value:
                        w('<input type="hidden" name="%s" value="%s">'%(key,
                            value))
            self._render()
            w('</form>')
        finally:
            self.cl = self.properties = self.client = None

def splitargs(*args, **kws):
    return args, kws
#  [('permission', 'perm2,perm3'), ('assignedto', '$userid'), ('status', 'open')]

templatefuncs = {}
for nm in template_funcs.__dict__.keys():
    if nm.startswith('do_'):
        templatefuncs[nm[3:]] = getattr(template_funcs, nm)

#
# $Log: not supported by cvs2svn $
# Revision 1.111  2002/08/15 00:40:10  richard
# cleanup
#
# Revision 1.110  2002/08/13 20:16:09  gmcm
# Use a real parser for templates.
# Rewrite htmltemplate to use the parser (hack, hack).
# Move the "do_XXX" methods to template_funcs.py.
# Redo the funcion tests (but not Template tests - they're hopeless).
# Simplified query form in cgi_client.
# Ability to delete msgs, files, queries.
# Ability to edit the metadata on files.
#
# Revision 1.109  2002/08/01 15:06:08  gmcm
# Use same regex to split search terms as used to index text.
# Fix to back_metakit for not changing journaltag on reopen.
# Fix htmltemplate's do_link so [No <whatever>] strings are href'd.
# Fix bogus "nosy edited ok" msg - the **d syntax does NOT share d between caller and callee.
#
# Revision 1.108  2002/07/31 22:40:50  gmcm
# Fixes to the search form and saving queries.
# Fixes to  sorting in back_metakit.py.
#
# Revision 1.107  2002/07/30 05:27:30  richard
# nicer error messages, and a bugfix
#
# Revision 1.106  2002/07/30 02:41:04  richard
# Removed the confusing, ugly two-column sorting stuff. Column heading clicks
# now only sort on one column. Nice and simple and obvious.
#
# Revision 1.105  2002/07/26 08:26:59  richard
# Very close now. The cgi and mailgw now use the new security API. The two
# templates have been migrated to that setup. Lots of unit tests. Still some
# issue in the web form for editing Roles assigned to users.
#
# Revision 1.104  2002/07/25 07:14:05  richard
# Bugger it. Here's the current shape of the new security implementation.
# Still to do:
#  . call the security funcs from cgi and mailgw
#  . change shipped templates to include correct initialisation and remove
#    the old config vars
# ... that seems like a lot. The bulk of the work has been done though. Honest :)
#
# Revision 1.103  2002/07/20 19:29:10  gmcm
# Fixes/improvements to the search form & saved queries.
#
# Revision 1.102  2002/07/18 23:07:08  richard
# Unit tests and a few fixes.
#
# Revision 1.101  2002/07/18 11:17:30  gmcm
# Add Number and Boolean types to hyperdb.
# Add conversion cases to web, mail & admin interfaces.
# Add storage/serialization cases to back_anydbm & back_metakit.
#
# Revision 1.100  2002/07/18 07:01:54  richard
# minor bugfix
#
# Revision 1.99  2002/07/17 12:39:10  gmcm
# Saving, running & editing queries.
#
# Revision 1.98  2002/07/10 00:17:46  richard
#  . added sorting of checklist HTML display
#
# Revision 1.97  2002/07/09 05:20:09  richard
#  . added email display function - mangles email addrs so they're not so easily
#    scraped from the web
#
# Revision 1.96  2002/07/09 04:19:09  richard
# Added reindex command to roundup-admin.
# Fixed reindex on first access.
# Also fixed reindexing of entries that change.
#
# Revision 1.95  2002/07/08 15:32:06  gmcm
# Pagination of index pages.
# New search form.
#
# Revision 1.94  2002/06/27 15:38:53  gmcm
# Fix the cycles (a clear method, called after render, that removes
# the bound methods from the globals dict).
# Use cl.filter instead of cl.list followed by sortfunc. For some
# backends (Metakit), filter can sort at C speeds, cutting >10 secs
# off of filling in the <select...> box for assigned_to when you
# have 600+ users.
#
# Revision 1.93  2002/06/27 12:05:25  gmcm
# Default labelprops to id.
# In history, make sure there's a .item before making a link / multilink into an href.
# Also in history, cgi.escape String properties.
# Clean up some of the reference cycles.
#
# Revision 1.92  2002/06/11 04:57:04  richard
# Added optional additional property to display in a Multilink form menu.
#
# Revision 1.91  2002/05/31 00:08:02  richard
# can now just display a link/multilink id - useful for stylesheet stuff
#
# Revision 1.90  2002/05/25 07:16:24  rochecompaan
# Merged search_indexing-branch with HEAD
#
# Revision 1.89  2002/05/15 06:34:47  richard
# forgot to fix the templating for last change
#
# Revision 1.88  2002/04/24 08:34:35  rochecompaan
# Sorting was applied to all nodes of the MultiLink class instead of
# the nodes that are actually linked to in the "field" template
# function.  This adds about 20+ seconds in the display of an issue if
# your database has a 1000 or more issue in it.
#
# Revision 1.87  2002/04/03 06:12:46  richard
# Fix for date properties as labels.
#
# Revision 1.86  2002/04/03 05:54:31  richard
# Fixed serialisation problem by moving the serialisation step out of the
# hyperdb.Class (get, set) into the hyperdb.Database.
#
# Also fixed htmltemplate after the showid changes I made yesterday.
#
# Unit tests for all of the above written.
#
# Revision 1.85  2002/04/02 01:40:58  richard
#  . link() htmltemplate function now has a "showid" option for links and
#    multilinks. When true, it only displays the linked node id as the anchor
#    text. The link value is displayed as a tooltip using the title anchor
#    attribute.
#
# Revision 1.84.2.2  2002/04/20 13:23:32  rochecompaan
# We now have a separate search page for nodes.  Search links for
# different classes can be customized in instance_config similar to
# index links.
#
# Revision 1.84.2.1  2002/04/19 19:54:42  rochecompaan
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
# Revision 1.84  2002/03/29 19:41:48  rochecompaan
#  . Fixed display of mutlilink properties when using the template
#    functions, menu and plain.
#
# Revision 1.83  2002/02/27 04:14:31  richard
# Ran it through pychecker, made fixes
#
# Revision 1.82  2002/02/21 23:11:45  richard
#  . fixed some problems in date calculations (calendar.py doesn't handle over-
#    and under-flow). Also, hour/minute/second intervals may now be more than
#    99 each.
#
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

