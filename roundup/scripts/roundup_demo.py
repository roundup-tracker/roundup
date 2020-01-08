#! /usr/bin/env python
#
# Copyright 2004 Richard Jones (richard@mechanicalcat.net)
#

DEFAULT_HOME = './demo'
DEFAULT_TEMPLATE = 'classic'


import sys


# --- patch sys.path to make sure 'import roundup' finds correct version
import os.path as osp

thisdir = osp.dirname(osp.abspath(__file__))
rootdir = osp.dirname(osp.dirname(thisdir))
if (osp.exists(thisdir + '/__init__.py') and
        osp.exists(rootdir + '/roundup/__init__.py')):
    # the script is located inside roundup source code
    sys.path.insert(0, rootdir)
# --/


from roundup import admin, configuration, demo, instance
from roundup.i18n import _
from roundup.anypy.my_input import my_input
from roundup import version_check

def run():
    home = DEFAULT_HOME
    template = DEFAULT_TEMPLATE
    nuke = sys.argv[-1] == 'nuke'
    # if there is no tracker in home, force nuke
    try:
        instance.open(home)
    except configuration.NoConfigError:
        nuke = 1
    # if we are to create the tracker, prompt for home
    if nuke:
        if len(sys.argv) > 2:
            backend = sys.argv[-2]
        else:
            backend = 'anydbm'
        # FIXME: i'd like to have an option to abort the tracker creation
        #   say, by entering a single dot.  but i cannot think of
        #   appropriate prompt for that.
        home = my_input(
            _('Enter directory path to create demo tracker [%s]: ') % home)
        if not home:
            home = DEFAULT_HOME
        templates = admin.AdminTool().listTemplates().keys()
        template = my_input(
            _('Enter tracker template to use (one of (%s)) [%s]: ') %
            (','.join(templates), template))
        if not template:
            template = DEFAULT_TEMPLATE
        # install
        demo.install_demo(home, backend,
                          admin.AdminTool().listTemplates()[template]['path'])
    # run
    demo.run_demo(home)


if __name__ == '__main__':
    run()

# vim: set et sts=4 sw=4 :
