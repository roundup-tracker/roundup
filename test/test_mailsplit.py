# $Id: test_mailsplit.py,v 1.2 2001-08-03 07:23:09 richard Exp $

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
        summary, content = parseContent(s)
        print '\n====\n', summary
        print '====', content
        print '===='

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
        summary, content = parseContent(s)
        print '\n====\n', summary
        print '====', content
        print '===='

    def testSimple(self):
        s = '''testing'''
        summary, content = parseContent(s)
        print '\n====\n', summary
        print '====', content
        print '===='

    def testEmpty(self):
        s = ''
        summary, content = parseContent(s)
        print '\n====\n', summary
        print '====', content
        print '===='

def suite():
   return unittest.makeSuite(MailsplitTestCase, 'test')


#
# $Log: not supported by cvs2svn $
# Revision 1.1  2001/08/03 07:18:22  richard
# Implemented correct mail splitting (was taking a shortcut). Added unit
# tests. Also snips signatures now too.
#
#
#
# vim: set filetype=python ts=4 sw=4 et si
