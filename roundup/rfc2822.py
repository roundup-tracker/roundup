"""Some rfc822 functions taken from the new (python2.3) "email" module.
"""
__docformat__ = 'restructuredtext'

import re
from string import letters, digits
from binascii import b2a_base64, a2b_base64

ecre = re.compile(r'''
  =\?                   # literal =?
  (?P<charset>[^?]*?)   # non-greedy up to the next ? is the charset
  \?                    # literal ?
  (?P<encoding>[qb])    # either a "q" or a "b", case insensitive
  \?                    # literal ?
  (?P<encoded>.*?)      # non-greedy up to the next ?= is the encoded string
  \?=                   # literal ?=
  ''', re.VERBOSE | re.IGNORECASE)

hqre = re.compile(r'^[A-z0-9!"#$%%&\'()*+,-./:;<=>?@\[\]^_`{|}~ ]+$')

CRLF = '\r\n'

def base64_decode(s, convert_eols=None):
    """Decode a raw base64 string.

    If convert_eols is set to a string value, all canonical email linefeeds,
    e.g. "\\r\\n", in the decoded text will be converted to the value of
    convert_eols.  os.linesep is a good choice for convert_eols if you are
    decoding a text attachment.

    This function does not parse a full MIME header value encoded with
    base64 (like =?iso-8895-1?b?bmloISBuaWgh?=) -- please use the high
    level email.Header class for that functionality.

    Taken from 'email' module
    """
    if not s:
        return s
    
    dec = a2b_base64(s)
    if convert_eols:
        return dec.replace(CRLF, convert_eols)
    return dec

def unquote_match(match):
    """Turn a match in the form ``=AB`` to the ASCII character with value
    0xab.

    Taken from 'email' module
    """
    s = match.group(0)
    return chr(int(s[1:3], 16))

def qp_decode(s):
    """Decode a string encoded with RFC 2045 MIME header 'Q' encoding.

    This function does not parse a full MIME header value encoded with
    quoted-printable (like =?iso-8895-1?q?Hello_World?=) -- please use
    the high level email.Header class for that functionality.

    Taken from 'email' module
    """
    s = s.replace('_', ' ')
    return re.sub(r'=\w{2}', unquote_match, s)

def _decode_header(header):
    """Decode a message header value without converting charset.

    Returns a list of (decoded_string, charset) pairs containing each of the
    decoded parts of the header.  Charset is None for non-encoded parts of the
    header, otherwise a lower-case string containing the name of the character
    set specified in the encoded string.

    Taken from 'email' module
    """
    # If no encoding, just return the header
    header = str(header)
    if not ecre.search(header):
        return [(header, None)]

    decoded = []
    dec = ''
    for line in header.splitlines():
        # This line might not have an encoding in it
        if not ecre.search(line):
            decoded.append((line, None))
            continue

        parts = ecre.split(line)
        while parts:
            unenc = parts.pop(0)
            if unenc:
                if unenc.strip():
                    decoded.append((unenc, None))
            if parts:
                charset, encoding = [s.lower() for s in parts[0:2]]
                encoded = parts[2]
                dec = ''
                if encoding == 'q':
                    dec = qp_decode(encoded)
                elif encoding == 'b':
                    dec = base64_decode(encoded)
                else:
                    dec = encoded

                if decoded and decoded[-1][1] == charset:
                    decoded[-1] = (decoded[-1][0] + dec, decoded[-1][1])
                else:
                    decoded.append((dec, charset))
            del parts[0:3]
    return decoded

def decode_header(hdr):
    """ Decodes rfc2822 encoded header and return utf-8 encoded string
    """
    if not hdr:
        return None
    outs = u""
    for section in _decode_header(hdr):
        charset = unaliasCharset(section[1])
        outs += unicode(section[0], charset or 'iso-8859-1', 'replace')
    return outs.encode('utf-8')

def encode_header(header, charset='utf-8'):
    """ Will encode in quoted-printable encoding only if header 
    contains non latin characters
    """

    # Return empty headers unchanged
    if not header:
        return header

    # return plain header if it is not contains non-ascii characters
    if hqre.match(header):
        return header
    
    quoted = ''
    #max_encoded = 76 - len(charset) - 7
    for c in header:
        # Space may be represented as _ instead of =20 for readability
        if c == ' ':
            quoted += '_'
        # These characters can be included verbatim
        elif hqre.match(c) and c not in '_=?':
            quoted += c
        # Otherwise, replace with hex value like =E2
        else:
            quoted += "=%02X" % ord(c)
            plain = 0

    return '=?%s?q?%s?=' % (charset, quoted)

def unaliasCharset(charset):
    if charset:
        return charset.lower().replace("windows-", 'cp')
        #return charset_table.get(charset.lower(), charset)
    return None

def test():
    print encode_header("Contrary, Mary")
    #print unaliasCharset('Windows-1251')

if __name__ == '__main__':
    test()

# vim: et
