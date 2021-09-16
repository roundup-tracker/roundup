"""
Restful API for Roundup

This module is free software, you may redistribute it
and/or modify under the same terms as Python.
"""

from __future__ import print_function

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse
import os
import json
import sys
import time
import traceback
import re

try:
    # if dicttoxml installed in roundup directory, use it
    from roundup.dicttoxml import dicttoxml
except ImportError:
    try:
        # else look in sys.path
        from dicttoxml import dicttoxml
    except ImportError:
        # else not supported
        dicttoxml = None

from hashlib import md5

from roundup import hyperdb
from roundup import date
from roundup import actions
from roundup.i18n import _
from roundup.anypy.strings import bs2b, b2s, u2s, is_us
from roundup.rate_limit import RateLimit, Gcra
from roundup.exceptions import Reject, UsageError
from roundup.cgi.exceptions import NotFound, Unauthorised, PreconditionFailed

import hmac
from datetime import timedelta

# Py3 compatible basestring
try:
    basestring
except NameError:
    basestring = str
    unicode = str

import roundup.anypy.random_ as random_

import logging
logger = logging.getLogger('roundup.rest')

if not random_.is_weak:
    logger.debug("Importing good random generator")
else:
    logger.warning("**SystemRandom not available. Using poor random generator")

chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'


def _data_decorator(func):
    """Wrap the returned data into an object."""
    def format_object(self, *args, **kwargs):
        # get the data / error from function
        try:
            code, data = func(self, *args, **kwargs)
        except NotFound as msg:
            code = 404
            data = msg
        except IndexError as msg:
            code = 404
            data = msg
        except Unauthorised as msg:
            code = 403
            data = msg
        except (UsageError, KeyError) as msg:
            code = 400
            data = msg
        except (AttributeError, Reject) as msg:
            code = 405
            data = msg
        except ValueError as msg:
            code = 409
            data = msg
        except PreconditionFailed as msg:
            code = 412
            data = msg
        except NotImplementedError:
            code = 402  # nothing to pay, just a mark for debugging purpose
            data = 'Method under development'
        except:  # noqa: E722
            exc, val, tb = sys.exc_info()
            code = 400
            ts = time.ctime()
            if getattr(self.client.request, 'DEBUG_MODE', None):
                data = val
            else:
                data = '%s: An error occurred. Please check the server log' \
                       ' for more information.' % ts
            # out to the logfile
            print('EXCEPTION AT', ts)
            traceback.print_exc()

        # decorate it
        self.client.response_code = code
        if code >= 400:  # any error require error format
            result = {
                'error': {
                    'status': code,
                    'msg': data
                }
            }
        else:
            if hasattr(self.db, 'stats') and self.report_stats:
                self.db.stats['elapsed'] = time.time()-self.start
                data['@stats'] = self.db.stats
            result = {
                'data': data
            }
        return result
    return format_object


def calculate_etag(node, key, classname="Missing", id="0",
                   repr_format="json"):
    '''given a hyperdb node generate a hashed representation of it to be
    used as an etag.

    This code needs a __repr__ function in the Password class. This
    replaces the repr(items) which would be:

      <roundup.password.Password instance at 0x7f3442406170>

    with the string representation:

       {PBKDF2}10000$k4d74EDgxlbH...A

    This makes the representation repeatable as the location of the
    password instance is not static and we need a constant value to
    calculate the etag.

    Note that repr() is chosen for the node rather than str() since
    repr is meant to be an unambiguous representation.

    classname and id are used for logging only.
    '''

    items = node.items(protected=True)  # include every item
    etag = hmac.new(bs2b(key), bs2b(repr_format +
                                    repr(sorted(items))), md5).hexdigest()
    logger.debug("object=%s%s; tag=%s; repr=%s", classname, id,
                 etag, repr(node.items(protected=True)))
    # Quotes are part of ETag spec, normal headers don't have quotes
    return '"%s"' % etag


def check_etag(node, key, etags, classname="Missing", id="0",
               repr_format="json"):
    '''Take a list of etags and compare to the etag for the given node.

    Iterate over all supplied etags,
       If a tag fails to match, return False.
       If at least one etag matches, return True.
       If all etags are None, return False.

    '''
    have_etag_match = False

    node_etag = calculate_etag(node, key, classname, id,
                               repr_format=repr_format)

    for etag in etags:
        if etag is not None:
            if etag != node_etag:
                return False
            have_etag_match = True

    if have_etag_match:
        return True
    else:
        return False


def obtain_etags(headers, input):
    '''Get ETags value from headers or payload data'''
    etags = []
    if '@etag' in input:
        etags.append(input['@etag'].value)
    etags.append(headers.get("If-Match", None))
    return etags


def parse_accept_header(accept):
    """
    Parse the Accept header *accept*, returning a list with 3-tuples of
    [(str(media_type), dict(params), float(q_value)),] ordered by q values.

    If the accept header includes vendor-specific types like::
        application/vnd.yourcompany.yourproduct-v1.1+json

    It will actually convert the vendor and version into parameters and
    convert the content type into `application/json` so appropriate content
    negotiation decisions can be made.

    Default `q` for values that are not specified is 1.0

    # Based on https://gist.github.com/samuraisam/2714195
    # Also, based on a snipped found in this project:
    #   https://github.com/martinblech/mimerender
    """
    result = []
    if not accept:
        return result

    for media_range in accept.split(","):
        parts = media_range.split(";")
        media_type = parts.pop(0).strip()
        media_params = []
        # convert vendor-specific content types into something useful (see
        # docstring)
        try:
            typ, subtyp = media_type.split('/')
        except ValueError:
            raise UsageError("Invalid media type: %s"%media_type)
        # check for a + in the sub-type
        if '+' in subtyp:
            # if it exists, determine if the subtype is a vendor-specific type
            vnd, sep, extra = subtyp.partition('+')
            if vnd.startswith('vnd'):
                # and then... if it ends in something like "-v1.1" parse the
                # version out
                if '-v' in vnd:
                    vnd, sep, rest = vnd.rpartition('-v')
                    if len(rest):
                        # add the version as a media param
                        try:
                            media_params.append(('version', rest))
                        except ValueError:
                            pass  # return no version value; use rest default
                # add the vendor code as a media param
                media_params.append(('vendor', vnd))
                # and re-write media_type to something like application/json so
                # it can be used usefully when looking up emitters
                media_type = '{}/{}'.format(typ, extra)
        q = 1.0
        for part in parts:
            try:
                (key, value) = part.lstrip().split("=", 1)
            except ValueError:
                raise UsageError("Invalid param: %s"%part.lstrip())
            key = key.strip()
            value = value.strip()
            if key == "q":
                q = float(value)
                if q > 1.0:
                    # Not sure what to do here. Can't find spec
                    # about how to handle q > 1.0. Since invalid
                    # I choose to make it lowest in priority.
                    q = 0.0001
            else:
                media_params.append((key, value))
        result.append((media_type, dict(media_params), q))
    result.sort(key=lambda x: x[2], reverse=True)
    return result


