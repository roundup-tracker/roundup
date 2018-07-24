from roundup import roundupdb

def newissuecopy(db, cl, nodeid, oldvalues):
    ''' Copy a message about new issues to a team address.
    '''
    # so use all the messages in the create
    change_note = cl.generateCreateNote(nodeid)

    # send a copy to the nosy list
    for msgid in cl.get(nodeid, 'messages'):
        try:
            # note: last arg must be a list
            cl.send_message(nodeid, msgid, change_note,
                ['roundup-devel@lists.sourceforge.net'])
        except roundupdb.MessageSendError as message:
            raise roundupdb.DetectorError(message)

def init(db):
    db.issue.react('create', newissuecopy)
#SHA: 6ed003c947e1f9df148f8f4500b7c2e68a45229b
