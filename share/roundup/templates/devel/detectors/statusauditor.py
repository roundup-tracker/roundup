def preset_new(db, cl, nodeid, newvalues):
    """ Make sure the status is set on new issues"""

    if newvalues.has_key('status') and newvalues['status']:
        return

    new = db.status.lookup('new')
    newvalues['status'] = new


def init(db): pass
    # fire before changes are made
    #db.issue.audit('create', preset_new)
