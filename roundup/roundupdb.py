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
# $Id: roundupdb.py,v 1.59 2002-06-18 03:55:25 dman13 Exp $

__doc__ = """
Extending hyperdb with types specific to issue-tracking.
"""

import re, os, smtplib, socket, copy, time, random
import MimeWriter, cStringIO
import base64, quopri, mimetypes
# if available, use the 'email' module, otherwise fallback to 'rfc822'
try :
    from email.Utils import dump_address_pair as straddr
except ImportError :
    from rfc822 import dump_address_pair as straddr

import hyperdb, date

# set to indicate to roundup not to actually _send_ email
# this var must contain a file to write the mail to
SENDMAILDEBUG = os.environ.get('SENDMAILDEBUG', '')

class DesignatorError(ValueError):
    pass
def splitDesignator(designator, dre=re.compile(r'([^\d]+)(\d+)')):
    ''' Take a foo123 and return ('foo', 123)
    '''
    m = dre.match(designator)
    if m is None:
        raise DesignatorError, '"%s" not a node designator'%designator
    return m.group(1), m.group(2)


def extractUserFromList(userClass, users):
    '''Given a list of users, try to extract the first non-anonymous user
       and return that user, otherwise return None
    '''
    if len(users) > 1:
        # make sure we don't match the anonymous or admin user
        for user in users:
            if user == '1': continue
            if userClass.get(user, 'username') == 'anonymous': continue
            # first valid match will do
            return user
        # well, I guess we have no choice
        return user[0]
    elif users:
        return users[0]
    return None

class Database:
    def getuid(self):
        """Return the id of the "user" node associated with the user
        that owns this connection to the hyperdatabase."""
        return self.user.lookup(self.journaltag)

    def uidFromAddress(self, address, create=1):
        ''' address is from the rfc822 module, and therefore is (name, addr)

            user is created if they don't exist in the db already
        '''
        (realname, address) = address

        # try a straight match of the address
        user = extractUserFromList(self.user,
            self.user.stringFind(address=address))
        if user is not None: return user

        # try the user alternate addresses if possible
        props = self.user.getprops()
        if props.has_key('alternate_addresses'):
            users = self.user.filter(None, {'alternate_addresses': address},
                [], [])
            user = extractUserFromList(self.user, users)
            if user is not None: return user

        # try to match the username to the address (for local
        # submissions where the address is empty)
        user = extractUserFromList(self.user,
            self.user.stringFind(username=address))

        # couldn't match address or username, so create a new user
        if create:
            return self.user.create(username=address, address=address,
                realname=realname)
        else:
            return 0

