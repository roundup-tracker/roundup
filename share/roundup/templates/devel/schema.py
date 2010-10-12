
#
# TRACKER SCHEMA
#

# Class automatically gets these properties:
#   creation = Date()
#   activity = Date()
#   creator = Link('user')
#   actor = Link('user')


# This is the repository class, then you can see/edit repositories in pages like
# "http://tracker/url/vcs_repo1"
vcs_repo = Class(db, "vcs_repo",
name=String(),
host=String(),
path=String(),
webview_url=String())
vcs_repo.setkey('name')

# Stores revision data, lets you see/edit revisions in pages like
# "http://tracker/url/vcs_rev1". The vcs_rev.item.html template is currently
# broken, but this works fine without it.
vcs_rev = Class(db, "vcs_rev",
repository=Link('vcs_repo'),
revision=String())



# Component
component = Class(db, 'component',
                  name=String(),
                  description=String(),
                  order=Number(),
                  assign_to=Link('user'))
component.setkey('name')

# Version
version = Class(db, 'version',
                name=String(),
                description=String(),
                order=Number())
version.setkey('name')

# Severity
severity = Class(db, 'severity',
                 name=String(),
                 description=String(),
                 order=Number())
severity.setkey('name')

# Priority
priority = Class(db, 'priority',
                 name=String(),
                 description=String(),
                 order=Number())
priority.setkey('name')

# Status
status = Class(db, "status",
               name=String(),
               description=String(),
               order=Number())
status.setkey("name")

# Resolution
resolution = Class(db, "resolution",
                   name=String(),
                   description=String(),
                   order=Number())
resolution.setkey('name')

# Keyword
keyword = Class(db, "keyword",
                name=String(),
                description=String())
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
             timezone=String(),
             vcs_name=String())

user.setkey("username")

# Permissions for revision creation and repository viewing.
for role in ('User',):
    db.security.addPermissionToRole(role, 'Create', 'vcs_rev')
    db.security.addPermissionToRole(role, 'View', 'vcs_repo')

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
                inreplyto=String(),
                revision=Link("vcs_rev"))

# File
file = FileClass(db, "file",
                name=String(),
                description=String(indexme='yes'))

# Patch
patch = FileClass(db, "patch",
                  name=String(),
                  description=String(indexme='yes'),
                  repository=String(),
                  revision=String())

# Bug Type
bug_type = Class(db, 'bug_type',
                 name=String(),
                 description=String(),
                 order=Number())
bug_type.setkey('name')

# IssueClass automatically gets these properties in addition to the Class ones:
#   title = String()
#   messages = Multilink("msg")
#   files = Multilink("file")
#   patches = Multilink("patches")
#   nosy = Multilink("user")
#   superseder = Multilink("issue")
bug = IssueClass(db, "bug",
                 type=Link('bug_type'),
                 components=Multilink('component'),
                 versions=Multilink('version'),
                 severity=Link('severity'),
                 priority=Link('priority'),
                 dependencies=Multilink('bug'),
                 assignee=Link('user'),
                 status=Link('status'),
                 resolution=Link('resolution'),
                 superseder=Link('bug'),
                 keywords=Multilink('keyword'))

# Task Type
task_type = Class(db, 'task_type',
                 name=String(),
                 description=String(),
                 order=Number())
task_type.setkey('name')

# IssueClass automatically gets these properties in addition to the Class ones:
#   title = String()
#   messages = Multilink("msg")
#   files = Multilink("file")
#   nosy = Multilink("user")
#   superseder = Multilink("issue")
task = IssueClass(db, "task",
                  type=Link('task_type'),
                  components=Multilink('component'),
                  priority=Link('priority'),
                  dependencies=Multilink('task'),
                  assignee=Multilink('user'),
                  status=Link('status'),
                  resolution=Link('resolution'),
                  solves=Link('bug'))

milestone = IssueClass(db, "milestone",
                       bugs=Multilink("bug"),
                       tasks=Multilink("task"),
                       status=Link("status"),
                       release_date=String())

#
# TRACKER SECURITY SETTINGS
#
# See the configuration and customisation document for information
# about security setup.

db.security.addRole(name='Developer', description='A developer')
db.security.addRole(name='Coordinator', description='A coordinator')

#
# REGULAR USERS
#
# Give the regular users access to the web and email interface
for r in 'User', 'Developer', 'Coordinator':
    db.security.addPermissionToRole(r, 'Web Access')
    db.security.addPermissionToRole(r, 'Email Access')

##########################
# User permissions
##########################

for cl in ('severity', 'component',
           'version', 'priority', 'status', 'resolution',
           'bug_type', 'bug', 'task_type', 'task', 'milestone',
           'keyword', 'file', 'msg'):
    db.security.addPermissionToRole('User', 'View', cl)
    db.security.addPermissionToRole('Anonymous', 'View', cl)
    db.security.addPermissionToRole('User', 'Create', cl)
    

def may_edit_file(db, userid, itemid):
    return userid == db.file.get(itemid, "creator")

