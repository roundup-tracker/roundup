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
# $Id: date.py,v 1.45 2003-03-06 06:12:30 richard Exp $

__doc__ = """
Date, time and time interval handling.
"""

import time, re, calendar, types
from i18n import _

class Date:
    '''
    As strings, date-and-time stamps are specified with the date in
    international standard format (yyyy-mm-dd) joined to the time
    (hh:mm:ss) by a period ("."). Dates in this form can be easily compared
    and are fairly readable when printed. An example of a valid stamp is
    "2000-06-24.13:03:59". We'll call this the "full date format". When
    Timestamp objects are printed as strings, they appear in the full date
    format with the time always given in GMT. The full date format is
    always exactly 19 characters long. 

    For user input, some partial forms are also permitted: the whole time
    or just the seconds may be omitted; and the whole date may be omitted
    or just the year may be omitted. If the time is given, the time is
    interpreted in the user's local time zone. The Date constructor takes
    care of these conversions. In the following examples, suppose that yyyy
    is the current year, mm is the current month, and dd is the current day
    of the month; and suppose that the user is on Eastern Standard Time.

      "2000-04-17" means <Date 2000-04-17.00:00:00>
      "01-25" means <Date yyyy-01-25.00:00:00>
      "2000-04-17.03:45" means <Date 2000-04-17.08:45:00>
      "08-13.22:13" means <Date yyyy-08-14.03:13:00>
      "11-07.09:32:43" means <Date yyyy-11-07.14:32:43>
      "14:25" means <Date yyyy-mm-dd.19:25:00>
      "8:47:11" means <Date yyyy-mm-dd.13:47:11>
      "." means "right now"

    The Date class should understand simple date expressions of the form
    stamp + interval and stamp - interval. When adding or subtracting
    intervals involving months or years, the components are handled
    separately. For example, when evaluating "2000-06-25 + 1m 10d", we
    first add one month to get 2000-07-25, then add 10 days to get
    2000-08-04 (rather than trying to decide whether 1m 10d means 38 or 40
    or 41 days).

    Example usage:
        >>> Date(".")
        <Date 2000-06-26.00:34:02>
        >>> _.local(-5)
        "2000-06-25.19:34:02"
        >>> Date(". + 2d")
        <Date 2000-06-28.00:34:02>
        >>> Date("1997-04-17", -5)
        <Date 1997-04-17.00:00:00>
        >>> Date("01-25", -5)
        <Date 2000-01-25.00:00:00>
        >>> Date("08-13.22:13", -5)
        <Date 2000-08-14.03:13:00>
        >>> Date("14:25", -5)
        <Date 2000-06-25.19:25:00>

    The date format 'yyyymmddHHMMSS' (year, month, day, hour,
    minute, second) is the serialisation format returned by the serialise()
    method, and is accepted as an argument on instatiation.
    '''
    def __init__(self, spec='.', offset=0):
        """Construct a date given a specification and a time zone offset.

          'spec' is a full date or a partial form, with an optional
                 added or subtracted interval. Or a date 9-tuple.
        'offset' is the local time zone offset from GMT in hours.
        """
        if type(spec) == type(''):
            self.set(spec, offset=offset)
        else:
            y,m,d,H,M,S,x,x,x = spec
            ts = calendar.timegm((y,m,d,H+offset,M,S,0,0,0))
            self.year, self.month, self.day, self.hour, self.minute, \
                self.second, x, x, x = time.gmtime(ts)

    def addInterval(self, interval):
        ''' Add the interval to this date, returning the date tuple
        '''
        # do the basic calc
        sign = interval.sign
        year = self.year + sign * interval.year
        month = self.month + sign * interval.month
        day = self.day + sign * interval.day
        hour = self.hour + sign * interval.hour
        minute = self.minute + sign * interval.minute
        second = self.second + sign * interval.second

        # now cope with under- and over-flow
        # first do the time
        while (second < 0 or second > 59 or minute < 0 or minute > 59 or
                hour < 0 or hour > 59):
            if second < 0: minute -= 1; second += 60
            elif second > 59: minute += 1; second -= 60
            if minute < 0: hour -= 1; minute += 60
            elif minute > 59: hour += 1; minute -= 60
            if hour < 0: day -= 1; hour += 24
            elif hour > 59: day += 1; hour -= 24

        # fix up the month so we're within range
        while month < 1 or month > 12:
            if month < 1: year -= 1; month += 12
            if month > 12: year += 1; month -= 12

        # now do the days, now that we know what month we're in
        mdays = calendar.mdays
        if month == 2 and calendar.isleap(year): month_days = 29
        else: month_days = mdays[month]
        while month < 1 or month > 12 or day < 0 or day > month_days:
            # now to day under/over
            if day < 0: month -= 1; day += month_days
            elif day > month_days: month += 1; day -= month_days

            # possibly fix up the month so we're within range
            while month < 1 or month > 12:
                if month < 1: year -= 1; month += 12
                if month > 12: year += 1; month -= 12

            # re-figure the number of days for this month
            if month == 2 and calendar.isleap(year): month_days = 29
            else: month_days = mdays[month]
        return (year, month, day, hour, minute, second, 0, 0, 0)

    def applyInterval(self, interval):
        ''' Apply the interval to this date
        '''
        self.year, self.month, self.day, self.hour, self.minute, \
            self.second, x, x, x = self.addInterval(interval)

    def __add__(self, interval):
        """Add an interval to this date to produce another date.
        """
        return Date(self.addInterval(interval))

    # deviates from spec to allow subtraction of dates as well
    def __sub__(self, other):
        """ Subtract:
             1. an interval from this date to produce another date.
             2. a date from this date to produce an interval.
        """
        if isinstance(other, Interval):
            other = Interval(other.get_tuple())
            other.sign *= -1
            return self.__add__(other)

        assert isinstance(other, Date), 'May only subtract Dates or Intervals'

        # TODO this code will fall over laughing if the dates cross
        # leap years, phases of the moon, ....
        a = calendar.timegm((self.year, self.month, self.day, self.hour,
            self.minute, self.second, 0, 0, 0))
        b = calendar.timegm((other.year, other.month, other.day,
            other.hour, other.minute, other.second, 0, 0, 0))
        diff = a - b
        if diff < 0:
            sign = 1
            diff = -diff
        else:
            sign = -1
        S = diff%60
        M = (diff/60)%60
        H = (diff/(60*60))%60
        if H>1: S = 0
        d = (diff/(24*60*60))%30
        if d>1: H = S = M = 0
        m = (diff/(30*24*60*60))%12
        if m>1: H = S = M = 0
        y = (diff/(365*24*60*60))
        if y>1: d = H = S = M = 0
        return Interval((y, m, d, H, M, S), sign=sign)

    def __cmp__(self, other):
        """Compare this date to another date."""
        if other is None:
            return 1
        for attr in ('year', 'month', 'day', 'hour', 'minute', 'second'):
            if not hasattr(other, attr):
                return 1
            r = cmp(getattr(self, attr), getattr(other, attr))
            if r: return r
        return 0

    def __str__(self):
        """Return this date as a string in the yyyy-mm-dd.hh:mm:ss format."""
        return '%4d-%02d-%02d.%02d:%02d:%02d'%(self.year, self.month, self.day,
            self.hour, self.minute, self.second)

    def pretty(self, format='%d %B %Y'):
        ''' print up the date date using a pretty format...

            Note that if the day is zero, and the day appears first in the
            format, then the day number will be removed from output.
        '''
        str = time.strftime(format, (self.year, self.month, self.day,
            self.hour, self.minute, self.second, 0, 0, 0))
        # handle zero day by removing it
        if format.startswith('%d') and str[0] == '0':
            return ' ' + str[1:]
        return str

    def set(self, spec, offset=0, date_re=re.compile(r'''
            (((?P<y>\d\d\d\d)-)?((?P<m>\d\d?)-(?P<d>\d\d?))?)? # yyyy-mm-dd
            (?P<n>\.)?                                     # .
            (((?P<H>\d?\d):(?P<M>\d\d))?(:(?P<S>\d\d))?)?  # hh:mm:ss
            (?P<o>.+)?                                     # offset
            ''', re.VERBOSE), serialised_re=re.compile(r'''
            (\d{4})(\d\d)(\d\d)(\d\d)(\d\d)(\d\d)
            ''', re.VERBOSE)):
        ''' set the date to the value in spec
        '''
        m = serialised_re.match(spec)
        if m is not None:
            # we're serialised - easy!
            self.year, self.month, self.day, self.hour, self.minute, \
                self.second = map(int, m.groups()[:6])
            return

        # not serialised data, try usual format
        m = date_re.match(spec)
        if m is None:
            raise ValueError, _('Not a date spec: [[yyyy-]mm-dd].'
                '[[h]h:mm[:ss]][offset]')

        info = m.groupdict()

        # get the current date as our default
        y,m,d,H,M,S,x,x,x = time.gmtime(time.time())

        # override year, month, day parts
        if info['m'] is not None and info['d'] is not None:
            m = int(info['m'])
            d = int(info['d'])
            if info['y'] is not None:
                y = int(info['y'])
            # time defaults to 00:00:00 GMT - offset (local midnight)
            H = -offset
            M = S = 0

        # override hour, minute, second parts
        if info['H'] is not None and info['M'] is not None:
            H = int(info['H']) - offset
            M = int(info['M'])
            S = 0
            if info['S'] is not None: S = int(info['S'])

        # now handle the adjustment of hour
        ts = calendar.timegm((y,m,d,H,M,S,0,0,0))
        self.year, self.month, self.day, self.hour, self.minute, \
            self.second, x, x, x = time.gmtime(ts)

        if info.get('o', None):
            self.applyInterval(Interval(info['o']))

    def __repr__(self):
        return '<Date %s>'%self.__str__()

    def local(self, offset):
        """ Return this date as yyyy-mm-dd.hh:mm:ss in a local time zone.
        """
        return Date((self.year, self.month, self.day, self.hour + offset,
            self.minute, self.second, 0, 0, 0))

    def get_tuple(self):
        return (self.year, self.month, self.day, self.hour, self.minute,
            self.second, 0, 0, 0)

    def serialise(self):
        return '%4d%02d%02d%02d%02d%02d'%(self.year, self.month,
            self.day, self.hour, self.minute, self.second)