_marker = []
# XXX: added the 'creator' faked attribute
class Class(hyperdb.Class):
    # Overridden methods:
    def __init__(self, db, classname, **properties):
        if (properties.has_key('creation') or properties.has_key('activity')
                or properties.has_key('creator')):
            raise ValueError, '"creation", "activity" and "creator" are reserved'
        hyperdb.Class.__init__(self, db, classname, **properties)
        self.auditors = {'create': [], 'set': [], 'retire': []}
        self.reactors = {'create': [], 'set': [], 'retire': []}

    def create(self, **propvalues):
        """These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        """
        if propvalues.has_key('creation') or propvalues.has_key('activity'):
            raise KeyError, '"creation" and "activity" are reserved'
        self.fireAuditors('create', None, propvalues)
        nodeid = hyperdb.Class.create(self, **propvalues)
        self.fireReactors('create', nodeid, None)
        return nodeid

    def set(self, nodeid, **propvalues):
        """These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        """
        if propvalues.has_key('creation') or propvalues.has_key('activity'):
            raise KeyError, '"creation" and "activity" are reserved'
        self.fireAuditors('set', nodeid, propvalues)
        # Take a copy of the node dict so that the subsequent set
        # operation doesn't modify the oldvalues structure.
        try:
            # try not using the cache initially
            oldvalues = copy.deepcopy(self.db.getnode(self.classname, nodeid,
                cache=0))
        except IndexError:
            # this will be needed if somone does a create() and set()
            # with no intervening commit()
            oldvalues = copy.deepcopy(self.db.getnode(self.classname, nodeid))
        hyperdb.Class.set(self, nodeid, **propvalues)
        self.fireReactors('set', nodeid, oldvalues)

    def retire(self, nodeid):
        """These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        """
        self.fireAuditors('retire', nodeid, None)
        hyperdb.Class.retire(self, nodeid)
        self.fireReactors('retire', nodeid, None)

    def get(self, nodeid, propname, default=_marker, cache=1):
        """Attempts to get the "creation" or "activity" properties should
        do the right thing.
        """
        if propname == 'creation':
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                return self.db.getjournal(self.classname, nodeid)[0][1]
            else:
                # on the strange chance that there's no journal
                return date.Date()
        if propname == 'activity':
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                return self.db.getjournal(self.classname, nodeid)[-1][1]
            else:
                # on the strange chance that there's no journal
                return date.Date()
        if propname == 'creator':
            journal = self.db.getjournal(self.classname, nodeid)
            if journal:
                name = self.db.getjournal(self.classname, nodeid)[0][2]
            else:
                return None
            return self.db.user.lookup(name)
        if default is not _marker:
            return hyperdb.Class.get(self, nodeid, propname, default,
                cache=cache)
        else:
            return hyperdb.Class.get(self, nodeid, propname, cache=cache)

    def getprops(self, protected=1):
        """In addition to the actual properties on the node, these
        methods provide the "creation" and "activity" properties. If the
        "protected" flag is true, we include protected properties - those
        which may not be modified.
        """
        d = hyperdb.Class.getprops(self, protected=protected).copy()
        if protected:
            d['creation'] = hyperdb.Date()
            d['activity'] = hyperdb.Date()
            d['creator'] = hyperdb.Link("user")
        return d

    #
    # Detector interface
    #
    def audit(self, event, detector):
        """Register a detector
        """
        l = self.auditors[event]
        if detector not in l:
            self.auditors[event].append(detector)

    def fireAuditors(self, action, nodeid, newvalues):
        """Fire all registered auditors.
        """
        for audit in self.auditors[action]:
            audit(self.db, self, nodeid, newvalues)

    def react(self, event, detector):
        """Register a detector
        """
        l = self.reactors[event]
        if detector not in l:
            self.reactors[event].append(detector)

    def fireReactors(self, action, nodeid, oldvalues):
        """Fire all registered reactors.
        """
        for react in self.reactors[action]:
            react(self.db, self, nodeid, oldvalues)

class FileClass(Class):
    def create(self, **propvalues):
        ''' snaffle the file propvalue and store in a file
        '''
        content = propvalues['content']
        del propvalues['content']
        newid = Class.create(self, **propvalues)
        self.db.storefile(self.classname, newid, None, content)
        return newid

    def get(self, nodeid, propname, default=_marker, cache=1):
        ''' trap the content propname and get it from the file
        '''

        poss_msg = 'Possibly a access right configuration problem.'
        if propname == 'content':
            try:
                return self.db.getfile(self.classname, nodeid, None)
            except IOError, (strerror):
                # BUG: by catching this we donot see an error in the log.
                return 'ERROR reading file: %s%s\n%s\n%s'%(
                        self.classname, nodeid, poss_msg, strerror)
        if default is not _marker:
            return Class.get(self, nodeid, propname, default, cache=cache)
        else:
            return Class.get(self, nodeid, propname, cache=cache)

    def getprops(self, protected=1):
        ''' In addition to the actual properties on the node, these methods
            provide the "content" property. If the "protected" flag is true,
            we include protected properties - those which may not be
            modified.
        '''
        d = Class.getprops(self, protected=protected).copy()
        if protected:
            d['content'] = hyperdb.String()
        return d

class MessageSendError(RuntimeError):
    pass

class DetectorError(RuntimeError):
    pass

