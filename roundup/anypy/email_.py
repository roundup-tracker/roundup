try:
    # Python 2.5+
    from email.parser import FeedParser
except ImportError:
    # Python 2.4
    try :
        from email.Parser import FeedParser
    except ImportError:
        from email.Parser import Parser
        class FeedParser:
            def __init__(self):
                self.content = []

            def feed(self, s):
                self.content.append(s)

            def close(self):
                p = Parser()
                return p.parsestr(''.join(self.content))
