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

"""An e-mail gateway for Roundup.

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

$Id: mailgw.py,v 1.180 2006-12-19 01:13:31 richard Exp $
"""
__docformat__ = 'restructuredtext'

import string, re, os, mimetools, cStringIO, smtplib, socket, binascii, quopri
import time, random, sys, logging
import traceback, MimeWriter, rfc822

from roundup import hyperdb, date, password, rfc2822, exceptions
from roundup.mailer import Mailer, MessageSendError
from roundup.i18n import _

SENDMAILDEBUG = os.environ.get('SENDMAILDEBUG', '')

class MailGWError(ValueError):
    pass

class MailUsageError(ValueError):
    pass

class MailUsageHelp(Exception):
    """ We need to send the help message to the user. """
    pass

class Unauthorized(Exception):
    """ Access denied """
    pass

class IgnoreMessage(Exception):
    """ A general class of message that we should ignore. """
    pass
class IgnoreBulk(IgnoreMessage):
        """ This is email from a mailing list or from a vacation program. """
        pass
class IgnoreLoop(IgnoreMessage):
        """ We've seen this message before... """
        pass

def initialiseSecurity(security):
    ''' Create some Permissions and Roles on the security object

        This function is directly invoked by security.Security.__init__()
        as a part of the Security object instantiation.
    '''
    p = security.addPermission(name="Email Access",
        description="User may use the email interface")
    security.addPermissionToRole('Admin', p)

def getparam(str, param):
    ''' From the rfc822 "header" string, extract "param" if it appears.
    '''
    if ';' not in str:
        return None
    str = str[str.index(';'):]
    while str[:1] == ';':
        str = str[1:]
        if ';' in str:
            # XXX Should parse quotes!
            end = str.index(';')
        else:
            end = len(str)
        f = str[:end]
        if '=' in f:
            i = f.index('=')
            if f[:i].strip().lower() == param:
                return rfc822.unquote(f[i+1:].strip())
    return None

class Message(mimetools.Message):
    ''' subclass mimetools.Message so we can retrieve the parts of the
        message...
    '''
    def getpart(self):
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

    def getparts(self):
        """Get all parts of this multipart message."""
        # skip over the intro to the first boundary
        self.getpart()

        # accumulate the other parts
        parts = []
        while 1:
            part = self.getpart()
            if part is None:
                break
            parts.append(part)
        return parts

    def getheader(self, name, default=None):
        hdr = mimetools.Message.getheader(self, name, default)
        if hdr:
            hdr = hdr.replace('\n','') # Inserted by rfc822.readheaders
        return rfc2822.decode_header(hdr)

    def getname(self):
        """Find an appropriate name for this message."""
        if self.gettype() == 'message/rfc822':
            # handle message/rfc822 specially - the name should be
            # the subject of the actual e-mail embedded here
            self.fp.seek(0)
            name = Message(self.fp).getheader('subject')
        else:
            # try name on Content-Type
            name = self.getparam('name')
            if not name:
                disp = self.getheader('content-disposition', None)
                if disp:
                    name = getparam(disp, 'filename')

        if name:
            return name.strip()

    def getbody(self):
        """Get the decoded message body."""
        self.rewindbody()
        encoding = self.getencoding()
        data = None
        if encoding == 'base64':
            # BUG: is base64 really used for text encoding or
            # are we inserting zip files here.
            data = binascii.a2b_base64(self.fp.read())
        elif encoding == 'quoted-printable':
            # the quopri module wants to work with files
            decoded = cStringIO.StringIO()
            quopri.decode(self.fp, decoded)
            data = decoded.getvalue()
        elif encoding == 'uuencoded':
            data = binascii.a2b_uu(self.fp.read())
        else:
            # take it as text
            data = self.fp.read()

        # Encode message to unicode
        charset = rfc2822.unaliasCharset(self.getparam("charset"))
        if charset:
            # Do conversion only if charset specified - handle
            # badly-specified charsets
            edata = unicode(data, charset, 'replace').encode('utf-8')
            # Convert from dos eol to unix
            edata = edata.replace('\r\n', '\n')
        else:
            # Leave message content as is
            edata = data

        return edata

    # General multipart handling:
    #   Take the first text/plain part, anything else is considered an
    #   attachment.
    # multipart/mixed:
    #   Multiple "unrelated" parts.
    # multipart/Alternative (rfc 1521):
    #   Like multipart/mixed, except that we'd only want one of the
    #   alternatives. Generally a top-level part from MUAs sending HTML
    #   mail - there will be a text/plain version.
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
    #   representation of compound objects, usually HTML mail with embedded
    #   images. Usually appears as an alternative.
    #   ACTION: Default, if we must.
    # multipart/report (rfc 1892):
    #   e.g. mail system delivery status reports.
    #   ACTION: Default. Could be ignored or used for Delivery Notification
    #   flagging.
    # multipart/form-data:
    #   For web forms only.

    def extract_content(self, parent_type=None):
        """Extract the body and the attachments recursively."""
        content_type = self.gettype()
        content = None
        attachments = []

        if content_type == 'text/plain':
            content = self.getbody()
        elif content_type[:10] == 'multipart/':
            for part in self.getparts():
                new_content, new_attach = part.extract_content(content_type)

                # If we haven't found a text/plain part yet, take this one,
                # otherwise make it an attachment.
                if not content:
                    content = new_content
                elif new_content:
                    attachments.append(part.as_attachment())

                attachments.extend(new_attach)
        elif (parent_type == 'multipart/signed' and
              content_type == 'application/pgp-signature'):
            # ignore it so it won't be saved as an attachment
            pass
        else:
            attachments.append(self.as_attachment())
        return content, attachments

    def as_attachment(self):
        """Return this message as an attachment."""
        return (self.getname(), self.gettype(), self.getbody())

