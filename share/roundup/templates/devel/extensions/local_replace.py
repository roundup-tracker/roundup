import re

hg_url_base = r'http://sourceforge.net/p/roundup/code/ci/'

substitutions = [ (re.compile(r'debian:\#(?P<id>\d+)'),
                   r'<a href="http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=\g<id>">debian#\g<id></a>' ),
                  (re.compile(r'\#(?P<ws>\s*)(?P<id>\d+)'),
                   r"<a href='issue\g<id>'>#\g<ws>\g<id></a>" ),
                  (re.compile(r'(?P<prews>^|\s+)issue(?P<ws>\s*)(?P<id>\d+)'),
                   r"\g<prews><a href='issue\g<id>'>issue\g<ws>\g<id></a>" ),
                  # matching the typical number:hash format of hg's own output
                  # and then use use hash instead of the number
                  (re.compile(r'(?P<prews>(^|\s+))(?P<revstr>(rev|hg))(?P<revnumber>\d+):(?P<refhash>[0-9a-fA-F]{12,40})(?P<post>\W+|$)'),
                      r'\g<prews><a href="' + hg_url_base + '\g<refhash>">\g<revstr>\g<revnumber>:\g<refhash></a>\g<post>'),
                  # matching hg revison number or hash
                  (re.compile(r'(?P<prews>(^|\s+))(?P<revstr>(revision|rev|r)\s?)(?P<revision>([1-9][0-9]*)|[0-9a-fA-F]{4,40})(?P<post>\W+|$)'),
                   r'\g<prews><a href="' + hg_url_base + '\g<revision>">\g<revstr>\g<revision></a>\g<post>'),
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
    quicktest("rev 012", False) # too short for a hg hash
    quicktest("rev 0123")
    quicktest("re140eb")
    quicktest(" r7140eb")
    quicktest(" rev7140eb ")
    quicktest("rev7140eb")
    quicktest("rev7140eb,")
    quicktest("rev4891:ad3d628e73f2")
    quicktest("hg4891:ad3d628e73f2")
