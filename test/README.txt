$Id: README.txt,v 1.1 2001-07-27 07:16:21 richard Exp $

Structre of the tests:

   1   Test date classes
   1.1 Date
   1.2 Interval
   2   Set up schema
   3   Open with specific backend
   3.1 anydbm
   3.2 bsddb
   4   Create database base set (stati, priority, etc)
   5   Perform some actions
   6   Perform mail import
   6.1 text/plain
   6.2 multipart/mixed (with one text/plain)
   6.3 text/html
   6.4 multipart/alternative (with one text/plain)
   6.5 multipart/alternative (with no text/plain)


------
$Log: not supported by cvs2svn $
Revision 1.1  2001/07/27 06:55:07  richard
moving tests -> test

Revision 1.2  2001/07/25 04:34:31  richard
Added id and log to tests files...

