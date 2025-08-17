'''Implement an in-memory hyperdb for testing purposes.
'''

import os
import shutil
import time

from roundup import configuration, date, hyperdb, password, roundupdb, security
from roundup.anypy.strings import s2b
from roundup.backends import back_anydbm, indexer_common, indexer_dbm, sessions_dbm
from roundup.support import ensureParentsExist
from roundup.test.tx_Source_detector import init as tx_Source_init

default_prefix = '../../share/roundup/templates/classic'


def new_config(debug=False, prefix=default_prefix):
    if not prefix.startswith('/'):
        prefix = os.path.join(os.path.dirname(__file__), prefix)
    config = configuration.CoreConfig()
    config.detectors = configuration.UserConfig(
        os.path.join(prefix, "detectors/config.ini"))
    config.ext = configuration.UserConfig(
        os.path.join(prefix, "extensions/config.ini"))
    config.DATABASE = "db"
    # config.logging = MockNull()
    # these TRACKER_WEB and MAIL_DOMAIN values are used in mailgw tests
    if debug:
        config.LOGGING_LEVEL = "DEBUG"
    config.MAIL_DOMAIN = "your.tracker.email.domain.example"
    config.TRACKER_WEB = "http://tracker.example/cgi-bin/roundup.cgi/bugs/"
    return config


def create(journaltag, create=True, debug=False, prefix=default_prefix):
    # "Nuke" in-memory db
    db_nuke('')

    db = Database(new_config(debug), journaltag)

    # load standard schema
    if not prefix.startswith('/'):
        prefix = os.path.join(os.path.dirname(__file__), prefix)

    schema = os.path.join(prefix, 'schema.py')
    hyperdb_vars = hyperdb.__dict__
    hyperdb_vars['Class'] = Class
    hyperdb_vars['FileClass'] = FileClass
    hyperdb_vars['IssueClass'] = IssueClass
    hyperdb_vars['db'] = db

    with open(schema) as fd:
        exec(compile(fd.read(), schema, 'exec'), hyperdb_vars)

    initial_data = os.path.join(prefix, 'initial_data.py')
    admin_vars = {"db": db, "admin_email": "admin@test.com",
                  "adminpw": password.Password('sekrit', config=db.config)}
    with open(initial_data) as fd:
        exec(compile(fd.read(), initial_data, 'exec'), admin_vars)

    # load standard detectors
    dirname = os.path.join(prefix, 'detectors')
    for fn in os.listdir(dirname):
        if not fn.endswith('.py'): continue                       # noqa: E701
        exec_vars = {}
        with open(os.path.join(dirname, fn)) as fd:
            exec(compile(fd.read(),
                         os.path.join(dirname, fn), 'exec'), exec_vars)
        exec_vars['init'](db)

    tx_Source_init(db)

    '''
    status = Class(db, "status", name=String())
    status.setkey("name")
    priority = Class(db, "priority", name=String(), order=String())
    priority.setkey("name")
    keyword = Class(db, "keyword", name=String(), order=String())
    keyword.setkey("name")
    user = Class(db, "user", username=String(), password=Password(),
        assignable=Boolean(), age=Number(), roles=String(), address=String(),
        supervisor=Link('user'),realname=String(),alternate_addresses=String())
    user.setkey("username")
    file = FileClass(db, "file", name=String(), type=String(),
        comment=String(indexme="yes"), fooz=Password())
    file_nidx = FileClass(db, "file_nidx", content=String(indexme='no'))
    issue = IssueClass(db, "issue", title=String(indexme="yes"),
        status=Link("status"), nosy=Multilink("user"), deadline=Date(),
        foo=Interval(), files=Multilink("file"), assignedto=Link('user'),
        priority=Link('priority'), spam=Multilink('msg'),
        feedback=Link('msg'))
    stuff = Class(db, "stuff", stuff=String())
    session = Class(db, 'session', title=String())
    msg = FileClass(db, "msg", date=Date(),
                           author=Link("user", do_journal='no'),
                           files=Multilink('file'), inreplyto=String(),
                           messageid=String(), summary=String(),
                           content=String(),
                           recipients=Multilink("user", do_journal='no')
                           )
    '''
    if create:
        db.user.create(username="fred", roles='User',
                       password=password.Password('sekrit',
                                                  config=db.config),
                       address='fred@example.com')

    db.security.addPermissionToRole('User', 'Email Access')
    '''
    db.security.addPermission(name='Register', klass='user')
    db.security.addPermissionToRole('User', 'Web Access')
    db.security.addPermissionToRole('Anonymous', 'Email Access')
    db.security.addPermissionToRole('Anonymous', 'Register', 'user')
    for cl in 'issue', 'file', 'msg', 'keyword':
        db.security.addPermissionToRole('User', 'View', cl)
        db.security.addPermissionToRole('User', 'Edit', cl)
        db.security.addPermissionToRole('User', 'Create', cl)
    for cl in 'priority', 'status':
        db.security.addPermissionToRole('User', 'View', cl)
    '''
    return db


