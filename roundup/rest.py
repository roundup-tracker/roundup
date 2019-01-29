# Restful API for Roundup
#
# This module is free software, you may redistribute it
# and/or modify under the same terms as Python.
#

import json
import pprint


class RestfulInstance(object):
    """Dummy Handler for REST
    """

    def __init__(self, db):
        # TODO: database, translator and instance.actions
        self.db = db

    def dispatch(self, method, uri, input):
        print method
        print uri
        print type(input)
        pprint.pprint(input)
        return ' '.join([method, uri, pprint.pformat(input)])
