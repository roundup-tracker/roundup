import sys, os, time, shutil

from roundup.hyperdb import String, Password, Link, Multilink, Date, \
    Interval, DatabaseError, Boolean, Number
from roundup import date, password
from roundup.indexer import Indexer

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
    status.create(name="unread")
    status.create(name="in-progress")
    status.create(name="testing")
    status.create(name="resolved")
    user.create(username='one')
    user.create(username='two')
    db.commit()

class config:
    DATABASE='_test_dir'
    GADFLY_DATABASE = ('test', DATABASE)
    MAILHOST = 'localhost'
    MAIL_DOMAIN = 'fill.me.in.'
    TRACKER_NAME = 'Roundup issue tracker'
    TRACKER_EMAIL = 'issue_tracker@%s'%MAIL_DOMAIN
    TRACKER_WEB = 'http://some.useful.url/'
    ADMIN_EMAIL = 'roundup-admin@%s'%MAIL_DOMAIN
    FILTER_POSITION = 'bottom'      # one of 'top', 'bottom', 'top and bottom'
    ANONYMOUS_ACCESS = 'deny'       # either 'deny' or 'allow'
    ANONYMOUS_REGISTER = 'deny'     # either 'deny' or 'allow'
    MESSAGES_TO_AUTHOR = 'no'       # either 'yes' or 'no'
    EMAIL_SIGNATURE_POSITION = 'bottom'

def main(backendname, time=time.time, numissues=10):
    try:
        exec('from roundup.backends import %s as backend'%backendname)
    except ImportError:
        return

    if os.path.exists(config.DATABASE):
        shutil.rmtree(config.DATABASE)

    times = []
    db = backend.Database(config, 'test')
    setupSchema(db, backend)

    # create a whole bunch of stuff
    for i in range(numissues):
        db.issue.create(**{'title': 'issue %s'%i})
        for j in range(10):
            db.issue.set(str(i+1), status='2', assignedto='2', nosy=[])
            db.issue.set(str(i+1), status='1', assignedto='1', nosy=['1','2'])
        db.user.create(**{'username': 'user %s'%i})
        for j in range(10):
            db.user.set(str(i+1), assignable=1)
            db.user.set(str(i+1), assignable=0)
    db.commit()
    sys.stdout.write('%7s: %-6d'%(backendname, numissues))
    sys.stdout.flush()

    times.append(('start', time()))

    # fetch
    for i in db.issue.list():
        db.issue.get(i, 'title')
    times.append(('fetch', time()))

    # journals
    for i in db.issue.list():
        db.issue.history(i)
    times.append(('journal', time()))

    # "calculated" props
    for i in db.issue.list():
        db.issue.get(i, 'activity')
        db.issue.get(i, 'creator')
        db.issue.get(i, 'creation')
    times.append(('jprops', time()))

    # lookup
    for i in range(numissues):
        db.user.lookup('user %s'%i)
    times.append(('lookup', time()))

    # filter
    for i in range(100):
        db.issue.filter(None, {'nosy': ['1'], 'assignedto': '1',
            'title':'issue'}, ('+', 'activity'), ('+', 'status'))
    times.append(('filter', time()))

    # results
    last = None
    for event, stamp in times:
        if last is None:
            first = stamp
        else:
            sys.stdout.write(' %-6.2f'%(stamp-last))
        last = stamp
    print ' %-6.2f'%(last-first)
    sys.stdout.flush()

if __name__ == '__main__':
    #      0         1         2         3         4         5         6
    #      01234567890123456789012345678901234567890123456789012345678901234
    print 'Test name       fetch  journl jprops lookup filter TOTAL '
    for name in 'anydbm bsddb bsddb3 metakit sqlite'.split():
        main(name)
    for name in 'anydbm bsddb bsddb3 metakit sqlite'.split():
        main(name, numissues=20)
#    for name in 'anydbm bsddb bsddb3 metakit sqlite'.split():
#        main(name, numissues=100)

