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

$Id: mailgw.py,v 1.77 2002-07-18 11:17:31 gmcm Exp $
'''


import string, re, os, mimetools, cStringIO, smtplib, socket, binascii, quopri
import time, random
import traceback, MimeWriter
import hyperdb, date, password

SENDMAILDEBUG = os.environ.get('SENDMAILDEBUG', '')

class MailGWError(ValueError):
    pass

class MailUsageError(ValueError):
    pass

class MailUsageHelp(Exception):
    pass

class UnAuthorized(Exception):
    """ Access denied """

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

subject_re = re.compile(r'(?P<refwd>\s*\W?\s*(fwd|re|aw)\s*\W?\s*)*'
    r'\s*(\[(?P<classname>[^\d\s]+)(?P<nodeid>\d+)?\])?'
    r'\s*(?P<title>[^[]+)?(\[(?P<args>.+?)\])?', re.I)

class MailGW:
    def __init__(self, instance, db):
        self.instance = instance
        self.db = db

        # should we trap exceptions (normal usage) or pass them through
        # (for testing)
        self.trapExceptions = 1

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
            except UnAuthorized, value:
                # just inform the user that he is not authorized
                sendto = [sendto[0][1]]
                m = ['']
                m.append(str(value))
                m = self.bounce_message(message, sendto, m)
            except:
                # bounce the message back to the sender with the error message
                sendto = [sendto[0][1], self.instance.ADMIN_EMAIL]
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
            sendto = [self.instance.ADMIN_EMAIL]
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
                self.instance.ADMIN_EMAIL, ', '.join(sendto), m.getvalue()))
        else:
            try:
                smtp = smtplib.SMTP(self.instance.MAILHOST)
                smtp.sendmail(self.instance.ADMIN_EMAIL, sendto, m.getvalue())
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
        writer.addheader('From', '%s <%s>'% (self.instance.INSTANCE_NAME,
                                            self.instance.ISSUE_TRACKER_EMAIL))
        writer.addheader('To', ','.join(sendto))
        writer.addheader('MIME-Version', '1.0')
        part = writer.startmultipartbody('mixed')
        part = writer.nextpart()
        body = part.startbody('text/plain')
        body.write('\n'.join(error))

        # reconstruct the original message
        m = cStringIO.StringIO()
        w = MimeWriter.MimeWriter(m)
        # default the content_type, just in case...
        content_type = 'text/plain'
        # add the headers except the content-type
        for header in message.headers:
            header_name = header.split(':')[0]
            if header_name.lower() == 'content-type':
                content_type = message.getheader(header_name)
            elif message.getheader(header_name):
                w.addheader(header_name, message.getheader(header_name))
        # now attach the message body
        body = w.startbody(content_type)
        try:
            message.rewindbody()
        except IOError:
            body.write("*** couldn't include message body: read from pipe ***")
        else:
            body.write(message.fp.read())

        # attach the original message to the returned message
        part = writer.nextpart()
        part.addheader('Content-Disposition','attachment')
        part.addheader('Content-Description','Message you sent')
        part.addheader('Content-Transfer-Encoding', '7bit')
        body = part.startbody('message/rfc822')
        body.write(m.getvalue())

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
                if hasattr(self.instance, 'MAIL_DEFAULT_CLASS') and \
                        self.instance.MAIL_DEFAULT_CLASS:
                    classname = self.instance.MAIL_DEFAULT_CLASS
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
        # handle the users
        #

        # Don't create users if ANONYMOUS_REGISTER_MAIL is denied
        # ... fall back on ANONYMOUS_REGISTER if the other doesn't exist
        create = 1
        if hasattr(self.instance, 'ANONYMOUS_REGISTER_MAIL'):
            if self.instance.ANONYMOUS_REGISTER_MAIL == 'deny':
                create = 0
        elif self.instance.ANONYMOUS_REGISTER == 'deny':
            create = 0

        author = self.db.uidFromAddress(message.getaddrlist('from')[0],
            create=create)
        if not author:
            raise UnAuthorized, '''
You are not a registered user.

