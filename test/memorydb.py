'''Implement an in-memory hyperdb for testing purposes.
'''

import shutil

from roundup import hyperdb
from roundup import roundupdb
from roundup import security
from roundup import password
from roundup import configuration
from roundup.backends import back_anydbm
from roundup.backends import indexer_dbm
from roundup.backends import sessions_dbm
from roundup.backends import indexer_common
from roundup.hyperdb import *
from roundup.support import ensureParentsExist

def new_config(debug=False):
    config = configuration.CoreConfig()
    config.DATABASE = "db"
    #config.logging = MockNull()
    # these TRACKER_WEB and MAIL_DOMAIN values are used in mailgw tests
    if debug:
        config.LOGGING_LEVEL = "DEBUG"
    config.MAIL_DOMAIN = "your.tracker.email.domain.example"
    config.TRACKER_WEB = "http://tracker.example/cgi-bin/roundup.cgi/bugs/"
    return config

def create(journaltag, create=True, debug=False):
    db = Database(new_config(debug), journaltag)

    # load standard schema
    schema = os.path.join(os.path.dirname(__file__),
        '../share/roundup/templates/classic/schema.py')
    vars = dict(globals())
    vars['db'] = db
    execfile(schema, vars)
    initial_data = os.path.join(os.path.dirname(__file__),
        '../share/roundup/templates/classic/initial_data.py')
    vars = dict(db=db, admin_email='admin@test.com',
        adminpw=password.Password('sekrit'))
    execfile(initial_data, vars)

    # load standard detectors
    thisdir = os.path.dirname(__file__)
    dirname = os.path.join(thisdir,
        '../share/roundup/templates/classic/detectors')
    for fn in os.listdir(dirname):
        if not fn.endswith('.py'): continue
        vars = {}
        execfile(os.path.join(dirname, fn), vars)
        vars['init'](db)

    vars = {}
    execfile(os.path.join(thisdir, "tx_Source_detector.py"), vars)
    vars['init'](db)

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
            password=password.Password('sekrit'), address='fred@example.com')

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
    def close(self):
        pass

class BasicDatabase(dict):
    ''' Provide a nice encapsulation of an anydbm store.

        Keys are id strings, values are automatically marshalled data.
    '''
    def __getitem__(self, key):
        if key not in self:
            d = self[key] = {}
            return d
        return super(BasicDatabase, self).__getitem__(key)
    def exists(self, infoid):
        return infoid in self
    def get(self, infoid, value, default=None):
        return self[infoid].get(value, default)
    def getall(self, infoid):
        if infoid not in self:
            raise KeyError(infoid)
        return self[infoid]
    def set(self, infoid, **newvalues):
        self[infoid].update(newvalues)
    def list(self):
        return self.keys()
    def destroy(self, infoid):
        del self[infoid]
    def commit(self):
        pass
    def close(self):
        pass
    def updateTimestamp(self, sessid):
        pass
    def clean(self):
        pass

class Sessions(BasicDatabase, sessions_dbm.Sessions):
    name = 'sessions'

