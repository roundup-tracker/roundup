#-*- encoding: utf8 -*-

import unittest, os, pprint, difflib, textwrap

from roundup.init import loadTemplateInfo


class TemplateInfoTestCase(unittest.TestCase):
    def testLoadTemplateInfo(self):
        path = os.path.join(os.path.dirname(__file__),
                            '../share/roundup/templates/classic')
        self.maxDiff = None
        self.assertEqual(
            loadTemplateInfo(path),
            {
              'description': textwrap.dedent('''\
                   This is a generic issue tracker that may be used to track bugs,
                                feature requests, project issues or any number of other types
                                of issues. Most users of Roundup will find that this template
                                suits them, with perhaps a few customisations.'''),
              'intended-for': 'All first-time Roundup users',
              'name': 'classic',
              'path': path
            }
        )

# vim: set et sts=4 sw=4 :
