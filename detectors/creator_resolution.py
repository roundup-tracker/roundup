# This detector was written by richard@mechanicalcat.net and it's been
# placed in the Public Domain. Copy and modify to your heart's content.

from roundup.exceptions import Reject

def creator_resolution(db, cl, nodeid, newvalues):
    '''Catch attempts to set the status to "resolved" - if the assignedto
    user isn't the creator, then set the status to "in-progress" (try
    "confirm-done" first though, but "classic" Roundup doesn't have that
    status)
    '''
    if 'status' not in newvalues:
        return

    # get the resolved state ID
    resolved_id = db.status.lookup('resolved')

    if newvalues['status'] != resolved_id:
        return

    # check the assignedto
    assignedto = newvalues.get('assignedto', cl.get(nodeid, 'assignedto'))
    creator = cl.get(nodeid, 'creator')
    if assignedto == creator:
        if db.getuid() != creator:
            name = db.user.get(creator, 'username')
            raise Reject('Only the creator (%s) may close this issue'%name)
        return

    # set the assignedto and status
    newvalues['assignedto'] = creator
    try:
        status = db.status.lookup('confirm-done')
    except KeyError:
        status = db.status.lookup('in-progress')
    newvalues['status'] = status

def init(db):
    db.issue.audit('set', creator_resolution)

# vim: set filetype=python ts=4 sw=4 et si
