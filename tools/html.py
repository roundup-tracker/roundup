import cStringIO, cgi, sys, urllib
import dps.utils
try:
    from restructuredtext import Parser
except ImportError:
    from dps.parsers.restructuredtext import Parser

# TODO: enforce model?

class DumbHTMLFormatter:
    def __init__(self):
        self.out = cStringIO.StringIO()
        self.w = self.out.write
        self.section = 0
        self.closers = []

    def format(self, node):
        '''Format a node
        '''
        for entry in node:
            self.formatOneTag(entry)

    def formatOneTag(self, tag):
        if tag.tagname == '#text':
            meth = self.format__text
        else:
            meth = getattr(self, 'format_'+tag.tagname)
        meth(tag)

    #
    # Root Element
    #
    # ((title, subtitle?)?, docinfo?, %structure.model;)
    #
    def format_document(self, document):
        ''' ((title, subtitle?)?, docinfo?, %structure.model;)

            
        '''
        self.document = document
        self.w('<html><head>\n')

        n = 0
        
        # See if there's a title
        if document[n].tagname == 'title':
            title = cgi.escape(document[n][0][0].data)
            self.w('<title>%s</title>\n'%title)
            n += 1
            if document[n].tagname == 'subtitle':
                title = cgi.escape(document[n][0][0].data)
                self.w('<h1>%s</h1>'%title)
                self.section += 1
                n += 1

        # Now see if there's biblio information

        # see if there's a field_list at the start of the document
        if document[n].tagname == 'docinfo':
            self.format_docinfo(document[n])
            n += 1

        self.w('</head>\n<body>')

        # now for the body
        l = list(document)
        for entry in l[n:]:
            self.formatOneTag(entry)
        self.w('</body>\n</html>')
        return self.out.getvalue()

    #
    # Title Elements
    #
    def format_title(self, node):
        self.w('<h%d>'%self.section)
        if node.children: self.format(node)
        self.w('</h%d>\n'%self.section)

    def format_subtitle(self, node):
        raise NotImplementedError, node

    # 
    # Bibliographic Elements
    #
    def format_docinfo(self, node):
        ''' (((%bibliographic.elements;)+, abstract?) | abstract)

            bibliographic.elements:
             author | authors | organization | contact | version | revision
             | status | date | copyright
        '''
        if node.children: self.format(node)

    def format_abstract(self, node):
        content = urllib.quote(node[0].data)
        self.w('<meta name="description" content="%s">\n'%content)

    def format_author(self, node):
        content = urllib.quote(node[0].data)
        self.w('<meta name="author" content="%s">\n'%content)

    def format_authors(self, node):
        ''' ((author, organization?, contact?)+)
        '''
        self.w('<meta name="author" content="')
        print node
        self.w('">\n'%content)

    def format_organization(self, node):
        content = urllib.quote(node[0].data)
        self.w('<meta name="organization" content="%s">\n'%content)

