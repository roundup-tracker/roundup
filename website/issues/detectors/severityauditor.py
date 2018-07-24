
def init_severity(db, cl, nodeid, newvalues):
    """Make sure severity is set on new issues"""
    if 'severity' in newvalues and newvalues['severity']:
        return

    normal = db.severity.lookup('normal')
    newvalues['severity'] = normal

def init(db):
    db.issue.audit('create', init_severity)
