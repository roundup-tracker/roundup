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
# $Id: roundupdb.py,v 1.27 2001-12-10 21:02:53 richard Exp $

__doc__ = """
Extending hyperdb with types specific to issue-tracking.
"""

import re, os, smtplib, socket
import mimetools, MimeWriter, cStringIO
import base64, mimetypes

import hyperdb, date

class DesignatorError(ValueError):
    pass
def splitDesignator(designator, dre=re.compile(r'([^\d]+)(\d+)')):
    ''' Take a foo123 and return ('foo', 123)
    '''
    m = dre.match(designator)
    if m is None:
        raise DesignatorError, '"%s" not a node designator'%designator
    return m.group(1), m.group(2)


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
        users = self.user.stringFind(address=address)
        for dummy in range(2):
            if len(users) > 1:
                # make sure we don't match the anonymous or admin user
                for user in users:
                    if user == '1': continue
                    if self.user.get(user, 'username') == 'anonymous': continue
                    # first valid match will do
                    return user
                # well, I guess we have no choice
                return user[0]
            elif users:
                return users[0]
            # try to match the username to the address (for local
            # submissions where the address is empty)
            users = self.user.stringFind(username=address)

        # couldn't match address or username, so create a new user
        return self.user.create(username=address, address=address,
            realname=realname)

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
        for audit in self.auditors['create']:
            audit(self.db, self, None, propvalues)
        nodeid = hyperdb.Class.create(self, **propvalues)
        for react in self.reactors['create']:
            react(self.db, self, nodeid, None)
        return nodeid

    def set(self, nodeid, **propvalues):
        """These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        """
        if propvalues.has_key('creation') or propvalues.has_key('activity'):
            raise KeyError, '"creation" and "activity" are reserved'
        for audit in self.auditors['set']:
            audit(self.db, self, nodeid, propvalues)
        oldvalues = self.db.getnode(self.classname, nodeid)
        hyperdb.Class.set(self, nodeid, **propvalues)
        for react in self.reactors['set']:
            react(self.db, self, nodeid, oldvalues)

    def retire(self, nodeid):
        """These operations trigger detectors and can be vetoed.  Attempts
        to modify the "creation" or "activity" properties cause a KeyError.
        """
        for audit in self.auditors['retire']:
            audit(self.db, self, nodeid, None)
        hyperdb.Class.retire(self, nodeid)
        for react in self.reactors['retire']:
            react(self.db, self, nodeid, None)

    def get(self, nodeid, propname, default=_marker):
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
            return hyperdb.Class.get(self, nodeid, propname, default)
        else:
            return hyperdb.Class.get(self, nodeid, propname)

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
        self.auditors[event].append(detector)

    def react(self, event, detector):
        """Register a detector
        """
        self.reactors[event].append(detector)


