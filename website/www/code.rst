Code
====

Changelog
----------

The changelog is available `here <http://cvs.roundup-tracker.org/roundup/roundup/CHANGES.txt?view=markup&content-type=text/vnd.viewcvs-markup&revision=HEAD>`_

ViewVC
------

You may browse the repository via `viewvc <http://cvs.roundup-tracker.org/roundup/>`_

Read-only Access
----------------

The code can be checked out through anonymous (pserver) CVS with the following commands::

  cvs -d:pserver:anonymous@cvs.roundup-tracker.org:/cvsroot/roundup login
 
  cvs -z3 -d:pserver:anonymous@cvs.roundup-tracker.org:/cvsroot/roundup co -P modulename 

Read-write Access
-----------------

Developers may also make use of shared SSH keys for authentication::

  export CVS_RSH=ssh
 
  cvs -z3 -d:ext:developername@cvs.roundup-tracker.org:/cvsroot/roundup co -P modulename

