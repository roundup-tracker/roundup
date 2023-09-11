"""Minimal html parser/normalizer for use in test_templating.

When testing markdown -> html conversion libraries, there are
gratuitous whitespace changes in generated output that break the
tests. Use this to try to normalize the generated HTML into something
that tries to preserve the semantic meaning allowing tests to stop
breaking.

This is not a complete parsing engine. It supports the Roundup issue
tracker unit tests so that no third party libraries are needed to run
the tests. If you find it useful enjoy.

Ideally this would be done by hijacking in some way
lxml.html.usedoctest to get a liberal parser that will ignore
whitespace. But that means the user has to install lxml to run the
tests. Similarly BeautifulSoup could be used to pretty print the html
but again, BeautifulSoup would need to be installed to run the
tests.

"""
try:
    from html.parser import HTMLParser
except ImportError:
    from HTMLParser import HTMLParser  # python2

try:
    from htmlentitydefs import name2codepoint
except ImportError:
    pass  # assume running under python3, name2codepoint predefined


class NormalizingHtmlParser(HTMLParser):
    """Handle start/end tags and normalize whitespace in data.
    Strip doctype, comments when passed in.

    Implements normalize method that takes input html and returns a
    normalized string leaving the instance ready for another call to
    normalize for another string.


    Note that using this rewrites all attributes parsed by HTMLParser
    into attr="value" form even though HTMLParser accepts other
    attribute specification forms.
    """

    debug = False  # set to true to enable more verbose output

    current_normalized_string = ""  # accumulate result string
    preserve_data = False           # if inside pre preserve whitespace

    def handle_starttag(self, tag, attrs):
        """put tag on new line with attributes.
           Note valid attributes according to HTMLParser:
              attrs='single_quote'
              attrs=noquote
              attrs="double_quote"
        """
        if self.debug: print("Start tag:", tag)

        self.current_normalized_string += "\n<%s" % tag

        for attr in attrs:
            if self.debug: print("     attr:", attr)
            self.current_normalized_string += ' %s="%s"' % attr

        self.current_normalized_string += ">\n"

        if tag == 'pre':
            self.preserve_data = True

    def handle_endtag(self, tag):
        if self.debug: print("End tag  :", tag)

        self.current_normalized_string += "\n</%s>" % tag

        if tag == 'pre':
            self.preserve_data = False

    def handle_data(self, data):
        if self.debug: print("Data     :", data)
        if not self.preserve_data:
            # normalize whitespace remove leading/trailing
            data = " ".join(data.strip().split())

        if data:
            self.current_normalized_string += "%s" % data

    def handle_comment(self, data):
        print("Comment  :", data)

    def handle_decl(self, data):
        print("Decl     :", data)

    def reset(self):
        """wrapper around reset with clearing of csef.current_normalized_string
           and reset of self.preserve_data
        """
        HTMLParser.reset(self)
        self.current_normalized_string = ""
        self.preserve_data = False

    def normalize(self, html):
        self.feed(html)
        result = self.current_normalized_string
        self.reset()
        return result


if __name__ == "__main__":
    parser = NormalizingHtmlParser()

    parser.feed('<div class="markup"><p> paragraph   text with whitespace\n  and more space  <pre><span class="f" data-attr="f">text more text</span></pre></div>')
    print("\n\ntest1", parser.current_normalized_string)

    parser.reset()

    parser.feed('''<div class="markup">
       <p> paragraph   text with whitespace\n  and more space  
       <pre><span class="f" data-attr="f">text \n more text</span></pre>
    </div>''')
    print("\n\ntest2", parser.current_normalized_string)
    parser.reset()
    print("\n\nnormalize", parser.normalize('''<div class="markup">
       <p> paragraph   text with whitespace\n  and more space  
       <pre><span class="f" data-attr="f">text \n more text &lt;</span></pre>
    </div>'''))