# XXX deviation from spec - was called ItemClass
class IssueClass(Class):

    # Overridden methods:

    def __init__(self, db, classname, **properties):
        """The newly-created class automatically includes the "messages",
        "files", "nosy", and "superseder" properties.  If the 'properties'
        dictionary attempts to specify any of these properties or a
        "creation" or "activity" property, a ValueError is raised."""
        if not properties.has_key('title'):
            properties['title'] = hyperdb.String()
        if not properties.has_key('messages'):
            properties['messages'] = hyperdb.Multilink("msg")
        if not properties.has_key('files'):
            properties['files'] = hyperdb.Multilink("file")
        if not properties.has_key('nosy'):
            properties['nosy'] = hyperdb.Multilink("user")
        if not properties.has_key('superseder'):
            properties['superseder'] = hyperdb.Multilink(classname)
        Class.__init__(self, db, classname, **properties)

    # New methods:

    def addmessage(self, nodeid, summary, text):
        """Add a message to an issue's mail spool.

        A new "msg" node is constructed using the current date, the user that
        owns the database connection as the author, and the specified summary
        text.

        The "files" and "recipients" fields are left empty.

        The given text is saved as the body of the message and the node is
        appended to the "messages" field of the specified issue.
        """

    def nosymessage(self, nodeid, msgid, oldvalues):
        """Send a message to the members of an issue's nosy list.

        The message is sent only to users on the nosy list who are not
        already on the "recipients" list for the message.
        
        These users are then added to the message's "recipients" list.
        """
        users = self.db.user
        messages = self.db.msg

        # figure the recipient ids
        sendto = []
        r = {}
        recipients = messages.get(msgid, 'recipients')
        for recipid in messages.get(msgid, 'recipients'):
            r[recipid] = 1

        # figure the author's id, and indicate they've received the message
        authid = messages.get(msgid, 'author')

        # possibly send the message to the author, as long as they aren't
        # anonymous
        if (self.db.config.MESSAGES_TO_AUTHOR == 'yes' and
                users.get(authid, 'username') != 'anonymous'):
            sendto.append(authid)
        r[authid] = 1

        # now figure the nosy people who weren't recipients
        nosy = self.get(nodeid, 'nosy')
        for nosyid in nosy:
            # Don't send nosy mail to the anonymous user (that user
            # shouldn't appear in the nosy list, but just in case they
            # do...)
            if users.get(nosyid, 'username') == 'anonymous':
                continue
            # make sure they haven't seen the message already
            if not r.has_key(nosyid):
                # send it to them
                sendto.append(nosyid)
                recipients.append(nosyid)

        # generate a change note
        if oldvalues:
            note = self.generateChangeNote(nodeid, oldvalues)
        else:
            note = self.generateCreateNote(nodeid)

        # we have new recipients
        if sendto:
            # map userids to addresses
            sendto = [users.get(i, 'address') for i in sendto]

            # update the message's recipients list
            messages.set(msgid, recipients=recipients)

            # send the message
            self.send_message(nodeid, msgid, note, sendto)

    # XXX backwards compatibility - don't remove
    sendmessage = nosymessage

    def send_message(self, nodeid, msgid, note, sendto):
        '''Actually send the nominated message from this node to the sendto
           recipients, with the note appended.
        '''
        users = self.db.user
        messages = self.db.msg
        files = self.db.file

        # determine the messageid and inreplyto of the message
        inreplyto = messages.get(msgid, 'inreplyto')
        messageid = messages.get(msgid, 'messageid')

        # make up a messageid if there isn't one (web edit)
        if not messageid:
            # this is an old message that didn't get a messageid, so
            # create one
            messageid = "<%s.%s.%s%s@%s>"%(time.time(), random.random(),
                self.classname, nodeid, self.db.config.MAIL_DOMAIN)
            messages.set(msgid, messageid=messageid)

        # send an email to the people who missed out
        cn = self.classname
        title = self.get(nodeid, 'title') or '%s message copy'%cn
        # figure author information
        authid = messages.get(msgid, 'author')
        authname = users.get(authid, 'realname')
        if not authname:
            authname = users.get(authid, 'username')
        authaddr = users.get(authid, 'address')
        if authaddr:
            authaddr = " <%s>" % straddr( ('',authaddr) )
        else:
            authaddr = ''

        # make the message body
        m = ['']

        # put in roundup's signature
        if self.db.config.EMAIL_SIGNATURE_POSITION == 'top':
            m.append(self.email_signature(nodeid, msgid))

        # add author information
        if len(self.get(nodeid,'messages')) == 1:
            m.append("New submission from %s%s:"%(authname, authaddr))
        else:
            m.append("%s%s added the comment:"%(authname, authaddr))
        m.append('')

        # add the content
        m.append(messages.get(msgid, 'content'))

        # add the change note
        if note:
            m.append(note)

        # put in roundup's signature
        if self.db.config.EMAIL_SIGNATURE_POSITION == 'bottom':
            m.append(self.email_signature(nodeid, msgid))

        # encode the content as quoted-printable
        content = cStringIO.StringIO('\n'.join(m))
        content_encoded = cStringIO.StringIO()
        quopri.encode(content, content_encoded, 0)
        content_encoded = content_encoded.getvalue()

        # get the files for this message
        message_files = messages.get(msgid, 'files')

        # make sure the To line is always the same (for testing mostly)
        sendto.sort()

        # create the message
        message = cStringIO.StringIO()
        writer = MimeWriter.MimeWriter(message)
        writer.addheader('Subject', '[%s%s] %s'%(cn, nodeid, title))
        writer.addheader('To', ', '.join(sendto))
        writer.addheader('From', straddr(
                              (authname, self.db.config.ISSUE_TRACKER_EMAIL) ) )
        writer.addheader('Reply-To', straddr( 
                                        (self.db.config.INSTANCE_NAME,
                                         self.db.config.ISSUE_TRACKER_EMAIL) ) )
        writer.addheader('MIME-Version', '1.0')
        if messageid:
            writer.addheader('Message-Id', messageid)
        if inreplyto:
            writer.addheader('In-Reply-To', inreplyto)

        # add a uniquely Roundup header to help filtering
        writer.addheader('X-Roundup-Name', self.db.config.INSTANCE_NAME)

        # attach files
        if message_files:
            part = writer.startmultipartbody('mixed')
            part = writer.nextpart()
            part.addheader('Content-Transfer-Encoding', 'quoted-printable')
            body = part.startbody('text/plain')
            body.write(content_encoded)
            for fileid in message_files:
                name = files.get(fileid, 'name')
                mime_type = files.get(fileid, 'type')
                content = files.get(fileid, 'content')
                part = writer.nextpart()
                if mime_type == 'text/plain':
                    part.addheader('Content-Disposition',
                        'attachment;\n filename="%s"'%name)
                    part.addheader('Content-Transfer-Encoding', '7bit')
                    body = part.startbody('text/plain')
                    body.write(content)
                else:
                    # some other type, so encode it
                    if not mime_type:
                        # this should have been done when the file was saved
                        mime_type = mimetypes.guess_type(name)[0]
                    if mime_type is None:
                        mime_type = 'application/octet-stream'
                    part.addheader('Content-Disposition',
                        'attachment;\n filename="%s"'%name)
                    part.addheader('Content-Transfer-Encoding', 'base64')
                    body = part.startbody(mime_type)
                    body.write(base64.encodestring(content))
            writer.lastpart()
        else:
            writer.addheader('Content-Transfer-Encoding', 'quoted-printable')
            body = writer.startbody('text/plain')
            body.write(content_encoded)

        # now try to send the message
        if SENDMAILDEBUG:
            open(SENDMAILDEBUG, 'w').write('FROM: %s\nTO: %s\n%s\n'%(
                self.db.config.ADMIN_EMAIL,
                ', '.join(sendto),message.getvalue()))
        else:
            try:
                # send the message as admin so bounces are sent there
                # instead of to roundup
                smtp = smtplib.SMTP(self.db.config.MAILHOST)
                smtp.sendmail(self.db.config.ADMIN_EMAIL, sendto,
                    message.getvalue())
            except socket.error, value:
                raise MessageSendError, \
                    "Couldn't send confirmation email: mailhost %s"%value
            except smtplib.SMTPException, value:
                raise MessageSendError, \
                    "Couldn't send confirmation email: %s"%value

    def email_signature(self, nodeid, msgid):
        ''' Add a signature to the e-mail with some useful information
        '''

        # simplistic check to see if the url is valid,
        # then append a trailing slash if it is missing
        base = self.db.config.ISSUE_TRACKER_WEB 
        if not isinstance( base , type('') ) or not base.startswith( "http://" ) :
            base = "Configuration Error: ISSUE_TRACKER_WEB isn't a fully-qualified URL"
        elif base[-1] != '/' :
            base += '/'
        web = base + 'issue'+ nodeid

        # ensure the email address is properly quoted
        email = straddr( (self.db.config.INSTANCE_NAME ,
                          self.db.config.ISSUE_TRACKER_EMAIL) )

        line = '_' * max(len(web), len(email))
        return '%s\n%s\n%s\n%s'%(line, email, web, line)


    def generateCreateNote(self, nodeid):
        """Generate a create note that lists initial property values
        """
        cn = self.classname
        cl = self.db.classes[cn]
        props = cl.getprops(protected=0)

        # list the values
        m = []
        l = props.items()
        l.sort()
        for propname, prop in l:
            value = cl.get(nodeid, propname, None)
            # skip boring entries
            if not value:
                continue
            if isinstance(prop, hyperdb.Link):
                link = self.db.classes[prop.classname]
                if value:
                    key = link.labelprop(default_to_id=1)
                    if key:
                        value = link.get(value, key)
                else:
                    value = ''
            elif isinstance(prop, hyperdb.Multilink):
                if value is None: value = []
                l = []
                link = self.db.classes[prop.classname]
                key = link.labelprop(default_to_id=1)
                if key:
                    value = [link.get(entry, key) for entry in value]
                value.sort()
                value = ', '.join(value)
            m.append('%s: %s'%(propname, value))
        m.insert(0, '----------')
        m.insert(0, '')
        return '\n'.join(m)

    def generateChangeNote(self, nodeid, oldvalues):
        """Generate a change note that lists property changes
        """

        if __debug__ :
            if not isinstance( oldvalues , type({}) ) :
                raise TypeError(
                        "'oldvalues' must be dict-like, not %s."
                        % str(type(oldvalues)) )

        cn = self.classname
        cl = self.db.classes[cn]
        changed = {}
        props = cl.getprops(protected=0)

        # determine what changed
        for key in oldvalues.keys():
            if key in ['files','messages']: continue
            new_value = cl.get(nodeid, key)
            # the old value might be non existent
            try:
                old_value = oldvalues[key]
                if type(new_value) is type([]):
                    new_value.sort()
                    old_value.sort()
                if new_value != old_value:
                    changed[key] = old_value
            except:
                changed[key] = new_value

        # list the changes
        m = []
        l = changed.items()
        l.sort()
        for propname, oldvalue in l:
            prop = props[propname]
            value = cl.get(nodeid, propname, None)
            if isinstance(prop, hyperdb.Link):
                link = self.db.classes[prop.classname]
                key = link.labelprop(default_to_id=1)
                if key:
                    if value:
                        value = link.get(value, key)
                    else:
                        value = ''
                    if oldvalue:
                        oldvalue = link.get(oldvalue, key)
                    else:
                        oldvalue = ''
                change = '%s -> %s'%(oldvalue, value)
            elif isinstance(prop, hyperdb.Multilink):
                change = ''
                if value is None: value = []
                if oldvalue is None: oldvalue = []
                l = []
                link = self.db.classes[prop.classname]
                key = link.labelprop(default_to_id=1)
                # check for additions
                for entry in value:
                    if entry in oldvalue: continue
                    if key:
                        l.append(link.get(entry, key))
                    else:
                        l.append(entry)
                if l:
                    change = '+%s'%(', '.join(l))
                    l = []
                # check for removals
                for entry in oldvalue:
                    if entry in value: continue
                    if key:
                        l.append(link.get(entry, key))
                    else:
                        l.append(entry)
                if l:
                    change += ' -%s'%(', '.join(l))
            else:
                change = '%s -> %s'%(oldvalue, value)
            m.append('%s: %s'%(propname, change))
        if m:
            m.insert(0, '----------')
            m.insert(0, '')
        return '\n'.join(m)

