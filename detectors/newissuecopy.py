# copied from nosyreaction

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
            cl.send_message(nodeid, msgid, change_note, ['team@team.host'])
        except roundupdb.MessageSendError, message:
            raise roundupdb.DetectorError, message

def init(db):
    db.issue.react('create', newissuecopy)

# vim: set filetype=python ts=4 sw=4 et si