class cldb(dict):
    def __init__(self, **values):
        super(cldb, self).__init__()
        for key, value in values.items():
            super(cldb, self).__setitem__(s2b(key), value)

    def __getitem__(self, key):
        return super(cldb, self).__getitem__(s2b(key))

    def __setitem__(self, key, value):
        return super(cldb, self).__setitem__(s2b(key), value)

    def __delitem__(self, key):
        return super(cldb, self).__delitem__(s2b(key))

    def __contains__(self, key):
        return super(cldb, self).__contains__(s2b(key))

    def close(self):
        pass


class BasicDatabase(dict):
    ''' Provide a nice encapsulation of an anydbm store.

        Keys are id strings, values are automatically marshalled data.
    '''
    def __init__(self, **values):
        super(BasicDatabase, self).__init__()
        for k, v in values.items():
            super(BasicDatabase, self).__setitem__(s2b(k), v)

    def __getitem__(self, key):
        if key not in self:
            d = self[key] = {}
            return d
        return super(BasicDatabase, self).__getitem__(s2b(key))

    def __setitem__(self, key, value):
        return super(BasicDatabase, self).__setitem__(s2b(key), value)

    def __delitem__(self, key):
        return super(BasicDatabase, self).__delitem__(s2b(key))

    def __contains__(self, key):
        return super(BasicDatabase, self).__contains__(s2b(key))

    def exists(self, infoid):
        return infoid in self
    _marker = []

    def get(self, infoid, value, default=_marker):
        if infoid not in self:
            if default is self._marker:
                raise KeyError
            else:
                return default
        return self[infoid].get(value, default)

    def getall(self, infoid):
        if infoid not in self:
            raise KeyError(infoid)
        return self[infoid]

    def set(self, infoid, **newvalues):
        if '__timestamp' in newvalues:
            try:
                float(newvalues['__timestamp'])
            except ValueError:
                if infoid in self:
                    del (newvalues['__timestamp'])
                else:
                    newvalues['__timestamp'] = time.time()
        self[infoid].update(newvalues)

    def list(self):
        return list(self.keys())

    def destroy(self, infoid):
        del self[infoid]

    def commit(self):
        pass

    def close(self):
        pass

    def updateTimestamp(self, sessid):
        sess = self.get(sessid, '__timestamp', None)
        now = time.time()
        if sess is None or now > sess + 60:
            self.set(sessid, __timestamp=now)

    def clean(self):
        pass


class Sessions(BasicDatabase, sessions_dbm.Sessions):
    name = 'sessions'


class OneTimeKeys(BasicDatabase, sessions_dbm.OneTimeKeys):
    name = 'otks'


class Indexer(indexer_dbm.Indexer):
    def __init__(self, db):
        indexer_common.Indexer.__init__(self, db)
        self.reindex = 0
        self.quiet = 9
        self.changed = 0

    def load_index(self, reload=0, wordlist=None):
        # Unless reload is indicated, do not load twice
        if self.index_loaded() and not reload:
            return 0
        self.words = {}
        self.files = {'_TOP': (0, None)}
        self.fileids = {}
        self.changed = 0

    def save_index(self):
        pass

    def force_reindex(self):
        # TODO I'm concerned that force_reindex may not be tested by
        # testForcedReindexing if the functionality can just be removed
        pass


