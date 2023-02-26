#
# Copyright (c) 2001 Richard Jones, richard@bofh.asn.au.
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#

"""This module provides the tokeniser used by roundup-admin.
"""
__docformat__ = 'restructuredtext'


def token_split(s, whitespace=' \r\n\t', quotes='\'"',
                escaped={'r': '\r', 'n': '\n', 't': '\t'}):
    r'''Split the string up into tokens. An occurence of a ``'`` or ``"`` in
    the input will cause the splitter to ignore whitespace until a matching
    quote char is found. Embedded non-matching quote chars are also skipped.

    Whitespace and quoting characters may be escaped using a backslash.
    ``\r``, ``\n`` and ``\t`` are converted to carriage-return, newline and
    tab.  All other backslashed characters are left as-is.

    Valid examples::

           hello world      (2 tokens: hello, world)
           "hello world"    (1 token: hello world)
           "Roch'e" Compaan (2 tokens: Roch'e Compaan)
           Roch\'e Compaan  (2 tokens: Roch'e Compaan)
           address="1 2 3"  (1 token: address=1 2 3)
           \\               (1 token: \)
           \n               (1 token: a newline)
           \o               (1 token: \o)

    Invalid examples::

           "hello world     (no matching quote)
           Roch'e Compaan   (no matching quote)
    '''
    l = []
    pos = 0
    NEWTOKEN = 'newtoken'
    TOKEN = 'token'
    QUOTE = 'quote'
    ESCAPE = 'escape'
    quotechar = ''
    state = NEWTOKEN
    oldstate = ''    # one-level state stack ;)
    length = len(s)
    token = ''
    while 1:
        # end of string, finish off the current token
        if pos == length:
            if state == QUOTE: raise ValueError
            elif state == TOKEN: l.append(token)
            break
        c = s[pos]
        if state == NEWTOKEN:
            # looking for a new token
            if c in quotes:
                # quoted token
                state = QUOTE
                quotechar = c
                pos = pos + 1
                continue
            elif c in whitespace:
                # skip whitespace
                pos = pos + 1
                continue
            elif c == '\\':
                pos = pos + 1
                oldstate = TOKEN
                state = ESCAPE
                continue
            # otherwise we have a token
            state = TOKEN
        elif state == TOKEN:
            if c in whitespace:
                # have a token, and have just found a whitespace terminator
                l.append(token)
                pos = pos + 1
                state = NEWTOKEN
                token = ''
                continue
            elif c in quotes:
                # have a token, just found embedded quotes
                state = QUOTE
                quotechar = c
                pos = pos + 1
                continue
            elif c == '\\':
                pos = pos + 1
                oldstate = state
                state = ESCAPE
                continue
        elif state == QUOTE and c == quotechar:
            # in a quoted token and found a matching quote char
            pos = pos + 1
            # now we're looking for whitespace
            state = TOKEN
            continue
        elif state == ESCAPE:
            # escaped-char conversions (t, r, n)
            # TODO: octal, hexdigit
            state = oldstate
            if c in escaped:
                c = escaped[c]
        # just add this char to the token and move along
        token = token + c
        pos = pos + 1
    return l

# vim: set filetype=python ts=4 sw=4 et si
