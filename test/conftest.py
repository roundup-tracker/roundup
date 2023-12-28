# simple way to see if there are order dependencies in tests
# can use if pytest-random-order --random-order mode isn't
# usable (e.g. python2).

#def pytest_collection_modifyitems(items): 
#    items.reverse()

# Add a marker for pg_schema tests.
# They duplicate the postgresql tests exactly but uses a named
# schema rather than the default 'public' schema.
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "pg_schema: tests using schema for postgres"
    )