class Database(back_anydbm.Database):
    """A database for storing records containing flexible data types.

    Transaction stuff TODO:

    - check the timestamp of the class file and nuke the cache if it's
      modified. Do some sort of conflict checking on the dirty stuff.
    - perhaps detect write collisions (related to above)?
    """

    dbtype = "memorydb"

    # Make it a little more persistent across re-open
    memdb = {}

    def __init__(self, config, journaltag=None):
        self.config, self.journaltag = config, journaltag
        self.classes = {}
        self.files = {}
        self.tx_files = {}
        self.security = security.Security(self)
        self.stats = {'cache_hits': 0, 'cache_misses': 0, 'get_items': 0,
                      'filtering': 0}
        self.sessions = Sessions()
        self.otks = OneTimeKeys()
        self.indexer = Indexer(self)
        roundupdb.Database.__init__(self)

        # anydbm bits
        self.cache = {}           # cache of nodes loaded or created
        self.dirtynodes = {}      # keep track of the dirty nodes by class
        self.newnodes = {}        # keep track of the new nodes by class
        self.destroyednodes = {}  # keep track of the destroyed nodes by class
        self.transactions = []
        self.tx_Source = None
        # persistence across re-open
        self.items = self.__class__.memdb.get('items', {})
        self.ids = self.__class__.memdb.get('ids', {})
        self.journals = self.__class__.memdb.get('journals', {})

    def filename(self, classname, nodeid, property=None, create=0):
        shutil.copyfile(__file__, __file__ + '.dummy')
        return __file__ + '.dummy'

    def filesize(self, classname, nodeid, property=None, create=0):
        return len(self.getfile(classname, nodeid, property))

    def post_init(self):
        super(Database, self).post_init()

    def refresh_database(self):
        pass

    def getSessionManager(self):
        return self.sessions

    def getOTKManager(self):
        return self.otks

    def reindex(self, classname=None, show_progress=False):
        pass

    def __repr__(self):
        return '<memorydb instance at %x>' % id(self)

    def storefile(self, classname, nodeid, property, content):
        if isinstance(content, str):
            content = s2b(content)
        self.tx_files[classname, nodeid, property] = content
        self.transactions.append((self.doStoreFile, (classname, nodeid,
                                                     property)))

    def getfile(self, classname, nodeid, property):
        if (classname, nodeid, property) in self.tx_files:
            return self.tx_files[classname, nodeid, property]
        return self.files[classname, nodeid, property]

    def doStoreFile(self, classname, nodeid, property, **databases):
        self.files[classname, nodeid, property] = self.tx_files[classname, nodeid, property]
        return (classname, nodeid)

    def rollbackStoreFile(self, classname, nodeid, property, **databases):
        del self.tx_files[classname, nodeid, property]

    def numfiles(self):
        return len(self.files) + len(self.tx_files)

    def close(self):
        self.clearCache()
        self.tx_files = {}
        # kill the schema too
        self.classes = {}
        # just keep the .items
        # persistence across re-open
        self.__class__.memdb['items'] = self.items
        self.__class__.memdb['ids'] = self.ids
        self.__class__.memdb['journals'] = self.journals

    #
    # Classes
    #
    def __getattr__(self, classname):
        """A convenient way of calling self.getclass(classname)."""
        if classname in self.classes:
            return self.classes[classname]
        raise AttributeError(classname)

    def addclass(self, cl):
        cn = cl.classname
        if cn in self.classes:
            raise ValueError('Class "%s" already defined.' % cn)
        self.classes[cn] = cl
        if cn not in self.items:
            self.items[cn] = cldb()
            self.ids[cn] = 0

        # add default Edit and View permissions
        self.security.addPermission(name="Create", klass=cn,
                                    description="User is allowed to create " +
                                    cn)
        self.security.addPermission(name="Edit", klass=cn,
                                    description="User is allowed to edit " +
                                    cn)
        self.security.addPermission(name="View", klass=cn,
                                    description="User is allowed to access " +
                                    cn)

    def getclasses(self):
        """Return a list of the names of all existing classes."""
        return sorted(self.classes.keys())

    def getclass(self, classname):
        """Get the Class object representing a particular class.

        If 'classname' is not a valid class name, a KeyError is raised.
        """
        try:
            return self.classes[classname]
        except KeyError:
            raise KeyError('There is no class called "%s"' % classname)

    #
    # Class DBs
    #
    def clear(self):
        self.items = {}

    def getclassdb(self, classname, mode='r'):
        """ grab a connection to the class db that will be used for
            multiple actions
        """
        return self.items[classname]

    def getCachedJournalDB(self, classname):
        return self.journals.setdefault(classname, {})

    #
    # Node IDs
    #
    def newid(self, classname):
        self.ids[classname] += 1
        return str(self.ids[classname])

    def setid(self, classname, nodeid):
        self.ids[classname] = int(nodeid)

    #
    # Journal
    #
    def doSaveJournal(self, classname, nodeid, action, params, creator,
                      creation):
        if creator is None:
            creator = self.getuid()
        if creation is None:
            creation = date.Date()
        self.journals.setdefault(classname, {}).setdefault(
            nodeid, []).append((nodeid, creation, creator, action, params))

    def doSetJournal(self, classname, nodeid, journal):
        self.journals.setdefault(classname, {})[nodeid] = journal

    def getjournal(self, classname, nodeid):
        # our journal result
        res = []

        # add any journal entries for transactions not committed to the
        # database
        for method, args in self.transactions:
            if method != self.doSaveJournal:
                continue
            (cache_classname, cache_nodeid, cache_action, cache_params,
                cache_creator, cache_creation) = args
            if cache_classname == classname and cache_nodeid == nodeid:
                if not cache_creator:
                    cache_creator = self.getuid()
                if not cache_creation:
                    cache_creation = date.Date()
                res.append((cache_nodeid, cache_creation, cache_creator,
                            cache_action, cache_params))
        try:
            res += self.journals.get(classname, {})[nodeid]
        except KeyError:
            if res: return res                                     # noqa: E701
            raise IndexError(nodeid)
        return res

    def pack(self, pack_before):
        """ Delete all journal entries except "create" before 'pack_before'.
        """
        pack_before = pack_before.serialise()
        for classname in self.journals:
            db = self.journals[classname]
            for key in db:
                # get the journal for this db entry
                kept_journals = []
                for entry in db[key]:
                    # unpack the entry
                    (_nodeid, date_stamp, self.journaltag, action,
                     _params) = entry
                    date_stamp = date_stamp.serialise()
                    # if the entry is after the pack date, _or_ the initial
                    # create entry, then it stays
                    if date_stamp > pack_before or action == 'create':
                        kept_journals.append(entry)
                db[key] = kept_journals


