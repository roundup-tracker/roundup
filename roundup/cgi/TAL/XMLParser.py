##############################################################################
#
# Copyright (c) 2001, 2002 Zope Corporation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
#
##############################################################################
# Modifications for Roundup:
# 1. commented out zLOG references
# 2. use roundup.anypy.urllib_
"""
Generic expat-based XML parser base class.
"""

#import zLOG

class XMLParser:

    ordered_attributes = 0

    handler_names = [
        "StartElementHandler",
        "EndElementHandler",
        "ProcessingInstructionHandler",
        "CharacterDataHandler",
        "UnparsedEntityDeclHandler",
        "NotationDeclHandler",
        "StartNamespaceDeclHandler",
        "EndNamespaceDeclHandler",
        "CommentHandler",
        "StartCdataSectionHandler",
        "EndCdataSectionHandler",
        "DefaultHandler",
        "DefaultHandlerExpand",
        "NotStandaloneHandler",
        "ExternalEntityRefHandler",
        "XmlDeclHandler",
        "StartDoctypeDeclHandler",
        "EndDoctypeDeclHandler",
        "ElementDeclHandler",
        "AttlistDeclHandler"
        ]

    def __init__(self, encoding=None):
        self.parser = p = self.createParser()
        # Make sure we don't get fed unicode strings in Python 2 as we
        # can't handle those
        if hasattr(self.parser, 'returns_unicode'):
            self.parser.returns_unicode = False
        if self.ordered_attributes:
            try:
                self.parser.ordered_attributes = self.ordered_attributes
            except AttributeError:
                #zLOG.LOG("TAL.XMLParser", zLOG.INFO, 
                #         "Can't set ordered_attributes")
                self.ordered_attributes = 0
        for name in self.handler_names:
            method = getattr(self, name, None)
            if method is not None:
                try:
                    setattr(p, name, method)
                except AttributeError:
                    #zLOG.LOG("TAL.XMLParser", zLOG.PROBLEM,
                    #         "Can't set expat handler %s" % name)
                    pass

    def createParser(self, encoding=None):
        global XMLParseError
        try:
            from Products.ParsedXML.Expat import pyexpat
            XMLParseError = pyexpat.ExpatError
            return pyexpat.ParserCreate(encoding, ' ')
        except ImportError:
            from xml.parsers import expat
            XMLParseError = expat.ExpatError
            return expat.ParserCreate(encoding, ' ')

    def parseFile(self, filename):
        self.parseStream(open(filename))

    def parseString(self, s):
        self.parser.Parse(s, 1)

    def parseURL(self, url):
        import roundup.anypy.urllib_
        self.parseStream(roundup.anypy.urllib_.urlopen(url))

    def parseStream(self, stream):
        self.parser.ParseFile(stream)

    def parseFragment(self, s, end=0):
        self.parser.Parse(s, end)