class MailGW:

    def __init__(self, instance, db, arguments=()):
        self.instance = instance
        self.db = db
        self.arguments = arguments
        self.default_class = None
        for option, value in self.arguments:
            if option == '-c':
                self.default_class = value.strip()

        self.mailer = Mailer(instance.config)
        self.logger = logging.getLogger('mailgw')

        # should we trap exceptions (normal usage) or pass them through
        # (for testing)
        self.trapExceptions = 1

    def do_pipe(self):
        """ Read a message from standard input and pass it to the mail handler.

            Read into an internal structure that we can seek on (in case
            there's an error).

            XXX: we may want to read this into a temporary file instead...
        """
        s = cStringIO.StringIO()
        s.write(sys.stdin.read())
        s.seek(0)
        self.main(s)
        return 0

    def do_mailbox(self, filename):
        """ Read a series of messages from the specified unix mailbox file and
            pass each to the mail handler.
        """
        # open the spool file and lock it
        import fcntl
        # FCNTL is deprecated in py2.3 and fcntl takes over all the symbols
        if hasattr(fcntl, 'LOCK_EX'):
            FCNTL = fcntl
        else:
            import FCNTL
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

    def do_imap(self, server, user='', password='', mailbox='', ssl=0):
        ''' Do an IMAP connection
        '''
        import getpass, imaplib, socket
        try:
            if not user:
                user = raw_input('User: ')
            if not password:
                password = getpass.getpass()
        except (KeyboardInterrupt, EOFError):
            # Ctrl C or D maybe also Ctrl Z under Windows.
            print "\nAborted by user."
            return 1
        # open a connection to the server and retrieve all messages
        try:
            if ssl:
                self.logger.debug('Trying server %r with ssl'%server)
                server = imaplib.IMAP4_SSL(server)
            else:
                self.logger.debug('Trying server %r without ssl'%server)
                server = imaplib.IMAP4(server)
        except (imaplib.IMAP4.error, socket.error, socket.sslerror):
            self.logger.exception('IMAP server error')
            return 1

        try:
            server.login(user, password)
        except imaplib.IMAP4.error, e:
            self.logger.exception('IMAP login failure')
            return 1

        try:
            if not mailbox:
                (typ, data) = server.select()
            else:
                (typ, data) = server.select(mailbox=mailbox)
            if typ != 'OK':
                self.logger.error('Failed to get mailbox %r: %s'%(mailbox,
                    data))
                return 1
            try:
                numMessages = int(data[0])
            except ValueError, value:
                self.logger.error('Invalid message count from mailbox %r'%
                    data[0])
                return 1
            for i in range(1, numMessages+1):
                (typ, data) = server.fetch(str(i), '(RFC822)')

                # mark the message as deleted.
                server.store(str(i), '+FLAGS', r'(\Deleted)')

                # process the message
                s = cStringIO.StringIO(data[0][1])
                s.seek(0)
                self.handle_Message(Message(s))
            server.close()
        finally:
            try:
                server.expunge()
            except:
                pass
            server.logout()

        return 0


    def do_apop(self, server, user='', password='', ssl=False):
        ''' Do authentication POP
        '''
        self._do_pop(server, user, password, True, ssl)

    def do_pop(self, server, user='', password='', ssl=False):
        ''' Do plain POP
        '''
        self._do_pop(server, user, password, False, ssl)

    def _do_pop(self, server, user, password, apop, ssl):
        '''Read a series of messages from the specified POP server.
        '''
        import getpass, poplib, socket
        try:
            if not user:
                user = raw_input('User: ')
            if not password:
                password = getpass.getpass()
        except (KeyboardInterrupt, EOFError):
            # Ctrl C or D maybe also Ctrl Z under Windows.
            print "\nAborted by user."
            return 1

        # open a connection to the server and retrieve all messages
        try:
            if ssl:
                klass = poplib.POP3_SSL
            else:
                klass = poplib.POP3
            server = klass(server)
        except socket.error:
            self.logger.exception('POP server error')
            return 1
        if apop:
            server.apop(user, password)
        else:
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
        """Handle an RFC822 Message

        Handle the Message object by calling handle_message() and then cope
        with any errors raised by handle_message.
        This method's job is to make that call and handle any
        errors in a sane manner. It should be replaced if you wish to
        handle errors in a different manner.
        """
        # in some rare cases, a particularly stuffed-up e-mail will make
        # its way into here... try to handle it gracefully

        sendto = message.getaddrlist('resent-from')
        if not sendto:
            sendto = message.getaddrlist('from')
        if not sendto:
            # very bad-looking message - we don't even know who sent it
            msg = ['Badly formed message from mail gateway. Headers:']
            msg.extend(message.headers)
            msg = '\n'.join(map(str, msg))
            self.logger.error(msg)
            return

        msg = 'Handling message'
        if message.getheader('message-id'):
            msg += ' (Message-id=%r)'%message.getheader('message-id')
        self.logger.info(msg)

        # try normal message-handling
        if not self.trapExceptions:
            return self.handle_message(message)

        # no, we want to trap exceptions
        try:
            return self.handle_message(message)
        except MailUsageHelp:
            # bounce the message back to the sender with the usage message
            fulldoc = '\n'.join(string.split(__doc__, '\n')[2:])
            m = ['']
            m.append('\n\nMail Gateway Help\n=================')
            m.append(fulldoc)
            self.mailer.bounce_message(message, [sendto[0][1]], m,
                subject="Mail Gateway Help")
        except MailUsageError, value:
            # bounce the message back to the sender with the usage message
            fulldoc = '\n'.join(string.split(__doc__, '\n')[2:])
            m = ['']
            m.append(str(value))
            m.append('\n\nMail Gateway Help\n=================')
            m.append(fulldoc)
            self.mailer.bounce_message(message, [sendto[0][1]], m)
        except Unauthorized, value:
            # just inform the user that he is not authorized
            m = ['']
            m.append(str(value))
            self.mailer.bounce_message(message, [sendto[0][1]], m)
        except IgnoreMessage:
            # do not take any action
            # this exception is thrown when email should be ignored
            msg = 'IgnoreMessage raised'
            if message.getheader('message-id'):
                msg += ' (Message-id=%r)'%message.getheader('message-id')
            self.logger.info(msg)
            return
        except:
            msg = 'Exception handling message'
            if message.getheader('message-id'):
                msg += ' (Message-id=%r)'%message.getheader('message-id')
            self.logger.exception(msg)

            # bounce the message back to the sender with the error message
            # let the admin know that something very bad is happening
            sendto = [sendto[0][1], self.instance.config.ADMIN_EMAIL]
            m = ['']
            m.append('An unexpected error occurred during the processing')
            m.append('of your message. The tracker administrator is being')
            m.append('notified.\n')
            self.mailer.bounce_message(message, sendto, m)

    def handle_message(self, message):
        ''' message - a Message instance

        Parse the message as per the module docstring.
        '''
        # detect loops
        if message.getheader('x-roundup-loop', ''):
            raise IgnoreLoop

        # handle the subject line
        subject = message.getheader('subject', '')
        if not subject:
            raise MailUsageError, _("""
Emails to Roundup trackers must include a Subject: line!
""")

        # detect Precedence: Bulk, or Microsoft Outlook autoreplies
        if (message.getheader('precedence', '') == 'bulk'
                or subject.lower().find("autoreply") > 0):
            raise IgnoreBulk

        if subject.strip().lower() == 'help':
            raise MailUsageHelp

        # config is used many times in this method.
        # make local variable for easier access
        config = self.instance.config

        # determine the sender's address
        from_list = message.getaddrlist('resent-from')
        if not from_list:
            from_list = message.getaddrlist('from')

        # XXX Don't enable. This doesn't work yet.
