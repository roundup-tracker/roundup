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

    def action_get(self, resource, input):
        classname, itemid = hyperdb.splitDesignator(resource)
        cl = self.db.getclass(classname)
        props = cl.properties.keys()
        props.sort()
        for p in props:
            if not self.db.security.hasPermission('View', self.db.getuid(),
                                                  classname, p, itemid):
                raise Unauthorised('Permission to view %s of %s denied' %
                                   (p, resource))
            result = [(prop, cl.get(itemid, prop)) for prop in props]

        # print type(result)
        # print type(dict(result))
        return json.JSONEncoder().encode(dict(result))
        # return json.dumps(dict(result))
        # return dict(result)

    def dispatch(self, method, uri, input):
        print method
        print uri
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

        print output
        print len(output)
        return output
