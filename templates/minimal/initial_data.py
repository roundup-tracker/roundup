#
# TRACKER DATABASE INITIALIZATION
#

# create the two default users
user = db.getclass('user')
user.create(username="admin", password=adminpw,
    address=admin_email, roles='Admin')
user.create(username="anonymous", roles='Anonymous')

# add any additional database creation steps here - but only if you
# haven't initialised the database with the admin "initialise" command

# vim: set et sts=4 sw=4 :