class Routing(object):
    __route_map = {}
    __var_to_regex = re.compile(r"<:(\w+)>")
    url_to_regex = r"([\\w.\-~!$&'()*+,;=:\%%]+)"

    @classmethod
    def route(cls, rule, methods='GET'):
        """A decorator that is used to register a view function for a
        given URL rule:
            @self.route('/')
            def index():
                return 'Hello World'

        rest/ will be added to the beginning of the url string

        Args:
            rule (string): the URL rule
            methods (string or tuple or list): the http method
        """
        # strip the '/' character from rule string
        rule = rule.strip('/')

        # add 'rest/' to the rule string
        if not rule.startswith('rest/'):
            rule = '^rest/' + rule + '$'

        if isinstance(methods, basestring):  # convert string to tuple
            methods = (methods,)
        methods = set(item.upper() for item in methods)

        # convert a rule to a compiled regex object
        # so /data/<:class>/<:id> will become
        #    /data/([charset]+)/([charset]+)
        # and extract the variable names to a list [(class), (id)]
        func_vars = cls.__var_to_regex.findall(rule)
        rule = re.compile(cls.__var_to_regex.sub(cls.url_to_regex, rule))
        # Save pattern to represent regex in route_map dictionary
        # The entries consist of a 2-tuple of the (rule, dictionary)
        # where rule is the compiled regex and dictionary contains the
        # func_obj dict indexed by method.
        pattern = rule.pattern

        # then we decorate it:
        # route_map[pattern] = (rule, func_dict)
        # where func_dict is a dictionary of func_obj (see below)
        # indexed by method name
        def decorator(func):
            rule_route = cls.__route_map.get(pattern, (rule, {}))
            rule_dict = rule_route[1]
            func_obj = {
                'func': func,
                'vars': func_vars
            }
            for method in methods:
                rule_dict[method] = func_obj
            cls.__route_map[pattern] = rule_route
            return func
        return decorator

    @classmethod
    def execute(cls, instance, path, method, input):
        # format the input, note that we may not lowercase the path
        # here, URL parameters are case-sensitive
        path = path.strip('/')
        if path == 'rest':
            # allow handler to be called for /rest/
            path = 'rest/'
        method = method.upper()

        # find the rule match the path
        # then get handler match the method
        for path_regex, funcs in cls.__route_map.values():
            # use compiled regex to find rule
            match_obj = path_regex.match(path)
            if match_obj:
                try:
                    func_obj = funcs[method]
                except KeyError:
                    raise Reject('Method %s not allowed' % method)

                # retrieve the vars list and the function caller
                list_vars = func_obj['vars']
                func = func_obj['func']

                # zip the varlist into a dictionary, and pass it to the caller
                args = dict(zip(list_vars, match_obj.groups()))
                args['input'] = input
                return func(instance, **args)
        raise NotFound('Nothing matches the given URI')


