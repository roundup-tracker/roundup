# -*- coding: utf-8 -*-
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
 . A message/rfc822 is treated similar tomultipart/mixed (except for
   special handling of the first text part) if unpack_rfc822 is set in
   the mailgw config section.

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
"""
__docformat__ = 'restructuredtext'

import string, re, os, mimetools, cStringIO, smtplib, socket, binascii, quopri
import time, random, sys, logging
import traceback, rfc822

from email.Header import decode_header

from roundup import configuration, hyperdb, date, password, rfc2822, exceptions
from roundup.mailer import Mailer, MessageSendError
from roundup.i18n import _
from roundup.hyperdb import iter_roles

try:
    import pyme, pyme.core, pyme.constants, pyme.constants.sigsum
except ImportError:
    pyme = None

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

def gpgh_key_getall(key, attr):
    ''' return list of given attribute for all uids in
        a key
    '''
    for u in key.uids:
        yield getattr(u, attr)

def check_pgp_sigs(sigs, gpgctx, author, may_be_unsigned=False):
    ''' Theoretically a PGP message can have several signatures. GPGME
        returns status on all signatures in a list. Walk that list
        looking for the author's signature. Note that even if incoming
        signatures are not required, the processing fails if there is an
        invalid signature.
    '''
    for sig in sigs:
        key = gpgctx.get_key(sig.fpr, False)
        # we really only care about the signature of the user who
        # submitted the email
        if key and (author in gpgh_key_getall(key, 'email')):
            if sig.summary & pyme.constants.sigsum.VALID:
                return True
            else:
                # try to narrow down the actual problem to give a more useful
                # message in our bounce
                if sig.summary & pyme.constants.sigsum.KEY_MISSING:
                    raise MailUsageError, \
                        _("Message signed with unknown key: %s") % sig.fpr
                elif sig.summary & pyme.constants.sigsum.KEY_EXPIRED:
                    raise MailUsageError, \
                        _("Message signed with an expired key: %s") % sig.fpr
                elif sig.summary & pyme.constants.sigsum.KEY_REVOKED:
                    raise MailUsageError, \
                        _("Message signed with a revoked key: %s") % sig.fpr
                else:
                    raise MailUsageError, \
                        _("Invalid PGP signature detected.")

    # we couldn't find a key belonging to the author of the email
    if sigs:
        raise MailUsageError, _("Message signed with unknown key: %s") % sig.fpr
    elif not may_be_unsigned:
        raise MailUsageError, _("Unsigned Message")

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
                # according to rfc 1431 the preceding line ending is part of
                # the boundary so we need to strip that
                length = s.tell()
                s.seek(-2, 1)
                lineending = s.read(2)
                if lineending == '\r\n':
                    s.truncate(length - 2)
                elif lineending[1] in ('\r', '\n'):
                    s.truncate(length - 1)
                else:
                    raise ValueError('Unknown line ending in message.')
                break
            s.write(line)
        if not s.getvalue().strip():
            return None
        s.seek(0)
        return Message(s)

    def getparts(self):
        """Get all parts of this multipart message."""
        # skip over the intro to the first boundary
        self.fp.seek(0)
        self.getpart()

        # accumulate the other parts
        parts = []
        while 1:
            part = self.getpart()
            if part is None:
                break
            parts.append(part)
        return parts

    def _decode_header_to_utf8(self, hdr):
        l = []
        prev_encoded = False
        for part, encoding in decode_header(hdr):
            if encoding:
                part = part.decode(encoding)
            # RFC 2047 specifies that between encoded parts spaces are
            # swallowed while at the borders from encoded to non-encoded
            # or vice-versa we must preserve a space. Multiple adjacent
            # non-encoded parts should not occur.
            if l and prev_encoded != bool(encoding):
                l.append(' ')
            prev_encoded = bool(encoding)
            l.append(part)
        return ''.join([s.encode('utf-8') for s in l])

    def getheader(self, name, default=None):
        hdr = mimetools.Message.getheader(self, name, default)
        # TODO are there any other False values possible?
        # TODO if not hdr: return hdr
        if hdr is None:
            return None
        if not hdr:
            return ''
        if hdr:
            hdr = hdr.replace('\n','') # Inserted by rfc822.readheaders
        return self._decode_header_to_utf8(hdr)

    def getaddrlist(self, name):
        # overload to decode the name part of the address
        l = []
        for (name, addr) in mimetools.Message.getaddrlist(self, name):
            name = self._decode_header_to_utf8(name)
            l.append((name, addr))
        return l

    def getname(self):
        """Find an appropriate name for this message."""
        name = None
        if self.gettype() == 'message/rfc822':
            # handle message/rfc822 specially - the name should be
            # the subject of the actual e-mail embedded here
            # we add a '.eml' extension like other email software does it
            self.fp.seek(0)
            s = cStringIO.StringIO(self.getbody())
            name = Message(s).getheader('subject')
            if name:
                name = name + '.eml'
        if not name:
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
    # message/rfc822:
    #   Only if configured in [mailgw] unpack_rfc822

    def extract_content(self, parent_type=None, ignore_alternatives=False,
        unpack_rfc822=False):
        """Extract the body and the attachments recursively.

           If the content is hidden inside a multipart/alternative part,
           we use the *last* text/plain part of the *first*
           multipart/alternative in the whole message.
        """
        content_type = self.gettype()
        content = None
        attachments = []

        if content_type == 'text/plain':
            content = self.getbody()
        elif content_type[:10] == 'multipart/':
            content_found = bool (content)
            ig = ignore_alternatives and not content_found
            for part in self.getparts():
                new_content, new_attach = part.extract_content(content_type,
                    not content and ig, unpack_rfc822)

                # If we haven't found a text/plain part yet, take this one,
                # otherwise make it an attachment.
                if not content:
                    content = new_content
                    cpart   = part
                elif new_content:
                    if content_found or content_type != 'multipart/alternative':
                        attachments.append(part.text_as_attachment())
                    else:
                        # if we have found a text/plain in the current
                        # multipart/alternative and find another one, we
                        # use the first as an attachment (if configured)
                        # and use the second one because rfc 2046, sec.
                        # 5.1.4. specifies that later parts are better
                        # (thanks to Philipp Gortan for pointing this
                        # out)
                        attachments.append(cpart.text_as_attachment())
                        content = new_content
                        cpart   = part

                attachments.extend(new_attach)
            if ig and content_type == 'multipart/alternative' and content:
                attachments = []
        elif unpack_rfc822 and content_type == 'message/rfc822':
            s = cStringIO.StringIO(self.getbody())
            m = Message(s)
            ig = ignore_alternatives and not content
            new_content, attachments = m.extract_content(m.gettype(), ig,
                unpack_rfc822)
            attachments.insert(0, m.text_as_attachment())
        elif (parent_type == 'multipart/signed' and
              content_type == 'application/pgp-signature'):
            # ignore it so it won't be saved as an attachment
            pass
        else:
            attachments.append(self.as_attachment())
        return content, attachments

    def text_as_attachment(self):
        """Return first text/plain part as Message"""
        if not self.gettype().startswith ('multipart/'):
            return self.as_attachment()
        for part in self.getparts():
            content_type = part.gettype()
            if content_type == 'text/plain':
                return part.as_attachment()
            elif content_type.startswith ('multipart/'):
                p = part.text_as_attachment()
                if p:
                    return p
        return None

    def as_attachment(self):
        """Return this message as an attachment."""
        return (self.getname(), self.gettype(), self.getbody())

    def pgp_signed(self):
        ''' RFC 3156 requires OpenPGP MIME mail to have the protocol parameter
        '''
        return self.gettype() == 'multipart/signed' \
            and self.typeheader.find('protocol="application/pgp-signature"') != -1

    def pgp_encrypted(self):
        ''' RFC 3156 requires OpenPGP MIME mail to have the protocol parameter
        '''
        return self.gettype() == 'multipart/encrypted' \
            and self.typeheader.find('protocol="application/pgp-encrypted"') != -1

    def decrypt(self, author, may_be_unsigned=False):
        ''' decrypt an OpenPGP MIME message
            This message must be signed as well as encrypted using the
            "combined" method if incoming signatures are configured.
            The decrypted contents are returned as a new message.
        '''
        (hdr, msg) = self.getparts()
        # According to the RFC 3156 encrypted mail must have exactly two parts.
        # The first part contains the control information. Let's verify that
        # the message meets the RFC before we try to decrypt it.
        if hdr.getbody().strip() != 'Version: 1' \
           or hdr.gettype() != 'application/pgp-encrypted':
            raise MailUsageError, \
                _("Unknown multipart/encrypted version.")

        context = pyme.core.Context()
        ciphertext = pyme.core.Data(msg.getbody())
        plaintext = pyme.core.Data()

        result = context.op_decrypt_verify(ciphertext, plaintext)

        if result:
            raise MailUsageError, _("Unable to decrypt your message.")

        # we've decrypted it but that just means they used our public
        # key to send it to us. now check the signatures to see if it
        # was signed by someone we trust
        result = context.op_verify_result()
        check_pgp_sigs(result.signatures, context, author,
            may_be_unsigned = may_be_unsigned)

        plaintext.seek(0,0)
        # pyme.core.Data implements a seek method with a different signature
        # than roundup can handle. So we'll put the data in a container that
        # the Message class can work with.
        c = cStringIO.StringIO()
        c.write(plaintext.read())
        c.seek(0)
        return Message(c)

    def verify_signature(self, author):
        ''' verify the signature of an OpenPGP MIME message
            This only handles detached signatures. Old style
            PGP mail (i.e. '-----BEGIN PGP SIGNED MESSAGE----')
            is archaic and not supported :)
        '''
        # we don't check the micalg parameter...gpgme seems to
        # figure things out on its own
        (msg, sig) = self.getparts()

        if sig.gettype() != 'application/pgp-signature':
            raise MailUsageError, \
                _("No PGP signature found in message.")

        # msg.getbody() is skipping over some headers that are
        # required to be present for verification to succeed so
        # we'll do this by hand
        msg.fp.seek(0)
        # according to rfc 3156 the data "MUST first be converted
        # to its content-type specific canonical form. For
        # text/plain this means conversion to an appropriate
        # character set and conversion of line endings to the
        # canonical <CR><LF> sequence."
        # TODO: what about character set conversion?
        canonical_msg = re.sub('(?<!\r)\n', '\r\n', msg.fp.read())
        msg_data = pyme.core.Data(canonical_msg)
        sig_data = pyme.core.Data(sig.getbody())

        context = pyme.core.Context()
        context.op_verify(sig_data, msg_data, None)

        # check all signatures for validity
        result = context.op_verify_result()
        check_pgp_sigs(result.signatures, context, author)

class parsedMessage:

    def __init__(self, mailgw, message):
        self.mailgw = mailgw
        self.config = mailgw.instance.config
        self.db = mailgw.db
        self.message = message
        self.subject = message.getheader('subject', '')
        self.has_prefix = False
        self.matches = dict.fromkeys(['refwd', 'quote', 'classname',
                                 'nodeid', 'title', 'args', 'argswhole'])
        self.from_list = message.getaddrlist('resent-from') \
                         or message.getaddrlist('from')
        self.pfxmode = self.config['MAILGW_SUBJECT_PREFIX_PARSING']
        self.sfxmode = self.config['MAILGW_SUBJECT_SUFFIX_PARSING']
        # these are filled in by subsequent parsing steps
        self.classname = None
        self.properties = None
        self.cl = None
        self.nodeid = None
        self.author = None
        self.recipients = None
        self.msg_props = {}
        self.props = None
        self.content = None
        self.attachments = None
        self.crypt = False

    def handle_ignore(self):
        ''' Check to see if message can be safely ignored:
            detect loops and
            Precedence: Bulk, or Microsoft Outlook autoreplies
        '''
        if self.message.getheader('x-roundup-loop', ''):
            raise IgnoreLoop
        if (self.message.getheader('precedence', '') == 'bulk'
                or self.subject.lower().find("autoreply") > 0):
            raise IgnoreBulk

    def handle_help(self):
        ''' Check to see if the message contains a usage/help request
        '''
        if self.subject.strip().lower() == 'help':
            raise MailUsageHelp

    def check_subject(self):
        ''' Check to see if the message contains a valid subject line
        '''
        if not self.subject:
            raise MailUsageError, _("""
