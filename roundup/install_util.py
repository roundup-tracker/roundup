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
# $Id: install_util.py,v 1.1 2001-11-12 22:26:32 jhermann Exp $

import os, sha


def checkDigest(filename):
    """Read file, check for valid fingerprint, return TRUE if ok"""
    # open and read file
    inp = open(filename, "r")
    lines = inp.readlines()
    inp.close()

    # get fingerprint from last line
    if lines[-1][:6] == "#SHA: ":
        # handle .py/.sh comment
        fingerprint = lines[-1][6:].strip()
    elif lines[-1][:10] == "<!-- SHA: ":
        # handle xml files
        fingerprint = lines[-1][10:]
        fingerprint = fingerprint.replace('-->', '')
        fingerprint = fingerprint.strip()
    else:
        return 0
    del lines[-1]

    # calculate current digest
    digest = sha.new()
    for line in lines:
        digest.update(line)

    # compare current to stored digest
    return fingerprint == digest.hexdigest()


class DigestFile:
    """ A class that you can use like open() and that calculates
        and writes a SHA digest to the target file.
    """

    def __init__(self, filename):
        self.filename = filename
        self.digest = sha.new()
        self.file = open(self.filename, "w")

    def write(self, data):
        self.file.write(data)
        self.digest.update(data)

    def close(self):
        file, ext = os.path.splitext(self.filename)

        if ext in [".xml", ".ent"]:
            self.file.write("<!-- SHA: %s -->\n" % (self.digest.hexdigest(),))
        elif ext in [".py", ".sh", ".conf", '']:
            self.file.write("#SHA: %s\n" % (self.digest.hexdigest(),))

        self.file.close()


def test():
    import sys

    testdata = open(sys.argv[0], 'r').read()
    testfile = "digest_test.py"

    out = DigestFile(testfile)
    out.write(testdata)
    out.close()

    assert checkDigest(testfile), "digest ok w/o modification"

    mod = open(testfile, 'r+')
    mod.seek(0)
    mod.write('# changed!')
    mod.close()

    assert not checkDigest(testfile), "digest fails after modification"

    os.remove(testfile)


if __name__ == '__main__':
    test()

#
# $Log: not supported by cvs2svn $

