#$Id: nosyreaction.py,v 1.1 2001-07-22 12:09:32 richard Exp $

def nosyreaction(db, cl, nodeid, oldvalues):
    ''' A standard detector is provided that watches for additions to the
        "messages" property.
        
        When a new message is added, the detector sends it to all the users on
        the "nosy" list for the issue that are not already on the "recipients"
        list of the message.
        
        Those users are then appended to the "recipients" property on the
        message, so multiple copies of a message are never sent to the same
        user.
        
        The journal recorded by the hyperdatabase on the "recipients" property
        then provides a log of when the message was sent to whom. 
    '''
    messages = []
    if oldvalues is None:
        # the action was a create, so use all the messages in the create
        messages = cl.get(nodeid, 'messages')
    elif oldvalues.has_key('messages'):
        # the action was a set (so adding new messages to an existing issue)
        m = {}
        for msgid in oldvalues['messages']:
            m[msgid] = 1
        messages = []
        # figure which of the messages now on the issue weren't there before
        for msgid in cl.get(nodeid, 'messages'):
            if not m.has_key(msgid):
                messages.append(msgid)
    if not messages:
        return

    # send a copy to the nosy list
    for msgid in messages:
        cl.sendmessage(nodeid, msgid)

    # update the nosy list with the recipients from the new messages
    nosy = cl.get(nodeid, 'nosy')
    n = {}
    for nosyid in nosy: n[nosyid] = 1
    change = 0
    # but don't add admin to the nosy list
    for msgid in messages:
        for recipid in db.msg.get(msgid, 'recipients'):
            if recipid != '1' and not n.has_key(recipid):
                change = 1
                nosy.append(recipid)
        authid = db.msg.get(msgid, 'author')
        if authid != '1' and not n.has_key(authid):
            change = 1
            nosy.append(authid)
    if change:
        cl.set(nodeid, nosy=nosy)


def init(db):
    db.issue.react('create', nosyreaction)
    db.issue.react('set', nosyreaction)

#
#$Log: not supported by cvs2svn $
#