Emails to Roundup trackers must include a Subject: line!
""")

    def parse_subject(self):
        ''' Matches subjects like:
        Re: "[issue1234] title of issue [status=resolved]"
        
        Each part of the subject is matched, stored, then removed from the
        start of the subject string as needed. The stored values are then
        returned
        '''

        tmpsubject = self.subject

        sd_open, sd_close = self.config['MAILGW_SUBJECT_SUFFIX_DELIMITERS']
        delim_open = re.escape(sd_open)
        if delim_open in '[(': delim_open = '\\' + delim_open
        delim_close = re.escape(sd_close)
        if delim_close in '[(': delim_close = '\\' + delim_close

        # Look for Re: et. al. Used later on for MAILGW_SUBJECT_CONTENT_MATCH
        re_re = r"(?P<refwd>%s)\s*" % self.config["MAILGW_REFWD_RE"].pattern
        m = re.match(re_re, tmpsubject, re.IGNORECASE|re.VERBOSE|re.UNICODE)
        if m:
            m = m.groupdict()
            if m['refwd']:
                self.matches.update(m)
                tmpsubject = tmpsubject[len(m['refwd']):] # Consume Re:

        # Look for Leading "
        m = re.match(r'(?P<quote>\s*")', tmpsubject,
                     re.IGNORECASE)
        if m:
            self.matches.update(m.groupdict())
            tmpsubject = tmpsubject[len(self.matches['quote']):] # Consume quote

        # Check if the subject includes a prefix
        self.has_prefix = re.search(r'^%s(\w+)%s'%(delim_open,
            delim_close), tmpsubject.strip())

        # Match the classname if specified
        class_re = r'%s(?P<classname>(%s))(?P<nodeid>\d+)?%s'%(delim_open,
            "|".join(self.db.getclasses()), delim_close)
        # Note: re.search, not re.match as there might be garbage
        # (mailing list prefix, etc.) before the class identifier
        m = re.search(class_re, tmpsubject, re.IGNORECASE)
        if m:
            self.matches.update(m.groupdict())
            # Skip to the end of the class identifier, including any
            # garbage before it.

            tmpsubject = tmpsubject[m.end():]

        # Match the title of the subject
        # if we've not found a valid classname prefix then force the
        # scanning to handle there being a leading delimiter
        title_re = r'(?P<title>%s[^%s]*)'%(
            not self.matches['classname'] and '.' or '', delim_open)
        m = re.match(title_re, tmpsubject.strip(), re.IGNORECASE)
        if m:
            self.matches.update(m.groupdict())
            tmpsubject = tmpsubject[len(self.matches['title']):] # Consume title

        if self.matches['title']:
            self.matches['title'] = self.matches['title'].strip()
        else:
            self.matches['title'] = ''

        # strip off the quotes that dumb emailers put around the subject, like
        #      Re: "[issue1] bla blah"
        if self.matches['quote'] and self.matches['title'].endswith('"'):
            self.matches['title'] = self.matches['title'][:-1]
        
        # Match any arguments specified
        args_re = r'(?P<argswhole>%s(?P<args>.+?)%s)?'%(delim_open,
            delim_close)
        m = re.search(args_re, tmpsubject.strip(), re.IGNORECASE|re.VERBOSE)
        if m:
            self.matches.update(m.groupdict())

    def rego_confirm(self):
        ''' Check for registration OTK and confirm the registration if found
        '''
        
        if self.config['EMAIL_REGISTRATION_CONFIRMATION']:
            otk_re = re.compile('-- key (?P<otk>[a-zA-Z0-9]{32})')
            otk = otk_re.search(self.matches['title'] or '')
            if otk:
                self.db.confirm_registration(otk.group('otk'))
                subject = 'Your registration to %s is complete' % \
                          self.config['TRACKER_NAME']
                sendto = [self.from_list[0][1]]
                self.mailgw.mailer.standard_message(sendto, subject, '')
                return 1
        return 0

    def get_classname(self):
        ''' Determine the classname of the node being created/edited
        '''
        subject = self.subject

        # get the classname
        if self.pfxmode == 'none':
            classname = None
        else:
            classname = self.matches['classname']

        if not classname and self.has_prefix and self.pfxmode == 'strict':
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

        # try to get the class specified - if "loose" or "none" then fall
        # back on the default
        attempts = []
        if classname:
            attempts.append(classname)

        if self.mailgw.default_class:
            attempts.append(self.mailgw.default_class)
        else:
            attempts.append(self.config['MAILGW_DEFAULT_CLASS'])

        # first valid class name wins
        self.cl = None
        for trycl in attempts:
            try:
                self.cl = self.db.getclass(trycl)
                classname = self.classname = trycl
                break
            except KeyError:
                pass

        if not self.cl:
            validname = ', '.join(self.db.getclasses())
            if classname:
                raise MailUsageError, _("""
