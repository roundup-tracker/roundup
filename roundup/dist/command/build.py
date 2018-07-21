#
# Copyright (C) 2009 Stefan Seefeld
# All rights reserved.
# For license terms see the file COPYING.txt.
#
from __future__ import print_function
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
        print('\n*** SOURCE WARNING: The MANIFEST file is missing!')
        return
    try:
        manifest = [l.strip() for l in f.readlines()]
    finally:
        f.close()
    err = set([line for line in manifest if not os.path.exists(line)])
    # ignore auto-generated files
    err = err - set(['roundup-admin', 'roundup-demo', 'roundup-gettext',
        'roundup-mailgw', 'roundup-server', 'roundup-xmlrpc-server'])
    if err:
        n = len(manifest)
        print('\n*** SOURCE WARNING: There are files missing (%d/%d found)!'%(
            n-len(err), n))
        print('Missing:', '\nMissing: '.join(err))

def build_message_files(command):
    """For each locale/*.po, build .mo file in target locale directory"""
    for (_src, _dst) in list_message_files():
        _build_dst = os.path.join("build", _dst)
        command.mkpath(os.path.dirname(_build_dst))
        command.announce("Compiling %s -> %s" % (_src, _build_dst))
        mo = msgfmt.Msgfmt(_src).get()
        open(_build_dst, 'wb').write(mo)


class build(base):

    def run(self):
        check_manifest()
        build_message_files(self)
        base.run(self)

