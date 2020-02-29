
from __future__ import print_function
from roundup.anypy.strings import u2s, uchr

import sys
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
                    soup = BeautifulSoup(html)

                    # kill all script and style elements
                    for script in soup(["script", "style"]):
                        script.extract()

                    return u2s(soup.get_text('\n', strip=True))

                self.html2text = html2text
            else:
                raise ImportError
        except ImportError:
            # use the fallback below if beautiful soup is not installed.
            try:
                # Python 3+.
                from html.parser import HTMLParser
                from html.entities import name2codepoint
            except ImportError:
                # Python 2.
                from HTMLParser import HTMLParser
                from htmlentitydefs import name2codepoint

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

                def handle_starttag(self, tag, attrs):
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
                        self.text = self.text + ' '

            def html2text(html):
                if _pyver == 3:
                    parser = DumbHTMLParser(convert_charrefs=True)
                else:
                    parser = DumbHTMLParser()
                parser.feed(html)
                parser.close()
                return parser.text

            self.html2text = html2text


if "__main__" == __name__:
    html = '''
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
<h2><a class="toc-backref" href="#id5">Prerequisites</a></h2>
<p>Roundup requires Python 2.5 or newer (but not Python 3) with a functioning
anydbm module. Download the latest version from <a class="reference external" href="http://www.python.org/">http://www.python.org/</a>.
It is highly recommended that users install the latest patch version
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
'''

    html2text = dehtml("dehtml").html2text
    if html2text:
        print(html2text(html))

    try:
        # trap error seen if N_TOKENS not defined when run.
        html2text = dehtml("beautifulsoup").html2text
        if html2text:
            print(html2text(html))
    except NameError as e:
        print("captured error %s" % e)

    html2text = dehtml("none").html2text
    if html2text:
        print("FAIL: Error, dehtml(none) is returning a function")
    else:
        print("PASS: dehtml(none) is returning None")
