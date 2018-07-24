from __future__ import print_function
import sys, os, time

from roundup.hyperdb import String, Password, Link, Multilink, Date, \
    Interval, DatabaseError, Boolean, Number
from roundup import date, password

from .db_test_base import config

def setupSchema(db, module):
    status = module.Class(db, "status", name=String())
    status.setkey("name")
    user = module.Class(db, "user", username=String(), password=Password(),
        assignable=Boolean(), age=Number(), roles=String())
    user.setkey("username")
    file = module.FileClass(db, "file", name=String(), type=String(),
        comment=String(indexme="yes"))
    issue = module.IssueClass(db, "issue", title=String(indexme="yes"),
        status=Link("status"), nosy=Multilink("user"), deadline=Date(),
        foo=Interval(), files=Multilink("file"), assignedto=Link('user'))
    session = module.Class(db, 'session', title=String())
    session.disableJournalling()
    db.post_init()
    db.commit()

def main(backendname, time=time.time, numissues=10):
    try:
        exec('from roundup.backends import %s as backend'%backendname)
    except ImportError:
        return

    times = []

    config.DATABASE = os.path.join('_benchmark', '%s-%s'%(backendname,
        numissues))
    if not os.path.exists(config.DATABASE):
        db = backend.Database(config, 'admin')
        setupSchema(db, backend)
        # create a whole bunch of stuff
        db.user.create(**{'username': 'admin'})
        db.status.create(name="unread")
        db.status.create(name="in-progress")
        db.status.create(name="testing")
        db.status.create(name="resolved")
        pc = -1
        for i in range(numissues):
            db.user.create(**{'username': 'user %s'%i})
            for j in range(10):
                db.user.set(str(i+1), assignable=1)
                db.user.set(str(i+1), assignable=0)
            db.issue.create(**{'title': 'issue %s'%i})
            for j in range(10):
                db.issue.set(str(i+1), status='2', assignedto='2', nosy=[])
                db.issue.set(str(i+1), status='1', assignedto='1',
                    nosy=['1','2'])
            if (i*100//numissues) != pc:
                pc = (i*100//numissues)
                sys.stdout.write("%d%%\r"%pc)
                sys.stdout.flush()
            db.commit()
    else:
        db = backend.Database(config, 'admin')
        setupSchema(db, backend)

    sys.stdout.write('%7s: %-6d'%(backendname, numissues))
    sys.stdout.flush()

    times.append(('start', time()))

    # fetch
    db.clearCache()
    for i in db.issue.list():
        db.issue.get(i, 'title')
    times.append(('fetch', time()))

    # journals
    db.clearCache()
    for i in db.issue.list():
        db.issue.history(i)
    times.append(('journal', time()))

    # "calculated" props
    db.clearCache()
    for i in db.issue.list():
        db.issue.get(i, 'activity')
        db.issue.get(i, 'creator')
        db.issue.get(i, 'creation')
    times.append(('jprops', time()))

    # lookup
    db.clearCache()
    for i in range(numissues):
        db.user.lookup('user %s'%i)
    times.append(('lookup', time()))

    # filter
    db.clearCache()
    for i in range(100):
        db.issue.filter(None, {'assignedto': '1', 'title':'issue'},
            ('+', 'activity'), ('+', 'status'))
    times.append(('filter', time()))

    # filter with multilink
    db.clearCache()
    for i in range(100):
        db.issue.filter(None, {'nosy': ['1'], 'assignedto': '1',
            'title':'issue'}, ('+', 'activity'), ('+', 'status'))
    times.append(('filtml', time()))

    # results
    last = None
    for event, stamp in times:
        if last is None:
            first = stamp
        else:
            sys.stdout.write(' %-6.2f'%(stamp-last))
        last = stamp
    print(' %-6.2f'%(last-first))
    sys.stdout.flush()

if __name__ == '__main__':
    #      0         1         2         3         4         5         6
    #      01234567890123456789012345678901234567890123456789012345678901234
    print('Test name       fetch  journl jprops lookup filter filtml TOTAL ')
    for name in 'anydbm metakit sqlite'.split():
        main(name)
    for name in 'anydbm metakit sqlite'.split():
        main(name, numissues=20)
    for name in 'anydbm metakit sqlite'.split():
        main(name, numissues=100)
    # don't even bother benchmarking the dbm backends > 100!
    for name in 'metakit sqlite'.split():
        main(name, numissues=1000)

# vim: set et sts=4 sw=4 :