Unknown address: %s
'''%message.getaddrlist('from')[0][1]

        # the author may have been created - make sure the change is
        # committed before we reopen the database
        self.db.commit()
            
        # reopen the database as the author
        username = self.db.user.get(author, 'username')
        self.db = self.instance.open(username)

        # re-get the class with the new database connection
        cl = self.db.getclass(classname)

        # now update the recipients list
        recipients = []
        tracker_email = self.instance.ISSUE_TRACKER_EMAIL.lower()
        for recipient in message.getaddrlist('to') + message.getaddrlist('cc'):
            r = recipient[1].strip().lower()
            if r == tracker_email or not r:
                continue

            # look up the recipient - create if necessary (and we're
            # allowed to)
            recipient = self.db.uidFromAddress(recipient, create)

            # if all's well, add the recipient to the list
            if recipient:
                recipients.append(recipient)

        #
        # handle message-id and in-reply-to
        #
        messageid = message.getheader('message-id')
        inreplyto = message.getheader('in-reply-to') or ''
        # generate a messageid if there isn't one
        if not messageid:
            messageid = "<%s.%s.%s%s@%s>"%(time.time(), random.random(),
                classname, nodeid, self.instance.MAIL_DOMAIN)

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
                    name = part.getparam('name')
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
        keep_citations = getattr(self.instance, 'EMAIL_KEEP_QUOTED_TEXT',
            'no') == 'yes'
        keep_body = getattr(self.instance, 'EMAIL_LEAVE_BODY_UNCHANGED',
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

def parseContent(content, keep_citations, keep_body,
        blank_line=re.compile(r'[\r\n]+\s*[\r\n]+'),
        eol=re.compile(r'[\r\n]+'), 
        signature=re.compile(r'^[>|\s]*[-_]+\s*$'),
        original_message=re.compile(r'^[>|\s]*-----Original Message-----$')):
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
        if (lines[0] and lines[0][0] in '>|') or (len(lines) > 1 and
                lines[1] and lines[1][0] in '>|'):
            # see if there's a response somewhere inside this section (ie.
            # no blank line between quoted message and response)
            for line in lines[1:]:
                if line[0] not in '>|':
                    break
            else:
                # we keep quoted bits if specified in the config
                if keep_citations:
                    l.append(section)
                continue
            # keep this section - it has reponse stuff in it
            if not summary:
                # and while we're at it, use the first non-quoted bit as
                # our summary
                summary = line
            lines = lines[lines.index(line):]
            section = '\n'.join(lines)

        if not summary:
            # if we don't have our summary yet use the first line of this
            # section
            summary = lines[0]
        elif signature.match(lines[0]) and 2 <= len(lines) <= 10:
            # lose any signature
            break
        elif original_message.match(lines[0]):
            # ditch the stupid Outlook quoting of the entire original message
            break

        # and add the section to the output
        l.append(section)
    # we only set content for those who want to delete cruft from the
    # message body, otherwise the body is left untouched.
    if not keep_body:
        content = '\n\n'.join(l)
    return summary, content

#
# $Log: not supported by cvs2svn $
# Revision 1.76  2002/07/10 06:39:37  richard
#  . made mailgw handle set and modify operations on multilinks (bug #579094)
#
# Revision 1.75  2002/07/09 01:21:24  richard
# Added ability for unit tests to turn off exception handling in mailgw so
# that exceptions are reported earlier (and hence make sense).
#
# Revision 1.74  2002/05/29 01:16:17  richard
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
# Revision 1.73  2002/05/22 04:12:05  richard
#  . applied patch #558876 ] cgi client customization
#    ... with significant additions and modifications ;)
#    - extended handling of ML assignedto to all places it's handled
#    - added more NotFound info
#
# Revision 1.72  2002/05/22 01:24:51  richard
# Added note to MIGRATION about new config vars. Also made us more resilient
# for upgraders. Reinstated list header style (oops)
#
# Revision 1.71  2002/05/08 02:40:55  richard
# grr
#
# Revision 1.70  2002/05/06 23:40:07  richard
# hrm
#
# Revision 1.69  2002/05/06 23:37:21  richard
# Tweaking the signature deletion from mail messages.
# Added nuking of the "-----Original Message-----" crap from Outlook.
#
# Revision 1.68  2002/05/02 07:56:34  richard
# . added option to automatically add the authors and recipients of messages
#   to the nosy lists with the options ADD_AUTHOR_TO_NOSY (default 'new') and
#   ADD_RECIPIENTS_TO_NOSY (default 'new'). These settings emulate the current
#   behaviour. Setting them to 'yes' will add the author/recipients to the nosy
#   on messages that create issues and followup messages.
# . added missing documentation for a few of the config option values
#
# Revision 1.67  2002/04/23 15:46:49  rochecompaan
#  . stripping of the email message body can now be controlled through
#    the config variables EMAIL_KEEP_QUOTED_TEST and
#    EMAIL_LEAVE_BODY_UNCHANGED.
#
# Revision 1.66  2002/03/14 23:59:24  richard
#  . #517734 ] web header customisation is obscure
#
# Revision 1.65  2002/02/15 00:13:38  richard
#  . #503204 ] mailgw needs a default class
#     - partially done - the setting of additional properties can wait for a
#       better configuration system.
#
# Revision 1.64  2002/02/14 23:46:02  richard
# . #516883 ] mail interface + ANONYMOUS_REGISTER
#
# Revision 1.63  2002/02/12 08:08:55  grubert
#  . Clean up mail handling, multipart handling.
#
# Revision 1.62  2002/02/05 14:15:29  grubert
#  . respect encodings in non multipart messages.
#
# Revision 1.61  2002/02/04 09:40:21  grubert
#  . add test for multipart messages with first part being encoded.
#
# Revision 1.60  2002/02/01 07:43:12  grubert
#  . mailgw checks encoding on first part too.
#
# Revision 1.59  2002/01/23 21:43:23  richard
# tabnuke
#
# Revision 1.58  2002/01/23 21:41:56  richard
#  . mailgw failures (unexpected ones) are forwarded to the roundup admin
#
# Revision 1.57  2002/01/22 22:27:43  richard
#  . handle stripping of "AW:" from subject line
#
# Revision 1.56  2002/01/22 11:54:45  rochecompaan
# Fixed status change in mail gateway.
#
# Revision 1.55  2002/01/21 10:05:47  rochecompaan
# Feature:
#  . the mail gateway now responds with an error message when invalid
#    values for arguments are specified for link or multilink properties
#  . modified unit test to check nosy and assignedto when specified as
#    arguments
#
# Fixed:
#  . fixed setting nosy as argument in subject line
#
# Revision 1.54  2002/01/16 09:14:45  grubert
#  . if the attachment has no name, name it unnamed, happens with tnefs.
#
# Revision 1.53  2002/01/16 07:20:54  richard
# simple help command for mailgw
#
# Revision 1.52  2002/01/15 00:12:40  richard
# #503340 ] creating issue with [asignedto=p.ohly]
#
# Revision 1.51  2002/01/14 02:20:15  richard
#  . changed all config accesses so they access either the instance or the
#    config attriubute on the db. This means that all config is obtained from
#    instance_config instead of the mish-mash of classes. This will make
#    switching to a ConfigParser setup easier too, I hope.
#
# At a minimum, this makes migration a _little_ easier (a lot easier in the
# 0.5.0 switch, I hope!)
#
# Revision 1.50  2002/01/11 22:59:01  richard
#  . #502342 ] pipe interface
#
# Revision 1.49  2002/01/10 06:19:18  richard
# followup lines directly after a quoted section were being eaten.
#
# Revision 1.48  2002/01/08 04:12:05  richard
# Changed message-id format to "<%s.%s.%s%s@%s>" so it complies with RFC822
#
# Revision 1.47  2002/01/02 02:32:38  richard
# ANONYMOUS_ACCESS -> ANONYMOUS_REGISTER
#
# Revision 1.46  2002/01/02 02:31:38  richard
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
# Revision 1.45  2001/12/20 15:43:01  rochecompaan
# Features added:
#  .  Multilink properties are now displayed as comma separated values in
#     a textbox
#  .  The add user link is now only visible to the admin user
#  .  Modified the mail gateway to reject submissions from unknown
#     addresses if ANONYMOUS_ACCESS is denied
#
# Revision 1.44  2001/12/18 15:30:34  rochecompaan
# Fixed bugs:
#  .  Fixed file creation and retrieval in same transaction in anydbm
#     backend
#  .  Cgi interface now renders new issue after issue creation
#  .  Could not set issue status to resolved through cgi interface
#  .  Mail gateway was changing status back to 'chatting' if status was
#     omitted as an argument
#
# Revision 1.43  2001/12/15 19:39:01  rochecompaan
# Oops.
#
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