class OneTimeKeys(BasicDatabase, sessions_dbm.Sessions):
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
        self.files = {'_TOP':(0,None)}
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
    def __init__(self, config, journaltag=None):
        self.config, self.journaltag = config, journaltag
        self.classes = {}
        self.items = {}
        self.ids = {}
        self.journals = {}
        self.files = {}
        self.tx_files = {}
        self.security = security.Security(self)
        self.stats = {'cache_hits': 0, 'cache_misses': 0, 'get_items': 0,
            'filtering': 0}
        self.sessions = Sessions()
        self.otks = OneTimeKeys()
        self.indexer = Indexer(self)

        # anydbm bits
        self.cache = {}         # cache of nodes loaded or created
        self.dirtynodes = {}    # keep track of the dirty nodes by class
        self.newnodes = {}      # keep track of the new nodes by class
        self.destroyednodes = {}# keep track of the destroyed nodes by class
        self.transactions = []
        self.tx_Source = None

    def filename(self, classname, nodeid, property=None, create=0):
        shutil.copyfile(__file__, __file__+'.dummy')
        return __file__+'.dummy'

    def filesize(self, classname, nodeid, property=None, create=0):
        return len(self.getfile(classname, nodeid, property))

    def post_init(self):
        pass

    def refresh_database(self):
        pass

    def getSessionManager(self):
        return self.sessions

    def getOTKManager(self):
        return self.otks

    def reindex(self, classname=None, show_progress=False):
        pass

    def __repr__(self):
        return '<memorydb instance at %x>'%id(self)

    def storefile(self, classname, nodeid, property, content):
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

    #
    # Classes
    #
    def __getattr__(self, classname):
        """A convenient way of calling self.getclass(classname)."""
        if self.classes.has_key(classname):
            return self.classes[classname]
        raise AttributeError, classname

    def addclass(self, cl):
        cn = cl.classname
        if self.classes.has_key(cn):
            raise ValueError, cn
        self.classes[cn] = cl
        if cn not in self.items:
            self.items[cn] = cldb()
            self.ids[cn] = 0

        # add default Edit and View permissions
        self.security.addPermission(name="Create", klass=cn,
            description="User is allowed to create "+cn)
        self.security.addPermission(name="Edit", klass=cn,
            description="User is allowed to edit "+cn)
        self.security.addPermission(name="View", klass=cn,
            description="User is allowed to access "+cn)

    def getclasses(self):
        """Return a list of the names of all existing classes."""
        l = self.classes.keys()
        l.sort()
        return l

    def getclass(self, classname):
        """Get the Class object representing a particular class.

        If 'classname' is not a valid class name, a KeyError is raised.
        """
        try:
            return self.classes[classname]
        except KeyError:
            raise KeyError, 'There is no class called "%s"'%classname

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
    def setid(self, classname, id):
        self.ids[classname] = int(id)

    #
    # Journal
    #
    def doSaveJournal(self, classname, nodeid, action, params, creator,
            creation):
        if creator is None:
            creator = self.getuid()
        if creation is None:
            creation = date.Date()
        self.journals.setdefault(classname, {}).setdefault(nodeid,
            []).append((nodeid, creation, creator, action, params))

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
            if res: return res
            raise IndexError, nodeid
        return res

    def pack(self, pack_before):
        """ Delete all journal entries except "create" before 'pack_before'.
        """
        pack_before = pack_before.serialise()
        for classname in self.journals:
            db = self.journals[classname]
            for key in db:
                # get the journal for this db entry
                l = []
                last_set_entry = None
                for entry in db[key]:
                    # unpack the entry
                    (nodeid, date_stamp, self.journaltag, action,
                        params) = entry
                    date_stamp = date_stamp.serialise()
                    # if the entry is after the pack date, _or_ the initial
                    # create entry, then it stays
                    if date_stamp > pack_before or action == 'create':
                        l.append(entry)
                db[key] = l

class Class(back_anydbm.Class):
    pass

class FileClass(back_anydbm.FileClass):
    def __init__(self, db, classname, **properties):
        if not properties.has_key('content'):
            properties['content'] = hyperdb.String(indexme='yes')
        if not properties.has_key('type'):
            properties['type'] = hyperdb.String()
        back_anydbm.Class.__init__(self, db, classname, **properties)

    def export_files(self, dirname, nodeid):
        dest = self.exportFilename(dirname, nodeid)
        ensureParentsExist(dest)
        f = open(dest, 'wb')
        f.write(self.db.files[self.classname, nodeid, None])
        f.close()

    def import_files(self, dirname, nodeid):
        source = self.exportFilename(dirname, nodeid)
        f = open(source, 'rb')
        self.db.files[self.classname, nodeid, None] = f.read()
        f.close()
        mime_type = None
        props = self.getprops()
        if props.has_key('type'):
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
        if not properties.has_key('title'):
            properties['title'] = hyperdb.String(indexme='yes')
        if not properties.has_key('messages'):
            properties['messages'] = hyperdb.Multilink("msg")
        if not properties.has_key('files'):
            properties['files'] = hyperdb.Multilink("file")
        if not properties.has_key('nosy'):
            # note: journalling is turned off as it really just wastes
            # space. this behaviour may be overridden in an instance
            properties['nosy'] = hyperdb.Multilink("user", do_journal="no")
        if not properties.has_key('superseder'):
            properties['superseder'] = hyperdb.Multilink(classname)
        Class.__init__(self, db, classname, **properties)

# vim: set et sts=4 sw=4 :
