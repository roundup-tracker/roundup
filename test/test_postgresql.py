#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
# 
# $Id: test_postgresql.py,v 1.1 2003-10-25 22:53:26 richard Exp $ 

import unittest, os, shutil, time

from roundup.hyperdb import DatabaseError

from db_test_base import DBTest, ROTest, config, SchemaTest, nodbconfig, \
    ClassicInitTest

from roundup import backends

class postgresqlOpener:
    if hasattr(backends, 'metakit'):
        from roundup.backends import postgresql as module

    def tearDown(self):
        self.db.close()
        self.module.Database.nuke(config)

class postgresqlDBTest(postgresqlOpener, DBTest):
    pass

class postgresqlROTest(postgresqlOpener, ROTest):
    pass

class postgresqlSchemaTest(postgresqlOpener, SchemaTest):
    pass

class postgresqlClassicInitTest(ClassicInitTest):
    backend = 'postgresql'

def test_suite():
    suite = unittest.TestSuite()
    if not hasattr(backends, 'postgresql'):
        return suite

    from roundup.backends import postgresql
    try:
        # Check if we can run postgresql tests
        import psycopg
        db = psycopg.Database(nodbconfig, 'admin')
        db.conn.select_db(config.POSTGRESQL_DBNAME)
        db.sql("SHOW TABLES");
        tables = db.sql_fetchall()
        if tables:
            # Database should be empty. We don't dare to delete any data
            raise DatabaseError, "(Database %s contains tables)"%\
                config.POSTGRESQL_DBNAME
        db.sql("DROP DATABASE %s" % config.POSTGRESQL_DBNAME)
        db.sql("CREATE DATABASE %s" % config.POSTGRESQL_DBNAME)
        db.close()
    except (MySQLdb.ProgrammingError, DatabaseError), msg:
        print "Skipping postgresql tests (%s)"%msg
    else:
        print 'Including postgresql tests'
        suite.addTest(unittest.makeSuite(postgresqlDBTest))
        suite.addTest(unittest.makeSuite(postgresqlROTest))
        suite.addTest(unittest.makeSuite(postgresqlSchemaTest))
        suite.addTest(unittest.makeSuite(postgresqlClassicInitTest))
    return suite

