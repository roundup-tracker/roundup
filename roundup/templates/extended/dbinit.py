# $Id: dbinit.py,v 1.7 2001-07-29 07:01:39 richard Exp $

import os

import instance_config
from roundup import roundupdb
import select_db
from roundup.roundupdb import Class, FileClass

class Database(roundupdb.Database, select_db.Database):
    ''' Creates a hybrid database from: 
         . the selected database back-end from select_db
         . the roundup extensions from roundupdb 
    ''' 
    pass 

class IssueClass(roundupdb.IssueClass):
    ''' issues need the email information
    '''
    ISSUE_TRACKER_EMAIL = instance_config.ISSUE_TRACKER_EMAIL
    ADMIN_EMAIL = instance_config.ADMIN_EMAIL
    MAILHOST = instance_config.MAILHOST

 
def open(name=None):
    ''' as from the roundupdb method openDB 
 
    ''' 
    from roundup.hyperdb import String, Date, Link, Multilink

    # open the database
    db = Database(instance_config.DATABASE, name)

    # Now initialise the schema. Must do this each time.
    pri = Class(db, "priority", 
                    name=String(), order=String())
    pri.setkey("name")

    stat = Class(db, "status", 
                    name=String(), order=String())
    stat.setkey("name")

    keywords = Class(db, "keyword", 
                    name=String())

    user = Class(db, "user", 
                    username=String(),   password=String(),
                    address=String(),    realname=String(), 
                    phone=String(),      organisation=String())
    user.setkey("username")

    msg = FileClass(db, "msg", 
                    author=Link("user"), recipients=Multilink("user"), 
                    date=Date(),         summary=String(), 
                    files=Multilink("file"))

    file = FileClass(db, "file", 
                    name=String(),       type=String())

    # bugs and support calls etc
    rate = Class(db, "rate", 
                    name=String(),       order=String())
    rate.setkey("name")

    source = Class(db, "source", 
                    name=String(),       order=String())
    source.setkey("name")

    platform = Class(db, "platform", 
                    name=String(),       order=String())
    platform.setkey("name")

    product = Class(db, "product", 
                    name=String(),       order=String())
    product.setkey("name")

    timelog = Class(db, "timelog", 
                    date=Date(),         time=String(),
                    performedby=Link("user"), description=String())

    issue = IssueClass(db, "issue", 
                    assignedto=Link("user"), priority=Link("priority"), 
                    status=Link("status"),   rate=Link("rate"), 
                    source=Link("source"),   product=Link("product"), 
                    platform=Multilink("platform"), version=String(),
                    timelog=Multilink("timelog"), customername=String())
    issue.setkey('title')

    import detectors
    detectors.init(db)

    return db
 
def init(adminpw): 
    ''' as from the roundupdb method initDB 
 
    Open the new database, and set up a bunch of attributes.

    ''' 
    dbdir = os.path.join(instance_config.DATABASE, 'files')
    if not os.path.isdir(dbdir):
        os.makedirs(dbdir)

    db = open("admin")
    db.clear()

    pri = db.getclass('priority')
    pri.create(name="fatal-bug", order="1")
    pri.create(name="bug", order="2")
    pri.create(name="usability", order="3")
    pri.create(name="feature", order="4")
    pri.create(name="support", order="5")

    stat = db.getclass('status')
    stat.create(name="unread", order="1")
    stat.create(name="deferred", order="2")
    stat.create(name="chatting", order="3")
    stat.create(name="need-eg", order="4")
    stat.create(name="in-progress", order="5")
    stat.create(name="testing", order="6")
    stat.create(name="done-cbb", order="7")
    stat.create(name="resolved", order="8")

    rate = db.getclass("rate")
    rate.create(name='basic', order="1")
    rate.create(name='premium', order="2")
    rate.create(name='internal', order="3")

    source = db.getclass("source")
    source.create(name='phone', order="1")
    source.create(name='e-mail', order="2")
    source.create(name='internal', order="3")
    source.create(name='internal-qa', order="4")

    platform = db.getclass("platform")
    platform.create(name='linux', order="1")
    platform.create(name='windows', order="2")
    platform.create(name='mac', order="3")

    product = db.getclass("product")
    product.create(name='Bizar Shop', order="1")
    product.create(name='Bizar Shop Developer', order="2")
    product.create(name='Bizar Shop Manual', order="3")
    product.create(name='Bizar Shop Developer Manual', order="4")

    user = db.getclass('user')
    user.create(username="admin", password=adminpw, 
                                  address=instance_config.ADMIN_EMAIL)

    db.close()

#
# $Log: not supported by cvs2svn $
# Revision 1.6  2001/07/25 01:23:07  richard
# Added the Roundup spec to the new documentation directory.
#
# Revision 1.5  2001/07/23 23:20:35  richard
# forgot to remove the interfaces from the dbinit module ;)
#
# Revision 1.4  2001/07/23 08:45:28  richard
# ok, so now "./roundup-admin init" will ask questions in an attempt to get a
# workable instance_home set up :)
# _and_ anydbm has had its first test :)
#
# Revision 1.3  2001/07/23 07:14:41  richard
# Moved the database backends off into backends.
#
# Revision 1.2  2001/07/23 06:25:50  richard
# relfected the move to roundup/backends
#
# Revision 1.1  2001/07/23 04:33:21  anthonybaxter
# split __init__.py into 2. dbinit and instance_config.
#
# Revision 1.1  2001/07/23 03:50:46  anthonybaxter
# moved templates to proper location
#
# Revision 1.2  2001/07/22 12:09:32  richard
# Final commit of Grande Splite
#
#
# vim: set filetype=python ts=4 sw=4 et si

