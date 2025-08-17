from __future__ import print_function
import unittest
import time

from roundup.anypy.cgi_ import FieldStorage, MiniFieldStorage
from roundup.cgi.templating import *
from roundup.cgi.ZTUtils.Iterator import Iterator
from roundup.test import memorydb
from .test_actions import MockNull, true
from .html_norm import NormalizingHtmlParser


import pytest
from .pytest_patcher import mark_class

try:
    from markdown2 import __version_info__ as md2__version_info__
except ImportError:
    md2__version_info__ = (0,0,0)

if ReStructuredText:
    skip_rst = lambda func, *args, **kwargs: func
else:
    skip_rst = mark_class(pytest.mark.skip(
        reason='ReStructuredText not available'))

import roundup.cgi.templating
if roundup.cgi.templating._import_mistune():
    skip_mistune = lambda func, *args, **kwargs: func
else:
    skip_mistune = mark_class(pytest.mark.skip(
        reason='mistune not available'))

if roundup.cgi.templating._import_markdown2():
    skip_markdown2 = lambda func, *args, **kwargs: func
else:
    skip_markdown2 = mark_class(pytest.mark.skip(
        reason='markdown2 not available'))

if roundup.cgi.templating._import_markdown():
    skip_markdown = lambda func, *args, **kwargs: func
else:
    skip_markdown = mark_class(pytest.mark.skip(
        reason='markdown not available'))

from roundup.anypy.strings import u2s, s2u

from roundup.backends.sessions_common import SessionCommon

