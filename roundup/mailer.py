"""Sending Roundup-specific mail over SMTP."""
# $Id: mailer.py,v 1.3 2003-10-04 11:21:47 jlgijsbers Exp $

import time, quopri, os, socket, smtplib, re

from cStringIO import StringIO
from MimeWriter import MimeWriter

from roundup.rfc2822 import encode_header

class MessageSendError(RuntimeError):
    pass

class Mailer:
    """Roundup-specific mail sending."""
    def __init__(self, config):
        self.config = config

        # set to indicate to roundup not to actually _send_ email
        # this var must contain a file to write the mail to
        self.debug = os.environ.get('SENDMAILDEBUG', '')

    def get_standard_message(self, to, subject, author=None):
        if not author:
            author = straddr((self.config.TRACKER_NAME,
                              self.config.ADMIN_EMAIL))
        message = StringIO()
        writer = MimeWriter(message)
        writer.addheader('Subject', encode_header(subject))
        writer.addheader('To', ', '.join(to))
        writer.addheader('From', author)
        writer.addheader('Date', time.strftime("%a, %d %b %Y %H:%M:%S +0000",
                                               time.gmtime()))

        # Add a unique Roundup header to help filtering
        writer.addheader('X-Roundup-Name', self.config.TRACKER_NAME)
        # and another one to avoid loops
        writer.addheader('X-Roundup-Loop', 'hello')

        writer.addheader('MIME-Version', '1.0')       
        
        return message, writer

    def standard_message(self, to, subject, content, author=None):
        """Send a standard message.

        Arguments:
        - to: a list of addresses usable by rfc822.parseaddr().
        - subject: the subject as a string.
        - content: the body of the message as a string.
        - author: the sender as a string, suitable for a 'From:' header.
        """
        message, writer = self.get_standard_message(to, subject, author)

        writer.addheader('Content-Transfer-Encoding', 'quoted-printable')
        body = writer.startbody('text/plain; charset=utf-8')
        content = StringIO(content)
        quopri.encode(content, body, 0)

        self.smtp_send(to, message)
       
    def bounce_message(self, bounced_message, to, error,
                       subject='Failed issue tracker submission'):
        """Bounce a message, attaching the failed submission.

        Arguments:
        - bounced_message: an RFC822 Message object.
        - to: a list of addresses usable by rfc822.parseaddr().
        - error: the reason of failure as a string.
        - subject: the subject as a string.
        
        """
        message, writer = self.get_standard_message(to, subject)

        part = writer.startmultipartbody('mixed')
        part = writer.nextpart()
        part.addheader('Content-Transfer-Encoding', 'quoted-printable')
        body = part.startbody('text/plain; charset=utf-8')
        body.write('\n'.join(error))

        # attach the original message to the returned message
        part = writer.nextpart()
        part.addheader('Content-Disposition', 'attachment')
        part.addheader('Content-Description', 'Message you sent')
        body = part.startbody('text/plain')

        for header in bounced_message.headers:
            body.write(header)
        body.write('\n')
        try:
            bounced_message.rewindbody()
        except IOError, message:
            body.write("*** couldn't include message body: %s ***"
                       % bounced_message)
        else:
            body.write(bounced_message.fp.read())

        writer.lastpart()

        self.smtp_send(to, message)
        
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
                                         ', '.join(to),
                                         message.getvalue()))
        else:
            # now try to send the message
            try:
                # send the message as admin so bounces are sent there
                # instead of to roundup
                smtp = SMTPConnection(self.config)
                smtp.sendmail(self.config.ADMIN_EMAIL, to,
                              message.getvalue())
            except socket.error, value:
                raise MessageSendError("Error: couldn't send email: "
                                       "mailhost %s"%value)
            except smtplib.SMTPException, msg:
                raise MessageSendError("Error: couldn't send email: %s"%msg)

class SMTPConnection(smtplib.SMTP):
    ''' Open an SMTP connection to the mailhost specified in the config
    '''
    def __init__(self, config):
        
        smtplib.SMTP.__init__(self, config.MAILHOST)

        # use TLS?
        use_tls = getattr(config, 'MAILHOST_TLS', 'no')
        if use_tls == 'yes':
            # do we have key files too?
            keyfile = getattr(config, 'MAILHOST_TLS_KEYFILE', '')
            if keyfile:
                certfile = getattr(config, 'MAILHOST_TLS_CERTFILE', '')
                if certfile:
                    args = (keyfile, certfile)
                else:
                    args = (keyfile, )
            else:
                args = ()
            # start the TLS
            self.starttls(*args)

        # ok, now do we also need to log in?
        mailuser = getattr(config, 'MAILUSER', None)
        if mailuser:
            self.login(*config.MAILUSER)

# use the 'email' module, either imported, or our copied version
try :
    from email.Utils import formataddr as straddr
except ImportError :
    # code taken from the email package 2.4.3
    def straddr(pair, specialsre = re.compile(r'[][\()<>@,:;".]'),
            escapesre = re.compile(r'[][\()"]')):
        name, address = pair
        if name:
            quotes = ''
            if specialsre.search(name):
                quotes = '"'
            name = escapesre.sub(r'\\\g<0>', name)
            return '%s%s%s <%s>' % (quotes, name, quotes, address)
        return address
