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
# $Id: test_mysql.py,v 1.4 2003-11-05 21:54:57 jlgijsbers Exp $ 

import unittest, os, shutil, time, imp

from roundup.hyperdb import DatabaseError
from roundup import init, backends

from db_test_base import DBTest, ROTest, config, SchemaTest, nodbconfig, \
    ClassicInitTest

class mysqlOpener:
    if hasattr(backends, 'mysql'):
        from roundup.backends import mysql as module

    def tearDown(self):
        self.db.close()
        self.module.db_nuke(config)

class mysqlDBTest(mysqlOpener, DBTest):
    pass

class mysqlROTest(mysqlOpener, ROTest):
    pass

class mysqlSchemaTest(mysqlOpener, SchemaTest):
    pass

class mysqlClassicInitTest(ClassicInitTest):
    backend = 'mysql'
    extra_config = '''
MYSQL_DBHOST = 'localhost'
MYSQL_DBUSER = 'rounduptest'
MYSQL_DBPASSWORD = 'rounduptest'
MYSQL_DBNAME = 'rounduptest'
MYSQL_DATABASE = (MYSQL_DBHOST, MYSQL_DBUSER, MYSQL_DBPASSWORD, MYSQL_DBNAME)
'''
    if hasattr(backends, 'mysql'):
        from roundup.backends import mysql as module
    def tearDown(self):
        ClassicInitTest.tearDown(self)
        self.module.db_nuke(config)

def test_suite():
    suite = unittest.TestSuite()
    if not hasattr(backends, 'mysql'):
        return suite

    from roundup.backends import mysql
    try:
        # Check if we can run mysql tests
        import MySQLdb
        db = mysql.Database(nodbconfig, 'admin')
        db.conn.select_db(config.MYSQL_DBNAME)
        db.sql("SHOW TABLES");
        tables = db.sql_fetchall()
        if 0: #tables:
            # Database should be empty. We don't dare to delete any data
            raise DatabaseError, "Database %s contains tables"%\
                config.MYSQL_DBNAME
        db.sql("DROP DATABASE %s" % config.MYSQL_DBNAME)
        db.sql("CREATE DATABASE %s" % config.MYSQL_DBNAME)
        db.close()
    except (MySQLdb.ProgrammingError, DatabaseError), msg:
        print "Skipping mysql tests (%s)"%msg
    else:
        print 'Including mysql tests'
        suite.addTest(unittest.makeSuite(mysqlDBTest))
        suite.addTest(unittest.makeSuite(mysqlROTest))
        suite.addTest(unittest.makeSuite(mysqlSchemaTest))
        suite.addTest(unittest.makeSuite(mysqlClassicInitTest))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

