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

__doc__ = '''
An e-mail gateway for Roundup.

Incoming messages are examined for multiple parts:
 . In a multipart/mixed message or part, each subpart is extracted and
   examined. The text/plain subparts are assembled to form the textual
   body of the message, to be stored in the file associated with a "msg"
   class node. Any parts of other types are each stored in separate files
   and given "file" class nodes that are linked to the "msg" node. 
 . In a multipart/alternative message or part, we look for a text/plain
   subpart and ignore the other parts.

Summary
-------
The "summary" property on message nodes is taken from the first non-quoting
section in the message body. The message body is divided into sections by
blank lines. Sections where the second and all subsequent lines begin with
a ">" or "|" character are considered "quoting sections". The first line of
the first non-quoting section becomes the summary of the message. 

Addresses
---------
All of the addresses in the To: and Cc: headers of the incoming message are
looked up among the user nodes, and the corresponding users are placed in
the "recipients" property on the new "msg" node. The address in the From:
header similarly determines the "author" property of the new "msg"
node. The default handling for addresses that don't have corresponding
users is to create new users with no passwords and a username equal to the
address. (The web interface does not permit logins for users with no
passwords.) If we prefer to reject mail from outside sources, we can simply
register an auditor on the "user" class that prevents the creation of user
nodes with no passwords. 

Actions
-------
The subject line of the incoming message is examined to determine whether
the message is an attempt to create a new item or to discuss an existing
item. A designator enclosed in square brackets is sought as the first thing
on the subject line (after skipping any "Fwd:" or "Re:" prefixes). 

If an item designator (class name and id number) is found there, the newly
created "msg" node is added to the "messages" property for that item, and
any new "file" nodes are added to the "files" property for the item. 

If just an item class name is found there, we attempt to create a new item
of that class with its "messages" property initialized to contain the new
"msg" node and its "files" property initialized to contain any new "file"
nodes. 

Triggers
--------
Both cases may trigger detectors (in the first case we are calling the
set() method to add the message to the item's spool; in the second case we
are calling the create() method to create a new node). If an auditor raises
an exception, the original message is bounced back to the sender with the
explanatory message given in the exception. 

$Id: mailgw.py,v 1.43 2001-12-15 19:39:01 rochecompaan Exp $
'''


import string, re, os, mimetools, cStringIO, smtplib, socket, binascii, quopri
import traceback, MimeWriter
import hyperdb, date, password

class MailGWError(ValueError):
    pass

class MailUsageError(ValueError):
    pass

class Message(mimetools.Message):
    ''' subclass mimetools.Message so we can retrieve the parts of the
        message...
    '''
    def getPart(self):
        ''' Get a single part of a multipart message and return it as a new
            Message instance.
        '''
        boundary = self.getparam('boundary')
        mid, end = '--'+boundary, '--'+boundary+'--'
        s = cStringIO.StringIO()
        while 1:
            line = self.fp.readline()
            if not line:
                break
            if line.strip() in (mid, end):
                break
            s.write(line)
        if not s.getvalue().strip():
            return None
        s.seek(0)
        return Message(s)

subject_re = re.compile(r'(?P<refwd>\s*\W?\s*(fwd|re)\s*\W?\s*)*'
    r'\s*(\[(?P<classname>[^\d\s]+)(?P<nodeid>\d+)?\])'
    r'\s*(?P<title>[^[]+)?(\[(?P<args>.+?)\])?', re.I)

