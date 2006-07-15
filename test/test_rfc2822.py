from roundup.rfc2822 import decode_header, encode_header

import unittest, time
 
class RFC2822TestCase(unittest.TestCase):
    def testDecode(self):
        src = 'Re: [it_issue3] '\
            '=?ISO-8859-1?Q?Ren=E9s_[resp=3Dg=2Cstatus=3D?= '\
            '=?ISO-8859-1?Q?feedback]?='
        result = 'Re: [it_issue3] Ren\xc3\xa9s [resp=g,status=feedback]'
        self.assertEqual(decode_header(src), result)

        src = 'Re: [it_issue3]'\
            ' =?ISO-8859-1?Q?Ren=E9s_[resp=3Dg=2Cstatus=3D?=' \
            ' =?ISO-8859-1?Q?feedback]?='
        result = 'Re: [it_issue3] Ren\xc3\xa9s [resp=g,status=feedback]'
        self.assertEqual(decode_header(src), result)

    def testEncode(self):
        src = 'Re: [it_issue3] Ren\xc3\xa9s [status=feedback]'
        result = '=?utf-8?q?Re:_[it=5Fissue3]_Ren=C3=A9s_[status=3Dfeedback]?='
        self.assertEqual(encode_header(src), result)

        src = 'Was machen\xc3\xbc und Fragezeichen?'
        result = '=?utf-8?q?Was_machen=C3=BC_und_Fragezeichen=3F?='
        self.assertEqual(encode_header(src), result)

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(RFC2822TestCase))
    return suite
