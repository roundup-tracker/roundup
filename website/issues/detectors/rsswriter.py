#!/usr/bin/python

#
#  RSS writer Roundup reactor
#  Mark Paschal <markpasc@markpasc.org>
#

import os

import logging
logger = logging.getLogger('detector')

import sys

# How many <item>s to have in the feed, at most.
MAX_ITEMS = 30

#
#  Module metadata
#

__author__ = "Mark Paschal <markpasc@markpasc.org>"
__copyright__ = "Copyright 2003 Mark Paschal"
__version__ = "1.2"

__changes__ = """
1.1  29 Aug 2003  Produces valid pubDates. Produces pubDates and authors for
                  change notes. Consolidates a message and change note into one
                  item. Uses TRACKER_NAME in filename to produce one feed per
                  tracker. Keeps to MAX_ITEMS limit more efficiently.
1.2   5 Sep 2003  Fixes bug with programmatically submitted issues having
                  messages without summaries (?!).
x.x  26 Feb 2017  John Rouillard try to deal with truncation of rss
                  file cause by error in parsing 8'bit characcters in
                  input message. Further attempts to fix issue by
                  modifying message bail on 0 length rss file. Delete
                  it and retry.
"""

__license__ = 'MIT'

#
#  Copyright 2003 Mark Paschal
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to deal
#  in the Software without restriction, including without limitation the rights
#  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#  copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in all
#  copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#  SOFTWARE.
#


# The strftime format to use for <pubDate>s.
RSS20_DATE_FORMAT = '%a, %d %b %Y %H:%M:%S +0000'


def newRss(title, link, description):
        """Returns an XML Document containing an RSS 2.0 feed with no items."""
        import xml.dom.minidom
        rss = xml.dom.minidom.Document()

        root = rss.appendChild(rss.createElement("rss"))
        root.setAttribute("version", "2.0")
        root.setAttribute("xmlns:atom","http://www.w3.org/2005/Atom")
        root.setAttribute("xmlns:dc","http://purl.org/dc/elements/1.1/")

        channel = root.appendChild(rss.createElement("channel"))
        addEl = lambda tag,value: channel.appendChild(rss.createElement(tag)).appendChild(rss.createTextNode(value))
        def addElA(tag,attr):
                node=rss.createElement(tag)
                for attr, val in attr.items():
                        node.setAttribute(attr, val)
                channel.appendChild(node)

        addEl("title", title)
        addElA('atom:link', attr={"rel": "self",
                   "type": "application/rss+xml", "href":  link + "@@file/rss.xml"})
        addEl("link", link)
        addEl("description", description)

        return rss  # has no items


def writeRss(db, cl, nodeid, olddata):
        """
        Reacts to a created or changed issue. Puts new messages and the change note
        in items in the RSS feed, as determined by the rsswriter.py FILENAME setting.
        If no RSS feed exists where FILENAME specifies, a new feed is created with
        rsswriter.newRss.
        """

        # The filename of a tracker's RSS feed. Tracker config variables
        # are placed with the standard '%' operator syntax.

        FILENAME = "%s/rss.xml"%db.config['TEMPLATES']

        # i.e., roundup.cgi/projects/_file/rss.xml
        # FILENAME = "/home/markpasc/public_html/%(TRACKER_NAME)s.xml"

        filename = FILENAME % db.config.__dict__

        # return if issue is private
        # enable when private property is added
        ##if ( db.issue.get(nodeid, 'private') ):
        ##        if __debug__:
        ##                logger.debug("rss: Private issue. not generating rss")
        ##        return

        if __debug__:
                logger.debug("rss: generating rss for issue %s", nodeid)

        # open the RSS
        import xml.dom.minidom
        from xml.parsers.expat import ExpatError

        try:
                rss = xml.dom.minidom.parse(filename)
        except IOError as e:
                if 2 != e.errno: raise
                # File not found
                rss = newRss(
                        "%s tracker" % (db.config.TRACKER_NAME,),
                        db.config.TRACKER_WEB,
                        "Recent changes to the %s Roundup issue tracker" % (db.config.TRACKER_NAME,)
                )
        except ExpatError as e:
                if os.path.getsize(filename) == 0:
                    # delete the file, it's broke
                    os.remove(filename)
                    # create new rss file
                    rss = newRss(
                        "%s tracker" % (db.config.TRACKER_NAME,),
                        db.config.TRACKER_WEB,
                        "Recent changes to the %s Roundup issue tracker" % (db.config.TRACKER_NAME,)
                    )
                else:
                    raise

        channel = rss.documentElement.getElementsByTagName('channel')[0]
        addEl = lambda parent,tag,value: parent.appendChild(rss.createElement(tag)).appendChild(rss.createTextNode(value))
        issuelink = '%sissue%s' % (db.config.TRACKER_WEB, nodeid)


        if olddata:
                chg = cl.generateChangeNote(nodeid, olddata)
        else:
                chg = cl.generateCreateNote(nodeid)

        def addItem(desc, date, userid):
                """
                Adds an RSS item to the RSS document. The title, link, and comments
                link are those of the current issue.
                
                desc: the description text to use
                date: an appropriately formatted string for pubDate
                userid: a Roundup user ID to use as author
                """

                item = rss.createElement('item')

                addEl(item, 'title', db.issue.get(nodeid, 'title'))
                addEl(item, 'link', issuelink)
                addEl(item, 'guid', issuelink + '#' + date.replace(' ','+'))
                addEl(item, 'comments', issuelink)
                addEl(item, 'description', desc.replace('&','&amp;').replace('<','&lt;').replace('\n', '<br>\n'))
                addEl(item, 'pubDate', date)
                # use dc:creator as username is not valid email address and
                # author element must be valid email address
                # addEl(item, 'author',
                addEl(item, 'dc:creator',
                        '%s' % (
                                db.user.get(userid, 'username')
                        )
                )

                channel.appendChild(item)

        # add detectors directory to path if it's not there.
        # FIXME - see if this pollutes the sys.path for other
        # trackers.
        detector_path="%s/detectors"%(db.config.TRACKER_HOME)
        if ( sys.path.count(detector_path) == 0 ):
                sys.path.insert(0,detector_path)

        from nosyreaction import determineNewMessages
        for msgid in determineNewMessages(cl, nodeid, olddata):
                logger.debug("Processing new message msg%s for issue%s", msgid, nodeid)
                desc = db.msg.get(msgid, 'content')

                if desc and chg:
                        desc += chg
                elif chg:
                        desc = chg
                chg = None

                addItem(desc or '', db.msg.get(msgid, 'date').pretty(RSS20_DATE_FORMAT), db.msg.get(msgid, 'author'))

        if chg:
                from time import strftime
                addItem(chg.replace('\n----------\n', ''), strftime(RSS20_DATE_FORMAT), db.getuid())


        for c in channel.getElementsByTagName('item')[0:-MAX_ITEMS]:  # leaves at most MAX_ITEMS at the end
                channel.removeChild(c)

        # write the RSS
        out = open(filename, 'w')

        try:
            out.write(rss.toxml())
        except Exception as e:
            # record the falure This should not happen.
            logger.error(e)
            out.close() # create 0 length file maybe?? But we handle above.
            raise  # let the user know something went wrong.

        out.close()


def init(db):
        db.issue.react('create', writeRss)
        db.issue.react('set', writeRss)
#SHA: c4f916a13d533ff0c49386fc4f1f9f254adeb744
