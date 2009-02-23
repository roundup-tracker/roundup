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
#$Id: statusauditor.py,v 1.5 2004-03-27 00:01:48 richard Exp $

def chatty(db, cl, nodeid, newvalues):
    ''' If the issue is currently 'unread', 'resolved', 'done-cbb' or None,
        then set it to 'chatting'
    '''
    # don't fire if there's no new message (ie. chat)
    if not newvalues.has_key('messages'):
        return
    if newvalues['messages'] == cl.get(nodeid, 'messages'):
        return

    # get the chatting state ID
    try:
        chatting_id = db.status.lookup('chatting')
    except KeyError:
        # no chatting state, ignore all this stuff
        return

    # get the current value
    current_status = cl.get(nodeid, 'status')

    # see if there's an explicit change in this transaction
    if newvalues.has_key('status'):
        # yep, skip
        return

    # determine the id of 'unread', 'resolved' and 'chatting'
    fromstates = []
    for state in 'unread resolved done-cbb'.split():
        try:
            fromstates.append(db.status.lookup(state))
        except KeyError:
            pass

    # ok, there's no explicit change, so check if we are in a state that
    # should be changed
    if current_status in fromstates + [None]:
        # yep, we're now chatting
        newvalues['status'] = chatting_id


def presetunread(db, cl, nodeid, newvalues):
    ''' Make sure the status is set on new issues
    '''
    if newvalues.has_key('status') and newvalues['status']:
        return

    # get the unread state ID
    try:
        unread_id = db.status.lookup('unread')
    except KeyError:
        # no unread state, ignore all this stuff
        return

    # ok, do it
    newvalues['status'] = unread_id


def init(db):
    # fire before changes are made
    db.issue.audit('set', chatty)
    db.issue.audit('create', presetunread)

# vim: set filetype=python ts=4 sw=4 et si