class RestfulInstance(object):
    """The RestfulInstance performs REST request from the client"""

    __default_patch_op = "replace"  # default operator for PATCH method
    __accepted_content_type = {
        "application/json": "json",
        "*/*": "json",
    }
    __default_accept_type = "json"

    __default_api_version = 1
    __supported_api_versions = [1]

    api_version = None

    def __init__(self, client, db):
        self.client = client
        self.db = db
        self.translator = client.translator
        # record start time for statistics reporting
        self.start = time.time()
        # disable stat reporting by default enable with @stats=True
        # query param
        self.report_stats = False
        # This used to be initialized from client.instance.actions which
        # would include too many actions that do not make sense in the
        # REST-API context, so for now we only permit the retire and
        # restore actions.
        self.actions = dict(retire=actions.Retire, restore=actions.Restore)

        # note TRACKER_WEB ends in a /
        self.base_path = '%srest' % (self.db.config.TRACKER_WEB)
        self.data_path = self.base_path + '/data'

        if dicttoxml:  # add xml if supported
            self.__accepted_content_type["application/xml"] = "xml"

    def props_from_args(self, cl, args, itemid=None, skip_protected=True):
        """Construct a list of properties from the given arguments,
        and return them after validation.

        Args:
            cl (string): class object of the resource
            args (list): the submitted form of the user
            itemid (string, optional): itemid of the object

        Returns:
            dict: dictionary of validated properties excluding
                  protected properties if strip_protected=True.

        Raises: UsageError if property does not exist and is not
           prefixed with @ indicating it's a meta variable.


        """
        unprotected_class_props = cl.properties.keys()
        protected_class_props = [p for p in
                                 list(cl.getprops(protected=True))
                                 if p not in unprotected_class_props]
        props = {}
        # props = dict.fromkeys(class_props, None)

        if not args:
            raise UsageError("No properties found.")

        for arg in args:
            key = arg.name
            value = arg.value
            if key.startswith('@'):
                # meta setting, not db property setting/reference
                continue
            if key in protected_class_props:
                # Skip protected props as a convenience.
                # Allows user to get object with all props,
                # change one prop, submit entire object
                # without having to remove any protected props
                # FIXME: Enhancement: raise error if value of prop
                # doesn't match db entry. In this case assume user
                # is really trying to set value. Another possibility is
                # they have an old copy of the data and it has been
                # updated. In the update case, we want etag validation
                # to generate the exception to reduce confusion. I think
                # etag validation occurs before this function is called but
                # I am not positive.
                if skip_protected:
                    continue
            elif key not in unprotected_class_props:
                # report bad props as this is an error.
                raise UsageError("Property %s not found in class %s" % (key,
                                        cl.classname))  # noqa: E128
            props[key] = self.prop_from_arg(cl, key, value, itemid)

        return props

    def prop_from_arg(self, cl, key, value, itemid=None):
        """Construct a property from the given argument,
        and return them after validation.

        Args:
            cl (string): class object of the resource
            key (string): attribute key
            value (string): attribute value
            itemid (string, optional): itemid of the object

        Returns:
            value: value of validated properties

        """
        prop = None
        if isinstance(key, unicode):
            try:
                key.encode('ascii')  # Check to see if it can be encoded
            except UnicodeEncodeError:
                raise UsageError(
                    'argument %r is not a valid ascii keyword' % key
                )
        if value:
            try:
                prop = hyperdb.rawToHyperdb(self.db, cl, itemid, key, value)
            except hyperdb.HyperdbValueError as msg:
                raise UsageError(msg)

        return prop

    def transitive_props (self, class_name, props):
        """Construct a list of transitive properties from the given
        argument, and return it after permission check. Raises
        Unauthorised if no permission. Permission is checked by
        checking View permission on each component. We do not allow to
        traverse multilinks -- the last item of an expansion *may* be a
        multilink but in the middle of a transitive prop.
        """
        checked_props = []
        uid = self.db.getuid()
        for p in props:
            pn = p
            cn = class_name
            if '.' in p:
                prop = None
                for pn in p.split('.'):
                    # Tried to dereference a non-Link property
                    if cn is None:
                        raise AttributeError("Unknown: %s" % p)
                    cls = self.db.getclass(cn)
                    # This raises a KeyError for unknown prop:
                    try:
                        prop = cls.getprops(protected=True)[pn]
                    except KeyError:
                        raise AttributeError("Unknown: %s" % p)
                    if isinstance(prop, hyperdb.Multilink):
                        raise UsageError(
                            'Multilink Traversal not allowed: %s' % p)
                    # Now we have the classname in cn and the prop name in pn.
                    if not self.db.security.hasPermission('View', uid, cn, pn):
                        raise(Unauthorised
                            ('User does not have permission on "%s.%s"'
                            % (cn, pn)))
                    try:
                        cn = prop.classname
                    except AttributeError:
                        cn = None
            checked_props.append (p)
        return checked_props

    def error_obj(self, status, msg, source=None):
        """Return an error object"""
        self.client.response_code = status
        result = {
            'error': {
                'status': status,
                'msg': msg
            }
        }
        if source is not None:
            result['error']['source'] = source

        return result

    def patch_data(self, op, old_val, new_val):
        """Perform patch operation based on old_val and new_val

        Args:
            op (string): PATCH operation: add, replace, remove
            old_val: old value of the property
            new_val: new value of the property

        Returns:
            result (string): value after performed the operation
        """
        # add operation: If neither of the value is None, use the other one
        #                Otherwise, concat those 2 value
        if op == 'add':
            if old_val is None:
                result = new_val
            elif new_val is None:
                result = old_val
            else:
                result = old_val + new_val
        # Replace operation: new value is returned
        elif op == 'replace':
            result = new_val
        # Remove operation:
        #   if old_val is not a list/dict, change it to None
        #   if old_val is a list/dict, but the parameter is empty,
        #       change it to none
        #   if old_val is a list/dict, and parameter is not empty
        #       proceed to remove the values from parameter from the list/dict
        elif op == 'remove':
            if isinstance(old_val, list):
                if new_val is None:
                    result = []
                elif isinstance(new_val, list):
                    result = [x for x in old_val if x not in new_val]
                else:
                    if new_val in old_val:
                        old_val.remove(new_val)
            elif isinstance(old_val, dict):
                if new_val is None:
                    result = {}
                elif isinstance(new_val, dict):
                    for x in new_val:
                        old_val.pop(x, None)
                else:
                    old_val.pop(new_val, None)
            else:
                result = None
        else:
            raise UsageError('PATCH Operation %s is not allowed' % op)

        return result

    def raise_if_no_etag(self, class_name, item_id, input, repr_format="json"):
        class_obj = self.db.getclass(class_name)
        if not check_etag(class_obj.getnode(item_id),
                          self.db.config.WEB_SECRET_KEY,
                          obtain_etags(self.client.request.headers, input),
                          class_name,
                          item_id, repr_format=repr_format):
            raise PreconditionFailed(
                "If-Match is missing or does not match."
                " Retrieve asset and retry modification if valid.")

    def format_item(self, node, item_id, props=None, verbose=1):
        ''' display class obj as requested by verbose and
            props.
        '''
        uid = self.db.getuid()
        class_name = node.cl.classname

        # version never gets used since we only
        # support version 1 at this time. Set it as
        # placeholder for later use.
        if self.api_version is None:
            version = self.__default_api_version  # noqa: F841
        else:
            version = self.api_version  # noqa: F841

        result = {}
        try:
            # pn = propname
            for pn in sorted(props):
                ok = False
                id = item_id
                nd = node
                cn = class_name
                for p in pn.split('.'):
                    if not self.db.security.hasPermission(
                            'View', uid, cn, p, id
                    ):
                        break
                    cl = self.db.getclass(cn)
                    nd = cl.getnode(id)
                    id = v = getattr(nd, p)
                    # Handle transitive properties where something on
                    # the road is None (empty Link property)
                    if id is None :
                        prop = None
                        ok = True
                        break
                    prop = cl.getprops(protected=True)[p]
                    cn = getattr(prop, 'classname', None)
                else:
                    ok = True
                if not ok:
                    continue
                if isinstance(prop, (hyperdb.Link, hyperdb.Multilink)):
                    linkcls = self.db.getclass(prop.classname)
                    cp = '%s/%s/' % (self.data_path, prop.classname)
                    if verbose and v:
                        if isinstance(v, type([])):
                            r = []
                            for id in v:
                                d = dict(id=id, link=cp + id)
                                if verbose > 1:
                                    label = linkcls.labelprop()
                                    d[label] = linkcls.get(id, label)
                                r.append(d)
                            result[pn] = r
                        else:
                            result[pn] = dict(id=v, link=cp + v)
                            if verbose > 1:
                                label = linkcls.labelprop()
                                result[pn][label] = linkcls.get(v, label)
                    else:
                        result[pn] = v
                elif isinstance(prop, hyperdb.String) and pn == 'content':
                    # Do not show the (possibly HUGE) content prop
                    # unless very verbose, we display the standard
                    # download link instead
                    if verbose < 3:
                        u = self.db.config.TRACKER_WEB
                        p = u + '%s%s/' % (class_name, node.id)
                        result[pn] = dict(link=p)
                    else:
                        result[pn] = v
                elif isinstance(prop, hyperdb.Password):
                    if v is not None:  # locked users like anonymous have None
                        result[pn] = "[password hidden scheme %s]" % v.scheme
                    else:
                        # Don't divulge it's a locked account. Choose most
                        # secure as default.
                        result[pn] = "[password hidden scheme PBKDF2]"
                else:
                    result[pn] = v
        except KeyError as msg:
            raise UsageError("%s field not valid" % msg)

        return result

    @Routing.route("/data/<:class_name>", 'GET')
    @_data_decorator
    def get_collection(self, class_name, input):
        """GET resource from class URI.

        This function returns only items have View permission
        class_name should be valid already

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            list: list of reference item in the class
                id: id of the object
                link: path to the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)

        uid = self.db.getuid()

        if not self.db.security.hasPermission('View', uid, class_name):
            raise Unauthorised('Permission to view %s denied' % class_name)

        class_obj = self.db.getclass(class_name)
        class_path = '%s/%s/' % (self.data_path, class_name)

        # Handle filtering and pagination
        filter_props = {}
        exact_props = {}
        page = {
            'size': None,
            'index': 1   # setting just size starts at page 1
        }
        verbose = 1
        display_props = set()
        sort = []
        for form_field in input.value:
            key = form_field.name
            value = form_field.value
            if key.startswith("@page_"):  # serve the paging purpose
                key = key[6:]
                value = int(value)
                page[key] = value
            elif key == "@verbose":
                verbose = int(value)
            elif key == "@fields" or key == "@attrs":
                f = value.split(",")
                if len(f) == 1:
                    f = value.split(":")
                allprops = class_obj.getprops(protected=True)
                display_props.update(self.transitive_props(class_name, f))
            elif key == "@sort":
                f = value.split(",")
                allprops = class_obj.getprops(protected=True)
                for p in f:
                    if not p:
                        raise UsageError("Empty property "
                                         "for class %s." % (class_name))
                    if p[0] in ('-', '+'):
                        pn = p[1:]
                        ss = p[0]
                    else:
                        ss = '+'
                        pn = p
                    # Only include properties where we have search permission
                    # Note that hasSearchPermission already returns 0 for
                    # non-existing properties.
                    if self.db.security.hasSearchPermission(
                        uid, class_name, pn
                    ):
                        sort.append((ss, pn))
                    else :
                        raise (Unauthorised(
                            'User does not have search permission on "%s.%s"'
                            % (class_name, pn)))
            elif key.startswith("@"):
                # ignore any unsupported/previously handled control key
                # like @apiver
                pass
            else:  # serve the filter purpose
                exact = False
                if key.endswith(':'):
                    exact = True
                    key = key[:-1]
                elif key.endswith('~'):
                    key = key[:-1]
                p = key.split('.', 1)[0]
                try:
                    prop = class_obj.getprops()[p]
                except KeyError:
                    raise UsageError("Field %s is not valid for %s class." %
                                     (p, class_name))
                # We drop properties without search permission silently
                # This reflects the current behavior of other roundup
                # interfaces
                # Note that hasSearchPermission already returns 0 for
                # non-existing properties.
                if not self.db.security.hasSearchPermission(
                    uid, class_name, key
                ):
                    raise (Unauthorised(
                        'User does not have search permission on "%s.%s"'
                        % (class_name, key)))

                linkcls = class_obj
                for p in key.split('.'):
                    prop = linkcls.getprops(protected=True)[p]
                    linkcls = getattr(prop, 'classname', None)
                    if linkcls:
                        linkcls = self.db.getclass(linkcls)

                if isinstance(prop, (hyperdb.Link, hyperdb.Multilink)):
                    if key in filter_props:
                        vals = filter_props[key]
                    else:
                        vals = []
                    for p in value.split(","):
                        dig = p and p.isdigit() or \
                            (p[0] in ('-', '+') and p[1:].isdigit())
                        if prop.try_id_parsing and dig:
                            vals.append(p)
                        else:
                            vals.append(linkcls.lookup(p))
                    filter_props[key] = vals
                else:
                    if not isinstance(prop, hyperdb.String):
                        exact = False
                    props = filter_props
                    if exact:
                        props = exact_props
                    if key in props:
                        if isinstance(props[key], list):
                            props[key].append(value)
                        else:
                            props[key] = [props[key], value]
                    else:
                        props[key] = value
        l = [filter_props]  # noqa: E741
        kw = {}
        if sort:
            l.append(sort)
        if exact_props:
            kw['exact_match_spec'] = exact_props
        if page['size'] is not None and page['size'] > 0:
            kw['limit'] = page['size']
            if page['index'] is not None and page['index'] > 1:
                kw['offset'] = (page['index'] - 1) * page['size']
        obj_list = class_obj.filter(None, *l, **kw)

        # Note: We don't sort explicitly in python. The filter implementation
        # of the DB already sorts by ID if no sort option was given.

        # add verbose elements. 2 and above get identifying label.
        if verbose > 1:
            lp = class_obj.labelprop()
            display_props.add(lp)

        # extract result from data
        result = {}
        result['collection'] = []
        for item_id in obj_list:
            r = {}
            if self.db.security.hasPermission(
                'View', uid, class_name, itemid=item_id, property='id'
            ):
                r = {'id': item_id, 'link': class_path + item_id}
            if display_props:
                # format_item does the permission checks
                r.update(self.format_item(class_obj.getnode(item_id),
                    item_id, props=display_props, verbose=verbose))
            if r:
                result['collection'].append(r)

        result_len = len(result['collection'])

        # pagination - page_index from 1...N
        if page['size'] is not None and page['size'] > 0:
            result['@links'] = {}
            for rel in ('next', 'prev', 'self'):
                if rel == 'next':
                    # if current index includes all data, continue
                    if page['size'] > result_len: continue  # noqa: E701
                    index = page['index']+1
                if rel == 'prev':
                    if page['index'] <= 1: continue  # noqa: E701
                    index = page['index'] - 1
                if rel == 'self': index = page['index']  # noqa: E701

                result['@links'][rel] = []
                result['@links'][rel].append({
                    'rel': rel,
                    'uri': "%s/%s?@page_index=%s&" % (self.data_path,
                                                      class_name, index) +
                           '&'.join(["%s=%s" % (field.name, field.value)
                                     for field in input.value
                                     if field.name != "@page_index"])})

        result['@total_size'] = result_len
        self.client.setHeader("X-Count-Total", str(result_len))
        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>", 'GET')
    @_data_decorator
    def get_element(self, class_name, item_id, input):
        """GET resource from object URI.

        This function returns only properties have View permission
        class_name and item_id should be valid already

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
                or (if the class has a key property) this can also be
                the key name, e.g. class_name = status, item_id = 'open'
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict: a dictionary represents the object
                id: id of the object
                type: class name of the object
                link: link to the object
                attributes: a dictionary represent the attributes of the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        class_obj = self.db.getclass(class_name)
        uid = self.db.getuid()
        # If it's not numeric it is a key
        if item_id.isdigit():
            itemid = item_id
        else:
            keyprop = class_obj.getkey()
            try:
                k, v = item_id.split('=', 1)
                if k != keyprop:
                    raise UsageError("Field %s is not key property" % k)
            except ValueError:
                v = item_id
            if not self.db.security.hasPermission(
                'View', uid, class_name, itemid=item_id, property=keyprop
            ):
                raise Unauthorised(
                    'Permission to view %s%s.%s denied'
                    % (class_name, item_id, keyprop)
                )
            itemid = class_obj.lookup(v)
        if not self.db.security.hasPermission(
            'View', uid, class_name, itemid=itemid
        ):
            raise Unauthorised(
                'Permission to view %s%s denied' % (class_name, itemid)
            )

        node = class_obj.getnode(itemid)
        etag = calculate_etag(node, self.db.config.WEB_SECRET_KEY,
                              class_name, itemid, repr_format="json")
        props = None
        protected = False
        verbose = 1
        for form_field in input.value:
            key = form_field.name
            value = form_field.value
            if key == "@fields" or key == "@attrs":
                if props is None:
                    props = set()
                # support , or : separated elements
                f = value.split(",")
                if len(f) == 1:
                    f = value.split(":")
                allprops = class_obj.getprops(protected=True)
                props.update(self.transitive_props(class_name, f))
            elif key == "@protected":
                # allow client to request read only
                # properties like creator, activity etc.
                # used only if no @fields/@attrs
                protected = value.lower() == "true"
            elif key == "@verbose":
                verbose = int(value)

        result = {}
        if props is None:
            props = set(class_obj.getprops(protected=protected))
        else:
            if verbose > 1:
                lp = class_obj.labelprop()
                props.add(lp)

        result = {
            'id': itemid,
            'type': class_name,
            'link': '%s/%s/%s' % (self.data_path, class_name, item_id),
            'attributes': self.format_item(node, itemid, props=props,
                                           verbose=verbose),
            '@etag': etag
        }

        self.client.setHeader("ETag", etag)
        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>/<:attr_name>", 'GET')
    @_data_decorator
    def get_attribute(self, class_name, item_id, attr_name, input):
        """GET resource from attribute URI.

        This function returns only attribute has View permission
        class_name should be valid already

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            attr_name (string): attribute of the resource (Ex: title, nosy)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            list: a dictionary represents the attribute
                id: id of the object
                type: class name of the attribute
                link: link to the attribute
                data: data of the requested attribute
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'View', self.db.getuid(), class_name, attr_name, item_id
        ):
            raise Unauthorised(
                'Permission to view %s%s %s denied' %
                (class_name, item_id, attr_name)
            )

        class_obj = self.db.getclass(class_name)
        node = class_obj.getnode(item_id)
        etag = calculate_etag(node, self.db.config.WEB_SECRET_KEY,
                              class_name, item_id,  repr_format="json")
        data = node.__getattr__(attr_name)
        result = {
            'id': item_id,
            'type': str(type(data)),
            'link': "%s/%s/%s/%s" %
                    (self.data_path, class_name, item_id, attr_name),
            'data': data,
            '@etag': etag
        }

        self.client.setHeader("ETag", etag)
        return 200, result

    @Routing.route("/data/<:class_name>", 'POST')
    @_data_decorator
    def post_collection(self, class_name, input):
        """POST a new object to a class

        If the item is successfully created, the "Location" header will also
        contain the link to the created object

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            input (list): the submitted form of the user

        Returns:
            int: http status code 201 (Created)
            dict: a reference item to the created object
                id: id of the object
                link: path to the object
        """
        return self.post_collection_inner(class_name, input)

    @Routing.route("/data/<:class_name>/@poe", 'POST')
    @_data_decorator
    def get_post_once_exactly(self, class_name, input):
        """Get the Post Once Exactly token to create a new instance of class
           See https://tools.ietf.org/html/draft-nottingham-http-poe-00"""
        otks = self.db.Otk
        poe_key = ''.join([random_.choice(chars) for x in range(40)])
        while otks.exists(u2s(poe_key)):
            poe_key = ''.join([random_.choice(chars) for x in range(40)])

        try:
            lifetime = int(input['lifetime'].value)
        except KeyError:
            lifetime = 30 * 60  # 30 minutes
        except ValueError:
            raise UsageError("Value 'lifetime' must be an integer specify lifetime in seconds. Got %s." % input['lifetime'].value)

        if lifetime > 3600 or lifetime < 1:
            raise UsageError("Value 'lifetime' must be between 1 second and 1 hour (3600 seconds). Got %s." % input['lifetime'].value)

        try:
            # if generic tag exists, we don't care about the value
            is_generic = input['generic']
            # we generate a generic POE token
            is_generic = True
        except KeyError:
            is_generic = False

        # a POE must be used within lifetime (30 minutes default).
        # Default OTK lifetime is 1 week. So to make different
        # lifetime, take current time, subtract 1 week and add
        # lifetime.
        ts = time.time() - (60 * 60 * 24 * 7) + lifetime
        if is_generic:
            otks.set(u2s(poe_key), uid=self.db.getuid(),
                     __timestamp=ts)
        else:
            otks.set(u2s(poe_key), uid=self.db.getuid(),
                     class_name=class_name,
                     __timestamp=ts)
        otks.commit()

        return 200, {'link': '%s/%s/@poe/%s' %
                     (self.data_path, class_name, poe_key),
                     'expires': ts + (60 * 60 * 24 * 7)}

    @Routing.route("/data/<:class_name>/@poe/<:post_token>", 'POST')
    @_data_decorator
    def post_once_exactly_collection(self, class_name, post_token, input):
        """Post exactly one to the resource named by class_name"""
        otks = self.db.Otk

        # remove expired keys so we don't use an expired key
        otks.clean()

        if not otks.exists(u2s(post_token)):
            # Don't log this failure. Would allow attackers to fill
            # logs.
            raise UsageError("POE token '%s' not valid." % post_token)

        # find out what user owns the key
        user = otks.get(u2s(post_token), 'uid', default=None)
        # find out what class it was meant for
        cn = otks.get(u2s(post_token), 'class_name', default=None)

        # Invalidate the key as it has been used.
        otks.destroy(u2s(post_token))
        otks.commit()

        # verify the same user that requested the key is the user
        # using the key.
        if user != self.db.getuid():
            # Tell the roundup admin that there is an issue
            # as the key got compromised.
            logger.warning(
                'Post Once key owned by user%s was denied. Used by user%s', user, self.db.getuid()
            )
            # Should we indicate to user that the token is invalid
            # because they are not the user who owns the key? It could
            # be a logic bug in the application. But I assume that
            # the key has been stolen and we don't want to tip our hand.
            raise UsageError("POE token '%s' not valid." % post_token)

        if cn != class_name and cn is not None:
            raise UsageError("POE token '%s' not valid for %s, was generated for class %s" % (post_token, class_name, cn))

        # handle this as though they POSTed to /rest/data/class
        return self.post_collection_inner(class_name, input)

    def post_collection_inner(self, class_name, input):
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'Create', self.db.getuid(), class_name
        ):
            raise Unauthorised('Permission to create %s denied' % class_name)

        class_obj = self.db.getclass(class_name)

        # convert types
        props = self.props_from_args(class_obj, input.value)

        # check for the key property
        key = class_obj.getkey()
        if key and key not in props:
            raise UsageError("Must provide the '%s' property." % key)

        for key in props:
            if not self.db.security.hasPermission(
                'Create', self.db.getuid(), class_name, property=key
            ):
                raise Unauthorised(
                    'Permission to create %s.%s denied' % (class_name, key)
                )

        # do the actual create
        try:
            item_id = class_obj.create(**props)
            self.db.commit()
        except (TypeError, IndexError, ValueError) as message:
            raise ValueError(message)
        except KeyError as msg:
            raise UsageError("Must provide the %s property." % msg)

        # set the header Location
        link = '%s/%s/%s' % (self.data_path, class_name, item_id)
        self.client.setHeader("Location", link)

        # set the response body
        result = {
            'id': item_id,
            'link': link
        }
        return 201, result

    @Routing.route("/data/<:class_name>/<:item_id>", 'PUT')
    @_data_decorator
    def put_element(self, class_name, item_id, input):
        """PUT a new content to an object

        Replace the content of the existing object

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict: a dictionary represents the modified object
                id: id of the object
                type: class name of the object
                link: link to the object
                attributes: a dictionary represent only changed attributes of
                            the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        class_obj = self.db.getclass(class_name)

        props = self.props_from_args(class_obj, input.value, item_id)
        for p in props:
            if not self.db.security.hasPermission(
                'Edit', self.db.getuid(), class_name, p, item_id
            ):
                raise Unauthorised(
                    'Permission to edit %s of %s%s denied' %
                    (p, class_name, item_id)
                )
        try:
            self.raise_if_no_etag(class_name, item_id, input)
            result = class_obj.set(item_id, **props)
            self.db.commit()
        except (TypeError, IndexError, ValueError) as message:
            raise ValueError(message)
        except KeyError as message:
            # key error returned for changing protected keys
            # and changing invalid keys
            raise UsageError(message)

        result = {
            'id': item_id,
            'type': class_name,
            'link': '%s/%s/%s' % (self.data_path, class_name, item_id),
            'attribute': result
        }
        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>/<:attr_name>", 'PUT')
    @_data_decorator
    def put_attribute(self, class_name, item_id, attr_name, input):
        """PUT an attribute to an object

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            attr_name (string): attribute of the resource (Ex: title, nosy)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict:a dictionary represents the modified object
                id: id of the object
                type: class name of the object
                link: link to the object
                attributes: a dictionary represent only changed attributes of
                            the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'Edit', self.db.getuid(), class_name, attr_name, item_id
        ):
            raise Unauthorised(
                'Permission to edit %s%s %s denied' %
                (class_name, item_id, attr_name)
            )
        class_obj = self.db.getclass(class_name)
        props = {
            attr_name: self.prop_from_arg(
                class_obj, attr_name, input['data'].value, item_id
            )
        }

        try:
            self.raise_if_no_etag(class_name, item_id, input)
            result = class_obj.set(item_id, **props)
            self.db.commit()
        except (TypeError, IndexError, ValueError) as message:
            raise ValueError(message)
        except KeyError as message:
            # key error returned for changing protected keys
            # and changing invalid keys
            raise AttributeError(message)

        result = {
            'id': item_id,
            'type': class_name,
            'link': '%s/%s/%s' % (self.data_path, class_name, item_id),
            'attribute': result
        }

        return 200, result

    @Routing.route("/data/<:class_name>", 'DELETE')
    @_data_decorator
    def delete_collection(self, class_name, input):
        """DELETE (retire) all objects in a class
           There is currently no use-case, so this is disabled and
           always returns Unauthorised.

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict:
                status (string): 'ok'
                count (int): number of deleted objects
        """
        raise Unauthorised('Deletion of a whole class disabled')
        ''' Hide original code to silence pylint.
            Leave it here in case we need to re-enable.
            FIXME: Delete in December 2020 if not used.
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'Retire', self.db.getuid(), class_name
        ):
            raise Unauthorised('Permission to delete %s denied' % class_name)

        class_obj = self.db.getclass(class_name)
        for item_id in class_obj.list():
            if not self.db.security.hasPermission(
                'Retire', self.db.getuid(), class_name, itemid=item_id
            ):
                raise Unauthorised(
                    'Permission to retire %s %s denied' % (class_name, item_id)
                )

        count = len(class_obj.list())
        for item_id in class_obj.list():
            class_obj.retire (item_id)

        self.db.commit()
        result = {
            'status': 'ok',
            'count': count
        }

        return 200, result
        '''

    @Routing.route("/data/<:class_name>/<:item_id>", 'DELETE')
    @_data_decorator
    def delete_element(self, class_name, item_id, input):
        """DELETE (retire) an object in a class

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict:
                status (string): 'ok'
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        class_obj = self.db.classes[class_name]
        if not self.db.security.hasPermission(
            'Retire', self.db.getuid(), class_name, itemid=item_id
        ):
            raise Unauthorised(
                'Permission to retire %s %s denied' % (class_name, item_id)
            )

        self.raise_if_no_etag(class_name, item_id, input)
        class_obj.retire(item_id)
        self.db.commit()
        result = {
            'status': 'ok'
        }

        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>/<:attr_name>", 'DELETE')
    @_data_decorator
    def delete_attribute(self, class_name, item_id, attr_name, input):
        """DELETE an attribute in a object by setting it to None or empty

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            attr_name (string): attribute of the resource (Ex: title, nosy)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict:
                status (string): 'ok'
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        if not self.db.security.hasPermission(
            'Edit', self.db.getuid(), class_name, attr_name, item_id
        ):
            raise Unauthorised(
                'Permission to delete %s%s %s denied' %
                (class_name, item_id, attr_name)
            )

        class_obj = self.db.getclass(class_name)
        if attr_name not in class_obj.getprops(protected=False):
            if attr_name in class_obj.getprops(protected=True):
                raise AttributeError("Attribute '%s' can not be deleted "
                                     "for class %s." % (attr_name, class_name))
            else:
                raise UsageError("Attribute '%s' not valid for class %s." % (
                    attr_name, class_name))
        if attr_name in class_obj.get_required_props():
            raise UsageError("Attribute '%s' is required by class %s and can not be deleted." % (
                attr_name, class_name))
        props = {}
        prop_obj = class_obj.get(item_id, attr_name)
        if isinstance(prop_obj, list):
            props[attr_name] = []
        else:
            props[attr_name] = None

        try:
            self.raise_if_no_etag(class_name, item_id, input)
            class_obj.set(item_id, **props)
            self.db.commit()
        except (TypeError, IndexError, ValueError) as message:
            raise ValueError(message)
        except KeyError as message:
            # key error returned for changing protected keys
            # and changing invalid keys
            raise UsageError(message)

        result = {
            'status': 'ok'
        }

        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>", 'PATCH')
    @_data_decorator
    def patch_element(self, class_name, item_id, input):
        """PATCH an object

        Patch an element using 3 operators
        ADD : Append new value to the object's attribute
        REPLACE: Replace object's attribute
        REMOVE: Clear object's attribute

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict: a dictionary represents the modified object
                id: id of the object
                type: class name of the object
                link: link to the object
                attributes: a dictionary represent only changed attributes of
                            the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        try:
            op = input['@op'].value.lower()
        except KeyError:
            op = self.__default_patch_op
        class_obj = self.db.getclass(class_name)

        self.raise_if_no_etag(class_name, item_id, input)

        # if patch operation is action, call the action handler
        action_args = [class_name + item_id]
        if op == 'action':
            # extract action_name and action_args from form fields
            name = None
            for form_field in input.value:
                key = form_field.name
                value = form_field.value
                if key == "@action_name":
                    name = value
                elif key.startswith('@action_args'):
                    action_args.append(value)

            if name in self.actions:
                action_type = self.actions[name]
            else:
                raise UsageError(
                    'action "%s" is not supported, allowed: %s' %
                    (name, ', '.join(self.actions.keys()))
                )
            action = action_type(self.db, self.translator)
            result = action.execute(*action_args)

            result = {
                'id': item_id,
                'type': class_name,
                'link': '%s/%s/%s' % (self.data_path, class_name, item_id),
                'result': result
            }
        else:
            # else patch operation is processing data
            props = self.props_from_args(class_obj, input.value, item_id,
                                         skip_protected=False)

            required_props = class_obj.get_required_props()
            for prop in props:
                if not self.db.security.hasPermission(
                    'Edit', self.db.getuid(), class_name, prop, item_id
                ):
                    raise Unauthorised(
                        'Permission to edit %s of %s%s denied' %
                        (prop, class_name, item_id)
                    )
                if op == 'remove' and prop in required_props:
                    raise UsageError(
                        "Attribute '%s' is required by class %s "
                        "and can not be removed." % (prop, class_name)
                    )

                props[prop] = self.patch_data(
                    op, class_obj.get(item_id, prop), props[prop]
                )

            try:
                result = class_obj.set(item_id, **props)
                self.db.commit()
            except (TypeError, IndexError, ValueError) as message:
                raise ValueError(message)

            result = {
                'id': item_id,
                'type': class_name,
                'link': '%s/%s/%s' % (self.data_path, class_name, item_id),
                'attribute': result
            }
        return 200, result

    @Routing.route("/data/<:class_name>/<:item_id>/<:attr_name>", 'PATCH')
    @_data_decorator
    def patch_attribute(self, class_name, item_id, attr_name, input):
        """PATCH an attribute of an object

        Patch an element using 3 operators
        ADD : Append new value to the attribute
        REPLACE: Replace attribute
        REMOVE: Clear attribute

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            item_id (string): id of the resource (Ex: 12, 15)
            attr_name (string): attribute of the resource (Ex: title, nosy)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            dict: a dictionary represents the modified object
                id: id of the object
                type: class name of the object
                link: link to the object
                attributes: a dictionary represent only changed attributes of
                            the object
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        try:
            op = input['@op'].value.lower()
        except KeyError:
            op = self.__default_patch_op

        if not self.db.security.hasPermission(
            'Edit', self.db.getuid(), class_name, attr_name, item_id
        ):
            raise Unauthorised(
                'Permission to edit %s%s %s denied' %
                (class_name, item_id, attr_name)
            )

        prop = attr_name
        class_obj = self.db.getclass(class_name)
        if attr_name not in class_obj.getprops(protected=False):
            if attr_name in class_obj.getprops(protected=True):
                raise AttributeError("Attribute '%s' can not be updated "
                                     "for class %s." % (attr_name, class_name))

        self.raise_if_no_etag(class_name, item_id, input)

        props = {
            prop: self.prop_from_arg(
                class_obj, prop, input['data'].value, item_id
            )
        }

        props[prop] = self.patch_data(
            op, class_obj.get(item_id, prop), props[prop]
        )

        try:
            result = class_obj.set(item_id, **props)
            self.db.commit()
        except (TypeError, IndexError, ValueError) as message:
            raise ValueError(message)
        except KeyError as message:
            # key error returned for changing protected keys
            # and changing invalid keys
            raise UsageError(message)

        result = {
            'id': item_id,
            'type': class_name,
            'link': '%s/%s/%s' % (self.data_path, class_name, item_id),
            'attribute': result
        }
        return 200, result

    @Routing.route("/data/<:class_name>", 'OPTIONS')
    @_data_decorator
    def options_collection(self, class_name, input):
        """OPTION return the HTTP Header for the class uri

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        self.client.setHeader(
            "Allow",
            "OPTIONS, GET, POST"
        )
        return 204, ""

    @Routing.route("/data/<:class_name>/<:item_id>", 'OPTIONS')
    @_data_decorator
    def options_element(self, class_name, item_id, input):
        """OPTION return the HTTP Header for the object uri

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        self.client.setHeader(
            "Accept-Patch",
            "application/x-www-form-urlencoded, multipart/form-data"
        )
        self.client.setHeader(
            "Allow",
            "OPTIONS, GET, PUT, DELETE, PATCH"
        )
        return 204, ""

    @Routing.route("/data/<:class_name>/<:item_id>/<:attr_name>", 'OPTIONS')
    @_data_decorator
    def option_attribute(self, class_name, item_id, attr_name, input):
        """OPTION return the HTTP Header for the attribute uri

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        if class_name not in self.db.classes:
            raise NotFound('Class %s not found' % class_name)
        class_obj = self.db.getclass(class_name)
        if attr_name in class_obj.getprops(protected=False):
            self.client.setHeader(
                "Accept-Patch",
                "application/x-www-form-urlencoded, multipart/form-data"
            )
            self.client.setHeader(
                "Allow",
                "OPTIONS, GET, PUT, DELETE, PATCH"
            )
        elif attr_name in class_obj.getprops(protected=True):
            # It must match a protected prop. These can't be written.
            self.client.setHeader(
                "Allow",
                "OPTIONS, GET"
            )
        else:
            raise NotFound('Attribute %s not valid for Class %s' % (
                attr_name, class_name))
        return 204, ""

    @Routing.route("/")
    @_data_decorator
    def describe(self, input):
        """Describe the rest endpoint"""
        result = {
            "default_version": self.__default_api_version,
            "supported_versions": self.__supported_api_versions,
            "links": [{"uri": self.base_path + "/summary",
                       "rel": "summary"},
                      {"uri": self.base_path,
                       "rel": "self"},
                      {"uri": self.base_path + "/data",
                       "rel": "data"}]
        }

        return 200, result

    @Routing.route("/", 'OPTIONS')
    @_data_decorator
    def options_describe(self, input):
        """OPTION return the HTTP Header for the root

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        self.client.setHeader(
            "Allow",
            "OPTIONS, GET"
        )
        return 204, ""

    @Routing.route("/data")
    @_data_decorator
    def data(self, input):
        """Describe the subelements of data

           One entry for each class the user may view
        """
        result = {}
        uid = self.db.getuid()
        for cls in sorted(self.db.classes):
            if self.db.security.hasPermission('View', uid, cls):
                result[cls] = dict(link=self.base_path + '/data/' + cls)
        return 200, result

    @Routing.route("/data", 'OPTIONS')
    @_data_decorator
    def options_data(self, input):
        """OPTION return the HTTP Header for the /data element

        Returns:
            int: http status code 204 (No content)
            body (string): an empty string
        """
        self.client.setHeader(
            "Allow",
            "OPTIONS, GET"
        )
        return 204, ""

    @Routing.route("/summary")
    @_data_decorator
    def summary(self, input):
        """Get a summary of resource from class URI.

        This function returns only items have View permission
        class_name should be valid already

        Args:
            class_name (string): class name of the resource (Ex: issue, msg)
            input (list): the submitted form of the user

        Returns:
            int: http status code 200 (OK)
            list:
        """
        if not self.db.security.hasPermission(
            'View', self.db.getuid(), 'issue'
        ) and not self.db.security.hasPermission(
            'View', self.db.getuid(), 'status'
        ) and not self.db.security.hasPermission(
            'View', self.db.getuid(), 'issue'
        ):
            raise Unauthorised('Permission to view summary denied')

        old = date.Date('-1w')

        created = []
        summary = {}
        messages = []

        # loop through all the recently-active issues
        for issue_id in self.db.issue.filter(None, {'activity': '-1w;'}):
            num = 0
            status_name = self.db.status.get(
                self.db.issue.get(issue_id, 'status'),
                'name'
            )
            issue_object = {
                'id': issue_id,
                'link': self.base_path + '/data/issue/' + issue_id,
                'title': self.db.issue.get(issue_id, 'title')
            }
            for _x, ts, _uid, action, data in self.db.issue.history(issue_id):
                if ts < old:
                    continue
                if action == 'create':
                    created.append(issue_object)
                elif action == 'set' and 'messages' in data:
                    num += 1
            summary.setdefault(status_name, []).append(issue_object)
            messages.append((num, issue_object))

        sorted(messages, key=lambda tup: tup[0], reverse=True)

        result = {
            'created': created,
            'summary': summary,
            'most_discussed': messages[:10]
        }

        return 200, result

    def getRateLimit(self):
        ''' By default set one rate limit for all users. Values
            for period (in seconds) and count set in config.
            However there is no reason these settings couldn't
            be pulled from the user's entry in the database. So define
            this method to allow a user to change it in the interfaces.py
            to use a field in the user object.
        '''
        # FIXME verify can override from interfaces.py.
        calls = self.db.config.WEB_API_CALLS_PER_INTERVAL
        interval = self.db.config.WEB_API_INTERVAL_IN_SEC
        if calls and interval:
            return RateLimit(calls, timedelta(seconds=interval))
        else:
            # disable rate limiting if either parameter is 0
            return None

    def dispatch(self, method, uri, input):
        """format and process the request"""
        output = None

        # Before we do anything has the user hit the rate limit.
        # This should (but doesn't at the moment) bypass
        # all other processing to minimize load of badly
        # behaving client.

        # Get the limit here and not in the init() routine to allow
        # for a different rate limit per user.
        apiRateLimit = self.getRateLimit()

        if apiRateLimit:  # if None, disable rate limiting
            gcra = Gcra()
            # unique key is an "ApiLimit-" prefix and the uid)
            apiLimitKey = "ApiLimit-%s" % self.db.getuid()
            otk = self.db.Otk
            try:
                val = otk.getall(apiLimitKey)
                gcra.set_tat_as_string(apiLimitKey, val['tat'])
            except KeyError:
                # ignore if tat not set, it's 1970-1-1 by default.
                pass
            # see if rate limit exceeded and we need to reject the attempt
            reject = gcra.update(apiLimitKey, apiRateLimit)

            # Calculate a timestamp that will make OTK expire the
            # unused entry 1 hour in the future
            ts = time.time() - (60 * 60 * 24 * 7) + 3600
            otk.set(apiLimitKey, tat=gcra.get_tat_as_string(apiLimitKey),
                    __timestamp=ts)
            otk.commit()

            limitStatus = gcra.status(apiLimitKey, apiRateLimit)
            if reject:
                for header, value in limitStatus.items():
                    self.client.setHeader(header, value)
                    # User exceeded limits: tell humans how long to wait
                    # Headers above will do the right thing for api
                    # aware clients.
                    msg = _("Api rate limits exceeded. Please wait: %s seconds.") % limitStatus['Retry-After']
                    output = self.error_obj(429, msg, source="ApiRateLimiter")
            else:
                for header, value in limitStatus.items():
                    # Retry-After will be 0 because
                    # user still has quota available.
                    # Don't put out the header.
                    if header in ('Retry-After',):
                        continue
                    self.client.setHeader(header, value)

        # if X-HTTP-Method-Override is set, follow the override method
        headers = self.client.request.headers
        # Never allow GET to be an unsafe operation (i.e. data changing).
        # User must use POST to "tunnel" DELETE, PUT, OPTIONS etc.
        override = headers.get('X-HTTP-Method-Override')
        if override:
            if method.upper() == 'POST':
                logger.debug(
                    'Method overridden from %s to %s', method, override)
                method = override
            else:
                output = self.error_obj(400,
                       "X-HTTP-Method-Override: %s must be used with "
                       "POST method not %s." % (override, method.upper()))
                logger.info(
                    'Ignoring X-HTTP-Method-Override using %s request on %s',
                    method.upper(), uri)

        # parse Accept header and get the content type
        # Acceptable types ordered with preferred one first
        # in list.
        try:
            accept_header = parse_accept_header(headers.get('Accept'))
        except UsageError as e:
            output = self.error_obj(406, _("Unable to parse Accept Header. %(error)s. "
                      "Acceptable types: %(acceptable_types)s") % {
                          'error': e.args[0],
                          'acceptable_types': " ".join(sorted(self.__accepted_content_type.keys()))})
            accept_header = []

        if not accept_header:
            accept_type = self.__default_accept_type
        else:
            accept_type = None
        for part in accept_header:
            if accept_type:
                # we accepted the best match, stop searching for
                # lower quality matches.
                break
            if part[0] in self.__accepted_content_type:
                accept_type = self.__accepted_content_type[part[0]]
                # Version order:
                #  1) accept header version=X specifier
                #     application/vnd.x.y; version=1
                #  2) from type in accept-header type/subtype-vX
                #     application/vnd.x.y-v1
                #  3) from @apiver in query string to make browser
                #     use easy
                # This code handles 1 and 2. Set api_version to none
                # to trigger @apiver parsing below
                # Places that need the api_version info should
                # use default if version = None
                try:
                    self.api_version = int(part[1]['version'])
                except KeyError:
                    self.api_version = None
                except (ValueError, TypeError):
                    # TypeError if int(None)
                    msg = ("Unrecognized version: %s. "
                           "See /rest without specifying version "
                           "for supported versions." % (
                               part[1]['version']))
                    output = self.error_obj(400, msg)

        # get the request format for response
        # priority : extension from uri (/rest/data/issue.json),
        #            header (Accept: application/json, application/xml)
        #            default (application/json)
        ext_type = os.path.splitext(urlparse(uri).path)[1][1:]

        # headers.get('Accept') is never empty if called here.
        # accept_type will be set to json if there is no Accept header
        # accept_type wil be empty only if there is an Accept header
        # with invalid values.
        data_type = ext_type or accept_type or headers.get('Accept') or "invalid"

        if (ext_type):
            # strip extension so uri make sense
            # .../issue.json -> .../issue
            uri = uri[:-(len(ext_type) + 1)]

        # add access-control-allow-* to support CORS
        self.client.setHeader("Access-Control-Allow-Origin", "*")
        self.client.setHeader(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-HTTP-Method-Override"
        )
        self.client.setHeader(
            "Allow",
            "OPTIONS, GET, POST, PUT, DELETE, PATCH"
        )
        self.client.setHeader(
            "Access-Control-Allow-Methods",
            "HEAD, OPTIONS, GET, PUT, DELETE, PATCH"
        )
        # Is there an input.value with format json data?
        # If so turn it into an object that emulates enough
        # of the FieldStorge methods/props to allow a response.
        content_type_header = headers.get('Content-Type', None)
        # python2 is str type, python3 is bytes
        if type(input.value) in (str, bytes) and content_type_header:
            # the structure of a content-type header
            # is complex: mime-type; options(charset ...)
            # for now we just accept application/json.
            # FIXME there should be a function:
            #   parse_content_type_header(content_type_header)
            # that returns a tuple like the Accept header parser.
            # Then the test below could use:
            #   parsed_content_type_header[0].lower() == 'json'
            # That way we could handle stuff like:
            #  application/vnd.roundup-foo+json; charset=UTF8
            # for example.
            if content_type_header.lower() == "application/json":
                try:
                    input = SimulateFieldStorageFromJson(b2s(input.value))
                except ValueError as msg:
                    output = self.error_obj(400, msg)
            else:
                    output = self.error_obj(415,
                                "Unable to process input of type %s" %
                                            content_type_header)

        # check for pretty print
        try:
            pretty_output = not input['@pretty'].value.lower() == "false"
        # Can also return a TypeError ("not indexable")
        # In case the FieldStorage could not parse the result
        except (KeyError, TypeError):
            pretty_output = True

        # check for runtime statistics
        try:
            self.report_stats = input['@stats'].value.lower() == "true"
        # Can also return a TypeError ("not indexable")
        # In case the FieldStorage could not parse the result
        except (KeyError, TypeError):
            report_stats = False

        # check for @apiver in query string
        msg = ("Unrecognized version: %s. "
               "See /rest without specifying version "
               "for supported versions.")
        try:
            if not self.api_version:
                self.api_version = int(input['@apiver'].value)
        # Can also return a TypeError ("not indexable")
        # In case the FieldStorage could not parse the result
        except (KeyError, TypeError):
            self.api_version = None
        except ValueError:
            output = self.error_obj(400, msg % input['@apiver'].value)

        # by this time the API version is set. Error if we don't
        # support it?
        if self.api_version is None:
            # FIXME: do we need to raise an error if client did not specify
            # version? This may be a good thing to require. Note that:
            # Accept: application/json; version=1 may not be legal but....
            #    Use default if not specified for now.
            self.api_version = self.__default_api_version
        elif self.api_version not in self.__supported_api_versions:
            raise UsageError(msg % self.api_version)

        # sadly del doesn't work on FieldStorage which can be the type of
        # input. So we have to ignore keys starting with @ at other
        # places in the code.
        # else:
        #     del(input['@apiver'])

        # Call the appropriate method
        try:
            # If output was defined by a prior error
            # condition skip call
            if not output:
                output = Routing.execute(self, uri, method, input)
        except NotFound as msg:
            output = self.error_obj(404, msg)
        except Reject as msg:
            output = self.error_obj(405, msg)

        # Format the content type
        if data_type.lower() == "json":
            self.client.setHeader("Content-Type", "application/json")
            if pretty_output:
                indent = 4
            else:
                indent = None
            output = RoundupJSONEncoder(indent=indent).encode(output)
        elif data_type.lower() == "xml" and dicttoxml:
            self.client.setHeader("Content-Type", "application/xml")
            if 'error' in output:
                # capture values in error with types unsupported
                # by dicttoxml e.g. an exception, into something it
                # can handle
                import numbers
                import collections
                for key, val in output['error'].items():
                    if isinstance(val, numbers.Number) or type(val) in \
                       (str, unicode):
                        pass
                    elif hasattr(val, 'isoformat'):  # datetime
                        pass
                    elif type(val) == bool:
                        pass
                    elif isinstance(val, dict):
                        pass
                    elif isinstance(val, collections.Iterable):
                        pass
                    elif val is None:
                        pass
                    else:
                        output['error'][key] = str(val)

            output = '<?xml version="1.0" encoding="UTF-8" ?>\n' + \
                     b2s(dicttoxml(output, root=False))
        else:
            # FIXME?? consider moving this earlier. We should
            # error out before doing any work if we can't
            # display acceptable output.
            self.client.response_code = 406
            output = ("Requested content type '%s' is not available.\n"
                      "Acceptable types: %s" % (data_type,
                      ", ".join(sorted(self.__accepted_content_type.keys()))))

        # Make output json end in a newline to
        # separate from following text in logs etc..
        return bs2b(output + "\n")


