import re

substitutions = [ (re.compile('debian:\#(?P<id>\d+)'),
                   '<a href="http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=\g<id>">debian#\g<id></a>' ),
                  (re.compile('\#(?P<ws>\s*)(?P<id>\d+)'),
                   "<a href='issue\g<id>'>#\g<ws>\g<id></a>" ),
                  (re.compile('(?P<prews>^|\s+)issue(?P<ws>\s*)(?P<id>\d+)'),
                   "\g<prews><a href='issue\g<id>'>issue\g<ws>\g<id></a>" ),
                  (re.compile('(?P<prews>^|\s+)(?P<revstr>(revision|rev|r)\s?)(?P<revision>[1-9a-fA-F][0-9a-fA-F]*)(?P<post>\W+|$)'),
                   "\g<prews><a href='http://sourceforge.net/p/roundup/code/ci/\g<revision>'>\g<revstr>\g<revision></a>\g<post>"),
                  ]

def local_replace(message):

    for cre, replacement in substitutions:
        message = cre.sub(replacement, message)

    return message


def init(instance):
    instance.registerUtil('localReplace', local_replace)

def quicktest(msgstr, should_replace = True):
    if not should_replace:
        print "(no)",
    print "'%s' -> '%s'" % (msgstr, local_replace(msgstr))

if "__main__" == __name__:
    print "Replacement examples. '(no)' should result in no replacement:"
    quicktest(" debian:#222")
    quicktest(" #555")
    quicktest("issue333")
    quicktest(" revision 222")
    quicktest(" r 222")
    quicktest(" wordthatendswithr 222", False)
    quicktest(" references", False)
    quicktest(" too many spaces r  222", False)
    quicktest("re-evaluate", False)
    quicktest("rex140eb", False)
    quicktest("re140eb")
    quicktest(" r7140eb")
    quicktest(" rev7140eb ")
    quicktest("rev7140eb")
    quicktest("rev7140eb,")
