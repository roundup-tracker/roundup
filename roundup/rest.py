"""
Restful API for Roundup

This module is free software, you may redistribute it
and/or modify under the same terms as Python.
"""

import json
import pprint
from roundup import hyperdb
from roundup.cgi.templating import Unauthorised


class RestfulInstance(object):
    """Dummy Handler for REST
    """

    def __init__(self, db):
        # TODO: database, translator and instance.actions
        self.db = db

    def action_get(self, resource_uri, input):
        # TODO: split this into collection URI and resource URI
        class_name = resource_uri
        try:
            class_obj = self.db.getclass(class_name)
            """prop_name = class_obj.labelprop()
            result = [class_obj.get(item_id, prop_name)
                      for item_id in class_obj.list()
                      if self.db.security.hasPermission('View', self.db.getuid(),
                                                        class_name, prop_name, item_id)
                      ]
            result = json.JSONEncoder().encode(result)"""
            result = [{'id': item_id}
                      for item_id in class_obj.list()
                      if self.db.security.hasPermission('View', self.db.getuid(),
                                                        class_name, None, item_id)
                      ]
            result = json.JSONEncoder().encode(result)
            #result = `len(dict(result))` + ' ' + `len(result)`
        except KeyError:
            pass

        try:
            class_name, item_id = hyperdb.splitDesignator(resource_uri)
            class_obj = self.db.getclass(class_name)
            props = class_obj.properties.keys()
            props.sort()
            result = [(prop_name, class_obj.get(item_id, prop_name))
                      for prop_name in props
                      if self.db.security.hasPermission('View', self.db.getuid(),
                                                        class_name, prop_name, item_id)
                      ]
            # Note: is this a bug by having an extra indent in xmlrpc ?
            result = json.JSONEncoder().encode(dict(result))
        except hyperdb.DesignatorError:
            pass

        # print type(result)
        # print type(dict(result))
        return result
        # return json.dumps(dict(result))
        # return dict(result)

    def dispatch(self, method, uri, input):
        print "METHOD: " + method + " URI: " + uri
        print type(input)
        pprint.pprint(input)

        # PATH is split to multiple pieces
        # 0 - rest
        # 1 - resource
        #
        # Example: rest/issue - collection uri
        # Example: rest/issue573 - element uri
        uri_path = uri.split("/")
        # TODO: use named function for this instead
        # TODO: check roundup/actions.py
        # TODO: if uri_path has more than 2 child, return 404
        output = "METHOD is not supported"
        if method == "GET":
            output = self.action_get(uri_path[1], input)
        elif method == "POST":
            pass
        elif method == "PUT":
            pass
        elif method == "DELETE":
            pass
        elif method == "PATCH":
            pass
        else:
            pass

        print "Response Length: " + `len(output)` + " - Response Content (First 50 char): " + output[:50]
        return output
