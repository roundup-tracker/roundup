=======================================================
Roundup: an Issue-Tracking System for Knowledge Workers
=======================================================

Introduction
============

Roundup is a tool for creating issue trackers. This includes:

  * bug trackers,
  * help desk,
  * agile development trackers,
  * customer issue tracking,
  * fleet maintenance tracking,
  * GTD tool etc.

It comes with predefined trackers meant to be customized for your
workflow. Starting trackers include:

  * generic tracker,
  * development bug/feature tracker (3 variations),
  * bare bones minimal tracker.

Your users interact with (create, read, update, close) issues using a
web interface or by email. It can be programmaticly managed via REST
or XMLRPC, CLI, or via local Python scripts.

The user's guide is at https://www.roundup-tracker.org/docs/user_guide.html.


INSTANT GRATIFICATION
=====================

The impatient may try Roundup immediately by running demo.py from
the source directory::

   python demo.py

This will create new tracker home in "demo" subdirectory and start
a web server. To reset demo instance::

   python demo.py nuke

For details see the "For the Really Impatient" section of the
installation document at:

   https://roundup-tracker.org/docs/installation.html#for-the-really-impatient

for details on running demo mode or using the docker demo mode.

Tracker Home
------------

"Tracker Home" is main concept when starting with Roundup. It is
directory where all your tracker data is stored. This directory is
created every time when new tracker is initialized and includes
tracker configuration, database, template, schema and extensions.

Using Roundup
=============

Please see the user's guide at:

  https://roundup-tracker.org/docs/installation.html#for-the-really-impatient

Installation
============

Please see "doc/installation.txt". For a basic tracker, only the
Python standard library is required. It can be enhanced by adding
other packages. A basic virtual environment install can be done using:


  python3 -m venv roundup
  . roundup/bin/activate
  python -m pip install roundup
  roundup-demo # to start a test demo instance

See "doc/installation.txt" for details on deploying a production
instance.

Upgrading
=========

Please see "doc/upgrading.txt".

Security Issues
===============

Please see "doc/security.txt" for directions on reporting security issues.


Other Information
=================

Start with the index.txt file in the "doc" directory. These
documentation files are written in reStructedText, which can be
converted into HTML format. If you have Sphinx installed, you can
do this by running::

   python setup.py build_doc

Resulting HTML files will be in "share/doc/roundup/html" directory.


Contributing Guidelines
=======================

To get started on development or documentation work, read the file
"doc/developers.txt".  This documents the project rules, how to set up
a development environment and submit patches and tests.

Support/Contact
===============

Please see https://www.roundup-tracker.org/contact.html for directions
on using email or IRC to contact the developers.


License
=======
See COPYING.txt.

tl;dr MIT, Zope version 2, Python Software Foundation version 2
