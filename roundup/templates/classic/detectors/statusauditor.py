# Copyright (c) 2002 ekit.com Inc (http://www.ekit-inc.com/)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
#$Id: statusauditor.py,v 1.1 2002-05-29 01:16:17 richard Exp $

def chatty(db, cl, nodeid, newvalues):
    ''' If the issue is currently 'unread' or 'resolved', then set
        it to 'chatting'
    '''
    # don't fire if there's no new message (ie. chat)
    if not newvalues.has_key('messages'):
        return
    if newvalues['messages'] == cl.get(nodeid, 'messages', cache=0):
        return

    # determine the id of 'unread', 'resolved' and 'chatting'
    unread_id = db.status.lookup('unread')
    resolved_id = db.status.lookup('resolved')
    chatting_id = db.status.lookup('chatting')

    # get the current value
    current_status = cl.get(nodeid, 'status')

    # see if there's an explicit change in this transaction
    if newvalues.has_key('status') and newvalues['status'] != current_status:
        # yep, skip
        return

    # ok, there's no explicit change, so do it manually
    if current_status in (unread_id, resolved_id):
        newvalues['status'] = chatting_id


def presetunread(db, cl, nodeid, newvalues):
    ''' Make sure the status is set on new issues
    '''
    if newvalues.has_key('status'):
        return

    # ok, do it
    newvalues['status'] = db.status.lookup('unread')


def init(db):
    # fire before changes are made
    db.issue.audit('set', chatty)
    db.issue.audit('create', presetunread)

#
#$Log: not supported by cvs2svn $
#