class MockConfig(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as err:
            raise AttributeError(err)

class MockDatabase(MockNull, SessionCommon):
    def getclass(self, name):
        # limit class names
        if name not in [ 'issue', 'user', 'status' ]:
            raise KeyError('There is no class called "%s"' % name)
        # Class returned must have hasnode(id) method that returns true
        # otherwise designators like 'issue1' can't be hyperlinked.
        self.classes[name].hasnode = lambda id: True if int(id) < 10 else False
        return self.classes[name]

    # setup for csrf testing of otks database api
    storage = {}
    def set(self, key, **props):
        MockDatabase.storage[key] = {}
        if '__timestamp' not in props:
            props['__timestamp'] = time.time() - 7*24*3600
        MockDatabase.storage[key].update(props)

    def get(self, key, field, default=None):
        if key not in MockDatabase.storage:
            return default
        return MockDatabase.storage[key][field]

    def getall(self, key):
        if key not in MockDatabase.storage:
            return default
        return MockDatabase.storage[key]

    def exists(self,key):
        return key in MockDatabase.storage

    def getOTKManager(self):
        return MockDatabase()

    def lifetime(self, seconds):
        return time.time() - 7*24*3600 + seconds

class TemplatingTestCase(unittest.TestCase):
    def setUp(self):
        self.form = FieldStorage()
        self.client = MockNull()
        self.client.db = db = MockDatabase()
        db.security.hasPermission = lambda *args, **kw: True
        self.client.form = self.form

        # add client props for testing anti_csrf_nonce
        self.client.session_api = MockNull(_sid="1234567890")
        self.client.db.getuid = lambda : 10
        self.client.db.config = MockConfig (
            {'WEB_CSRF_TOKEN_LIFETIME': 10,
             'MARKDOWN_BREAK_ON_NEWLINE': False })

class HTMLDatabaseTestCase(TemplatingTestCase):
    def test_HTMLDatabase___getitem__(self):
        db = HTMLDatabase(self.client)
        self.assertTrue(isinstance(db['issue'], HTMLClass))
        # following assertions are invalid
        # since roundup/cgi/templating.py r1.173.
        # HTMLItem is function, not class,
        # but HTMLUserClass and HTMLUser are passed on.
        # these classes are no more.  they have ceased to be.
        #self.assertTrue(isinstance(db['user'], HTMLUserClass))
        #self.assertTrue(isinstance(db['issue1'], HTMLItem))
        #self.assertTrue(isinstance(db['user1'], HTMLUser))

    def test_HTMLDatabase___getattr__(self):
        db = HTMLDatabase(self.client)
        self.assertTrue(isinstance(db.issue, HTMLClass))
        # see comment in test_HTMLDatabase___getitem__
        #self.assertTrue(isinstance(db.user, HTMLUserClass))
        #self.assertTrue(isinstance(db.issue1, HTMLItem))
        #self.assertTrue(isinstance(db.user1, HTMLUser))

    def test_HTMLDatabase_classes(self):
        db = HTMLDatabase(self.client)
        db._db.classes = {'issue':MockNull(), 'user': MockNull()}
        db.classes()

    def test_HTMLDatabase_list(self):
        # The list method used to produce a traceback when a None value
        # for an order attribute of a class was encountered. This
        # happens when the 'get' of the order attribute for a numeric
        # id produced a None value. So we put '23' as a key into the
        # list and set things up that a None value is returned on 'get'.

        # This keeps db.issue static, otherwise it changes for each call
        db = MockNull(issue = HTMLDatabase(self.client).issue)
        db.issue._klass.list = lambda : ['23', 'a', 'b']
        # Make db.getclass return something that has a sensible 'get' method
        def get(x, y, allow_abort=True):
            return None
        mock = MockNull(get = get)
        db.issue._db.getclass = lambda x : mock
        l = db.issue.list()

class FunctionsTestCase(TemplatingTestCase):
    def test_lookupIds(self):
        db = HTMLDatabase(self.client)
        def lookup(key):
            if key == 'ok':
                return '1'
            if key == 'fail':
                raise KeyError('fail')
            if key == '@current_user':
                raise KeyError('@current_user')
            return key
        db._db.classes = {'issue': MockNull(lookup=lookup)}
        prop = MockNull(classname='issue')
        self.assertEqual(lookupIds(db._db, prop, ['1','2']), ['1','2'])
        self.assertEqual(lookupIds(db._db, prop, ['ok','2']), ['1','2'])
        self.assertEqual(lookupIds(db._db, prop, ['ok', 'fail'], 1),
            ['1', 'fail'])
        self.assertEqual(lookupIds(db._db, prop, ['ok', 'fail']), ['1'])
        self.assertEqual(lookupIds(db._db, prop, ['ok', '@current_user']),
                        ['1'])

    def test_lookupKeys(self):
        db = HTMLDatabase(self.client)
        def get(entry, key, allow_abort=True):
            return {'1': 'green', '2': 'eggs'}.get(entry, entry)
        shrubbery = MockNull(get=get)
        db._db.classes = {'shrubbery': shrubbery}
        self.assertEqual(lookupKeys(shrubbery, 'spam', ['1','2']),
            ['green', 'eggs'])
        self.assertEqual(lookupKeys(shrubbery, 'spam', ['ok','2']), ['ok',
            'eggs'])

class HTMLClassTestCase(TemplatingTestCase) :

    def test_link(self):
        """Make sure lookup of a Link property works even in the
        presence of multiple values in the form."""
        def lookup(key) :
            self.assertEqual(key, key.strip())
            return "Status%s"%key
        self.form.list.append(MiniFieldStorage("issue@status", "1"))
        self.form.list.append(MiniFieldStorage("issue@status", "2"))
        status = hyperdb.Link("status")
        self.client.db.classes = dict \
            ( issue = MockNull(getprops = lambda : dict(status = status))
            , status  = MockNull(get = lambda id, name : id, lookup = lookup)
            )
        self.client.form = self.form
        cls = HTMLClass(self.client, "issue")

        s = cls["status"]
        self.assertEqual(s._value, '1')

    def test_link_default(self):
        """Make sure default value for link is returned
           if new item and no value in form."""
        def lookup(key) :
            self.assertEqual(key, key.strip())
            return "Status%s"%key
        status = hyperdb.Link("status")
        # set default_value
        status.__dict__['_Type__default_value'] = "4"

        self.client.db.classes = dict \
            ( issue = MockNull(getprops = lambda : dict(status = status))
            , status  = MockNull(get = lambda id, name : id, lookup = lookup, get_default_value = lambda: 4)
            )
        self.client.form = self.form

        cls = HTMLClass(self.client, "issue")
        s = cls["status"]
        self.assertEqual(s._value, '4')

    def test_link_with_value_and_default(self):
        """Make sure default value is not used if there
           is a value in the form."""
        def lookup(key) :
            self.assertEqual(key, key.strip())
            return "Status%s"%key
        self.form.list.append(MiniFieldStorage("issue@status", "2"))
        self.form.list.append(MiniFieldStorage("issue@status", "1"))
        status = hyperdb.Link("status")
        # set default_value
        status.__dict__['_Type__default_value'] = "4"

        self.client.db.classes = dict \
            ( issue = MockNull(getprops = lambda : dict(status = status))
            , status  = MockNull(get = lambda id, name : id, lookup = lookup, get_default_value = lambda: 4)
            )
        self.client.form = self.form

        cls = HTMLClass(self.client, "issue")
        s = cls["status"]
        self.assertEqual(s._value, '2')

    def test_multilink(self):
        """`lookup` of an item will fail if leading or trailing whitespace
           has not been stripped.
        """
        def lookup(key) :
            self.assertEqual(key, key.strip())
            return "User%s"%key
        self.form.list.append(MiniFieldStorage("nosy", "1, 2"))
        nosy = hyperdb.Multilink("user")
        self.client.db.classes = dict \
            ( issue = MockNull(getprops = lambda : dict(nosy = nosy))
            , user  = MockNull(get = lambda id, name : id, lookup = lookup)
            )
        cls = HTMLClass(self.client, "issue")
        cls["nosy"]

    def test_anti_csrf_nonce(self):
        '''call the csrf creation function and do basic length test

           Store the data in a mock db with the same api as the otk
           db. Make sure nonce is 54 chars long. Lookup the nonce in
           db and retrieve data. Verify that the nonce lifetime is
           correct (within 1 second of 1 week - lifetime), the uid is
           correct (1), the dummy sid is correct.

           Consider three cases:
             * create nonce via module function setting lifetime
             * create nonce via TemplatingUtils method setting lifetime
             * create nonce via module function with default lifetime

        '''

        # the value below is number of seconds in a week.
        week_seconds = 604800

        otks=self.client.db.getOTKManager()

        for test in [ 'module', 'template', 'default_time' ]:
            print("Testing:", test)
            
            if test == 'module':
                # test the module function
                nonce1 = anti_csrf_nonce(self.client, lifetime=1)
                # lifetime * 60 is the offset
                greater_than = week_seconds - 1 * 60
            elif test == 'template':
                # call the function through the TemplatingUtils class
                cls = TemplatingUtils(self.client)
                nonce1 = cls.anti_csrf_nonce(lifetime=5)
                greater_than = week_seconds - 5 * 60
            elif test == 'default_time':
                # use the module function but with no lifetime
                nonce1 = anti_csrf_nonce(self.client)
                # see above for web nonce lifetime.
                greater_than = week_seconds - 10 * 60

            self.assertEqual(len(nonce1), 54)

            uid = otks.get(nonce1, 'uid', default=None)
            sid = otks.get(nonce1, 'sid', default=None)
            timestamp = otks.get(nonce1, '__timestamp', default=None)

            self.assertEqual(uid, 10) 
            self.assertEqual(sid, self.client.session_api._sid)

            now = time.time()

            print("now, timestamp, greater, difference",
                  now, timestamp, greater_than, now - timestamp)

        
            # lower bound of the difference is above. Upper bound
            # of difference is run time between time.time() in
            # the call to anti_csrf_nonce and the time.time() call
            # that assigns ts above. I declare that difference
            # to be less than 1 second for this to pass.
            self.assertEqual(True,
                       greater_than <= now - timestamp < (greater_than + 1) )

    def test_number__int__(self):
        # test with number
        p = NumberHTMLProperty(self.client, 'testnum', '1', None, 'test',
                               2345678.2345678)
        self.assertEqual(p.__int__(), 2345678)

        property = MockNull(get_default_value = lambda: None)
        p = NumberHTMLProperty(self.client, 'testnum', '1', property, 
                               'test', None)
        with self.assertRaises(TypeError) as e:
            p.__int__()

    def test_number__float__(self):
        # test with number
        p = NumberHTMLProperty(self.client, 'testnum', '1', None, 'test',
                               2345678.2345678)
        self.assertEqual(p.__float__(), 2345678.2345678)

        property = MockNull(get_default_value = lambda: None)
        p = NumberHTMLProperty(self.client, 'testnum', '1', property, 
                               'test', None)
        with self.assertRaises(TypeError) as e:
            p.__float__()

    def test_number_field(self):
        import sys

        _py3 = sys.version_info[0] > 2

        # python2 truncates while python3 rounds. Sigh.
        if _py3:
            expected_val = 2345678.2345678
        else:
            expected_val = 2345678.23457

        # test with number
        p = NumberHTMLProperty(self.client, 'testnum', '1', None, 'test',
                               2345678.2345678)
        self.client.db.config['WEB_USE_BROWSER_NUMBER_INPUT'] = False
        self.assertEqual(p.field(),
                         ('<input id="testnum1@test" name="testnum1@test" '
                         'size="30" type="text" value="%s">')%expected_val)
        self.client.db.config['WEB_USE_BROWSER_NUMBER_INPUT'] = True
        self.assertEqual(p.field(),
                         ('<input id="testnum1@test" name="testnum1@test" '
                         'size="30" type="number" value="%s">')%expected_val)
        self.assertEqual(p.field(size=10),
                         ('<input id="testnum1@test" name="testnum1@test" '
                         'size="10" type="number" value="%s">')%expected_val)
        self.assertEqual(p.field(size=10, dataprop="foo", dataprop2=5),
                         ('<input dataprop="foo" dataprop2="5" '
                          'id="testnum1@test" name="testnum1@test" '
                          'size="10" type="number" '
                          'value="%s">'%expected_val))

        self.assertEqual(p.field(size=10, klass="class1", 
                                 **{ "class": "class2 class3",
                                     "data-prop": "foo",
                                     "data-prop2": 5}),
                         ('<input class="class2 class3" data-prop="foo" '
                          'data-prop2="5" id="testnum1@test" '
                          'klass="class1" '
                          'name="testnum1@test" size="10" type="number" '
                          'value="%s">')%expected_val)

        # get plain representation if user can't edit
        p.is_edit_ok = lambda: False
        self.assertEqual(p.field(), p.plain())

        # test with string which is wrong type
        p = NumberHTMLProperty(self.client, 'testnum', '1', None, 'test',
                               "234567e.2345678")
        self.assertEqual(p.field(),
                         ('<input id="testnum1@test" name="testnum1@test" '
                          'size="30" type="number" value="234567e.2345678">'))

        # test with None value, pretend property.__default_value = Null which
        #    is the default. It would be returned by get_default_value
        #    which I mock.
        property = MockNull(get_default_value = lambda: None)
        p = NumberHTMLProperty(self.client, 'testnum', '1', property, 
                               'test', None)
        self.assertEqual(p.field(),
                         ('<input id="testnum1@test" name="testnum1@test" '
                         'size="30" type="number" value="">'))

    def test_number_plain(self):
        import sys

        _py3 = sys.version_info[0] > 2

        # python2 truncates while python3 rounds. Sigh.
        if _py3:
            expected_val = 2345678.2345678
        else:
            expected_val = 2345678.23457

        p = NumberHTMLProperty(self.client, 'testnum', '1', None, 'test',
                               2345678.2345678)

        self.assertEqual(p.plain(), "%s"%expected_val)

    def test_number_pretty(self):
        # test with number
        p = NumberHTMLProperty(self.client, 'testnum', '1', None, 'test',
                               2345678.2345678)
        self.assertEqual(p.pretty(), "2345678.235")

        # test with string which is wrong type
        p = NumberHTMLProperty(self.client, 'testnum', '1', None, 'test',
                               "2345678.2345678")
        self.assertEqual(p.pretty(), "2345678.2345678")

        # test with boolean
        p = NumberHTMLProperty(self.client, 'testnum', '1', None, 'test',
                               True)
        self.assertEqual(p.pretty(), "1.000")

        # test with None value, pretend property.__default_value = Null which
        #    is the default. It would be returned by get_default_value
        #    which I mock.
        property = MockNull(get_default_value = lambda: None)
        p = NumberHTMLProperty(self.client, 'testnum', '1', property, 
                               'test', None)
        self.assertEqual(p.pretty(), '')

        with self.assertRaises(ValueError) as e:
            p.pretty('%0.3')

    def test_string_url_quote(self):
        ''' test that urlquote quotes the string '''
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', 'test string< foo@bar')
        self.assertEqual(p.url_quote(), 'test%20string%3C%20foo%40bar')

    def test_string_email(self):
        ''' test that email obscures the email '''
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', 'rouilj@foo.example.com')
        self.assertEqual(p.email(), 'rouilj at foo example ...')

    def test_string_wrapped(self):
        test_string = ('A long string that needs to be wrapped to'
                       ' 80 characters and no more. Put in a link issue1.'
                       ' Put in <html> to be escaped. Put in a'
                       ' https://example.com/link as well. Let us see if'
                       ' it will wrap properly.' )

        test_result_wrap = {}
        test_result_wrap[80] = ('A long string that needs to be wrapped to 80'
                       ' characters and no more. Put in a\n'
                       'link <a href="issue1">issue1</a>. Put in'
                       ' &lt;html&gt; to be escaped. Put in a <a'
                       ' href="https://example.com/link"'
                       ' rel="nofollow noopener">'
                       'https://example.com/link</a> as\n'
                       'well. Let us see if it will wrap properly.')
        test_result_wrap[20] = (
            'A long string that\n'
            'needs to be wrapped\n'
            'to 80 characters and\n'
            'no more. Put in a\nlink <a href="issue1">issue1</a>. Put in\n'
            '&lt;html&gt; to be\n'
            'escaped. Put in a\n'
            '<a href="https://example.com/link" rel="nofollow '
            'noopener">https://example.com/link</a>\n'
            'as well. Let us see\n'
            'if it will wrap\n'
            'properly.')
        test_result_wrap[100] = (
            'A long string that needs to be wrapped to 80 characters and no more. Put in a link <a href="issue1">issue1</a>. Put in\n'
            '&lt;html&gt; to be escaped. Put in a <a href="https://example.com/link" rel="nofollow noopener">https://example.com/link</a> as well. Let us see if it will wrap\n'
            'properly.')

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                               test_string)

        for i in [80, 20, 100]:
            wrapped = p.wrapped(columns=i)
            print(wrapped)
            self.assertEqual(wrapped, test_result_wrap[i])

    def test_string_plain_or_hyperlinked(self):
        ''' test that email obscures the email '''
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', 'A string <b> with rouilj@example.com embedded &lt; html</b>')
        self.assertEqual(p.plain(), 'A string <b> with rouilj@example.com embedded &lt; html</b>')
        self.assertEqual(p.plain(escape=1), 'A string &lt;b&gt; with rouilj@example.com embedded &amp;lt; html&lt;/b&gt;')
        self.assertEqual(p.plain(hyperlink=1), 'A string &lt;b&gt; with <a href="mailto:rouilj@example.com">rouilj@example.com</a> embedded &amp;lt; html&lt;/b&gt;')
        self.assertEqual(p.plain(escape=1, hyperlink=1), 'A string &lt;b&gt; with <a href="mailto:rouilj@example.com">rouilj@example.com</a> embedded &amp;lt; html&lt;/b&gt;')

        self.assertEqual(p.hyperlinked(), 'A string &lt;b&gt; with <a href="mailto:rouilj@example.com">rouilj@example.com</a> embedded &amp;lt; html&lt;/b&gt;')
        # check designators
        for designator in [ "issue1", "issue 1" ]:
            p = StringHTMLProperty(self.client, 'test', '1', None, 'test', designator)
            self.assertEqual(p.hyperlinked(),
                             '<a href="issue1">%s</a>'%designator)

        # issue 100 > 10 which is a magic number for the mocked hasnode
        # If id number is greater than 10 hasnode reports it does not have
        # the node.
        for designator in ['issue100', 'issue 100']:
            p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                                   designator)
            self.assertEqual(p.hyperlinked(), designator)

        # zoom class does not exist
        for designator in ['zoom1', 'zoom100', 'zoom 1']:
            p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                                   designator)
            self.assertEqual(p.hyperlinked(), designator)


    @skip_rst
    def test_string_rst(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'A string with cmeerw@example.com *embedded* \u00df'))

        # test case to make sure include directive is disabled
        q = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'\n\n.. include:: XyZrMt.html\n\n<badtag>\n\n'))
        q_result=u'''<div class="document">
<div class="system-message">
<p class="system-message-title">System Message: WARNING/2 (<tt class="docutils">&lt;string&gt;</tt>, line 3)</p>
<p>&quot;include&quot; directive disabled.</p>
<pre class="literal-block">
.. include:: XyZrMt.html

</pre>
</div>
<p>&lt;badtag&gt;</p>
</div>
'''

        # test case to make sure raw directive is disabled
        r =  StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'\n\n.. raw:: html\n\n   <badtag>\n\n'))
        r_result='''<div class="document">
<div class="system-message">
<p class="system-message-title">System Message: WARNING/2 (<tt class="docutils">&lt;string&gt;</tt>, line 3)</p>
<p>&quot;raw&quot; directive disabled.</p>
<pre class="literal-block">
.. raw:: html

   &lt;badtag&gt;

</pre>
</div>
</div>
'''
	# test case to make sure javascript and data url's aren't turned
        # into links
        s = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'<badtag>\njavascript:badcode data:text/plain;base64,SGVsbG8sIFdvcmxkIQ=='))
        s_result = '<div class="document">\n<p>&lt;badtag&gt;\njavascript:badcode data:text/plain;base64,SGVsbG8sIFdvcmxkIQ==</p>\n</div>\n'

        # test url recognition
        t = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'link is https://example.com/link for testing.'))
        t_result = '<div class="document">\n<p>link is <a class="reference external" href="https://example.com/link">https://example.com/link</a> for testing.</p>\n</div>\n'

        # test text that doesn't need to be processed
        u = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'Just a plain old string here. Nothig to process.'))
        u_result = '<div class="document">\n<p>Just a plain old string here. Nothig to process.</p>\n</div>\n'

        self.assertEqual(p.rst(), u2s(u'<div class="document">\n<p>A string with <a class="reference external" href="mailto:cmeerw&#64;example.com">cmeerw&#64;example.com</a> <em>embedded</em> \u00df</p>\n</div>\n'))
        self.assertEqual(q.rst(), u2s(q_result))
        self.assertEqual(r.rst(), u2s(r_result))
        self.assertEqual(s.rst(), u2s(s_result))
        self.assertEqual(t.rst(), u2s(t_result))
        self.assertEqual(u.rst(), u2s(u_result))

    def test_string_field(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', 'A string <b> with rouilj@example.com embedded &lt; html</b>')
        self.assertEqual(p.field(), '<input id="test1@test" name="test1@test" size="30" type="text" value="A string &lt;b&gt; with rouilj@example.com embedded &amp;lt; html&lt;/b&gt;">')

    def test_string_multiline(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', 'A string <b> with rouilj@example.com embedded &lt; html</b>')
        self.assertEqual(p.multiline(), '<textarea  name="test1@test" id="test1@test" rows="5" cols="40">A string &lt;b&gt; with rouilj@example.com embedded &amp;lt; html&lt;/b&gt;</textarea>')
        self.assertEqual(p.multiline(rows=300, cols=100, **{'class':'css_class'}), '<textarea class="css_class" name="test1@test" id="test1@test" rows="300" cols="100">A string &lt;b&gt; with rouilj@example.com embedded &amp;lt; html&lt;/b&gt;</textarea>')

    def test_url_match(self):
        '''Test the URL regular expression in StringHTMLProperty.
        '''
        def t(s, nothing=False, **groups):
            m = StringHTMLProperty.hyper_re.search(s)
            if nothing:
                if m:
                    self.assertEqual(m, None, '%r matched (%r)'%(s, m.groupdict()))
                return
            else:
                self.assertNotEqual(m, None, '%r did not match'%s)
            d = m.groupdict()
            for g in groups:
                self.assertEqual(d[g], groups[g], '%s %r != %r in %r'%(g, d[g],
                    groups[g], s))

        #t('123.321.123.321', 'url')
        t('https://example.com/demo/issue8#24MRV9BZYx:V:1B~sssssssssssssss~4~4', url="https://example.com/demo/issue8#24MRV9BZYx:V:1B~sssssssssssssss~4~4")
        t('http://localhost/', url='http://localhost/')
        t('http://roundup.net/', url='http://roundup.net/')
        t('http://richard@localhost/', url='http://richard@localhost/')
        t('http://richard:sekrit@localhost/',
            url='http://richard:sekrit@localhost/')
        t('<HTTP://roundup.net/>', url='HTTP://roundup.net/')
        t('www.a.ex', url='www.a.ex')
        t('foo.a.ex', nothing=True)
        t('StDevValidTimeSeries.GetObservation', nothing=True)
        t('http://a.ex', url='http://a.ex')
        t('http://a.ex/?foo&bar=baz\\.@!$%()qwerty',
            url='http://a.ex/?foo&bar=baz\\.@!$%()qwerty')
        t('www.foo.net', url='www.foo.net')
        t('richard@com.example', email='richard@com.example')
        t('r@a.com', email='r@a.com')
        t('i1', **{'class':'i', 'id':'1'})
        t('item123', **{'class':'item', 'id':'123'})
        t('item 123', **{'class':'item', 'id':'123'})
        t('www.user:pass@host.net', email='pass@host.net')
        t('user:pass@www.host.net', url='user:pass@www.host.net')
        t('123.35', nothing=True)
        t('-.3535', nothing=True)

    def test_url_replace(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', '')
        def t(s): return p.hyper_re.sub(p._hyper_repl, s)
        ae = self.assertEqual
        ae(t('issue5#msg10'), '<a href="issue5#msg10">issue5#msg10</a>')
        ae(t('issue5'), '<a href="issue5">issue5</a>')
        ae(t('issue2255'), 'issue2255')
        ae(t('foo https://example.com/demo/issue8#24MRV9BZYx:V:1B~sssssssssssssss~4~4 bar'),
           'foo <a href="https://example.com/demo/issue8#24MRV9BZYx:V:1B~sssssssssssssss~4~4" rel="nofollow noopener">'
           'https://example.com/demo/issue8#24MRV9BZYx:V:1B~sssssssssssssss~4~4</a> bar')
        ae(t('item123123123123'), 'item123123123123')
        ae(t('http://roundup.net/'),
           '<a href="http://roundup.net/" rel="nofollow noopener">http://roundup.net/</a>')
        ae(t('&lt;HTTP://roundup.net/&gt;'),
           '&lt;<a href="HTTP://roundup.net/" rel="nofollow noopener">HTTP://roundup.net/</a>&gt;')
        ae(t('&lt;http://roundup.net/&gt;.'),
            '&lt;<a href="http://roundup.net/" rel="nofollow noopener">http://roundup.net/</a>&gt;.')
        ae(t('&lt;www.roundup.net&gt;'),
           '&lt;<a href="http://www.roundup.net" rel="nofollow noopener">www.roundup.net</a>&gt;')
        ae(t('(www.roundup.net)'),
           '(<a href="http://www.roundup.net" rel="nofollow noopener">www.roundup.net</a>)')
        ae(t('foo http://msdn.microsoft.com/en-us/library/ms741540(VS.85).aspx bar'),
           'foo <a href="http://msdn.microsoft.com/en-us/library/ms741540(VS.85).aspx" rel="nofollow noopener">'
           'http://msdn.microsoft.com/en-us/library/ms741540(VS.85).aspx</a> bar')
        ae(t('(e.g. http://en.wikipedia.org/wiki/Python_(programming_language))'),
           '(e.g. <a href="http://en.wikipedia.org/wiki/Python_(programming_language)" rel="nofollow noopener">'
           'http://en.wikipedia.org/wiki/Python_(programming_language)</a>)')
        ae(t('(e.g. http://en.wikipedia.org/wiki/Python_(programming_language)).'),
           '(e.g. <a href="http://en.wikipedia.org/wiki/Python_(programming_language)" rel="nofollow noopener">'
           'http://en.wikipedia.org/wiki/Python_(programming_language)</a>).')
        ae(t('(e.g. http://en.wikipedia.org/wiki/Python_(programming_language))&gt;.'),
           '(e.g. <a href="http://en.wikipedia.org/wiki/Python_(programming_language)" rel="nofollow noopener">'
           'http://en.wikipedia.org/wiki/Python_(programming_language)</a>)&gt;.')
        ae(t('(e.g. http://en.wikipedia.org/wiki/Python_(programming_language&gt;)).'),
           '(e.g. <a href="http://en.wikipedia.org/wiki/Python_(programming_language" rel="nofollow noopener">'
           'http://en.wikipedia.org/wiki/Python_(programming_language</a>&gt;)).')
        for c in '.,;:!':
            # trailing punctuation is not included
            ae(t('http://roundup.net/%c ' % c),
               '<a href="http://roundup.net/" rel="nofollow noopener">http://roundup.net/</a>%c ' % c)
            # trailing punctuation is not included without trailing space
            ae(t('http://roundup.net/%c' % c),
               '<a href="http://roundup.net/" rel="nofollow noopener">http://roundup.net/</a>%c' % c)
            # but it's included if it's part of the URL
            ae(t('http://roundup.net/%c/' % c),
               '<a href="http://roundup.net/%c/" rel="nofollow noopener">http://roundup.net/%c/</a>' % (c, c))
            # including with a non / terminated path
            ae(t('http://roundup.net/test%c ' % c),
               '<a href="http://roundup.net/test" rel="nofollow noopener">http://roundup.net/test</a>%c ' % c)
            # but it's included if it's part of the URL path
            ae(t('http://roundup.net/%ctest' % c),
               '<a href="http://roundup.net/%ctest" rel="nofollow noopener">http://roundup.net/%ctest</a>' % (c, c))


    def test_input_html4(self):
        # boolean attributes are just the attribute name
        # indicate with attr=None or attr="attr"
        #   e.g. disabled

        input=input_html4(required=None, size=30)
        self.assertEqual(input, '<input required size="30" type="text">')

        input=input_html4(required="required", size=30)
        self.assertEqual(input, '<input required="required" size="30" type="text">')

        attrs={"required": None, "class": "required", "size": 30}
        input=input_html4(**attrs)
        self.assertEqual(input, '<input class="required" required size="30" type="text">')

        attrs={"disabled": "disabled", "class": "required", "size": 30}
        input=input_html4(**attrs)
        self.assertEqual(input, '<input class="required" disabled="disabled" size="30" type="text">')


class HTMLPropertyTestClass(unittest.TestCase):
    def setUp(self):
        self.form = FieldStorage()
        self.client = MockNull()
        self.client.db = db = memorydb.create('admin')
        db.tx_Source = "web"

        db.issue.addprop(tx_Source=hyperdb.String())

        db.security.hasPermission = lambda *args, **kw: True
        self.client.form = self.form

        self.client._props = MockNull()
        # add client props for testing anti_csrf_nonce
        self.client.session_api = MockNull(_sid="1234567890")
        self.client.db.getuid = lambda : 10

    @pytest.fixture(autouse=True)
    def inject_fixtures(self, caplog):
        self._caplog = caplog

class BooleanHTMLPropertyTestCase(HTMLPropertyTestClass):

    def setUp(self):
        super(BooleanHTMLPropertyTestCase, self).setUp()

        db = self.client.db
        db.issue.addprop(boolvalt=hyperdb.Boolean())
        db.issue.addprop(boolvalf=hyperdb.Boolean())
        db.issue.addprop(boolvalunset=hyperdb.Boolean())

        self.client.db.issue.create(title="title",
                                    boolvalt = True,
                                    boolvalf = False)

    def tearDown(self):
        self.client.db.close()
        memorydb.db_nuke('')

    testdata = [
        ("boolvalt", "Yes", True, False),
        ("boolvalf", "No", False, True),
        ("boolvalunset", "", False, True),
    ]

    def test_BoolHTMLRadioButtons(self):
        #propname = "boolvalt"

        #plainval = "Yes"

        self.maxDiff = None
        for test_inputs in self.testdata:
            params = {
                "check1": 'checked="checked" ' if test_inputs[2] else "",
                "check2": 'checked="checked" ' if test_inputs[3] else "",
                "propname": test_inputs[0],
                "plainval": test_inputs[1],

            }


            test_hyperdbBoolean = self.client.db.issue.getprops("1")[
                params['propname']]
            test_boolean = self.client.db.issue.get("1", params['propname'])

            # client, classname, nodeid, prop, name, value,
            #    anonymous=0, offset=None
            d = BooleanHTMLProperty(self.client, 'issue', '1',
                                    test_hyperdbBoolean,
                                    params['propname'], test_boolean)

            self.assertIsInstance(d._value, (type(None), bool))

            self.assertEqual(d.plain(), params['plainval'])

            input_expected = (
                '<input %(check1)sid="issue1@%(propname)s_yes" '
                'name="issue1@%(propname)s" type="radio" value="yes">'
                '<label class="rblabel" for="issue1@%(propname)s_yes">'
                'Yes</label>'
                '<input %(check2)sid="issue1@%(propname)s_no" name="issue1@%(propname)s" '
                'type="radio" value="no"><label class="rblabel" '
                'for="issue1@%(propname)s_no">No</label>') % params

            self.assertEqual(d.field(), input_expected)

            y_label = ( '<label class="rblabel" for="issue1@%(propname)s_yes">'
                        'True</label>') % params
            n_label = ('<label class="rblabel" '
                       'for="issue1@%(propname)s_no">False</label>') % params
            u_label = ('<label class="rblabel" '
                       'for="issue1@%(propname)s_unk">Ignore</label>') % params

            input_expected = (
                '<input %(check1)sid="issue1@%(propname)s_yes" '
                'name="issue1@%(propname)s" type="radio" value="yes">'
                + y_label +
                '<input %(check2)sid="issue1@%(propname)s_no" name="issue1@%(propname)s" '
                'type="radio" value="no">' + n_label ) % params

            self.assertEqual(d.field(y_label=y_label, n_label=n_label), input_expected)


            input_expected = (
                '<label class="rblabel" for="issue1@%(propname)s_yes">'
                'Yes</label>'
                '<input %(check1)sid="issue1@%(propname)s_yes" '
                'name="issue1@%(propname)s" type="radio" value="yes">'
                '<label class="rblabel" '
                'for="issue1@%(propname)s_no">No</label>'
                '<input %(check2)sid="issue1@%(propname)s_no" '
                    'name="issue1@%(propname)s" '
                'type="radio" value="no">') % params

            print(d.field(labelfirst=True))
            self.assertEqual(d.field(labelfirst=True), input_expected)

            input_expected = (
                '<label class="rblabel" for="issue1@%(propname)s_unk">'
                'Ignore</label>'
                '<input id="issue1@%(propname)s_unk" '
                'name="issue1@%(propname)s" type="radio" value="">'
                '<input %(check1)sid="issue1@%(propname)s_yes" '
                'name="issue1@%(propname)s" type="radio" value="yes">'
                '<label class="rblabel" for="issue1@%(propname)s_yes">'
                'Yes</label>'
                '<input %(check2)sid="issue1@%(propname)s_no" name="issue1@%(propname)s" '
                'type="radio" value="no"><label class="rblabel" '
                'for="issue1@%(propname)s_no">No</label>') % params

            self.assertEqual(d.field(u_label=u_label), input_expected)


        # one test with the last d is enough.
        # check permissions return
        is_view_ok_orig = d.is_view_ok
        is_edit_ok_orig = d.is_edit_ok
        no_access = lambda : False

        d.is_view_ok = no_access
        self.assertEqual(d.plain(), "[hidden]")

        d.is_edit_ok = no_access
        self.assertEqual(d.field(), "[hidden]")

        d.is_view_ok = is_view_ok_orig
        self.assertEqual(d.field(), params['plainval'])
        d.is_edit_ok = is_edit_ok_orig

class DateHTMLPropertyTestCase(HTMLPropertyTestClass):

    def setUp(self):
        super(DateHTMLPropertyTestCase, self).setUp()

        db = self.client.db
        db.issue.addprop(deadline=hyperdb.Date())

        self.test_datestring = "2021-01-01.11:22:10"

        self.client.db.issue.create(title="title",
                                    deadline=date.Date(self.test_datestring))
        self.client.db.getUserTimezone = lambda: "2"

    def tearDown(self):
        self.client.db.close()
        memorydb.db_nuke('')

    def exp_classhelp(self, cls='issue', prop='deadline', dlm='.'):
        value = dlm.join (('2021-01-01', '11:22:10'))
        return ('<a class="classhelp" data-calurl="%(cls)s?'
        '@template=calendar&amp;property=%(prop)s&amp;'
        'form=itemSynopsis&amp;date=%(value)s" '
        'data-height="200" data-width="300" href="javascript:help_window'
        '(\'%(cls)s?@template=calendar&amp;property=%(prop)s&amp;'
        'form=itemSynopsis&date=%(value)s\', 300, 200)">(cal)</a>'
        ) % {'cls': cls, 'prop': prop, 'value': value}

    def test_DateHTMLWithDate(self):
        """Test methods when DateHTMLProperty._value is a hyperdb.Date()
        """
        self.client.db.config['WEB_USE_BROWSER_DATE_INPUT'] = True
        test_datestring = self.test_datestring
        test_Date = self.client.db.issue.get("1", 'deadline')
        test_hyperdbDate = self.client.db.issue.getprops("1")['deadline']

        self.client.classname = "issue"
        self.client.template = "item"

        # client, classname, nodeid, prop, name, value,
        #    anonymous=0, offset=None
        d = DateHTMLProperty(self.client, 'issue', '1', test_hyperdbDate,
                             'deadline', test_Date)
        self.assertIsInstance(d._value, date.Date)
        self.assertEqual(d.pretty(), " 1 January 2021")
        self.assertEqual(d.pretty("%2d %B %Y"), "01 January 2021")
        self.assertEqual(d.pretty(format="%Y-%m"), "2021-01")
        self.assertEqual(d.plain(), "2021-01-01.13:22:10")
        self.assertEqual(d.local("-4").plain(), "2021-01-01.07:22:10")
        input_expected = """<input id="issue1@deadline" name="issue1@deadline" size="30" type="date" value="2021-01-01">"""
        self.assertEqual(d.field(display_time=False), input_expected)

        input_expected = '<input id="issue1@deadline" name="issue1@deadline" '\
            'size="30" type="datetime-local" value="2021-01-01T13:22:10">'
        self.assertEqual(d.field(), input_expected)

        input_expected = '<input id="issue1@deadline" name="issue1@deadline" '\
            'size="30" type="text" value="2021-01-01.13:22:10">'
        field = d.field(format='%Y-%m-%d.%H:%M:%S', popcal=False)
        self.assertEqual(field, input_expected)

        # test with format
        input_expected = '<input id="issue1@deadline" name="issue1@deadline" '\
            'size="30" type="text" value="2021-01">' + self.exp_classhelp()

        self.assertEqual(d.field(format="%Y-%m"), input_expected)

        input_expected = '<input id="issue1@deadline" name="issue1@deadline" '\
            'size="30" type="text" value="2021-01">'

        input = d.field(format="%Y-%m", popcal=False)
        self.assertEqual(input, input_expected)

    def test_DateHTMLWithText(self):
        """Test methods when DateHTMLProperty._value is a string
           rather than a hyperdb.Date()
        """
        test_datestring = "2021-01-01 11:22:10"
        test_date = hyperdb.Date("2")

        self.form.list.append(MiniFieldStorage("test1@test", test_datestring))
        self.client._props=test_date
        self.client.db.config['WEB_USE_BROWSER_DATE_INPUT'] = False

        self.client.db.classes = dict \
            ( test = MockNull(getprops = lambda : test_date)
            )

        self.client.classname = "test"
        self.client.template = "item"

        # client, classname, nodeid, prop, name, value,
        #    anonymous=0, offset=None
        d = DateHTMLProperty(self.client, 'test', '1', self.client._props,
                             'test', '')
        self.assertIs(type(d._value), str)
        self.assertEqual(d.pretty(), "2021-01-01 11:22:10")
        self.assertEqual(d.plain(), "2021-01-01 11:22:10")
        input_expected = '<input id="test1@test" name="test1@test" size="30" '\
            'type="text" value="2021-01-01 11:22:10">'
        self.assertEqual(d.field(popcal=False), input_expected)
        self.client.db.config['WEB_USE_BROWSER_DATE_INPUT'] = True
        input_expected = '<input id="test1@test" name="test1@test" size="30" '\
            'type="datetime-local" value="2021-01-01 11:22:10">'
        self.assertEqual(d.field(), input_expected)
        self.client.db.config['WEB_USE_BROWSER_DATE_INPUT'] = False

        input_expected = '<input id="test1@test" name="test1@test" size="40" '\
            'type="text" value="2021-01-01 11:22:10">'
        self.assertEqual(d.field(size=40, popcal=False), input_expected)

        input_expected = ('<input id="test1@test" name="test1@test" size="30" '
            'type="text" value="2021-01-01 11:22:10">'
            + self.exp_classhelp(cls='test', prop='test', dlm=' '))
        self.maxDiff=None
        self.assertEqual(d.field(format="%Y-%m"), input_expected)

        # format always uses type="text" even when date input is set
        self.client.db.config['WEB_USE_BROWSER_DATE_INPUT'] = True
        result = d.field(format="%Y-%m-%d", popcal=False)
        input_expected = '<input id="test1@test" name="test1@test" size="30" '\
            'type="text" value="2021-01-01 11:22:10">'
        self.assertEqual(result, input_expected)

        input_expected = ('<input id="test1@test" name="test1@test" size="30" '
            'type="text" value="2021-01-01 11:22:10">'
            + self.exp_classhelp(cls='test', prop='test', dlm=' '))
        self.assertEqual(d.field(format="%Y-%m"), input_expected)

        result = d.field(format="%Y-%m-%dT%H:%M:%S", popcal=False)
        input_expected = '<input id="test1@test" name="test1@test" size="30" '\
            'type="text" value="2021-01-01 11:22:10">'
        self.assertEqual(result, input_expected)

# common markdown test cases
class MarkdownTests:
    def mangleMarkdown2(self, s):
        ''' markdown2's rel=nofollow support on 'a' tags isn't programmable.
            So we are using it's builtin nofollow support. Mangle the string
            so that it matches the test case.

                turn: <a rel="nofollow" href="foo"> into
                      <a href="foo" rel="nofollow noopener">

            Also if it is a mailto url, we don't expect rel="nofollow",
            so delete it.

                turn: <a rel="nofollow" href="mailto:foo"> into
                      <a href="mailto:foo">

            Also when a title is present it is put in a different place
            from markdown, so fix it to normalize.

                turn:

                <a rel="nofollow" href="http://example.com/" title="a title">
                into
                <a href="http://example.com/" rel="nofollow noopener" title="a title">
        '''
        if type(self) == Markdown2TestCase and s.find('a rel="nofollow"') != -1:
            if s.find('href="mailto:') == -1:
                # not a mailto url
                if 'rel="nofollow"' in s:
                    if 'title="' in s:
                        s = s.replace(' rel="nofollow" ', ' ').replace(' title=', ' rel="nofollow noopener" title=')
                    else:
                        s = s.replace(' rel="nofollow" ', ' ').replace('">', '" rel="nofollow noopener">')

                return s
            else:
                # a mailto url
                return s.replace(' rel="nofollow" ', ' ')
        return s


    def test_string_markdown(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'A string with <br> *embedded* \u00df'))
        self.assertEqual(p.markdown().strip(), u2s(u'<p>A string with &lt;br&gt; <em>embedded</em> \u00df</p>'))

    def test_string_markdown_link(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                               u2s(u'A link <http://localhost>'))
        m = p.markdown().strip()
        m = self.mangleMarkdown2(m)

        self.assertEqual( u2s(u'<p>A link <a href="http://localhost" rel="nofollow noopener">http://localhost</a></p>'), m)

    def test_string_markdown_link_item(self):
        """ The link formats for the different markdown engines changes.
            Order of attributes, value for rel (noopener, nofollow etc)
            is different. So most tests check for a substring that indicates
            success rather than the entire returned string.
        """
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                               u2s(u'An issue1 link'))
        self.assertIn( u2s(u'href="issue1"'), p.markdown().strip())
        # just verify that plain linking is working
        self.assertIn( u2s(u'href="issue1"'), p.plain(hyperlink=1))

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                               u2s(u'An [issue1](issue1) link'))
        self.assertIn( u2s(u'href="issue1"'), p.markdown().strip())
        # just verify that plain linking is working
        self.assertIn( u2s(u'href="issue1"'), p.plain(hyperlink=1))

        p = StringHTMLProperty(
            self.client, 'test', '1', None, 'test',
            u2s(u'An [issue1](https://example.com/issue1) link'))
        self.assertIn( u2s(u'href="https://example.com/issue1"'),
                       p.markdown().strip())

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                               u2s(u'An [issu1](#example) link'))
        self.assertIn( u2s(u'href="#example"'), p.markdown().strip())

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                               u2s(u'An [issu1](/example) link'))
        self.assertIn( u2s(u'href="/example"'), p.markdown().strip())

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                               u2s(u'An [issu1](./example) link'))
        self.assertIn( u2s(u'href="./example"'), p.markdown().strip())

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                               u2s(u'An [issu1](../example) link'))
        self.assertIn( u2s(u'href="../example"'), p.markdown().strip())

        p = StringHTMLProperty(
            self.client, 'test', '1', None, 'test',
            u2s(u'A [wuarchive_ftp](ftp://www.wustl.gov/file) link'))
        self.assertIn( u2s(u'href="ftp://www.wustl.gov/file"'),
                       p.markdown().strip())

        p = StringHTMLProperty(
            self.client, 'test', '1', None, 'test',
            u2s(u'An [issue1] (https://example.com/issue1) link'))
        self.assertIn( u2s(u'href="issue1"'), p.markdown().strip())
        if type(self) == MistuneTestCase:
            # mistune makes the https url into a real link
            self.assertIn( u2s(u'href="https://example.com/issue1"'),
                           p.markdown().strip())
        else:
            # the other two engines leave the parenthesized url as is.
            self.assertIn( u2s(u' (https://example.com/issue1) link'),
                           p.markdown().strip())

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                               u2s(u'An [issu1](.../example) link'))
        if (isinstance(self, Markdown2TestCase) and 
           md2__version_info__ > (2, 4, 9)):
            # markdown2 > 2.4.9 handles this differently
            self.assertIn( u2s(u'href="#"'), p.markdown().strip())
        else:
            self.assertIn( u2s(u'href=".../example"'), p.markdown().strip())
            
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                               u2s(u'A [phone](tel:0016175555555) link'))
        if (isinstance(self, Markdown2TestCase) and
           md2__version_info__ > (2, 4, 9)):
            self.assertIn(u2s(u'href="#"'), p.markdown().strip())
        else:
            self.assertIn( u2s(u'href="tel:0016175555555"'),
                           p.markdown().strip())

    def test_string_email_markdown_link(self):
        # markdown2 and markdown escape the email address
        try:
            from html import unescape as html_unescape
        except ImportError:
            from HTMLParser import HTMLParser
            html_unescape = HTMLParser().unescape

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                               u2s(u'A link <cmeerw@example.com>'))
        m = html_unescape(p.markdown().strip())
        m = self.mangleMarkdown2(m)

        self.assertEqual(m, u2s(u'<p>A link <a href="mailto:cmeerw@example.com">cmeerw@example.com</a></p>'))

        p = StringHTMLProperty(
            self.client, 'test', '1', None, 'test',
            u2s(u'An bare email baduser@daemons.com link'))
        m = self.mangleMarkdown2(html_unescape(p.markdown().strip()))
        self.assertIn( u2s(u'href="mailto:baduser@daemons.com"'),
                       m)
        
        p = StringHTMLProperty(
            self.client, 'test', '1', None, 'test',
            u2s(u'An [email_url](mailto:baduser@daemons.com) link'))
        m = self.mangleMarkdown2(html_unescape(p.markdown().strip()))
        
        if isinstance(self, MistuneTestCase):
            self.assertIn('<a href="mailto:baduser@daemons.com" rel="nofollow noopener">email_url</a>', m)            
        else:
            self.assertIn('<a href="mailto:baduser@daemons.com">email_url</a>', m)

    def test_string_markdown_javascript_link(self):
        # make sure we don't get a "javascript:" link
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'<javascript:alert(1)>'))
        self.assertTrue(p.markdown().find('href="javascript:') == -1)

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'[link](javascript:alert(1))'))
        self.assertTrue(p.markdown().find('href="javascript:') == -1)

    def test_string_markdown_data_link(self):
        # make sure we don't get a "data:" link
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'<data:text/plain;base64,SGVsbG8sIFdvcmxkIQ==>'))
        print(p.markdown())
        self.assertTrue(p.markdown().find('href="data:') == -1)

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'[data link](data:text/plain;base64,SGVsbG8sIFdvcmxkIQ==)'))
        print(p.markdown())
        self.assertTrue(p.markdown().find('href="data:') == -1)


    def test_string_markdown_forced_line_break(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'This is a set of text  \n:that should have a break  \n:at newlines. Each  \n:colon should be the start of an html line'))
        # sigh different backends render this differently:
        #  of text <br />
        #  of text<br>
        # etc.
        # Rather than using a different result for each
        # renderer, look for '<br' and require three of them.
        m = p.markdown()
        print(m)
        self.assertEqual(3, m.count('<br'))

    def test_string_markdown_code_block(self):
        ''' also verify that embedded html is escaped '''
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'embedded code block <pre>\n\n```\nline 1\nline 2\n```\n\nnew </pre> paragraph'))
        self.assertEqual(p.markdown().strip().replace('\n\n', '\n'), u2s(u'<p>embedded code block &lt;pre&gt;</p>\n<pre><code>line 1\nline 2\n</code></pre>\n<p>new &lt;/pre&gt; paragraph</p>'))

    def test_string_markdown_code_block_attribute(self):
        parser = NormalizingHtmlParser()

        ''' also verify that embedded html is escaped '''
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'embedded code block <pre>\n\n``` python\nline 1\nline 2\n```\n\nnew </pre> paragraph'))
        m = parser.normalize(p.markdown())
        parser.reset()
        print(m)
        if type(self) == MistuneTestCase:
            self.assertEqual(m, parser.normalize('<p>embedded code block &lt;pre&gt;</p>\n<pre><code class="lang-python">line 1\nline 2\n</code></pre>\n<p>new &lt;/pre&gt; paragraph</p>'))
        elif type(self) == MarkdownTestCase:
            self.assertEqual(m.replace('class="python"','class="language-python"'), parser.normalize('<p>embedded code block &lt;pre&gt;</p>\n<pre><code class="language-python">line 1\nline 2\n</code></pre>\n<p>new &lt;/pre&gt; paragraph</p>'))
        else:
            expected_result = parser.normalize('<p>embedded code block &lt;pre&gt;</p>\n<div class="codehilite"><pre><span></span><code><span class="n">line</span> <span class="mi">1</span>\n<span class="n">line</span> <span class="mi">2</span>\n</code></pre></div>\n<p>new &lt;/pre&gt; paragraph</p>')
            self.assertEqual(m, expected_result)

    def test_markdown_return_text_on_exception(self):
        ''' string is invalid markdown. missing end of fenced code block '''
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'embedded code block <pre>\n\n``` python\nline 1\nline 2\n\n\nnew </pre> paragraph'))
        m = p.markdown().strip()
        print(m)
        self.assertEqual(m.replace('\n\n','\n'), '<p>embedded code block &lt;pre&gt;</p>\n<p>``` python\nline 1\nline 2</p>\n<p>new &lt;/pre&gt; paragraph</p>')

    def test_markdown_break_on_newline(self):
        self.client.db.config['MARKDOWN_BREAK_ON_NEWLINE'] = True
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'A string with\nline break\ntwice.'))
        m = p.markdown()
        self.assertEqual(2, m.count('<br'))
        self.client.db.config['MARKDOWN_BREAK_ON_NEWLINE'] = False

        m = p.markdown()
        self.assertEqual(0, m.count('<br'))

    def test_markdown_hyperlinked_url(self):
        # classic markdown does not emit a \n at end of rendered string
        # so rstrip \n.
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'http://example.com/'))
        m = p.markdown(hyperlink=1)
        m = self.mangleMarkdown2(m)
        print(m)
        self.assertEqual(m.rstrip('\n'), '<p><a href="http://example.com/" rel="nofollow noopener">http://example.com/</a></p>')

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'<http://example.com/>'))
        m = p.markdown(hyperlink=1)
        m = self.mangleMarkdown2(m)
        self.assertEqual(m.rstrip('\n'), '<p><a href="http://example.com/" rel="nofollow noopener">http://example.com/</a></p>')

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'[label](http://example.com/ "a title")'))
        m = p.markdown(hyperlink=1)
        m = self.mangleMarkdown2(m)
        self.assertEqual(m.rstrip('\n'), '<p><a href="http://example.com/" rel="nofollow noopener" title="a title">label</a></p>')

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'[label](http://example.com/).'))
        m = p.markdown(hyperlink=1)
        m = self.mangleMarkdown2(m)
        self.assertEqual(m.rstrip('\n'), '<p><a href="http://example.com/" rel="nofollow noopener">label</a>.</p>')

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'![](http://example.com/)'))
        m = p.markdown(hyperlink=1)
        m = self.mangleMarkdown2(m)
        self.assertIn(m, [
                '<p><img src="http://example.com/" alt=""/></p>\n',
                '<p><img src="http://example.com/" alt="" /></p>\n',
                '<p><img src="http://example.com/" alt=""></p>\n',
                '<p><img alt="" src="http://example.com/" /></p>', # markdown
                ])

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'An URL http://example.com/ with text'))
        m = p.markdown(hyperlink=1)
        m = self.mangleMarkdown2(m)
        self.assertEqual(m.rstrip('\n'), '<p>An URL <a href="http://example.com/" rel="nofollow noopener">http://example.com/</a> with text</p>')

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'An URL https://example.com/path with text'))
        m = p.markdown(hyperlink=1)
        m = self.mangleMarkdown2(m)
        self.assertEqual(m.rstrip('\n'), '<p>An URL <a href="https://example.com/path" rel="nofollow noopener">https://example.com/path</a> with text</p>')

