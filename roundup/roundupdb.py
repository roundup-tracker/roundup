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
# $Id: roundupdb.py,v 1.12 2001-10-04 02:16:15 richard Exp $

import re, os, smtplib, socket

import hyperdb, date

def splitDesignator(designator, dre=re.compile(r'([^\d]+)(\d+)')):
    ''' Take a foo123 and return ('foo', 123)
    '''
    m = dre.match(designator)
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
        if users: return users[0]
        return self.user.create(username=address, address=address,
            realname=realname)

_marker = []
# XXX: added the 'creator' faked attribute
class Class(hyperdb.Class):
    # Overridden methods:
    def __init__(self, db, classname, **properties):
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
        if (properties.has_key('creation') or properties.has_key('activity')
                or properties.has_key('creator')):
            raise ValueError, '"creation", "activity" and "creator" are reserved'
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
        authid = self.db.msg.get(msgid, 'author')
        r[authid] = 1

        # now figure the nosy people who weren't recipients
        sendto = []
        nosy = self.get(nodeid, 'nosy')
        for nosyid in nosy:
            if not r.has_key(nosyid):
                sendto.append(nosyid)
                recipients.append(nosyid)

        if sendto:
            # update the message's recipients list
            self.db.msg.set(msgid, recipients=recipients)

            # send an email to the people who missed out
            sendto = [self.db.user.get(i, 'address') for i in recipients]
            cn = self.classname
            title = self.get(nodeid, 'title') or '%s message copy'%cn
            m = ['Subject: [%s%s] %s'%(cn, nodeid, title)]
            m.append('To: %s'%', '.join(sendto))
            m.append('Reply-To: %s'%self.ISSUE_TRACKER_EMAIL)
            m.append('')
            m.append(self.db.msg.get(msgid, 'content'))
            m.append(self.email_footer(nodeid, msgid))
            # TODO attachments
            try:
                smtp = smtplib.SMTP(self.MAILHOST)
                smtp.sendmail(self.ISSUE_TRACKER_EMAIL, sendto, '\n'.join(m))
            except socket.error, value:
                return "Couldn't send confirmation email: mailhost %s"%value
            except smtplib.SMTPException, value:
                return "Couldn't send confirmation email: %s"%value

    def email_footer(self, nodeid, msgid):
        ''' Add a footer to the e-mail with some useful information
        '''
        web = self.ISSUE_TRACKER_WEB
        return '''%s
Roundup issue tracker
%s
%s
'''%('_'*len(web), self.ISSUE_TRACKER_EMAIL, web)

#
# $Log: not supported by cvs2svn $
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
