#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
# 
# $Id: test_dates.py,v 1.19 2003-03-06 06:12:30 richard Exp $ 

import unittest, time

from roundup.date import Date, Interval, fixTimeOverflow

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
        date = Date("2000-4-7")
        ae(str(date), '2000-04-07.00:00:00')
        date = Date("2000-4-17")
        ae(str(date), '2000-04-17.00:00:00')
        date = Date("01-25")
        y, m, d, x, x, x, x, x, x = time.gmtime(time.time())
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
        ae(str(date), '2000-04-17.05:00:00')
        date = Date("01-25", -5)
        y, m, d, x, x, x, x, x, x = time.gmtime(time.time())
        ae(str(date), '%s-01-25.05:00:00'%y)
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

    def testOffsetRandom(self):
        ae = self.assertEqual
        # XXX unsure of the usefulness of these, they're pretty random
        date = Date('2000-01-01') + Interval('- 2y 2m')
        ae(str(date), '1997-11-01.00:00:00')
        date = Date('2000-01-01 - 2y 2m')
        ae(str(date), '1997-11-01.00:00:00')
        date = Date('2000-01-01') + Interval('2m')
        ae(str(date), '2000-03-01.00:00:00')
        date = Date('2000-01-01 + 2m')
        ae(str(date), '2000-03-01.00:00:00')

        date = Date('2000-01-01') + Interval('60d')
        ae(str(date), '2000-03-01.00:00:00')
        date = Date('2001-01-01') + Interval('60d')
        ae(str(date), '2001-03-02.00:00:00')

    def testOffsetAdd(self):
        ae = self.assertEqual
        date = Date('2000-02-28.23:59:59') + Interval('00:00:01')
        ae(str(date), '2000-02-29.00:00:00')
        date = Date('2001-02-28.23:59:59') + Interval('00:00:01')
        ae(str(date), '2001-03-01.00:00:00')

        date = Date('2000-02-28.23:58:59') + Interval('00:01:01')
        ae(str(date), '2000-02-29.00:00:00')
        date = Date('2001-02-28.23:58:59') + Interval('00:01:01')
        ae(str(date), '2001-03-01.00:00:00')

        date = Date('2000-02-28.22:58:59') + Interval('01:01:01')
        ae(str(date), '2000-02-29.00:00:00')
        date = Date('2001-02-28.22:58:59') + Interval('01:01:01')
        ae(str(date), '2001-03-01.00:00:00')

        date = Date('2000-02-28.22:58:59') + Interval('00:00:3661')
        ae(str(date), '2000-02-29.00:00:00')
        date = Date('2001-02-28.22:58:59') + Interval('00:00:3661')
        ae(str(date), '2001-03-01.00:00:00')

    def testOffsetSub(self):
        ae = self.assertEqual
        date = Date('2000-01-01') - Interval('- 2y 2m')
        ae(str(date), '2002-03-01.00:00:00')
        date = Date('2000-01-01') - Interval('2m')
        ae(str(date), '1999-11-01.00:00:00')

        date = Date('2000-03-01') - Interval('60d')
        ae(str(date), '2000-01-01.00:00:00')
        date = Date('2001-03-02') - Interval('60d')
        ae(str(date), '2001-01-01.00:00:00')

        date = Date('2000-02-29.00:00:00') - Interval('00:00:01')
        ae(str(date), '2000-02-28.23:59:59')
        date = Date('2001-03-01.00:00:00') - Interval('00:00:01')
        ae(str(date), '2001-02-28.23:59:59')

        date = Date('2000-02-29.00:00:00') - Interval('00:01:01')
        ae(str(date), '2000-02-28.23:58:59')
        date = Date('2001-03-01.00:00:00') - Interval('00:01:01')
        ae(str(date), '2001-02-28.23:58:59')

        date = Date('2000-02-29.00:00:00') - Interval('01:01:01')
        ae(str(date), '2000-02-28.22:58:59')
        date = Date('2001-03-01.00:00:00') - Interval('01:01:01')
        ae(str(date), '2001-02-28.22:58:59')

        date = Date('2000-02-29.00:00:00') - Interval('00:00:3661')
        ae(str(date), '2000-02-28.22:58:59')
        date = Date('2001-03-01.00:00:00') - Interval('00:00:3661')
        ae(str(date), '2001-02-28.22:58:59')

    def testDateLocal(self):
        ae = self.assertEqual
        date = Date("02:42:20")
        date = date.local(10)
        y, m, d, x, x, x, x, x, x = time.gmtime(time.time())
        ae(str(date), '%s-%02d-%02d.12:42:20'%(y, m, d))

    def testIntervalInit(self):
        ae = self.assertEqual
        ae(str(Interval('3y')), '+ 3y')
        ae(str(Interval('2 y 1 m')), '+ 2y 1m')
        ae(str(Interval('1m 25d')), '+ 1m 25d')
        ae(str(Interval('-2w 3 d ')), '- 17d')
        ae(str(Interval(' - 1 d 2:50 ')), '- 1d 2:50')
        ae(str(Interval(' 14:00 ')), '+ 14:00')
        ae(str(Interval(' 0:04:33 ')), '+ 0:04:33')

    def testIntervalAdd(self):
        ae = self.assertEqual
        ae(str(Interval('1y') + Interval('1y')), '+ 2y')
        ae(str(Interval('1y') + Interval('1m')), '+ 1y 1m')
        ae(str(Interval('1y') + Interval('2:40')), '+ 1y 2:40')
        ae(str(Interval('1y') + Interval('- 1y')), '')
        ae(str(Interval('- 1y') + Interval('1y')), '')
        ae(str(Interval('- 1y') + Interval('- 1y')), '- 2y')
        ae(str(Interval('1y') + Interval('- 1m')), '+ 11m')
        ae(str(Interval('1:00') + Interval('1:00')), '+ 2:00')
        ae(str(Interval('0:50') + Interval('0:50')), '+ 1:40')
        ae(str(Interval('1:50') + Interval('- 1:50')), '')
        ae(str(Interval('- 1:50') + Interval('1:50')), '')
        ae(str(Interval('- 1:50') + Interval('- 1:50')), '- 3:40')
        ae(str(Interval('1:59:59') + Interval('00:00:01')), '+ 2:00')
        ae(str(Interval('2:00') + Interval('- 00:00:01')), '+ 1:59:59')

    def testIntervalSub(self):
        ae = self.assertEqual
        ae(str(Interval('1y') - Interval('- 1y')), '+ 2y')
        ae(str(Interval('1y') - Interval('- 1m')), '+ 1y 1m')
        ae(str(Interval('1y') - Interval('- 2:40')), '+ 1y 2:40')
        ae(str(Interval('1y') - Interval('1y')), '')
        ae(str(Interval('1y') - Interval('1m')), '+ 11m')
        ae(str(Interval('1:00') - Interval('- 1:00')), '+ 2:00')
        ae(str(Interval('0:50') - Interval('- 0:50')), '+ 1:40')
        ae(str(Interval('1:50') - Interval('1:50')), '')
        ae(str(Interval('1:59:59') - Interval('- 00:00:01')), '+ 2:00')
        ae(str(Interval('2:00') - Interval('00:00:01')), '+ 1:59:59')

    def testOverflow(self):
        ae = self.assertEqual
        ae(fixTimeOverflow((1,0,0,0, 0, 0, 60)), (1,0,0,0, 0, 1, 0))
        ae(fixTimeOverflow((1,0,0,0, 0, 0, 100)), (1,0,0,0, 0, 1, 40))
        ae(fixTimeOverflow((1,0,0,0, 0, 0, 60*60)), (1,0,0,0, 1, 0, 0))
        ae(fixTimeOverflow((1,0,0,0, 0, 0, 24*60*60)), (1,0,0,1, 0, 0, 0))
        ae(fixTimeOverflow((1,0,0,0, 0, 0, -1)), (-1,0,0,0, 0, 0, 1))
        ae(fixTimeOverflow((1,0,0,0, 0, 0, -100)), (-1,0,0,0, 0, 1, 40))
        ae(fixTimeOverflow((1,0,0,0, 0, 0, -60*60)), (-1,0,0,0, 1, 0, 0))
        ae(fixTimeOverflow((1,0,0,0, 0, 0, -24*60*60)), (-1,0,0,1, 0, 0, 0))
        ae(fixTimeOverflow((-1,0,0,0, 0, 0, 1)), (-1,0,0,0, 0, 0, 1))
        ae(fixTimeOverflow((-1,0,0,0, 0, 0, 100)), (-1,0,0,0, 0, 1, 40))
        ae(fixTimeOverflow((-1,0,0,0, 0, 0, 60*60)), (-1,0,0,0, 1, 0, 0))
        ae(fixTimeOverflow((-1,0,0,0, 0, 0, 24*60*60)), (-1,0,0,1, 0, 0, 0))

    def testDivision(self):
        ae = self.assertEqual
        ae(str(Interval('1y')/2), '+ 6m')
        ae(str(Interval('1:00')/2), '+ 0:30')
        ae(str(Interval('00:01')/2), '+ 0:00:30')

    def testSorting(self):
        ae = self.assertEqual
        i1 = Interval('1y')
        i2 = Interval('1d')
        l = [i1, i2]; l.sort()
        ae(l, [i2, i1])
        l = [i2, i1]; l.sort()
        ae(l, [i2, i1])
        i1 = Interval('- 2d')
        i2 = Interval('1d')
        l = [i1, i2]; l.sort()
        ae(l, [i1, i2])


def suite():
   return unittest.makeSuite(DateTestCase, 'test')


# vim: set filetype=python ts=4 sw=4 et si
