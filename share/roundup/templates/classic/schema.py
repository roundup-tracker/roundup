
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
db.security.addPermission(name='Register', klass='user',
                          description='User is allowed to register new user')

# FileClass automatically gets this property in addition to the Class ones:
#   content = String()    [saved to disk in <tracker home>/db/files/]
#   type = String()       [MIME type of the content, default 'text/plain']
msg = FileClass(db, "msg",
                author=Link("user", do_journal='no'),
                recipients=Multilink("user", do_journal='no'),
                date=Date(),
                summary=String(),
                files=Multilink("file"),
                messageid=String(),
                inreplyto=String())

file = FileClass(db, "file",
                name=String())

# IssueClass automatically gets these properties in addition to the Class ones:
#   title = String()
#   messages = Multilink("msg")
#   files = Multilink("file")
#   nosy = Multilink("user")
#   superseder = Multilink("issue")
issue = IssueClass(db, "issue",
                assignedto=Link("user"),
                keyword=Multilink("keyword"),
                priority=Link("priority"),
                status=Link("status"))

#
# TRACKER SECURITY SETTINGS
#
# See the configuration and customisation document for information
# about security setup.

#
# REGULAR USERS
#
# Give the regular users access to the web and email interface
db.security.addPermissionToRole('User', 'Web Access')
db.security.addPermissionToRole('User', 'Email Access')

# Assign the access and edit Permissions for issue, file and message
# to regular users now
for cl in 'issue', 'file', 'msg', 'keyword':
    db.security.addPermissionToRole('User', 'View', cl)
    db.security.addPermissionToRole('User', 'Edit', cl)
    db.security.addPermissionToRole('User', 'Create', cl)
for cl in 'priority', 'status':
    db.security.addPermissionToRole('User', 'View', cl)

# May users view other user information? Comment these lines out
# if you don't want them to
db.security.addPermissionToRole('User', 'View', 'user')

# Users should be able to edit their own details -- this permission is
# limited to only the situation where the Viewed or Edited item is their own.
def own_record(db, userid, itemid):
    '''Determine whether the userid matches the item being accessed.'''
    return userid == itemid
p = db.security.addPermission(name='View', klass='user', check=own_record,
    description="User is allowed to view their own user details")
db.security.addPermissionToRole('User', p)
p = db.security.addPermission(name='Edit', klass='user', check=own_record,
    description="User is allowed to edit their own user details")
db.security.addPermissionToRole('User', p)

# Users should be able to edit and view their own queries. They should also
# be able to view any marked as not private. They should not be able to
# edit others' queries, even if they're not private
def view_query(db, userid, itemid):
    private_for = db.query.get(itemid, 'private_for')
    if not private_for: return True
    return userid == private_for
def edit_query(db, userid, itemid):
    return userid == db.query.get(itemid, 'creator')
p = db.security.addPermission(name='View', klass='query', check=view_query,
    description="User is allowed to view their own and public queries")
db.security.addPermissionToRole('User', p)
p = db.security.addPermission(name='Edit', klass='query', check=edit_query,
    description="User is allowed to edit their queries")
db.security.addPermissionToRole('User', p)
p = db.security.addPermission(name='Retire', klass='query', check=edit_query,
    description="User is allowed to retire their queries")
db.security.addPermissionToRole('User', p)
p = db.security.addPermission(name='Create', klass='query',
    description="User is allowed to create queries")
db.security.addPermissionToRole('User', p)


#
# ANONYMOUS USER PERMISSIONS
#
# Let anonymous users access the web interface. Note that almost all
# trackers will need this Permission. The only situation where it's not
# required is in a tracker that uses an HTTP Basic Authenticated front-end.
db.security.addPermissionToRole('Anonymous', 'Web Access')

# Let anonymous users access the email interface (note that this implies
# that they will be registered automatically, hence they will need the
# "Create" user Permission below)
# This is disabled by default to stop spam from auto-registering users on
# public trackers.
#db.security.addPermissionToRole('Anonymous', 'Email Access')

# Assign the appropriate permissions to the anonymous user's Anonymous
# Role. Choices here are:
# - Allow anonymous users to register
db.security.addPermissionToRole('Anonymous', 'Register', 'user')

# Allow anonymous users access to view issues (and the related, linked
# information)
for cl in 'issue', 'file', 'msg', 'keyword', 'priority', 'status':
    db.security.addPermissionToRole('Anonymous', 'View', cl)

# [OPTIONAL]
# Allow anonymous users access to create or edit "issue" items (and the
# related file and message items)
#for cl in 'issue', 'file', 'msg':
#   db.security.addPermissionToRole('Anonymous', 'Create', cl)
#   db.security.addPermissionToRole('Anonymous', 'Edit', cl)


# vim: set filetype=python sts=4 sw=4 et si :
