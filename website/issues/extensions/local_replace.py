import re

substitutions = [ (re.compile('debian:\#(?P<id>\d+)'),
                   '<a href="http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=\g<id>">debian#\g<id></a>' ),
                  (re.compile('\#(?P<ws>\s*)(?P<id>\d+)'),
                   "<a href='issue\g<id>'>#\g<ws>\g<id></a>" ),
                  (re.compile('(?P<prews>\s+)revision(?P<ws>\s*)(?P<revision>\d+)'),
                   "\g<prews><a href='http://svn.roundup-tracker.org/viewvc/roundup?view=rev&rev=\g<revision>'>revision\g<ws>\g<revision></a>"),
                  (re.compile('(?P<prews>\s+)rev(?P<ws>\s*)(?P<revision>\d+)'),
                   "\g<prews><a href='http://svn.roundup-tracker.org/viewvc/roundup?view=rev&rev=\g<revision>'>rev\g<ws>\g<revision></a>"),
                  (re.compile('(?P<prews>\s+)(?P<revstr>r|r\s+)(?P<revision>\d+)'),
                   "\g<prews><a href='http://svn.roundup-tracker.org/viewvc/roundup?view=rev&rev=\g<revision>'>\g<revstr>\g<revision></a>"),
                  ]

def local_replace(message):

    for cre, replacement in substitutions:
        message = cre.sub(replacement, message)

    return message
        
    
    
def init(instance):
    instance.registerUtil('localReplace', local_replace)
    

if "__main__" == __name__:
    print " debian:#222", local_replace(" debian:#222")
    print " revision 222", local_replace(" revision 222")
    print " wordthatendswithr 222", local_replace(" wordthatendswithr 222")
    print " r222", local_replace(" r222")
    print " r 222", local_replace(" r 222")
    print " #555", local_replace(" #555")
    
