# HTML pages don't provide a way to change the contents of a file.
# However REST does allow setting content and the HTML interface can
# be directed to update the content as well. This detector
# prevents changes to file content.

from roundup.exceptions import UsageError

def immutable_file_contents(db, cl, nodeid, newvalues):
    ''' Prevent content changes to a file
    '''
    if 'content' in newvalues:
        raise UsageError("File contents are immutable. "
                         "Rejecting change to contents.")


def init(db):
    """If you have other FileClass based classes add them here."""

    # fire before changes are made
    db.file.audit('set', immutable_file_contents)
    db.msg.audit('set', immutable_file_contents)

