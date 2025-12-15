
from __future__ import print_function

import sys

from roundup.anypy.strings import u2s, uchr

# ruff PLC0415 ignore imports not at top of file
# ruff RET505 ignore else  after return
# ruff: noqa: PLC0415 RET505

_pyver = sys.version_info[0]


class dehtml:
    def __init__(self, converter):
        if converter == "none":
            self.html2text = None
            return

        try:
            if converter == "beautifulsoup":
                # Not as well tested as dehtml.
                from bs4 import BeautifulSoup

                def html2text(html):
                    soup = BeautifulSoup(html, "html.parser")

                    # kill all script and style elements
                    for script in soup(["script", "style"]):
                        script.extract()

                    return u2s(soup.get_text("\n", strip=True))

                self.html2text = html2text
            elif converter == "justhtml":
                from justhtml import stream

                def html2text(html):
                    # The below does not work.
                    # Using stream parser since I couldn't seem to strip
                    # 'script' and 'style' blocks. But stream doesn't
                    # have error reporting or stripping of text nodes
                    # and dropping empty nodes. Also I would like to try
                    # its GFM markdown output too even though it keeps
                    # tables as html and doesn't completely covert as
                    # this would work well for those supporting markdown.
                    #
                    #  ctx used for for testing since I have a truncated
                    #  test doc. It eliminates error from missing DOCTYPE
                    #  and head.
                    #
                    #from justhtml import JustHTML
                    # from justhtml.context import FragmentContext
                    #
                    #ctx = FragmentContext('html')
                    #justhtml = JustHTML(html,collect_errors=True,
                    #                    fragment_context=ctx)
                    # I still have the text output inside style/script tags.
                    # with :not(style, script). I do get text contents
                    # with query("style, script").
                    #
                    #return u2s("\n".join(
                    #     [elem.to_text(separator="\n", strip=True)
                    #        for elem in justhtml.query(":not(style, script)")])
                    #          )

                    # define inline elements so I can accumulate all unbroken
                    # text in a single line with embedded inline elements.
                    # 'br' is inline but should be treated it as a line break
                    # and element before/after should not be accumulated
                    # together.
                    inline_elements = (
                        "a",
                        "address",
                        "b",
                        "cite",
                        "code",
                        "em",
                        "i",
                        "img",
                        "mark",
                        "q",
                        "s",
                        "small",
                        "span",
                        "strong",
                        "sub",
                        "sup",
                        "time")

                    # each line is appended and joined at the end
                    text = []
                    # the accumulator for all text in inline elements
                    text_accumulator = ""
                    # if set skip all lines till matching end tag found
                    # used to skip script/style blocks
                    skip_till_endtag = None
                    # used to force text_accumulator into text with added
                    # newline so we have a blank line between paragraphs.
                    _need_parabreak = False

                    for event, data in stream(html):
                        if event == "end" and skip_till_endtag == data:
                            skip_till_endtag = None
                            continue
                        if skip_till_endtag:
                            continue
                        if (event == "start" and
                              data[0] in ('script', 'style')):
                            skip_till_endtag = data[0]
                            continue
                        if (event == "start" and
                              text_accumulator and
                              data[0] not in inline_elements):
                            # add accumulator to "text"
                            text.append(text_accumulator)
                            text_accumulator = ""
                            _need_parabreak = False
                        elif event == "text":
                            if not data.isspace():
                                text_accumulator = text_accumulator + data
                                _need_parabreak = True
                        elif (_need_parabreak and
                              event == "start" and
                              data[0] == "p"):
                            text.append(text_accumulator + "\n")
                            text_accumulator = ""
                            _need_parabreak = False

                    # save anything left in the accumulator at end of document
                    if text_accumulator:
                        # add newline to match dehtml and beautifulsoup
                        text.append(text_accumulator + "\n")
                    return u2s("\n".join(text))

                self.html2text = html2text
            else:
                raise ImportError
        except ImportError:
            # use the fallback below if beautiful soup is not installed.
            try:
                # Python 3+.
                from html.entities import name2codepoint
                from html.parser import HTMLParser
            except ImportError:
                # Python 2.
                from htmlentitydefs import name2codepoint
                from HTMLParser import HTMLParser

            class DumbHTMLParser(HTMLParser):
                # class attribute
                text = ""

                # internal state variable
                _skip_data = False
                _last_empty = False

                def handle_data(self, data):
                    if self._skip_data:  # skip data in script or style block
                        return

                    if (data.strip() == ""):
                        # reduce multiple blank lines to 1
                        if (self._last_empty):
                            return
                        else:
                            self._last_empty = True
                    else:
                        self._last_empty = False

                    self.text = self.text + data

                def handle_starttag(self, tag, attrs):  # noqa: ARG002
                    if (tag == "p"):
                        self.text = self.text + "\n"
                    if (tag in ("style", "script")):
                        self._skip_data = True

                def handle_endtag(self, tag):
                    if (tag in ("style", "script")):
                        self._skip_data = False

                def handle_entityref(self, name):
                    if self._skip_data:
                        return
                    c = uchr(name2codepoint[name])
                    try:
                        self.text = self.text + c
                    except UnicodeEncodeError:
                        # print a space as a placeholder
                        self.text = self.text + " "

            def html2text(html):
                parser = DumbHTMLParser(
                    convert_charrefs=True) if _pyver == 3 else DumbHTMLParser()
                parser.feed(html)
                parser.close()
                return parser.text

            self.html2text = html2text


