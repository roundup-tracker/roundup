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
db.security.addPermissionToRole('User', 'Web Access')
db.security.addPermissionToRole('User', 'Email Access')

# May users view other user information?
# Comment these lines out if you don't want them to
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
db.security.addPermissionToRole('Anonymous', 'Email Access')

# Assign the appropriate permissions to the anonymous user's
# Anonymous Role. Choices here are:
# - Allow anonymous users to register
db.security.addPermissionToRole('Anonymous', 'Register', 'user')

# vim: set et sts=4 sw=4 :
