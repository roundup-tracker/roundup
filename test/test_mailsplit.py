# $Id: test_mailsplit.py,v 1.1 2001-08-03 07:18:22 richard Exp $

import unittest, cStringIO

from roundup.mailgw import parseContent

class MailsplitTestCase(unittest.TestCase):
    def testPreComment(self):
        s = '''
i will have to think about this later...not a 1.0.4 thing I don't
think...too much thought involved!

issue_tracker@bizarsoftware.com.au wrote:
> Hey, is there a reason why we can't just leave shop_domain and
> secure_domain blank and user the REQUEST.whatever_the_machine_name_is
> for most users? And then specify that if you're going to have
> secure_domain, you've got to have shop_domain too?
>
> -------
> nosy: richard, tejay
> ___________________________
> Roundup issue tracker
> issue_tracker@bizarsoftware.com.au
> http://dirk.adroit/cgi-bin/roundup.cgi/issue_tracker/

--
Terry Kerr (terry@bizarsoftware.com.au)
Bizar Software Pty Ltd (www.bizarsoftware.com.au)
Phone: +61 3 9563 4461
Fax: +61 3 9563 3856
ICQ: 79303381
'''
        summary, content = parseContent(s)
        print '\n====\n', summary
        print '====', content
        print '===='

    def testPostComment(self):
        s = '''
issue_tracker@bizarsoftware.com.au wrote:
> Hey, is there a reason why we can't just leave shop_domain and
> secure_domain blank and user the REQUEST.whatever_the_machine_name_is
> for most users? And then specify that if you're going to have
> secure_domain, you've got to have shop_domain too?
>
> -------
> nosy: richard, tejay
> ___________________________
> Roundup issue tracker
> issue_tracker@bizarsoftware.com.au
> http://dirk.adroit/cgi-bin/roundup.cgi/issue_tracker/

i will have to think about this later...not a 1.0.4 thing I don't
think...too much thought involved!

--
Terry Kerr (terry@bizarsoftware.com.au)
Bizar Software Pty Ltd (www.bizarsoftware.com.au)
Phone: +61 3 9563 4461
Fax: +61 3 9563 3856
ICQ: 79303381
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
#
#
# vim: set filetype=python ts=4 sw=4 et si