@skip_mistune
class MistuneTestCase(TemplatingTestCase, MarkdownTests) :
    def setUp(self):
        TemplatingTestCase.setUp(self)

        from roundup.cgi import templating
        self.__markdown = templating.markdown
        templating.markdown = templating._import_mistune()

    def tearDown(self):
        from roundup.cgi import templating
        templating.markdown = self.__markdown

@skip_markdown2
class Markdown2TestCase(TemplatingTestCase, MarkdownTests) :
    def setUp(self):
        TemplatingTestCase.setUp(self)

        from roundup.cgi import templating
        self.__markdown = templating.markdown
        templating.markdown = templating._import_markdown2()

    def tearDown(self):
        from roundup.cgi import templating
        templating.markdown = self.__markdown

@skip_markdown
class MarkdownTestCase(TemplatingTestCase, MarkdownTests) :
    def setUp(self):
        TemplatingTestCase.setUp(self)

        from roundup.cgi import templating
        self.__markdown = templating.markdown
        templating.markdown = templating._import_markdown()

    def tearDown(self):
        from roundup.cgi import templating
        templating.markdown = self.__markdown


class NoMarkdownTestCase(TemplatingTestCase) :
    def setUp(self):
        TemplatingTestCase.setUp(self)

        from roundup.cgi import templating
        self.__markdown = templating.markdown
        templating.markdown = None

    def tearDown(self):
        from roundup.cgi import templating
        templating.markdown = self.__markdown

    def test_string_markdown(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'A string http://localhost with cmeerw@example.com <br> *embedded* \u00df'))
        self.assertEqual(p.markdown(), u2s(u'A string <a href="http://localhost" rel="nofollow noopener">http://localhost</a> with <a href="mailto:cmeerw@example.com">cmeerw@example.com</a> &lt;br&gt; *embedded* \u00df'))

