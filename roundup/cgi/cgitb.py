#
# This module was written by Ka-Ping Yee, <ping@lfw.org>.
#
# $Id: cgitb.py,v 1.12 2004-07-13 10:18:00 a1s Exp $

"""Extended CGI traceback handler by Ka-Ping Yee, <ping@lfw.org>.
"""
__docformat__ = 'restructuredtext'

import sys, os, types, string, keyword, linecache, tokenize, inspect, cgi
import pydoc, traceback

from roundup.cgi import templating, TranslationService

def get_translator(i18n=None):
    """Return message translation function (gettext)

    Parameters:
        i18n - translation service, such as roundup.i18n module
            or TranslationService object.

    Return ``gettext`` attribute of the ``i18n`` object, if available
    (must be a message translation function with one argument).
    If ``gettext`` cannot be obtained from ``i18n``, take default
    TranslationService.

    """
    try:
        return i18n.gettext
    except:
        return TranslationService.get_translation().gettext

def breaker():
    return ('<body bgcolor="white">' +
            '<font color="white" size="-5"> > </font> ' +
            '</table>' * 5)

def niceDict(indent, dict):
    l = []
    for k,v in dict.items():
        l.append('<tr><td><strong>%s</strong></td><td>%s</td></tr>'%(k,
            cgi.escape(repr(v))))
    return '\n'.join(l)

def pt_html(context=5, i18n=None):
    _ = get_translator(i18n)
    esc = cgi.escape
    exc_info = [esc(str(value)) for value in sys.exc_info()[:2]]
    l = [_('<h1>Templating Error</h1>\n'
            '<p><b>%(exc_type)s</b>: %(exc_value)s</p>\n'
            '<p class="help">Debugging information follows</p>'
         ) % {'exc_type': exc_info[0], 'exc_value': exc_info[1]},
         '<ol>',]
    from roundup.cgi.PageTemplates.Expressions import TraversalError
    t = inspect.trace(context)
    t.reverse()
    for frame, file, lnum, func, lines, index in t:
        args, varargs, varkw, locals = inspect.getargvalues(frame)
        if locals.has_key('__traceback_info__'):
            ti = locals['__traceback_info__']
            if isinstance(ti, TraversalError):
                s = []
                for name, info in ti.path:
                    s.append(_('<li>"%(name)s" (%(info)s)</li>')
                        % {'name': name, 'info': esc(repr(info))})
                s = '\n'.join(s)
                l.append(_('<li>Looking for "%(name)s", '
                    'current path:<ol>%(path)s</ol></li>'
                ) % {'name': ti.name, 'path': s})
            else:
                l.append(_('<li>In %s</li>') % esc(str(ti)))
        if locals.has_key('__traceback_supplement__'):
            ts = locals['__traceback_supplement__']
            if len(ts) == 2:
                supp, context = ts
                s = _('A problem occurred in your template "%s".') \
                    % str(context.id)
                if context._v_errors:
                    s = s + '<br>' + '<br>'.join(
                        [esc(x) for x in context._v_errors])
                l.append('<li>%s</li>'%s)
            elif len(ts) == 3:
                supp, context, info = ts
                l.append(_('''
<li>While evaluating the %(info)r expression on line %(line)d
<table class="otherinfo" style="font-size: 90%%">
 <tr><th colspan="2" class="header">Current variables:</th></tr>
 %(globals)s
 %(locals)s
</table></li>
''') % {
    'info': info,
    'line': context.position[0],
    'globals': niceDict('    ', context.global_vars),
    'locals': niceDict('    ', context.local_vars)
})

    l.append('''
</ol>
<table style="font-size: 80%%; color: gray">
 <tr><th class="header" align="left">%s</th></tr>
 <tr><td><pre>%s</pre></td></tr>
</table>''' % (_('Full traceback:'), cgi.escape(''.join(
        traceback.format_exception(*sys.exc_info())
    ))))
    l.append('<p>&nbsp;</p>')
    return '\n'.join(l)

