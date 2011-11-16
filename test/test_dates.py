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
from __future__ import nested_scopes

import unittest
import time
import datetime
import calendar

from roundup import date, i18n
from roundup.date import Date, Interval, Range, fixTimeOverflow, \
    get_timezone


class DateTestCase(unittest.TestCase):
    def setUp(self):
        self.old_gettext_ = i18n.gettext
        self.old_ngettext_ = i18n.ngettext
        i18n.gettext = i18n.get_translation(language='C').gettext
        i18n.ngettext = i18n.get_translation(language='C').ngettext

    def tearDown(self):
        i18n.gettext = self.old_gettext_
        i18n.ngettext = self.old_ngettext_

    def testDateInterval(self):
        ae = self.assertEqual
        date = Date("2000-06-26.00:34:02 + 2d")
        ae(str(date), '2000-06-28.00:34:02')
        date = Date("2000-02-27 + 2d")
        ae(str(date), '2000-02-29.00:00:00')
        date = Date("2001-02-27 + 2d")
        ae(str(date), '2001-03-01.00:00:00')
        date = Date("2009", add_granularity=True)
        self.assertRaises(ValueError, Date, ". +30d", add_granularity=True)
        
    def testDate(self):
        ae = self.assertEqual
        date = Date("2000-04-17")
        ae(str(date), '2000-04-17.00:00:00')
        date = Date("2000/04/17")
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
        date = Date("2000/04/17.03:45")
        ae(str(date), '2000-04-17.03:45:00')
        date = Date("08-13.22:13")
        ae(str(date), '%s-08-13.22:13:00'%y)
        date = Date("11-07.09:32:43")
        ae(str(date), '%s-11-07.09:32:43'%y)
        date = Date("14:25")
        ae(str(date), '%s-%02d-%02d.14:25:00'%(y, m, d))
        date = Date("8:47:11")
        ae(str(date), '%s-%02d-%02d.08:47:11'%(y, m, d))
        ae(str(Date('2003')), '2003-01-01.00:00:00')
        ae(str(Date('2004-06')), '2004-06-01.00:00:00')
        ae(str(Date('1900-02-01')), '1900-02-01.00:00:00')
        ae(str(Date('1800-07-15')), '1800-07-15.00:00:00')

    def testLeapYear(self):
        self.assertEquals(str(Date('2008-02-29')), '2008-02-29.00:00:00')

    def testDateError(self):
        self.assertRaises(ValueError, Date, "12")
        # Date cannot handle dates before year 1
        self.assertRaises(ValueError, Date, (0, 1, 1, 0, 0, 0.0, 0, 1, -1))
        self.assertRaises(ValueError, Date, "1/1/06")

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

        # just make sure we parse these, m'kay?
        date = Date('-1d')
        date = Date('-1w')
        date = Date('-1m')
        date = Date('-1y')

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
        date = Date('2001-03-01.00:00:00') + Interval('150y')
        ae(str(date), '2151-03-01.00:00:00')

    def testOffsetSub(self):
        ae = self.assertEqual
        date = Date('2000-12-01') - Interval('- 1d')

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
        date = Date('2001-03-01.00:00:00') - Interval('150y')
        ae(str(date), '1851-03-01.00:00:00')

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
        ae(str(Interval(8.*3600)), '+ 8:00')

    def testIntervalInitDate(self):
        ae = self.assertEqual
        now = Date('.')
        now.hour = now.minute = now.second = 0
        then = now + Interval('2d')
        ae((Interval(str(then))), Interval('- 2d'))
        then = now - Interval('2d')
        ae(Interval(str(then)), Interval('+ 2d'))

    def testIntervalAddMonthBoundary(self):
        # force the transition over a month boundary
        now = Date('2003-10-30.00:00:00')
        then = now + Interval('2d')
        self.assertEqual(str(then), '2003-11-01.00:00:00')
        now = Date('2004-02-28.00:00:00')
        then = now + Interval('1d')
        self.assertEqual(str(then), '2004-02-29.00:00:00')
        now = Date('2003-02-28.00:00:00')
        then = now + Interval('1d')
        self.assertEqual(str(then), '2003-03-01.00:00:00')
        now = Date('2003-01-01.00:00:00')
        then = now + Interval('59d')
        self.assertEqual(str(then), '2003-03-01.00:00:00')
        now = Date('2004-01-01.00:00:00')
        then = now + Interval('59d')
        self.assertEqual(str(then), '2004-02-29.00:00:00')

    def testIntervalSubtractMonthBoundary(self):
        # force the transition over a month boundary
        now = Date('2003-11-01.00:00:00')
        then = now - Interval('2d')
        self.assertEqual(str(then), '2003-10-30.00:00:00')
        now = Date('2004-02-29.00:00:00')
        then = now - Interval('1d')
        self.assertEqual(str(then), '2004-02-28.00:00:00')
        now = Date('2003-03-01.00:00:00')
        then = now - Interval('1d')
        self.assertEqual(str(then), '2003-02-28.00:00:00')
        now = Date('2003-03-01.00:00:00')
        then = now - Interval('59d')
        self.assertEqual(str(then), '2003-01-01.00:00:00')
        now = Date('2004-02-29.00:00:00')
        then = now - Interval('59d')
        self.assertEqual(str(then), '2004-01-01.00:00:00')

    def testIntervalAddYearBoundary(self):
        # force the transition over a year boundary
        now = Date('2003-12-30.00:00:00')
        then = now + Interval('2d')
        self.assertEqual(str(then), '2004-01-01.00:00:00')
        now = Date('2003-01-01.00:00:00')
        then = now + Interval('365d')
        self.assertEqual(str(then), '2004-01-01.00:00:00')
        now = Date('2004-01-01.00:00:00')
        then = now + Interval('366d')
        self.assertEqual(str(then), '2005-01-01.00:00:00')

    def testIntervalSubtractYearBoundary(self):
        # force the transition over a year boundary
        now = Date('2003-01-01.00:00:00')
        then = now - Interval('2d')
        self.assertEqual(str(then), '2002-12-30.00:00:00')
        now = Date('2004-02-01.00:00:00')
        then = now - Interval('365d')
        self.assertEqual(str(then), '2003-02-01.00:00:00')
        now = Date('2005-02-01.00:00:00')
        then = now - Interval('365d')
        self.assertEqual(str(then), '2004-02-02.00:00:00')

    def testDateSubtract(self):
        # These are thoroughly broken right now.
        i = Date('2003-03-15.00:00:00') - Date('2003-03-10.00:00:00')
        self.assertEqual(i, Interval('5d'))
        i = Date('2003-02-01.00:00:00') - Date('2003-03-01.00:00:00')
        self.assertEqual(i, Interval('-28d'))
        i = Date('2003-03-01.00:00:00') - Date('2003-02-01.00:00:00')
        self.assertEqual(i, Interval('28d'))
        i = Date('2003-03-03.00:00:00') - Date('2003-02-01.00:00:00')
        self.assertEqual(i, Interval('30d'))
        i = Date('2003-03-03.00:00:00') - Date('2002-02-01.00:00:00')
        self.assertEqual(i, Interval('395d'))
        i = Date('2003-03-03.00:00:00') - Date('2003-04-01.00:00:00')
        self.assertEqual(i, Interval('-29d'))
        i = Date('2003-03-01.00:00:00') - Date('2003-02-01.00:00:00')
        self.assertEqual(i, Interval('28d'))
        # force the transition over a year boundary
        i = Date('2003-01-01.00:00:00') - Date('2002-01-01.00:00:00')
        self.assertEqual(i, Interval('365d'))
        i = Date('1952-01-01') - Date('1953-01-01')
        self.assertEqual(i, Interval('-366d'))
        i = Date('1953-01-01') - Date('1952-01-01')
        self.assertEqual(i, Interval('366d'))

    def testIntervalAdd(self):
        ae = self.assertEqual
        ae(str(Interval('1y') + Interval('1y')), '+ 2y')
        ae(str(Interval('1y') + Interval('1m')), '+ 1y 1m')
        ae(str(Interval('1y') + Interval('2:40')), '+ 1y 2:40')
        ae(str(Interval('1y') + Interval('- 1y')), '00:00')
        ae(str(Interval('- 1y') + Interval('1y')), '00:00')
        ae(str(Interval('- 1y') + Interval('- 1y')), '- 2y')
        ae(str(Interval('1y') + Interval('- 1m')), '+ 11m')
        ae(str(Interval('1:00') + Interval('1:00')), '+ 2:00')
        ae(str(Interval('0:50') + Interval('0:50')), '+ 1:40')
        ae(str(Interval('1:50') + Interval('- 1:50')), '00:00')
        ae(str(Interval('- 1:50') + Interval('1:50')), '00:00')
        ae(str(Interval('- 1:50') + Interval('- 1:50')), '- 3:40')
        ae(str(Interval('1:59:59') + Interval('00:00:01')), '+ 2:00')
        ae(str(Interval('2:00') + Interval('- 00:00:01')), '+ 1:59:59')

    def testIntervalSub(self):
        ae = self.assertEqual
        ae(str(Interval('1y') - Interval('- 1y')), '+ 2y')
        ae(str(Interval('1y') - Interval('- 1m')), '+ 1y 1m')
        ae(str(Interval('1y') - Interval('- 2:40')), '+ 1y 2:40')
        ae(str(Interval('1y') - Interval('1y')), '00:00')
        ae(str(Interval('1y') - Interval('1m')), '+ 11m')
        ae(str(Interval('1:00') - Interval('- 1:00')), '+ 2:00')
        ae(str(Interval('0:50') - Interval('- 0:50')), '+ 1:40')
        ae(str(Interval('1:50') - Interval('1:50')), '00:00')
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

        i1 = Interval("1:20")
        i2 = Interval("2d")
        i3 = Interval("3:30")
        l = [i1, i2, i3]; l.sort()
        ae(l, [i1, i3, i2])

    def testGranularity(self):
        ae = self.assertEqual
        ae(str(Date('2003-2-12', add_granularity=1)), '2003-02-12.23:59:59')
        ae(str(Date('2003-1-1.23:00', add_granularity=1)), '2003-01-01.23:00:59')
        ae(str(Date('2003', add_granularity=1)), '2003-12-31.23:59:59')
        ae(str(Date('2003-5', add_granularity=1)), '2003-05-31.23:59:59')
        ae(str(Date('2003-12', add_granularity=1)), '2003-12-31.23:59:59')
        ae(str(Interval('+1w', add_granularity=1)), '+ 14d')
        ae(str(Interval('-2m 3w', add_granularity=1)), '- 2m 14d')

    def testIntervalPretty(self):
        def ae(spec, pretty):
            self.assertEqual(Interval(spec).pretty(), pretty)
        ae('2y', 'in 2 years')
        ae('1y', 'in 1 year')
        ae('2m', 'in 2 months')
        ae('1m 30d', 'in 2 months')
        ae('60d', 'in 2 months')
        ae('59d', 'in 1 month')
        ae('1m', 'in 1 month')
        ae('29d', 'in 1 month')
        ae('28d', 'in 4 weeks')
        ae('8d', 'in 1 week')
        ae('7d', 'in 7 days')
        ae('1w', 'in 7 days')
        ae('2d', 'in 2 days')
        ae('1d', 'tomorrow')
        ae('02:00:00', 'in 2 hours')
        ae('01:59:00', 'in 1 3/4 hours')
        ae('01:45:00', 'in 1 3/4 hours')
        ae('01:30:00', 'in 1 1/2 hours')
        ae('01:29:00', 'in 1 1/4 hours')
        ae('01:00:00', 'in an hour')
        ae('00:30:00', 'in 1/2 an hour')
        ae('00:15:00', 'in 1/4 hour')
        ae('00:02:00', 'in 2 minutes')
        ae('00:01:00', 'in 1 minute')
        ae('00:00:30', 'in a moment')
        ae('-00:00:30', 'just now')
        ae('-1d', 'yesterday')
        ae('-1y', '1 year ago')
        ae('-2y', '2 years ago')

    def testPyDatetime(self):
        d = datetime.datetime.now()
        Date(d)
        toomuch = datetime.MAXYEAR + 1
        self.assertRaises(ValueError, Date, (toomuch, 1, 1, 0, 0, 0, 0, 1, -1))

    def testSimpleTZ(self):
        ae = self.assertEqual
        # local to utc
        date = Date('2006-04-04.12:00:00', 2)
        ae(str(date), '2006-04-04.10:00:00')
        # utc to local
        date = Date('2006-04-04.10:00:00')
        date = date.local(2)
        ae(str(date), '2006-04-04.12:00:00')
        # from Date instance
        date = Date('2006-04-04.12:00:00')
        date = Date(date, 2)
        ae(str(date), '2006-04-04.10:00:00')

    def testTimestamp(self):
        ae = self.assertEqual
        date = Date('2038')
        ae(date.timestamp(), 2145916800)
        date = Date('1902')
        ae(date.timestamp(), -2145916800)
        date = Date(time.gmtime(0))
        ae(date.timestamp(), 0)
        ae(str(date), '1970-01-01.00:00:00')
        date = Date(time.gmtime(0x7FFFFFFF))
        ae(date.timestamp(), 2147483647)
        ae(str(date), '2038-01-19.03:14:07')
        date = Date('1901-12-13.20:45:52')
        ae(date.timestamp(), -0x80000000L)
        ae(str(date), '1901-12-13.20:45:52')
        date = Date('9999')
        ae (date.timestamp(), 253370764800.0)
        date = Date('0033')
        ae (date.timestamp(), -61125753600.0)
        ae(str(date), '0033-01-01.00:00:00')