class MailGW:
    def __init__(self, instance, db):
        self.instance = instance
        self.db = db

    def main(self, fp):
        ''' fp - the file from which to read the Message.
        '''
        self.handle_Message(Message(fp))

    def handle_Message(self, message):
        '''Handle an RFC822 Message

        Handle the Message object by calling handle_message() and then cope
        with any errors raised by handle_message.
        This method's job is to make that call and handle any
        errors in a sane manner. It should be replaced if you wish to
        handle errors in a different manner.
        '''
        # in some rare cases, a particularly stuffed-up e-mail will make
        # its way into here... try to handle it gracefully
        sendto = message.getaddrlist('from')
        if sendto:
            try:
                return self.handle_message(message)
            except MailUsageError, value:
                # bounce the message back to the sender with the usage message
                fulldoc = '\n'.join(string.split(__doc__, '\n')[2:])
                sendto = [sendto[0][1]]
                m = ['']
                m.append(str(value))
                m.append('\n\nMail Gateway Help\n=================')
                m.append(fulldoc)
                m = self.bounce_message(message, sendto, m)
            except:
                # bounce the message back to the sender with the error message
                sendto = [sendto[0][1]]
                m = ['']
                m.append('----  traceback of failure  ----')
                s = cStringIO.StringIO()
                import traceback
                traceback.print_exc(None, s)
                m.append(s.getvalue())
                m = self.bounce_message(message, sendto, m)
        else:
            # very bad-looking message - we don't even know who sent it
            sendto = [self.ADMIN_EMAIL]
            m = ['Subject: badly formed message from mail gateway']
            m.append('')
            m.append('The mail gateway retrieved a message which has no From:')
            m.append('line, indicating that it is corrupt. Please check your')
            m.append('mail gateway source. Failed message is attached.')
            m.append('')
            m = self.bounce_message(message, sendto, m,
                subject='Badly formed message from mail gateway')

        # now send the message
        try:
            smtp = smtplib.SMTP(self.MAILHOST)
            smtp.sendmail(self.ADMIN_EMAIL, sendto, m.getvalue())
        except socket.error, value:
            raise MailGWError, "Couldn't send confirmation email: "\
                "mailhost %s"%value
        except smtplib.SMTPException, value:
            raise MailGWError, "Couldn't send confirmation email: %s"%value

    def bounce_message(self, message, sendto, error,
            subject='Failed issue tracker submission'):
        ''' create a message that explains the reason for the failed
            issue submission to the author and attach the original
            message.
        '''
        msg = cStringIO.StringIO()
        writer = MimeWriter.MimeWriter(msg)
        writer.addheader('Subject', subject)
        writer.addheader('From', '%s <%s>'% (self.instance.INSTANCE_NAME,
                                            self.ISSUE_TRACKER_EMAIL))
        writer.addheader('To', ','.join(sendto))
        writer.addheader('MIME-Version', '1.0')
        part = writer.startmultipartbody('mixed')
        part = writer.nextpart()
        body = part.startbody('text/plain')
        body.write('\n'.join(error))

        # reconstruct the original message
        m = cStringIO.StringIO()
        w = MimeWriter.MimeWriter(m)
        for header in message.headers:
            header_name = header.split(':')[0]
            if message.getheader(header_name):
                w.addheader(header_name,message.getheader(header_name))
        body = w.startbody('text/plain')
        try:
            message.fp.seek(0)
        except:
            pass
        body.write(message.fp.read())

        # attach the original message to the returned message
        part = writer.nextpart()
        part.addheader('Content-Disposition','attachment')
        part.addheader('Content-Transfer-Encoding', '7bit')
        body = part.startbody('message/rfc822')
        body.write(m.getvalue())

        writer.lastpart()
        return msg

    def handle_message(self, message):
        ''' message - a Message instance

        Parse the message as per the module docstring.
        '''
        # handle the subject line
        subject = message.getheader('subject', '')
        m = subject_re.match(subject)
        if not m:
            raise MailUsageError, '''
The message you sent to roundup did not contain a properly formed subject
line. The subject must contain a class name or designator to indicate the
"topic" of the message. For example:
    Subject: [issue] This is a new issue
      - this will create a new issue in the tracker with the title "This is
        a new issue".
    Subject: [issue1234] This is a followup to issue 1234
      - this will append the message's contents to the existing issue 1234
        in the tracker.

Subject was: "%s"
'''%subject

        # get the classname
        classname = m.group('classname')
        try:
            cl = self.db.getclass(classname)
        except KeyError:
            raise MailUsageError, '''
The class name you identified in the subject line ("%s") does not exist in the
database.

Valid class names are: %s
Subject was: "%s"
'''%(classname, ', '.join(self.db.getclasses()), subject)

        # get the optional nodeid
        nodeid = m.group('nodeid')

        # title is optional too
        title = m.group('title')
        if title:
            title = title.strip()
        else:
            title = ''

        # but we do need either a title or a nodeid...
        if not nodeid and not title:
            raise MailUsageError, '''
I cannot match your message to a node in the database - you need to either
supply a full node identifier (with number, eg "[issue123]" or keep the
previous subject title intact so I can match that.

Subject was: "%s"
'''%subject

        # extract the args
        subject_args = m.group('args')

        # If there's no nodeid, check to see if this is a followup and
        # maybe someone's responded to the initial mail that created an
        # entry. Try to find the matching nodes with the same title, and
        # use the _last_ one matched (since that'll _usually_ be the most
        # recent...)
        if not nodeid and m.group('refwd'):
            l = cl.stringFind(title=title)
            if l:
                nodeid = l[-1]

        # start of the props
        properties = cl.getprops()
        props = {}

        # handle the args
        args = m.group('args')
        if args:
            for prop in string.split(args, ';'):
                try:
                    key, value = prop.split('=')
                except ValueError, message:
                    raise MailUsageError, '''
Subject argument list not of form [arg=value,value,...;arg=value,value...]
   (specific exception message was "%s")

Subject was: "%s"
'''%(message, subject)
                key = key.strip()
                try:
                    proptype =  properties[key]
                except KeyError:
                    raise MailUsageError, '''
Subject argument list refers to an invalid property: "%s"

Subject was: "%s"
'''%(key, subject)
                if isinstance(proptype, hyperdb.String):
                    props[key] = value.strip()
                if isinstance(proptype, hyperdb.Password):
                    props[key] = password.Password(value.strip())
                elif isinstance(proptype, hyperdb.Date):
                    try:
                        props[key] = date.Date(value.strip())
                    except ValueError, message:
                        raise UsageError, '''
Subject argument list contains an invalid date for %s.

Error was: %s
Subject was: "%s"
'''%(key, message, subject)
                elif isinstance(proptype, hyperdb.Interval):
                    try:
                        props[key] = date.Interval(value) # no strip needed
                    except ValueError, message:
                        raise UsageError, '''
Subject argument list contains an invalid date interval for %s.

Error was: %s
Subject was: "%s"
'''%(key, message, subject)
                elif isinstance(proptype, hyperdb.Link):
                    link = self.db.classes[proptype.classname]
                    propkey = link.labelprop(default_to_id=1)
                    try:
                        props[key] = link.get(value.strip(), propkey)
                    except:
                        props[key] = link.lookup(value.strip())
                elif isinstance(proptype, hyperdb.Multilink):
                    link = self.db.classes[proptype.classname]
                    propkey = link.labelprop(default_to_id=1)
                    l = [x.strip() for x in value.split(',')]
                    for item in l:
                        try:
                            v = link.get(item, propkey)
                        except:
                            v = link.lookup(item)
                        if props.has_key(key):
                            props[key].append(v)
                        else:
                            props[key] = [v]


        #
        # handle the users
        #
        author = self.db.uidFromAddress(message.getaddrlist('from')[0])
        # reopen the database as the author
        username = self.db.user.get(author, 'username')
        self.db = self.instance.open(username)

        # re-get the class with the new database connection
        cl = self.db.getclass(classname)

        # now update the recipients list
        recipients = []
        tracker_email = self.ISSUE_TRACKER_EMAIL.lower()
        for recipient in message.getaddrlist('to') + message.getaddrlist('cc'):
            if recipient[1].strip().lower() == tracker_email:
                continue
            recipients.append(self.db.uidFromAddress(recipient))

        # now handle the body - find the message
        content_type =  message.gettype()
        attachments = []
        if content_type == 'multipart/mixed':
            # skip over the intro to the first boundary
            part = message.getPart()
            content = None
            while 1:
                # get the next part
                part = message.getPart()
                if part is None:
                    break
                # parse it
                subtype = part.gettype()
                if subtype == 'text/plain' and not content:
                    # add all text/plain parts to the message content
                    if content is None:
                        content = part.fp.read()
                    else:
                        content = content + part.fp.read()

                elif subtype == 'message/rfc822':
                    # handle message/rfc822 specially - the name should be
                    # the subject of the actual e-mail embedded here
                    i = part.fp.tell()
                    mailmess = Message(part.fp)
                    name = mailmess.getheader('subject')
                    part.fp.seek(i)
                    attachments.append((name, 'message/rfc822', part.fp.read()))

                else:
                    # try name on Content-Type
                    name = part.getparam('name')
                    # this is just an attachment
                    encoding = part.getencoding()
                    if encoding == 'base64':
                        data = binascii.a2b_base64(part.fp.read())
                    elif encoding == 'quoted-printable':
                        # the quopri module wants to work with files
                        decoded = cStringIO.StringIO()
                        quopri.decode(part.fp, decoded)
                        data = decoded.getvalue()
                    elif encoding == 'uuencoded':
                        data = binascii.a2b_uu(part.fp.read())
                    attachments.append((name, part.gettype(), data))

            if content is None:
                raise MailUsageError, '''
Roundup requires the submission to be plain text. The message parser could
not find a text/plain part to use.
'''

        elif content_type[:10] == 'multipart/':
            # skip over the intro to the first boundary
            message.getPart()
            content = None
            while 1:
                # get the next part
                part = message.getPart()
                if part is None:
                    break
                # parse it
                if part.gettype() == 'text/plain' and not content:
                    # this one's our content
                    content = part.fp.read()
            if content is None:
                raise MailUsageError, '''
Roundup requires the submission to be plain text. The message parser could
not find a text/plain part to use.
'''

        elif content_type != 'text/plain':
            raise MailUsageError, '''
Roundup requires the submission to be plain text. The message parser could
not find a text/plain part to use.
'''

        else:
            content = message.fp.read()

        summary, content = parseContent(content)

        # handle the files
        files = []
        for (name, mime_type, data) in attachments:
            files.append(self.db.file.create(type=mime_type, name=name,
                content=data))

        # now handle the db stuff
        if nodeid:
            # If an item designator (class name and id number) is found there,
            # the newly created "msg" node is added to the "messages" property
            # for that item, and any new "file" nodes are added to the "files" 
            # property for the item. 

            # if the message is currently 'unread' or 'resolved', then set
            # it to 'chatting'
            if properties.has_key('status'):
                try:
                    # determine the id of 'unread', 'resolved' and 'chatting'
                    unread_id = self.db.status.lookup('unread')
                    resolved_id = self.db.status.lookup('resolved')
                    chatting_id = self.db.status.lookup('chatting')
                except KeyError:
                    pass
                else:
                    if (not props.has_key('status') or
                            props['status'] == unread_id or
                            props['status'] == resolved_id):
                        props['status'] = chatting_id

            # add nosy in arguments to issue's nosy list
            if not props.has_key('nosy'): props['nosy'] = []
            n = {}
            for nid in cl.get(nodeid, 'nosy'):
                n[nid] = 1
            for value in props['nosy']:
                if self.db.hasnode('user', value):
                    nid = value
                else: 
                    continue
                if n.has_key(nid): continue
                n[nid] = 1
            props['nosy'] = n.keys()
            # add assignedto to the nosy list
            try:
                assignedto = self.db.user.lookup(props['assignedto'])
                if assignedto not in props['nosy']:
                    props['nosy'].append(assignedto)
            except:
                pass
                
            message_id = self.db.msg.create(author=author,
                recipients=recipients, date=date.Date('.'), summary=summary,
                content=content, files=files)
            try:
                messages = cl.get(nodeid, 'messages')
            except IndexError:
                raise MailUsageError, '''
The node specified by the designator in the subject of your message ("%s")
does not exist.

Subject was: "%s"
'''%(nodeid, subject)
            messages.append(message_id)
            props['messages'] = messages

            # now apply the changes
            try:
                cl.set(nodeid, **props)
            except (TypeError, IndexError, ValueError), message:
                raise MailUsageError, '''
There was a problem with the message you sent:
   %s
'''%message
            # commit the changes to the DB
            self.db.commit()
        else:
            # If just an item class name is found there, we attempt to create a
            # new item of that class with its "messages" property initialized to
            # contain the new "msg" node and its "files" property initialized to
            # contain any new "file" nodes. 
            message_id = self.db.msg.create(author=author,
                recipients=recipients, date=date.Date('.'), summary=summary,
                content=content, files=files)

            # pre-set the issue to unread
            if properties.has_key('status') and not props.has_key('status'):
                try:
                    # determine the id of 'unread'
                    unread_id = self.db.status.lookup('unread')
                except KeyError:
                    pass
                else:
                    props['status'] = '1'

            # set the title to the subject
            if properties.has_key('title') and not props.has_key('title'):
                props['title'] = title

            # pre-load the messages list and nosy list
            props['messages'] = [message_id]
            nosy = props.get('nosy', [])
            n = {}
            for value in nosy:
                if self.db.hasnode('user', value):
                    nid = value
                else:
                    continue
                if n.has_key(nid): continue
                n[nid] = 1
            props['nosy'] = n.keys() + recipients
            # add the author to the nosy list
            if not n.has_key(author):
                props['nosy'].append(author)
                n[author] = 1
            # add assignedto to the nosy list
            try:
                assignedto = self.db.user.lookup(props['assignedto'])
                if not n.has_key(assignedto):
                    props['nosy'].append(assignedto)
            except:
                pass

            # and attempt to create the new node
            try:
                nodeid = cl.create(**props)
            except (TypeError, IndexError, ValueError), message:
                raise MailUsageError, '''
There was a problem with the message you sent:
   %s
'''%message

            # commit the new node(s) to the DB
            self.db.commit()

