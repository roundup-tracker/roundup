#! /usr/bin/python
'''
Incoming messages are examined for multiple parts. In a multipart/mixed
message or part, each subpart is extracted and examined. In a
multipart/alternative message or part, we look for a text/plain subpart and
ignore the other parts. The text/plain subparts are assembled to form the
textual body of the message, to be stored in the file associated with a
"msg" class node. Any parts of other types are each stored in separate
files and given "file" class nodes that are linked to the "msg" node. 

The "summary" property on message nodes is taken from the first non-quoting
section in the message body. The message body is divided into sections by
blank lines. Sections where the second and all subsequent lines begin with
a ">" or "|" character are considered "quoting sections". The first line of
the first non-quoting section becomes the summary of the message. 

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

Both cases may trigger detectors (in the first case we are calling the
set() method to add the message to the item's spool; in the second case we
are calling the create() method to create a new node). If an auditor raises
an exception, the original message is bounced back to the sender with the
explanatory message given in the exception. 
'''

import sys
if int(sys.version[0]) < 2:
    print "Roundup requires Python 2.0 or newer."
    sys.exit(0)

import string, re, os, mimetools, StringIO, smtplib, socket, binascii, quopri
import config, date, roundupdb

def getPart(fp, boundary):
    line = ''
    s = StringIO.StringIO()
    while 1:
        line_n = fp.readline()
        if not line_n:
            break
        line = line_n.strip()
        if line == '--'+boundary+'--':
            break
        if line == '--'+boundary:
            break
        s.write(line_n)
    if not s.getvalue().strip():
        return None
    return s

subject_re = re.compile(r'(\[?(fwd|re):\s*)*'
    r'(\[(?P<classname>[^\d]+)(?P<nodeid>\d+)?\])'
    r'(?P<title>[^\[]+)(\[(?P<args>.+?)\])?', re.I)

def roundup_mail(db, fp):
    # ok, figure the subject, author, recipients and content-type
    message = mimetools.Message(fp)
    try:
        handle_message(db, message)
    except:
        # send an email to the people who missed out
        sendto = [message.getaddrlist('from')[0][1]]
        m = ['Subject: failed issue tracker submission']
        m.append('')
        # TODO as attachments?
        m.append('----  traceback of failure  ----')
        return
        s = StringIO.StringIO()
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
            smtp = smtplib.SMTP(config.MAILHOST)
            smtp.sendmail(config.ADMIN_EMAIL, sendto, '\n'.join(m))
        except socket.error, value:
            return "Couldn't send confirmation email: mailhost %s"%value
        except smtplib.SMTPException, value:
            return "Couldn't send confirmation email: %s"%value

def handle_message(db, message):
    # handle the subject line
    m = subject_re.match(message.getheader('subject'))
    if not m:
        raise ValueError, 'No [designator] found in subject "%s"'
    classname = m.group('classname')
    nodeid = m.group('nodeid')
    title = m.group('title').strip()
    subject_args = m.group('args')
    cl = db.getclass(classname)
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
    author = db.uidFromAddress(message.getaddrlist('from')[0])
    recipients = []
    for recipient in message.getaddrlist('to') + message.getaddrlist('cc'):
        if recipient[1].strip().lower() == config.ISSUE_TRACKER_EMAIL:
            continue
        recipients.append(db.uidFromAddress(recipient))

    # now handle the body - find the message
    content_type =  message.gettype()
    attachments = []
    if content_type == 'multipart/mixed':
        boundary = message.getparam('boundary')
        # skip over the intro to the first boundary
        part = getPart(message.fp, boundary)
        content = None
        while 1:
            # get the next part
            part = getPart(message.fp, boundary)
            if part is None:
                break
            # parse it
            part.seek(0)
            submessage = mimetools.Message(part)
            subtype = submessage.gettype()
            if subtype == 'text/plain' and not content:
                # this one's our content
                content = part.read()
            elif subtype == 'message/rfc822':
                i = part.tell()
                subsubmess = mimetools.Message(part)
                name = subsubmess.getheader('subject')
                part.seek(i)
                attachments.append((name, 'message/rfc822', part.read()))
            else:
                # try name on Content-Type
                name = submessage.getparam('name')
                # this is just an attachment
                data = part.read()
                encoding = submessage.getencoding()
                if encoding == 'base64':
                    data = binascii.a2b_base64(data)
                elif encoding == 'quoted-printable':
                    data = quopri.decode(data)
                elif encoding == 'uuencoded':
                    data = binascii.a2b_uu(data)
                attachments.append((name, submessage.gettype(), data))
        if content is None:
            raise ValueError, 'No text/plain part found'

    elif content_type[:10] == 'multipart/':
        boundary = message.getparam('boundary')
        # skip over the intro to the first boundary
        getPart(message.fp, boundary)
        content = None
        while 1:
            # get the next part
            part = getPart(message.fp, boundary)
            if part is None:
                break
            # parse it
            part.seek(0)
            submessage = mimetools.Message(part)
            if submessage.gettype() == 'text/plain' and not content:
                # this one's our content
                content = part.read()
        if content is None:
            raise ValueError, 'No text/plain part found'

    elif content_type != 'text/plain':
        raise ValueError, 'No text/plain part found'

    else:
        content = message.fp.read()

    # extract out the summary from the message
    summary = []
    for line in content.split('\n'):
        line = line.strip()
        if summary and not line:
            break
        if not line:
            summary.append('')
        elif line[0] not in '>|':
            summary.append(line)
    summary = '\n'.join(summary)

    # handle the files
    files = []
    for (name, type, data) in attachments:
        files.append(db.file.create(type=type, name=name, content=data))

    # now handle the db stuff
    if nodeid:
        # If an item designator (class name and id number) is found there, the
        # newly created "msg" node is added to the "messages" property for
        # that item, and any new "file" nodes are added to the "files" 
        # property for the item. 
        message_id = db.msg.create(author=author, recipients=recipients,
            date=date.Date('.'), summary=summary, content=content,
            files=files)
        messages = cl.get(nodeid, 'messages')
        messages.append(message_id)
        props['messages'] = messages
        apply(cl.set, (nodeid, ), props)
    else:
        # If just an item class name is found there, we attempt to create a
        # new item of that class with its "messages" property initialized to
        # contain the new "msg" node and its "files" property initialized to
        # contain any new "file" nodes. 
        message_id = db.msg.create(author=author, recipients=recipients,
            date=date.Date('.'), summary=summary, content=content,
            files=files)
        if not props.has_key('assignedto'):
            props['assignedto'] = 1             # "admin"
        if not props.has_key('priority'):
            props['priority'] = 1               # "bug-fatal"
        if not props.has_key('status'):
            props['status'] = 1                 # "unread"
        if not props.has_key('title'):
            props['title'] = title
        props['messages'] = [message_id]
        props['nosy'] = recipients[:]
        props['nosy'].append(author)
        props['nosy'].sort()
        nodeid = apply(cl.create, (), props)

    return 0

if __name__ == '__main__':
    db = roundupdb.openDB(config.DATABASE, 'admin', '1')
    roundup_mail(db, sys.stdin)
    db.close()