The class name you identified in the subject line ("%(classname)s") does
not exist in the database.

Valid class names are: %(validname)s
Subject was: "%(subject)s"
""") % locals()
            else:
                raise MailUsageError, _("""
You did not identify a class name in the subject line and there is no
default set for this tracker. The subject must contain a class name or
designator to indicate the 'topic' of the message. For example:
    Subject: [issue] This is a new issue
      - this will create a new issue in the tracker with the title 'This is
        a new issue'.
    Subject: [issue1234] This is a followup to issue 1234
      - this will append the message's contents to the existing issue 1234
        in the tracker.

Subject was: '%(subject)s'
""") % locals()
        # get the class properties
        self.properties = self.cl.getprops()
        

    def get_nodeid(self):
        ''' Determine the nodeid from the message and return it if found
        '''
        title = self.matches['title']
        subject = self.subject
        
        if self.pfxmode == 'none':
            nodeid = None
        else:
            nodeid = self.matches['nodeid']

        # try in-reply-to to match the message if there's no nodeid
        inreplyto = self.message.getheader('in-reply-to') or ''
        if nodeid is None and inreplyto:
            l = self.db.getclass('msg').stringFind(messageid=inreplyto)
            if l:
                nodeid = self.cl.filter(None, {'messages':l})[0]


        # but we do need either a title or a nodeid...
        if nodeid is None and not title:
            raise MailUsageError, _("""
