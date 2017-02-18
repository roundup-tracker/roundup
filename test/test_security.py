# Copyright (c) 2002 ekit.com Inc (http://www.ekit-inc.com/)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import os, unittest, shutil

from roundup import backends
import roundup.password
from db_test_base import setupSchema, MyTestCase, config


class PermissionTest(MyTestCase, unittest.TestCase):
    def setUp(self):
        backend = backends.get_backend('anydbm')
        # remove previous test, ignore errors
        if os.path.exists(config.DATABASE):
            shutil.rmtree(config.DATABASE)
        os.makedirs(config.DATABASE + '/files')
        self.db = backend.Database(config, 'admin')
        setupSchema(self.db, 1, backend)

    def testInterfaceSecurity(self):
        ' test that the CGI and mailgw have initialised security OK '
        # TODO: some asserts

    def testInitialiseSecurity(self):
        ei = self.db.security.addPermission(name="Edit", klass="issue",
                        description="User is allowed to edit issues")
        self.db.security.addPermissionToRole('User', ei)
        ai = self.db.security.addPermission(name="View", klass="issue",
                        description="User is allowed to access issues")
        self.db.security.addPermissionToRole('User', ai)

    def testAdmin(self):
        ei = self.db.security.addPermission(name="Edit", klass="issue",
                        description="User is allowed to edit issues")
        self.db.security.addPermissionToRole('User', ei)
        ei = self.db.security.addPermission(name="Edit", klass=None,
                        description="User is allowed to edit issues")
        self.db.security.addPermissionToRole('Admin', ei)

        u1 = self.db.user.create(username='one', roles='Admin')
        u2 = self.db.user.create(username='two', roles='User')

        self.assert_(self.db.security.hasPermission('Edit', u1, None))
        self.assert_(not self.db.security.hasPermission('Edit', u2, None))


    def testGetPermission(self):
        self.db.security.getPermission('Edit')
        self.db.security.getPermission('View')
        self.assertRaises(ValueError, self.db.security.getPermission, 'x')
        self.assertRaises(ValueError, self.db.security.getPermission, 'Edit',
            'fubar')

        add = self.db.security.addPermission
        get = self.db.security.getPermission

        # class
        ei = add(name="Edit", klass="issue")
        self.assertEquals(get('Edit', 'issue'), ei)
        ai = add(name="View", klass="issue")
        self.assertEquals(get('View', 'issue'), ai)

        # property
        epi = add(name="Edit", klass="issue", properties=['title'])
        self.assertEquals(get('Edit', 'issue', properties=['title']), epi)
        api = add(name="View", klass="issue", properties=['title'])
        self.assertEquals(get('View', 'issue', properties=['title']), api)
        
        # check function
        dummy = lambda: 0
        eci = add(name="Edit", klass="issue", check=dummy)
        self.assertEquals(get('Edit', 'issue', check=dummy), eci)
        aci = add(name="View", klass="issue", check=dummy)
        self.assertEquals(get('View', 'issue', check=dummy), aci)

        # all
        epci = add(name="Edit", klass="issue", properties=['title'],
            check=dummy)
        self.assertEquals(get('Edit', 'issue', properties=['title'],
            check=dummy), epci)
        apci = add(name="View", klass="issue", properties=['title'],
            check=dummy)
        self.assertEquals(get('View', 'issue', properties=['title'],
            check=dummy), apci)

    def testDBinit(self):
        self.db.user.create(username="demo", roles='User')
        self.db.user.create(username="anonymous", roles='Anonymous')

    def testAccessControls(self):
        add = self.db.security.addPermission
        has = self.db.security.hasPermission
        addRole = self.db.security.addRole
        addToRole = self.db.security.addPermissionToRole

        none = self.db.user.create(username='none', roles='None')

        # test admin access
        addRole(name='Super')
        addToRole('Super', add(name="Test"))
        super = self.db.user.create(username='super', roles='Super')

        # test class-level access
        addRole(name='Role1')
        addToRole('Role1', add(name="Test", klass="test"))
        user1 = self.db.user.create(username='user1', roles='Role1')
        self.assertEquals(has('Test', user1, 'test'), 1)
        self.assertEquals(has('Test', super, 'test'), 1)
        self.assertEquals(has('Test', none, 'test'), 0)

        # property
        addRole(name='Role2')
        addToRole('Role2', add(name="Test", klass="test", properties=['a','b']))
        user2 = self.db.user.create(username='user2', roles='Role2')
        # *any* access to class
        self.assertEquals(has('Test', user1, 'test'), 1)
        self.assertEquals(has('Test', user2, 'test'), 1)

        # *any* access to item
        self.assertEquals(has('Test', user1, 'test', itemid='1'), 1)
        self.assertEquals(has('Test', user2, 'test', itemid='1'), 1)
        self.assertEquals(has('Test', super, 'test', itemid='1'), 1)
        self.assertEquals(has('Test', none, 'test', itemid='1'), 0)

        # now property test
        self.assertEquals(has('Test', user2, 'test', property='a'), 1)
        self.assertEquals(has('Test', user2, 'test', property='b'), 1)
        self.assertEquals(has('Test', user2, 'test', property='c'), 0)
        self.assertEquals(has('Test', user1, 'test', property='a'), 1)
        self.assertEquals(has('Test', user1, 'test', property='b'), 1)
        self.assertEquals(has('Test', user1, 'test', property='c'), 1)
        self.assertEquals(has('Test', super, 'test', property='a'), 1)
        self.assertEquals(has('Test', super, 'test', property='b'), 1)
        self.assertEquals(has('Test', super, 'test', property='c'), 1)
        self.assertEquals(has('Test', none, 'test', property='a'), 0)
        self.assertEquals(has('Test', none, 'test', property='b'), 0)
        self.assertEquals(has('Test', none, 'test', property='c'), 0)
        self.assertEquals(has('Test', none, 'test'), 0)

        # check function new style. Make sure that other args are passed.
        def check(db,userid,itemid, **other):
            prop = other['property']
            prop = other['classname']
            prop = other['permission']
            return (itemid == '1')

        addRole(name='Role3')
        addToRole('Role3', add(name="Test", klass="test", check=check))
        user3 = self.db.user.create(username='user3', roles='Role3')
        # *any* access to class
        self.assertEquals(has('Test', user1, 'test'), 1)
        self.assertEquals(has('Test', user2, 'test'), 1)
        self.assertEquals(has('Test', user3, 'test'), 1)
        self.assertEquals(has('Test', none, 'test'), 0)
        # now check function
        self.assertEquals(has('Test', user3, 'test', itemid='1'), 1)
        self.assertEquals(has('Test', user3, 'test', itemid='2'), 0)
        self.assertEquals(has('Test', user2, 'test', itemid='1'), 1)
        self.assertEquals(has('Test', user2, 'test', itemid='2'), 1)
        self.assertEquals(has('Test', user1, 'test', itemid='2'), 1)
        self.assertEquals(has('Test', user1, 'test', itemid='2'), 1)
        self.assertEquals(has('Test', super, 'test', itemid='1'), 1)
        self.assertEquals(has('Test', super, 'test', itemid='2'), 1)
        self.assertEquals(has('Test', none, 'test', itemid='1'), 0)
        self.assertEquals(has('Test', none, 'test', itemid='2'), 0)

    def testTransitiveSearchPermissions(self):
        add = self.db.security.addPermission
        has = self.db.security.hasSearchPermission
        addRole = self.db.security.addRole
        addToRole = self.db.security.addPermissionToRole
        addRole(name='User')
        addRole(name='Anonymous')
        addRole(name='Issue')
        addRole(name='Msg')
        addRole(name='UV')
        user = self.db.user.create(username='user1', roles='User')
        anon = self.db.user.create(username='anonymous', roles='Anonymous')
        ui = self.db.user.create(username='user2', roles='Issue')
        uim = self.db.user.create(username='user3', roles='Issue,Msg')
        uimu = self.db.user.create(username='user4', roles='Issue,Msg,UV')
        iv = add(name="View", klass="issue")
        addToRole('User', iv)
        addToRole('Anonymous', iv)
        addToRole('Issue', iv)
        ms = add(name="Search", klass="msg")
        addToRole('User', ms)
        addToRole('Anonymous', ms)
        addToRole('Msg', ms)
        uv = add(name="View", klass="user")
        addToRole('User', uv)
        addToRole('UV', uv)
        self.assertEquals(has(anon, 'issue', 'messages'), 1)
        self.assertEquals(has(anon, 'issue', 'messages.author'), 0)
        self.assertEquals(has(anon, 'issue', 'messages.author.username'), 0)
        self.assertEquals(has(anon, 'issue', 'messages.recipients'), 0)
        self.assertEquals(has(anon, 'issue', 'messages.recipients.username'), 0)
        self.assertEquals(has(user, 'issue', 'messages'), 1)
        self.assertEquals(has(user, 'issue', 'messages.author'), 1)
        self.assertEquals(has(user, 'issue', 'messages.author.username'), 1)
        self.assertEquals(has(user, 'issue', 'messages.recipients'), 1)
        self.assertEquals(has(user, 'issue', 'messages.recipients.username'), 1)

        self.assertEquals(has(ui, 'issue', 'messages'), 0)
        self.assertEquals(has(ui, 'issue', 'messages.author'), 0)
        self.assertEquals(has(ui, 'issue', 'messages.author.username'), 0)
        self.assertEquals(has(ui, 'issue', 'messages.recipients'), 0)
        self.assertEquals(has(ui, 'issue', 'messages.recipients.username'), 0)

        self.assertEquals(has(uim, 'issue', 'messages'), 1)
        self.assertEquals(has(uim, 'issue', 'messages.author'), 0)
        self.assertEquals(has(uim, 'issue', 'messages.author.username'), 0)
        self.assertEquals(has(uim, 'issue', 'messages.recipients'), 0)
        self.assertEquals(has(uim, 'issue', 'messages.recipients.username'), 0)

        self.assertEquals(has(uimu, 'issue', 'messages'), 1)
        self.assertEquals(has(uimu, 'issue', 'messages.author'), 1)
        self.assertEquals(has(uimu, 'issue', 'messages.author.username'), 1)
        self.assertEquals(has(uimu, 'issue', 'messages.recipients'), 1)
        self.assertEquals(has(uimu, 'issue', 'messages.recipients.username'), 1)

    # roundup.password has its own built-in test, call it.
    def test_password(self):
        roundup.password.test()

# vim: set filetype=python sts=4 sw=4 et si :
