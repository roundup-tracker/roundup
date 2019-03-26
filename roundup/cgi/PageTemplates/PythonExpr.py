##############################################################################
#
# Copyright (c) 2001 Zope Corporation and Contributors. All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
#
##############################################################################
# Modified for Roundup:
# 
# 1. more informative traceback info

"""Generic Python Expression Handler
"""

import symtable

from .TALES import CompilerError
from sys import exc_info

class getSecurityManager:
    '''Null security manager'''
    def validate(self, *args, **kwargs):
        return 1
    addContext = removeContext = validateValue = validate

class PythonExpr:
    def __init__(self, name, expr, engine):
        self.expr = expr = expr.strip().replace('\n', ' ')
        try:
            d = {}
            self.f_code = 'def f():\n return %s\n' % expr.strip()
            exec(self.f_code, d)
            self._f = d['f']
        except:
            raise CompilerError(('Python expression error:\n'
                                 '%s: %s') % exc_info()[:2])
        self._get_used_names()

    def _get_used_names(self):
        self._f_varnames = vnames = []
        for vname in self._get_from_symtab():
            if vname[0] not in '$_.':
                vnames.append(vname)

    def _get_from_symtab(self):
        """
        Get the variables used in the 'f' function.
        """
        variables = set()
        table = symtable.symtable(self.f_code, "<string>", "exec")
        if table.has_children():
            variables.update(self._walk_children(table))
        return variables

    def _walk_children(self, sym):
        """
        Get the variables at this level. Recurse to get them all.
        """
        variables = set()
        for child in sym.get_children():
            variables.update(set(child.get_identifiers()))
            if child.has_children():
                variables.update(self._walk_children(child))
        return variables

    def _bind_used_names(self, econtext, _marker=[]):
        # Bind template variables
        names = {'CONTEXTS': econtext.contexts}
        variables = econtext.vars
        getType = econtext.getCompiler().getTypes().get
        for vname in self._f_varnames:
            val = variables.get(vname, _marker)
            if val is _marker:
                has = val = getType(vname)
                if has:
                    val = ExprTypeProxy(vname, val, econtext)
                    names[vname] = val
            else:
                names[vname] = val
        return names

    def __call__(self, econtext):
        __traceback_info__ = 'python expression "%s"'%self.expr
        f = self._f
        f.__globals__.update(self._bind_used_names(econtext))
        return f()

    def __str__(self):
        return 'Python expression "%s"' % self.expr
    def __repr__(self):
        return '<PythonExpr %s>' % self.expr

class ExprTypeProxy:
    '''Class that proxies access to an expression type handler'''
    def __init__(self, name, handler, econtext):
        self._name = name
        self._handler = handler
        self._econtext = econtext
    def __call__(self, text):
        return self._handler(self._name, text,
                             self._econtext.getCompiler())(self._econtext)