# TODO: not in DTD
#    def format_keywords(self, node):
#        content = urllib.quote(node[0].data)
#        self.w('<meta name="keywords" content="%s">\n'%content)

    def format_contact(self, node):
        addr = urllib.quote(node[0].data)
        self.w('<link rev="made" href="mailto:%s>\n'%addr)

    def format_version(self, node):
        addr = urllib.quote(node[0].data)
        self.w('<meta name="version" content="%s">\n'%content)

    def format_revision(self, node):
        addr = urllib.quote(node[0].data)
        self.w('<meta name="revision" content="%s">\n'%content)

    def format_status(self, node):
        addr = urllib.quote(node[0].data)
        self.w('<meta name="status" content="%s">\n'%content)

    def format_date(self, node):
        addr = urllib.quote(node[0].data)
        self.w('<meta name="date" content="%s">\n'%content)

    def format_copyright(self, node):
        addr = urllib.quote(node[0].data)
        self.w('<meta name="copyright" content="%s">\n'%content)

    #
    # Structural Elements
    #
    # section
    #
    # structure.model:
    # ( ((%body.elements; | transition)+, (%structural.elements;)*)
    # | (%structural.elements;)+ )
    #
    def format_section(self, node):
        self.w('<a name="%s"></a>'%urllib.quote(node.attributes['name']))
        self.section += 1
        if node.children: self.format(node)
        self.section -= 1

    def format_transition(self, node):
        self.w('<hr>')

    #
    # Body Elements
    #
    # paragraph | literal_block | block_quote | doctest_block| table
    # | figure | image | footnote 
    # | bullet_list | enumerated_list | definition_list | field_list
    # | option_list
    # | note | tip | hint | warning | error | caution | danger | important
    # | target | substitution_definition | comment | system_message
    #
    #
    def format_paragraph(self, node):
        ''' %text.model;
        '''
            # TODO: there are situations where the <p> </p> are unnecessary
        self.w('<p>')
        if node.children: self.format(node)
        self.w('</p>\n')

    # Simple lists
    def format_bullet_list(self, node):
        ''' (list_item+)
            bullet    CDATA
        '''
        # TODO: handle attribute
        self.w('<ul>\n')
        if node.children: self.format(node)
        self.w('</ul>\n')

    def format_enumerated_list(self, node):
        ''' (list_item+)
            enumtype  (arabic | loweralpha | upperalpha | lowerroman |
                       upperroman)
            prefix    CDATA
            suffix    CDATA
            start     CDATA
        '''
        # TODO: handle attributes
        self.w('<ol>\n')
        if node.children: self.format(node)
        self.w('</ol>\n')

    def format_list_item(self, node):
        ''' (%body.elements;)+
        '''
        self.w('<li>')
        if node.children: self.format(node)
        self.w('</li>\n')

    # Definition List
    def format_definition_list(self, node):
        ''' (definition_list_item+)
        '''
        self.w('<dl>\n')
        if node.children: self.format(node)
        self.w('</dl>\n')

    def format_definition_list_item(self, node):
        '''  (term, classifier?, definition)
        '''
        self.w('<dt>')
        if node.children: self.format(node)

    def format_term(self, node):
        ''' %text.model;
        '''
        self.w('<span class="term">')
        if node.children:self.format(node)
        self.w('</span>')

    def format_classifier(self, node):
        ''' %text.model;
        '''
        # TODO: handle the classifier better
        self.w('<span class="classifier">')
        if node.children: self.format(node)
        self.w('</span>')

    def format_definition(self, node):
        ''' (%body.elements;)+
        '''
        self.w('</dt>\n<dd>')
        # TODO: this is way suboptimal!
        first = 1
        for child in node.children:
            if child.tagname == 'paragraph' and first:
                # just format the contents of the para
                self.format(child)
            else:
                # format the whole tag
                self.formatOneTag(child)
            first = 0
        self.w('</dd>\n')

    # Field List
    def format_field_list(self, node):
        ''' (field+)
        '''
        self.w('<dl>')
        if node.children: self.format(node)
        self.w('</dl>')

    def format_field(self, node):
        ''' (field_name, field_argument*, field_body)
        '''
        self.w('<dt>')
        if node.children: self.format(node)

    def format_field_name(self, node):
        ''' (#PCDATA)
        '''
        self.w('<span class="field_name">')
        if node.children:self.format(node)
        self.w('</span>')

    def format_field_argument(self, node):
        ''' (#PCDATA)
        '''
        self.w('<span class="field_argument">')
        if node.children: self.format(node)
        self.w('</span>')

    def format_field_body(self, node):
        ''' (%body.elements;)+
        '''
        self.w('</dt>\n<dd class="field_body">')
        if node.children: self.format(node)
        self.w('</dd>\n')

    # Option List
    def format_option_list(self, node):
        ''' (option_list_item+)
        '''
        self.w('<table border=0 cellspacing=0 cellpadding=2><tr><th align="left" class="option_header">Option</th>\n')
        self.w('<th align="left" class="option_header">Description</th></tr>\n')
        if node.children: self.format(node)
        self.w('</table>\n')

    def format_option_list_item(self, node):
        ''' (option+, description)
        '''
        self.w('<tr>')
        if node.children: self.format(node)
        self.w('</tr>\n')

    def format_option(self, node):
        ''' ((short_option | long_option | vms_option), option_argument?)
        '''
        self.w('<td align="left" valign="top" class="option">')
        if node.children: self.format(node)
        self.w('</td>')

    def format_short_option(self, node):
        ''' (#PCDATA)
        '''
        for option in node.children:
            self.w('-%s'%cgi.escape(option.data))

    def format_long_option(self, node):
        ''' (#PCDATA)
        '''
        for option in node.children:
            self.w('--%s'%cgi.escape(option.data))

    def format_vms_option(self, node):
        ''' (#PCDATA)
        '''
        for option in node.children:
            self.w('/%s'%cgi.escape(option.data))

    def format_option_argument(self, node):
        ''' (#PCDATA)
        '''
        for option in node.children:
            self.w('=%s'%cgi.escape(option.data))

    def format_description(self, node):
        ''' (%body.elements;)+
        '''
        self.w('<td align="left" valign="top" class="option_description">')
        if node.children: self.format(node)
        self.w('</td>\n')

    # Literal Block
    def format_literal_block(self, node):
        self.w('<pre>')
        if node.children: self.format(node)
        self.w('</pre>\n')

    # Block Quote
    def format_block_quote(self, node):
        # TODO: I believe this needs to be CSS'ified - blockquote is deprecated
        self.w('<blockquote>')
        if node.children: self.format(node)
        self.w('</blockquote>\n')

    # Doctest Block
    def format_doctest_block(self, node):
        self.w('<pre>')
        if node.children: self.format(node)
        self.w('</pre>\n')

    # Note, tip, hint, warning, error, caution, danger, important
    def format_note(self, node):
        ''' (%body.elements;)+
        '''
        self.w('<span class="note">')
        if node.children: self.format(node)
        self.w('</span>')
 
    def format_tip(self, node):
        ''' (%body.elements;)+
        '''
        self.w('<span class="tip">')
        if node.children: self.format(node)
        self.w('</span>')

    def format_hint(self, node):
        ''' (%body.elements;)+
        '''
        self.w('<span class="hint">')
        if node.children: self.format(node)
        self.w('</span>')

    def format_warning(self, node):
        ''' (%body.elements;)+
        '''
        self.w('<span class="warning">')
        if node.children: self.format(node)
        self.w('</span>')

    def format_error(self, node):
        ''' (%body.elements;)+
        '''
        self.w('<span class="error">')
        if node.children: self.format(node)
        self.w('</span>')

    def format_caution(self, node):
        ''' (%body.elements;)+
        '''
        self.w('<span class="caution">')
        if node.children: self.format(node)
        self.w('</span>')

    def format_danger(self, node):
        ''' (%body.elements;)+
        '''
        self.w('<span class="danger">')
        if node.children: self.format(node)
        self.w('</span>')

    def format_important(self, node):
        ''' (%body.elements;)+
        '''
        self.w('<span class="important">')
        if node.children: self.format(node)
        self.w('</span>')

    # Footnote
    def format_footnote(self, node):
        ''' (label?, (%body.elements;)+)
            %auto.att;
        '''
        raise NotImplementedError, node

    def format_label(self, node):
        ''' (#PCDATA)
        '''
        for label in node.children:
            self.w(cgi.escape(label.data))

    # Target
    def format_target(self, node):
        ''' (%text.model;)
            %reference.atts;
             %anonymous.att;
        '''
        pass

    # Substitution Definition
    def format_substitution_definition(self, node):
        ''' (%text.model;)
        '''
        raise NotImplementedError, node

    # Comment
    def format_comment(self, node):
        ''' (#PCDATA)
            %fixedspace.att;
        '''
        # TODO: handle attrs
        self.w('<!--')
        for data in node.children:
            self.w(cgi.escape(data.data))
        self.w('-->')

    # Figure
    def format_figure(self, node):
        ''' (image, ((caption, legend?) | legend)
        '''
        raise NotImplementedError, node

    def format_image(self, node):
        ''' EMPTY
            uri       CDATA     #REQUIRED
            alt       CDATA     #IMPLIED
            height    NMTOKEN   #IMPLIED
            width     NMTOKEN   #IMPLIED
            scale     NMTOKEN   #IMPLIED
        '''
	attrs = node.attributes
	l = ['src="%(uri)s"'%attrs]
	if attrs.has_key('alt'):
	    l.append('alt="%(alt)s"'%attrs)
	if attrs.has_key('alt'):
	    l.append('alt="%(alt)s"'%attrs)
	if attrs.has_key('height'):
	    l.append('height="%(height)s"'%attrs)
	if attrs.has_key('width'):
	    l.append('width="%(width)s"'%attrs)
	# TODO: scale
        self.w('<img %s>'%(' '.join(l)))

    def format_caption(self, node):
        ''' %text.model;
        '''
        raise NotImplementedError, node

    def format_legend(self, node):
        ''' (%body.elements;)+
        '''
        raise NotImplementedError, node

    # System Message
    def format_system_message(self, node):
        ''' (%body.elements;)+
            level     NMTOKEN   #IMPLIED
            type      CDATA     #IMPLIED
        '''
        self.w('<span class="system_message-%s">'%node.attributes['type'])
        if node.children: self.format(node)
        self.w('</span>')

    #
    # Tables:
    #  NOT IN DOM YET
    #
    def format_table(self, node):
        '''
            +------------------------+------------+----------+----------+
            | Header row, column 1   | Header 2   | Header 3 | Header 4 |
            | (header rows optional) |            |          |          |
            +========================+============+==========+==========+
            | body row 1, column 1   | column 2   | column 3 | column 4 |
            +------------------------+------------+----------+----------+
            | body row 2             | Cells may span columns.          |
            +------------------------+------------+---------------------+
            | body row 3             | Cells may  | - Table cells       |
            +------------------------+ span rows. | - contain           |
            | body row 4             |            | - body elements.    |
            +------------------------+------------+---------------------+
        '''
        self.w('<table border=1>\n')
        if node.children: self.format(node)
        self.w('</table>\n')

    def format_tgroup(self, node):
        # we get the number of columns, if that's important
        if node.children: self.format(node)

    def format_colspec(self, node):
        # we get colwidth, but don't need it
        pass

    def format_thead(self, node):
        for row in node.children:
            self.w('<tr>')
            for cell in row.children:
                s = ''
                attrs = cell.attributes
                if attrs.has_key('morecols'):
                    s = s + ' colspan=%d'%(attrs['morecols']+1)
                if attrs.has_key('morerows'):
                    s = s + ' rowspan=%d'%(attrs['morerows']+1)
                self.w('<th valign="top" align="left"%s>'%s)
                if cell.children: self.format(cell)
                self.w('</th>\n')
            self.w('</tr>\n')

    def format_tbody(self, node):
        for row in node.children:
            self.w('<tr>')
            for cell in row.children:
                s = ''
                attrs = cell.attributes
                if attrs.has_key('morecols'):
                    s = s + ' colspan=%d'%(attrs['morecols']+1)
                if attrs.has_key('morerows'):
                    s = s + ' rowspan=%d'%(attrs['morerows']+1)
                self.w('<td valign="top" align="left"%s>'%s)
                if cell.children: self.format(cell)
                self.w('</td>\n')
            self.w('</tr>\n')

    #
    # Inline Elements
    #
    # Inline elements occur within the text contents of body elements. Some
    # nesting of inline elements is allowed by these definitions, with the
    # following caveats:
    # - An inline element may not contain a nested element of the same type
    #   (e.g. <strong> may not contain another <strong>).
    # - Nested inline elements may or may not be supported by individual
    #   applications using this DTD.
    # - The inline elements <footnote_reference>, <literal>, and <image> do
    #   not support nesting.
    #
    #  What that means is that all of these take (%text.model;) except:
    #   literal (#PCDATA)
    #   footnote_reference (#PCDATA)
    #
    # text.model:
    # (#PCDATA | %inline.elements;)*
    #
    def format_emphasis(self, node):
        ''' (%text.model;)
        '''
        self.w('<em>')
        if node.children: self.format(node)
        self.w('</em>')

    def format_strong(self, node):
        ''' (%text.model;)
        '''
        self.w('<strong>')
        if node.children: self.format(node)
        self.w('</strong>')

    def format_interpreted(self, node):
        ''' (%text.model;)
            type      CDATA     #IMPLIED
        '''
        pass #raise NotImplementedError, node

    def format_literal(self, node):
        ''' (#PCDATA)
        '''
        self.w('<tt>')
        for literal in node.children:
            self.w(cgi.escape(literal.data))
        self.w('</tt>')

    def format_reference(self, node):
        ''' (%text.model;)
            %reference.atts;
            %anonymous.att;
        '''
        attrs = node.attributes
        doc = self.document
        ok = 1
        print node
        if attrs.has_key('refuri'):
            self.w('<a href="%s">'%attrs['refuri'])
        elif doc.explicit_targets.has_key(attrs['refname']):
            # an external reference has been defined
            ref = doc.explicit_targets[attrs['refname']]
            if ref.attributes.has_key('refuri'):
                self.w('<a href="%s">'%ref.attributes['refuri'])
            else:
                self.w('<a href="#%s">'%attrs['refname'])
        elif doc.implicit_targets.has_key(attrs['refname']):
            # internal reference
            name = attrs['refname']
            self.w('<a href="#%s">'%urllib.quote(name))
        else:
            ok = 0
            self.w('<span class="formatter_error">target "%s" '
                'undefined</span>'%attrs['refname'])
        if node.children: self.format(node)
        if ok:
            self.w('</a>')

    def format_footnote_reference(self, node):
        ''' (#PCDATA)
            %reference.atts;
            %auto.att;
        '''
        raise NotImplementedError, node

    def format_substitution_reference(self, node):
        ''' (%text.model;)
            %refname.att;
        '''
        raise NotImplementedError, node

    def format_problematic(self, node):
        ''' (%text.model;)
        '''
        raise NotImplementedError, node

    #
    # Finally, #text
    #
    def format__text(self, node):
        self.w(cgi.escape(node.data))


def main(filename, debug=0):
    parser = Parser()
    input = open(filename).read()
    document = dps.utils.newdocument()
    parser.parse(input, document)
    if debug == 1:
        print document.pformat()
    else:
        formatter = DumbHTMLFormatter()
        print formatter.format_document(document)

if __name__ == '__main__':
    if len(sys.argv) > 2:
        main(sys.argv[1], debug=1)
    else:
        main(sys.argv[1])