I cannot match your message to a node in the database - you need to either
supply a full designator (with number, eg "[issue123]") or keep the
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
        tmatch_mode = self.config['MAILGW_SUBJECT_CONTENT_MATCH']
        if tmatch_mode != 'never' and nodeid is None and self.matches['refwd']:
            l = self.cl.stringFind(title=title)
            limit = None
            if (tmatch_mode.startswith('creation') or
                    tmatch_mode.startswith('activity')):
                limit, interval = tmatch_mode.split(' ', 1)
                threshold = date.Date('.') - date.Interval(interval)
            for id in l:
                if limit:
                    if threshold < self.cl.get(id, limit):
                        nodeid = id
                else:
                    nodeid = id

        # if a nodeid was specified, make sure it's valid
        if nodeid is not None and not self.cl.hasnode(nodeid):
            if self.pfxmode == 'strict':
                raise MailUsageError, _("""
The node specified by the designator in the subject of your message
("%(nodeid)s") does not exist.

Subject was: "%(subject)s"
""") % locals()
            else:
                nodeid = None
        self.nodeid = nodeid

    def get_author_id(self):
        ''' Attempt to get the author id from the existing registered users,
            otherwise attempt to register a new user and return their id
        '''
        # Don't create users if anonymous isn't allowed to register
        create = 1
        anonid = self.db.user.lookup('anonymous')
        if not (self.db.security.hasPermission('Register', anonid, 'user')
                and self.db.security.hasPermission('Email Access', anonid)):
            create = 0

        # ok, now figure out who the author is - create a new user if the
        # "create" flag is true
        author = uidFromAddress(self.db, self.from_list[0], create=create)

        # if we're not recognised, and we don't get added as a user, then we
        # must be anonymous
        if not author:
            author = anonid

        # make sure the author has permission to use the email interface
        if not self.db.security.hasPermission('Email Access', author):
            if author == anonid:
                # we're anonymous and we need to be a registered user
                from_address = self.from_list[0][1]
                registration_info = ""
                if self.db.security.hasPermission('Web Access', author) and \
                   self.db.security.hasPermission('Register', anonid, 'user'):
                    tracker_web = self.config.TRACKER_WEB
                    registration_info = """ Please register at:

%(tracker_web)suser?template=register

...before sending mail to the tracker.""" % locals()

                raise Unauthorized, _("""
You are not a registered user.%(registration_info)s

Unknown address: %(from_address)s
""") % locals()
            else:
                # we're registered and we're _still_ not allowed access
                raise Unauthorized, _(
                    'You are not permitted to access this tracker.')
        self.author = author

    def check_permissions(self):
        ''' Check if the author has permission to edit or create this
            class of node
        '''
        if self.nodeid:
            if not self.db.security.hasPermission('Edit', self.author,
                    self.classname, itemid=self.nodeid):
                raise Unauthorized, _(
                    'You are not permitted to edit %(classname)s.'
                    ) % self.__dict__
        else:
            if not self.db.security.hasPermission('Create', self.author,
                    self.classname):
                raise Unauthorized, _(
                    'You are not permitted to create %(classname)s.'
                    ) % self.__dict__

    def commit_and_reopen_as_author(self):
        ''' the author may have been created - make sure the change is
            committed before we reopen the database
            then re-open the database as the author
        '''
        self.db.commit()

        # set the database user as the author
        username = self.db.user.get(self.author, 'username')
        self.db.setCurrentUser(username)

        # re-get the class with the new database connection
        self.cl = self.db.getclass(self.classname)

    def get_recipients(self):
        ''' Get the list of recipients who were included in message and
            register them as users if possible
        '''
        # Don't create users if anonymous isn't allowed to register
        create = 1
        anonid = self.db.user.lookup('anonymous')
        if not (self.db.security.hasPermission('Register', anonid, 'user')
                and self.db.security.hasPermission('Email Access', anonid)):
            create = 0

        # get the user class arguments from the commandline
        user_props = self.mailgw.get_class_arguments('user')

        # now update the recipients list
        recipients = []
        tracker_email = self.config['TRACKER_EMAIL'].lower()
        msg_to = self.message.getaddrlist('to')
        msg_cc = self.message.getaddrlist('cc')
        for recipient in msg_to + msg_cc:
            r = recipient[1].strip().lower()
            if r == tracker_email or not r:
                continue

            # look up the recipient - create if necessary (and we're
            # allowed to)
            recipient = uidFromAddress(self.db, recipient, create, **user_props)

            # if all's well, add the recipient to the list
            if recipient:
                recipients.append(recipient)
        self.recipients = recipients

    def get_props(self):
        ''' Generate all the props for the new/updated node and return them
        '''
        subject = self.subject
        
        # get the commandline arguments for issues
        issue_props = self.mailgw.get_class_arguments('issue', self.classname)
        
        #
        # handle the subject argument list
        #
        # figure what the properties of this Class are
        props = {}
        args = self.matches['args']
        argswhole = self.matches['argswhole']
        title = self.matches['title']
        
        # Reform the title 
        if self.matches['nodeid'] and self.nodeid is None:
            title = subject
        
        if args:
            if self.sfxmode == 'none':
                title += ' ' + argswhole
            else:
                errors, props = setPropArrayFromString(self, self.cl, args,
                    self.nodeid)
                # handle any errors parsing the argument list
                if errors:
                    if self.sfxmode == 'strict':
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
        if (title and self.properties.has_key('title') and not
                issue_props.has_key('title')):
            issue_props['title'] = title
        if (self.nodeid and self.properties.has_key('title') and not
                self.config['MAILGW_SUBJECT_UPDATES_TITLE']):
            issue_props['title'] = self.cl.get(self.nodeid,'title')

        # merge the command line props defined in issue_props into
        # the props dictionary because function(**props, **issue_props)
        # is a syntax error.
        for prop in issue_props.keys() :
            if not props.has_key(prop) :
                props[prop] = issue_props[prop]

        self.props = props

    def get_pgp_message(self):
        ''' If they've enabled PGP processing then verify the signature
            or decrypt the message
        '''
        def pgp_role():
            """ if PGP_ROLES is specified the user must have a Role in the list
                or we will skip PGP processing
            """
            if self.config.PGP_ROLES:
                return self.db.user.has_role(self.author,
                    *iter_roles(self.config.PGP_ROLES))
            else:
                return True

        if self.config.PGP_ENABLE:
            if pgp_role() and self.config.PGP_ENCRYPT:
                self.crypt = True
            assert pyme, 'pyme is not installed'
            # signed/encrypted mail must come from the primary address
            author_address = self.db.user.get(self.author, 'address')
            if self.config.PGP_HOMEDIR:
                os.environ['GNUPGHOME'] = self.config.PGP_HOMEDIR
            if self.config.PGP_REQUIRE_INCOMING in ('encrypted', 'both') \
                and pgp_role() and not self.message.pgp_encrypted():
                raise MailUsageError, _(
                    "This tracker has been configured to require all email "
                    "be PGP encrypted.")
            if self.message.pgp_signed():
                self.message.verify_signature(author_address)
            elif self.message.pgp_encrypted():
                # Replace message with the contents of the decrypted
                # message for content extraction
                # Note: the bounce-handling code now makes sure that
                # either the encrypted mail received is sent back or
                # that the error message is encrypted if needed.
                encr_only = self.config.PGP_REQUIRE_INCOMING == 'encrypted'
                encr_only = encr_only or not pgp_role()
                self.crypt = True
                self.message = self.message.decrypt(author_address,
                    may_be_unsigned = encr_only)
            elif pgp_role():
                raise MailUsageError, _("""
This tracker has been configured to require all email be PGP signed or
encrypted.""")

    def get_content_and_attachments(self):
        ''' get the attachments and first text part from the message
        '''
        ig = self.config.MAILGW_IGNORE_ALTERNATIVES
        self.content, self.attachments = self.message.extract_content(
            ignore_alternatives=ig,
            unpack_rfc822=self.config.MAILGW_UNPACK_RFC822)
        

    def create_files(self):
        ''' Create a file for each attachment in the message
        '''
        if not self.properties.has_key('files'):
            return
        files = []
        file_props = self.mailgw.get_class_arguments('file')
        
        if self.attachments:
            for (name, mime_type, data) in self.attachments:
                if not self.db.security.hasPermission('Create', self.author,
                    'file'):
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
            # allowed to attach the files to an existing node?
            if self.nodeid and not self.db.security.hasPermission('Edit',
                    self.author, self.classname, 'files'):
                raise Unauthorized, _(
                    'You are not permitted to add files to %(classname)s.'
                    ) % self.__dict__

            self.msg_props['files'] = files
            if self.nodeid:
                # extend the existing files list
                fileprop = self.cl.get(self.nodeid, 'files')
                fileprop.extend(files)
                files = fileprop

            self.props['files'] = files

    def create_msg(self):
        ''' Create msg containing all the relevant information from the message
        '''
        if not self.properties.has_key('messages'):
            return
        msg_props = self.mailgw.get_class_arguments('msg')
        self.msg_props.update (msg_props)
        
        # Get the message ids
        inreplyto = self.message.getheader('in-reply-to') or ''
        messageid = self.message.getheader('message-id')
        # generate a messageid if there isn't one
        if not messageid:
            messageid = "<%s.%s.%s%s@%s>"%(time.time(), random.random(),
                self.classname, self.nodeid, self.config['MAIL_DOMAIN'])
        
        if self.content is None:
            raise MailUsageError, _("""
Roundup requires the submission to be plain text. The message parser could
not find a text/plain part to use.
""")

        # parse the body of the message, stripping out bits as appropriate
        summary, content = parseContent(self.content, config=self.config)
        content = content.strip()

        if content:
            if not self.db.security.hasPermission('Create', self.author, 'msg'):
                raise Unauthorized, _(
                    'You are not permitted to create messages.')

            try:
                message_id = self.db.msg.create(author=self.author,
                    recipients=self.recipients, date=date.Date('.'),
                    summary=summary, content=content,
                    messageid=messageid, inreplyto=inreplyto, **self.msg_props)
            except exceptions.Reject, error:
                raise MailUsageError, _("""
Mail message was rejected by a detector.
%(error)s
""") % locals()
            # allowed to attach the message to the existing node?
            if self.nodeid and not self.db.security.hasPermission('Edit',
                    self.author, self.classname, 'messages'):
                raise Unauthorized, _(
                    'You are not permitted to add messages to %(classname)s.'
                    ) % self.__dict__

            if self.nodeid:
                # add the message to the node's list
                messages = self.cl.get(self.nodeid, 'messages')
                messages.append(message_id)
                self.props['messages'] = messages
            else:
                # pre-load the messages list
                self.props['messages'] = [message_id]

    def create_node(self):
        ''' Create/update a node using self.props 
        '''
        classname = self.classname
        try:
            if self.nodeid:
                # Check permissions for each property
                for prop in self.props.keys():
                    if not self.db.security.hasPermission('Edit', self.author,
                            classname, prop):
                        raise Unauthorized, _('You are not permitted to edit '
                            'property %(prop)s of class %(classname)s.'
                            ) % locals()
                self.cl.set(self.nodeid, **self.props)
            else:
                # Check permissions for each property
                for prop in self.props.keys():
                    if not self.db.security.hasPermission('Create', self.author,
                            classname, prop):
                        raise Unauthorized, _('You are not permitted to set '
                            'property %(prop)s of class %(classname)s.'
                            ) % locals()
                self.nodeid = self.cl.create(**self.props)
        except (TypeError, IndexError, ValueError, exceptions.Reject), message:
            raise MailUsageError, _("""
There was a problem with the message you sent:
   %(message)s
""") % locals()

        return self.nodeid

        # XXX Don't enable. This doesn't work yet.
