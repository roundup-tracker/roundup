from __future__ import nested_scopes

import unittest
from cgi import FieldStorage, MiniFieldStorage

from roundup import hyperdb
from roundup.date import Date, Interval
from roundup.cgi.actions import *
from roundup.cgi.exceptions import Redirect, Unauthorised, SeriousError

class MockNull:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            self.__dict__[key] = value

    def __call__(self, *args, **kwargs): return MockNull()
    def __getattr__(self, name):
        # This allows assignments which assume all intermediate steps are Null
        # objects if they don't exist yet.
        #
        # For example (with just 'client' defined):
        #
        # client.db.config.TRACKER_WEB = 'BASE/'
        self.__dict__[name] = MockNull()
        return getattr(self, name)

    def __getitem__(self, key): return self
    def __nonzero__(self): return 0
    def __str__(self): return ''
    def __repr__(self): return '<MockNull 0x%x>'%id(self)

def true(*args, **kwargs):
    return 1

class ActionTestCase(unittest.TestCase):
    def setUp(self):
        self.form = FieldStorage()
        self.client = MockNull()
        self.client.form = self.form

class ShowActionTestCase(ActionTestCase):
    def assertRaisesMessage(self, exception, callable, message, *args,
                            **kwargs):
        """An extension of assertRaises, which also checks the exception
        message. We need this because we rely on exception messages when
        redirecting.
        """
        try:
            callable(*args, **kwargs)
        except exception, msg:
            self.assertEqual(str(msg), message)
        else:
            if hasattr(excClass,'__name__'):
                excName = excClass.__name__
            else:
                excName = str(excClass)
            raise self.failureException, excName

    def testShowAction(self):
        self.client.base = 'BASE/'

        action = ShowAction(self.client)
        self.assertRaises(ValueError, action.handle)

        self.form.value.append(MiniFieldStorage('@type', 'issue'))
        self.assertRaises(SeriousError, action.handle)

        self.form.value.append(MiniFieldStorage('@number', '1'))
        self.assertRaisesMessage(Redirect, action.handle, 'BASE/issue1')

    def testShowActionNoType(self):
        action = ShowAction(self.client)
        self.assertRaises(ValueError, action.handle)
        self.form.value.append(MiniFieldStorage('@number', '1'))
        self.assertRaisesMessage(ValueError, action.handle,
            'No type specified')

class RetireActionTestCase(ActionTestCase):
    def testRetireAction(self):
        self.client.db.security.hasPermission = true
        self.client.ok_message = []
        RetireAction(self.client).handle()
        self.assert_(len(self.client.ok_message) == 1)

    def testNoPermission(self):
        self.assertRaises(Unauthorised, RetireAction(self.client).execute)

    def testDontRetireAdminOrAnonymous(self):
        self.client.db.security.hasPermission=true
        # look up the user class
        self.client.classname = 'user'
        # but always look up admin, regardless of nodeid
        self.client.db.user.get = lambda a,b: 'admin'
        self.assertRaises(ValueError, RetireAction(self.client).handle)
        # .. or anonymous
        self.client.db.user.get = lambda a,b: 'anonymous'
        self.assertRaises(ValueError, RetireAction(self.client).handle)

class SearchActionTestCase(ActionTestCase):
    def setUp(self):
        ActionTestCase.setUp(self)
        self.action = SearchAction(self.client)

class StandardSearchActionTestCase(SearchActionTestCase):
    def testNoPermission(self):
        self.assertRaises(Unauthorised, self.action.execute)

    def testQueryName(self):
        self.assertEqual(self.action.getQueryName(), '')

        self.form.value.append(MiniFieldStorage('@queryname', 'foo'))
        self.assertEqual(self.action.getQueryName(), 'foo')

class FakeFilterVarsTestCase(SearchActionTestCase):
    def setUp(self):
        SearchActionTestCase.setUp(self)
        self.client.db.classes.getprops = lambda: {'foo': hyperdb.Multilink('foo')}

    def assertFilterEquals(self, expected):
        self.action.fakeFilterVars()
        self.assertEqual(self.form.getvalue('@filter'), expected)

    def testEmptyMultilink(self):
        self.form.value.append(MiniFieldStorage('foo', ''))
        self.form.value.append(MiniFieldStorage('foo', ''))

        self.assertFilterEquals(None)

    def testNonEmptyMultilink(self):
        self.form.value.append(MiniFieldStorage('foo', ''))
        self.form.value.append(MiniFieldStorage('foo', '1'))

        self.assertFilterEquals('foo')

    def testEmptyKey(self):
        self.form.value.append(MiniFieldStorage('foo', ''))
        self.assertFilterEquals(None)

    def testStandardKey(self):
        self.form.value.append(MiniFieldStorage('foo', '1'))
        self.assertFilterEquals('foo')

    def testStringKey(self):
        self.client.db.classes.getprops = lambda: {'foo': hyperdb.String()}
        self.form.value.append(MiniFieldStorage('foo', 'hello'))
        self.assertFilterEquals('foo')

    def testTokenizedStringKey(self):
        self.client.db.classes.getprops = lambda: {'foo': hyperdb.String()}
        self.form.value.append(MiniFieldStorage('foo', 'hello world'))

        self.assertFilterEquals('foo')

        # The single value gets replaced with the tokenized list.
        self.assertEqual([x.value for x in self.form['foo']], ['hello', 'world'])

class CollisionDetectionTestCase(ActionTestCase):
    def setUp(self):
        ActionTestCase.setUp(self)
        self.action = EditItemAction(self.client)
        self.now = Date('.')
        # round off for testing
        self.now.second = int(self.now.second)

    def testLastUserActivity(self):
        self.assertEqual(self.action.lastUserActivity(), None)

        self.client.form.value.append(MiniFieldStorage('@lastactivity', str(self.now)))
        self.assertEqual(self.action.lastUserActivity(), self.now)

    def testLastNodeActivity(self):
        self.action.classname = 'issue'
        self.action.nodeid = '1'

        def get(nodeid, propname):
            self.assertEqual(nodeid, '1')
            self.assertEqual(propname, 'activity')
            return self.now
        self.client.db.issue.get = get

        self.assertEqual(self.action.lastNodeActivity(), self.now)

    def testCollision(self):
        self.failUnless(self.action.detectCollision(self.now, self.now + Interval("1d")))
        self.failIf(self.action.detectCollision(self.now, self.now - Interval("1d")))
        self.failIf(self.action.detectCollision(None, self.now))

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(RetireActionTestCase))
    suite.addTest(unittest.makeSuite(StandardSearchActionTestCase))
    suite.addTest(unittest.makeSuite(FakeFilterVarsTestCase))
    suite.addTest(unittest.makeSuite(ShowActionTestCase))
    suite.addTest(unittest.makeSuite(CollisionDetectionTestCase))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

