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
#$Id: nosyreaction.py,v 1.13 2002-07-31 23:57:36 richard Exp $

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
    current = {}
    if nodeid is None:
        ok = ('new', 'yes')
    else:
        ok = ('yes',)
        # old node, get the current values from the node if they haven't
        # changed
        if not newvalues.has_key('nosy'):
            nosy = cl.get(nodeid, 'nosy')
            for value in nosy:
                if not current.has_key(value):
                    current[value] = 1

    # if the nosy list changed in this transaction, init from the new value
    if newvalues.has_key('nosy'):
        nosy = newvalues.get('nosy', [])
        for value in nosy:
            if not db.hasnode('user', value):
                continue
            if not current.has_key(value):
                current[value] = 1

    # add assignedto(s) to the nosy list
    if newvalues.has_key('assignedto') and newvalues['assignedto'] is not None:
        propdef = cl.getprops()
        if isinstance(propdef['assignedto'], hyperdb.Link):
            assignedto_ids = [newvalues['assignedto']]
        elif isinstance(propdef['assignedto'], hyperdb.Multilink):
            assignedto_ids = newvalues['assignedto']
        for assignedto_id in assignedto_ids:
            if not current.has_key(assignedto_id):
                current[assignedto_id] = 1

    # see if there's any new messages - if so, possibly add the author and
    # recipient to the nosy
    if newvalues.has_key('messages'):
        if nodeid is None:
            ok = ('new', 'yes')
            messages = newvalues['messages']
        else:
            ok = ('yes',)
            # figure which of the messages now on the issue weren't
            # there before - make sure we don't get a cached version!
            oldmessages = cl.get(nodeid, 'messages', cache=0)
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
                current[authid] = 1

            # add on the recipients of the message
            if add_recips in ok:
                for recipient in msg.get(msgid, 'recipients'):
                    current[recipient] = 1

    # that's it, save off the new nosy list
    newvalues['nosy'] = current.keys()

def init(db):
    db.issue.react('create', nosyreaction)
    db.issue.react('set', nosyreaction)
    db.issue.audit('create', updatenosy)
    db.issue.audit('set', updatenosy)

#
#$Log: not supported by cvs2svn $
#Revision 1.12  2002/05/29 01:16:17  richard
#Sorry about this huge checkin! It's fixing a lot of related stuff in one go
#though.
#
#. #541941 ] changing multilink properties by mail
#. #526730 ] search for messages capability
#. #505180 ] split MailGW.handle_Message
#  - also changed cgi client since it was duplicating the functionality
#. build htmlbase if tests are run using CVS checkout (removed note from
#  installation.txt)
#. don't create an empty message on email issue creation if the email is empty
#
#Revision 1.11  2002/01/14 22:21:38  richard
##503353 ] setting properties in initial email
#
#Revision 1.10  2002/01/11 23:22:29  richard
# . #502437 ] rogue reactor and unittest
#   in short, the nosy reactor was modifying the nosy list. That code had
#   been there for a long time, and I suspsect it was there because we
#   weren't generating the nosy list correctly in other places of the code.
#   We're now doing that, so the nosy-modifying code can go away from the
#   nosy reactor.
#
#Revision 1.9  2001/12/15 19:24:39  rochecompaan
# . Modified cgi interface to change properties only once all changes are
#   collected, files created and messages generated.
# . Moved generation of change note to nosyreactors.
# . We now check for changes to "assignedto" to ensure it's added to the
#   nosy list.
#
#Revision 1.8  2001/12/05 14:26:44  rochecompaan
#Removed generation of change note from "sendmessage" in roundupdb.py.
#The change note is now generated when the message is created.
#
#Revision 1.7  2001/11/30 11:29:04  rochecompaan
#Property changes are now listed in emails generated by Roundup
#
#Revision 1.6  2001/11/26 22:55:56  richard
#Feature:
# . Added INSTANCE_NAME to configuration - used in web and email to identify
#   the instance.
# . Added EMAIL_SIGNATURE_POSITION to indicate where to place the roundup
#   signature info in e-mails.
# . Some more flexibility in the mail gateway and more error handling.
# . Login now takes you to the page you back to the were denied access to.
#
#Fixed:
# . Lots of bugs, thanks Roché and others on the devel mailing list!
#
#Revision 1.5  2001/11/12 22:01:07  richard
#Fixed issues with nosy reaction and author copies.
#
#Revision 1.4  2001/10/30 00:54:45  richard
#Features:
# . #467129 ] Lossage when username=e-mail-address
# . #473123 ] Change message generation for author
# . MailGW now moves 'resolved' to 'chatting' on receiving e-mail for an issue.
#
#Revision 1.3  2001/08/07 00:24:43  richard
#stupid typo
#
#Revision 1.2  2001/08/07 00:15:51  richard
#Added the copyright/license notice to (nearly) all files at request of
#Bizar Software.
#
#Revision 1.1  2001/07/23 23:29:10  richard
#Adding the classic template
#
#Revision 1.1  2001/07/23 03:50:47  anthonybaxter
#moved templates to proper location
#
#Revision 1.1  2001/07/22 12:09:32  richard
#Final commit of Grande Splite
#
#
