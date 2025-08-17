"""Random tests for anypy modules"""


import unittest
from roundup.anypy.strings import repr_export, eval_import
from roundup.anypy.cmp_ import _test

import sys
_py3 = sys.version_info[0] > 2

class StringsTest(unittest.TestCase):

    def test_import_params(self):
        """ issue2551170 - handle long int in history/journal
            params tuple
        """
        # python2 export with id as number
        val = eval_import("('issue', 2345L, 'status')")
        self.assertSequenceEqual(val, ('issue', 2345, 'status'))

        # eval a tuple e.g. date representation
        val = eval_import("(2022, 9, 6, 3, 58, 4.776, 0, 0, 0)")
        self.assertSequenceEqual(val, (2022, 9, 6, 3, 58, 4.776, 0, 0, 0))

        # eval a boolean
        val = eval_import("False")
        self.assertEqual(val, False)
        val = eval_import("True")
        self.assertEqual(val, True)

        # check syntax error
        for testcase in ['true', '(2004, 10, 20', "2000, 10, 22)",
                         "test'", '"test']:
            with self.assertRaises(ValueError) as m:
                val = eval_import(testcase)
            print(m.exception)

        # python3 export with id as number
        val = eval_import("('issue', 2345, 'status')")
        self.assertSequenceEqual(val, ('issue', 2345, 'status'))

        # python2 or python3 export with id as string
        val = eval_import("('issue', '2345', 'status')")
        self.assertSequenceEqual(val, ('issue', '2345', 'status'))

    def test_export_params(self):
        """ issue2551170 - handle long int in history/journal
            params tuple
        """
        # python2 export with id as number
        if _py3:
            val = repr_export(('issue', 2345, 'status'))
            self.assertEqual(val, "('issue', 2345, 'status')")
        else:
            val = repr_export(('issue', long(2345), 'status'))
            self.assertEqual(val, "('issue', 2345L, 'status')")

        # python2 or python3 export with id as string
        val = repr_export(('issue', '2345', 'status'))
        self.assertEqual(val, "('issue', '2345', 'status')")
            
class MiscTest(unittest.TestCase):

    def test_cmp_(self):
        _test()
