import unittest, StringIO

from roundup import rlog

class LoggingTestCase(unittest.TestCase):
    def setUp(self):
        self.logging = rlog.BasicLogging()
        self.file = StringIO.StringIO()
        self.logging.setFile(self.file)
    def testLevels(self):
        logger = self.logging.getLogger('test')
        v1 = self.file.getvalue()
        logger.debug('test')
        v2 = self.file.getvalue()
        self.assertEqual(v1, v2, 'Logged when should not have')

        v1 = self.file.getvalue()
        logger.info('test')
        v2 = self.file.getvalue()
        self.assertNotEqual(v1, v2, 'Nothing logged')

        v1 = self.file.getvalue()
        logger.warning('test')
        v2 = self.file.getvalue()
        self.assertNotEqual(v1, v2, 'Nothing logged')

        v1 = self.file.getvalue()
        logger.error('test')
        v2 = self.file.getvalue()
        self.assertNotEqual(v1, v2, 'Nothing logged')

        v1 = self.file.getvalue()
        try:
            1/0
        except:
            logger.exception('test')
        v2 = self.file.getvalue()
        self.assertNotEqual(v1, v2, 'Nothing logged')

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(LoggingTestCase))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

