# $Id: test_dates.py,v 1.4 2001-07-29 23:32:13 richard Exp $ 

import unittest, time

from roundup.date import Date, Interval

class DateTestCase(unittest.TestCase):
    def testDateInterval(self):
        ae = self.assertEqual
        date = Date("2000-06-26.00:34:02 + 2d")
        ae(str(date), '2000-06-28.00:34:02')
        date = Date("2000-02-27 + 2d")
        ae(str(date), '2000-02-29.00:00:00')
        date = Date("2001-02-27 + 2d")
        ae(str(date), '2001-03-01.00:00:00')

    def testDate(self):
        ae = self.assertEqual
        date = Date("2000-04-17")
        ae(str(date), '2000-04-17.00:00:00')
        date = Date("01-25")
        y, m, d, x, x, x, x, x, x = time.gmtime()
        ae(str(date), '%s-01-25.00:00:00'%y)
        date = Date("2000-04-17.03:45")
        ae(str(date), '2000-04-17.03:45:00')
        date = Date("08-13.22:13")
        ae(str(date), '%s-08-13.22:13:00'%y)
        date = Date("11-07.09:32:43")
        ae(str(date), '%s-11-07.09:32:43'%y)
        date = Date("14:25")
        ae(str(date), '%s-%02d-%02d.14:25:00'%(y, m, d))
        date = Date("8:47:11")
        ae(str(date), '%s-%02d-%02d.08:47:11'%(y, m, d))

    def testOffset(self):
        ae = self.assertEqual
        date = Date("2000-04-17", -5)
        ae(str(date), '2000-04-17.00:00:00')
        date = Date("01-25", -5)
        y, m, d, x, x, x, x, x, x = time.gmtime()
        ae(str(date), '%s-01-25.00:00:00'%y)
        date = Date("2000-04-17.03:45", -5)
        ae(str(date), '2000-04-17.08:45:00')
        date = Date("08-13.22:13", -5)
        ae(str(date), '%s-08-14.03:13:00'%y)
        date = Date("11-07.09:32:43", -5)
        ae(str(date), '%s-11-07.14:32:43'%y)
        date = Date("14:25", -5)
        ae(str(date), '%s-%02d-%02d.19:25:00'%(y, m, d))
        date = Date("8:47:11", -5)
        ae(str(date), '%s-%02d-%02d.13:47:11'%(y, m, d))

    def testInterval(self):
        ae = self.assertEqual
        ae(str(Interval('3y')), '+ 3y')
        ae(str(Interval('2 y 1 m')), '+ 2y 1m')
        ae(str(Interval('1m 25d')), '+ 1m 25d')
        ae(str(Interval('-2w 3 d ')), '- 17d')
        ae(str(Interval(' - 1 d 2:50 ')), '- 1d 2:50')
        ae(str(Interval(' 14:00 ')), '+ 14:00')
        ae(str(Interval(' 0:04:33 ')), '+ 0:04:33')

def suite():
   return unittest.makeSuite(DateTestCase, 'test')


#
# $Log: not supported by cvs2svn $
# Revision 1.3  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.2  2001/07/29 06:42:20  richard
# Added Interval tests.
#
# Revision 1.1  2001/07/27 06:55:07  richard
# moving tests -> test
#
# Revision 1.2  2001/07/25 04:34:31  richard
# Added id and log to tests files...
#
#
# vim: set filetype=python ts=4 sw=4 et si
