#! /usr/bin/env python
#
# Copyright 2004 Richard Jones (richard@mechanicalcat.net)

"""Extract translatable strings from tracker templates"""

from __future__ import print_function
import os
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


from roundup.i18n import _
from roundup.cgi.TAL import talgettext

# name of message template file.
# i don't think this will ever need to be changed, but still...
TEMPLATE_FILE = "messages.pot"


def run():
    # return unless command line arguments contain single directory path
    if (len(sys.argv) != 2) or (sys.argv[1] in ("-h", "--help")):
        print(_("Usage: %(program)s <tracker home>") %
              {"program": sys.argv[0]})
        return
    # collect file paths of html templates
    home = os.path.abspath(sys.argv[1])
    htmldir = os.path.join(home, "html")
    if os.path.isdir(htmldir):
        # glob is not used because i want to match file names
        # without case sensitivity, and that is easier done this way.
        htmlfiles = [filename for filename in os.listdir(htmldir)
                     if os.path.isfile(os.path.join(htmldir, filename))
                     and filename.lower().endswith(".html")]
    else:
        htmlfiles = []
    # return if no html files found
    if not htmlfiles:
        print(_("No tracker templates found in directory %s") % home)
        return
    # change to locale dir to have relative source references
    locale = os.path.join(home, "locale")
    if not os.path.isdir(locale):
        os.mkdir(locale)
    os.chdir(locale)
    # tweak sys.argv as this is the only way to tell talgettext what to do
    # Note: unix-style paths used instead of os.path.join deliberately
    sys.argv[1:] = ["-o", TEMPLATE_FILE] \
        + ["../html/" + filename for filename in htmlfiles]
    # run
    talgettext.main()


if __name__ == "__main__":
    run()

# vim: set et sts=4 sw=4 :