def html(context=5, i18n=None):
    _ = get_translator(i18n)
    etype, evalue = sys.exc_type, sys.exc_value
    if type(etype) is types.ClassType:
        etype = etype.__name__
    pyver = 'Python ' + string.split(sys.version)[0] + '<br>' + sys.executable
    head = pydoc.html.heading(
        _('<font size=+1><strong>%(exc_type)s</strong>: %(exc_value)s</font>')
        % {'exc_type': etype, 'exc_value': evalue},
        '#ffffff', '#777777', pyver)

    head = head + (_('<p>A problem occurred while running a Python script. '
                   'Here is the sequence of function calls leading up to '
                   'the error, with the most recent (innermost) call first. '
                   'The exception attributes are:'))

    indent = '<tt><small>%s</small>&nbsp;</tt>' % ('&nbsp;' * 5)
    traceback = []
    for frame, file, lnum, func, lines, index in inspect.trace(context):
        if file is None:
            link = _("&lt;file is None - probably inside <tt>eval</tt> "
                "or <tt>exec</tt>&gt;")
        else:
            file = os.path.abspath(file)
            link = '<a href="file:%s">%s</a>' % (file, pydoc.html.escape(file))
        args, varargs, varkw, locals = inspect.getargvalues(frame)
        if func == '?':
            call = ''
        else:
            call = _('in <strong>%s</strong>') % func + inspect.formatargvalues(
                    args, varargs, varkw, locals,
                    formatvalue=lambda value: '=' + pydoc.html.repr(value))

        level = '''
<table width="100%%" bgcolor="#dddddd" cellspacing=0 cellpadding=2 border=0>
<tr><td>%s %s</td></tr></table>''' % (link, call)

        if index is None or file is None:
            traceback.append('<p>' + level)
            continue

        # do a file inspection
        names = []
        def tokeneater(type, token, start, end, line, names=names):
            if type == tokenize.NAME and token not in keyword.kwlist:
                if token not in names:
                    names.append(token)
            if type == tokenize.NEWLINE: raise IndexError
        def linereader(file=file, lnum=[lnum]):
            line = linecache.getline(file, lnum[0])
            lnum[0] = lnum[0] + 1
            return line

        try:
            tokenize.tokenize(linereader, tokeneater)
        except IndexError:
            pass
        lvals = []
        for name in names:
            if name in frame.f_code.co_varnames:
                if locals.has_key(name):
                    value = pydoc.html.repr(locals[name])
                else:
                    value = _('<em>undefined</em>')
                name = '<strong>%s</strong>' % name
            else:
                if frame.f_globals.has_key(name):
                    value = pydoc.html.repr(frame.f_globals[name])
                else:
                    value = _('<em>undefined</em>')
                name = '<em>global</em> <strong>%s</strong>' % name
            lvals.append('%s&nbsp;= %s'%(name, value))
        if lvals:
            lvals = string.join(lvals, ', ')
            lvals = indent + '<small><font color="#909090">%s'\
                '</font></small><br>'%lvals
        else:
            lvals = ''

        excerpt = []
        i = lnum - index
        for line in lines:
            number = '&nbsp;' * (5-len(str(i))) + str(i)
            number = '<small><font color="#909090">%s</font></small>' % number
            line = '<tt>%s&nbsp;%s</tt>' % (number, pydoc.html.preformat(line))
            if i == lnum:
                line = '''
<table width="100%%" bgcolor="white" cellspacing=0 cellpadding=0 border=0>
<tr><td>%s</td></tr></table>''' % line
            excerpt.append('\n' + line)
            if i == lnum:
                excerpt.append(lvals)
            i = i + 1
        traceback.append('<p>' + level + string.join(excerpt, '\n'))

    traceback.reverse()

    exception = '<p><strong>%s</strong>: %s' % (str(etype), str(evalue))
    attribs = []
    if type(evalue) is types.InstanceType:
        for name in dir(evalue):
            value = pydoc.html.repr(getattr(evalue, name))
            attribs.append('<br>%s%s&nbsp;= %s' % (indent, name, value))

    return head + string.join(attribs) + string.join(traceback) + '<p>&nbsp;</p>'

def handler():
    print breaker()
    print html()

# vim: set filetype=python ts=4 sw=4 et si :