#  "[^A-z.]tracker\+(?P<classname>[^\d\s]+)(?P<nodeid>\d+)\@some.dom.ain[^A-z.]"
        # handle delivery to addresses like:tracker+issue25@some.dom.ain
        # use the embedded issue number as our issue
#            issue_re = config['MAILGW_ISSUE_ADDRESS_RE']
#            if issue_re:
#                for header in ['to', 'cc', 'bcc']:
#                    addresses = message.getheader(header, '')
#                if addresses:
#                  # FIXME, this only finds the first match in the addresses.
#                    issue = re.search(issue_re, addresses, 'i')
#                    if issue:
#                        classname = issue.group('classname')
#                        nodeid = issue.group('nodeid')
#                        break

    # Default sequence of methods to be called on message. Use this for
    # easier override of the default message processing
    # list consists of tuples (method, return_if_true), the parsing
    # returns if the return_if_true flag is set for a method *and* the
    # method returns something that evaluates to True.
    method_list = [
        # Filter out messages to ignore
        ("handle_ignore", False),
        # Check for usage/help requests
        ("handle_help", False),
        # Check if the subject line is valid
        ("check_subject", False),
        # get importants parts from subject
        ("parse_subject", False),
        # check for registration OTK
        ("rego_confirm", True),
        # get the classname
        ("get_classname", False),
        # get the optional nodeid:
        ("get_nodeid", False),
        # Determine who the author is:
        ("get_author_id", False),
        # allowed to edit or create this class?
        ("check_permissions", False),
        # author may have been created:
        # commit author to database and re-open as author
        ("commit_and_reopen_as_author", False),
        # Get the recipients list
        ("get_recipients", False),
        # get the new/updated node props
        ("get_props", False),
        # Handle PGP signed or encrypted messages
        ("get_pgp_message", False),
        # extract content and attachments from message body:
        ("get_content_and_attachments", False),
        # put attachments into files linked to the issue:
        ("create_files", False),
        # create the message if there's a message body (content):
        ("create_msg", False),
    ]


    def parse (self):
        for methodname, flag in self.method_list:
            method = getattr (self, methodname)
            ret = method()
            if flag and ret:
                return
        # perform the node change / create:
        return self.create_node()