#
# $Log: not supported by cvs2svn $
# Revision 1.58  2002/06/16 01:05:15  dman13
# Removed temporary workaround -- it seems it was a bug in the
# nosyreaction detector in the 0.4.1 extended template and has already
# been fixed in CVS.  We'll see.
#
# Revision 1.57  2002/06/15 15:49:29  dman13
# Use 'email' instead of 'rfc822', if available.
# Don't use isinstance() on a string (not allowed in python 2.1).
# Return an error message instead of crashing if 'oldvalues' isn't a
#     dict (in generateChangeNote).
#
# Revision 1.56  2002/06/14 03:54:21  dman13
# #565992 ] if ISSUE_TRACKER_WEB doesn't have the trailing '/', add it
#
# use the rfc822 module to ensure that every (oddball) email address and
# real-name is properly quoted
#
# Revision 1.55  2002/06/11 04:58:07  richard
# detabbing
#
# Revision 1.54  2002/05/29 01:16:17  richard
# Sorry about this huge checkin! It's fixing a lot of related stuff in one go
# though.
#
# . #541941 ] changing multilink properties by mail
# . #526730 ] search for messages capability
# . #505180 ] split MailGW.handle_Message
#   - also changed cgi client since it was duplicating the functionality
# . build htmlbase if tests are run using CVS checkout (removed note from
#   installation.txt)
# . don't create an empty message on email issue creation if the email is empty
#
# Revision 1.53  2002/05/25 07:16:24  rochecompaan
# Merged search_indexing-branch with HEAD
#
# Revision 1.52  2002/05/15 03:27:16  richard
#  . fixed SCRIPT_NAME in ZRoundup for instances not at top level of Zope
#    (thanks dman)
#  . fixed some sorting issues that were breaking some unit tests under py2.2
#  . mailgw test output dir was confusing the init test (but only on 2.2 *shrug*)
#
# fixed bug in the init unit test that meant only the bsddb test ran if it
# could (it clobbered the anydbm test)
#
# Revision 1.51  2002/04/08 03:46:42  richard
# make it work
#
# Revision 1.50  2002/04/08 03:40:31  richard
#  . added a "detectors" directory for people to put their useful auditors and
#    reactors in. Note - the roundupdb.IssueClass.sendmessage method has been
#    split and renamed "nosymessage" specifically for things like the nosy
#    reactor, and "send_message" which just sends the message.
#
# The initial detector is one that we'll be using here at ekit - it bounces new
# issue messages to a team address.
#
# Revision 1.49.2.1  2002/04/19 19:54:42  rochecompaan
# cgi_client.py
#     removed search link for the time being
#     moved rendering of matches to htmltemplate
# hyperdb.py
#     filtering of nodes on full text search incorporated in filter method
# roundupdb.py
#     added paramater to call of filter method
# roundup_indexer.py
#     added search method to RoundupIndexer class
#
# Revision 1.49  2002/03/19 06:41:49  richard
# Faster, easier, less mess ;)
#
# Revision 1.48  2002/03/18 18:32:00  rochecompaan
# All messages sent to the nosy list are now encoded as quoted-printable.
#
# Revision 1.47  2002/02/27 03:16:02  richard
# Fixed a couple of dodgy bits found by pychekcer.
#
# Revision 1.46  2002/02/25 14:22:59  grubert
#  . roundup db: catch only IOError in getfile.
#
# Revision 1.44  2002/02/15 07:08:44  richard
#  . Alternate email addresses are now available for users. See the MIGRATION
#    file for info on how to activate the feature.
#
# Revision 1.43  2002/02/14 22:33:15  richard
#  . Added a uniquely Roundup header to email, "X-Roundup-Name"
#
# Revision 1.42  2002/01/21 09:55:14  rochecompaan
# Properties in change note are now sorted
#
# Revision 1.41  2002/01/15 00:12:40  richard
# #503340 ] creating issue with [asignedto=p.ohly]
#
# Revision 1.40  2002/01/14 22:21:38  richard
# #503353 ] setting properties in initial email
#
# Revision 1.39  2002/01/14 02:20:15  richard
#  . changed all config accesses so they access either the instance or the
#    config attriubute on the db. This means that all config is obtained from
#    instance_config instead of the mish-mash of classes. This will make
#    switching to a ConfigParser setup easier too, I hope.
#
# At a minimum, this makes migration a _little_ easier (a lot easier in the
# 0.5.0 switch, I hope!)
#
# Revision 1.38  2002/01/10 05:57:45  richard
# namespace clobberation
#
# Revision 1.37  2002/01/08 04:12:05  richard
# Changed message-id format to "<%s.%s.%s%s@%s>" so it complies with RFC822
#
# Revision 1.36  2002/01/02 02:31:38  richard
# Sorry for the huge checkin message - I was only intending to implement #496356
# but I found a number of places where things had been broken by transactions:
#  . modified ROUNDUPDBSENDMAILDEBUG to be SENDMAILDEBUG and hold a filename
#    for _all_ roundup-generated smtp messages to be sent to.
#  . the transaction cache had broken the roundupdb.Class set() reactors
#  . newly-created author users in the mailgw weren't being committed to the db
#
# Stuff that made it into CHANGES.txt (ie. the stuff I was actually working
# on when I found that stuff :):
#  . #496356 ] Use threading in messages
#  . detectors were being registered multiple times
#  . added tests for mailgw
#  . much better attaching of erroneous messages in the mail gateway
#
# Revision 1.35  2001/12/20 15:43:01  rochecompaan
# Features added:
#  .  Multilink properties are now displayed as comma separated values in
#     a textbox
#  .  The add user link is now only visible to the admin user
#  .  Modified the mail gateway to reject submissions from unknown
#     addresses if ANONYMOUS_ACCESS is denied
#
# Revision 1.34  2001/12/17 03:52:48  richard
# Implemented file store rollback. As a bonus, the hyperdb is now capable of
# storing more than one file per node - if a property name is supplied,
# the file is called designator.property.
# I decided not to migrate the existing files stored over to the new naming
# scheme - the FileClass just doesn't specify the property name.
#
# Revision 1.33  2001/12/16 10:53:37  richard
# take a copy of the node dict so that the subsequent set
# operation doesn't modify the oldvalues structure
#
# Revision 1.32  2001/12/15 23:48:35  richard
# Added ROUNDUPDBSENDMAILDEBUG so one can test the sendmail method without
# actually sending mail :)
#
# Revision 1.31  2001/12/15 19:24:39  rochecompaan
#  . Modified cgi interface to change properties only once all changes are
#    collected, files created and messages generated.
#  . Moved generation of change note to nosyreactors.
#  . We now check for changes to "assignedto" to ensure it's added to the
#    nosy list.
#
# Revision 1.30  2001/12/12 21:47:45  richard
#  . Message author's name appears in From: instead of roundup instance name
#    (which still appears in the Reply-To:)
#  . envelope-from is now set to the roundup-admin and not roundup itself so
#    delivery reports aren't sent to roundup (thanks Patrick Ohly)
#
# Revision 1.29  2001/12/11 04:50:49  richard
# fixed the order of the blank line and '-------' line
#
# Revision 1.28  2001/12/10 22:20:01  richard
# Enabled transaction support in the bsddb backend. It uses the anydbm code
# where possible, only replacing methods where the db is opened (it uses the
# btree opener specifically.)
# Also cleaned up some change note generation.
# Made the backends package work with pydoc too.
#
# Revision 1.27  2001/12/10 21:02:53  richard
# only insert the -------- change note marker if there is a change note
#
# Revision 1.26  2001/12/05 14:26:44  rochecompaan
# Removed generation of change note from "sendmessage" in roundupdb.py.
# The change note is now generated when the message is created.
#
# Revision 1.25  2001/11/30 20:28:10  rochecompaan
# Property changes are now completely traceable, whether changes are
# made through the web or by email
#
# Revision 1.24  2001/11/30 11:29:04  rochecompaan
# Property changes are now listed in emails generated by Roundup
#
# Revision 1.23  2001/11/27 03:17:13  richard
# oops
#
# Revision 1.22  2001/11/27 03:00:50  richard
# couple of bugfixes from latest patch integration
#
# Revision 1.21  2001/11/26 22:55:56  richard
# Feature:
#  . Added INSTANCE_NAME to configuration - used in web and email to identify
#    the instance.
#  . Added EMAIL_SIGNATURE_POSITION to indicate where to place the roundup
#    signature info in e-mails.
#  . Some more flexibility in the mail gateway and more error handling.
#  . Login now takes you to the page you back to the were denied access to.
#
# Fixed:
#  . Lots of bugs, thanks Roché and others on the devel mailing list!
#
# Revision 1.20  2001/11/25 10:11:14  jhermann
# Typo fix
#
# Revision 1.19  2001/11/22 15:46:42  jhermann
# Added module docstrings to all modules.
#
# Revision 1.18  2001/11/15 10:36:17  richard
#  . incorporated patch from Roch'e Compaan implementing attachments in nosy
#     e-mail
#
# Revision 1.17  2001/11/12 22:01:06  richard
# Fixed issues with nosy reaction and author copies.
#
# Revision 1.16  2001/10/30 00:54:45  richard
# Features:
#  . #467129 ] Lossage when username=e-mail-address
#  . #473123 ] Change message generation for author
#  . MailGW now moves 'resolved' to 'chatting' on receiving e-mail for an issue.
#
# Revision 1.15  2001/10/23 01:00:18  richard
# Re-enabled login and registration access after lopping them off via
# disabling access for anonymous users.
# Major re-org of the htmltemplate code, cleaning it up significantly. Fixed
# a couple of bugs while I was there. Probably introduced a couple, but
# things seem to work OK at the moment.
#
# Revision 1.14  2001/10/21 07:26:35  richard
# feature #473127: Filenames. I modified the file.index and htmltemplate
#  source so that the filename is used in the link and the creation
#  information is displayed.
#
# Revision 1.13  2001/10/21 00:45:15  richard
# Added author identification to e-mail messages from roundup.
#
# Revision 1.12  2001/10/04 02:16:15  richard
# Forgot to pass the protected flag down *sigh*.
#
# Revision 1.11  2001/10/04 02:12:42  richard
# Added nicer command-line item adding: passing no arguments will enter an
# interactive more which asks for each property in turn. While I was at it, I
# fixed an implementation problem WRT the spec - I wasn't raising a
# ValueError if the key property was missing from a create(). Also added a
# protected=boolean argument to getprops() so we can list only the mutable
# properties (defaults to yes, which lists the immutables).
#
# Revision 1.10  2001/08/07 00:24:42  richard
# stupid typo
#
# Revision 1.9  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.8  2001/08/02 06:38:17  richard
# Roundupdb now appends "mailing list" information to its messages which
# include the e-mail address and web interface address. Templates may
# override this in their db classes to include specific information (support
# instructions, etc).
#
# Revision 1.7  2001/07/30 02:38:31  richard
# get() now has a default arg - for migration only.
#
# Revision 1.6  2001/07/30 00:05:54  richard
# Fixed IssueClass so that superseders links to its classname rather than
# hard-coded to "issue".
#
# Revision 1.5  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.4  2001/07/29 04:05:37  richard
# Added the fabricated property "id".
#
# Revision 1.3  2001/07/23 07:14:41  richard
# Moved the database backends off into backends.
#
# Revision 1.2  2001/07/22 12:09:32  richard
# Final commit of Grande Splite
#
# Revision 1.1  2001/07/22 11:58:35  richard
# More Grande Splite
#
#
# vim: set filetype=python ts=4 sw=4 et si
