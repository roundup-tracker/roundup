import unittest
from cgi import FieldStorage, MiniFieldStorage

from roundup.cgi.templating import *
from test_actions import MockNull, true

class MockDatabase(MockNull):
    def getclass(self, name):
        return self.classes[name]

class TemplatingTestCase(unittest.TestCase):
    def setUp(self):
        self.form = FieldStorage()
        self.client = MockNull()
        self.client.db = db = MockDatabase()
        db.security.hasPermission = lambda *args, **kw: True
        self.client.form = self.form

class HTMLDatabaseTestCase(TemplatingTestCase):
    def test_HTMLDatabase___getitem__(self):
        db = HTMLDatabase(self.client)
        self.assert_(isinstance(db['issue'], HTMLClass))
        # following assertions are invalid
        # since roundup/cgi/templating.py r1.173.
        # HTMLItem is function, not class,
        # but HTMLUserClass and HTMLUser are passed on.
        # these classes are no more.  they have ceased to be.
        #self.assert_(isinstance(db['user'], HTMLUserClass))
        #self.assert_(isinstance(db['issue1'], HTMLItem))
        #self.assert_(isinstance(db['user1'], HTMLUser))

    def test_HTMLDatabase___getattr__(self):
        db = HTMLDatabase(self.client)
        self.assert_(isinstance(db.issue, HTMLClass))
        # see comment in test_HTMLDatabase___getitem__
        #self.assert_(isinstance(db.user, HTMLUserClass))
        #self.assert_(isinstance(db.issue1, HTMLItem))
        #self.assert_(isinstance(db.user1, HTMLUser))

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
                raise KeyError, 'fail'
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
        self.form.list.append(MiniFieldStorage("status", "1"))
        self.form.list.append(MiniFieldStorage("status", "2"))
        status = hyperdb.Link("status")
        self.client.db.classes = dict \
            ( issue = MockNull(getprops = lambda : dict(status = status))
            , status  = MockNull(get = lambda id, name : id, lookup = lookup)
            )
        cls = HTMLClass(self.client, "issue")
        cls["status"]

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

    def test_url_match(self):
        '''Test the URL regular expression in StringHTMLProperty.
        '''
        def t(s, nothing=False, **groups):
            m = StringHTMLProperty.hyper_re.search(s)
            if nothing:
                if m:
                    self.assertEquals(m, None, '%r matched (%r)'%(s, m.groupdict()))
                return
            else:
                self.assertNotEquals(m, None, '%r did not match'%s)
            d = m.groupdict()
            for g in groups:
                self.assertEquals(d[g], groups[g], '%s %r != %r in %r'%(g, d[g],
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
           '<a href="http://roundup.net/">http://roundup.net/</a>')
        ae(t('&lt;HTTP://roundup.net/&gt;'),
           '&lt;<a href="HTTP://roundup.net/">HTTP://roundup.net/</a>&gt;')
        ae(t('&lt;http://roundup.net/&gt;.'),
            '&lt;<a href="http://roundup.net/">http://roundup.net/</a>&gt;.')
        ae(t('&lt;www.roundup.net&gt;'),
           '&lt;<a href="http://www.roundup.net">www.roundup.net</a>&gt;')
        ae(t('(www.roundup.net)'),
           '(<a href="http://www.roundup.net">www.roundup.net</a>)')
        ae(t('foo http://msdn.microsoft.com/en-us/library/ms741540(VS.85).aspx bar'),
           'foo <a href="http://msdn.microsoft.com/en-us/library/ms741540(VS.85).aspx">'
           'http://msdn.microsoft.com/en-us/library/ms741540(VS.85).aspx</a> bar')
        ae(t('(e.g. http://en.wikipedia.org/wiki/Python_(programming_language))'),
           '(e.g. <a href="http://en.wikipedia.org/wiki/Python_(programming_language)">'
           'http://en.wikipedia.org/wiki/Python_(programming_language)</a>)')
        ae(t('(e.g. http://en.wikipedia.org/wiki/Python_(programming_language)).'),
           '(e.g. <a href="http://en.wikipedia.org/wiki/Python_(programming_language)">'
           'http://en.wikipedia.org/wiki/Python_(programming_language)</a>).')
        ae(t('(e.g. http://en.wikipedia.org/wiki/Python_(programming_language))&gt;.'),
           '(e.g. <a href="http://en.wikipedia.org/wiki/Python_(programming_language)">'
           'http://en.wikipedia.org/wiki/Python_(programming_language)</a>)&gt;.')
        ae(t('(e.g. http://en.wikipedia.org/wiki/Python_(programming_language&gt;)).'),
           '(e.g. <a href="http://en.wikipedia.org/wiki/Python_(programming_language">'
           'http://en.wikipedia.org/wiki/Python_(programming_language</a>&gt;)).')
        for c in '.,;:!':
            # trailing punctuation is not included
            ae(t('http://roundup.net/%c ' % c),
               '<a href="http://roundup.net/">http://roundup.net/</a>%c ' % c)
            # but it's included if it's part of the URL
            ae(t('http://roundup.net/%c/' % c),
               '<a href="http://roundup.net/%c/">http://roundup.net/%c/</a>' % (c, c))

'''
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
    def getItem(self, itemid, num_re=re.compile('-?\d+')):
    def properties(self, sort=1):
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
    def __cmp__(self, other):
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
    def plain(self, escape=0):
    def field(self, size=30, showid=0):
    def menu(self, size=None, height=None, showid=0, additional=[],

def make_sort_function(db, classname, sort_on=None):
    def sortfunc(a, b):

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

class TemplatingUtils:
    def __init__(self, client):
    def Batch(self, sequence, size, start, end=0, orphan=0, overlap=0):

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
