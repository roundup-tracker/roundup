# $Id: __init__.py,v 1.1 2001-07-23 03:50:46 anthonybaxter Exp $

MAIL_DOMAIN=MAILHOST=HTTP_HOST=None
HTTP_PORT=0

try:
    from localconfig import *
except ImportError:
    localconfig = None

import os

# roundup home is this package's directory
ROUNDUP_HOME=os.path.split(__file__)[0]

# The SMTP mail host that roundup will use to send mail
if not MAILHOST:
    MAILHOST = 'localhost'

# The domain name used for email addresses.
if not MAIL_DOMAIN:
    MAIL_DOMAIN = 'bizarsoftware.com.au'

# the next two are only used for the standalone HTTP server.
if not HTTP_HOST:
    HTTP_HOST = ''
if not HTTP_PORT:
    HTTP_PORT = 9080

# This is the directory that the database is going to be stored in
DATABASE = os.path.join(ROUNDUP_HOME, 'db')

# This is the directory that the HTML templates reside in
TEMPLATES = os.path.join(ROUNDUP_HOME, 'templates')

# The email address that mail to roundup should go to
ISSUE_TRACKER_EMAIL = 'issue_tracker@%s'%MAIL_DOMAIN

# The email address that roundup will complain to if it runs into trouble
ADMIN_EMAIL = 'roundup-admin@%s'%MAIL_DOMAIN

# Somewhere for roundup to log stuff internally sent to stdout or stderr
LOG = os.path.join(ROUNDUP_HOME, 'roundup.log')


from roundup import hyperdb, hyper_bsddb, roundupdb, cgi_client, mailgw 
 
class Database(roundupdb.Database, hyper_bsddb.Database):
    ''' Creates a hybrid database from: 
         . the base Database class given in hyperdb (basic functionlity) 
         . the BSDDB implementation in hyperdb_bsddb 
         . the roundup extensions from roundupdb 
    ''' 
    pass 

Class = roundupdb.Class
class IssueClass(roundupdb.IssueClass):
    ''' issues need the email information
    '''
    ISSUE_TRACKER_EMAIL = ISSUE_TRACKER_EMAIL
    ADMIN_EMAIL = ADMIN_EMAIL
    MAILHOST = MAILHOST

FileClass = roundupdb.FileClass
 
class Client(cgi_client.Client): 
    ''' derives basic mail gateway implementation from the standard module, 
        with any specific extensions 
    ''' 
    TEMPLATES = TEMPLATES
    pass 
 
class MailGW(mailgw.MailGW): 
    ''' derives basic mail gateway implementation from the standard module, 
        with any specific extensions 
    ''' 
    ISSUE_TRACKER_EMAIL = ISSUE_TRACKER_EMAIL
    ADMIN_EMAIL = ADMIN_EMAIL
    MAILHOST = MAILHOST
 
def open(name=None):
    ''' as from the roundupdb method openDB 
 
     storagelocator must be the directory the __init__.py file is in 
     - os.path.split(__file__)[0] gives us that I think 
    ''' 
    db = Database(DATABASE, name)
    pri = Class(db, "priority", name=hyperdb.String(), order=hyperdb.String())
    pri.setkey("name")
    stat = Class(db, "status", name=hyperdb.String(), order=hyperdb.String())
    stat.setkey("name")
    Class(db, "keyword", name=hyperdb.String())
    user = Class(db, "user", username=hyperdb.String(),
        password=hyperdb.String(), address=hyperdb.String(),
        realname=hyperdb.String(), phone=hyperdb.String(),
        organisation=hyperdb.String())
    user.setkey("username")
    msg = FileClass(db, "msg", author=hyperdb.Link("user"),
        recipients=hyperdb.Multilink("user"), date=hyperdb.Date(),
        summary=hyperdb.String(), files=hyperdb.Multilink("file"))
    file = FileClass(db, "file", name=hyperdb.String(), type=hyperdb.String())

    # bugs and support calls etc
    rate = Class(db, "rate", name=hyperdb.String(), order=hyperdb.String())
    rate.setkey("name")
    source = Class(db, "source", name=hyperdb.String(), order=hyperdb.String())
    source.setkey("name")
    platform = Class(db, "platform", name=hyperdb.String(), order=hyperdb.String())
    platform.setkey("name")
    product = Class(db, "product", name=hyperdb.String(), order=hyperdb.String())
    product.setkey("name")
    Class(db, "timelog", date=hyperdb.Date(), time=hyperdb.String(),
        performedby=hyperdb.Link("user"), description=hyperdb.String())
    issue = IssueClass(db, "issue", assignedto=hyperdb.Link("user"),
        priority=hyperdb.Link("priority"), status=hyperdb.Link("status"),
        rate=hyperdb.Link("rate"), source=hyperdb.Link("source"),
        product=hyperdb.Link("product"), platform=hyperdb.Multilink("platform"),
        version=hyperdb.String(),
        timelog=hyperdb.Multilink("timelog"), customername=hyperdb.String())
    issue.setkey('title')
    import detectors
    detectors.init(db)
    return db
 
def init(adminpw): 
    ''' as from the roundupdb method initDB 
 
     storagelocator must be the directory the __init__.py file is in 
     - os.path.split(__file__)[0] gives us that I think 
    ''' 
    dbdir = os.path.join(DATABASE, 'files')
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
    user.create(username="admin", password=adminpw, address=ADMIN_EMAIL)

    db.close()

#
# $Log: not supported by cvs2svn $
# Revision 1.2  2001/07/22 12:09:32  richard
# Final commit of Grande Splite
#
#


