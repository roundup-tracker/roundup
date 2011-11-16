# Note: this backend is EXPERIMENTAL. Do not use if you value your data.
import re

import psycopg

from roundup import hyperdb
from roundup.support import ensureParentsExist
from roundup.backends import back_postgresql, tsearch2_setup, indexer_rdbms
from roundup.backends.back_postgresql import db_create, db_nuke, db_command
from roundup.backends.back_postgresql import pg_command, db_exists, Class, IssueClass, FileClass
from roundup.backends.indexer_common import _isLink, Indexer

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
        
class Indexer(Indexer):
    def __init__(self, db):
        self.db = db

    # This indexer never needs to reindex.
    def should_reindex(self):
        return 0

    def getHits(self, search_terms, klass):
        return self.find(search_terms, klass)    
    
    def find(self, search_terms, klass):
        if not search_terms:
            return None

        hits = self.tsearchQuery(klass.classname, search_terms)
        designator_propname = {}

        for nm, propclass in klass.getprops().items():
            if _isLink(propclass):
                hits.extend(self.tsearchQuery(propclass.classname, search_terms))

        return hits

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
        if klass.getprops().has_key('type'):
            nodeids = [nodeid for nodeid in nodeids
                       if klass.get(nodeid, 'type') == 'text/plain']

        # XXX: We haven't implemented property-level search, so I'm just faking
        # it here with a property named 'XXX'. We still need to fix the other
        # backends and indexer_common.Indexer.search to only want to unpack two
        # values.
        return [(classname, nodeid, 'XXX') for nodeid in nodeids]

    # These only exist to satisfy the interface that's expected from indexers.
    def force_reindex(self):
        pass

    def add_text(self, identifier, text, mime_type=None):
        pass

    def close(self):
        pass

class FileClass(hyperdb.FileClass, Class):
    '''This class defines a large chunk of data. To support this, it has a
       mandatory String property "content" which is typically saved off
       externally to the hyperdb.

       However, this implementation just stores it in the hyperdb.
    '''
    def __init__(self, db, classname, **properties):
        '''The newly-created class automatically includes the "content" property.,
        '''
        properties['content'] = hyperdb.String(indexme='yes')
        Class.__init__(self, db, classname, **properties)

    default_mime_type = 'text/plain'
    def create(self, **propvalues):
        # figure the mime type
        if self.getprops().has_key('type') and not propvalues.get('type'):
            propvalues['type'] = self.default_mime_type
        return Class.create(self, **propvalues)

    def export_files(self, dirname, nodeid):
        dest = self.exportFilename(dirname, nodeid)
        ensureParentsExist(dest)
        fp = open(dest, "w")
        fp.write(self.get(nodeid, "content", default=''))
        fp.close()

    def import_files(self, dirname, nodeid):
        source = self.exportFilename(dirname, nodeid)

        fp = open(source, "r")
        # Use Database.setnode instead of self.set or self.set_inner here, as
        # Database.setnode doesn't update the "activity" or "actor" properties.
        self.db.setnode(self.classname, nodeid, values={'content': fp.read()})
        fp.close()
