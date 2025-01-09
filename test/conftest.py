# simple way to see if there are order dependencies in tests
# can use if pytest-random-order --random-order mode isn't
# usable (e.g. python2).


# known issues:
#  python3 -m pytest -k Whoosh test/test_indexer.py fails starting with
#      first reversed (so last) test in module
#
#  python3 -m pytest test/test_cgi.py 
#    fails: FormTestCase::testCreatePermission
#           FormTestCase::testClassPermission
#           FormTestCase::testCheckAndPropertyPermission
#
#  this failure results in a failure in test_action again with
#     bad permission application. Something run prior to these
#     tests is breaking the permission checks.

#def pytest_collection_modifyitems(items): 
#    items.reverse()

# Add a marker for pg_schema tests.
# They duplicate the postgresql tests exactly but uses a named
# schema rather than the default 'public' schema.
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "pg_schema: tests using schema for postgres"
    )

# try to work around loss of testmon data when ^Cing out of tests.
def pytest_unconfigure(config):
    if hasattr(config, "testmon_data"):
        config.testmon_data.db.con.close()