if __name__ == "__main__":
    # ruff: noqa: B011 S101

    try:
        assert False
    except AssertionError:
        pass
    else:
        print("Error, assertions turned off. Test fails")
        sys.exit(1)

    html = """
<body>
<script>
this must not be in output
</script>
<style>
p {display:block}
</style>
    <div class="header"><h1>Roundup</h1>
        <div id="searchbox" style="display: none">
          <form class="search" action="../search.html" method="get">
            <input type="text" name="q" size="18" />
            <input type="submit" value="Search" />
            <input type="hidden" name="check_keywords" value="yes" />
            <input type="hidden" name="area" value="default" />
          </form>
        </div>
        <script type="text/javascript">$('#searchbox').show(0);</script>
    </div>
       <ul class="current">
<li class="toctree-l1"><a class="reference internal" href="../index.html">Home</a></li>
<li class="toctree-l1"><a class="reference external" href="http://pypi.python.org/pypi/roundup">Download</a></li>
<li class="toctree-l1 current"><a class="reference internal" href="../docs.html">Docs</a><ul class="current">
<li class="toctree-l2"><a class="reference internal" href="features.html">Roundup Features</a></li>
<li class="toctree-l2 current"><a class="current reference internal" href="">Installing Roundup</a></li>
<li class="toctree-l2"><a class="reference internal" href="upgrading.html">Upgrading to newer versions of Roundup</a></li>
<li class="toctree-l2"><a class="reference internal" href="FAQ.html">Roundup FAQ</a></li>
<li class="toctree-l2"><a class="reference internal" href="user_guide.html">User Guide</a></li>
<li class="toctree-l2"><a class="reference internal" href="customizing.html">Customising Roundup</a></li>
<li class="toctree-l2"><a class="reference internal" href="admin_guide.html">Administration Guide</a></li>
</ul>
<div class="section" id="prerequisites">
<H2><a class="toc-backref" href="#id5">Prerequisites</a></H2>
<p>Roundup requires Python 2.5 or newer (but not Python 3) with a functioning
anydbm module. Download the latest version from <a class="reference external" href="http://www.python.org/">http://www.python.org/</a>.
It is highly recommended that users install the <span>latest patch version</span>
of python as these contain many fixes to serious bugs.</p>
<p>Some variants of Linux will need an additional &#8220;python dev&#8221; package
installed for Roundup installation to work. Debian and derivatives, are
known to require this.</p>
<p>If you&#8217;re on windows, you will either need to be using the ActiveState python
distribution (at <a class="reference external" href="http://www.activestate.com/Products/ActivePython/">http://www.activestate.com/Products/ActivePython/</a>), or you&#8217;ll
have to install the win32all package separately (get it from
<a class="reference external" href="http://starship.python.net/crew/mhammond/win32/">http://starship.python.net/crew/mhammond/win32/</a>).</p>
<script>
  &lt; HELP &GT;
</script>
</div>
</body>
"""

    if len(sys.argv) > 1:
        with open(sys.argv[1]) as h:
            html = h.read()

    print("==== beautifulsoup")
    try:
        # trap error seen if N_TOKENS not defined when run.
        html2text = dehtml("beautifulsoup").html2text
        if html2text:
            text = html2text(html)
            assert ('HELP' not in text)
            assert ('display:block' not in text)
            print(text)
    except NameError as e:
        print("captured error %s" % e)

    print("==== justhtml")
    try:
        html2text = dehtml("justhtml").html2text
        if html2text:
            text = html2text(html)
            assert ('HELP' not in text)
            assert ('display:block' not in text)
            print(text)
    except NameError as e:
        print("captured error %s" % e)

    print("==== dehtml")
    html2text = dehtml("dehtml").html2text
    if html2text:
        text = html2text(html)
        assert ('HELP' not in text)
        assert ('display:block' not in text)
        print(text)

    print("==== disabled html -> text conversion")
    html2text = dehtml("none").html2text
    if html2text:
        print("FAIL: Error, dehtml(none) is returning a function")
    else:
        print("PASS: dehtml(none) is returning None")
