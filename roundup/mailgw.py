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

'''
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

$Id: mailgw.py,v 1.100 2002-12-10 00:11:15 richard Exp $
'''

import string, re, os, mimetools, cStringIO, smtplib, socket, binascii, quopri
import time, random, sys
import traceback, MimeWriter
import hyperdb, date, password

SENDMAILDEBUG = os.environ.get('SENDMAILDEBUG', '')

class MailGWError(ValueError):
    pass

class MailUsageError(ValueError):
    pass

class MailUsageHelp(Exception):
    pass

class Unauthorized(Exception):
    """ Access denied """

def initialiseSecurity(security):
    ''' Create some Permissions and Roles on the security object

        This function is directly invoked by security.Security.__init__()
        as a part of the Security object instantiation.
    '''
    security.addPermission(name="Email Registration",
        description="Anonymous may register through e-mail")
    p = security.addPermission(name="Email Access",
        description="User may use the email interface")
    security.addPermissionToRole('Admin', p)

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

subject_re = re.compile(r'(?P<refwd>\s*\W?\s*(fwd|re|aw)\W\s*)*'
    r'\s*(?P<quote>")?(\[(?P<classname>[^\d\s]+)(?P<nodeid>\d+)?\])?'
    r'\s*(?P<title>[^[]+)?"?(\[(?P<args>.+?)\])?', re.I)