def parseContent(content, blank_line=re.compile(r'[\r\n]+\s*[\r\n]+'),
        eol=re.compile(r'[\r\n]+'), signature=re.compile(r'^[>|\s]*[-_]+\s*$')):
    ''' The message body is divided into sections by blank lines.
    Sections where the second and all subsequent lines begin with a ">" or "|"
    character are considered "quoting sections". The first line of the first
    non-quoting section becomes the summary of the message. 
    '''
    # strip off leading carriage-returns / newlines
    i = 0
    for i in range(len(content)):
        if content[i] not in '\r\n':
            break
    if i > 0:
        sections = blank_line.split(content[i:])
    else:
        sections = blank_line.split(content)

    # extract out the summary from the message
    summary = ''
    l = []
    for section in sections:
        #section = section.strip()
        if not section:
            continue
        lines = eol.split(section)
        if lines[0] and lines[0][0] in '>|':
            continue
        if len(lines) > 1 and lines[1] and lines[1][0] in '>|':
            continue
        if not summary:
            summary = lines[0]
            l.append(section)
            continue
        if signature.match(lines[0]):
            break
        l.append(section)
    return summary, '\n\n'.join(l)

#
# $Log: not supported by cvs2svn $
# Revision 1.42  2001/12/15 19:24:39  rochecompaan
#  . Modified cgi interface to change properties only once all changes are
#    collected, files created and messages generated.
#  . Moved generation of change note to nosyreactors.
#  . We now check for changes to "assignedto" to ensure it's added to the
#    nosy list.
#
# Revision 1.41  2001/12/10 00:57:38  richard
# From CHANGES:
#  . Added the "display" command to the admin tool - displays a node's values
#  . #489760 ] [issue] only subject
#  . fixed the doc/index.html to include the quoting in the mail alias.
#
# Also:
#  . fixed roundup-admin so it works with transactions
#  . disabled the back_anydbm module if anydbm tries to use dumbdbm
#
# Revision 1.40  2001/12/05 14:26:44  rochecompaan
# Removed generation of change note from "sendmessage" in roundupdb.py.
# The change note is now generated when the message is created.
#
# Revision 1.39  2001/12/02 05:06:16  richard
# . We now use weakrefs in the Classes to keep the database reference, so
#   the close() method on the database is no longer needed.
#   I bumped the minimum python requirement up to 2.1 accordingly.
# . #487480 ] roundup-server
# . #487476 ] INSTALL.txt
#
# I also cleaned up the change message / post-edit stuff in the cgi client.
# There's now a clearly marked "TODO: append the change note" where I believe
# the change note should be added there. The "changes" list will obviously
# have to be modified to be a dict of the changes, or somesuch.
#
# More testing needed.
#
# Revision 1.38  2001/12/01 07:17:50  richard
# . We now have basic transaction support! Information is only written to
#   the database when the commit() method is called. Only the anydbm
#   backend is modified in this way - neither of the bsddb backends have been.
#   The mail, admin and cgi interfaces all use commit (except the admin tool
#   doesn't have a commit command, so interactive users can't commit...)
# . Fixed login/registration forwarding the user to the right page (or not,
#   on a failure)
#
# Revision 1.37  2001/11/28 21:55:35  richard
#  . login_action and newuser_action return values were being ignored
#  . Woohoo! Found that bloody re-login bug that was killing the mail
#    gateway.
#  (also a minor cleanup in hyperdb)
#
# Revision 1.36  2001/11/26 22:55:56  richard
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
# Revision 1.35  2001/11/22 15:46:42  jhermann
# Added module docstrings to all modules.
#
# Revision 1.34  2001/11/15 10:24:27  richard
# handle the case where there is no file attached
#
# Revision 1.33  2001/11/13 21:44:44  richard
#  . re-open the database as the author in mail handling
#
# Revision 1.32  2001/11/12 22:04:29  richard
# oops, left debug in there
#
# Revision 1.31  2001/11/12 22:01:06  richard
# Fixed issues with nosy reaction and author copies.
#
# Revision 1.30  2001/11/09 22:33:28  richard
# More error handling fixes.
#
# Revision 1.29  2001/11/07 05:29:26  richard
# Modified roundup-mailgw so it can read e-mails from a local mail spool
# file. Truncates the spool file after parsing.
# Fixed a couple of small bugs introduced in roundup.mailgw when I started
# the popgw.
#
# Revision 1.28  2001/11/01 22:04:37  richard
# Started work on supporting a pop3-fetching server
# Fixed bugs:
#  . bug #477104 ] HTML tag error in roundup-server
#  . bug #477107 ] HTTP header problem
#
# Revision 1.27  2001/10/30 11:26:10  richard
# Case-insensitive match for ISSUE_TRACKER_EMAIL in address in e-mail.
#
# Revision 1.26  2001/10/30 00:54:45  richard
# Features:
#  . #467129 ] Lossage when username=e-mail-address
#  . #473123 ] Change message generation for author
#  . MailGW now moves 'resolved' to 'chatting' on receiving e-mail for an issue.
#
# Revision 1.25  2001/10/28 23:22:28  richard
# fixed bug #474749 ] Indentations lost
#
# Revision 1.24  2001/10/23 22:57:52  richard
# Fix unread->chatting auto transition, thanks Roch'e
#
# Revision 1.23  2001/10/21 04:00:20  richard
# MailGW now moves 'unread' to 'chatting' on receiving e-mail for an issue.
#
# Revision 1.22  2001/10/21 03:35:13  richard
# bug #473125: Paragraph in e-mails
#
# Revision 1.21  2001/10/21 00:53:42  richard
# bug #473130: Nosy list not set correctly
#
# Revision 1.20  2001/10/17 23:13:19  richard
# Did a fair bit of work on the admin tool. Now has an extra command "table"
# which displays node information in a tabular format. Also fixed import and
# export so they work. Removed freshen.
# Fixed quopri usage in mailgw from bug reports.
#
# Revision 1.19  2001/10/11 23:43:04  richard
# Implemented the comma-separated printing option in the admin tool.
# Fixed a typo (more of a vim-o actually :) in mailgw.
#
# Revision 1.18  2001/10/11 06:38:57  richard
# Initial cut at trying to handle people responding to CC'ed messages that
# create an issue.
#
# Revision 1.17  2001/10/09 07:25:59  richard
# Added the Password property type. See "pydoc roundup.password" for
# implementation details. Have updated some of the documentation too.
#
# Revision 1.16  2001/10/05 02:23:24  richard
#  . roundup-admin create now prompts for property info if none is supplied
#    on the command-line.
#  . hyperdb Class getprops() method may now return only the mutable
#    properties.
#  . Login now uses cookies, which makes it a whole lot more flexible. We can
#    now support anonymous user access (read-only, unless there's an
#    "anonymous" user, in which case write access is permitted). Login
#    handling has been moved into cgi_client.Client.main()
#  . The "extended" schema is now the default in roundup init.
#  . The schemas have had their page headings modified to cope with the new
#    login handling. Existing installations should copy the interfaces.py
#    file from the roundup lib directory to their instance home.
#  . Incorrectly had a Bizar Software copyright on the cgitb.py module from
#    Ping - has been removed.
#  . Fixed a whole bunch of places in the CGI interface where we should have
#    been returning Not Found instead of throwing an exception.
#  . Fixed a deviation from the spec: trying to modify the 'id' property of
#    an item now throws an exception.
#
# Revision 1.15  2001/08/30 06:01:17  richard
# Fixed missing import in mailgw :(
#
# Revision 1.14  2001/08/13 23:02:54  richard
# Make the mail parser a little more robust.
#
# Revision 1.13  2001/08/12 06:32:36  richard
# using isinstance(blah, Foo) now instead of isFooType
#
# Revision 1.12  2001/08/08 01:27:00  richard
# Added better error handling to mailgw.
#
# Revision 1.11  2001/08/08 00:08:03  richard
# oops ;)
#
# Revision 1.10  2001/08/07 00:24:42  richard
# stupid typo
#
# Revision 1.9  2001/08/07 00:15:51  richard
# Added the copyright/license notice to (nearly) all files at request of
# Bizar Software.
#
# Revision 1.8  2001/08/05 07:06:07  richard
# removed some print statements
#
# Revision 1.7  2001/08/03 07:18:22  richard
# Implemented correct mail splitting (was taking a shortcut). Added unit
# tests. Also snips signatures now too.
#
# Revision 1.6  2001/08/01 04:24:21  richard
# mailgw was assuming certain properties existed on the issues being created.
#
# Revision 1.5  2001/07/29 07:01:39  richard
# Added vim command to all source so that we don't get no steenkin' tabs :)
#
# Revision 1.4  2001/07/28 06:43:02  richard
# Multipart message class has the getPart method now. Added some tests for it.
#
# Revision 1.3  2001/07/28 00:34:34  richard
# Fixed some non-string node ids.
#
# Revision 1.2  2001/07/22 12:09:32  richard
# Final commit of Grande Splite
#
#
# vim: set filetype=python ts=4 sw=4 et si