p = db.security.addPermission(name='Edit', klass='file', check=may_edit_file,
    description="User is allowed to remove their own files")
db.security.addPermissionToRole('User', p)

p = db.security.addPermission(name='Create', klass='bug',
                              properties=('title', 'bug_type',
                                          'components', 'versions',
                                          'severity',
                                          'messages', 'files', 'nosy'),
                              description='User can report and discuss bugs')
db.security.addPermissionToRole('User', p)

p = db.security.addPermission(name='Edit', klass='bug',
                              properties=('title', 'bug_type',
                                          'components', 'versions',
                                          'severity',
                                          'messages', 'files', 'nosy'),
                              description='User can report and discuss bugs')
db.security.addPermissionToRole('User', p)

p = db.security.addPermission(name='Create', klass='task',
                              properties=('title', 'task_type',
                                          'components',
                                          'messages', 'files', 'nosy'),
                              description='Developer can create and discuss tasks')
db.security.addPermissionToRole('Developer', p)

p = db.security.addPermission(name='Edit', klass='task',
                              properties=('title', 'task_type',
                                          'components',
                                          'messages', 'files', 'nosy'),
                              description='Developer can create and discuss tasks')
db.security.addPermissionToRole('Developer', p)

p = db.security.addPermission(name='Create', klass='milestone',
                              description='Coordinator can create and discuss milestones')
db.security.addPermissionToRole('Coordinator', p)

p = db.security.addPermission(name='Edit', klass='milestone',
                              description='Coordinator can create and discuss milestones')
db.security.addPermissionToRole('Coordinator', p)


##########################
# Developer permissions
##########################
for cl in ('bug_type', 'severity', 'component',
           'version', 'priority', 'status', 'resolution',
           'bug', 'file', 'msg', 'keyword'):
    db.security.addPermissionToRole('Developer', 'View', cl)

for cl in ('bug', 'file', 'msg', 'keyword'):
    db.security.addPermissionToRole('Developer', 'Edit', cl)
    db.security.addPermissionToRole('Developer', 'Create', cl)


##########################
# Coordinator permissions
##########################
for cl in ('bug_type', 'task_type', 'severity', 'component',
           'version', 'priority', 'status', 'resolution', 'bug', 'task', 'file', 'msg'):
    db.security.addPermissionToRole('Coordinator', 'View', cl)
    db.security.addPermissionToRole('Coordinator', 'Edit', cl)
    db.security.addPermissionToRole('Coordinator', 'Create', cl)

# May users view other user information? Comment these lines out
# if you don't want them to
db.security.addPermissionToRole('User', 'View', 'user')
db.security.addPermissionToRole('Developer', 'View', 'user')
db.security.addPermissionToRole('Coordinator', 'View', 'user')

# Allow Coordinator to edit any user, including their roles.
db.security.addPermissionToRole('Coordinator', 'Edit', 'user')
db.security.addPermissionToRole('Coordinator', 'Web Roles')

# Users should be able to edit their own details -- this permission is
# limited to only the situation where the Viewed or Edited item is their own.
def own_record(db, userid, itemid):
    '''Determine whether the userid matches the item being accessed.'''
    return userid == itemid
p = db.security.addPermission(name='View', klass='user', check=own_record,
    description="User is allowed to view their own user details")
for r in 'User', 'Developer', 'Coordinator':
    db.security.addPermissionToRole(r, p)
p = db.security.addPermission(name='Edit', klass='user', check=own_record,
    description="User is allowed to edit their own user details",
    properties=('username', 'password',
                'address', 'realname',
                'phone', 'organization',
                'alternate_addresses',
                'queries',
                'timezone')) # Note: 'roles' excluded - users should not be able to edit their own roles. 
for r in 'User', 'Developer':
    db.security.addPermissionToRole(r, p)

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
for r in 'User', 'Developer', 'Coordinator':
    db.security.addPermissionToRole(r, p)
p = db.security.addPermission(name='Edit', klass='query', check=edit_query,
    description="User is allowed to edit their queries")
for r in 'User', 'Developer', 'Coordinator':
    db.security.addPermissionToRole(r, p)
p = db.security.addPermission(name='Create', klass='query',
    description="User is allowed to create queries")
for r in 'User', 'Developer', 'Coordinator':
    db.security.addPermissionToRole(r, p)


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
db.security.addPermissionToRole('Anonymous', 'Create', 'user')

# Allow anonymous users access to view issues (and the related, linked
# information).

for cl in 'bug', 'task', 'milestone', 'severity', 'status', 'resolution', 'msg', 'file':
    db.security.addPermissionToRole('Anonymous', 'View', cl)

# [OPTIONAL]
# Allow anonymous users access to create or edit "issue" items (and the
# related file and message items)
#for cl in 'issue', 'file', 'msg':
#   db.security.addPermissionToRole('Anonymous', 'Create', cl)
#   db.security.addPermissionToRole('Anonymous', 'Edit', cl)


# vim: set filetype=python sts=4 sw=4 et si :

