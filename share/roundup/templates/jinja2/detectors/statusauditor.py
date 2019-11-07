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

from roundup.configuration import BooleanOption, InvalidOptionError

def chatty(db, cl, nodeid, newvalues):
    ''' If the issue is currently 'resolved', 'done-cbb' or None,
        then set it to 'chatting'. If issue is 'unread' and
        chatting_requires_two_users is true, set state
        to 'chatting' if the person adding the new message is not
        the same as the person who created the issue. This allows
        somebody to submit multiple emails describing the problem
        without changing it to 'chatting'. 'chatting' should
        indicate at least two people are 'chatting'.
    '''
    # If set to true, change state from 'unread' to 'chatting' only
    # if the author of the update is not the person who created the
    # first message (and thus the issue). If false (default ini file
    # setting) set 'chatting' when the second message is received.
    try:
        chatting_requires_two_users = BooleanOption(None,
                        "detector::Statusauditor",
                        "CHATTING_REQUIRES_TWO_USERS").str2value(
        db.config.detectors[
        'STATUSAUDITOR_CHATTING_REQUIRES_TWO_USERS' ]
    )
    except InvalidOptionError:
        raise InvalidOptionError("Option STATUSAUDITOR_CHATTING_REQUIRES_TWO_USERS not found in detectors/config.ini. Contact tracker admin to fix.")
        
    # don't fire if there's no new message (ie. chat)
    if 'messages' not in newvalues:
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
    if 'status' in newvalues:
        # yep, skip
        return

    # determine the id of 'unread', 'resolved' and 'chatting'
    fromstates = []
    for state in 'unread resolved done-cbb'.split():
        try:
            fromstates.append(db.status.lookup(state))
        except KeyError:
            pass

    unread = fromstates[0] # grab the 'unread' state which is first

    # ok, there's no explicit change, so check if we are in a state that
    # should be changed. First see if we should set 'chatting' based on
    # who opened the issue.
    if current_status == unread and chatting_requires_two_users:
        # find creator of issue and compare to currentuser making
        # update. If the creator is same as initial author don't
        # change to 'chatting'.
        issue_creator = cl.get(nodeid, 'creator')
        if issue_creator == db.getuid():
            # person is chatting with themselves, don't set 'chatting'
            return

    # Current author is not the initiator of the issue so
    # we are 'chatting'.
    if current_status in fromstates + [None]:
        # yep, we're now chatting
        newvalues['status'] = chatting_id


def presetunread(db, cl, nodeid, newvalues):
    ''' Make sure the status is set on new issues
    '''
    if 'status' in newvalues and newvalues['status']:
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
