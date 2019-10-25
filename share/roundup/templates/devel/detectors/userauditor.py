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

import re

# regular expression thanks to: http://www.regular-expressions.info/email.html
# this is the "99.99% solution for syntax only".
email_regexp = (r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*", r"(localhost|(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9]))")
email_rfc = re.compile('^' + email_regexp[0] + '@' + email_regexp[1] + '$', re.IGNORECASE)
email_local = re.compile('^' + email_regexp[0] + '$', re.IGNORECASE)

valid_username = re.compile('^[a-z0-9_@!%.+-]+$', re.IGNORECASE)

def valid_address(address):
    ''' If we see an @-symbol in the address then check against the full
        RFC syntax. Otherwise it is a local-only address so only check
        the local part of the RFC syntax.
    '''
    if '@' in address:
        return email_rfc.match(address)
    else:
        return email_local.match(address)

def get_addresses(user):
    ''' iterate over all known addresses in a newvalues dict
        this takes of the address/alterate_addresses handling
    '''
    if 'address' in user:
        yield user['address']
    if user.get('alternate_addresses', None):
        for address in user['alternate_addresses'].split('\n'):
            yield address

def audit_user_fields(db, cl, nodeid, newvalues):
    ''' Make sure user properties are valid.

        - email address is syntactically valid
        - email address is unique
        - roles specified exist
        - timezone is valid
        - username matches A-z0-9_-.@!+% (email symbols)
    '''

    if 'username' in newvalues:
        if not valid_username.match(newvalues['username']):
            raise ValueError("Username/Login Name must consist only of the letters a-z (any case), digits 0-9 and the symbols: @._-!+%")
        
    for address in get_addresses(newvalues):
        if not valid_address(address):
            raise ValueError('Email address syntax is invalid "%s"'%address)

        check_main = db.user.stringFind(address=address)
        # make sure none of the alts are owned by anyone other than us (x!=nodeid)
        check_alts = [x for x in db.user.filter(None, {'alternate_addresses' : address}) if x != nodeid]
        if check_main or check_alts:
            raise ValueError('Email address %s already in use' % address)

    newroles = newvalues.get('roles')
    if newroles:
        for rolename in [r.lower().strip() for r in newroles.split(',')]:
            if rolename and rolename not in db.security.role:
                raise ValueError('Role "%s" does not exist'%rolename)

    tz = newvalues.get('timezone', None)
    if tz:
        # if they set a new timezone validate the timezone by attempting to
        # use it before we store it to the db.
        import roundup.date
        import datetime
        try:
            TZ = roundup.date.get_timezone(tz)
            dt = datetime.datetime.now()
            local = TZ.localize(dt).utctimetuple()
        except IOError:
            raise ValueError('Timezone "%s" does not exist' % tz)
        except ValueError:
            raise ValueError('Timezone "%s" exceeds valid range [-23...23]' % tz)

def init(db):
    # fire before changes are made
    db.user.audit('set', audit_user_fields)
    db.user.audit('create', audit_user_fields)

# vim: sts=4 sw=4 et si
