"""Sending Roundup-specific mail over SMTP.
"""
__docformat__ = 'restructuredtext'
# $Id: mailer.py,v 1.22 2008-07-21 01:44:58 richard Exp $

import time, quopri, os, socket, smtplib, re, sys, traceback, email

from cStringIO import StringIO

from roundup import __version__
from roundup.date import get_timezone

from email.Utils import formatdate, formataddr
from email.Message import Message
from email.Header import Header
from email.MIMEText import MIMEText
from email.MIMEMultipart import MIMEMultipart

class MessageSendError(RuntimeError):
    pass

def encode_quopri(msg):
    orig = msg.get_payload()
    encdata = quopri.encodestring(orig)
    msg.set_payload(encdata)
    del msg['Content-Transfer-Encoding']
    msg['Content-Transfer-Encoding'] = 'quoted-printable'

class Mailer:
    """Roundup-specific mail sending."""
    def __init__(self, config):
        self.config = config

        # set to indicate to roundup not to actually _send_ email
        # this var must contain a file to write the mail to
        self.debug = os.environ.get('SENDMAILDEBUG', '') \
            or config["MAIL_DEBUG"]

        # set timezone so that things like formatdate(localtime=True)
        # use the configured timezone
        # apparently tzset doesn't exist in python under Windows, my bad.
        # my pathetic attempts at googling a Windows-solution failed
        # so if you're on Windows your mail won't use your configured
        # timezone.
        if hasattr(time, 'tzset'):
            os.environ['TZ'] = get_timezone(self.config.TIMEZONE).tzname(None)
            time.tzset()

    def get_standard_message(self, to, subject, author=None, multipart=False):
        '''Form a standard email message from Roundup.

        "to"      - recipients list
        "subject" - Subject
        "author"  - (name, address) tuple or None for admin email

        Subject and author are encoded using the EMAIL_CHARSET from the
        config (default UTF-8).

        Returns a Message object.
        '''
        # encode header values if they need to be
        charset = getattr(self.config, 'EMAIL_CHARSET', 'utf-8')
        tracker_name = unicode(self.config.TRACKER_NAME, 'utf-8')
        if not author:
            author = formataddr((tracker_name, self.config.ADMIN_EMAIL))
        else:
            name = unicode(author[0], 'utf-8')
            author = formataddr((name, author[1]))

        if multipart:
            message = MIMEMultipart()
        else:
            message = Message()
            message.set_type('text/plain')
            message.set_charset(charset)

        try:
            message['Subject'] = subject.encode('ascii')
        except UnicodeError:
            message['Subject'] = Header(subject, charset)
        message['To'] = ', '.join(to)
        try:
            message['From'] = author.encode('ascii')
        except UnicodeError:
            message['From'] = Header(author, charset)
        message['Date'] = formatdate(localtime=True)

        # add a Precedence header so autoresponders ignore us
        message['Precedence'] = 'bulk'

        # Add a unique Roundup header to help filtering
        try:
            message['X-Roundup-Name'] = tracker_name.encode('ascii')
        except UnicodeError:
            message['X-Roundup-Name'] = Header(tracker_name, charset)

        # and another one to avoid loops
        message['X-Roundup-Loop'] = 'hello'
        # finally, an aid to debugging problems
        message['X-Roundup-Version'] = __version__

        message['MIME-Version'] = '1.0'

        return message

    def standard_message(self, to, subject, content, author=None):
        """Send a standard message.

        Arguments:
        - to: a list of addresses usable by rfc822.parseaddr().
        - subject: the subject as a string.
        - content: the body of the message as a string.
        - author: the sender as a (name, address) tuple

        All strings are assumed to be UTF-8 encoded.
        """
        message = self.get_standard_message(to, subject, author)
        message.set_payload(content)
        encode_quopri(message)
        self.smtp_send(to, str(message))

    def bounce_message(self, bounced_message, to, error,
                       subject='Failed issue tracker submission'):
        """Bounce a message, attaching the failed submission.

        Arguments:
        - bounced_message: an RFC822 Message object.
        - to: a list of addresses usable by rfc822.parseaddr(). Might be
          extended or overridden according to the config
          ERROR_MESSAGES_TO setting.
        - error: the reason of failure as a string.
        - subject: the subject as a string.

        """
        # see whether we should send to the dispatcher or not
        dispatcher_email = getattr(self.config, "DISPATCHER_EMAIL",
            getattr(self.config, "ADMIN_EMAIL"))
        error_messages_to = getattr(self.config, "ERROR_MESSAGES_TO", "user")
        if error_messages_to == "dispatcher":
            to = [dispatcher_email]
        elif error_messages_to == "both":
            to.append(dispatcher_email)

        message = self.get_standard_message(to, subject)

        # add the error text
        part = MIMEText(error)
        message.attach(part)

        # attach the original message to the returned message
        try:
            bounced_message.rewindbody()
        except IOError, message:
            body.write("*** couldn't include message body: %s ***"
                       % bounced_message)
        else:
            body.write(bounced_message.fp.read())
        part = MIMEText(bounced_message.fp.read())
        part['Content-Disposition'] = 'attachment'
        for header in bounced_message.headers:
            part.write(header)
        message.attach(part)

        # send
        try:
            self.smtp_send(to, str(message))
        except MessageSendError:
            # squash mail sending errors when bouncing mail
            # TODO this *could* be better, as we could notify admin of the
            # problem (even though the vast majority of bounce errors are
            # because of spam)
            pass

    def exception_message(self):
        '''Send a message to the admins with information about the latest
        traceback.
        '''
        subject = '%s: %s'%(self.config.TRACKER_NAME, sys.exc_info()[1])
        to = [self.config.ADMIN_EMAIL]
        content = '\n'.join(traceback.format_exception(*sys.exc_info()))
        self.standard_message(to, subject, content)

    def smtp_send(self, to, message):
        """Send a message over SMTP, using roundup's config.

        Arguments:
        - to: a list of addresses usable by rfc822.parseaddr().
        - message: a StringIO instance with a full message.
        """
        if self.debug:
            # don't send - just write to a file
            open(self.debug, 'a').write('FROM: %s\nTO: %s\n%s\n' %
                                        (self.config.ADMIN_EMAIL,
                                         ', '.join(to), message))
        else:
            # now try to send the message
            try:
                # send the message as admin so bounces are sent there
                # instead of to roundup
                smtp = SMTPConnection(self.config)
                smtp.sendmail(self.config.ADMIN_EMAIL, to, message)
            except socket.error, value:
                raise MessageSendError("Error: couldn't send email: "
                                       "mailhost %s"%value)
            except smtplib.SMTPException, msg:
                raise MessageSendError("Error: couldn't send email: %s"%msg)

class SMTPConnection(smtplib.SMTP):
    ''' Open an SMTP connection to the mailhost specified in the config
    '''
    def __init__(self, config):
        smtplib.SMTP.__init__(self, config.MAILHOST, port=config['MAIL_PORT'],
                              local_hostname=config['MAIL_LOCAL_HOSTNAME'])

        # start the TLS if requested
        if config["MAIL_TLS"]:
            self.ehlo()
            self.starttls(config["MAIL_TLS_KEYFILE"],
                config["MAIL_TLS_CERTFILE"])

        # ok, now do we also need to log in?
        mailuser = config["MAIL_USERNAME"]
        if mailuser:
            self.login(mailuser, config["MAIL_PASSWORD"])

# vim: set et sts=4 sw=4 :
