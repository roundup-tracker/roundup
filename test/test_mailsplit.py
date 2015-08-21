#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.

import unittest, cStringIO

from roundup.mailgw import parseContent

class MailsplitTestCase(unittest.TestCase):
    def testPreComment(self):
        s = '''
blah blah blah blah... blah blah? blah blah blah blah blah. blah blah blah
blah blah blah blah blah blah blah blah blah blah blah!

issue_tracker@foo.com wrote:
> blah blah blah blahblah blahblah blahblah blah blah blah blah blah blah
> blah blah blah blah blah blah blah blah blah?  blah blah blah blah blah
> blah blah blah blah blah blah blah...  blah blah blah blah.  blah blah
> blah blah blah blah?  blah blah blah blah blah blah!  blah blah!
>
> -------
> nosy: userfoo, userken
> _________________________________________________
> Roundup issue tracker
> issue_tracker@foo.com
> http://foo.com/cgi-bin/roundup.cgi/issue_tracker/

--
blah blah blah signature
userfoo@foo.com
'''
        summary, content = parseContent(s, 0, 0)
        self.assertEqual(summary, 'blah blah blah blah... blah blah? blah blah blah blah blah. blah blah blah')
        self.assertEqual(content, 'blah blah blah blah... blah blah? blah blah blah blah blah. blah blah blah\nblah blah blah blah blah blah blah blah blah blah blah!')


    def testPostComment(self):
        s = '''
issue_tracker@foo.com wrote:
> blah blah blah blahblah blahblah blahblah blah blah blah blah blah
> blah
> blah blah blah blah blah blah blah blah blah?  blah blah blah blah
> blah
> blah blah blah blah blah blah blah...  blah blah blah blah.  blah
> blah
> blah blah blah blah?  blah blah blah blah blah blah!  blah blah!
>
> -------
> nosy: userfoo, userken
> _________________________________________________
> Roundup issue tracker
> issue_tracker@foo.com
> http://foo.com/cgi-bin/roundup.cgi/issue_tracker/

blah blah blah blah... blah blah? blah blah blah blah blah. blah blah blah
blah blah blah blah blah blah blah blah blah blah blah!

--
blah blah blah signature
userfoo@foo.com
'''
        summary, content = parseContent(s, 0, 0)
        self.assertEqual(summary, 'blah blah blah blah... blah blah? blah blah blah blah blah. blah blah blah')
        self.assertEqual(content, 'blah blah blah blah... blah blah? blah blah blah blah blah. blah blah blah\nblah blah blah blah blah blah blah blah blah blah blah!')


    def testKeepCitation(self):
        s = '''
blah blah blah blah... blah blah? blah blah blah blah blah. blah blah blah
blah blah blah blah blah blah blah blah blah blah blah!

issue_tracker@foo.com wrote:
> blah blah blah blahblah blahblah blahblah blah blah blah blah blah blah
> blah blah blah blah blah blah blah blah blah?  blah blah blah blah blah
> blah blah blah blah blah blah blah...  blah blah blah blah.  blah blah
> blah blah blah blah?  blah blah blah blah blah blah!  blah blah!
>
> -------
> nosy: userfoo, userken
> _________________________________________________
> Roundup issue tracker
> issue_tracker@foo.com
> http://foo.com/cgi-bin/roundup.cgi/issue_tracker/

--
blah blah blah signature
userfoo@foo.com
'''
        summary, content = parseContent(s, 1, 0)
        self.assertEqual(summary, 'blah blah blah blah... blah blah? blah blah blah blah blah. blah blah blah')
        self.assertEqual(content, '''\
blah blah blah blah... blah blah? blah blah blah blah blah. blah blah blah
blah blah blah blah blah blah blah blah blah blah blah!

issue_tracker@foo.com wrote:
> blah blah blah blahblah blahblah blahblah blah blah blah blah blah blah
> blah blah blah blah blah blah blah blah blah?  blah blah blah blah blah
> blah blah blah blah blah blah blah...  blah blah blah blah.  blah blah
> blah blah blah blah?  blah blah blah blah blah blah!  blah blah!
>
> -------
> nosy: userfoo, userken
> _________________________________________________
> Roundup issue tracker
> issue_tracker@foo.com
> http://foo.com/cgi-bin/roundup.cgi/issue_tracker/''')


    def testKeepBody(self):
        s = '''
blah blah blah blah... blah blah? blah blah blah blah blah. blah blah blah
blah blah blah blah blah blah blah blah blah blah blah!

issue_tracker@foo.com wrote:
> blah blah blah blahblah blahblah blahblah blah blah blah blah blah blah
> blah blah blah blah blah blah blah blah blah?  blah blah blah blah blah
> blah blah blah blah blah blah blah...  blah blah blah blah.  blah blah
> blah blah blah blah?  blah blah blah blah blah blah!  blah blah!
>
> -------
> nosy: userfoo, userken
> _________________________________________________
> Roundup issue tracker
> issue_tracker@foo.com
> http://foo.com/cgi-bin/roundup.cgi/issue_tracker/

--
blah blah blah signature
userfoo@foo.com
'''
        summary, content = parseContent(s, 0, 1)
        self.assertEqual(summary, 'blah blah blah blah... blah blah? blah blah blah blah blah. blah blah blah')
        self.assertEqual(content, '''
blah blah blah blah... blah blah? blah blah blah blah blah. blah blah blah
blah blah blah blah blah blah blah blah blah blah blah!

issue_tracker@foo.com wrote:
> blah blah blah blahblah blahblah blahblah blah blah blah blah blah blah
> blah blah blah blah blah blah blah blah blah?  blah blah blah blah blah
> blah blah blah blah blah blah blah...  blah blah blah blah.  blah blah
> blah blah blah blah?  blah blah blah blah blah blah!  blah blah!
>
> -------
> nosy: userfoo, userken
> _________________________________________________
> Roundup issue tracker
> issue_tracker@foo.com
> http://foo.com/cgi-bin/roundup.cgi/issue_tracker/

--
blah blah blah signature
userfoo@foo.com
''')

    def testAllQuoted(self):
        s = '\nissue_tracker@foo.com wrote:\n> testing\n'
        summary, content = parseContent(s, 0, 1)
        self.assertEqual(summary, '')
        self.assertEqual(content, s)

    def testSimple(self):
        s = '''testing'''
        summary, content = parseContent(s, 0, 0)
        self.assertEqual(summary, 'testing')
        self.assertEqual(content, 'testing')

    def testParagraphs(self):
        s = '''testing\n\ntesting\n\ntesting'''
        summary, content = parseContent(s, 0, 0)
        self.assertEqual(summary, 'testing')
        self.assertEqual(content, 'testing\n\ntesting\n\ntesting')

    def testSimpleFollowup(self):
        s = '''>hello\ntesting'''
        summary, content = parseContent(s, 0, 0)
        self.assertEqual(summary, 'testing')
        self.assertEqual(content, 'testing')

    def testSimpleFollowupParas(self):
        s = '''>hello\ntesting\n\ntesting\n\ntesting'''
        summary, content = parseContent(s, 0, 0)
        self.assertEqual(summary, 'testing')
        self.assertEqual(content, 'testing\n\ntesting\n\ntesting')

    def testEmpty(self):
        s = ''
        summary, content = parseContent(s, 0, 0)
        self.assertEqual(summary, '')
        self.assertEqual(content, '')

    def testIndentationSummary(self):
        s = '    Four space indent.\n\n    Four space indent.\nNo indent.'
        summary, content = parseContent(s, 0, 0)
        self.assertEqual(summary, '    Four space indent.')

    def testIndentationContent(self):
        s = '    Four space indent.\n\n    Four space indent.\nNo indent.'
        summary, content = parseContent(s, 0, 0)
        self.assertEqual(content, s)

    def testMultilineSummary(self):
        s = 'This is a long sentence that would normally\nbe split. More words.'
        summary, content = parseContent(s, 0, 0)
        self.assertEqual(summary, 'This is a long sentence that would '
            'normally\nbe split.')

    def testKeepMultipleHyphens(self):
        body = '''Testing, testing.

----
Testing, testing.'''
        summary, content = parseContent(body, 1, 0)
        self.assertEqual(body, content)

# vim: set filetype=python ts=4 sw=4 et si
