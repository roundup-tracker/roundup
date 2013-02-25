# -*- coding: utf-8 -*-

from roundup import password, date

pri = db.getclass('priority')
pri.create(name=''"critical", order="1")
pri.create(name=''"urgent", order="2")
pri.create(name=''"bug", order="3")
pri.create(name=''"feature", order="4")
pri.create(name=''"wish", order="5")

stat = db.getclass('status')
stat.create(name=''"unread", order="1")
stat.create(name=''"deferred", order="2")
stat.create(name=''"chatting", order="3")
stat.create(name=''"need-eg", order="4")
stat.create(name=''"in-progress", order="5")
stat.create(name=''"testing", order="6")
stat.create(name=''"done-cbb", order="7")
stat.create(name=''"resolved", order="8")

user = db.getclass('user')
user.create(username="admin", password=adminpw,
    address=admin_email, roles='Admin')
user.create(username="anonymous", roles='Anonymous')
user.create(username='testuser', password=password.Password('testuser'),
    realname='Test User', roles='User', address='t1@example.com')
