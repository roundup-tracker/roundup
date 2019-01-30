"""
Restful API for Roundup

This module is free software, you may redistribute it
and/or modify under the same terms as Python.
"""

import json
import pprint
from roundup import hyperdb
from roundup.cgi.templating import Unauthorised
from roundup import xmlrpc


class RestfulInstance(object):
    """Dummy Handler for REST
    """

    def __init__(self, db):
        # TODO: database, translator and instance.actions
        self.db = db

    def get_collection(self, class_name, input):
        class_obj = self.db.getclass(class_name)
        prop_name = class_obj.labelprop()
        result = [{'id': item_id, 'name': class_obj.get(item_id, prop_name)}
                  for item_id in class_obj.list()
                  if self.db.security.hasPermission('View', self.db.getuid(),
                                                    class_name, None, item_id)
                  ]
        result = json.JSONEncoder().encode(result)

        return result

    def get_element(self, class_name, item_id, input):
        class_obj = self.db.getclass(class_name)
        props = class_obj.properties.keys()
        props.sort()  # sort properties
        result = [(prop_name, class_obj.get(item_id, prop_name))
                  for prop_name in props
                  if self.db.security.hasPermission('View', self.db.getuid(),
                                                    class_name, prop_name,
                                                    item_id)
                  ]
        result = json.JSONEncoder().encode(dict(result))

        return result

    def post_collection(self, class_name, input):
        if not self.db.security.hasPermission('Create', self.db.getuid(),
                                              class_name):
            raise Unauthorised('Permission to create %s denied' % class_name)

        class_obj = self.db.getclass(class_name)

        # convert types
        props = xmlrpc.props_from_args(self.db, class_obj, input)

        # check for the key property
        key = class_obj.getkey()
        if key and key not in props:
            raise xmlrpc.UsageError, 'Must provide the "%s" property.' % key

        for key in props:
            if not self.db.security.hasPermission('Create', self.db.getuid(),
                                                  class_name, property=key):
                raise Unauthorised('Permission to create %s.%s denied' %
                                   (class_name, key))

        # do the actual create
        try:
            result = class_obj.create(**props)
            self.db.commit()
        except (TypeError, IndexError, ValueError), message:
            raise xmlrpc.UsageError, message
        return result

    def post_element(self, class_name, item_id, input):
        raise NotImplementedError

    def put_collection(self, class_name, input):
        raise NotImplementedError

    def put_element(self, class_name, item_id, input):
        raise NotImplementedError

    def delete_collection(self, class_name, input):
        # TODO: should I allow user to delete the whole collection ?
        raise NotImplementedError

    def delete_element(self, class_name, item_id, input):
        # TODO: BUG with DELETE without form data. Working with random data
        #       crash at line self.form = cgi.FieldStorage(fp=request.rfile, environ=env)
        try:
            self.db.destroynode(class_name, item_id)
            result = 'OK'
        except IndexError:
            result = 'Error'

        return result

    def patch_collection(self, class_name, input):
        raise NotImplementedError

    def patch_element(self, class_name, item_id, input):
        raise NotImplementedError

    def dispatch(self, method, uri, input):
        print "METHOD: " + method + " URI: " + uri
        print type(input)
        pprint.pprint(input)
        # TODO: process input_form directly instead of making a new array
        # TODO: rest server
        # TODO: check roundup/actions.py
        # TODO: if uri_path has more than 2 child, return 404
        # TODO: custom JSONEncoder to handle other data type
        # TODO: catch all error and display error.

        # PATH is split to multiple pieces
        # 0 - rest
        # 1 - resource

        resource_uri = uri.split("/")[1]
        input_data = ["%s=%s" % (item.name, item.value) for item in input]

        try:
            if resource_uri in self.db.classes:
                output = getattr(self, "%s_collection" % method.lower())(resource_uri, input_data)
            else:
                class_name, item_id = hyperdb.splitDesignator(resource_uri)
                output = getattr(self, "%s_element" % method.lower())(class_name, item_id, input_data)
        except hyperdb.DesignatorError:
            pass  # invalid URI
        except AttributeError:
            raise NotImplementedError  # Error: method is invalid

        print "Length: %s - Content(50 char): %s" % (len(output), output[:50])
        return output