class MailGW:
    def __init__(self, instance, db):
        self.instance = instance
        self.db = db

        # should we trap exceptions (normal usage) or pass them through
        # (for testing)
        self.trapExceptions = 1

    def do_pipe(self):
        ''' Read a message from standard input and pass it to the mail handler.

            Read into an internal structure that we can seek on (in case
            there's an error).

            XXX: we may want to read this into a temporary file instead...
        '''
        s = cStringIO.StringIO()
        s.write(sys.stdin.read())
        s.seek(0)
        self.main(s)
        return 0

    def do_mailbox(self, filename):
        ''' Read a series of messages from the specified unix mailbox file and
            pass each to the mail handler.
        '''
        # open the spool file and lock it
        import fcntl, FCNTL
        f = open(filename, 'r+')
        fcntl.flock(f.fileno(), FCNTL.LOCK_EX)

        # handle and clear the mailbox
        try:
            from mailbox import UnixMailbox
            mailbox = UnixMailbox(f, factory=Message)
            # grab one message
            message = mailbox.next()
            while message:
                # handle this message
                self.handle_Message(message)
                message = mailbox.next()
            # nuke the file contents
            os.ftruncate(f.fileno(), 0)
        except:
            import traceback
            traceback.print_exc()
            return 1
        fcntl.flock(f.fileno(), FCNTL.LOCK_UN)
        return 0

    def do_pop(self, server, user='', password=''):
        '''Read a series of messages from the specified POP server.
        '''
        import getpass, poplib, socket
        try:
            if not user:
                user = raw_input(_('User: '))
            if not password:
                password = getpass.getpass()
        except (KeyboardInterrupt, EOFError):
            # Ctrl C or D maybe also Ctrl Z under Windows.
            print "\nAborted by user."
            return 1

        # open a connection to the server and retrieve all messages
        try:
            server = poplib.POP3(server)
        except socket.error, message:
            print "POP server error:", message
            return 1
        server.user(user)
        server.pass_(password)
        numMessages = len(server.list()[1])
        for i in range(1, numMessages+1):
            # retr: returns 
            # [ pop response e.g. '+OK 459 octets',
            #   [ array of message lines ],
            #   number of octets ]
            lines = server.retr(i)[1]
            s = cStringIO.StringIO('\n'.join(lines))
            s.seek(0)
            self.handle_Message(Message(s))
            # delete the message
            server.dele(i)

        # quit the server to commit changes.
        server.quit()
        return 0

    def main(self, fp):
        ''' fp - the file from which to read the Message.
        '''
        return self.handle_Message(Message(fp))

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
            if not self.trapExceptions:
                return self.handle_message(message)
            try:
                return self.handle_message(message)
            except MailUsageHelp:
                # bounce the message back to the sender with the usage message
                fulldoc = '\n'.join(string.split(__doc__, '\n')[2:])
                sendto = [sendto[0][1]]
                m = ['']
                m.append('\n\nMail Gateway Help\n=================')
                m.append(fulldoc)
                m = self.bounce_message(message, sendto, m,
                    subject="Mail Gateway Help")
            except MailUsageError, value:
                # bounce the message back to the sender with the usage message
                fulldoc = '\n'.join(string.split(__doc__, '\n')[2:])
                sendto = [sendto[0][1]]
                m = ['']
                m.append(str(value))
                m.append('\n\nMail Gateway Help\n=================')
                m.append(fulldoc)
                m = self.bounce_message(message, sendto, m)
            except Unauthorized, value:
                # just inform the user that he is not authorized
                sendto = [sendto[0][1]]
                m = ['']
                m.append(str(value))
                m = self.bounce_message(message, sendto, m)
            except:
                # bounce the message back to the sender with the error message
                sendto = [sendto[0][1], self.instance.config.ADMIN_EMAIL]
                m = ['']
                m.append('An unexpected error occurred during the processing')
                m.append('of your message. The tracker administrator is being')
                m.append('notified.\n')
                m.append('----  traceback of failure  ----')
                s = cStringIO.StringIO()
                import traceback
                traceback.print_exc(None, s)
                m.append(s.getvalue())
                m = self.bounce_message(message, sendto, m)
        else:
            # very bad-looking message - we don't even know who sent it
            sendto = [self.instance.config.ADMIN_EMAIL]
            m = ['Subject: badly formed message from mail gateway']
            m.append('')
            m.append('The mail gateway retrieved a message which has no From:')
            m.append('line, indicating that it is corrupt. Please check your')
            m.append('mail gateway source. Failed message is attached.')
            m.append('')
            m = self.bounce_message(message, sendto, m,
                subject='Badly formed message from mail gateway')

        # now send the message
        if SENDMAILDEBUG:
            open(SENDMAILDEBUG, 'w').write('From: %s\nTo: %s\n%s\n'%(
                self.instance.config.ADMIN_EMAIL, ', '.join(sendto),
                    m.getvalue()))
        else:
            try:
                smtp = smtplib.SMTP(self.instance.config.MAILHOST)
                smtp.sendmail(self.instance.config.ADMIN_EMAIL, sendto,
                    m.getvalue())
            except socket.error, value:
                raise MailGWError, "Couldn't send error email: "\
                    "mailhost %s"%value
            except smtplib.SMTPException, value:
                raise MailGWError, "Couldn't send error email: %s"%value

    def bounce_message(self, message, sendto, error,
            subject='Failed issue tracker submission'):
        ''' create a message that explains the reason for the failed
            issue submission to the author and attach the original
            message.
        '''
        msg = cStringIO.StringIO()
        writer = MimeWriter.MimeWriter(msg)
        writer.addheader('Subject', subject)
        writer.addheader('From', '%s <%s>'% (self.instance.config.TRACKER_NAME,
            self.instance.config.TRACKER_EMAIL))
        writer.addheader('To', ','.join(sendto))
        writer.addheader('MIME-Version', '1.0')
        part = writer.startmultipartbody('mixed')
        part = writer.nextpart()
        body = part.startbody('text/plain')
        body.write('\n'.join(error))

        # attach the original message to the returned message
        part = writer.nextpart()
        part.addheader('Content-Disposition','attachment')
        part.addheader('Content-Description','Message you sent')
        body = part.startbody('text/plain')
        for header in message.headers:
            body.write(header)
        body.write('\n')
        try:
            message.rewindbody()
        except IOError, message:
            body.write("*** couldn't include message body: %s ***"%message)
        else:
            body.write(message.fp.read())

        writer.lastpart()
        return msg

    def get_part_data_decoded(self,part):
        encoding = part.getencoding()
        data = None
        if encoding == 'base64':
            # BUG: is base64 really used for text encoding or
            # are we inserting zip files here. 
            data = binascii.a2b_base64(part.fp.read())
        elif encoding == 'quoted-printable':
            # the quopri module wants to work with files
            decoded = cStringIO.StringIO()
            quopri.decode(part.fp, decoded)
            data = decoded.getvalue()
        elif encoding == 'uuencoded':
            data = binascii.a2b_uu(part.fp.read())
        else:
            # take it as text
            data = part.fp.read()
        return data

    def handle_message(self, message):
        ''' message - a Message instance

        Parse the message as per the module docstring.
        '''
        # handle the subject line
        subject = message.getheader('subject', '')

        if subject.strip() == 'help':
            raise MailUsageHelp

        m = subject_re.match(subject)

        # check for well-formed subject line
        if m:
            # get the classname
            classname = m.group('classname')
            if classname is None:
                # no classname, fallback on the default
                if hasattr(self.instance.config, 'MAIL_DEFAULT_CLASS') and \
                        self.instance.config.MAIL_DEFAULT_CLASS:
                    classname = self.instance.config.MAIL_DEFAULT_CLASS
                else:
                    # fail
                    m = None

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

        # get the class
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

        # strip off the quotes that dumb emailers put around the subject, like
        #      Re: "[issue1] bla blah"
        if m.group('quote') and title.endswith('"'):
            title = title[:-1]

        # but we do need either a title or a nodeid...
        if nodeid is None and not title:
            raise MailUsageError, '''
I cannot match your message to a node in the database - you need to either
supply a full node identifier (with number, eg "[issue123]" or keep the
previous subject title intact so I can match that.

Subject was: "%s"
'''%subject

        # If there's no nodeid, check to see if this is a followup and
        # maybe someone's responded to the initial mail that created an
        # entry. Try to find the matching nodes with the same title, and
        # use the _last_ one matched (since that'll _usually_ be the most
        # recent...)
        if nodeid is None and m.group('refwd'):
            l = cl.stringFind(title=title)
            if l:
                nodeid = l[-1]

        # if a nodeid was specified, make sure it's valid
        if nodeid is not None and not cl.hasnode(nodeid):
            raise MailUsageError, '''
The node specified by the designator in the subject of your message ("%s")
does not exist.

Subject was: "%s"
'''%(nodeid, subject)

        #
        # handle the users
        #
        # Don't create users if anonymous isn't allowed to register
        create = 1
        anonid = self.db.user.lookup('anonymous')
        if not self.db.security.hasPermission('Email Registration', anonid):
            create = 0

        # ok, now figure out who the author is - create a new user if the
        # "create" flag is true
        author = uidFromAddress(self.db, message.getaddrlist('from')[0],
            create=create)

        # if we're not recognised, and we don't get added as a user, then we
        # must be anonymous
        if not author:
            author = anonid

        # make sure the author has permission to use the email interface
        if not self.db.security.hasPermission('Email Access', author):
            if author == anonid:
                # we're anonymous and we need to be a registered user
                raise Unauthorized, '''
You are not a registered user.

Unknown address: %s
'''%message.getaddrlist('from')[0][1]
            else:
                # we're registered and we're _still_ not allowed access
                raise Unauthorized, 'You are not permitted to access '\
                    'this tracker.'

        # make sure they're allowed to edit this class of information
        if not self.db.security.hasPermission('Edit', author, classname):
            raise Unauthorized, 'You are not permitted to edit %s.'%classname

        # the author may have been created - make sure the change is
        # committed before we reopen the database
        self.db.commit()

        # reopen the database as the author
        username = self.db.user.get(author, 'username')
        self.db.close()
        self.db = self.instance.open(username)

        # re-get the class with the new database connection
        cl = self.db.getclass(classname)

        # now update the recipients list
        recipients = []
        tracker_email = self.instance.config.TRACKER_EMAIL.lower()
        for recipient in message.getaddrlist('to') + message.getaddrlist('cc'):
            r = recipient[1].strip().lower()
            if r == tracker_email or not r:
                continue

            # look up the recipient - create if necessary (and we're
            # allowed to)
            recipient = uidFromAddress(self.db, recipient, create)

            # if all's well, add the recipient to the list
            if recipient:
                recipients.append(recipient)

        #
        # extract the args
        #
        subject_args = m.group('args')

        #
        # handle the subject argument list
        #
        # figure what the properties of this Class are
        properties = cl.getprops()
        props = {}
        args = m.group('args')
        if args:
            errors = []
            for prop in string.split(args, ';'):
                # extract the property name and value
                try:
                    propname, value = prop.split('=')
                except ValueError, message:
                    errors.append('not of form [arg=value,'
                        'value,...;arg=value,value...]')
                    break

                # ensure it's a valid property name
                propname = propname.strip()
                try:
                    proptype =  properties[propname]
                except KeyError:
                    errors.append('refers to an invalid property: '
                        '"%s"'%propname)
                    continue

                # convert the string value to a real property value
                if isinstance(proptype, hyperdb.String):
                    props[propname] = value.strip()
                if isinstance(proptype, hyperdb.Password):
                    props[propname] = password.Password(value.strip())
                elif isinstance(proptype, hyperdb.Date):
                    try:
                        props[propname] = date.Date(value.strip())
                    except ValueError, message:
                        errors.append('contains an invalid date for '
                            '%s.'%propname)
                elif isinstance(proptype, hyperdb.Interval):
                    try:
                        props[propname] = date.Interval(value)
                    except ValueError, message:
                        errors.append('contains an invalid date interval'
                            'for %s.'%propname)
                elif isinstance(proptype, hyperdb.Link):
                    linkcl = self.db.classes[proptype.classname]
                    propkey = linkcl.labelprop(default_to_id=1)
                    try:
                        props[propname] = linkcl.lookup(value)
                    except KeyError, message:
                        errors.append('"%s" is not a value for %s.'%(value,
                            propname))
                elif isinstance(proptype, hyperdb.Multilink):
                    # get the linked class
                    linkcl = self.db.classes[proptype.classname]
                    propkey = linkcl.labelprop(default_to_id=1)
                    if nodeid:
                        curvalue = cl.get(nodeid, propname)
                    else:
                        curvalue = []

                    # handle each add/remove in turn
                    # keep an extra list for all items that are
                    # definitely in the new list (in case of e.g.
                    # <propname>=A,+B, which should replace the old
                    # list with A,B)
                    set = 0
                    newvalue = []
                    for item in value.split(','):
                        item = item.strip()

                        # handle +/-
                        remove = 0
                        if item.startswith('-'):
                            remove = 1
                            item = item[1:]
                        elif item.startswith('+'):
                            item = item[1:]
                        else:
                            set = 1

                        # look up the value
                        try:
                            item = linkcl.lookup(item)
                        except KeyError, message:
                            errors.append('"%s" is not a value for %s.'%(item,
                                propname))
                            continue

                        # perform the add/remove
                        if remove:
                            try:
                                curvalue.remove(item)
                            except ValueError:
                                errors.append('"%s" is not currently in '
                                    'for %s.'%(item, propname))
                                continue
                        else:
                            newvalue.append(item)
                            if item not in curvalue:
                                curvalue.append(item)

                    # that's it, set the new Multilink property value,
                    # or overwrite it completely
                    if set:
                        props[propname] = newvalue
                    else:
                        props[propname] = curvalue
                elif isinstance(proptype, hyperdb.Boolean):
                    value = value.strip()
                    props[propname] = value.lower() in ('yes', 'true', 'on', '1')
                elif isinstance(proptype, hyperdb.Number):
                    value = value.strip()
                    props[propname] = int(value)

            # handle any errors parsing the argument list
            if errors:
                errors = '\n- '.join(errors)
                raise MailUsageError, '''
There were problems handling your subject line argument list:
- %s

Subject was: "%s"
'''%(errors, subject)

        #
        # handle message-id and in-reply-to
        #
        messageid = message.getheader('message-id')
        inreplyto = message.getheader('in-reply-to') or ''
        # generate a messageid if there isn't one
        if not messageid:
            messageid = "<%s.%s.%s%s@%s>"%(time.time(), random.random(),
                classname, nodeid, self.instance.config.MAIL_DOMAIN)

        #
        # now handle the body - find the message
        #
        content_type =  message.gettype()
        attachments = []
        # General multipart handling:
        #   Take the first text/plain part, anything else is considered an 
        #   attachment.
        # multipart/mixed: multiple "unrelated" parts.
        # multipart/signed (rfc 1847): 
        #   The control information is carried in the second of the two 
        #   required body parts.
        #   ACTION: Default, so if content is text/plain we get it.
        # multipart/encrypted (rfc 1847): 
        #   The control information is carried in the first of the two 
        #   required body parts.
        #   ACTION: Not handleable as the content is encrypted.
        # multipart/related (rfc 1872, 2112, 2387):
        #   The Multipart/Related content-type addresses the MIME
        #   representation of compound objects.
        #   ACTION: Default. If we are lucky there is a text/plain.
        #   TODO: One should use the start part and look for an Alternative
        #   that is text/plain.
        # multipart/Alternative (rfc 1872, 1892):
        #   only in "related" ?
        # multipart/report (rfc 1892):
        #   e.g. mail system delivery status reports.
        #   ACTION: Default. Could be ignored or used for Delivery Notification 
        #   flagging.
        # multipart/form-data:
        #   For web forms only.
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
                    # The first text/plain part is the message content.
                    content = self.get_part_data_decoded(part) 
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
                    name = part.getparam('name').strip()
                    if not name:
                        disp = part.getheader('content-disposition', None)
                        if disp:
                            name = disp.getparam('filename').strip()
                    # this is just an attachment
                    data = self.get_part_data_decoded(part) 
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
                    content = self.get_part_data_decoded(part) 
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
            content = self.get_part_data_decoded(message) 
 
        # figure how much we should muck around with the email body
        keep_citations = getattr(self.instance.config, 'EMAIL_KEEP_QUOTED_TEXT',
            'no') == 'yes'
        keep_body = getattr(self.instance.config, 'EMAIL_LEAVE_BODY_UNCHANGED',
            'no') == 'yes'

        # parse the body of the message, stripping out bits as appropriate
        summary, content = parseContent(content, keep_citations, 
            keep_body)

        # 
        # handle the attachments
        #
        files = []
        for (name, mime_type, data) in attachments:
            if not name:
                name = "unnamed"
            files.append(self.db.file.create(type=mime_type, name=name,
                content=data))

        # 
        # create the message if there's a message body (content)
        #
        if content:
            message_id = self.db.msg.create(author=author,
                recipients=recipients, date=date.Date('.'), summary=summary,
                content=content, files=files, messageid=messageid,
                inreplyto=inreplyto)

            # attach the message to the node
            if nodeid:
                # add the message to the node's list
                messages = cl.get(nodeid, 'messages')
                messages.append(message_id)
                props['messages'] = messages
            else:
                # pre-load the messages list
                props['messages'] = [message_id]

                # set the title to the subject
                if properties.has_key('title') and not props.has_key('title'):
                    props['title'] = title

        #
        # perform the node change / create
        #
        try:
            if nodeid:
                cl.set(nodeid, **props)
            else:
                nodeid = cl.create(**props)
        except (TypeError, IndexError, ValueError), message:
            raise MailUsageError, '''
There was a problem with the message you sent:
   %s
'''%message

        # commit the changes to the DB
        self.db.commit()

        return nodeid

