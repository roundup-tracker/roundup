
import pprint
db = Database("test_db", "richard")
status = Class(db, "status", name=String())
status.setkey("name")
print db.status.create(name="unread")
print db.status.create(name="in-progress")
print db.status.create(name="testing")
print db.status.create(name="resolved")
print db.status.count()
print db.status.list()
print db.status.lookup("in-progress")
db.status.retire(3)
print db.status.list()
issue = Class(db, "issue", title=String(), status=Link("status"))
db.issue.create(title="spam", status=1)
db.issue.create(title="eggs", status=2)
db.issue.create(title="ham", status=4)
db.issue.create(title="arguments", status=2)
db.issue.create(title="abuse", status=1)
user = Class(db, "user", username=String(), password=String())
user.setkey("username")
db.issue.addprop(fixer=Link("user"))
print db.issue.getprops()
#{"title": <hyperdb.String>, "status": <hyperdb.Link to "status">,
#"user": <hyperdb.Link to "user">}
db.issue.set(5, status=2)
print db.issue.get(5, "status")
print db.status.get(2, "name")
print db.issue.get(5, "title")
print db.issue.find(status = db.status.lookup("in-progress"))
print db.issue.history(5)
# [(<Date 2000-06-28.19:09:43>, "ping", "create", {"title": "abuse", "status": 1}),
# (<Date 2000-06-28.19:11:04>, "ping", "set", {"status": 2})]
print db.status.history(1)
# [(<Date 2000-06-28.19:09:43>, "ping", "link", ("issue", 5, "status")),
# (<Date 2000-06-28.19:11:04>, "ping", "unlink", ("issue", 5, "status"))]
print db.status.history(2)
# [(<Date 2000-06-28.19:11:04>, "ping", "link", ("issue", 5, "status"))]

# TODO: set up some filter tests
