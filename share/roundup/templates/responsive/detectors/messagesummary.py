from roundup.mailgw import parseContent

def summarygenerator(db, cl, nodeid, newvalues):
    ''' If the message doesn't have a summary, make one for it.
    '''
    if newvalues.has_key('summary') or not newvalues.has_key('content'):
        return

    summary, content = parseContent(newvalues['content'], config=db.config)
    newvalues['summary'] = summary


def init(db):
    # fire before changes are made
    db.msg.audit('create', summarygenerator)

# vim: set filetype=python ts=4 sw=4 et si
#SHA: 538f90cb7f4eb63f77eca252b87afbe037d29c48
