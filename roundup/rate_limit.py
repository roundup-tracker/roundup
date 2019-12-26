# Originaly from
# https://smarketshq.com/implementing-gcra-in-python-5df1f11aaa96?gi=4b9725f99bfa
# with imports, modifications for python 2, implementation of
# set/get_tat and marshaling as string, support for testonly
# and status method.

from datetime import timedelta, datetime


class RateLimit:  # pylint: disable=too-few-public-methods
    def __init__(self, count, period):
        self.count = count
        self.period = period

    @property
    def inverse(self):
        return self.period.total_seconds() / self.count


class Gcra:
    def __init__(self):
        self.memory = {}

    def get_tat(self, key):
        # This should return a previous tat for the key or the current time.
        if key in self.memory:
            return self.memory[key]
        else:
            return datetime.min

    def set_tat(self, key, tat):
        self.memory[key] = tat

    def get_tat_as_string(self, key):
        # get value as string:
        #  YYYY-MM-DDTHH:MM:SS.mmmmmm
        # to allow it to be marshalled/unmarshaled
        if key in self.memory:
            return self.memory[key].isoformat()
        else:
            return datetime.min.isoformat()

    def set_tat_as_string(self, key, tat):
        # Take value as string and unmarshall:
        #  YYYY-MM-DDTHH:MM:SS.mmmmmm
        # to datetime
        self.memory[key] = datetime.strptime(tat, "%Y-%m-%dT%H:%M:%S.%f")

    def update(self, key, limit, testonly=False):
        '''Determine if the item associated with the key should be
           rejected given the RateLimit limit.
        '''
        now = datetime.utcnow()
        tat = max(self.get_tat(key), now)
        separation = (tat - now).total_seconds()
        max_interval = limit.period.total_seconds() - limit.inverse
        if separation > max_interval:
            reject = True
        else:
            reject = False
            if not testonly:
                new_tat = max(tat, now) + timedelta(seconds=limit.inverse)
                self.set_tat(key, new_tat)
        return reject

    def status(self, key, limit):
        '''Return status suitable for displaying as headers:
            X-RateLimit-Limit: calls allowed per period. Period/window
                is not specified in any api I found.
            X-RateLimit-Limit-Period: Non standard. Defines period in
                seconds for RateLimit-Limit.
            X-RateLimit-Remaining: How many calls are left in this window.
            X-RateLimit-Reset: window ends in this many seconds (not an
                 epoch timestamp) and all RateLimit-Limit calls are
                 available again.
            Retry-After: if user's request fails, this is the next time there
                 will be at least 1 available call to be consumed.
        '''

        ret = {}
        tat = self.get_tat(key)
        # static defined headers according to limit
        # all values are strings as that is required when used as headers
        ret['X-RateLimit-Limit'] = str(limit.count)
        ret['X-RateLimit-Limit-Period'] = str(
                                           int(
                                            limit.period.total_seconds())
                                          )

        # status of current limit as of now
        now = datetime.utcnow()

        current_count = int((limit.period - (tat - now)).total_seconds() /
                            limit.inverse)
        ret['X-RateLimit-Remaining'] = str(min(current_count, limit.count))

        # tat_in_epochsec = (tat - datetime(1970, 1, 1)).total_seconds()
        seconds_to_tat = (tat - now).total_seconds()
        ret['X-RateLimit-Reset'] = str(max(seconds_to_tat, 0))
        ret['X-RateLimit-Reset-date'] = "%s" % tat
        ret['Now'] = str((now - datetime(1970, 1, 1)).total_seconds())
        ret['Now-date'] = "%s" % now

        if self.update(key, limit, testonly=True):
            # A new request would be rejected if it was processes.
            # The user has to wait until an item is dequeued.
            # One item is dequeued every limit.inverse seconds.
            ret['Retry-After'] = str(int(limit.inverse))
            ret['Retry-After-Timestamp'] = "%s" % \
                    (now + timedelta(seconds=limit.inverse))  # noqa: E127
        else:
            # if we are not rejected, the user can post another
            # attempt immediately.
            # Do we even need this header if not rejected?
            # RFC implies this is used with a 503 (or presumably
            # 429 which may postdate the rfc). So if no error, no header?
            # ret['Retry-After'] = '0'
            # ret['Retry-After-Timestamp'] = str(ret['Now-date'])
            pass

        return ret
