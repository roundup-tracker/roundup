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
# $Id: test_mysql.py,v 1.1 2003-10-25 22:53:26 richard Exp $ 

import unittest, os, shutil, time, imp

from roundup.hyperdb import DatabaseError
from roundup import init

from db_test_base import DBTest, ROTest, config, SchemaTest, nodbconfig, \
    ClassicInitTest

class mysqlOpener:
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

    def testCreation(self):
        ae = self.assertEqual

        # create the instance
        init.install(self.dirname, 'templates/classic')
        init.write_select_db(self.dirname, self.backend)
        f = open(os.path.join(self.dirname, 'config.py'), 'a')
        try:
            f.write('''
MYSQL_DBHOST = 'localhost'
MYSQL_DBUSER = 'rounduptest'
MYSQL_DBPASSWORD = 'rounduptest'
MYSQL_DBNAME = 'rounduptest'
MYSQL_DATABASE = (MYSQL_DBHOST, MYSQL_DBUSER, MYSQL_DBPASSWORD, MYSQL_DBNAME)
            ''')
        finally:
            f.close()
        init.initialise(self.dirname, 'sekrit')

        # check we can load the package
        instance = imp.load_package(self.dirname, self.dirname)

        # and open the database
        db = instance.open()

        # check the basics of the schema and initial data set
        l = db.priority.list()
        ae(l, ['1', '2', '3', '4', '5'])
        l = db.status.list()
        ae(l, ['1', '2', '3', '4', '5', '6', '7', '8'])
        l = db.keyword.list()
        ae(l, [])
        l = db.user.list()
        ae(l, ['1', '2'])
        l = db.msg.list()
        ae(l, [])
        l = db.file.list()
        ae(l, [])
        l = db.issue.list()
        ae(l, [])

    from roundup.backends import mysql as module
    def tearDown(self):
        ClassicInitTest.tearDown(self)
        self.module.db_nuke(config)

def test_suite():
    suite = unittest.TestSuite()

    from roundup import backends
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