class Interval:
    '''
    Date intervals are specified using the suffixes "y", "m", and "d". The
    suffix "w" (for "week") means 7 days. Time intervals are specified in
    hh:mm:ss format (the seconds may be omitted, but the hours and minutes
    may not).

      "3y" means three years
      "2y 1m" means two years and one month
      "1m 25d" means one month and 25 days
      "2w 3d" means two weeks and three days
      "1d 2:50" means one day, two hours, and 50 minutes
      "14:00" means 14 hours
      "0:04:33" means four minutes and 33 seconds

    Example usage:
        >>> Interval("  3w  1  d  2:00")
        <Interval + 22d 2:00>
        >>> Date(". + 2d") + Interval("- 3w")
        <Date 2000-06-07.00:34:02>
        >>> Interval('1:59:59') + Interval('00:00:01')
        <Interval + 2:00>
        >>> Interval('2:00') + Interval('- 00:00:01')
        <Interval + 1:59:59>
        >>> Interval('1y')/2
        <Interval + 6m>
        >>> Interval('1:00')/2
        <Interval + 0:30>

    Interval arithmetic is handled in a couple of special ways, trying
    to cater for the most common cases. Fundamentally, Intervals which
    have both date and time parts will result in strange results in
    arithmetic - because of the impossibility of handling day->month->year
    over- and under-flows. Intervals may also be divided by some number.

    Intervals are added to Dates in order of:
       seconds, minutes, hours, years, months, days

    Calculations involving months (eg '+2m') have no effect on days - only
    days (or over/underflow from hours/mins/secs) will do that, and
    days-per-month and leap years are accounted for. Leap seconds are not.

    The interval format 'syyyymmddHHMMSS' (sign, year, month, day, hour,
    minute, second) is the serialisation format returned by the serialise()
    method, and is accepted as an argument on instatiation.

    TODO: more examples, showing the order of addition operation
    '''
    def __init__(self, spec, sign=1):
        """Construct an interval given a specification."""
        if type(spec) == type(''):
            self.set(spec)
        else:
            if len(spec) == 7:
                self.sign, self.year, self.month, self.day, self.hour, \
                    self.minute, self.second = spec
            else:
                # old, buggy spec form
                self.sign = sign
                self.year, self.month, self.day, self.hour, self.minute, \
                    self.second = spec

    def __cmp__(self, other):
        """Compare this interval to another interval."""
        if other is None:
            return 1
        for attr in 'sign year month day hour minute second'.split():
            if not hasattr(other, attr):
                return 1
            r = cmp(getattr(self, attr), getattr(other, attr))
            if r:
                return r
        return 0

    def __str__(self):
        """Return this interval as a string."""
        l = []
        if self.year: l.append('%sy'%self.year)
        if self.month: l.append('%sm'%self.month)
        if self.day: l.append('%sd'%self.day)
        if self.second:
            l.append('%d:%02d:%02d'%(self.hour, self.minute, self.second))
        elif self.hour or self.minute:
            l.append('%d:%02d'%(self.hour, self.minute))
        if l:
            l.insert(0, {1:'+', -1:'-'}[self.sign])
        return ' '.join(l)

    def __add__(self, other):
        if isinstance(other, Date):
            # the other is a Date - produce a Date
            return Date(other.addInterval(self))
        elif isinstance(other, Interval):
            # add the other Interval to this one
            a = self.get_tuple()
            as = a[0]
            b = other.get_tuple()
            bs = b[0]
            i = [as*x + bs*y for x,y in zip(a[1:],b[1:])]
            i.insert(0, 1)
            i = fixTimeOverflow(i)
            return Interval(i)
        # nope, no idea what to do with this other...
        raise TypeError, "Can't add %r"%other

    def __sub__(self, other):
        if isinstance(other, Date):
            # the other is a Date - produce a Date
            interval = Interval(self.get_tuple())
            interval.sign *= -1
            return Date(other.addInterval(interval))
        elif isinstance(other, Interval):
            # add the other Interval to this one
            a = self.get_tuple()
            as = a[0]
            b = other.get_tuple()
            bs = b[0]
            i = [as*x - bs*y for x,y in zip(a[1:],b[1:])]
            i.insert(0, 1)
            i = fixTimeOverflow(i)
            return Interval(i)
        # nope, no idea what to do with this other...
        raise TypeError, "Can't add %r"%other

    def __div__(self, other):
        ''' Divide this interval by an int value.

            Can't divide years and months sensibly in the _same_
            calculation as days/time, so raise an error in that situation.
        '''
        try:
            other = float(other)
        except TypeError:
            raise ValueError, "Can only divide Intervals by numbers"

        y, m, d, H, M, S = (self.year, self.month, self.day,
            self.hour, self.minute, self.second)
        if y or m:
            if d or H or M or S:
                raise ValueError, "Can't divide Interval with date and time"
            months = self.year*12 + self.month
            months *= self.sign

            months = int(months/other)

            sign = months<0 and -1 or 1
            m = months%12
            y = months / 12
            return Interval((sign, y, m, 0, 0, 0, 0))

        else:
            # handle a day/time division
            seconds = S + M*60 + H*60*60 + d*60*60*24
            seconds *= self.sign

            seconds = int(seconds/other)

            sign = seconds<0 and -1 or 1
            seconds *= sign
            S = seconds%60
            seconds /= 60
            M = seconds%60
            seconds /= 60
            H = seconds%24
            d = seconds / 24
            return Interval((sign, 0, 0, d, H, M, S))

    def set(self, spec, interval_re=re.compile('''
            \s*(?P<s>[-+])?         # + or -
            \s*((?P<y>\d+\s*)y)?    # year
            \s*((?P<m>\d+\s*)m)?    # month
            \s*((?P<w>\d+\s*)w)?    # week
            \s*((?P<d>\d+\s*)d)?    # day
            \s*(((?P<H>\d+):(?P<M>\d+))?(:(?P<S>\d+))?)?   # time
            \s*''', re.VERBOSE), serialised_re=re.compile('''
            (?P<s>[+-])?1?(?P<y>([ ]{3}\d|\d{4}))(?P<m>\d{2})(?P<d>\d{2})
            (?P<H>\d{2})(?P<M>\d{2})(?P<S>\d{2})''', re.VERBOSE)):
        ''' set the date to the value in spec
        '''
        self.year = self.month = self.week = self.day = self.hour = \
            self.minute = self.second = 0
        self.sign = 1
        m = serialised_re.match(spec)
        if not m:
            m = interval_re.match(spec)
            if not m:
                raise ValueError, _('Not an interval spec: [+-] [#y] [#m] [#w] '
                    '[#d] [[[H]H:MM]:SS]')

        info = m.groupdict()
        for group, attr in {'y':'year', 'm':'month', 'w':'week', 'd':'day',
                'H':'hour', 'M':'minute', 'S':'second'}.items():
            if info.get(group, None) is not None:
                setattr(self, attr, int(info[group]))

        if self.week:
            self.day = self.day + self.week*7

        if info['s'] is not None:
            self.sign = {'+':1, '-':-1}[info['s']]

    def __repr__(self):
        return '<Interval %s>'%self.__str__()

    def pretty(self):
        ''' print up the date date using one of these nice formats..
        '''
        if self.year:
            if self.year == 1:
                return _('1 year')
            else:
                return _('%(number)s years')%{'number': self.year}
        elif self.month or self.day > 13:
            days = (self.month * 30) + self.day
            if days > 28:
                if int(days/30) > 1:
                    s = _('%(number)s months')%{'number': int(days/30)}
                else:
                    s = _('1 month')
            else:
                s = _('%(number)s weeks')%{'number': int(days/7)}
        elif self.day > 7:
            s = _('1 week')
        elif self.day > 1:
            s = _('%(number)s days')%{'number': self.day}
        elif self.day == 1 or self.hour > 12:
            if self.sign > 0:
                return _('tomorrow')
            else:
                return _('yesterday')
        elif self.hour > 1:
            s = _('%(number)s hours')%{'number': self.hour}
        elif self.hour == 1:
            if self.minute < 15:
                s = _('an hour')
            elif self.minute/15 == 2:
                s = _('1 1/2 hours')
            else:
                s = _('1 %(number)s/4 hours')%{'number': self.minute/15}
        elif self.minute < 1:
            if self.sign > 0:
                return _('in a moment')
            else:
                return _('just now')
        elif self.minute == 1:
            s = _('1 minute')
        elif self.minute < 15:
            s = _('%(number)s minutes')%{'number': self.minute}
        elif int(self.minute/15) == 2:
            s = _('1/2 an hour')
        else:
            s = _('%(number)s/4 hour')%{'number': int(self.minute/15)}
        if self.sign < 0: 
            s = s + _(' ago')
        else:
            s = _('in') + s
        return s

    def get_tuple(self):
        return (self.sign, self.year, self.month, self.day, self.hour,
            self.minute, self.second)

    def serialise(self):
        sign = self.sign > 0 and '+' or '-'
        return '%s%04d%02d%02d%02d%02d%02d'%(sign, self.year, self.month,
            self.day, self.hour, self.minute, self.second)

