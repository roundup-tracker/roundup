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
# $Id: roundupdb.py,v 1.91 2003-09-16 16:12:38 kedder Exp $

__doc__ = """
Extending hyperdb with types specific to issue-tracking.
"""

import re, os, smtplib, socket, time, random
import cStringIO, base64, quopri, mimetypes

from rfc2822 import encode_header

from roundup import password, date, hyperdb

# MessageSendError is imported for backwards compatibility
from roundup.mailer import Mailer, straddr, MessageSendError

class Database:
    def getuid(self):
        """Return the id of the "user" node associated with the user
        that owns this connection to the hyperdatabase."""
        if self.journaltag is None:
            return None
        elif self.journaltag == 'admin':
            # admin user may not exist, but always has ID 1
            return '1'
        else:
            return self.user.lookup(self.journaltag)

    def getUserTimezone(self):
        """Return user timezone defined in 'timezone' property of user class.
        If no such property exists return 0
        """
        userid = self.getuid()
        try:
            timezone = int(self.user.get(userid, 'timezone'))
        except (KeyError, ValueError, TypeError):
            # If there is no class 'user' or current user doesn't have timezone 
            # property or that property is not numeric assume he/she lives in 
            # Greenwich :)
            timezone = 0
        return timezone

    def confirm_registration(self, otk):
        props = self.otks.getall(otk)
        for propname, proptype in self.user.getprops().items():
            value = props.get(propname, None)
            if value is None:
                pass
            elif isinstance(proptype, hyperdb.Date):
                props[propname] = date.Date(value)
            elif isinstance(proptype, hyperdb.Interval):
                props[propname] = date.Interval(value)
            elif isinstance(proptype, hyperdb.Password):
                props[propname] = password.Password()
                props[propname].unpack(value)

        # tag new user creation with 'admin'
        self.journaltag = 'admin'

        # create the new user
        cl = self.user
      
        props['roles'] = self.config.NEW_WEB_USER_ROLES
        del props['__time']
        userid = cl.create(**props)
        # clear the props from the otk database
        self.otks.destroy(otk)
        self.commit()
        
        return userid


class DetectorError(RuntimeError):
    """ Raised by detectors that want to indicate that something's amiss
    """
    pass

