                                    Roundup
                                    =======


1. License
==========
This software is released under the GNU GPL. The copyright is held by Bizar
Software Pty Ltd (http://www.bizarsoftware.com.au).

The stylesheet included with this package has been copied from the Zope
management interface and presumably belongs to Digital Creations.


2. Installation
===============
For installation notes, please see the file INSTALL.TXT


3. Usage
========
The system is designed to accessed through the command-line, e-mail or web
interface.

3.1 Command-line
----------------
The command-line tool is called "roundup-admin" and is used for most low-level
database manipulations such as:
 . creating a database instance
 . redefining the list of products ("create" and "retire" commands)
 . adding users manually, or setting their passwords ("create" and "set")
 . other stuff - run it with no arguments to get a better description of
   what it does.


3.2 E-mail
----------
See the docstring at the start of the roundup/mailgw.py source file.


3.3 Web
-------
Hopefully, this interface is pretty self-explanatory...

Index views may be modified by the following arguments:
    :sort    - sort by prop name, optionally preceeded with '-'
	     to give descending or nothing for ascending sorting.
    :group   - group by prop name, optionally preceeded with '-' or
	     to sort in descending or nothing for ascending order.
    :filter  - selects which props should be displayed in the filter
	     section. Default is all.
    :columns - selects the columns that should be displayed.
	     Default is all.
    propname - selects the values the node properties given by propname
             must have (very basic search/filter).



3. Design
=========
This software was written according to the specification found at

 http://software-carpentry.codesourcery.com/entries/second-round/track/Roundup/

a copy of the spec is distributed with roundup as doc/spec.html.


There have been some modifications. I've marked these in the source with
'XXX' comments when I remember to.

In short:
 Class.find() - may match multiple properties, uses keyword args.

 Class.filter() - isn't in the spec and it's very useful to have at the Class
    level.
 
 CGI interface index view specifier layout part - lose the '+' from the
    sorting arguments (it's a reserved URL character ;). Just made no
    prefix mean ascending and '-' prefix descending.

 ItemClass - renamed to IssueClass to better match it only having one
    hypderdb class "issue". Allowing > 1 hyperdb class breaks the
    "superseder" multilink (since it can only link to one thing, and we'd
    want bugs to link to support and vice-versa).

 templates - the call="link()" is handled by special-case mechanisms in my
    top-level CGI handler. In a nutshell, the handler looks for a method on
    itself called 'index%s' or 'item%s' where %s is a class. Most items
    pass on to the templating mechanism, but the file class _always_ does
    downloading. It'll probably stay this way too...

 template - call="link(property)" may be used to link "the current node"
    (from an index) - the link text is the property specified.

 template - added functions that I found very useful: List, History and
    Submit.

 template - items must specify the message lists, history, etc. Having them
    by default was sometimes not wanted.

 template - index view determines its default columns from the template's
    <property> tags.

 template - menu() and field() look awfully similar now .... ;)

 roundup.py - the command-line tool has a lot more commands at its disposal



4. TODO
=======
Most of the TODO items are captured in comments in the code. In summary:

in general:
  . better error handling (nicer messages for users)
  . possibly revert the entire damn thing to 1.5.2 ... :(
roundup.py:
  . getopt() for command line
  . default init db in some way?
hyperdb:
  . transaction support
roundupdb:
  . split the file storage into multiple files
roundup-mailgw:
  . errors as attachments
  . snip signatures?
server:
  . check the source file timestamps before reloading
date:
  . blue Date.__sub__ needs food, badly
config
  . default to blank config in distribution and warn appropriately
roundup_cgi
  . searching
  . keep form fields in form on bad submission - only clear it if all ok
  . messages should have the roundup CGI URL in them


5. Known Bugs
=============

date:
  . date subtraction doesn't work correctly "if the dates cross leap years,
    phases of the moon, ..."

filter:
  . incorrectly embeds hidden fields for filters being displayed - and
    doesn't use the existing values for filters being displayed either.


6. Author
=========
richard@bizarsoftware.com.au


7. Thanks
=========
Well, Ping, of course ;)

Anthony Baxter, for some good first-release feedback. And then continuing
support through development on sourceforge.

