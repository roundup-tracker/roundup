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
# $Id: dbinit.py,v 1.1.2.1 2003-11-14 02:47:56 richard Exp $

import os

import config
from select_db import Database, Class, FileClass, IssueClass

def open(name=None):
    ''' as from the roundupdb method openDB 
    ''' 
    from roundup.hyperdb import String, Password, Date, Link, Multilink
    from roundup.hyperdb import Interval, Boolean, Number

    # open the database
    db = Database(config, name)

    #
    # Now initialise the schema. Must do this each time the database is
    # opened.
    #

    # Class automatically gets these properties:
    #   creation = Date()
    #   activity = Date()
    #   creator = Link('user')
    pri = Class(db, "priority", 
                    name=String(), order=String())
    pri.setkey("name")

    stat = Class(db, "status", 
                    name=String(), order=String())
    stat.setkey("name")

    keyword = Class(db, "keyword", 
                    name=String())
    keyword.setkey("name")
    
    query = Class(db, "query",
                    klass=String(),     name=String(),
                    url=String())
    query.setkey("name")

    # add any additional database schema configuration here
    
    # Note: roles is a comma-separated string of Role names
    user = Class(db, "user", 
                    username=String(),   password=Password(),
                    address=String(),    realname=String(), 
                    phone=String(),      organisation=String(),
                    alternate_addresses=String(),
                    queries=Multilink('query'), roles=String(),
                    timezone=String())
    user.setkey("username")

    # FileClass automatically gets these properties:
    #   content = String()    [saved to disk in <tracker home>/db/files/]
    #   (it also gets the Class properties creation, activity and creator)
    msg = FileClass(db, "msg", 
                    author=Link("user", do_journal='no'),
                    recipients=Multilink("user", do_journal='no'), 
                    date=Date(),         summary=String(), 
                    files=Multilink("file"),
                    messageid=String(),  inreplyto=String())

    file = FileClass(db, "file", 
                    name=String(),       type=String())

    # IssueClass automatically gets these properties:
    #   title = String()
    #   messages = Multilink("msg")
    #   files = Multilink("file")
    #   nosy = Multilink("user")
    #   superseder = Multilink("issue")
    #   (it also gets the Class properties creation, activity and creator)
    issue = IssueClass(db, "issue", 
                    assignedto=Link("user"), topic=Multilink("keyword"),
                    priority=Link("priority"), status=Link("status"))

    #
    # SECURITY SETTINGS
    #
    # See the configuration and customisation document for information
    # about security setup.
    # Add new Permissions for this schema
    for cl in 'issue', 'file', 'msg', 'user', 'query', 'keyword':
        db.security.addPermission(name="Edit", klass=cl,
            description="User is allowed to edit "+cl)
        db.security.addPermission(name="View", klass=cl,
            description="User is allowed to access "+cl)

    # Assign the access and edit Permissions for issue, file and message
    # to regular users now
    for cl in 'issue', 'file', 'msg', 'query', 'keyword':
        p = db.security.getPermission('View', cl)
        db.security.addPermissionToRole('User', p)
        p = db.security.getPermission('Edit', cl)
        db.security.addPermissionToRole('User', p)

    # and give the regular users access to the web and email interface
    p = db.security.getPermission('Web Access')
    db.security.addPermissionToRole('User', p)
    p = db.security.getPermission('Email Access')
    db.security.addPermissionToRole('User', p)

    # May users view other user information? Comment these lines out
    # if you don't want them to
    p = db.security.getPermission('View', 'user')
    db.security.addPermissionToRole('User', p)

    # Assign the appropriate permissions to the anonymous user's Anonymous
    # Role. Choices here are:
    # - Allow anonymous users to register through the web
    p = db.security.getPermission('Web Registration')
    db.security.addPermissionToRole('Anonymous', p)
    # - Allow anonymous (new) users to register through the email gateway
    p = db.security.getPermission('Email Registration')
    db.security.addPermissionToRole('Anonymous', p)
    # - Allow anonymous users access to the "issue" class of data
    #   Note: this also grants access to related information like files,
    #         messages, statuses etc that are linked to issues
    p = db.security.getPermission('View', 'issue')
    db.security.addPermissionToRole('Anonymous', p)
    # - Allow anonymous users access to edit the "issue" class of data
    #   Note: this also grants access to create related information like
    #         files and messages etc that are linked to issues
    #p = db.security.getPermission('Edit', 'issue')
    #db.security.addPermissionToRole('Anonymous', p)

    # oh, g'wan, let anonymous access the web interface too
    p = db.security.getPermission('Web Access')
    db.security.addPermissionToRole('Anonymous', p)

    import detectors
    detectors.init(db)

    # schema is set up - run any post-initialisation
    db.post_init()
    return db
 
def init(adminpw): 
    ''' as from the roundupdb method initDB 
 
    Open the new database, and add new nodes - used for initialisation. You
    can edit this before running the "roundup-admin initialise" command to
    change the initial database entries.
    ''' 
    dbdir = os.path.join(config.DATABASE, 'files')
    if not os.path.isdir(dbdir):
        os.makedirs(dbdir)

    db = open("admin")
    db.clear()

    #
    # INITIAL PRIORITY AND STATUS VALUES
    #
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

    # create the two default users
    user = db.getclass('user')
    user.create(username="admin", password=adminpw,
        address=config.ADMIN_EMAIL, roles='Admin')
    user.create(username="anonymous", roles='Anonymous')

    # add any additional database create steps here - but only if you
    # haven't initialised the database with the admin "initialise" command

    db.commit()
    db.close()

# vim: set filetype=python ts=4 sw=4 et si

