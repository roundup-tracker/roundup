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
# 
# $Id: test_mailsplit.py,v 1.10 2002-04-23 16:18:18 rochecompaan Exp $

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

def suite():
   return unittest.makeSuite(MailsplitTestCase, 'test')


#
# $Log: not supported by cvs2svn $
# Revision 1.9  2002/01/10 06:19:20  richard
# followup lines directly after a quoted section were being eaten.
#
# Revision 1.8  2001/10/28 23:22:28  richard
# fixed bug #474749 ] Indentations lost
#
# Revision 1.7  2001/10/23 00:57:32  richard
# Removed debug print from mailsplit test.
#
# Revision 1.6  2001/10/21 03:35:13  richard
# bug #473125: Paragraph in e-mails
#
# Revision 1.5  2001/08/07 00:24:43  richard
# stupid typo
#
# Revision 1.4  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.3  2001/08/05 07:06:25  richard
# removed some print statements
#
# Revision 1.2  2001/08/03 07:23:09  richard
# er, removed the innocent from the the code :)
#
# Revision 1.1  2001/08/03 07:18:22  richard
# Implemented correct mail splitting (was taking a shortcut). Added unit
# tests. Also snips signatures now too.
#
#
#
# vim: set filetype=python ts=4 sw=4 et si