def extractUserFromList(userClass, users):
    '''Given a list of users, try to extract the first non-anonymous user
       and return that user, otherwise return None
    '''
    if len(users) > 1:
        for user in users:
            # make sure we don't match the anonymous or admin user
            if userClass.get(user, 'username') in ('admin', 'anonymous'):
                continue
            # first valid match will do
            return user
        # well, I guess we have no choice
        return user[0]
    elif users:
        return users[0]
    return None

def uidFromAddress(db, address, create=1):
    ''' address is from the rfc822 module, and therefore is (name, addr)

        user is created if they don't exist in the db already
    '''
    (realname, address) = address

    # try a straight match of the address
    user = extractUserFromList(db.user, db.user.stringFind(address=address))
    if user is not None: return user

    # try the user alternate addresses if possible
    props = db.user.getprops()
    if props.has_key('alternate_addresses'):
        users = db.user.filter(None, {'alternate_addresses': address})
        user = extractUserFromList(db.user, users)
        if user is not None: return user

    # try to match the username to the address (for local
    # submissions where the address is empty)
    user = extractUserFromList(db.user, db.user.stringFind(username=address))

    # couldn't match address or username, so create a new user
    if create:
        return db.user.create(username=address, address=address,
            realname=realname, roles=db.config.NEW_EMAIL_USER_ROLES)
    else:
        return 0

