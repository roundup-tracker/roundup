$Id: README.txt,v 1.3 2004-10-24 08:37:58 a1s Exp $

Structure of the tests:

   1   Test date classes
   1.1 Date
   1.2 Interval
   2   Set up schema
   3   Open with specific backend
   3.1 anydbm
   4   Create database base set (stati, priority, etc)
   5   Perform some actions
   6   Perform mail import
   6.1 text/plain
   6.2 multipart/mixed (with one text/plain)
   6.3 text/html
   6.4 multipart/alternative (with one text/plain)
   6.5 multipart/alternative (with no text/plain)
