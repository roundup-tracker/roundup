# Copyright (c) 2003 Richard Jones (richard@mechanicalcat.net)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
#$Id: userauditor.py,v 1.5 2007-08-31 17:45:17 jpend Exp $

def audit_user_fields(db, cl, nodeid, newvalues):
    ''' Make sure user properties are valid.

        - email address has no spaces in it
        - roles specified exist
        - timezone is valid
    '''
    if newvalues.has_key('address') and ' ' in newvalues['address']:
        raise ValueError, 'Email address must not contain spaces'

    for rolename in [r.lower().strip() for r in newvalues.get('roles', '').split(',')]:
            if rolename and not db.security.role.has_key(rolename):
                raise ValueError, 'Role "%s" does not exist'%rolename

    if newvalues.has_key('timezone'):
        # validate the timezone by attempting to use it
        # before we store it to the db.
        import roundup.date
        import datetime
        try:
            tz = newvalues['timezone']
            TZ = roundup.date.get_timezone(tz)
            dt = datetime.datetime.now()
            local = TZ.localize(dt).utctimetuple()
        except IOError:
            raise ValueError, 'Timezone "%s" does not exist' % tz
        except ValueError:
            raise ValueError, 'Timezone "%s" exceeds valid range [-23...23]' % tz

def init(db):
    # fire before changes are made
    db.user.audit('set', audit_user_fields)
    db.user.audit('create', audit_user_fields)

# vim: sts=4 sw=4 et si