# deviation from spec - was called IssueClass
class IssueClass:
    """ This class is intended to be mixed-in with a hyperdb backend
        implementation. The backend should provide a mechanism that
        enforces the title, messages, files, nosy and superseder
        properties:
            properties['title'] = hyperdb.String(indexme='yes')
            properties['messages'] = hyperdb.Multilink("msg")
            properties['files'] = hyperdb.Multilink("file")
            properties['nosy'] = hyperdb.Multilink("user")
            properties['superseder'] = hyperdb.Multilink(classname)
    """

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

    # XXX "bcc" is an optional extra here...
    def nosymessage(self, nodeid, msgid, oldvalues, whichnosy='nosy',
            from_address=None, cc=[]): #, bcc=[]):
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
        if (users.get(authid, 'username') != 'anonymous' and
                not r.has_key(authid)):
            if (self.db.config.MESSAGES_TO_AUTHOR == 'yes' or
                (self.db.config.MESSAGES_TO_AUTHOR == 'new' and not oldvalues)):
                # make sure they have an address
                add = users.get(authid, 'address')
                if add:
                    # send it to them
                    sendto.append(add)
                    recipients.append(authid)

        r[authid] = 1

        # now deal with cc people.
        for cc_userid in cc :
            if r.has_key(cc_userid):
                continue
            # make sure they have an address
            add = users.get(cc_userid, 'address')
            if add:
                # send it to them
                sendto.append(add)
                recipients.append(cc_userid)

        # now figure the nosy people who weren't recipients
        nosy = self.get(nodeid, whichnosy)
        for nosyid in nosy:
            # Don't send nosy mail to the anonymous user (that user
            # shouldn't appear in the nosy list, but just in case they
            # do...)
            if users.get(nosyid, 'username') == 'anonymous':
                continue
            # make sure they haven't seen the message already
            if not r.has_key(nosyid):
                # make sure they have an address
                add = users.get(nosyid, 'address')
                if add:
                    # send it to them
                    sendto.append(add)
                    recipients.append(nosyid)

        # generate a change note
        if oldvalues:
            note = self.generateChangeNote(nodeid, oldvalues)
        else:
            note = self.generateCreateNote(nodeid)

        # we have new recipients
        if sendto:
            # update the message's recipients list
            messages.set(msgid, recipients=recipients)

            # send the message
            self.send_message(nodeid, msgid, note, sendto, from_address)

    # backwards compatibility - don't remove
    sendmessage = nosymessage

    def send_message(self, nodeid, msgid, note, sendto, from_address=None):
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

        # make sure we have a from address
        if from_address is None:
            from_address = self.db.config.TRACKER_EMAIL

        # additional bit for after the From: "name"
        from_tag = getattr(self.db.config, 'EMAIL_FROM_TAG', '')
        if from_tag:
            from_tag = ' ' + from_tag

        subject = '[%s%s] %s' % (cn, nodeid, encode_header(title))
        author = straddr((encode_header(authname) + from_tag, from_address))

        # create the message
        mailer = Mailer(self.db.config)
        message, writer = mailer.get_standard_message(', '.join(sendto),
                                                      subject, author)

        tracker_name = encode_header(self.db.config.TRACKER_NAME)
        writer.addheader('Reply-To', straddr((tracker_name, from_address)))
        if messageid:
            writer.addheader('Message-Id', messageid)
        if inreplyto:
            writer.addheader('In-Reply-To', inreplyto)

        # attach files
        if message_files:
            part = writer.startmultipartbody('mixed')
            part = writer.nextpart()
            part.addheader('Content-Transfer-Encoding', 'quoted-printable')
            body = part.startbody('text/plain; charset=utf-8')
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
            body = writer.startbody('text/plain; charset=utf-8')
            body.write(content_encoded)

        mailer.smtp_send(sendto, message)

    def email_signature(self, nodeid, msgid):
        ''' Add a signature to the e-mail with some useful information
        '''
        # simplistic check to see if the url is valid,
        # then append a trailing slash if it is missing
        base = self.db.config.TRACKER_WEB 
        if (not isinstance(base , type('')) or
            not (base.startswith('http://') or base.startswith('https://'))):
            base = "Configuration Error: TRACKER_WEB isn't a " \
                "fully-qualified URL"
        elif base[-1] != '/' :
            base += '/'
        web = base + self.classname + nodeid

        # ensure the email address is properly quoted
        email = straddr((self.db.config.TRACKER_NAME,
            self.db.config.TRACKER_EMAIL))

        line = '_' * max(len(web)+2, len(email))
        return '%s\n%s\n<%s>\n%s'%(line, email, web, line)


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
            if not isinstance(oldvalues, type({})) :
                raise TypeError("'oldvalues' must be dict-like, not %s."%
                    type(oldvalues))

        cn = self.classname
        cl = self.db.classes[cn]
        changed = {}
        props = cl.getprops(protected=0)

        # determine what changed
        for key in oldvalues.keys():
            if key in ['files','messages']:
                continue
            if key in ('activity', 'creator', 'creation'):
                continue
            # not all keys from oldvalues might be available in database
            # this happens when property was deleted
            try:                
                new_value = cl.get(nodeid, key)
            except KeyError:
                continue
            # the old value might be non existent
            # this happens when property was added
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
                    l.sort()
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
                    l.sort()
                    change += ' -%s'%(', '.join(l))
            else:
                change = '%s -> %s'%(oldvalue, value)
            m.append('%s: %s'%(propname, change))
        if m:
            m.insert(0, '----------')
            m.insert(0, '')
        return '\n'.join(m)

# vim: set filetype=python ts=4 sw=4 et si
