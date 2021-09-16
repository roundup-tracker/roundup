def preset_new(db, cl, nodeid, newvalues):
    """ Make sure the status is set on new issues"""

    if 'status' in newvalues and newvalues['status']:
        return

    new = db.status.lookup('new')
    newvalues['status'] = new

def update_pending(db, cl, nodeid, newvalues):
    ''' If the issue is currently 'pending' and person other than assigned
        updates it, then set it to 'open'.
    '''
    # don't fire if there's no new message (ie. update)
    if 'messages' not in newvalues:
        return
    if newvalues['messages'] == cl.get(nodeid, 'messages'):
        return

    # get the open state ID
    try:
        open_id = db.status.lookup('open')
    except KeyError:
        # no open state, ignore all this stuff
        return

    # get the current value
    current_status = cl.get(nodeid, 'status')

    # see if there's an explicit change in this transaction
    if 'status' in newvalues:
        # yep, skip
        return

    assignee = cl.get(nodeid, 'assignee')
    if assignee == db.getuid():
        # this change is brought to you by the assignee and number 4
        # so don't change status.
        return

    # determine the id of 'pending'
    fromstates = []
    for state in 'pending'.split():
        try:
            fromstates.append(db.status.lookup(state))
        except KeyError:
            pass

    # ok, there's no explicit change, so check if we are in a state that
    # should be changed
    if current_status in fromstates + [None]:
        # yep, we're now open
        newvalues['status'] = open_id

def init(db):
    # fire before changes are made
    db.issue.audit('create', preset_new)
    db.issue.audit('set', update_pending)
