import htmllib, formatter

class Require:
    ''' Encapsulates a parsed <require attributes>...[<else>...]</require>
    '''
    def __init__(self, attributes):
        self.attributes = attributes
        self.current = self.ok = []
        self.fail = []
    def __len__(self):
        return len(self.current)
    def __getitem__(self, n):
        return self.current[n]
    def __setitem__(self, n, data):
        self.current[n] = data
    def append(self, data):
        self.current.append(data)
    def elseMode(self):
        self.current = self.fail

class Display:
    ''' Encapsulates a parsed <display attributes>
    '''
    def __init__(self, attributes):
        self.attributes = attributes

class Property:
    ''' Encapsulates a parsed <property attributes>
    '''
    def __init__(self, attributes):
        self.attributes = attributes

class RoundupTemplateParser(htmllib.HTMLParser):
    ''' Parse Roundup's HTML template structure into a list of components:

        'string': this is just plain data to be displayed
        Display : instances indicate that display functions are to be called
        Require : if/else style check using the conditions in the attributes,
                  displaying the "ok" list of components or "fail" list

    '''
    def __init__(self):
        htmllib.HTMLParser.__init__(self, formatter.NullFormatter())
        self.current = self.structure = []
        self.stack = []

    def handle_data(self, data):
        self.append_data(data)

    def append_data(self, data):
        if self.current and isinstance(self.current[-1], type('')):
            self.current[-1] = self.current[-1] + data
        else:
            self.current.append(data)

    def unknown_starttag(self, tag, attributes):
        s = ''
        s = s + '<%s' % tag
        for name, value in attributes:
            s = s + ' %s="%s"' % (name, value)
        s = s + '>'
        self.append_data(s)

    def handle_starttag(self, tag, method, attributes):
        if tag in ('require', 'else', 'display', 'property'):
            method(attributes)
        else:
            self.unknown_starttag(tag, attributes)

    def unknown_endtag(self, tag):
        if tag == 'require':
            self.current = self.stack.pop()
        else:
            self.append_data('</%s>'%tag)

    def handle_endtag(self, tag, method):
        self.unknown_endtag(tag)

    def close(self):
        htmllib.HTMLParser.close(self)

    def do_display(self, attributes):
        self.current.append(Display(attributes))

    def do_property(self, attributes):
        self.current.append(Property(attributes))

    def do_require(self, attributes):
        r = Require(attributes)
        self.current.append(r)
        self.stack.append(self.current)
        self.current = r

    def do_else(self, attributes):
        self.current.elseMode()

def display(structure, indent=''):
    ''' Pretty-print the parsed structure for debugging
    '''
    for entry in structure:
        if isinstance(entry, type('')):
            print "%s%r"%(indent, entry[:50])
        elif isinstance(entry, Require):
            print '%sTEST: %r'%(indent, entry.attributes)
            print '%sOK...'%indent
            display(entry.ok, indent+' ')
            if entry.fail:
                print '%sFAIL...'%indent
                display(entry.fail, indent+' ')
        elif isinstance(entry, Display):
            print '%sDISPLAY: %r'%(indent, entry.attributes)

if __name__ == '__main__':
    import sys
    parser = RoundupTemplateParser()
    parser.feed(open(sys.argv[1], 'r').read())
    display(parser.structure)

#
# $Log: not supported by cvs2svn $
#
# vim: set filetype=python ts=4 sw=4 et si

