#
# Copyright (C) 2009 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#
from roundup import msgfmt
from distutils.command.build import build as base
import os
from glob import glob

def list_message_files(suffix=".po"):
    """Return list of all found message files and their intallation paths"""
    _files = glob("locale/*" + suffix)
    _list = []
    for _file in _files:
        # basename (without extension) is a locale name
        _locale = os.path.splitext(os.path.basename(_file))[0]
        _list.append((_file, os.path.join(
            "share", "locale", _locale, "LC_MESSAGES", "roundup.mo")))
    return _list

def check_manifest():
    """Check that the files listed in the MANIFEST are present when the
    source is unpacked.
    """
    try:
        f = open('MANIFEST')
    except:
        print '\n*** SOURCE WARNING: The MANIFEST file is missing!'
        return
    try:
        manifest = [l.strip() for l in f.readlines()]
    finally:
        f.close()
    err = [line for line in manifest if not os.path.exists(line)]
    err.sort()
    # ignore auto-generated files
    if err == ['roundup-admin', 'roundup-demo', 'roundup-gettext',
            'roundup-mailgw', 'roundup-server']:
        err = []
    if err:
        n = len(manifest)
        print '\n*** SOURCE WARNING: There are files missing (%d/%d found)!'%(
            n-len(err), n)
        print 'Missing:', '\nMissing: '.join(err)


class build(base):

    def build_message_files(self):
        """For each locale/*.po, build .mo file in target locale directory"""
        for (_src, _dst) in list_message_files():
            _build_dst = os.path.join("build", _dst)
            self.mkpath(os.path.dirname(_build_dst))
            self.announce("Compiling %s -> %s" % (_src, _build_dst))
            msgfmt.make(_src, _build_dst)

    def run(self):
        check_manifest()
        self.build_message_files()
        base.run(self)

