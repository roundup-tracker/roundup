import unittest

import test_dates, test_schema, test_db

def go():
    suite = unittest.TestSuite((
        test_dates.suite(),
        test_schema.suite(),
        test_db.suite(),
    ))
    runner = unittest.TextTestRunner()
    runner.run(suite)