class FileClass(Class):
    def create(self, **propvalues):
        ''' snaffle the file propvalue and store in a file
        '''
        content = propvalues['content']
        del propvalues['content']
        newid = Class.create(self, **propvalues)
        self.setcontent(self.classname, newid, content)
        return newid

    def filename(self, classname, nodeid):
        # TODO: split into multiple files directories
        return os.path.join(self.db.dir, 'files', '%s%s'%(classname, nodeid))

    def setcontent(self, classname, nodeid, content):
        ''' set the content file for this file
        '''
        open(self.filename(classname, nodeid), 'wb').write(content)

    def getcontent(self, classname, nodeid):
        ''' get the content file for this file
        '''
        return open(self.filename(classname, nodeid), 'rb').read()

    def get(self, nodeid, propname, default=_marker):
        ''' trap the content propname and get it from the file
        '''
        if propname == 'content':
            return self.getcontent(self.classname, nodeid)
        if default is not _marker:
            return Class.get(self, nodeid, propname, default)
        else:
            return Class.get(self, nodeid, propname)

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
    # configuration
    MESSAGES_TO_AUTHOR = 'no'
    INSTANCE_NAME = 'Roundup issue tracker'
    EMAIL_SIGNATURE_POSITION = 'bottom'

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

    def sendmessage(self, nodeid, msgid):
        """Send a message to the members of an issue's nosy list.

        The message is sent only to users on the nosy list who are not
        already on the "recipients" list for the message.
        
        These users are then added to the message's "recipients" list.
        """
        # figure the recipient ids
        recipients = self.db.msg.get(msgid, 'recipients')
        r = {}
        for recipid in recipients:
            r[recipid] = 1
        rlen = len(recipients)

        # figure the author's id, and indicate they've received the message
        authid = self.db.msg.get(msgid, 'author')

        # get the current nosy list, we'll need it
        nosy = self.get(nodeid, 'nosy')

        # ... but duplicate the message to the author as long as it's not
        # the anonymous user
        if (self.MESSAGES_TO_AUTHOR == 'yes' and
                self.db.user.get(authid, 'username') != 'anonymous'):
            if not r.has_key(authid):
                recipients.append(authid)
        r[authid] = 1

        # now figure the nosy people who weren't recipients
        for nosyid in nosy:
            # Don't send nosy mail to the anonymous user (that user
            # shouldn't appear in the nosy list, but just in case they
            # do...)
            if self.db.user.get(nosyid, 'username') == 'anonymous': continue
            if not r.has_key(nosyid):
                recipients.append(nosyid)

        # no new recipients
        if rlen == len(recipients):
            return

        # update the message's recipients list
        self.db.msg.set(msgid, recipients=recipients)

        # send an email to the people who missed out
        sendto = [self.db.user.get(i, 'address') for i in recipients]
        cn = self.classname
        title = self.get(nodeid, 'title') or '%s message copy'%cn
        # figure author information
        authname = self.db.user.get(authid, 'realname')
        if not authname:
            authname = self.db.user.get(authid, 'username')
        authaddr = self.db.user.get(authid, 'address')
        if authaddr:
            authaddr = ' <%s>'%authaddr
        else:
            authaddr = ''

        # make the message body
        m = ['']

        # put in roundup's signature
        if self.EMAIL_SIGNATURE_POSITION == 'top':
            m.append(self.email_signature(nodeid, msgid))

        # add author information
        if len(self.get(nodeid,'messages')) == 1:
            m.append("New submission from %s%s:"%(authname, authaddr))
        else:
            m.append("%s%s added the comment:"%(authname, authaddr))
        m.append('')

        # add the content
        m.append(self.db.msg.get(msgid, 'content'))

        # put in roundup's signature
        if self.EMAIL_SIGNATURE_POSITION == 'bottom':
            m.append(self.email_signature(nodeid, msgid))

        # get the files for this message
        files = self.db.msg.get(msgid, 'files')

        # create the message
        message = cStringIO.StringIO()
        writer = MimeWriter.MimeWriter(message)
        writer.addheader('Subject', '[%s%s] %s'%(cn, nodeid, title))
        writer.addheader('To', ', '.join(sendto))
        writer.addheader('From', '%s <%s>'%(self.INSTANCE_NAME,
            self.ISSUE_TRACKER_EMAIL))
        writer.addheader('Reply-To', '%s <%s>'%(self.INSTANCE_NAME,
            self.ISSUE_TRACKER_EMAIL))
        writer.addheader('MIME-Version', '1.0')

        # attach files
        if files:
            part = writer.startmultipartbody('mixed')
            part = writer.nextpart()
            body = part.startbody('text/plain')
            body.write('\n'.join(m))
            for fileid in files:
                name = self.db.file.get(fileid, 'name')
                mime_type = self.db.file.get(fileid, 'type')
                content = self.db.file.get(fileid, 'content')
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
            body = writer.startbody('text/plain')
            body.write('\n'.join(m))

        # now try to send the message
        try:
            smtp = smtplib.SMTP(self.MAILHOST)
            smtp.sendmail(self.ISSUE_TRACKER_EMAIL, sendto, message.getvalue())
        except socket.error, value:
            raise MessageSendError, \
                "Couldn't send confirmation email: mailhost %s"%value
        except smtplib.SMTPException, value:
            raise MessageSendError, \
                "Couldn't send confirmation email: %s"%value

    def email_signature(self, nodeid, msgid):
        ''' Add a signature to the e-mail with some useful information
        '''
        web = self.ISSUE_TRACKER_WEB + 'issue'+ nodeid
        email = '"%s" <%s>'%(self.INSTANCE_NAME, self.ISSUE_TRACKER_EMAIL)
        line = '_' * max(len(web), len(email))
        return '%s\n%s\n%s\n%s'%(line, email, web, line)

    def generateChangeNote(self, nodeid, newvalues):
        """Generate a change note that lists property changes
        """
        cn = self.classname
        cl = self.db.classes[cn]
        changed = {}
        props = cl.getprops(protected=0)

        # determine what changed
        for key in newvalues.keys():
            if key in ['files','messages']: continue
            new_value = newvalues[key]
            # the old value might be non existent
            try:
                old_value = cl.get(nodeid, key)
                if type(old_value) is type([]):
                    old_value.sort()
                    new_value.sort()
                if old_value != new_value:
                    changed[key] = new_value
            except:
                changed[key] = new_value

        # list the changes
        for propname, value in changed.items():
            prop = cl.properties[propname]
            oldvalue = cl.get(nodeid, propname, None)
            change = '%s -> %s'%(oldvalue, value)
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
            m.append('%s: %s'%(propname, change))
        if m:
            m.insert(0, '')
            m.insert(0, '----------')
        return '\n'.join(m)

#
# $Log: not supported by cvs2svn $
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
