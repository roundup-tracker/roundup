"""Random tests for anypy modules"""


import unittest
from roundup.anypy.strings import repr_export, eval_import

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
            