#  "[^A-z.]tracker\+(?P<classname>[^\d\s]+)(?P<nodeid>\d+)\@some.dom.ain[^A-z.]"
        # handle delivery to addresses like:tracker+issue25@some.dom.ain
        # use the embedded issue number as our issue
#        issue_re = config['MAILGW_ISSUE_ADDRESS_RE']
#        if issue_re:
#            for header in ['to', 'cc', 'bcc']:
#                addresses = message.getheader(header, '')
#            if addresses:
#              # FIXME, this only finds the first match in the addresses.
#                issue = re.search(issue_re, addresses, 'i')
#                if issue:
#                    classname = issue.group('classname')
#                    nodeid = issue.group('nodeid')
#                    break

        # Matches subjects like:
        # Re: "[issue1234] title of issue [status=resolved]"
        open, close = config['MAILGW_SUBJECT_SUFFIX_DELIMITERS']
        delim_open = re.escape(open)
        if delim_open in '[(': delim_open = '\\' + delim_open
        delim_close = re.escape(close)
        if delim_close in '[(': delim_close = '\\' + delim_close
        subject_re = r'''
        (?P<refwd>\s*\W?\s*(fw|fwd|re|aw|sv|ang)\W\s*)*\s*   # Re:
        (?P<quote>")?                                 # Leading "
        (%s(?P<classname>[^\d\s]+)                    # [issue..
           (?P<nodeid>\d+)?                           # ..1234]
         %s)?\s*
        (?P<title>[^%s]+)?                             # issue title
        "?                                            # Trailing "
        (?P<argswhole>%s(?P<args>.+?)%s)?             # [prop=value]
        '''%(delim_open, delim_close, delim_open, delim_open, delim_close)
        subject_re = re.compile(subject_re, re.IGNORECASE|re.VERBOSE)

        # figure subject line parsing modes
        pfxmode = config['MAILGW_SUBJECT_PREFIX_PARSING']
        sfxmode = config['MAILGW_SUBJECT_SUFFIX_PARSING']

        # check for well-formed subject line
        m = subject_re.match(subject)
        if m:
            # check for registration OTK
            # or fallback on the default class
            if self.db.config['EMAIL_REGISTRATION_CONFIRMATION']:
                otk_re = re.compile('-- key (?P<otk>[a-zA-Z0-9]{32})')
                otk = otk_re.search(m.group('title') or '')
                if otk:
                    self.db.confirm_registration(otk.group('otk'))
                    subject = 'Your registration to %s is complete' % \
                              config['TRACKER_NAME']
                    sendto = [from_list[0][1]]
                    self.mailer.standard_message(sendto, subject, '')
                    return
            # get the classname
            if pfxmode == 'none':
                classname = None
            else:
                classname = m.group('classname')
            if classname is None:
                if self.default_class:
                    classname = self.default_class
                else:
                    classname = config['MAILGW_DEFAULT_CLASS']
                    if not classname:
                        # fail
                        m = None

        if not m and pfxmode == 'strict':
            raise MailUsageError, _("""
The message you sent to roundup did not contain a properly formed subject
line. The subject must contain a class name or designator to indicate the
'topic' of the message. For example:
    Subject: [issue] This is a new issue
      - this will create a new issue in the tracker with the title 'This is
        a new issue'.
    Subject: [issue1234] This is a followup to issue 1234
      - this will append the message's contents to the existing issue 1234
        in the tracker.

Subject was: '%(subject)s'
""") % locals()

        # try to get the class specified - if "loose" then fall back on the
        # default
        attempts = [classname]
        if pfxmode == 'loose':
            if self.default_class:
                attempts.append(self.default_class)
            else:
                attempts.append(config['MAILGW_DEFAULT_CLASS'])
        cl = None
        for trycl in attempts:
            try:
                cl = self.db.getclass(classname)
                break
            except KeyError:
                pass
        if not cl:
            validname = ', '.join(self.db.getclasses())
            raise MailUsageError, _("""
The class name you identified in the subject line ("%(classname)s") does not exist in the
database.

Valid class names are: %(validname)s
Subject was: "%(subject)s"
""") % locals()

        # get the optional nodeid
        if pfxmode == 'none':
            nodeid = None
        else:
            nodeid = m.group('nodeid')

        # try in-reply-to to match the message if there's no nodeid
        inreplyto = message.getheader('in-reply-to') or ''
        if nodeid is None and inreplyto:
            l = self.db.getclass('msg').stringFind(inreplyto=inreplyto)
            if l:
                nodeid = l[0]

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
            raise MailUsageError, _("""
I cannot match your message to a node in the database - you need to either
supply a full designator (with number, eg "[issue123]" or keep the
previous subject title intact so I can match that.

Subject was: "%(subject)s"
""") % locals()

        # If there's no nodeid, check to see if this is a followup and
        # maybe someone's responded to the initial mail that created an
        # entry. Try to find the matching nodes with the same title, and
        # use the _last_ one matched (since that'll _usually_ be the most
        # recent...). The subject_content_match config may specify an
        # additional restriction based on the matched node's creation or
        # activity.
        tmatch_mode = config['MAILGW_SUBJECT_CONTENT_MATCH']
        if tmatch_mode != 'never' and nodeid is None and m.group('refwd'):
            l = cl.stringFind(title=title)
            limit = None
            if (tmatch_mode.startswith('creation') or
                    tmatch_mode.startswith('activity')):
                limit, interval = tmatch_mode.split(' ', 1)
                threshold = date.Date('.') - date.Interval(interval)
            for id in l:
                if limit:
                    if threshold < cl.get(id, limit):
                        nodeid = id
                else:
                    nodeid = id

        # if a nodeid was specified, make sure it's valid
        if nodeid is not None and not cl.hasnode(nodeid):
            if pfxmode == 'strict':
                raise MailUsageError, _("""
The node specified by the designator in the subject of your message
("%(nodeid)s") does not exist.

Subject was: "%(subject)s"
""") % locals()
            else:
                title = subject
                nodeid = None

        # Handle the arguments specified by the email gateway command line.
        # We do this by looping over the list of self.arguments looking for
        # a -C to tell us what class then the -S setting string.
        msg_props = {}
        user_props = {}
        file_props = {}
        issue_props = {}
        # so, if we have any arguments, use them
        if self.arguments:
            current_class = 'msg'
            for option, propstring in self.arguments:
                if option in ( '-C', '--class'):
                    current_class = propstring.strip()
                    # XXX this is not flexible enough.
                    #   we should chect for subclasses of these classes,
                    #   not for the class name...
                    if current_class not in ('msg', 'file', 'user', 'issue'):
                        mailadmin = config['ADMIN_EMAIL']
                        raise MailUsageError, _("""
The mail gateway is not properly set up. Please contact
%(mailadmin)s and have them fix the incorrect class specified as:
  %(current_class)s
""") % locals()
                if option in ('-S', '--set'):
                    if current_class == 'issue' :
                        errors, issue_props = setPropArrayFromString(self,
                            cl, propstring.strip(), nodeid)
                    elif current_class == 'file' :
                        temp_cl = self.db.getclass('file')
                        errors, file_props = setPropArrayFromString(self,
                            temp_cl, propstring.strip())
                    elif current_class == 'msg' :
                        temp_cl = self.db.getclass('msg')
                        errors, msg_props = setPropArrayFromString(self,
                            temp_cl, propstring.strip())
                    elif current_class == 'user' :
                        temp_cl = self.db.getclass('user')
                        errors, user_props = setPropArrayFromString(self,
                            temp_cl, propstring.strip())
                    if errors:
                        mailadmin = config['ADMIN_EMAIL']
                        raise MailUsageError, _("""
The mail gateway is not properly set up. Please contact
%(mailadmin)s and have them fix the incorrect properties:
  %(errors)s
""") % locals()

        #
        # handle the users
        #
        # Don't create users if anonymous isn't allowed to register
        create = 1
        anonid = self.db.user.lookup('anonymous')
        if not (self.db.security.hasPermission('Create', anonid, 'user')
                and self.db.security.hasPermission('Email Access', anonid)):
            create = 0

        # ok, now figure out who the author is - create a new user if the
        # "create" flag is true
        author = uidFromAddress(self.db, from_list[0], create=create)

        # if we're not recognised, and we don't get added as a user, then we
        # must be anonymous
        if not author:
            author = anonid

        # make sure the author has permission to use the email interface
        if not self.db.security.hasPermission('Email Access', author):
            if author == anonid:
                # we're anonymous and we need to be a registered user
                from_address = from_list[0][1]
                raise Unauthorized, _("""
You are not a registered user.

Unknown address: %(from_address)s
""") % locals()
            else:
                # we're registered and we're _still_ not allowed access
                raise Unauthorized, _(
                    'You are not permitted to access this tracker.')

        # make sure they're allowed to edit or create this class of information
        if nodeid:
            if not self.db.security.hasPermission('Edit', author, classname,
                    itemid=nodeid):
                raise Unauthorized, _(
                    'You are not permitted to edit %(classname)s.') % locals()
        else:
            if not self.db.security.hasPermission('Create', author, classname):
                raise Unauthorized, _(
                    'You are not permitted to create %(classname)s.'
                    ) % locals()

        # the author may have been created - make sure the change is
        # committed before we reopen the database
        self.db.commit()

        # set the database user as the author
        username = self.db.user.get(author, 'username')
        self.db.setCurrentUser(username)

        # re-get the class with the new database connection
        cl = self.db.getclass(classname)

        # now update the recipients list
        recipients = []
        tracker_email = config['TRACKER_EMAIL'].lower()
        for recipient in message.getaddrlist('to') + message.getaddrlist('cc'):
            r = recipient[1].strip().lower()
            if r == tracker_email or not r:
                continue

            # look up the recipient - create if necessary (and we're
            # allowed to)
            recipient = uidFromAddress(self.db, recipient, create, **user_props)

            # if all's well, add the recipient to the list
            if recipient:
                recipients.append(recipient)

        #
        # handle the subject argument list
        #
        # figure what the properties of this Class are
        properties = cl.getprops()
        props = {}
        args = m.group('args')
        argswhole = m.group('argswhole')
        if args:
            if sfxmode == 'none':
                title += ' ' + argswhole
            else:
                errors, props = setPropArrayFromString(self, cl, args, nodeid)
                # handle any errors parsing the argument list
                if errors:
                    if sfxmode == 'strict':
                        errors = '\n- '.join(map(str, errors))
                        raise MailUsageError, _("""
There were problems handling your subject line argument list:
- %(errors)s

Subject was: "%(subject)s"
""") % locals()
                    else:
                        title += ' ' + argswhole


        # set the issue title to the subject
        title = title.strip()
        if (title and properties.has_key('title') and not
                issue_props.has_key('title')):
            issue_props['title'] = title

        #
        # handle message-id and in-reply-to
        #
        messageid = message.getheader('message-id')
        # generate a messageid if there isn't one
        if not messageid:
            messageid = "<%s.%s.%s%s@%s>"%(time.time(), random.random(),
                classname, nodeid, config['MAIL_DOMAIN'])

        # now handle the body - find the message
        content, attachments = message.extract_content()
        if content is None:
            raise MailUsageError, _("""
Roundup requires the submission to be plain text. The message parser could
not find a text/plain part to use.
""")

        # figure how much we should muck around with the email body
        keep_citations = config['MAILGW_KEEP_QUOTED_TEXT']
        keep_body = config['MAILGW_LEAVE_BODY_UNCHANGED']

        # parse the body of the message, stripping out bits as appropriate
        summary, content = parseContent(content, keep_citations,
            keep_body)
        content = content.strip()

        #
        # handle the attachments
        #
        if properties.has_key('files'):
            files = []
            for (name, mime_type, data) in attachments:
                if not self.db.security.hasPermission('Create', author, 'file'):
                    raise Unauthorized, _(
                        'You are not permitted to create files.')
                if not name:
                    name = "unnamed"
                try:
                    fileid = self.db.file.create(type=mime_type, name=name,
                         content=data, **file_props)
                except exceptions.Reject:
                    pass
                else:
                    files.append(fileid)
            # attach the files to the issue
            if not self.db.security.hasPermission('Edit', author,
                    classname, 'files'):
                raise Unauthorized, _(
                    'You are not permitted to add files to %(classname)s.'
                    ) % locals()

            if nodeid:
                # extend the existing files list
                fileprop = cl.get(nodeid, 'files')
                fileprop.extend(files)
                props['files'] = fileprop
            else:
                # pre-load the files list
                props['files'] = files

        #
        # create the message if there's a message body (content)
        #
        if (content and properties.has_key('messages')):
            if not self.db.security.hasPermission('Create', author, 'msg'):
                raise Unauthorized, _(
                    'You are not permitted to create messages.')

            try:
                message_id = self.db.msg.create(author=author,
                    recipients=recipients, date=date.Date('.'),
                    summary=summary, content=content, files=files,
                    messageid=messageid, inreplyto=inreplyto, **msg_props)
            except exceptions.Reject, error:
                raise MailUsageError, _("""
Mail message was rejected by a detector.
%(error)s
""") % locals()
            # attach the message to the node
            if not self.db.security.hasPermission('Edit', author,
                    classname, 'messages'):
                raise Unauthorized, _(
                    'You are not permitted to add messages to %(classname)s.'
                    ) % locals()

            if nodeid:
                # add the message to the node's list
                messages = cl.get(nodeid, 'messages')
                messages.append(message_id)
                props['messages'] = messages
            else:
                # pre-load the messages list
                props['messages'] = [message_id]

        #
        # perform the node change / create
        #
        try:
            # merge the command line props defined in issue_props into
            # the props dictionary because function(**props, **issue_props)
            # is a syntax error.
            for prop in issue_props.keys() :
                if not props.has_key(prop) :
                    props[prop] = issue_props[prop]

            # Check permissions for each property
            for prop in props.keys():
                if not self.db.security.hasPermission('Edit', author,
                        classname, prop):
                    raise Unauthorized, _('You are not permitted to edit '
                        'property %(prop)s of class %(classname)s.') % locals()

            if nodeid:
                cl.set(nodeid, **props)
            else:
                nodeid = cl.create(**props)
        except (TypeError, IndexError, ValueError), message:
            raise MailUsageError, _("""
There was a problem with the message you sent:
   %(message)s
""") % locals()

        # commit the changes to the DB
        self.db.commit()

        return nodeid


