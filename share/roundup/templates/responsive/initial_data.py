from roundup.password import Password

#
# TRACKER INITIAL PRIORITY AND STATUS VALUES
#

bug_type = db.getclass('bug_type')
bug_type.create(name='crash', order='1')
bug_type.create(name='compile error', order='2')
bug_type.create(name='resource usage', order='3')
bug_type.create(name='security', order='4')
bug_type.create(name='behavior', order='5')
bug_type.create(name='rfe', order='6')

component = db.getclass('component')
component.create(name="backend", order="1")
component.create(name="frontend", order="2")
component.create(name="documentation", order="3")
component.create(name="specification", order="4")

version = db.getclass('version')
version.create(name='devel', order='1')
version.create(name='1.0', order='2')
version.create(name='1.1', order='3')
version.create(name='1.2', order='4')
version.create(name='1.3', order='5')
version.create(name='1.4', order='6')


severity = db.getclass('severity')
severity.create(name='critical', order='1')
severity.create(name='urgent', order='2')
severity.create(name='major', order='3')
severity.create(name='normal', order='4')
severity.create(name='minor', order='5')

priority = db.getclass('priority')
priority.create(name='immediate', order='1')
priority.create(name='urgent', order='2')
priority.create(name='high', order='3')
priority.create(name='normal', order='4')
priority.create(name='low', order='5')

status = db.getclass('status')
status.create(name = "new", order = "1")
status.create(name='open', order='2')
status.create(name='closed', order='3')
status.create(name='pending', description='user feedback required', order='4')

resolution = db.getclass('resolution')
resolution.create(name='accepted', order='1')
resolution.create(name='duplicate', order='2')
resolution.create(name='fixed', order='3')
resolution.create(name='invalid', order='4')
resolution.create(name='later', order='5')
resolution.create(name='out of date', order='6')
resolution.create(name='postponed', order='7')
resolution.create(name='rejected', order='8')
resolution.create(name='remind', order='9')
resolution.create(name='wont fix', order='10')
resolution.create(name='works for me', order='11')

keyword = db.getclass("keyword")
keyword.create(name="patch", description="Contains patch")

#
# create the two default users
user = db.getclass('user')
user.create(username="admin", password=adminpw, address=admin_email, roles='Admin')
user.create(username="anonymous", roles='Anonymous')
user.create(username="user", roles='User')
user.create(username="developer", roles='User, Developer')
user.create(username="coordinator", roles='User, Developer, Coordinator')

