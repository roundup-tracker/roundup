# -*- coding: iso-8859-1 -*-
"""
    MoinMoin - roundup theme

    Created by Stefan Seefeld.

    @copyright: 2009 Stefan Seefeld
    @license: GNU GPL, see COPYING for details.
"""

from MoinMoin.theme import ThemeBase
from MoinMoin import wikiutil

class Theme(ThemeBase):

    name = "roundup"

    def logo(self):
        html = u''
        if self.cfg.logo_string:
            page = wikiutil.getFrontPage(self.request)
            logo = page.link_to_raw(self.request, self.cfg.logo_string)
            html = u'<h1>%s</h1>' %logo
        return html

    def menu(self, d):
        """ Create menu"""
        html = [
            u'<div class="menu">',
            u'  <ul>',
            u'    <li><a href="http://www.roundup-tracker.org">Home</a></li>',
            u'    <li><a href="http://pypi.python.org/pypi/roundup">Download</a></li>',
            u'    <li><a href="http://www.roundup-tracker.org/docs.html">Docs</a></li>',
            u'    <li><a href="http://issues.roundup-tracker.org">Issues</a></li>',
            u'    <li><a href="http://www.roundup-tracker.org/contact.html">Contact</a></li>',
            self.wiki_links(d),
            u'    <li><a href="http://www.roundup-tracker.org/code.html">Code</a></li>',
            u'  </ul>',
            u'</div>',
            ]
        return u'\n'.join(html)

    def wiki_links(self, d):
        
        request = self.request
        found = {} # pages we found. prevent duplicates
        items = [] # wiki items items

        # Process config navi_bar
        if request.cfg.navi_bar:
           for text in request.cfg.navi_bar:
               pagename, link = self.splitNavilink(text)
               items.append('<li>%s</li>'%link)
               found[pagename] = 1

        # Add user links to wiki links, eliminating duplicates.
        userlinks = request.user.getQuickLinks()
        for text in userlinks:
            # Split text without localization, user knows what he wants
            pagename, link = self.splitNavilink(text, localize=0)
            if not pagename in found:
                items.append('<li>%s</li>'%link)
                found[pagename] = 1

        text = '[[%s|Wiki]]'%self.cfg.page_front_page
        pagename, link = self.splitNavilink(text, localize=0)
        menu = '<ul>%s\n</ul>'%'\n'.join(items)
        user = '%s'%self.username(d)
	html = u'<li class="current">%s\n%s\n%s\n</li>'%(link,menu,user)
        return html

    def header(self, d):
        """
        Assemble page header

        @param d: parameter dictionary
        @rtype: string
        @return: page header html
        """
        _ = self.request.getText

        html = [
            u'<div class="header">',
            self.logo(),
            self.searchform(d),
            u'<div id="locationline">',
            self.interwiki(d),
            u'</div>',
            u'</div>',
            u'<div class="navigation">',
            self.menu(d),
            u'</div>',
            u'<div class="content">',
            self.trail(d),
            self.msg(d),
            self.title(d),
            self.editbar(d),
            ]
        return u'\n'.join(html)

    def footer(self, d, **keywords):
        """ Assemble wiki footer

        @param d: parameter dictionary
        @keyword ...:...
        @rtype: unicode
        @return: page footer html
        """
        page = d['page']
        html = [
            u'</div><!-- content -->',
            u'<div class="footer">',
            self.credits(d),
            self.showversion(d, **keywords),
            u'</div>',
            ]
        return u'\n'.join(html)


def execute(request):
    """ Generate and return a theme object

    @param request: the request object
    @rtype: MoinTheme
    @return: Theme object
    """
    return Theme(request)

