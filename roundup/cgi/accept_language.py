"""Parse the Accept-Language header as defined in RFC2616.

See http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.4
for details.  This module should follow the spec.
Author: Hernan M. Foffani (hfoffani@gmail.com)
Some use samples:

>>> parse("da, en-gb;q=0.8, en;q=0.7")
['da', 'en_gb', 'en']
>>> parse("en;q=0.2, fr;q=1")
['fr', 'en']
>>> parse("zn; q = 0.2 ,pt-br;q =1")
['pt_br', 'zn']
>>> parse("es-AR")
['es_AR']
>>> parse("es-es-cat")
['es_es_cat']
>>> parse("")
[]
>>> parse(None)
[]
>>> parse("   ")
[]
>>> parse("en,")
['en']
"""

import re
import heapq

# regexp for languange-range search
nqlre = "([A-Za-z]+[-[A-Za-z]+]*)$"
# regexp for languange-range search with quality value
qlre  = "([A-Za-z]+[-[A-Za-z]+]*);q=([\d\.]+)"
# both
lre   = re.compile(nqlre + "|" + qlre)

ascii = ''.join([chr(x) for x in xrange(256)])
whitespace = ' \t\n\r\v\f'

def parse(language_header):
    """parse(string_with_accept_header_content) -> languages list"""

    if language_header is None: return []

    # strip whitespaces.
    lh = language_header.translate(ascii, whitespace)

    # if nothing, return
    if lh == "": return []

    # split by commas and parse the quality values.
    pls = [lre.findall(x) for x in lh.split(',')]

    # drop uncomformant
    qls = [x[0] for x in pls if len(x) > 0]

    # use a heap queue to sort by quality values.
    # the value of each item is 1.0 complement.
    pq = []
    for l in qls:
        if l[0] != '':
            heapq.heappush(pq, (0.0, l[0]))
        else:
            heapq.heappush(pq, (1.0-float(l[2]), l[1]))

    # get the languages ordered by quality
    # and replace - by _
    return [x[1].replace('-','_') for x in pq]

if __name__ == "__main__":
    import doctest
    doctest.testmod()

# vim: set et sts=4 sw=4 :