class NoRstTestCase(TemplatingTestCase) :
    def setUp(self):
        TemplatingTestCase.setUp(self)

        from roundup.cgi import templating
        self.__ReStructuredText = templating.ReStructuredText
        templating.ReStructuredText = None

    def tearDown(self):
        from roundup.cgi import templating
        templating.ReStructuredText = self.__ReStructuredText

    def test_string_rst(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'A string with cmeerw@example.com *embedded* \u00df'))
        self.assertEqual(p.rst(), u2s(u'A string with <a href="mailto:cmeerw@example.com">cmeerw@example.com</a> *embedded* \u00df'))

class NumberIntegerHTMLPropertyTestCase(HTMLPropertyTestClass):

    def setUp(self):
        super(NumberIntegerHTMLPropertyTestCase, self).setUp()

        db = self.client.db
        db.issue.addprop(numberval=hyperdb.Number())
        db.issue.addprop(intval=hyperdb.Integer())

        self.client.db.issue.create(title="title",
                                    numberval = "3.14",
                                    intval="314")

    def tearDown(self):
        self.client.db.close()
        memorydb.db_nuke('')

    def test_IntegerHTML(self):
        test_hyperdbInteger = self.client.db.issue.getprops("1")['intval']
        test_Integer = test_hyperdbInteger.from_raw(
            self.client.db.issue.get("1", 'intval')
        )

        # client, classname, nodeid, prop, name, value,
        #    anonymous=0, offset=None
        d = IntegerHTMLProperty(self.client, 'issue', '1',
                                test_hyperdbInteger,
                                'intval', test_Integer)

        self.assertIsInstance(d._value, int)

        self.assertEqual(d.plain(), "314")

        input_expected = """<input id="issue1@intval" name="issue1@intval" size="30" type="text" value="314">"""
        self.assertEqual(d.field(), input_expected)

        input_expected = """<input id="issue1@intval" name="issue1@intval" size="30" step="50" type="text" value="314">"""
        self.assertEqual(d.field(step="50"), input_expected)

        input_expected = """<input id="issue1@intval" name="issue1@intval" size="30" type="text" value="314">"""
        self.assertEqual(d.field(type="text"), input_expected)


        # check permissions return
        is_view_ok_orig = d.is_view_ok
        is_edit_ok_orig = d.is_edit_ok
        no_access = lambda : False

        d.is_view_ok = no_access
        self.assertEqual(d.plain(), "[hidden]")

        d.is_edit_ok = no_access
        self.assertEqual(d.field(), "[hidden]")

        d.is_view_ok = is_view_ok_orig
        self.assertEqual(d.field(), "314")
        d.is_edit_ok = is_edit_ok_orig

    def test_NumberHTML(self):
        test_hyperdbNumber = self.client.db.issue.getprops("1")['numberval']
        test_Number = test_hyperdbNumber.from_raw(
            self.client.db.issue.get("1", 'numberval')
        )

        # client, classname, nodeid, prop, name, value,
        #    anonymous=0, offset=None
        d = NumberHTMLProperty(self.client, 'issue', '1',
                                test_hyperdbNumber,
                                'numberval', test_Number)

        # string needed for memorydb/anydbm backend. Float?? when
        # running against sql backends.
        self.assertIsInstance(d._value, float)

        self.assertEqual(d._value, 3.14)

        input_expected = """<input id="issue1@numberval" name="issue1@numberval" size="30" type="text" value="3.14">"""
        self.assertEqual(d.field(), input_expected)

        input_expected = """<input id="issue1@numberval" name="issue1@numberval" size="30" step="50" type="text" value="3.14">"""
        self.assertEqual(d.field(step="50"), input_expected)

        input_expected = """<input id="issue1@numberval" name="issue1@numberval" size="30" type="text" value="3.14">"""
        self.assertEqual(d.field(type="text"), input_expected)

        self.assertEqual(d.pretty("%0.3f"), "3.140")
        self.assertEqual(d.pretty("%0.3d"), "003")
        self.assertEqual(d.pretty("%2d"), " 3")

        # see what happens if for other values
        value = d._value
        d._value = "1" # integer
        self.assertEqual(d.pretty("%2d"), "1")
        d._value = "I'mNotAFloat" # not a number
        self.assertEqual(d.pretty("%2d"), "I'mNotAFloat")
        d._value = value

        # check permissions return
        is_view_ok_orig = d.is_view_ok
        is_edit_ok_orig = d.is_edit_ok
        no_access = lambda : False

        d.is_view_ok = no_access
        self.assertEqual(d.plain(), "[hidden]")

        d.is_edit_ok = no_access
        self.assertEqual(d.field(), "[hidden]")

        d.is_view_ok = is_view_ok_orig
        self.assertEqual(d.field(), "3.14")
        d.is_edit_ok = is_edit_ok_orig

