# $Id: __init__.py,v 1.4 2001-07-29 07:01:39 richard Exp $

__doc__ = '''
This is a simple-to-use and -install issue-tracking system with
command-line, web and e-mail interfaces.

Roundup manages a number of issues (with properties such as
"description", "priority", and so on) and provides the ability to (a) submit
new issues, (b) find and edit existing issues, and (c) discuss issues with
other participants. The system will facilitate communication among the
participants by managing discussions and notifying interested parties when
issues are edited. 

Roundup's structure is that of a cake:

 _________________________________________________________________________
|  E-mail Client   |   Web Browser   |   Detector Scripts   |    Shell    |
|------------------+-----------------+----------------------+-------------|
|   E-mail User    |    Web User     |      Detector        |   Command   | 
|-------------------------------------------------------------------------|
|                         Roundup Database Layer                          |
|-------------------------------------------------------------------------|
|                          Hyperdatabase Layer                            |
|-------------------------------------------------------------------------|
|                             Storage Layer                               |
 -------------------------------------------------------------------------

The first layer represents the users (chocolate).
The second layer is the Roundup interface to the users (vanilla).
The third and fourth layers are the internal Roundup database storage
  mechanisms (strawberry).
The final, lowest layer is the underlying database storage (rum).

These are implemented in the code in the following manner:
  E-mail User: roundup-mailgw and roundup.mailgw
     Web User: cgi-bin/roundup.cgi or roundup-server over
               roundup.cgi_client, roundup.cgitb and roundup.htmltemplate
     Detector: roundup.roundupdb and templates/<template>/detectors
      Command: roundup-admin
   Roundup DB: roundup.roundupdb
     Hyper DB: roundup.hyperdb, roundup.date
      Storage: roundup.backends.*

Additionally, there is a directory of unit tests in "test".

For more information, see the original overview and specification documents
written by Ka-Ping Yee in the "doc" directory. If nothing else, it has a
much prettier cake :)
'''

#
# $Log: not supported by cvs2svn $
# Revision 1.3  2001/07/28 01:39:02  richard
# Added some documentation to the roundup package.
#
# Revision 1.2  2001/07/22 12:09:32  richard
# Final commit of Grande Splite
#
#
# vim: set filetype=python ts=4 sw=4 et si