class TimezoneTestCase(unittest.TestCase):

    def testTZ(self):
        ae = self.assertEqual
        tz = 'Europe/Warsaw'

        # local to utc, DST
        date = Date('2006-04-04.12:00:00', tz)
        ae(str(date), '2006-04-04.10:00:00')

        # local to utc, no DST
        date = Date('2006-01-01.12:00:00', tz)
        ae(str(date), '2006-01-01.11:00:00')

        # utc to local, DST
        date = Date('2006-04-04.10:00:00')
        date = date.local(tz)
        ae(str(date), '2006-04-04.12:00:00')

        # utc to local, no DST
        date = Date('2006-01-01.10:00:00')
        date = date.local(tz)
        ae(str(date), '2006-01-01.11:00:00')

        date = Date('2006-04-04.12:00:00')
        date = Date(date, tz)
        ae(str(date), '2006-04-04.10:00:00')
        date = Date('2006-01-01.12:00:00')
        date = Date(date, tz)
        ae(str(date), '2006-01-01.11:00:00')


class RangeTestCase(unittest.TestCase):

    def testRange(self):
        ae = self.assertEqual
        r = Range('2006', Date)
        ae(str(r.from_value), '2006-01-01.00:00:00')
        ae(str(r.to_value), '2006-12-31.23:59:59')
        for i in range(1, 13):
            r = Range('2006-%02d'%i, Date)
            ae(str(r.from_value), '2006-%02d-01.00:00:00'%i)
            ae(str(r.to_value), '2006-%02d-%02d.23:59:59'%(i,
                calendar.mdays[i]))


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(DateTestCase))
    suite.addTest(unittest.makeSuite(RangeTestCase))
    try:
        import pytz
    except ImportError:
        pass
    else:
        suite.addTest(unittest.makeSuite(TimezoneTestCase))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

# vim: set filetype=python sts=4 sw=4 et si :
