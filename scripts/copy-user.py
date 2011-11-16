#!/usr/bin/env python
# Copyright (C) 2003 by Intevation GmbH
# Author:
# Thomas Arendsen Hein <thomas@intevation.de>
#
# This program is free software dual licensed under the GPL (>=v2)
# and the Roundup Licensing (see COPYING.txt in the roundup distribution).

"""
copy-user <instance-home> <instance-home> <userid> [<userid>...]

Copy one or more Roundup users from one tracker instance to another.
Example:
    copy-user /roundup/tracker1 /roundup/tracker2 `seq 3 10` 14 16
    (copies users 3, 4, 5, 6, 7, 8, 9, 10, 14 and 16)
"""

import sys
import roundup.instance


def copy_user(home1, home2, *userids):
    """Copy users which are listed by userids from home1 to home2"""

    copyattribs = ['username', 'password', 'address', 'realname', 'phone',
                   'organisation', 'alternate_addresses', 'roles', 'timezone']

    try:
        instance1 = roundup.instance.open(home1)
        print "Opened source instance: %s" % home1
    except:
        print "Can't open source instance: %s" % home1
        sys.exit(1)

    try:
        instance2 = roundup.instance.open(home2)
        print "Opened target instance: %s" % home2
    except:
        print "Can't open target instance: %s" % home2
        sys.exit(1)

    db1 = instance1.open('admin')
    db2 = instance2.open('admin')

    userlist = db1.user.list()
    for userid in userids:
        try:
            userid = str(int(userid))
        except ValueError, why:
            print "Not a numeric user id: %s  Skipping ..." % (userid,)
            continue
        if userid not in userlist:
            print "User %s not in source instance. Skipping ..." % userid
            continue

        user = {}
        for attrib in copyattribs:
            value = db1.user.get(userid, attrib)
            if value:
                user[attrib] = value
        try:
            db2.user.lookup(user['username'])
            print "User %s: Username '%s' exists in target instance. Skipping ..." % (userid, user['username'])
            continue
        except KeyError, why:
            pass
        print "Copying user %s (%s) ..." % (userid, user['username'])
        db2.user.create(**user)

    db2.commit()
    db2.close()
    print "Closed target instance."
    db1.close()
    print "Closed source instance."


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print __doc__
        sys.exit(1)
    else:
        copy_user(*sys.argv[1:])