class ZUtilsTestcase(TemplatingTestCase):

    def test_Iterator(self):
        """Test all the iterator functions and properties.
        """
        sequence = ['one', 'two', '3', 4]
        i = Iterator(sequence)
        for j in [ # element, item, 1st, last, even, odd, number,
                   # letter, Letter, roman, Roman
                (1, "one", 1, 0, True,  0, 1, 'a', 'A', 'i',   'I'),
                (1, "two", 0, 0, False, 1, 2, 'b', 'B', 'ii',  'II'),
                (1, "3",   0, 0, True,  0, 3, 'c', 'C', 'iii', 'III'),
                (1,   4,   0, 1, False, 1, 4, 'd', 'D', 'iv',  'IV'),
                # next() fails with 0 when past end of sequence
                # everything else is left at end of sequence
                (0,   4,   0, 1, False, 1, 4, 'd', 'D', 'iv',  'IV'),


        ]:
            element = i.next()  # returns 1 if next item else 0
            print(i.item)
            self.assertEqual(element, j[0])
            self.assertEqual(i.item, j[1])
            self.assertEqual(i.first(), j[2])
            self.assertEqual(i.start, j[2])
            self.assertEqual(i.last(), j[3])
            self.assertEqual(i.end, j[3])
            self.assertIs(i.even(), j[4])
            self.assertEqual(i.odd(), j[5])
            self.assertEqual(i.number(), j[6])
            self.assertEqual(i.index, j[6] - 1)
            self.assertEqual(i.nextIndex, j[6])
            self.assertEqual(i.letter(), j[7])
            self.assertEqual(i.Letter(), j[8])
            self.assertEqual(i.roman(), j[9])
            self.assertEqual(i.Roman(), j[10])

        class I:
            def __init__(self, name, data):
                self.name = name
                self.data = data

        sequence = [I('Al',   'd'),
                    I('Bob',  'e'),
                    I('Bob',  'd'),
                    I('Chip', 'd')
        ]

        iterator = iter(sequence)

        # Iterator is supposed take both sequence and Python iterator.
        for source in [sequence, iterator]:
            i = Iterator(source)

            element = i.next()  # returns 1 if next item else 0
            item1 = i.item

            # note these can trigger calls by first/last to same_part().
            # It can return true for first/last even when there are more
            # items in the sequence. I am just testing the current
            # implementation. Woe to the person who tries to change
            # Iterator.py.

            self.assertEqual(element, 1)
            # i.start == 1, so it bypasses name check
            self.assertEqual(i.first(name='namea'), 1)
            self.assertEqual(i.first(name='name'), 1)
            # i.end == 0 so it uses name check in object
            self.assertEqual(i.last(name='namea'), 0)
            self.assertEqual(i.last(name='name'), 0)

            element = i.next()  # returns 1 if next item else 0
            item2 = i.item
            self.assertEqual(element, 1)
            # i.start == 0 so it uses name check
            # between item1 and item2
            self.assertEqual(i.first(name='namea'), 0)
            self.assertEqual(i.first(name='name'), 0)
            # i.end == 0 so it uses name check in object
            # between item2 and the next item item3
            self.assertEqual(i.last(name='namea'), 0)
            self.assertEqual(i.last(name='name'), True)

            element = i.next()  # returns 1 if next item else 0
            item3 = i.item
            self.assertEqual(element, 1)
            # i.start == 0 so it uses name check
            self.assertEqual(i.first(name='namea'), 0)
            self.assertEqual(i.first(name='name'), 1)
            # i.end == 0 so it uses name check in object
            # between item3 and the next item item4
            self.assertEqual(i.last(name='namea'), 0)
            self.assertEqual(i.last(name='name'), 0)

            element = i.next()  # returns 1 if next item else 0
            item4 = i.item
            self.assertEqual(element, 1)
            # i.start == 0 so it uses name check
            self.assertEqual(i.first(name='namea'), 0)
            self.assertEqual(i.first(name='name'), 0)
            # i.end == 0 so it uses name check in object
            # last two object have same name (1)
            self.assertEqual(i.last(name='namea'), 1)
            self.assertEqual(i.last(name='name'), 1)

            element = i.next()  # returns 1 if next item else 0
            self.assertEqual(element, 0)

            # this is the underlying call for first/last
            # when i.start/i.end are 0
            # use non-existing attribute name, same item
            self.assertIs(i.same_part('namea', item2, item2), False)
            # use correct attribute name
            self.assertIs(i.same_part('name', item2, item2), True)
            # use no attribute name
            self.assertIs(i.same_part(None, item2, item2), True)

            # use non-existing attribute name, different item
            # non-matching names
            self.assertIs(i.same_part('namea', item1, item2), False)
            # use correct attribute name
            self.assertIs(i.same_part('name', item1, item2), False)
            # use no attribute name
            self.assertIs(i.same_part(None, item1, item2), False)

            # use non-existing attribute name, different item
            # matching names
            self.assertIs(i.same_part('namea', item2, item3), False)
            # use correct attribute name
            self.assertIs(i.same_part('name', item2, item3), True)
            # use no attribute name
            self.assertIs(i.same_part(None, item2, item3), False)

