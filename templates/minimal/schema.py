#
# TRACKER SCHEMA
#

# Class automatically gets these properties:
#   creation = Date()
#   activity = Date()
#   creator = Link('user')
#   actor = Link('user')

# The "Minimal" template gets only one class, the required "user"
# class. That's it. And even that has the bare minimum of properties.

# Note: roles is a comma-separated string of Role names
user = Class(db, "user", username=String(), password=Password(),
    address=String(), alternate_addresses=String(), roles=String())
user.setkey("username")
#
# TRACKER SECURITY SETTINGS
#
# See the configuration and customisation document for information
# about security setup.

#
# REGULAR USERS
#
# Give the regular users access to the web and email interface
p = db.security.getPermission('Web Access')
db.security.addPermissionToRole('User', p)
p = db.security.getPermission('Email Access')
db.security.addPermissionToRole('User', p)

# May users view other user information?
# Comment these lines out if you don't want them to
p = db.security.getPermission('View', 'user')
db.security.addPermissionToRole('User', p)

# Users should be able to edit their own details.
# Note that this permission is limited to only the situation
# where the Viewed or Edited item is their own.
def own_record(db, userid, itemid):
    '''Determine whether the userid matches the item being accessed.'''
    return userid == itemid
p = db.security.addPermission(name='View', klass='user', check=own_record,
    description="User is allowed to view their own user details")
p = db.security.addPermission(name='Edit', klass='user', check=own_record,
    description="User is allowed to edit their own user details")
db.security.addPermissionToRole('User', p)

#
# ANONYMOUS USER PERMISSIONS
#
# Let anonymous users access the web interface. Note that almost all
# trackers will need this Permission. The only situation where it's not
# required is in a tracker that uses an HTTP Basic Authenticated front-end.
p = db.security.getPermission('Web Access')
db.security.addPermissionToRole('Anonymous', p)

# Let anonymous users access the email interface (note that this implies
# that they will be registered automatically, hence they will need the
# "Create" user Permission below)
p = db.security.getPermission('Email Access')
db.security.addPermissionToRole('Anonymous', p)

# Assign the appropriate permissions to the anonymous user's
# Anonymous Role. Choices here are:
# - Allow anonymous users to register
p = db.security.getPermission('Create', 'user')
db.security.addPermissionToRole('Anonymous', p)

# vim: set et sts=4 sw=4 :