def parseContent(content, keep_citations, keep_body,
        blank_line=re.compile(r'[\r\n]+\s*[\r\n]+'),
        eol=re.compile(r'[\r\n]+'), 
        signature=re.compile(r'^[>|\s]*[-_]+\s*$'),
        original_message=re.compile(r'^[>|\s]*-----Original Message-----$')):
    ''' The message body is divided into sections by blank lines.
        Sections where the second and all subsequent lines begin with a ">"
        or "|" character are considered "quoting sections". The first line of
        the first non-quoting section becomes the summary of the message. 

        If keep_citations is true, then we keep the "quoting sections" in the
        content.
        If keep_body is true, we even keep the signature sections.
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
        if (lines[0] and lines[0][0] in '>|') or (len(lines) > 1 and
                lines[1] and lines[1][0] in '>|'):
            # see if there's a response somewhere inside this section (ie.
            # no blank line between quoted message and response)
            for line in lines[1:]:
                if line and line[0] not in '>|':
                    break
            else:
                # we keep quoted bits if specified in the config
                if keep_citations:
                    l.append(section)
                continue
            # keep this section - it has reponse stuff in it
            lines = lines[lines.index(line):]
            section = '\n'.join(lines)
            # and while we're at it, use the first non-quoted bit as
            # our summary
            summary = section

        if not summary:
            # if we don't have our summary yet use the first line of this
            # section
            summary = section
        elif signature.match(lines[0]) and 2 <= len(lines) <= 10:
            # lose any signature
            break
        elif original_message.match(lines[0]):
            # ditch the stupid Outlook quoting of the entire original message
            break

        # and add the section to the output
        l.append(section)

    # figure the summary - find the first sentence-ending punctuation or the
    # first whole line, whichever is longest
    sentence = re.search(r'^([^!?\.]+[!?\.])', summary)
    if sentence:
        sentence = sentence.group(1)
    else:
        sentence = ''
    first = eol.split(summary)[0]
    summary = max(sentence, first)

    # Now reconstitute the message content minus the bits we don't care
    # about.
    if not keep_body:
        content = '\n\n'.join(l)

    return summary, content

# vim: set filetype=python ts=4 sw=4 et si
