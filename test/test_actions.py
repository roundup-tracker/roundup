import unittest
from cgi import FieldStorage, MiniFieldStorage

from roundup import hyperdb
from roundup.date import Date, Interval
from roundup.cgi.actions import *
from roundup.cgi.exceptions import Redirect, Unauthorised, SeriousError

from mocknull import MockNull

def true(*args, **kwargs):
    return 1

class ActionTestCase(unittest.TestCase):
    def setUp(self):
        self.form = FieldStorage()
        self.client = MockNull()
        self.client.form = self.form
        class TemplatingUtils:
            pass
        self.client.instance.interfaces.TemplatingUtils = TemplatingUtils

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
            if hasattr(exception, '__name__'):
                excName = exception.__name__
            else:
                excName = str(exception)
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
        self.client.db.classes.get_transitive_prop = lambda x: \
            hyperdb.Multilink('foo')

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
        self.client.db.classes.get_transitive_prop = lambda x: hyperdb.String()
        self.form.value.append(MiniFieldStorage('foo', 'hello world'))

        self.assertFilterEquals('foo')

        # The single value gets replaced with the tokenized list.
        self.assertEqual([x.value for x in self.form['foo']],
            ['hello', 'world'])

class CollisionDetectionTestCase(ActionTestCase):
    def setUp(self):
        ActionTestCase.setUp(self)
        self.action = EditItemAction(self.client)
        self.now = Date('.')
        # round off for testing
        self.now.second = int(self.now.second)

    def testLastUserActivity(self):
        self.assertEqual(self.action.lastUserActivity(), None)

        self.client.form.value.append(
            MiniFieldStorage('@lastactivity', str(self.now)))
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
        # fake up an actual change
        self.action.classname = 'test'
        self.action.nodeid = '1'
        self.client.parsePropsFromForm = lambda: ({('test','1'):{1:1}}, [])
        self.failUnless(self.action.detectCollision(self.now,
            self.now + Interval("1d")))
        self.failIf(self.action.detectCollision(self.now,
            self.now - Interval("1d")))
        self.failIf(self.action.detectCollision(None, self.now))

class LoginTestCase(ActionTestCase):
    def setUp(self):
        ActionTestCase.setUp(self)
        self.client.error_message = []

        # set the db password to 'right'
        self.client.db.user.get = lambda a,b: 'right'

        # unless explicitly overridden, we should never get here
        self.client.opendb = lambda a: self.fail(
            "Logged in, but we shouldn't be.")

    def assertLoginLeavesMessages(self, messages, username=None, password=None):
        if username is not None:
            self.form.value.append(MiniFieldStorage('__login_name', username))
        if password is not None:
            self.form.value.append(
                MiniFieldStorage('__login_password', password))

        LoginAction(self.client).handle()
        self.assertEqual(self.client.error_message, messages)

    def testNoUsername(self):
        self.assertLoginLeavesMessages(['Username required'])

    def testInvalidUsername(self):
        def raiseKeyError(a):
            raise KeyError
        self.client.db.user.lookup = raiseKeyError
        self.assertLoginLeavesMessages(['Invalid login'], 'foo')

    def testInvalidPassword(self):
        self.assertLoginLeavesMessages(['Invalid login'], 'foo', 'wrong')

    def testNoWebAccess(self):
        self.assertLoginLeavesMessages(['You do not have permission to login'],
                                        'foo', 'right')

    def testCorrectLogin(self):
        self.client.db.security.hasPermission = lambda *args, **kwargs: True

        def opendb(username):
            self.assertEqual(username, 'foo')
        self.client.opendb = opendb

        self.assertLoginLeavesMessages([], 'foo', 'right')

class EditItemActionTestCase(ActionTestCase):
    def setUp(self):
        ActionTestCase.setUp(self)
        self.result = []
        class AppendResult:
            def __init__(inner_self, name):
                inner_self.name = name
            def __call__(inner_self, *args, **kw):
                self.result.append((inner_self.name, args, kw))
                if inner_self.name == 'set':
                    return kw
                return '17'

        self.client.db.security.hasPermission = true
        self.client.classname = 'issue'
        self.client.base = 'http://tracker/'
        self.client.nodeid = '4711'
        self.client.template = 'item'
        self.client.db.classes.create = AppendResult('create')
        self.client.db.classes.set = AppendResult('set')
        self.client.db.classes.getprops = lambda: \
            ({'messages':hyperdb.Multilink('msg')
             ,'content':hyperdb.String()
             ,'files':hyperdb.Multilink('file')
             ,'msg':hyperdb.Link('msg')
             })
        self.action = EditItemAction(self.client)

    def testMessageAttach(self):
        expect = \
            [ ('create',(),{'content':'t'})
            , ('set',('4711',), {'messages':['23','42','17']})
            ]
        self.client.db.classes.get = lambda a, b:['23','42']
        self.client.parsePropsFromForm = lambda: \
            ( {('msg','-1'):{'content':'t'},('issue','4711'):{}}
            , [('issue','4711','messages',[('msg','-1')])]
            )
        try :
            self.action.handle()
        except Redirect, msg:
            pass
        self.assertEqual(expect, self.result)

    def testFileAttach(self):
        expect = \
            [('create',(),{'content':'t','type':'text/plain','name':'t.txt'})
            ,('set',('4711',),{'files':['23','42','17']})
            ]
        self.client.db.classes.get = lambda a, b:['23','42']
        self.client.parsePropsFromForm = lambda: \
            ( {('file','-1'):{'content':'t','type':'text/plain','name':'t.txt'}
              ,('issue','4711'):{}
              }
            , [('issue','4711','messages',[('msg','-1')])
              ,('issue','4711','files',[('file','-1')])
              ,('msg','-1','files',[('file','-1')])
              ]
            )
        try :
            self.action.handle()
        except Redirect, msg:
            pass
        self.assertEqual(expect, self.result)

    def testLinkExisting(self):
        expect = [('set',('4711',),{'messages':['23','42','1']})]
        self.client.db.classes.get = lambda a, b:['23','42']
        self.client.parsePropsFromForm = lambda: \
            ( {('issue','4711'):{},('msg','1'):{}}
            , [('issue','4711','messages',[('msg','1')])]
            )
        try :
            self.action.handle()
        except Redirect, msg:
            pass
        self.assertEqual(expect, self.result)

    def testLinkNewToExisting(self):
        expect = [('create',(),{'msg':'1','title':'TEST'})]
        self.client.db.classes.get = lambda a, b:['23','42']
        self.client.parsePropsFromForm = lambda: \
            ( {('issue','-1'):{'title':'TEST'},('msg','1'):{}}
            , [('issue','-1','msg',[('msg','1')])]
            )
        try :
            self.action.handle()
        except Redirect, msg:
            pass
        self.assertEqual(expect, self.result)

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(RetireActionTestCase))
    suite.addTest(unittest.makeSuite(StandardSearchActionTestCase))
    suite.addTest(unittest.makeSuite(FakeFilterVarsTestCase))
    suite.addTest(unittest.makeSuite(ShowActionTestCase))
    suite.addTest(unittest.makeSuite(CollisionDetectionTestCase))
    suite.addTest(unittest.makeSuite(LoginTestCase))
    suite.addTest(unittest.makeSuite(EditItemActionTestCase))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

# vim: set et sts=4 sw=4 :
