=======================================================
Roundup: an Issue-Tracking System for Knowledge Workers
=======================================================

INSTANT GRATIFICATION
=====================

The impatient may try Roundup immediately by running demo.py from
the source directory::

   python demo.py

This will create new tracker home in "demo" subdirectory and start
server. To reset demo instance::

   python demo.py nuke


Tracker Home
=============
"Tracker Home" is main concept when starting with Roundup. It is
directory where all your tracker data is stored. This directory is
created every time when new tracker is initialized and includes
tracker configuration, database, template, schema and extensions.


Installation
============
Please see "doc/installation.txt"


Upgrading
=========
Please see "doc/upgrading.txt"


Usage and Other Information
===========================
Start with the index.txt file in the "doc" directory. These
documentation files are written in reStructedText, which can be
converted into HTML format. If you have Sphinx installed, you can
do this by running::

   python setup.py build_doc

Resulting HTML files will be in "share/doc/roundup/html" directory.


For Developers
==============
To get started on development work, read the developers.txt file in
the "doc" directory.


License
=======
See COPYING.txt