class RoundupJSONEncoder(json.JSONEncoder):
    """RoundupJSONEncoder overrides the default JSONEncoder to handle all
    types of the object without returning any error"""
    def default(self, obj):
        try:
            result = json.JSONEncoder.default(self, obj)
        except TypeError:
            result = str(obj)
        return result


class SimulateFieldStorageFromJson():
    '''
    The internals of the rest interface assume the data was sent as
    application/x-www-form-urlencoded. So we should have a
    FieldStorage and MiniFieldStorage structure.

    However if we want to handle json data, we need to:
      1) create the Fieldstorage/MiniFieldStorage structure
    or
      2) simultate the interface parts of FieldStorage structure

    To do 2, create a object that emulates the:

          object['prop'].value

    references used when accessing a FieldStorage structure.

    That's what this class does with all names and values as native
    strings. Note that json is UTF-8, so we convert any unicode to
    string.

    '''
    def __init__(self, json_string):
        ''' Parse the json string into an internal dict. '''
        def raise_error_on_constant(x):
            raise ValueError("Unacceptable number: %s" % x)
        try:
            self.json_dict = json.loads(json_string,
                                    parse_constant=raise_error_on_constant)
            self.value = [self.FsValue(index, self.json_dict[index])
                          for index in self.json_dict.keys()]
        except ValueError:
            self.json_dict = {}
            self.value = None

    class FsValue:
        '''Class that does nothing but response to a .value property '''
        def __init__(self, name, val):
            self.name = u2s(name)
            if is_us(val):
                # handle most common type first
                self.value = u2s(val)
            elif isinstance(val, type([])):
                # then lists of strings
                self.value = [u2s(v) for v in val]
            else:
                # then stringify anything else (int, float)
                self.value = str(val)

    def __getitem__(self, index):
        '''Return an FsValue created from the value of self.json_dict[index]
        '''
        return self.FsValue(index, self.json_dict[index])

    def __contains__(self, index):
        ''' implement: 'foo' in DICT '''
        return index in self.json_dict