class MailGW:

    # To override the message parsing, derive your own class from
    # parsedMessage and assign to parsed_message_class in a derived
    # class of MailGW
    parsed_message_class = parsedMessage

    def __init__(self, instance, arguments=()):
        self.instance = instance
        self.arguments = arguments
        self.default_class = None
        for option, value in self.arguments:
            if option == '-c':
                self.default_class = value.strip()

        self.mailer = Mailer(instance.config)
        self.logger = logging.getLogger('roundup.mailgw')

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

    def do_imap(self, server, user='', password='', mailbox='', ssl=0,
            cram=0):
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
            if cram:
                server.login_cram_md5(user, password)
            else:
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

        self.parsed_message = None
        crypt = False
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
        # Note: by default we return the message received not the
        # internal state of the parsedMessage -- except for
        # MailUsageError, Unauthorized and for unknown exceptions. For
        # the latter cases we make sure the error message is encrypted
        # if needed (if it either was received encrypted or pgp
        # processing is turned on for the user).
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
            if self.parsed_message:
                message = self.parsed_message.message
                crypt = self.parsed_message.crypt
            self.mailer.bounce_message(message, [sendto[0][1]], m, crypt=crypt)
        except Unauthorized, value:
            # just inform the user that he is not authorized
            m = ['']
            m.append(str(value))
            if self.parsed_message:
                message = self.parsed_message.message
                crypt = self.parsed_message.crypt
            self.mailer.bounce_message(message, [sendto[0][1]], m, crypt=crypt)
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
            m = ['']
            m.append('An unexpected error occurred during the processing')
            m.append('of your message. The tracker administrator is being')
            m.append('notified.\n')
            if self.parsed_message:
                message = self.parsed_message.message
                crypt = self.parsed_message.crypt
            self.mailer.bounce_message(message, [sendto[0][1]], m, crypt=crypt)

            m.append('----------------')
            m.append(traceback.format_exc())
            self.mailer.bounce_message(message, [self.instance.config.ADMIN_EMAIL], m)

    def handle_message(self, message):
        ''' message - a Message instance

        Parse the message as per the module docstring.
        '''
        # get database handle for handling one email
        self.db = self.instance.open ('admin')
        try:
            return self._handle_message(message)
        finally:
            self.db.close()

    def _handle_message(self, message):
        ''' message - a Message instance

        Parse the message as per the module docstring.
        The following code expects an opened database and a try/finally
        that closes the database.
        '''
        self.parsed_message = self.parsed_message_class(self, message)
        nodeid = self.parsed_message.parse ()

        # commit the changes to the DB
        self.db.commit()

        self.parsed_message = None
        return nodeid

    def get_class_arguments(self, class_type, classname=None):
        ''' class_type - a valid node class type:
                - 'user' refers to the author of a message
                - 'issue' refers to an issue-type class (to which the
                  message is appended) specified in parameter classname
                  Note that this need not be the real classname, we get
                  the real classname used as a parameter (from previous
                  message-parsing steps)
                - 'file' specifies a file-type class
                - 'msg' is the message-class
            classname - the name of the current issue-type class

        Parse the commandline arguments and retrieve the properties that
        are relevant to the class_type. We now allow multiple -S options
        per class_type (-C option).
        '''
        allprops = {}

        classname = classname or class_type
        cls_lookup = { 'issue' : classname }
        
        # Allow other issue-type classes -- take the real classname from
        # previous parsing-steps of the message:
        clsname = cls_lookup.get (class_type, class_type)

        # check if the clsname is valid
        try:
            self.db.getclass(clsname)
        except KeyError:
            mailadmin = self.instance.config['ADMIN_EMAIL']
            raise MailUsageError, _("""
The mail gateway is not properly set up. Please contact
%(mailadmin)s and have them fix the incorrect class specified as:
  %(clsname)s
""") % locals()
        
        if self.arguments:
            # The default type on the commandline is msg
            if class_type == 'msg':
                current_type = class_type
            else:
                current_type = None
            
            # Handle the arguments specified by the email gateway command line.
            # We do this by looping over the list of self.arguments looking for
            # a -C to match the class we want, then use the -S setting string.
            for option, propstring in self.arguments:
                if option in ( '-C', '--class'):
                    current_type = propstring.strip()
                    
                    if current_type != class_type:
                        current_type = None

                elif current_type and option in ('-S', '--set'):
                    cls = cls_lookup.get (current_type, current_type)
                    temp_cl = self.db.getclass(cls)
                    errors, props = setPropArrayFromString(self,
                        temp_cl, propstring.strip())

                    if errors:
                        mailadmin = self.instance.config['ADMIN_EMAIL']
                        raise MailUsageError, _("""
The mail gateway is not properly set up. Please contact
%(mailadmin)s and have them fix the incorrect properties:
  %(errors)s
""") % locals()
                    allprops.update(props)

        return allprops


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
        # We want an exact match of the email, not just a substring
        # match. Otherwise e.g. support@example.com would match
        # discuss-support@example.com which is not what we want.
        found_users = []
        for u in users:
            alt = db.user.get(u, 'alternate_addresses').split('\n')
            for a in alt:
                if a.strip().lower() == address.lower():
                    found_users.append(u)
                    break
        user = extractUserFromList(db.user, found_users)
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
                password=password.Password(password.generatePassword(), config=db.config),
                **user_props)
        except exceptions.Reject:
            return 0
    else:
        return 0

