"""
In Python 3, sometimes TAL "python:" expressions that refer to
variables but not all variables are recognized. That is in Python 2.7
all variables used in a TAL "python:" expression are recognized as
references. In Python 3.5 (perhaps earlier), some TAL "python:"
expressions refer to variables but the reference generates an error
like this:

<class 'NameError'>: name 'some_tal_variable' is not defined

even when the variable is defined. Output after this message lists the
variable and its value.
"""

import unittest

from roundup.cgi.PageTemplates.PythonExpr import PythonExpr as PythonExprClass

class ExprTest(unittest.TestCase):
    def testExpr(self):
        expr = '[x for x in context.assignedto ' \
               'if x.realname not in user_realnames]'
        pe = PythonExprClass('test', expr, None)
        # Looking at the expression, only context and user_realnames are
        # external variables. The names assignedto and realname are members,
        # and x is local.
        required_names = ['context', 'user_realnames']
        got_names = pe._f_varnames
        for required_name in required_names:
            self.assertIn(required_name, got_names)
