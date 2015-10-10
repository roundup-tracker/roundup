A number of tests uses the infrastructure of
	db_test_base.py

grep "from db_test_base" -l *.py
benchmark.py
session_common.py
test_anydbm.py
test_indexer.py
test_memorydb.py
test_mysql.py
test_postgresql.py
test_security.py
test_sqlite.py
test_userauditor.py

grep "import db_test_base" -l *.py
test_cgi.py
test_jinja2.py
test_mailgw.py
test_xmlrpc.py

grep "import memory\|from memory" -l *.py 
test_mailgw.py
test_memorydb.py


The remaining lines are an 2001 description from Richard,
which probably is outdated:

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
