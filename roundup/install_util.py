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
# $Id: install_util.py,v 1.11 2006-01-25 03:11:43 richard Exp $

"""Support module to generate and check fingerprints of installed files.
"""
__docformat__ = 'restructuredtext'

import os, sha, shutil

sgml_file_types = [".xml", ".ent", ".html"]
hash_file_types = [".py", ".sh", ".conf", ".cgi"]
slast_file_types = [".css"]

digested_file_types = sgml_file_types + hash_file_types + slast_file_types

def extractFingerprint(lines):
    # get fingerprint from last line
    if lines[-1].startswith("#SHA: "):
        # handle .py/.sh comment
        return lines[-1][6:].strip()
    elif lines[-1].startswith("<!-- SHA: "):
        # handle xml/html files
        fingerprint = lines[-1][10:]
        fingerprint = fingerprint.replace('-->', '')
        return fingerprint.strip()
    elif lines[-1].startswith("/* SHA: "):
        # handle css files
        fingerprint = lines[-1][8:]
        fingerprint = fingerprint.replace('*/', '')
        return fingerprint.strip()
    return None

def checkDigest(filename):
    """Read file, check for valid fingerprint, return TRUE if ok"""
    # open and read file
    inp = open(filename, "r")
    lines = inp.readlines()
    inp.close()

    fingerprint = extractFingerprint(lines)
    if fingerprint is None:
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
        lines = data.splitlines()
        # if the file is coming from an installed tracker being used as a
        # template, then we will want to re-calculate the SHA
        fingerprint = extractFingerprint(lines)
        if fingerprint is not None:
            data = '\n'.join(lines[:-1]) + '\n'
        self.file.write(data)
        self.digest.update(data)

    def close(self):
        file, ext = os.path.splitext(self.filename)

        if ext in sgml_file_types:
            self.file.write("<!-- SHA: %s -->\n" % (self.digest.hexdigest(),))
        elif ext in hash_file_types:
            self.file.write("#SHA: %s\n" % (self.digest.hexdigest(),))
        elif ext in slast_file_types:
            self.file.write("/* SHA: %s */\n" % (self.digest.hexdigest(),))

        self.file.close()


def copyDigestedFile(src, dst, copystat=1):
    """ Copy data from `src` to `dst`, adding a fingerprint to `dst`.
        If `copystat` is true, the file status is copied, too
        (like shutil.copy2).
    """
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))

    dummy, ext = os.path.splitext(src)
    if ext not in digested_file_types:
        if copystat:
            return shutil.copy2(src, dst)
        else:
            return shutil.copyfile(src, dst)

    fsrc = None
    fdst = None
    try:
        fsrc = open(src, 'r')
        fdst = DigestFile(dst)
        shutil.copyfileobj(fsrc, fdst)
    finally:
        if fdst: fdst.close()
        if fsrc: fsrc.close()

    if copystat: shutil.copystat(src, dst)


def test():
    import sys

    testdata = open(sys.argv[0], 'r').read()

    for ext in digested_file_types:
        testfile = "__digest_test" + ext

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

# vim: set filetype=python ts=4 sw=4 et si
