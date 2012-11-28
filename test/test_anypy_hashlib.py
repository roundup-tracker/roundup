#! /usr/bin/env python
import unittest
import warnings

import roundup.anypy.hashlib_

class UntestableWarning(Warning):
    pass

# suppress deprecation warnings; -> warnings.filters[0]:
warnings.simplefilter(action='ignore',
                      category=DeprecationWarning,
                      append=0)

try:
    import sha
except:
    warnings.warn('sha module functions', UntestableWarning)
    sha = None

try:
    import md5
except:
    warnings.warn('md5 module functions', UntestableWarning)
    md5 = None

try:
    import hashlib
except:
    warnings.warn('hashlib module functions', UntestableWarning)
    hashlib = None

# preserve other warning filters set elsewhere:
del warnings.filters[0]

if not ((sha or md5) and hashlib):
    warnings.warn('anypy.hashlib_ continuity', UntestableWarning)

class TestCase_anypy_hashlib(unittest.TestCase):
    """test the hashlib compatibility layer"""

    data_for_test = (
           ('',
            'da39a3ee5e6b4b0d3255bfef95601890afd80709',
            'd41d8cd98f00b204e9800998ecf8427e'),
           ('Strange women lying in ponds distributing swords'
            ' is no basis for a system of government.',
            'da9b2b00466b00411038c057681fe67349f92d7d',
            'b71c5178d316ec446c25386f4857d4f9'),
           ('Ottos Mops hopst fort',
            'fdf7e6c54cf07108c86edd8d47c90450671c2c81',
            'a3dce74bee59ee92f1038263e5252500'),
           ('Dieser Satz kein Verb',
            '3030aded8a079b92043a39dc044a35443959dcdd',
            '2f20c69d514228011fb0d32e14dd5d80'),
           )

    # the following two are always excecuted: 
    def test_sha1_expected_anypy(self):
        """...anypy.hashlib_.sha1().hexdigest() yields expected results"""
        for src, SHA, MD5 in self.data_for_test:
            self.assertEqual(roundup.anypy.hashlib_.sha1(src).hexdigest(), SHA)

    def test_md5_expected_anypy(self):
        """...anypy.hashlib_.md5().hexdigest() yields expected results"""
        for src, SHA, MD5 in self.data_for_test:
            self.assertEqual(roundup.anypy.hashlib_.md5(src).hexdigest(), MD5)

    # execution depending on availability of modules: 
    if md5 and hashlib:
        def test_md5_continuity(self):
            """md5.md5().digest() == hashlib.md5().digest()"""
            if md5.md5 is hashlib.md5:
                return
            else:
                for s, i1, i2 in self.data_for_test:
                    self.assertEqual(md5.md5(s).digest(),
                                     hashlib.md5().digest())

    if md5:
        def test_md5_expected(self):
            """md5.md5().hexdigest() yields expected results"""
            for src, SHA, MD5 in self.data_for_test:
                self.assertEqual(md5.md5(src).hexdigest(), MD5)

        def test_md5_new_expected(self):
            """md5.new is md5.md5, or at least yields expected results"""
            if md5.new is md5.md5:
                return
            else:
                for src, SHA, MD5 in self.data_for_test:
                    self.assertEqual(md5.new(src).hexdigest(), MD5)

    if sha and hashlib:
        def test_sha1_continuity(self):
            """sha.sha().digest() == hashlib.sha1().digest()"""
            if sha.sha is hashlib.sha1:
                return
            else:
                for s in self.data_for_test:
                    self.assertEqual(sha.sha(s).digest(),
                                     hashlib.sha1().digest())

    if sha:
        def test_sha_expected(self):
            """sha.sha().hexdigest() yields expected results"""
            for src, SHA, MD5 in self.data_for_test:
                self.assertEqual(sha.sha(src).hexdigest(), SHA)

        def test_sha_new_expected(self):
            """sha.new is sha.sha, or at least yields expected results"""
            if sha.new is sha.sha:
                return
            else:
                for src, SHA, MD5 in self.data_for_test:
                    self.assertEqual(sha.new(src).hexdigest(), SHA)

    if hashlib:
        def test_sha1_expected_hashlib(self):
            """hashlib.sha1().hexdigest() yields expected results"""
            for src, SHA, MD5 in self.data_for_test:
                self.assertEqual(hashlib.sha1(src).hexdigest(), SHA)

        def test_md5_expected_hashlib(self):
            """hashlib.md5().hexdigest() yields expected results"""
            for src, SHA, MD5 in self.data_for_test:
                self.assertEqual(hashlib.md5(src).hexdigest(), MD5)

def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestCase_anypy_hashlib))
    return suite

if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    unittest.main(testRunner=runner)

# vim: ts=8 et sts=4 sw=4 si