def parseContent(content, keep_citations=None, keep_body=None, config=None):
    """Parse mail message; return message summary and stripped content

    The message body is divided into sections by blank lines.
    Sections where the second and all subsequent lines begin with a ">"
    or "|" character are considered "quoting sections". The first line of
    the first non-quoting section becomes the summary of the message.

    Arguments:

        keep_citations: declared for backward compatibility.
            If omitted or None, use config["MAILGW_KEEP_QUOTED_TEXT"]

        keep_body: declared for backward compatibility.
            If omitted or None, use config["MAILGW_LEAVE_BODY_UNCHANGED"]

        config: tracker configuration object.
            If omitted or None, use default configuration.

    """
    if config is None:
        config = configuration.CoreConfig()
    if keep_citations is None:
        keep_citations = config["MAILGW_KEEP_QUOTED_TEXT"]
    if keep_body is None:
        keep_body = config["MAILGW_LEAVE_BODY_UNCHANGED"]
    eol = config["MAILGW_EOL_RE"]
    signature = config["MAILGW_SIGN_RE"]
    original_msg = config["MAILGW_ORIGMSG_RE"]

    # strip off leading carriage-returns / newlines
    i = 0
    for i in range(len(content)):
        if content[i] not in '\r\n':
            break
    if i > 0:
        sections = config["MAILGW_BLANKLINE_RE"].split(content[i:])
    else:
        sections = config["MAILGW_BLANKLINE_RE"].split(content)

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
