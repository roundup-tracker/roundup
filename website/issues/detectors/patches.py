# Auditor for patch files
# Patches should be declared as text/plain (also .py files),
# independent of what the browser says, and
# the "patch" keyword should get set automatically.

import posixpath

patchtypes = ('.diff', '.patch')
sourcetypes = ('.diff', '.patch', '.py')

def ispatch(file, types):
    return posixpath.splitext(file)[1] in types

def patches_text_plain(db, cl, nodeid, newvalues):
    if ispatch(newvalues['name'], sourcetypes):
        newvalues['type'] = 'text/plain'

def patches_keyword(db, cl, nodeid, newvalues):
    # Check whether there are any new files
    newfiles = set(newvalues.get('files',()))
    if nodeid:
        newfiles -= set(db.issue.get(nodeid, 'files'))
    # Check whether any of these is a patch
    newpatch = False
    for fileid in newfiles:
        if ispatch(db.file.get(fileid, 'name'), patchtypes):
            newpatch = True
            break
    if newpatch:
        # Add the patch keyword if its not already there
        patchid = db.keyword.lookup("patch")
        oldkeywords = []
        if nodeid:
            oldkeywords = db.issue.get(nodeid, 'keywords')
            if patchid in oldkeywords:
                # This is already marked as a patch
                return
        if not newvalues.has_key('keywords'):
            newvalues['keywords'] = oldkeywords
        newvalues['keywords'].append(patchid)

def init(db):
    db.file.audit('create', patches_text_plain)
    db.issue.audit('create', patches_keyword)
    db.issue.audit('set', patches_keyword)
