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
       WARNING: Very ugly !!!!, cleaned & better organized in progress (next commit)
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
            result = [class_obj.get(item_id, prop_name)"""
            result = [{'id': item_id}
                      for item_id in class_obj.list()
                      if self.db.security.hasPermission('View',
                                                        self.db.getuid(),
                                                        class_name,
                                                        None,
                                                        item_id)
                      ]
            result = json.JSONEncoder().encode(result)
            # result = `len(dict(result))` + ' ' + `len(result)`
        except KeyError:
            pass

        try:
            class_name, item_id = hyperdb.splitDesignator(resource_uri)
            class_obj = self.db.getclass(class_name)
            props = class_obj.properties.keys()
            props.sort()
            result = [(prop_name, class_obj.get(item_id, prop_name))
                      for prop_name in props
                      if self.db.security.hasPermission('View',
                                                        self.db.getuid(),
                                                        class_name,
                                                        prop_name,
                                                        item_id)
                      ]
            # Note: is this a bug by having an extra indent in xmlrpc ?
            result = json.JSONEncoder().encode(dict(result))
        except hyperdb.DesignatorError:
            pass

        return result

    def action_post(self, resource_uri, input):
        class_name = resource_uri

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

    def action_put(self, resource_uri, input):
        raise NotImplementedError

    def action_delete(self, resource_uri, input):
        # TODO: should I allow user to delete the whole collection ?
        # TODO: BUG with DELETE without form data. Working with random data
        #       crash at line self.form = cgi.FieldStorage(fp=request.rfile, environ=env)
        class_name = resource_uri
        try:
            class_obj = self.db.getclass(class_name)
            raise NotImplementedError
        except KeyError:
            pass

        try:
            class_name, item_id = hyperdb.splitDesignator(resource_uri)
            print class_name
            print item_id
            self.db.destroynode(class_name, item_id)
            result = 'OK'
        except IndexError:
            result = 'Error'
        except hyperdb.DesignatorError:
            pass

        return result

    def action_patch(self, resource_uri, input):
        raise NotImplementedError

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
        input_form = ["%s=%s" % (item.name, item.value) for item in input]
        # TODO: process input_form directly instead of making a new array
        # TODO: rest server
        # TODO: check roundup/actions.py
        # TODO: if uri_path has more than 2 child, return 404
        # TODO: custom JSONEncoder to handle other data type
        # TODO: catch all error and display error.
        try:
            output = getattr(self, "action_%s" % method.lower())(uri_path[1], input_form)
        except AttributeError:
            raise NotImplementedError

        print "Response Length: %s - Response Content (First 50 char): %s" %\
              (len(output), output[:50])
        return output