class Class(back_anydbm.Class):
    pass


class FileClass(back_anydbm.FileClass):
    def __init__(self, db, classname, **properties):
        if 'content' not in properties:
            properties['content'] = hyperdb.String(indexme='yes')
        if 'type' not in properties:
            properties['type'] = hyperdb.String()
        back_anydbm.Class.__init__(self, db, classname, **properties)

    def export_files(self, dirname, nodeid):
        dest = self.exportFilename(dirname, nodeid)
        ensureParentsExist(dest)
        with open(dest, 'wb') as f:
            f.write(self.db.files[self.classname, nodeid, None])

    def import_files(self, dirname, nodeid):
        source = self.exportFilename(dirname, nodeid)
        with open(source, 'rb') as f:
            self.db.files[self.classname, nodeid, None] = f.read()
        mime_type = None
        props = self.getprops()
        if 'type' in props:
            mime_type = self.get(nodeid, 'type')
        if not mime_type:
            mime_type = self.default_mime_type
        if props['content'].indexme:
            self.db.indexer.add_text((self.classname, nodeid, 'content'),
                                     self.get(nodeid, 'content'), mime_type)


# deviation from spec - was called ItemClass
class IssueClass(Class, roundupdb.IssueClass):
    # Overridden methods:
    def __init__(self, db, classname, **properties):
        """The newly-created class automatically includes the "messages",
        "files", "nosy", and "superseder" properties.  If the 'properties'
        dictionary attempts to specify any of these properties or a
        "creation" or "activity" property, a ValueError is raised.
        """
        if 'title' not in properties:
            properties['title'] = hyperdb.String(indexme='yes')
        if 'messages' not in properties:
            properties['messages'] = hyperdb.Multilink("msg")
        if 'files' not in properties:
            properties['files'] = hyperdb.Multilink("file")
        if 'nosy' not in properties:
            # note: journalling is turned off as it really just wastes
            # space. this behaviour may be overridden in an instance
            properties['nosy'] = hyperdb.Multilink("user", do_journal="no")
        if 'superseder' not in properties:
            properties['superseder'] = hyperdb.Multilink(classname)
        Class.__init__(self, db, classname, **properties)

# Methods to check for existence and nuke the db
# We don't support multiple named databases


def db_exists(name):
    return bool(Database.memdb)


def db_nuke(name):
    Database.memdb = {}

# vim: set et sts=4 sw=4 :
