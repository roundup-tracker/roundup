import unittest, os, shutil

from roundup.backends import anydbm
from roundup.hyperdb import String, Link, Multilink, Date, Interval, Class

def setupSchema(db):
    status = Class(db, "status", name=String())
    status.setkey("name")
    status.create(name="unread")
    status.create(name="in-progress")
    status.create(name="testing")
    status.create(name="resolved")
    Class(db, "user", username=String(), password=String())
    Class(db, "issue", title=String(), status=Link("status"))

class DBTestCase(unittest.TestCase):
    def setUp(self):
        class Database(anydbm.Database):
            pass
        # remove previous test, ignore errors
        if os.path.exists('_test_dir'):
            shutil.rmtree('_test_dir')
        os.mkdir('_test_dir')
        self.db = Database('_test_dir', 'test')
        setupSchema(self.db)

    def tearDown(self):
        self.db.close()
        shutil.rmtree('_test_dir')

    def testChanges(self):
        self.db.issue.create(title="spam", status='1')
        self.db.issue.create(title="eggs", status='2')
        self.db.issue.create(title="ham", status='4')
        self.db.issue.create(title="arguments", status='2')
        self.db.issue.create(title="abuse", status='1')
        self.db.issue.addprop(fixer=Link("user"))
        self.db.issue.getprops()
#{"title": <hyperdb.String>, "status": <hyperdb.Link to "status">,
#"user": <hyperdb.Link to "user">}
        self.db.issue.set('5', status=2)
        self.db.issue.get('5', "status")
        self.db.status.get('2', "name")
        self.db.issue.get('5', "title")
        self.db.issue.find(status = self.db.status.lookup("in-progress"))
        self.db.issue.history('5')
        self.db.status.history('1')
        self.db.status.history('2')


def suite():
   return unittest.makeSuite(DBTestCase, 'test')

