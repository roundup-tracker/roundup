class StringFragmentCmpHelper:
    def compareStringFragments(self, s, fragments):
        """Compare a string agains a list of fragments where a tuple denotes a
        set of alternatives
        """
        pos = 0
        for frag in fragments:
            if type(frag) != tuple:
                self.assertEqual(s[pos:pos + len(frag)], frag)
                pos += len(frag)
            else:
                found = False
                for alt in frag:
                    if s[pos:pos + len(alt)] == alt:
                        pos += len(alt)
                        found = True
                        break

                if not found:
                    l = max(map(len, frag))
                    raise AssertionError('%s != %s' %
                                         (repr(s[pos:pos + l]), str(frag)))
        self.assertEqual(s[pos:], '')
