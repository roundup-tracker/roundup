import unittest

from roundup.support import wrap

class WrapTestCase(unittest.TestCase):
    def testWrap(self):
        lorem = '''Lorem ipsum dolor sit amet, consectetuer adipiscing elit.'''
        wrapped = '''Lorem ipsum dolor
sit amet,
consectetuer
adipiscing elit.'''
        self.assertEquals(wrap(lorem, 20), wrapped)

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(WrapTestCase))
    return suite
