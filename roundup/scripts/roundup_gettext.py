#! /usr/bin/env python
#
# Copyright 2004 Richard Jones (richard@mechanicalcat.net)

"""Extract translatable strings from tracker templates and detectors/extensions"""

from __future__ import print_function

import os

# --- patch sys.path to make sure 'import roundup' finds correct version
import os.path as osp
import sys
import tempfile

thisdir = osp.dirname(osp.abspath(__file__))
rootdir = osp.dirname(osp.dirname(thisdir))
if (osp.exists(thisdir + '/__init__.py') and
        osp.exists(rootdir + '/roundup/__init__.py')):
    # the script is located inside roundup source code
    sys.path.insert(0, rootdir)
# --/

from roundup.anypy import scandir_
from roundup import configuration
from roundup.cgi.TAL import talgettext
from roundup.i18n import _
from roundup.pygettext import TokenEater, make_escapes, tokenize

try:
    import polib
except ImportError:
    print(_("\nExtracting translatable strings only from html templates.\n"
            "Because the 'polib' module is missing, unable to extract\n"
            "translations from detectors or extensions.\n"
            "The 'polib' module can be installed with pip.\n"))
    polib = None


# from pygettext's main():
class Options:
    # constants
    GNU = 1
    SOLARIS = 2
    # defaults
    extractall = 0 # FIXME: currently this option has no effect at all.
    escape = 0
    keywords = ["_", "gettext", "ngettext", "ugettext"]
    outpath = ''
    outfile = ''
    writelocations = 1
    locationstyle = GNU
    verbose = 0
    width = 10
    excludefilename = ''
    docstrings = 0
    nodocstrings = {}
    toexclude = [] # TODO we should exclude all strings already found in some template


tokeneater_options = Options()

# name of message template file.
# i don't think this will ever need to be changed, but still...
TEMPLATE_FILE = "messages.pot"


def run():
    # return unless command line arguments contain single directory path
    if (len(sys.argv) != 2) or (sys.argv[1] in ("-h", "--help")):
        print(_("Usage: %(program)s <tracker home>") %
              {"program": sys.argv[0]})
        return

    home = os.path.abspath(sys.argv[1])
    # collect file paths of html templates from config
    config = configuration.CoreConfig(home)
    htmldir = config["TEMPLATES"]
    if os.path.isdir(htmldir):
        # glob is not used because i want to match file names
        # without case sensitivity, and that is easier done this way.
        htmlfiles = [e.name for e in os.scandir(htmldir)
                     if e.is_file()
                     and e.name.lower().endswith(".html")]
    else:
        htmlfiles = []
    # return if no html files found
    if not htmlfiles:
        print(_("No tracker templates found in directory %s") % htmldir)
        return
    # change to locale dir to have relative source references
    locale = os.path.join(home, "locale")
    if not os.path.isdir(locale):
        os.mkdir(locale)
    os.chdir(locale)

    # compute relative path to template directory from locale directory
    relpath = os.path.relpath(htmldir)

    # tweak sys.argv as this is the only way to tell talgettext what to do
    # Note: unix-style paths used instead of os.path.join deliberately
    sys.argv[1:] = ["-o", TEMPLATE_FILE] \
        + [relpath + "/" + filename for filename in htmlfiles]
    # run
    talgettext.main()

    if not polib:
        return

    # we have now everything from the templates in the TEMPLATE_FILE
    # now we search in home/detectors and home/extensions *.py files for
    # tokeneater_options.keywords
    # this is partly assembled from pygettext's main()
    make_escapes(not tokeneater_options.escape)

    pyfiles = []
    for source in ["detectors", "extensions"]:
        for root, _dirs, files in os.walk(os.path.join("..", source)):
            pyfiles.extend([os.path.join(root, f) for f in files if f.endswith(".py")])

    eater = TokenEater(tokeneater_options)

    for filename in pyfiles:
        eater.set_filename(filename)
        with open(filename, "r") as f:
            try:
                for token in tokenize.generate_tokens(f.readline):
                    eater(*token)
            except tokenize.TokenError as e:
                print('%s: %s, line %d, column %d' % (
                    e[0], filename, e[1][0], e[1][1]), file=sys.stderr)

    with tempfile.NamedTemporaryFile("w") as tf:
        eater.write(tf)
        tf.seek(0)
        p1 = polib.pofile(TEMPLATE_FILE)
        p2 = polib.pofile(tf.name)

        p2_msg_ids = {e.msgid for e in p2}
        for e in p1:
            if e.msgid in p2_msg_ids:
                p2_e = p2.find(e.msgid)
                e.occurrences.extend(p2_e.occurrences)
                p2_msg_ids.remove(e.msgid)

        for msgid in p2_msg_ids:
            p1.append(p2.find(msgid))
        p1.save()


if __name__ == "__main__":
    run()

# vim: set et sts=4 sw=4 :
