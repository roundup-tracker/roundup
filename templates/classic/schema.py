
#
# TRACKER SCHEMA
#

# Class automatically gets these properties:
#   creation = Date()
#   activity = Date()
#   creator = Link('user')
#   actor = Link('user')

# Priorities
pri = Class(db, "priority", 
                name=String(),
                order=Number())
pri.setkey("name")

# Statuses
stat = Class(db, "status", 
                name=String(),
                order=Number())
stat.setkey("name")

# Keywords
keyword = Class(db, "keyword", 
                name=String())
keyword.setkey("name")

# User-defined saved searches
query = Class(db, "query",
                klass=String(),
                name=String(),
                url=String(),
                private_for=Link('user'))

# add any additional database schema configuration here

user = Class(db, "user", 
                username=String(),
                password=Password(),
                address=String(),
                realname=String(), 
                phone=String(),
                organisation=String(),
                alternate_addresses=String(),
                queries=Multilink('query'),
                roles=String(),     # comma-separated string of Role names
                timezone=String())
user.setkey("username")

# FileClass automatically gets this property in addition to the Class ones:
#   content = String()    [saved to disk in <tracker home>/db/files/]
msg = FileClass(db, "msg", 
                author=Link("user", do_journal='no'),
                recipients=Multilink("user", do_journal='no'), 
                date=Date(),
                summary=String(), 
                files=Multilink("file"),
                messageid=String(),
                inreplyto=String())

file = FileClass(db, "file", 
                name=String(),
                type=String())

# IssueClass automatically gets these properties in addition to the Class ones:
#   title = String()
#   messages = Multilink("msg")
#   files = Multilink("file")
#   nosy = Multilink("user")
#   superseder = Multilink("issue")
issue = IssueClass(db, "issue", 
                assignedto=Link("user"),
                topic=Multilink("keyword"),
                priority=Link("priority"),
                status=Link("status"))

#
# TRACKER SECURITY SETTINGS
#
# See the configuration and customisation document for information
# about security setup.
# Assign the access and edit Permissions for issue, file and message
# to regular users now
for cl in 'issue', 'file', 'msg', 'query', 'keyword':
    p = db.security.getPermission('View', cl)
    db.security.addPermissionToRole('User', p)
    p = db.security.getPermission('Edit', cl)
    db.security.addPermissionToRole('User', p)
for cl in 'priority', 'status':
    p = db.security.getPermission('View', cl)
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
# - Allow anonymous users access to view issues (which implies being
#   able to view all linked information too
for cl in 'issue', 'file', 'msg', 'keyword', 'priority', 'status':
    p = db.security.getPermission('View', cl)
    db.security.addPermissionToRole('Anonymous', p)
# - Allow anonymous users access to edit the "issue" class of data
#   Note: this also grants access to create related information like
#         files and messages etc that are linked to issues
#p = db.security.getPermission('Edit', 'issue')
#db.security.addPermissionToRole('Anonymous', p)

# oh, g'wan, let anonymous access the web interface too
p = db.security.getPermission('Web Access')
db.security.addPermissionToRole('Anonymous', p)


# vim: set filetype=python sts=4 sw=4 et si
