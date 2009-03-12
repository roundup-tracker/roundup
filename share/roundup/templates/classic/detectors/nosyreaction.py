#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
# 
#$Id: nosyreaction.py,v 1.4 2005-04-04 08:47:14 richard Exp $

# Python 2.3 ... 2.6 compatibility:
from roundup.anypy.sets_ import set

from roundup import roundupdb, hyperdb

def nosyreaction(db, cl, nodeid, oldvalues):
    ''' A standard detector is provided that watches for additions to the
        "messages" property.
        
        When a new message is added, the detector sends it to all the users on
        the "nosy" list for the issue that are not already on the "recipients"
        list of the message.
        
        Those users are then appended to the "recipients" property on the
        message, so multiple copies of a message are never sent to the same
        user.
        
        The journal recorded by the hyperdatabase on the "recipients" property
        then provides a log of when the message was sent to whom. 
    '''
    # send a copy of all new messages to the nosy list
    for msgid in determineNewMessages(cl, nodeid, oldvalues):
        try:
            cl.nosymessage(nodeid, msgid, oldvalues)
        except roundupdb.MessageSendError, message:
            raise roundupdb.DetectorError, message

def determineNewMessages(cl, nodeid, oldvalues):
    ''' Figure a list of the messages that are being added to the given
        node in this transaction.
    '''
    messages = []
    if oldvalues is None:
        # the action was a create, so use all the messages in the create
        messages = cl.get(nodeid, 'messages')
    elif oldvalues.has_key('messages'):
        # the action was a set (so adding new messages to an existing issue)
        m = {}
        for msgid in oldvalues['messages']:
            m[msgid] = 1
        messages = []
        # figure which of the messages now on the issue weren't there before
        for msgid in cl.get(nodeid, 'messages'):
            if not m.has_key(msgid):
                messages.append(msgid)
    return messages

def updatenosy(db, cl, nodeid, newvalues):
    '''Update the nosy list for changes to the assignedto
    '''
    # nodeid will be None if this is a new node
    current_nosy = set()
    if nodeid is None:
        ok = ('new', 'yes')
    else:
        ok = ('yes',)
        # old node, get the current values from the node if they haven't
        # changed
        if not newvalues.has_key('nosy'):
            nosy = cl.get(nodeid, 'nosy')
            for value in nosy:
                current_nosy.add(value)

    # if the nosy list changed in this transaction, init from the new value
    if newvalues.has_key('nosy'):
        nosy = newvalues.get('nosy', [])
        for value in nosy:
            if not db.hasnode('user', value):
                continue
            current_nosy.add(value)

    new_nosy = set(current_nosy)

    # add assignedto(s) to the nosy list
    if newvalues.has_key('assignedto') and newvalues['assignedto'] is not None:
        propdef = cl.getprops()
        if isinstance(propdef['assignedto'], hyperdb.Link):
            assignedto_ids = [newvalues['assignedto']]
        elif isinstance(propdef['assignedto'], hyperdb.Multilink):
            assignedto_ids = newvalues['assignedto']
        for assignedto_id in assignedto_ids:
            new_nosy.add(assignedto_id)

    # see if there's any new messages - if so, possibly add the author and
    # recipient to the nosy
    if newvalues.has_key('messages'):
        if nodeid is None:
            ok = ('new', 'yes')
            messages = newvalues['messages']
        else:
            ok = ('yes',)
            # figure which of the messages now on the issue weren't
            oldmessages = cl.get(nodeid, 'messages')
            messages = []
            for msgid in newvalues['messages']:
                if msgid not in oldmessages:
                    messages.append(msgid)

        # configs for nosy modifications
        add_author = getattr(db.config, 'ADD_AUTHOR_TO_NOSY', 'new')
        add_recips = getattr(db.config, 'ADD_RECIPIENTS_TO_NOSY', 'new')

        # now for each new message:
        msg = db.msg
        for msgid in messages:
            if add_author in ok:
                authid = msg.get(msgid, 'author')
                new_nosy.add(authid)

            # add on the recipients of the message
            if add_recips in ok:
                for recipient in msg.get(msgid, 'recipients'):
                    new_nosy.add(recipient)

    if current_nosy != new_nosy:
        # that's it, save off the new nosy list
        newvalues['nosy'] = list(new_nosy)

def init(db):
    db.issue.react('create', nosyreaction)
    db.issue.react('set', nosyreaction)
    db.issue.audit('create', updatenosy)
    db.issue.audit('set', updatenosy)

# vim: set filetype=python ts=4 sw=4 et si
