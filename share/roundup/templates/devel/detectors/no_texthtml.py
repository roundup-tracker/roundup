
def audit_html_files(db, cl, nodeid, newvalues):
    if 'type' in newvalues and newvalues['type'] == 'text/html':
        newvalues['type'] = 'text/plain'
    

def init(db):
    db.file.audit('set', audit_html_files)
    db.file.audit('create', audit_html_files)
