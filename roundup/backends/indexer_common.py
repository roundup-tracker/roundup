import re

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
        # Do not index anything longer than 25 characters since that'll be
        # gibberish (encoded text or somesuch) or shorter than 2 characters
        self.minlength = 2
        self.maxlength = 25

    def is_stopword(self, word):
        return word in self.stopwords

    def getHits(self, search_terms, klass):
        return self.find(search_terms)

    def search(self, search_terms, klass, ignore={}):
        """Display search results looking for [search, terms] associated
        with the hyperdb Class "klass". Ignore hits on {class: property}.
        """
        # do the index lookup
        hits = self.getHits(search_terms, klass)
        if not hits:
            return {}

        designator_propname = {}
        for nm, propclass in klass.getprops().iteritems():
            if _isLink(propclass):
                designator_propname.setdefault(propclass.classname,
                    []).append(nm)

        # build a dictionary of nodes and their associated messages
        # and files
        nodeids = {}      # this is the answer
        propspec = {}     # used to do the klass.find
        for l in designator_propname.itervalues():
            for propname in l:
                propspec[propname] = {}  # used as a set (value doesn't matter)

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
                continue # we ignore duplicate resids
            nodeids[resid] = {}
            node_dict = nodeids[resid]
            # now figure out where it came from
            for linkprop in propspec:
                v = klass.get(resid, linkprop)
                # the link might be a Link so deal with a single result or None
                if isinstance(propdefs[linkprop], hyperdb.Link):
                    if v is None: continue
                    v = [v]
                for nodeid in v:
                    if nodeid in propspec[linkprop]:
                        # OK, this node[propname] has a winner
                        if linkprop not in node_dict:
                            node_dict[linkprop] = [nodeid]
                        else:
                            node_dict[linkprop].append(nodeid)
        return nodeids

