import unittest, time

from roundup.date import Date, Interval

class DateTestCase(unittest.TestCase):
    def testDateInterval(self):
        date = Date("2000-06-26.00:34:02 + 2d")
        self.assertEqual(str(date), '2000-06-28.00:34:02')
        date = Date("2000-02-27 + 2d")
        self.assertEqual(str(date), '2000-02-29.00:00:00')
        date = Date("2001-02-27 + 2d")
        self.assertEqual(str(date), '2001-03-01.00:00:00')

    def testDate(self):
        date = Date("2000-04-17")
        self.assertEqual(str(date), '2000-04-17.00:00:00')
        date = Date("01-25")
        y, m, d, x, x, x, x, x, x = time.gmtime()
        self.assertEqual(str(date), '%s-01-25.00:00:00'%y)
        date = Date("2000-04-17.03:45")
        self.assertEqual(str(date), '2000-04-17.03:45:00')
        date = Date("08-13.22:13")
        self.assertEqual(str(date), '%s-08-13.22:13:00'%y)
        date = Date("11-07.09:32:43")
        self.assertEqual(str(date), '%s-11-07.09:32:43'%y)
        date = Date("14:25")
        self.assertEqual(str(date), '%s-%02d-%02d.14:25:00'%(y, m, d))
        date = Date("8:47:11")
        self.assertEqual(str(date), '%s-%02d-%02d.08:47:11'%(y, m, d))

    def testOffset(self):
        date = Date("2000-04-17", -5)
        self.assertEqual(str(date), '2000-04-17.00:00:00')
        date = Date("01-25", -5)
        y, m, d, x, x, x, x, x, x = time.gmtime()
        self.assertEqual(str(date), '%s-01-25.00:00:00'%y)
        date = Date("2000-04-17.03:45", -5)
        self.assertEqual(str(date), '2000-04-17.08:45:00')
        date = Date("08-13.22:13", -5)
        self.assertEqual(str(date), '%s-08-14.03:13:00'%y)
        date = Date("11-07.09:32:43", -5)
        self.assertEqual(str(date), '%s-11-07.14:32:43'%y)
        date = Date("14:25", -5)
        self.assertEqual(str(date), '%s-%02d-%02d.19:25:00'%(y, m, d))
        date = Date("8:47:11", -5)
        self.assertEqual(str(date), '%s-%02d-%02d.13:47:11'%(y, m, d))

    def testInterval(self):
        pass

def suite():
   return unittest.makeSuite(DateTestCase, 'test')

