import os, unittest, shutil
from db_test_base import setupTracker

class UserAuditorTest(unittest.TestCase):
    def setUp(self):
        self.dirname = '_test_user_auditor'
        self.instance = setupTracker(self.dirname)
        self.db = self.instance.open('admin')

        try:
            import pytz
            self.pytz = True
        except ImportError:
            self.pytz = False

        self.db.user.create(username='kyle', address='kyle@example.com',
            realname='Kyle Broflovski', roles='User')

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH): raise

    def testBadTimezones(self):
        self.assertRaises(ValueError, self.db.user.create, username='eric', timezone='24')

        userid = self.db.user.lookup('kyle')

        self.assertRaises(ValueError, self.db.user.set, userid, timezone='3000')
        self.assertRaises(ValueError, self.db.user.set, userid, timezone='24')
        self.assertRaises(ValueError, self.db.user.set, userid, timezone='-24')
        self.assertRaises(ValueError, self.db.user.set, userid, timezone='-3000')

        if self.pytz:
            try:
                from pytz import UnknownTimeZoneError
            except:
                UnknownTimeZoneError = ValueError
            self.assertRaises(UnknownTimeZoneError, self.db.user.set, userid, timezone='MiddleOf/Nowhere')

    def testGoodTimezones(self):
        self.db.user.create(username='test_user01', timezone='12')

        if self.pytz:
            self.db.user.create(username='test_user02', timezone='MST')

        userid = self.db.user.lookup('kyle')

        # TODO: roundup should accept non-integer offsets since those are valid
        # this is the offset for Tehran, Iran
        #self.db.user.set(userid, timezone='3.5')

        self.db.user.set(userid, timezone='-23')
        self.db.user.set(userid, timezone='23')
        self.db.user.set(userid, timezone='0')

        if self.pytz:
            self.db.user.set(userid, timezone='US/Eastern')

    def testBadEmailAddresses(self):
        userid = self.db.user.lookup('kyle')
        self.assertRaises(ValueError, self.db.user.set, userid, address='kyle @ example.com')
        self.assertRaises(ValueError, self.db.user.set, userid, address='one@example.com,two@example.com')
        self.assertRaises(ValueError, self.db.user.set, userid, address='weird@@example.com')
        self.assertRaises(ValueError, self.db.user.set, userid, address='embedded\nnewline@example.com')
        # verify that we check alternates as well
        self.assertRaises(ValueError, self.db.user.set, userid, alternate_addresses='kyle @ example.com')
        # make sure we accept local style addresses
        self.db.user.set(userid, address='kyle')
        # verify we are case insensitive
        self.db.user.set(userid, address='kyle@EXAMPLE.COM')

    def testUniqueEmailAddresses(self):
        self.db.user.create(username='kenny', address='kenny@example.com', alternate_addresses='sp_ken@example.com')
        self.assertRaises(ValueError, self.db.user.create, username='test_user01', address='kenny@example.com')
        uid = self.db.user.create(username='eric', address='eric@example.com')
        self.assertRaises(ValueError, self.db.user.set, uid, address='kenny@example.com')

        # make sure we check alternates
        self.assertRaises(ValueError, self.db.user.set, uid, address='kenny@example.com')
        self.assertRaises(ValueError, self.db.user.set, uid, address='sp_ken@example.com')
        self.assertRaises(ValueError, self.db.user.set, uid, alternate_addresses='kenny@example.com')

    def testBadRoles(self):
        userid = self.db.user.lookup('kyle')
        self.assertRaises(ValueError, self.db.user.set, userid, roles='BadRole')
        self.assertRaises(ValueError, self.db.user.set, userid, roles='User,BadRole')

    def testGoodRoles(self):
        userid = self.db.user.lookup('kyle')
        # make sure we handle commas in weird places
        self.db.user.set(userid, roles='User,')
        self.db.user.set(userid, roles=',User')
        # make sure we strip whitespace
        self.db.user.set(userid, roles='    User   ')
        # check for all-whitespace (treat as no role)
        self.db.user.set(userid, roles='   ')

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(UserAuditorTest))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

# vim: filetype=python sts=4 sw=4 et si