def fixTimeOverflow(time):
    ''' Handle the overflow in the time portion (H, M, S) of "time":
            (sign, y,m,d,H,M,S)

        Overflow and underflow will at most affect the _days_ portion of
        the date. We do not overflow days to months as we don't know _how_
        to, generally.
    '''
    # XXX we could conceivably use this function for handling regular dates
    # XXX too - we just need to interrogate the month/year for the day
    # XXX overflow...

    sign, y, m, d, H, M, S = time
    seconds = sign * (S + M*60 + H*60*60 + d*60*60*24)
    if seconds:
        sign = seconds<0 and -1 or 1
        seconds *= sign
        S = seconds%60
        seconds /= 60
        M = seconds%60
        seconds /= 60
        H = seconds%24
        d = seconds / 24
    else:
        months = y*12 + m
        sign = months<0 and -1 or 1
        months *= sign
        m = months%12
        y = months/12

    return (sign, y, m, d, H, M, S)


def test():
    intervals = ("  3w  1  d  2:00", " + 2d", "3w")
    for interval in intervals:
        print '>>> Interval("%s")'%interval
        print `Interval(interval)`

    dates = (".", "2000-06-25.19:34:02", ". + 2d", "1997-04-17", "01-25",
        "08-13.22:13", "14:25")
    for date in dates:
        print '>>> Date("%s")'%date
        print `Date(date)`

    sums = ((". + 2d", "3w"), (".", "  3w  1  d  2:00"))
    for date, interval in sums:
        print '>>> Date("%s") + Interval("%s")'%(date, interval)
        print `Date(date) + Interval(interval)`

if __name__ == '__main__':
    test()

# vim: set filetype=python ts=4 sw=4 et si
