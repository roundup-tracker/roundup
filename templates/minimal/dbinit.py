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
# $Id: dbinit.py,v 1.1 2003-04-17 03:27:27 richard Exp $

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

    # The "Minimal" template gets only one class, the required "user"
    # class. That's it. And even that has the bare minimum of properties.

    # Note: roles is a comma-separated string of Role names
    user = Class(db, "user", username=String(), password=Password(),
        address=String(), alternate_addresses=String(), roles=String())
    user.setkey("username")

    # add any additional database schema configuration here

    #
    # SECURITY SETTINGS
    #
    # new permissions for this schema
    for cl in ('user', ):
        db.security.addPermission(name="Edit", klass=cl,
            description="User is allowed to edit "+cl)
        db.security.addPermission(name="View", klass=cl,
            description="User is allowed to access "+cl)

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

    # create the two default users
    user = db.getclass('user')
    user.create(username="admin", password=adminpw,
        address=config.ADMIN_EMAIL, roles='Admin')
    user.create(username="anonymous", roles='Anonymous')

    # add any additional database create steps here - but only if you
    # haven't initialised the database with the admin "initialise" command

    db.commit()

# vim: set filetype=python ts=4 sw=4 et si

