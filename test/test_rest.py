import unittest
import os
import shutil
import errno

from roundup.cgi.exceptions import *
from roundup import password, hyperdb
from roundup.rest import RestfulInstance
from roundup.backends import list_backends
from roundup.cgi import client

import db_test_base

NEEDS_INSTANCE = 1


class TestCase(unittest.TestCase):

    backend = None

    def setUp(self):
        self.dirname = '_test_rest'
        # set up and open a tracker
        self.instance = db_test_base.setupTracker(self.dirname, self.backend)

        # open the database
        self.db = self.instance.open('admin')

        # Get user id (user4 maybe). Used later to get data from db.
        self.joeid = self.db.user.create(
            username='joe',
            password=password.Password('random'),
            address='random@home.org',
            realname='Joe Random',
            roles='User'
        )

        self.db.commit()
        self.db.close()
        self.db = self.instance.open('joe')

        self.db.tx_Source = 'web'

        self.db.issue.addprop(tx_Source=hyperdb.String())
        self.db.msg.addprop(tx_Source=hyperdb.String())

        self.db.post_init()

        thisdir = os.path.dirname(__file__)
        vars = {}
        execfile(os.path.join(thisdir, "tx_Source_detector.py"), vars)
        vars['init'](self.db)

        env = {
            'PATH_INFO': 'http://localhost/rounduptest/rest/',
            'HTTP_HOST': 'localhost',
            'TRACKER_NAME': 'rounduptest'
        }
        dummy_client = client.Client(self.instance, None, env, [], None)

        self.server = RestfulInstance(dummy_client, self.db)

    def tearDown(self):
        self.db.close()
        try:
            shutil.rmtree(self.dirname)
        except OSError, error:
            if error.errno not in (errno.ENOENT, errno.ESRCH):
                raise

    def testGet(self):
        """
        Retrieve all three users
        obtain data for 'joe'
        """
        # Retrieve all three users.
        code, results = self.server.get_collection('user', {})
        self.assertEqual(code, 200)
        self.assertEqual(len(results), 3)

        # Obtain data for 'joe'.
        code, results = self.server.get_element('user', self.joeid, {})
        self.assertEqual(code, 200)
        self.assertEqual(results['attributes']['username'], 'joe')
        self.assertEqual(results['attributes']['realname'], 'Joe Random')

        # Obtain data for 'joe'.
        code, results = self.server.get_attribute(
            'user', self.joeid, 'username', {}
        )
        self.assertEqual(code, 200)
        self.assertEqual(results['data'], 'joe')

    def testPut(self):
        """
        Change joe's 'realname'
        Check if we can't change admin's detail
        """
        # change Joe's realname via attribute uri
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('data', 'Joe Doe Doe')
        ]
        code, results = self.server.put_attribute(
            'user', self.joeid, 'realname', form
        )
        code, results = self.server.get_attribute(
            'user', self.joeid, 'realname', {}
        )
        self.assertEqual(code, 200)
        self.assertEqual(results['data'], 'Joe Doe Doe')

        # Reset joe's 'realname'.
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('realname', 'Joe Doe')
        ]
        code, results = self.server.put_element('user', self.joeid, form)
        code, results = self.server.get_element('user', self.joeid, {})
        self.assertEqual(code, 200)
        self.assertEqual(results['attributes']['realname'], 'Joe Doe')

        # check we can't change admin's details
        self.assertRaises(
            Unauthorised,
            self.server.put_element, 'user', '1', form
        )

    def testPost(self):
        """
        Post a new issue with title: foo
        Verify the information of the created issue
        """
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('title', 'foo')
        ]
        code, results = self.server.post_collection('issue', form)
        self.assertEqual(code, 201)
        issueid = results['id']
        code, results = self.server.get_element('issue', issueid, {})
        self.assertEqual(code, 200)
        self.assertEqual(results['attributes']['title'], 'foo')
        self.assertEqual(self.db.issue.get(issueid, "tx_Source"), 'web')

    def testPostFile(self):
        """
        Post a new file with content: hello\r\nthere
        Verify the information of the created file
        """
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('content', 'hello\r\nthere')
        ]
        code, results = self.server.post_collection('file', form)
        self.assertEqual(code, 201)
        fileid = results['id']
        code, results = self.server.get_element('file', fileid, {})
        self.assertEqual(code, 200)
        self.assertEqual(results['attributes']['content'], 'hello\r\nthere')

    def testAuthDeniedPut(self):
        """
        Test unauthorized PUT request
        """
        # Wrong permissions (caught by roundup security module).
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('realname', 'someone')
        ]
        self.assertRaises(
            Unauthorised,
            self.server.put_element, 'user', '1', form
        )

    def testAuthDeniedPost(self):
        """
        Test unauthorized POST request
        """
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('username', 'blah')
        ]
        self.assertRaises(
            Unauthorised,
            self.server.post_collection, 'user', form
        )

    def testAuthAllowedPut(self):
        """
        Test authorized PUT request
        """
        self.db.setCurrentUser('admin')
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('realname', 'someone')
        ]
        try:
            try:
                self.server.put_element('user', '2', form)
            except Unauthorised, err:
                self.fail('raised %s' % err)
        finally:
            self.db.setCurrentUser('joe')

    def testAuthAllowedPost(self):
        """
        Test authorized POST request
        """
        self.db.setCurrentUser('admin')
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('username', 'blah')
        ]
        try:
            try:
                self.server.post_collection('user', form)
            except Unauthorised, err:
                self.fail('raised %s' % err)
        finally:
            self.db.setCurrentUser('joe')

    def testDeleteAttributeUri(self):
        """
        Test Delete an attribute
        """
        # create a new issue with userid 1 in the nosy list
        issue_id = self.db.issue.create(title='foo', nosy=['1'])

        # remove the title and nosy
        code, results = self.server.delete_attribute(
            'issue', issue_id, 'title', {}
        )
        self.assertEqual(code, 200)

        code, results = self.server.delete_attribute(
            'issue', issue_id, 'nosy', {}
        )
        self.assertEqual(code, 200)

        # verify the result
        code, results = self.server.get_element('issue', issue_id, {})
        self.assertEqual(code, 200)
        self.assertEqual(len(results['attributes']['nosy']), 0)
        self.assertListEqual(results['attributes']['nosy'], [])
        self.assertEqual(results['attributes']['title'], None)

    def testPatchAdd(self):
        """
        Test Patch op 'Add'
        """
        # create a new issue with userid 1 in the nosy list
        issue_id = self.db.issue.create(title='foo', nosy=['1'])

        # add userid 2 to the nosy list
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('op', 'add'),
            cgi.MiniFieldStorage('nosy', '2')
        ]
        code, results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(code, 200)

        # verify the result
        code, results = self.server.get_element('issue', issue_id, {})
        self.assertEqual(code, 200)
        self.assertEqual(len(results['attributes']['nosy']), 2)
        self.assertListEqual(results['attributes']['nosy'], ['1', '2'])

    def testPatchReplace(self):
        """
        Test Patch op 'Replace'
        """
        # create a new issue with userid 1 in the nosy list and status = 1
        issue_id = self.db.issue.create(title='foo', nosy=['1'], status='1')

        # replace userid 2 to the nosy list and status = 3
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('op', 'replace'),
            cgi.MiniFieldStorage('nosy', '2'),
            cgi.MiniFieldStorage('status', '3')
        ]
        code, results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(code, 200)

        # verify the result
        code, results = self.server.get_element('issue', issue_id, {})
        self.assertEqual(code, 200)
        self.assertEqual(results['attributes']['status'], '3')
        self.assertEqual(len(results['attributes']['nosy']), 1)
        self.assertListEqual(results['attributes']['nosy'], ['2'])

    def testPatchRemoveAll(self):
        """
        Test Patch Action 'Remove'
        """
        # create a new issue with userid 1 in the nosy list
        issue_id = self.db.issue.create(title='foo', nosy=['1', '2'])

        # remove the nosy list and the title
        form = cgi.FieldStorage()
        form.list = [
            cgi.MiniFieldStorage('op', 'remove'),
            cgi.MiniFieldStorage('nosy', ''),
            cgi.MiniFieldStorage('title', '')
        ]
        code, results = self.server.patch_element('issue', issue_id, form)
        self.assertEqual(code, 200)

        # verify the result
        code, results = self.server.get_element('issue', issue_id, {})
        self.assertEqual(code, 200)
        self.assertEqual(results['attributes']['title'], None)
        self.assertEqual(len(results['attributes']['nosy']), 0)
        self.assertEqual(results['attributes']['nosy'], [])


def test_suite():
    suite = unittest.TestSuite()
    for l in list_backends():
        dct = dict(backend=l)
        subcls = type(TestCase)('TestCase_%s' % l, (TestCase,), dct)
        suite.addTest(unittest.makeSuite(subcls))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)
