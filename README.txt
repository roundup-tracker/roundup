                                    Roundup
                                    =======


1. License
==========

Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
This module is free software, and you may redistribute it and/or modify
under the same terms as Python, so long as this copyright message and
disclaimer are retained in their original form.

IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.


The stylesheet included with this package has been copied from the Zope
management interface and presumably belongs to Digital Creations.


2. Installation
===============
For installation notes, please see the file INSTALL.TXT


3. Usage
========
The system is designed to accessed through the command-line, e-mail or web
interface. Roundup has some useful doucmentation in its docstrings, so
"pydoc roundup" will give useful information.

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
Use "pydoc roundup.mailgw".


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
See the information in the "doc" directory.



4. TODO
=======
Most of the TODO items are captured in comments in the code. In summary:

in general:
  . more unit tests
  . more back-ends
  . better error handling (nicer messages for users)
hyperdb:
  . transaction support
  . more efficient reverse lookups
roundupdb:
  . split the file storage into multiple dirs?
roundup-mailgw:
  . errors as attachments
roundup-server:
  . check the source file timestamps before reloading
cgi_client
  . keep form fields in form on bad submission - only clear it if all ok


5. Known Bugs
=============

date:
  . date subtraction doesn't work correctly "if the dates cross leap years,
    phases of the moon, ..."
cgi:
  . setting an issue to resolved, and no other changes, results in a change
    message with no indication of what changed
  . enabling a filter disables the current filter hidden fields...


6. Author
=========
richard@users.sourceforge.net


7. Thanks
=========
Well, Ping, of course ;)

Anthony Baxter, for some good first-release feedback. And then continuing
support through development on sourceforge.

