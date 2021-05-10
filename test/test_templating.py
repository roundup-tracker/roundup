from __future__ import print_function
import unittest
from cgi import FieldStorage, MiniFieldStorage

from roundup.cgi.templating import *
from .test_actions import MockNull, true


import pytest
from .pytest_patcher import mark_class

if ReStructuredText:
    skip_rst = lambda func, *args, **kwargs: func
else:
    skip_rst = mark_class(pytest.mark.skip(
        reason='ReStructuredText not available'))

if StructuredText:
    skip_stext = lambda func, *args, **kwargs: func
else:
    skip_stext = mark_class(pytest.mark.skip(
        reason='StructuredText not available'))

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

class MockDatabase(MockNull):
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
        MockDatabase.storage[key].update(props)

    def get(self, key, field, default=None):
        if key not in MockDatabase.storage:
            return default
        return MockDatabase.storage[key][field]

    def exists(self,key):
        return key in MockDatabase.storage

    def getOTKManager(self):
        return MockDatabase()

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
        self.client.db.config = {'WEB_CSRF_TOKEN_LIFETIME': 10, 'MARKDOWN_BREAK_ON_NEWLINE': False }

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

class FunctionsTestCase(TemplatingTestCase):
    def test_lookupIds(self):
        db = HTMLDatabase(self.client)
        def lookup(key):
            if key == 'ok':
                return '1'
            if key == 'fail':
                raise KeyError('fail')
            return key
        db._db.classes = {'issue': MockNull(lookup=lookup)}
        prop = MockNull(classname='issue')
        self.assertEqual(lookupIds(db._db, prop, ['1','2']), ['1','2'])
        self.assertEqual(lookupIds(db._db, prop, ['ok','2']), ['1','2'])
        self.assertEqual(lookupIds(db._db, prop, ['ok', 'fail'], 1),
            ['1', 'fail'])
        self.assertEqual(lookupIds(db._db, prop, ['ok', 'fail']), ['1'])

    def test_lookupKeys(self):
        db = HTMLDatabase(self.client)
        def get(entry, key):
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
           db. Make sure nonce is 64 chars long. Lookup the nonce in
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

            self.assertEqual(len(nonce1), 64)

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
        test_result = ('A long string that needs to be wrapped to 80'
                       ' characters and no more. Put in a\n'
                       'link <a href="issue1">issue1</a>. Put in'
                       ' &lt;html&gt; to be escaped. Put in a <a'
                       ' href="https://example.com/link"'
                       ' rel="nofollow noopener">'
                       'https://example.com/link</a> as\n'
                       'well. Let us see if it will wrap properly.')

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test',
                               test_string)
        self.assertEqual(p.wrapped(), test_result)

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

    @skip_stext
    def test_string_stext(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'A string with cmeerw@example.com *embedded* \u00df'))
        self.assertEqual(p.stext(), u2s(u'<p>A string with <a href="mailto:cmeerw@example.com">cmeerw@example.com</a> <em>embedded</em> \u00df</p>\n'))

    def test_string_field(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', 'A string <b> with rouilj@example.com embedded &lt; html</b>')
        self.assertEqual(p.field(), '<input name="test1@test" size="30" type="text" value="A string &lt;b&gt; with rouilj@example.com embedded &amp;lt; html&lt;/b&gt;">')

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
        t('www.user:pass@host.net', email='pass@host.net')
        t('user:pass@www.host.net', url='user:pass@www.host.net')
        t('123.35', nothing=True)
        t('-.3535', nothing=True)

    def test_url_replace(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', '')
        def t(s): return p.hyper_re.sub(p._hyper_repl, s)
        ae = self.assertEqual
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
            # but it's included if it's part of the URL
            ae(t('http://roundup.net/%c/' % c),
               '<a href="http://roundup.net/%c/" rel="nofollow noopener">http://roundup.net/%c/</a>' % (c, c))

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

    def test_input_xhtml(self):
        # boolean attributes are attribute name="attribute name"
        # indicate with attr=None or attr="attr"
        #    e.g. disabled="disabled"
        input=input_xhtml(required=None, size=30)
        self.assertEqual(input, '<input required="required" size="30" type="text"/>')

        input=input_xhtml(required="required", size=30)
        self.assertEqual(input, '<input required="required" size="30" type="text"/>')

        attrs={"required": None, "class": "required", "size": 30}
        input=input_xhtml(**attrs)
        self.assertEqual(input, '<input class="required" required="required" size="30" type="text"/>')

        attrs={"disabled": "disabled", "class": "required", "size": 30}
        input=input_xhtml(**attrs)
        self.assertEqual(input, '<input class="required" disabled="disabled" size="30" type="text"/>')


class HTMLPropertyTestClass(unittest.TestCase):
    def setUp(self):
        self.form = FieldStorage()
        self.client = MockNull()
        self.client.db = db = MockDatabase()
        db.security.hasPermission = lambda *args, **kw: True
        self.client.form = self.form

        self.client._props = MockNull()
        # add client props for testing anti_csrf_nonce
        self.client.session_api = MockNull(_sid="1234567890")
        self.client.db.getuid = lambda : 10

class DateHTMLPropertyTestCase(HTMLPropertyTestClass):

    def test_DateHTMLWithText(self):
        """Test methods when DateHTMLProperty._value is a string
           rather than a hyperdb.Date()
        """
        test_datestring = "2021-01-01 11:22:10"
        test_date = hyperdb.Date("2")

        self.form.list.append(MiniFieldStorage("test1@test", test_datestring))
        self.client._props=test_date

        self.client.db.classes = dict \
            ( test = MockNull(getprops = lambda : test_date)
            )

        # client, classname, nodeid, prop, name, value,
        #    anonymous=0, offset=None
        d = DateHTMLProperty(self.client, 'test', '1', self.client._props,
                             'test', '')
        self.assertIs(type(d._value), str)
        self.assertEqual(d.pretty(), "2021-01-01 11:22:10")
        self.assertEqual(d.plain(), "2021-01-01 11:22:10")
        input = """<input name="test1@test" size="30" type="text" value="2021-01-01 11:22:10"><a class="classhelp" data-calurl="test?@template=calendar&amp;amp;property=test&amp;amp;form=itemSynopsis&amp;date=2021-01-01 11:22:10" data-height="200" data-width="300" href="javascript:help_window('test?@template=calendar&amp;property=test&amp;form=itemSynopsis&date=2021-01-01 11:22:10', 300, 200)">(cal)</a>"""
        self.assertEqual(d.field(), input)

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
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'A link <http://localhost>'))
        self.assertEqual(p.markdown().strip(), u2s(u'<p>A link <a href="http://localhost">http://localhost</a></p>'))

    def test_string_markdown_link_item(self):
        """ The link formats for the different markdown engines changes.
            Order of attributes, value for rel (noopener, nofollow etc)
            is different. So most tests check for a substring that indicates
            success rather than the entire returned string.
        """
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'An issue1 link'))
        self.assertIn( u2s(u'href="issue1"'), p.markdown().strip())
        # just verify that plain linking is working
        self.assertIn( u2s(u'href="issue1"'), p.plain(hyperlink=1))

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'An [issue1](issue1) link'))
        self.assertIn( u2s(u'href="issue1"'), p.markdown().strip())
        # just verify that plain linking is working
        self.assertIn( u2s(u'href="issue1"'), p.plain(hyperlink=1))

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'An [issue1](https://example.com/issue1) link'))
        self.assertIn( u2s(u'href="https://example.com/issue1"'), p.markdown().strip())

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'An [issue1] (https://example.com/issue1) link'))
        self.assertIn( u2s(u'href="issue1"'), p.markdown().strip())
        if type(self) == MistuneTestCase:
            # mistune makes the https url into a real link
            self.assertIn( u2s(u'href="https://example.com/issue1"'), p.markdown().strip())
        else:
            # the other two engines leave the parenthesized url as is.
            self.assertIn( u2s(u' (https://example.com/issue1) link'), p.markdown().strip())

    def test_string_markdown_link(self):
        # markdown2 and markdown escape the email address
        try:
            from html import unescape as html_unescape
        except ImportError:
            from HTMLParser import HTMLParser
            html_unescape = HTMLParser().unescape

        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'A link <cmeerw@example.com>'))
        m = html_unescape(p.markdown().strip())
        m = self.mangleMarkdown2(m)

        self.assertEqual(m, u2s(u'<p>A link <a href="mailto:cmeerw@example.com">cmeerw@example.com</a></p>'))

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
        ''' also verify that embedded html is escaped '''
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'embedded code block <pre>\n\n``` python\nline 1\nline 2\n```\n\nnew </pre> paragraph'))
        m = p.markdown().strip()
        print(m)
        if type(self) == MistuneTestCase:
            self.assertEqual(m.replace('\n\n','\n'), '<p>embedded code block &lt;pre&gt;</p>\n<pre><code class="lang-python">line 1\nline 2\n</code></pre>\n<p>new &lt;/pre&gt; paragraph</p>')
        elif type(self) == MarkdownTestCase:
            self.assertEqual(m.replace('\n\n','\n'), '<p>embedded code block &lt;pre&gt;</p>\n<pre><code class="language-python">line 1\nline 2\n</code></pre>\n<p>new &lt;/pre&gt; paragraph</p>')
        else:
            self.assertEqual(m.replace('\n\n', '\n'), '<p>embedded code block &lt;pre&gt;</p>\n<div class="codehilite"><pre><span></span><code><span class="n">line</span> <span class="mi">1</span>\n<span class="n">line</span> <span class="mi">2</span>\n</code></pre></div>\n<p>new &lt;/pre&gt; paragraph</p>')

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

class NoStextTestCase(TemplatingTestCase) :
    def setUp(self):
        TemplatingTestCase.setUp(self)

        from roundup.cgi import templating
        self.__StructuredText = templating.StructuredText
        templating.StructuredText = None

    def tearDown(self):
        from roundup.cgi import templating
        templating.StructuredText = self.__StructuredText

    def test_string_stext(self):
        p = StringHTMLProperty(self.client, 'test', '1', None, 'test', u2s(u'A string with cmeerw@example.com *embedded* \u00df'))
        self.assertEqual(p.stext(), u2s(u'A string with <a href="mailto:cmeerw@example.com">cmeerw@example.com</a> *embedded* \u00df'))


r'''
class HTMLPermissions:
    def is_edit_ok(self):
    def is_view_ok(self):
    def is_only_view_ok(self):
    def view_check(self):
    def edit_check(self):

def input_html4(**attrs):
def input_xhtml(**attrs):

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