r'''
class HTMLPermissions:
    def is_edit_ok(self):
    def is_view_ok(self):
    def is_only_view_ok(self):
    def view_check(self):
    def edit_check(self):

def input_html4(**attrs):

class HTMLInputMixin:
    def __init__(self):

class HTMLClass(HTMLInputMixin, HTMLPermissions):
    def __init__(self, client, classname, anonymous=0):
    def __repr__(self):
    def __getitem__(self, item):
    def __getattr__(self, attr):
    def designator(self):
    def getItem(self, itemid, num_re=re.compile(r'-?\d+')):
    def properties(self, sort=1, cansearch=True):
    def list(self, sort_on=None):
    def csv(self):
    def propnames(self):
    def filter(self, request=None, filterspec={}, sort=(None,None),
    def classhelp(self, properties=None, label='(list)', width='500',
    def submit(self, label="Submit New Entry"):
    def history(self):
    def renderWith(self, name, **kwargs):

class HTMLItem(HTMLInputMixin, HTMLPermissions):
    def __init__(self, client, classname, nodeid, anonymous=0):
    def __repr__(self):
    def __getitem__(self, item):
    def __getattr__(self, attr):
    def designator(self):
    def is_retired(self):
    def submit(self, label="Submit Changes"):
    def journal(self, direction='descending'):
    def history(self, direction='descending', dre=re.compile('\d+')):
    def renderQueryForm(self):

class HTMLUserPermission:
    def is_edit_ok(self):
    def is_view_ok(self):
    def _user_perm_check(self, type):

class HTMLUserClass(HTMLUserPermission, HTMLClass):

class HTMLUser(HTMLUserPermission, HTMLItem):
    def __init__(self, client, classname, nodeid, anonymous=0):
    def hasPermission(self, permission, classname=_marker):

class HTMLProperty(HTMLInputMixin, HTMLPermissions):
    def __init__(self, client, classname, nodeid, prop, name, value,
    def __repr__(self):
    def __str__(self):
    def __lt__(self, other):
    def __le__(self, other):
    def __eq__(self, other):
    def __ne__(self, other):
    def __gt__(self, other):
    def __ge__(self, other):
    def is_edit_ok(self):
    def is_view_ok(self):

class StringHTMLProperty(HTMLProperty):
    def _hyper_repl(self, match):
    def hyperlinked(self):
    def plain(self, escape=0, hyperlink=0):
    def stext(self, escape=0):
    def field(self, size = 30):
    def multiline(self, escape=0, rows=5, cols=40):
    def email(self, escape=1):

class PasswordHTMLProperty(HTMLProperty):
    def plain(self):
    def field(self, size = 30):
    def confirm(self, size = 30):

class NumberHTMLProperty(HTMLProperty):
    def plain(self):
    def field(self, size = 30):
    def __int__(self):
    def __float__(self):

class IntegerHTMLProperty(HTMLProperty):
    def plain(self):
    def field(self, size = 30):
    def __int__(self):

class BooleanHTMLProperty(HTMLProperty):
    def plain(self):
    def field(self):

class DateHTMLProperty(HTMLProperty):
    def plain(self):
    def now(self):
    def field(self, size = 30):
    def reldate(self, pretty=1):
    def pretty(self, format=_marker):
    def local(self, offset):

class IntervalHTMLProperty(HTMLProperty):
    def plain(self):
    def pretty(self):
    def field(self, size = 30):

class LinkHTMLProperty(HTMLProperty):
    def __init__(self, *args, **kw):
    def __getattr__(self, attr):
    def plain(self, escape=0):
    def field(self, showid=0, size=None):
    def menu(self, size=None, height=None, showid=0, additional=[],

class MultilinkHTMLProperty(HTMLProperty):
    def __init__(self, *args, **kwargs):
    def __len__(self):
    def __getattr__(self, attr):
    def __getitem__(self, num):
    def __contains__(self, value):
    def reverse(self):
    def sorted(self, property, reverse=False):
    def plain(self, escape=0):
    def field(self, size=30, showid=0):
    def menu(self, size=None, height=None, showid=0, additional=[],

def make_key_function(db, classname, sort_on=None):
    def keyfunc(a):

def find_sort_key(linkcl):

def handleListCGIValue(value):

class ShowDict:
    def __init__(self, columns):
    def __getitem__(self, name):

class HTMLRequest(HTMLInputMixin):
    def __init__(self, client):
    def _post_init(self):
    def updateFromURL(self, url):
    def update(self, kwargs):
    def description(self):
    def __str__(self):
    def indexargs_form(self, columns=1, sort=1, group=1, filter=1,
    def indexargs_url(self, url, args):
    def base_javascript(self):
    def batch(self):

class Batch(ZTUtils.Batch):
    def __init__(self, client, sequence, size, start, end=0, orphan=0,
    def __getitem__(self, index):
    def propchanged(self, property):
    def previous(self):
    def next(self):

#class TemplatingUtils:
#    def __init__(self, client):
#    def Batch(self, sequence, size, start, end=0, orphan=0, overlap=0):

class NoTemplate(Exception):
class Unauthorised(Exception):
    def __init__(self, action, klass):
    def __str__(self):

class Loader:
    def __init__(self, dir):
    def precompileTemplates(self):
    def load(self, name, extension=None):
    def __getitem__(self, name):

class RoundupPageTemplate(PageTemplate.PageTemplate):
    def getContext(self, client, classname, request):
    def render(self, client, classname, request, **options):
    def __repr__(self):
'''

# vim: set et sts=4 sw=4 :
