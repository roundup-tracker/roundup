#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL THE BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
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

$Id: mailgw.py,v 1.9 2001-08-07 00:15:51 richard Exp $
'''


import string, re, os, mimetools, cStringIO, smtplib, socket, binascii, quopri
import traceback
import date

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

subject_re = re.compile(r'(\[?(fwd|re):\s*)*'
    r'(\[(?P<classname>[^\d]+)(?P<nodeid>\d+)?\])'
    r'(?P<title>[^\[]+)(\[(?P<args>.+?)\])?', re.I)

class MailGW:
    def __init__(self, db):
        self.db = db

    def main(self, fp):
        ''' fp - the file from which to read the Message.

        Read a message from fp and then call handle_message() with the
        result. This method's job is to make that call and handle any
        errors in a sane manner. It should be replaced if you wish to
        handle errors in a different manner.
        '''
        # ok, figure the subject, author, recipients and content-type
        message = Message(fp)
        try:
            self.handle_message(message)
        except:
            # bounce the message back to the sender with the error message
            sendto = [message.getaddrlist('from')[0][1]]
            m = ['Subject: failed issue tracker submission']
            m.append('')
            # TODO as attachments?
            m.append('----  traceback of failure  ----')
            s = cStringIO.StringIO()
            import traceback
            traceback.print_exc(None, s)
            m.append(s.getvalue())
            m.append('---- failed message follows ----')
            try:
                fp.seek(0)
            except:
                pass
            m.append(fp.read())
            try:
                smtp = smtplib.SMTP(self.MAILHOST)
                smtp.sendmail(self.ADMIN_EMAIL, sendto, '\n'.join(m))
            except socket.error, value:
                return "Couldn't send confirmation email: mailhost %s"%value
            except smtplib.SMTPException, value:
                return "Couldn't send confirmation email: %s"%value

    def handle_message(self, message):
        ''' message - a Message instance

        Parse the message as per the module docstring.
        '''
        # handle the subject line
        m = subject_re.match(message.getheader('subject'))
        if not m:
            raise ValueError, 'No [designator] found in subject "%s"'
        classname = m.group('classname')
        nodeid = m.group('nodeid')
        title = m.group('title').strip()
        subject_args = m.group('args')
        cl = self.db.getclass(classname)
        properties = cl.getprops()
        props = {}
        args = m.group('args')
        if args:
            for prop in string.split(m.group('args'), ';'):
                try:
                    key, value = prop.split('=')
                except ValueError, message:
                    raise ValueError, 'Args list not of form [arg=value,value,...;arg=value,value,value..]  (specific exception message was "%s")'%message
                type =  properties[key]
                if type.isStringType:
                    props[key] = value 
                elif type.isDateType:
                    props[key] = date.Date(value)
                elif type.isIntervalType:
                    props[key] = date.Interval(value)
                elif type.isLinkType:
                    props[key] = value
                elif type.isMultilinkType:
                    props[key] = value.split(',')

        # handle the users
        author = self.db.uidFromAddress(message.getaddrlist('from')[0])
        recipients = []
        for recipient in message.getaddrlist('to') + message.getaddrlist('cc'):
            if recipient[1].strip().lower() == self.ISSUE_TRACKER_EMAIL:
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
                    data = part.fp.read()
                    encoding = part.getencoding()
                    if encoding == 'base64':
                        data = binascii.a2b_base64(data)
                    elif encoding == 'quoted-printable':
                        data = quopri.decode(data)
                    elif encoding == 'uuencoded':
                        data = binascii.a2b_uu(data)
                    attachments.append((name, part.gettype(), data))

            if content is None:
                raise ValueError, 'No text/plain part found'

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
                raise ValueError, 'No text/plain part found'

        elif content_type != 'text/plain':
            raise ValueError, 'No text/plain part found'

        else:
            content = message.fp.read()

        summary, content = parseContent(content)

        # handle the files
        files = []
        for (name, type, data) in attachments:
            files.append(self.db.file.create(type=type, name=name,
                content=data))

        # now handle the db stuff
        if nodeid:
            # If an item designator (class name and id number) is found there,
            # the newly created "msg" node is added to the "messages" property
            # for that item, and any new "file" nodes are added to the "files" 
            # property for the item. 
            message_id = self.db.msg.create(author=author,
                recipients=recipients, date=date.Date('.'), summary=summary,
                content=content, files=files)
            messages = cl.get(nodeid, 'messages')
            messages.append(message_id)
            props['messages'] = messages
            cl.set(nodeid, **props)
        else:
            # If just an item class name is found there, we attempt to create a
            # new item of that class with its "messages" property initialized to
            # contain the new "msg" node and its "files" property initialized to
            # contain any new "file" nodes. 
            message_id = self.db.msg.create(author=author,
                recipients=recipients, date=date.Date('.'), summary=summary,
                content=content, files=files)
            # fill out the properties with defaults where required
            if properties.has_key('assignedto') and \
                    not props.has_key('assignedto'):
                props['assignedto'] = '1'             # "admin"
            if properties.has_key('status') and not props.has_key('status'):
                props['status'] = '1'                 # "unread"
            if properties.has_key('title') and not props.has_key('title'):
                props['title'] = title
            props['messages'] = [message_id]
            props['nosy'] = recipients[:]
            props['nosy'].append(author)
            props['nosy'].sort()
            nodeid = cl.create(**props)

def parseContent(content, blank_line=re.compile(r'[\r\n]+\s*[\r\n]+'),
        eol=re.compile(r'[\r\n]+'), signature=re.compile(r'^[>|\s]*[-_]+\s*$')):
    ''' The message body is divided into sections by blank lines.
    Sections where the second and all subsequent lines begin with a ">" or "|"
    character are considered "quoting sections". The first line of the first
    non-quoting section becomes the summary of the message. 
    '''
    sections = blank_line.split(content)
    # extract out the summary from the message
    summary = ''
    l = []
    for section in sections:
        section = section.strip()
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
    return summary, '\n'.join(l)

#
# $Log: not supported by cvs2svn $
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
