from roundup import hyperdb

STOPWORDS = [
    "A", "AND", "ARE", "AS", "AT", "BE", "BUT", "BY",
    "FOR", "IF", "IN", "INTO", "IS", "IT",
    "NO", "NOT", "OF", "ON", "OR", "SUCH",
    "THAT", "THE", "THEIR", "THEN", "THERE", "THESE",
    "THEY", "THIS", "TO", "WAS", "WILL", "WITH"
]


def _isLink(propclass):
    return (isinstance(propclass, hyperdb.Link) or
            isinstance(propclass, hyperdb.Multilink))


class Indexer:
    def __init__(self, db):
        self.stopwords = set(STOPWORDS)
        for word in db.config[('main', 'indexer_stopwords')]:
            self.stopwords.add(word)
        # Do not index anything longer than maxlength characters since
        # that'll be gibberish (encoded text or somesuch) or shorter
        # than 2 characters
        self.minlength = 2
        self.maxlength = 50
        self.language = db.config[('main', 'indexer_language')]
        # Some indexers have a query language. If that is the case,
        # we don't parse the user supplied query into a wordlist.
        self.query_language = False

    def is_stopword(self, word):
        return word in self.stopwords

    def getHits(self, search_terms, klass):
        return self.find(search_terms)

    def save_index(self):
        pass

    def search(self, search_terms, klass, ignore=None):
        """Display search results looking for [search, terms] associated
        with the hyperdb Class "klass". Ignore hits on {class: property}.
        """
        # do the index lookup
        hits = self.getHits(search_terms, klass)
        if not hits:
            return {}

        designator_propname = {}
        for nm, propclass in klass.getprops().items():
            if _isLink(propclass):
                designator_propname.setdefault(propclass.classname,
                                               []).append(nm)

        # build a dictionary of nodes and their associated messages
        # and files
        nodeids = {}      # this is the answer
        propspec = {}     # used to do the klass.find
        for pn in designator_propname.values():
            for propname in pn:
                propspec[propname] = {}  # used as a set (value doesn't matter)

        if ignore is None:
            ignore = {}
        # don't unpack hits entries as sqlite3's Row can't be unpacked :(
        for entry in hits:
            # skip this result if we don't care about this class/property
            classname = entry[0]
            property = entry[2]
            if (classname, property) in ignore:
                continue

            # if it's a property on klass, it's easy
            # (make sure the nodeid is str() not unicode() as returned by some
            # backends as that can cause problems down the track)
            nodeid = str(entry[1])
            if classname == klass.classname:
                if nodeid not in nodeids:
                    nodeids[nodeid] = {}
                continue

            # make sure the class is a linked one, otherwise ignore
            if classname not in designator_propname:
                continue

            # it's a linked class - set up to do the klass.find
            for linkprop in designator_propname[classname]:
                propspec[linkprop][nodeid] = 1

        # retain only the meaningful entries
        for propname, idset in list(propspec.items()):
            if not idset:
                del propspec[propname]

        # klass.find tells me the klass nodeids the linked nodes relate to
        propdefs = klass.getprops()
        for resid in klass.find(**propspec):
            resid = str(resid)
            if resid in nodeids:
                continue  # we ignore duplicate resids
            nodeids[resid] = {}
            node_dict = nodeids[resid]
            # now figure out where it came from
            for linkprop in propspec:
                v = klass.get(resid, linkprop)
                # the link might be a Link so deal with a single result or None
                if isinstance(propdefs[linkprop], hyperdb.Link):
                    if v is None:
                        continue
                    v = [v]
                for nodeid in v:
                    if nodeid in propspec[linkprop]:
                        # OK, this node[propname] has a winner
                        if linkprop not in node_dict:
                            node_dict[linkprop] = [nodeid]
                        else:
                            node_dict[linkprop].append(nodeid)
        return nodeids


def get_indexer(config, db):
    indexer_name = getattr(config, "INDEXER", "")
    if not indexer_name:
        # Try everything
        try:
            from .indexer_xapian import Indexer
            return Indexer(db)
        except ImportError:
            pass

        try:
            from .indexer_whoosh import Indexer
            return Indexer(db)
        except ImportError:
            pass

        indexer_name = "native"  # fallback to native full text search

    if indexer_name == "xapian":
        from .indexer_xapian import Indexer
        return Indexer(db)

    if indexer_name == "whoosh":
        from .indexer_whoosh import Indexer
        return Indexer(db)

    if indexer_name == "native-fts":
        if db.dbtype not in ("sqlite", "postgres"):
            raise AssertionError("Indexer native-fts is configured, but only "
                "sqlite and postgres support it. Database is: %r" % db.dbtype)

        if db.dbtype == "sqlite":
            from roundup.backends.indexer_sqlite_fts import Indexer
            return Indexer(db)

        if db.dbtype == "postgres":
            from roundup.backends.indexer_postgresql_fts import Indexer
            return Indexer(db)

    if indexer_name == "native":
        # load proper native indexing based on database type
        if db.dbtype == "anydbm":
            from roundup.backends.indexer_dbm import Indexer
            return Indexer(db)

        if db.dbtype in ("sqlite", "postgres", "mysql"):
            from roundup.backends.indexer_rdbms import Indexer
            return Indexer(db)

    raise AssertionError("Invalid indexer: %r" % (indexer_name))
