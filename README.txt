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
See the information in the "doc" directory.



4. TODO
=======
Most of the TODO items are captured in comments in the code. In summary:

in general:
  . more unit tests
  . more back-ends
  . better error handling (nicer messages for users)
  . possibly revert the entire damn thing to 1.5.2 ... :(
hyperdb:
  . transaction support
  . more efficient reverse lookups
roundupdb:
  . split the file storage into multiple dirs?
roundup-mailgw:
  . errors as attachments
  . snip signatures?
roundup-server:
  . check the source file timestamps before reloading
cgi_client
  . keep form fields in form on bad submission - only clear it if all ok


5. Known Bugs
=============

date:
  . date subtraction doesn't work correctly "if the dates cross leap years,
    phases of the moon, ..."


6. Author
=========
richard@sourceforge.net


7. Thanks
=========
Well, Ping, of course ;)

Anthony Baxter, for some good first-release feedback. And then continuing
support through development on sourceforge.

