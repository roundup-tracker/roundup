import re

import psycopg

from roundup import hyperdb
from roundup.backends import back_postgresql, tsearch2_setup, indexer_rdbms
from roundup.backends.back_postgresql import db_create, db_nuke, db_command
from roundup.backends.back_postgresql import pg_command, db_exists, Class, IssueClass, FileClass

# XXX: Should probably be on the Class class.
def _indexedProps(spec):
    """Get a list of properties to be indexed on 'spec'."""
    return [prop for prop, propclass in spec.getprops().items()
            if isinstance(propclass, hyperdb.String) and propclass.indexme]

def _getQueryDict(spec):
    """Get a convenience dictionary for creating tsearch2 indexes."""
    query_dict = {'classname': spec.classname,
                  'indexedColumns': ['_' + prop for prop in _indexedProps(spec)]}
    query_dict['tablename'] = "_%(classname)s" % query_dict
    query_dict['triggername'] = "%(tablename)s_tsvectorupdate" % query_dict
    return query_dict

def _isLink(propclass):
    return (isinstance(propclass, hyperdb.Link) or
            isinstance(propclass, hyperdb.Multilink))

class Database(back_postgresql.Database):
    def __init__(self, config, journaltag=None):
        back_postgresql.Database.__init__(self, config, journaltag)
        self.indexer = Indexer(self)
    
    def create_version_2_tables(self):
        back_postgresql.Database.create_version_2_tables(self)
        tsearch2_setup.setup(self.cursor)    

    def create_class_table_indexes(self, spec):
        back_postgresql.Database.create_class_table_indexes(self, spec)
        self.cursor.execute("""CREATE INDEX _%(classname)s_idxFTI_idx
                               ON %(tablename)s USING gist(idxFTI);""" %
                            _getQueryDict(spec))

        self.create_tsearch2_trigger(spec)

    def create_tsearch2_trigger(self, spec):
        d = _getQueryDict(spec)
        if d['indexedColumns']:
            
            d['joined'] = " || ' ' ||".join(d['indexedColumns'])
            query = """UPDATE %(tablename)s
                       SET idxFTI = to_tsvector('default', %(joined)s)""" % d
            self.cursor.execute(query)

            d['joined'] = ", ".join(d['indexedColumns']) 
            query = """CREATE TRIGGER %(triggername)s
                       BEFORE UPDATE OR INSERT ON %(tablename)s
                       FOR EACH ROW EXECUTE PROCEDURE
                       tsearch2(idxFTI, %(joined)s);""" % d
            self.cursor.execute(query)

    def drop_tsearch2_trigger(self, spec):
        # Check whether the trigger exists before trying to drop it.
        query_dict = _getQueryDict(spec)
        self.sql("""SELECT tgname FROM pg_catalog.pg_trigger
                    WHERE tgname = '%(triggername)s'""" % query_dict)
        if self.cursor.fetchall():
            self.sql("""DROP TRIGGER %(triggername)s ON %(tablename)s""" %
                     query_dict)

    def update_class(self, spec, old_spec, force=0):
        result = back_postgresql.Database.update_class(self, spec, old_spec, force)

        # Drop trigger...
        self.drop_tsearch2_trigger(spec)

        # and recreate if necessary.
        self.create_tsearch2_trigger(spec)

        return result

    def determine_all_columns(self, spec):
        cols, mls = back_postgresql.Database.determine_all_columns(self, spec)
        cols.append(('idxFTI', 'tsvector'))
        return cols, mls
        
class Indexer:
    def __init__(self, db):
        self.db = db

    def force_reindex(self):
        pass
        
    def should_reindex(self):
        pass

    def save_index(self):
        pass

    def add_text(self, identifier, text, mime_type=None):
        pass

    def close(self):
        pass
    
    def search(self, search_terms, klass, ignore={},
               dre=re.compile(r'([^\d]+)(\d+)')):
        '''Display search results looking for [search, terms] associated
        with the hyperdb Class "klass". Ignore hits on {class: property}.

        "dre" is a helper, not an argument.
        '''
        # do the index lookup
        hits = self.find(search_terms, klass)
        if not hits:
            return {}

        designator_propname = {}
        for nm, propclass in klass.getprops().items():
            if (isinstance(propclass, hyperdb.Link)
                or isinstance(propclass, hyperdb.Multilink)):
                designator_propname[propclass.classname] = nm

        # build a dictionary of nodes and their associated messages
        # and files
        nodeids = {}      # this is the answer
        propspec = {}     # used to do the klass.find
        for propname in designator_propname.values():
            propspec[propname] = {}   # used as a set (value doesn't matter)

        for classname, nodeid in hits:
            # if it's a property on klass, it's easy
            if classname == klass.classname:
                if not nodeids.has_key(nodeid):
                    nodeids[nodeid] = {}
                continue

            # make sure the class is a linked one, otherwise ignore
            if not designator_propname.has_key(classname):
                continue

            # it's a linked class - set up to do the klass.find
            linkprop = designator_propname[classname]   # eg, msg -> messages
            propspec[linkprop][nodeid] = 1

        # retain only the meaningful entries
        for propname, idset in propspec.items():
            if not idset:
                del propspec[propname]
        
        # klass.find tells me the klass nodeids the linked nodes relate to
        for resid in klass.find(**propspec):
            resid = str(resid)
            if not nodeids.has_key(id):
                nodeids[resid] = {}
            node_dict = nodeids[resid]
            # now figure out where it came from
            for linkprop in propspec.keys():
                for nodeid in klass.get(resid, linkprop):
                    if propspec[linkprop].has_key(nodeid):
                        # OK, this node[propname] has a winner
                        if not node_dict.has_key(linkprop):
                            node_dict[linkprop] = [nodeid]
                        else:
                            node_dict[linkprop].append(nodeid)
        return nodeids
    
    def find(self, search_terms, klass):
        if not search_terms:
            return None

        nodeids = self.tsearchQuery(klass.classname, search_terms)
        designator_propname = {}

        for nm, propclass in klass.getprops().items():
            if _isLink(propclass):
                nodeids.extend(self.tsearchQuery(propclass.classname, search_terms))

        return nodeids

    def tsearchQuery(self, classname, search_terms):
        query = """SELECT id FROM _%(classname)s
                   WHERE idxFTI @@ to_tsquery('default', '%(terms)s')"""                    
        
        query = query % {'classname': classname,
                         'terms': ' & '.join(search_terms)}
        self.db.cursor.execute(query)
        klass = self.db.getclass(classname)
        nodeids = [str(row[0]) for row in self.db.cursor.fetchall()]

        # filter out files without text/plain mime type
        # XXX: files without text/plain shouldn't be indexed at all, we
        # should take care of this in the trigger
        if 'type' in klass.getprops():
            nodeids = [nodeid for nodeid in nodeids
                       if klass.get(nodeid, 'type') == 'text/plain']
            
        return [(classname, nodeid) for nodeid in nodeids]

# XXX: we can't reuse hyperdb.FileClass for importing/exporting, so file
# contents will end up in CSV exports for now. Not sure whether this is
# truly a problem. If it is, we should write an importer/exporter that
# converts from the database to the filesystem and vice versa
class FileClass(Class):
    def __init__(self, db, classname, **properties):
        '''The newly-created class automatically includes the "content" property.,
        '''
        properties['content'] = hyperdb.String(indexme='yes')
        Class.__init__(self, db, classname, **properties)

    default_mime_type = 'text/plain'
    def create(self, **propvalues):
        # figure the mime type
        if not propvalues.get('type'):
            propvalues['type'] = self.default_mime_type
        return Class.create(self, **propvalues)
