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
        except roundupdb.MessageSendError as message:
            raise roundupdb.DetectorError(message)

def determineNewMessages(cl, nodeid, oldvalues):
    ''' Figure a list of the messages that are being added to the given
        node in this transaction.
    '''
    messages = []
    if oldvalues is None:
        # the action was a create, so use all the messages in the create
        messages = cl.get(nodeid, 'messages')
    elif 'messages' in oldvalues:
        # the action was a set (so adding new messages to an existing issue)
        m = {}
        for msgid in oldvalues['messages']:
            m[msgid] = 1
        messages = []
        # figure which of the messages now on the issue weren't there before
        for msgid in cl.get(nodeid, 'messages'):
            if msgid not in m:
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
        if 'nosy' not in newvalues:
            nosy = cl.get(nodeid, 'nosy')
            for value in nosy:
                current_nosy.add(value)

    # if the nosy list changed in this transaction, init from the new value
    if 'nosy' in newvalues:
        nosy = newvalues.get('nosy', [])
        for value in nosy:
            if not db.hasnode('user', value):
                continue
            current_nosy.add(value)

    new_nosy = set(current_nosy)

    # add assignedto(s) to the nosy list
    if 'assignedto' in newvalues and newvalues['assignedto'] is not None:
        propdef = cl.getprops()
        if isinstance(propdef['assignedto'], hyperdb.Link):
            assignedto_ids = [newvalues['assignedto']]
        elif isinstance(propdef['assignedto'], hyperdb.Multilink):
            assignedto_ids = newvalues['assignedto']
        for assignedto_id in assignedto_ids:
            new_nosy.add(assignedto_id)

    # see if there's any new messages - if so, possibly add the author and
    # recipient to the nosy
    if 'messages' in newvalues:
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
    db.bug.react('create', nosyreaction)
    db.bug.react('set', nosyreaction)
    db.bug.audit('create', updatenosy)
    db.bug.audit('set', updatenosy)

    db.task.react('create', nosyreaction)
    db.task.react('set', nosyreaction)
    db.task.audit('create', updatenosy)
    db.task.audit('set', updatenosy)

    db.milestone.react('create', nosyreaction)
    db.milestone.react('set', nosyreaction)
    db.milestone.audit('create', updatenosy)
    db.milestone.audit('set', updatenosy)
