import re

substitutions = [ (re.compile('debian:\#(?P<id>\d+)'),
                   '<a href="http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=\g<id>">debian#\g<id></a>' ),
                  (re.compile('\#(?P<ws>\s*)(?P<id>\d+)'),
                   "<a href='issue\g<id>'>#\g<ws>\g<id></a>" ),
                  (re.compile('(?P<prews>^|\s+)(?P<revstr>(revision|rev|r)\s?)(?P<revision>[\da-fA-F]+)(?P<postws>\s+|$)'),
                   "\g<prews><a href='http://sourceforge.net/p/roundup/code/ci/\g<revision>'>\g<revstr>\g<revision></a>"),
                  ]

def local_replace(message):

    for cre, replacement in substitutions:
        message = cre.sub(replacement, message)

    return message


def init(instance):
    instance.registerUtil('localReplace', local_replace)


if "__main__" == __name__:
    print " debian:#222", local_replace(" debian:#222")
    print " #555", local_replace(" #555")
    print " revision 222", local_replace(" revision 222")
    print " r 222", local_replace(" r 222")
    print " wordthatendswithr 222", local_replace(" wordthatendswithr 222") # should fail
    print " references", local_replace(" references") # should fail
    print " too many spaces r  222", local_replace(" too many spaces r  222") # should fail
    print " r7140eb", local_replace(" r7140eb")
    print " rev7140eb ", local_replace(" rev7140eb")
    print "rev7140eb", local_replace("rev7140eb")
