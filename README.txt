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
OUT OF THE USE OF THIS CODE, EVEN IF BIZAR SOFTWARE PTY LTD HAS BEEN ADVISED
OF THE POSSIBILITY OF SUCH DAMAGE.

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
See the index.html file in the "doc" directory.


3. Design
=========
See the information in the "doc" directory.



4. TODO
=======
Most of the TODO items are captured in comments in the code. In summary:

in general:
  . more unit tests
  . more back-ends
hyperdb:
  . more efficient reverse lookups
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
richard@users.sourceforge.net


7. Thanks
=========
Well, Ping, of course ;)

Anthony Baxter, for some good first-release feedback. And then continuing
support through development on sourceforge.

