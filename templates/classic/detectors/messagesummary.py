#$Id: messagesummary.py,v 1.1 2003-04-17 03:26:38 richard Exp $

from roundup.mailgw import parseContent

def summarygenerator(db, cl, nodeid, newvalues):
    ''' If the message doesn't have a summary, make one for it.
    '''
    if newvalues.has_key('summary') or not newvalues.has_key('content'):
        return

    summary, content = parseContent(newvalues['content'], 1, 1)
    newvalues['summary'] = summary


def init(db):
    # fire before changes are made
    db.msg.audit('create', summarygenerator)

# vim: set filetype=python ts=4 sw=4 et si