def setPropArrayFromString(self, cl, propString, nodeid=None):
    ''' takes string of form prop=value,value;prop2=value
        and returns (error, prop[..])
    '''
    props = {}
    errors = []
    for prop in string.split(propString, ';'):
        # extract the property name and value
        try:
            propname, value = prop.split('=')
        except ValueError, message:
            errors.append(_('not of form [arg=value,value,...;'
                'arg=value,value,...]'))
            return (errors, props)
        # convert the value to a hyperdb-usable value
        propname = propname.strip()
        try:
            props[propname] = hyperdb.rawToHyperdb(self.db, cl, nodeid,
                propname, value)
        except hyperdb.HyperdbValueError, message:
            errors.append(str(message))
    return errors, props


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


def uidFromAddress(db, address, create=1, **user_props):
    ''' address is from the rfc822 module, and therefore is (name, addr)

        user is created if they don't exist in the db already
        user_props may supply additional user information
    '''
    (realname, address) = address

    # try a straight match of the address
    user = extractUserFromList(db.user, db.user.stringFind(address=address))
    if user is not None:
        return user

    # try the user alternate addresses if possible
    props = db.user.getprops()
    if props.has_key('alternate_addresses'):
        users = db.user.filter(None, {'alternate_addresses': address})
        user = extractUserFromList(db.user, users)
        if user is not None:
            return user

    # try to match the username to the address (for local
    # submissions where the address is empty)
    user = extractUserFromList(db.user, db.user.stringFind(username=address))

    # couldn't match address or username, so create a new user
    if create:
        # generate a username
        if '@' in address:
            username = address.split('@')[0]
        else:
            username = address
        trying = username
        n = 0
        while 1:
            try:
                # does this username exist already?
                db.user.lookup(trying)
            except KeyError:
                break
            n += 1
            trying = username + str(n)

        # create!
        try:
            return db.user.create(username=trying, address=address,
                realname=realname, roles=db.config.NEW_EMAIL_USER_ROLES,
                password=password.Password(password.generatePassword()),
                **user_props)
        except exceptions.Reject:
            return 0
    else:
        return 0


def parseContent(content, keep_citations, keep_body,
        blank_line=re.compile(r'[\r\n]+\s*[\r\n]+'),
        eol=re.compile(r'[\r\n]+'),
        signature=re.compile(r'^[>|\s]*-- ?$'),
        original_msg=re.compile(r'^[>|\s]*-----\s?Original Message\s?-----$')):
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
        elif original_msg.match(lines[0]):
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

# vim: set filetype=python sts=4 sw=4 et si :
