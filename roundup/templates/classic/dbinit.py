#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL THE BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
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
# $Id: dbinit.py,v 1.6 2001-08-07 00:15:51 richard Exp $

import os

import instance_config
from roundup import roundupdb, cgi_client, mailgw 
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
    ISSUE_TRACKER_WEB = instance_config.ISSUE_TRACKER_WEB
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

    keyword = Class(db, "keyword", 
                    name=String())
    keyword.setkey("name")

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

    issue = IssueClass(db, "issue", 
                    assignedto=Link("user"), topic=Multilink("keyword"),
                    priority=Link("priority"), status=Link("status"))
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
    pri.create(name="critical", order="1")
    pri.create(name="urgent", order="2")
    pri.create(name="bug", order="3")
    pri.create(name="feature", order="4")
    pri.create(name="wish", order="5")

    stat = db.getclass('status')
    stat.create(name="unread", order="1")
    stat.create(name="deferred", order="2")
    stat.create(name="chatting", order="3")
    stat.create(name="need-eg", order="4")
    stat.create(name="in-progress", order="5")
    stat.create(name="testing", order="6")
    stat.create(name="done-cbb", order="7")
    stat.create(name="resolved", order="8")

    user = db.getclass('user')
    user.create(username="admin", password=adminpw, 
                                  address=instance_config.ADMIN_EMAIL)

    db.close()

#
# $Log: not supported by cvs2svn $
# Revision 1.5  2001/08/02 06:38:17  richard
# Roundupdb now appends "mailing list" information to its messages which
# include the e-mail address and web interface address. Templates may
# override this in their db classes to include specific information (support
# instructions, etc).
#
# Revision 1.4  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.3  2001/07/24 10:46:22  anthonybaxter
# Added templatebuilder module. two functions - one to pack up the html base,
# one to unpack it. Packed up the two standard templates into htmlbases.
# Modified __init__ to install them.
#
# __init__.py magic was needed for the rather high levels of wierd import magic.
# Reducing level of import magic == (good, future)
#
# Revision 1.2  2001/07/24 01:06:43  richard
# Oops - accidentally duped the keywords class
#
# Revision 1.1  2001/07/23 23:28:43  richard
# Adding the classic template
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

