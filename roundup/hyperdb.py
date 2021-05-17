#
# Copyright (c) 2001 Bizar Software Pty Ltd (http://www.bizarsoftware.com.au/)
# This module is free software, and you may redistribute it and/or modify
# under the same terms as Python, so long as this copyright message and
# disclaimer are retained in their original form.
#
# IN NO EVENT SHALL BIZAR SOFTWARE PTY LTD BE LIABLE TO ANY PARTY FOR
# DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES ARISING
# OUT OF THE USE OF THIS CODE, EVEN IF THE AUTHOR HAS BEEN ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# BIZAR SOFTWARE PTY LTD SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING,
# BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE.  THE CODE PROVIDED HEREUNDER IS ON AN "AS IS"
# BASIS, AND THERE IS NO OBLIGATION WHATSOEVER TO PROVIDE MAINTENANCE,
# SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
#

"""Hyperdatabase implementation, especially field types.
"""
__docformat__ = 'restructuredtext'

# standard python modules
import os, re, shutil, sys, weakref
import traceback
import logging

# roundup modules
from . import date, password
from .support import ensureParentsExist, PrioList
from roundup.mlink_expr import Expression
from roundup.i18n import _
from roundup.cgi.exceptions import DetectorError
from roundup.anypy.cmp_ import NoneAndDictComparable
from roundup.anypy.strings import eval_import

logger = logging.getLogger('roundup.hyperdb')


#
# Types
#
class _Type(object):
    """A roundup property type."""
    def __init__(self, required=False, default_value=None, quiet=False):
        self.required = required
        self.__default_value = default_value
        self.quiet = quiet
        # We do not allow updates if self.computed is True
        # For now only Multilinks (using the rev_multilink) can be computed
        self.computed = False

    def __repr__(self):
        ' more useful for dumps '
        return '<%s.%s>' % (self.__class__.__module__, self.__class__.__name__)

    def get_default_value(self):
        """The default value when creating a new instance of this property."""
        return self.__default_value

    def register (self, cls, propname):
        """Register myself to the class of which we are a property
           the given propname is the name we have in our class.
        """
        assert not getattr(self, 'cls', None)
        self.name = propname
        self.cls  = cls

    def sort_repr(self, cls, val, name):
        """Representation used for sorting. This should be a python
        built-in type, otherwise sorting will take ages. Note that
        individual backends may chose to use something different for
        sorting as long as the outcome is the same.
        """
        return val


class String(_Type):
    """An object designating a String property."""
    def __init__(self, indexme='no', required=False, default_value="",
                 quiet=False):
        super(String, self).__init__(required, default_value, quiet)
        self.indexme = indexme == 'yes'

    def from_raw(self, value, propname='', **kw):
        """fix the CRLF/CR -> LF stuff"""
        if propname == 'content':
            # Why oh why wasn't the FileClass content property a File
            # type from the beginning?
            return value
        return fixNewlines(value)

    def sort_repr(self, cls, val, name):
        if not val:
            return val
        if name == 'id':
            return int(val)
        return val.lower()


class Password(_Type):
    """An object designating a Password property."""
    def __init__(self, scheme=None, required=False, default_value=None,
                 quiet=False):
        super(Password, self).__init__(required, default_value, quiet)
        self.scheme = scheme

    def from_raw(self, value, **kw):
        if not value:
            return None
        try:
            return password.Password(encrypted=value, scheme=self.scheme,
                                     strict=True)
        except password.PasswordValueError as message:
            raise HyperdbValueError(_('property %s: %s') %
                                    (kw['propname'], message))

    def sort_repr(self, cls, val, name):
        if not val:
            return val
        return str(val)


class Date(_Type):
    """An object designating a Date property."""
    def __init__(self, offset=None, required=False, default_value=None,
                 quiet=False):
        super(Date, self).__init__(required=required,
                                   default_value=default_value,
                                   quiet=quiet)
        self._offset = offset

    def offset(self, db):
        if self._offset is not None:
            return self._offset
        return db.getUserTimezone()

    def from_raw(self, value, db, **kw):
        try:
            value = date.Date(value, self.offset(db))
        except ValueError as message:
            raise HyperdbValueError(_('property %s: %r is an invalid '
                                      'date (%s)') % (kw['propname'],
                                                      value, message))
        return value

    def range_from_raw(self, value, db):
        """return Range value from given raw value with offset correction"""
        return date.Range(value, date.Date, offset=self.offset(db))

    def sort_repr(self, cls, val, name):
        if not val:
            return val
        return str(val)


class Interval(_Type):
    """An object designating an Interval property."""
    def from_raw(self, value, **kw):
        try:
            value = date.Interval(value)
        except ValueError as message:
            raise HyperdbValueError(_('property %s: %r is an invalid '
                                      'date interval (%s)') %
                                    (kw['propname'], value, message))
        return value

    def sort_repr(self, cls, val, name):
        if not val:
            return val
        return val.as_seconds()


class _Pointer(_Type):
    """An object designating a Pointer property that links or multilinks
    to a node in a specified class."""
    def __init__(self, classname, do_journal='yes', try_id_parsing='yes',
                 required=False, default_value=None,
                 msg_header_property=None, quiet=False, rev_multilink=None):
        """ Default is to journal link and unlink events.
            When try_id_parsing is false, we don't allow IDs in input
            fields (the key of the Link or Multilink property must be
            given instead). This is useful when the name of a property
            can be numeric. It will only work if the linked item has a
            key property and is a questionable feature for multilinks.
            The msg_header_property is used in the mail gateway when
            sending out messages: By default roundup creates headers of
            the form: 'X-Roundup-issue-prop: value' for all properties
            prop of issue that have a 'name' property. This definition
            allows to override the 'name' property. A common use-case is
            adding a mail-header with the assigned_to property to allow
            user mail-filtering of issue-emails for which they're
            responsible. In that case setting
            'msg_header_property="username"' for the assigned_to
            property will generated message headers of the form:
            'X-Roundup-issue-assigned_to: joe_user'.
            The rev_multilink is used to inject a reverse multilink into
            the Class linked by a Link or Multilink property. Note that
            the result is always a Multilink. The name given with
            rev_multilink is the name in the class where it is injected.
        """
        super(_Pointer, self).__init__(required, default_value, quiet)
        self.classname = classname
        self.do_journal = do_journal == 'yes'
        self.try_id_parsing = try_id_parsing == 'yes'
        self.msg_header_property = msg_header_property
        self.rev_multilink = rev_multilink

    def __repr__(self):
        """more useful for dumps. But beware: This is also used in schema
        storage in SQL backends!
        """
        return '<%s.%s to "%s">' % (self.__class__.__module__,
                                    self.__class__.__name__, self.classname)


class Link(_Pointer):
    """An object designating a Link property that links to a
       node in a specified class."""
    def from_raw(self, value, db, propname, **kw):
        if (self.try_id_parsing and value == '-1') or not value:
            value = None
        else:
            if self.try_id_parsing:
                value = convertLinkValue(db, propname, self, value)
            else:
                value = convertLinkValue(db, propname, self, value, None)
        return value

    def sort_repr(self, cls, val, name):
        if not val:
            return val
        op = cls.labelprop()
        if op == 'id':
            return int(cls.get(val, op))
        return cls.get(val, op)


class Multilink(_Pointer):
    """An object designating a Multilink property that links
       to nodes in a specified class.

       "classname" indicates the class to link to

       "do_journal" indicates whether the linked-to nodes should have
                    'link' and 'unlink' events placed in their journal
       "rev_property" is used when injecting reverse multilinks. By
                    default (for a normal multilink) the table name is
                    <name_of_linking_class>_<name_of_link_property>
                    e.g. for the messages multilink in issue in the
                    classic schema it would be "issue_messages". The
                    multilink table in that case has two columns, the
                    nodeid contains the ID of the linking class while
                    the linkid contains the ID of the linked-to class.
                    When injecting backlinks, for a backlink resulting
                    from a Link or Multilink the table_name,
                    linkid_name, and nodeid_name must be explicitly
                    specified. So when specifying a rev_multilink
                    property for the messages attribute in the example
                    above, we would get 'issue_messages' for the
                    table_name, 'nodeid' for the linkid_name and
                    'linkid' for the nodeid_name (note the reversal).
                    For a rev_multilink resulting, e.g. from the
                    standard 'status' Link in the Class 'issue' in the
                    classic template we would set table_name to '_issue'
                    (table names in the database get a leading
                    underscore), the nodeid_name to 'status' and the
                    linkid_name to 'id'. With these settings we can use
                    the standard query engine (with minor modifications
                    for the computed names) to resolve reverse
                    multilinks.
    """

    def __init__(self, classname, do_journal='yes', required=False,
                 quiet=False, try_id_parsing='yes', rev_multilink=None,
                 rev_property=None):

        super(Multilink, self).__init__(classname,
                                        do_journal,
                                        required=required,
                                        default_value=[], quiet=quiet,
                                        try_id_parsing=try_id_parsing,
                                        rev_multilink=rev_multilink)
        self.rev_property  = rev_property
        self.rev_classname = None
        self.rev_propname  = None
        self.table_name    = None # computed in 'register' below
        self.linkid_name   = 'linkid'
        self.nodeid_name   = 'nodeid'
        if self.rev_property:
            # Do not allow updates if this is a reverse multilink
            self.computed = True
            self.rev_classname = rev_property.cls.classname
            self.rev_propname  = rev_property.name
            if isinstance(self.rev_property, Link):
                self.table_name  = '_' + self.rev_classname
                self.linkid_name = 'id'
                self.nodeid_name = '_' + self.rev_propname
            else:
                self.table_name  = self.rev_classname + '_' + self.rev_propname
                self.linkid_name = 'nodeid'
                self.nodeid_name = 'linkid'

    def from_raw(self, value, db, klass, propname, itemid, **kw):
        if not value:
            return []

        # get the current item value if it's not a new item
        if itemid and not itemid.startswith('-'):
            curvalue = klass.get(itemid, propname)
        else:
            curvalue = []

        # if the value is a comma-separated string then split it now
        if isinstance(value, type('')):
            value = value.split(',')

        # handle each add/remove in turn
        # keep an extra list for all items that are
        # definitely in the new list (in case of e.g.
        # <propname>=A,+B, which should replace the old
        # list with A,B)
        do_set = 1
        newvalue = []
        for item in value:
            item = item.strip()

            # skip blanks
            if not item: continue

            # handle +/-
            remove = 0
            if item.startswith('-'):
                remove = 1
                item = item[1:].strip()
                do_set = 0
            elif item.startswith('+'):
                item = item[1:].strip()
                do_set = 0

            # look up the value
            if self.try_id_parsing:
                itemid = convertLinkValue(db, propname, self, item)
            else:
                itemid = convertLinkValue(db, propname, self, item, None)

            # perform the add/remove
            if remove:
                try:
                    curvalue.remove(itemid)
                except ValueError:
                    # This can occur if the edit adding the element
                    # produced an error, so the form has it in the
                    # "no selection" choice but it's not set in the
                    # database.
                    pass
            else:
                newvalue.append(itemid)
                if itemid not in curvalue:
                    curvalue.append(itemid)

        # that's it, set the new Multilink property value,
        # or overwrite it completely
        if do_set:
            value = newvalue
        else:
            value = curvalue

        # TODO: one day, we'll switch to numeric ids and this will be
        # unnecessary :(
        value = [int(x) for x in value]
        value.sort()
        value = [str(x) for x in value]
        return value

    def register(self, cls, propname):
        super(Multilink, self).register(cls, propname)
        if self.table_name is None:
            self.table_name = self.cls.classname + '_' + self.name

    def sort_repr(self, cls, val, name):
        if not val:
            return val
        op = cls.labelprop()
        if op == 'id':
            return [int(cls.get(v, op)) for v in val]
        return [cls.get(v, op) for v in val]


class Boolean(_Type):
    """An object designating a boolean property"""
    def from_raw(self, value, **kw):
        value = value.strip()
        # checked is a common HTML checkbox value
        value = value.lower() in ('checked', 'yes', 'true', 'on', '1')
        return value


class Number(_Type):
    """An object designating a numeric property"""
    def __init__(self, use_double=False, **kw):
        """ The value use_double tells the database backend to use a
            floating-point format with more precision than the default.
            Usually implemented by type 'double precision' in the sql
            backend. The default is to use single-precision float (aka
            'real') in the db. Note that sqlite already uses 8-byte for
            floating point numbers.
        """
        self.use_double = use_double
        super(Number, self).__init__(**kw)

    def from_raw(self, value, **kw):
        value = value.strip()
        try:
            value = float(value)
        except ValueError:
            raise HyperdbValueError(_('property %s: %r is not a number') %
                                    (kw['propname'], value))
        return value


class Integer(_Type):
    """An object designating an integer property"""
    def from_raw(self, value, **kw):
        value = value.strip()
        try:
            value = int(value)
        except ValueError:
            raise HyperdbValueError(_('property %s: %r is not an integer') %
                                    (kw['propname'], value))
        return value


#
# Support for splitting designators
#
class DesignatorError(ValueError):
    pass


def splitDesignator(designator,
                    dre=re.compile(r'^([A-Za-z](?:[A-Za-z_0-9]*[A-Za-z_]+)?)(\d+)$')):
    """ Take a foo123 and return ('foo', 123)
    """
    m = dre.match(designator)
    if m is None:
        raise DesignatorError(_('"%s" not a node designator') % designator)
    return m.group(1), m.group(2)


class Exact_Match(object):
    """ Used to encapsulate exact match semantics search values
    """
    def __init__(self, value):
        self.value = value


class Proptree(object):
    """ Simple tree data structure for property lookup. Each node in
    the tree is a roundup Class Property that has to be navigated to
    find given property. The need_for attribute is used to mark nodes
    that are used for sorting, searching or retrieval: The attribute
    is a dictionary containing one or several of the values 'sort',
    'search', 'retrieve'.

    The Proptree is also used for transitively searching attributes for
    backends that do not support transitive search (e.g. anydbm). The
    val attribute with set_val is used for this.
    """

    def __init__(self, db, cls, name, props, parent=None, retr=False):
        self.db = db
        self.name = name
        self.props = props
        self.parent = parent
        self.val = None
        self.has_values = False
        self.has_result = False
        self.cls = cls
        self.classname = None
        self.uniqname = None
        self.children = []
        self.sortattr = []
        self.propdict = {}
        self.need_for = {'search': True}
        self.sort_direction = None
        self.sort_ids = None
        self.sort_ids_needed = False
        self.sort_result = None
        self.attr_sort_done = False
        self.tree_sort_done = False
        self.propclass = None
        self.orderby = []
        self.sql_idx = None  # index of retrieved column in sql result
        self.need_retired = False
        self.need_child_retired = False
        if parent:
            self.root = parent.root
            self.depth = parent.depth + 1
        else:
            self.root = self
            self.seqno = 1
            self.depth = 0
            self.need_for['sort'] = True
        self.id = self.root.seqno
        self.root.seqno += 1
        if self.cls:
            self.classname = self.cls.classname
            self.uniqname = '%s%s' % (self.cls.classname, self.id)
        if not self.parent:
            self.uniqname = self.cls.classname
        if retr:
            self.append_retr_props()

    def append(self, name, need_for='search', retr=False):
        """Append a property to self.children. Will create a new
        propclass for the child.
        """
        if name in self.propdict:
            pt = self.propdict[name]
            pt.need_for[need_for] = True
            # For now we do not recursively retrieve Link properties
            #if retr and isinstance(pt.propclass, Link):
            #    pt.append_retr_props()
            return pt
        propclass = self.props[name]
        cls = None
        props = None
        if isinstance(propclass, (Link, Multilink)):
            cls = self.db.getclass(propclass.classname)
            props = cls.getprops()
        child = self.__class__(self.db, cls, name, props, parent=self)
        child.need_for = {need_for: True}
        child.propclass = propclass
        if isinstance(propclass, Multilink) and self.props[name].computed:
            if isinstance(self.props[name].rev_property, Link):
                child.need_retired = True
            else:
                child.need_child_retired = True
        self.children.append(child)
        self.propdict[name] = child
        # For now we do not recursively retrieve Link properties
        #if retr and isinstance(child.propclass, Link):
        #    child.append_retr_props()
        return child

    def append_retr_props(self):
        """Append properties for retrieval."""
        for name, prop in self.cls.getprops(protected=1).items():
            if isinstance(prop, Multilink):
                continue
            self.append(name, need_for='retrieve')

    def compute_sort_done(self, mlseen=False):
        """ Recursively check if attribute is needed for sorting
        ('sort' in self.need_for) or all children have tree_sort_done set and
        sort_ids_needed unset: set self.tree_sort_done if one of the conditions
        holds. Also remove sort_ids_needed recursively once having seen a
        Multilink that is used for sorting.
        """
        if isinstance(self.propclass, Multilink) and 'sort' in self.need_for:
            mlseen = True
        if mlseen:
            self.sort_ids_needed = False
        self.tree_sort_done = True
        for p in self.children:
            p.compute_sort_done(mlseen)
            if not p.tree_sort_done:
                self.tree_sort_done = False
        if 'sort' not in self.need_for:
            self.tree_sort_done = True
        if mlseen:
            self.tree_sort_done = False

    def ancestors(self):
        p = self
        while p.parent:
            yield p
            p = p.parent

    def search(self, search_matches=None, sort=True, retired=False):
        """ Recursively search for the given properties in a proptree.
        Once all properties are non-transitive, the search generates a
        simple _filter call which does the real work
        """
        filterspec = {}
        exact_match_spec = {}
        for p in self.children:
            if 'search' in p.need_for:
                x = [c for c in p.children if 'search' in c.need_for]
                if x:
                    p.search(sort=False)
                if getattr(p.propclass,'rev_property',None):
                    pn = p.propclass.rev_property.name
                    cl = p.propclass.rev_property.cls
                    if not isinstance(p.val, type([])):
                        p.val = [p.val]
                    nval = [int(i) for i in p.val]
                    pval = [str(i) for i in nval if i >= 0]
                    items = set()
                    if not nval or min(nval) >= -1:
                        if -1 in nval:
                            s1 = set(self.cls.getnodeids(retired=False))
                            s2 = set()
                            for id in cl.getnodeids(retired=False):
                                node = cl.getnode(id)
                                if node[pn]:
                                    if isinstance(node[pn], type([])):
                                        s2.update(node[pn])
                                    else:
                                        s2.add(node[pn])
                            items |= s1.difference(s2)
                        if isinstance(p.propclass.rev_property, Link):
                            items |= set(cl.get(x, pn) for x in pval
                                if not cl.is_retired(x))
                        else:
                            items |= set().union(*(cl.get(x, pn) for x in pval
                                if not cl.is_retired(x)))
                    else:
                        # Expression: materialize rev multilinks and run
                        # expression on them
                        expr = Expression(nval)
                        by_id = {}
                        for id in self.cls.getnodeids(retired=False):
                            by_id[id] = set()
                        items = set()
                        for id in cl.getnodeids(retired=False):
                            node = cl.getnode(id)
                            if node[pn]:
                                v = node[pn]
                                if not isinstance(v, type([])):
                                    v = [v]
                                for x in v:
                                    if x not in by_id:
                                        continue
                                    by_id[x].add(id)
                        for k in by_id:
                            if expr.evaluate(by_id[k]):
                                items.add(k)

                    # The subquery has found nothing. So it doesn't make
                    # sense to search further.
                    if not items:
                        self.set_val([], force=True)
                        return self.val
                    filterspec[p.name] = list(sorted(items, key=int))
                elif isinstance(p.val, type([])):
                    exact = []
                    subst = []
                    for v in p.val:
                        if isinstance(v, Exact_Match):
                            exact.append(v.value)
                        else:
                            subst.append(v)
                    if exact:
                        exact_match_spec[p.name] = exact
                    if subst:
                        filterspec[p.name] = subst
                    elif not exact: # don't set if we have exact criteria
                        if p.has_result:
                            # A subquery already has found nothing. So
                            # it doesn't make sense to search further.
                            self.set_val([], force=True)
                            return self.val
                        else:
                            filterspec[p.name] = ['-1'] # no match was found
                else:
                    assert not isinstance(p.val, Exact_Match)
                    filterspec[p.name] = p.val
        self.set_val(self.cls._filter(search_matches, filterspec, sort and self,
                                      retired=retired,
                                      exact_match_spec=exact_match_spec))
        return self.val

    def sort(self, ids=None):
        """ Sort ids by the order information stored in self. With
        optimisations: Some order attributes may be precomputed (by the
        backend) and some properties may already be sorted.
        """
        if ids is None:
            ids = self.val
        if self.sortattr and [s for s in self.sortattr
                              if not s.attr_sort_done]:
            return self._searchsort(ids, True, True)
        return ids

    def sortable_children(self, intermediate=False):
        """ All children needed for sorting. If intermediate is True,
        intermediate nodes (not being a sort attribute) are returned,
        too.
        """
        return [p for p in self.children
                if 'sort' in p.need_for and (intermediate or p.sort_direction)]

    def __iter__(self):
        """ Yield nodes in depth-first order -- visited nodes first """
        for p in self.children:
            yield p
            for c in p:
                yield c

    def _get(self, ids):
        """Lookup given ids -- possibly a list of list. We recurse until
        we have a list of ids.
        """
        if not ids:
            return ids
        if isinstance(ids[0], list):
            cids = [self._get(i) for i in ids]
        else:
            cids = [i and self.parent.cls.get(i, self.name) for i in ids]
            if self.sortattr:
                cids = [self._searchsort(i, False, True) for i in cids]
        return cids

    def _searchsort(self, ids=None, update=True, dosort=True):
        """ Recursively compute the sort attributes. Note that ids
        may be a deeply nested list of lists of ids if several
        multilinks are encountered on the way from the root to an
        individual attribute. We make sure that everything is properly
        sorted on the way up. Note that the individual backend may
        already have precomputed self.result or self.sort_ids. In this
        case we do nothing for existing sa.result and recurse further if
        self.sort_ids is available.

        Yech, Multilinks: This gets especially complicated if somebody
        sorts by different attributes of the same multilink (or
        transitively across several multilinks). My use-case is sorting
        by issue.messages.author and (reverse) by issue.messages.date.
        In this case we sort the messages by author and date and use
        this sorted list twice for sorting issues. This means that
        issues are sorted by author and then by the time of the messages
        *of this author*. Probably what the user intends in that case,
        so we do *not* use two sorted lists of messages, one sorted by
        author and one sorted by date for sorting issues.
        """
        for pt in self.sortable_children(intermediate=True):
            # ids can be an empty list
            if pt.tree_sort_done or not ids:
                continue
            if pt.sort_ids:  # cached or computed by backend
                cids = pt.sort_ids
            else:
                cids = pt._get(ids)
            if pt.sort_direction and not pt.sort_result:
                sortrep = pt.propclass.sort_repr
                pt.sort_result = pt._sort_repr(sortrep, cids)
            pt.sort_ids = cids
            if pt.children:
                pt._searchsort(cids, update, False)
        if self.sortattr and dosort:
            ids = self._sort(ids)
        if not update:
            for pt in self.sortable_children(intermediate=True):
                pt.sort_ids = None
            for pt in self.sortattr:
                pt.sort_result = None
        return ids

    def set_val(self, val, force=False, result=True):
        """ Check if self.val is already defined (it is not None and
            has_values is True). If yes, we compute the
            intersection of the old and the new value(s)
            Note: If self is a Leaf node we need to compute a
            union: Normally we intersect (logical and) different
            subqueries into a Link or Multilink property. But for
            leaves we might have a part of a query in a filterspec and
            in an exact_match_spec. These have to be all there, the
            generated search will ensure a logical and of all tests for
            equality/substring search.
        """
        if force:
            assert val == []
            assert result
            self.val = val
            self.has_values = True
            self.has_result = True
            return
        if self.has_values:
            v = self.val
            if not isinstance(self.val, type([])):
                v = [self.val]
            vals = set(v)
            if not isinstance(val, type([])):
                val = [val]
        if self.has_result:
            assert result
            # if cls is None we're a leaf
            if self.cls:
                vals.intersection_update(val)
            else:
                vals.update(val)
            self.val = list(vals)
        else:
            # If a subquery found nothing we don't care if there is an
            # expression
            if not self.has_values or not val:
                self.val = val
                if result:
                    self.has_result = True
            else:
                if not result:
                    assert not self.cls
                    vals.update(val)
                    self.val = list(vals)
                else:
                    assert self.cls
                    is_expression = \
                        self.val and min(int(i) for i in self.val) < -1
                    if is_expression:
                        # Tag on the ORed values with an AND
                        l = val
                        for i in range(len(val)-1):
                            l.append('-4')
                        l.append('-3')
                        self.val = self.val + l
                    else:
                        vals.intersection_update(val)
                        self.val = list(vals)
                    self.has_result = True
        self.has_values = True

    def _sort(self, val):
        """Finally sort by the given sortattr.sort_result. Note that we
        do not sort by attrs having attr_sort_done set. The caller is
        responsible for setting attr_sort_done only for trailing
        attributes (otherwise the sort order is wrong). Since pythons
        sort is stable, we can sort already sorted lists without
        destroying the sort-order for items that compare equal with the
        current sort.

        Sorting-Strategy: We sort repeatedly by different sort-keys from
        right to left. Since pythons sort is stable, we can safely do
        that. An optimisation is a "run-length encoding" of the
        sort-directions: If several sort attributes sort in the same
        direction we can combine them into a single sort. Note that
        repeated sorting is probably more efficient than using
        compare-methods in python due to the overhead added by compare
        methods.
        """
        if not val:
            return val
        sortattr = []
        directions = []
        dir_idx = []
        idx = 0
        curdir = None
        for sa in self.sortattr:
            if sa.attr_sort_done:
                break
            if sortattr:
                assert len(sortattr[0]) == len(sa.sort_result)
            sortattr.append(sa.sort_result)
            if curdir != sa.sort_direction:
                dir_idx.append(idx)
                directions.append(sa.sort_direction)
                curdir = sa.sort_direction
            idx += 1
        sortattr.append(val)
        sortattr = zip(*sortattr)
        for dir, i in reversed(list(zip(directions, dir_idx))):
            rev = dir == '-'
            sortattr = sorted(sortattr,
                              key=lambda x: NoneAndDictComparable(x[i:idx]),
                              reverse=rev)
            idx = i
        return [x[-1] for x in sortattr]

    def _sort_repr(self, sortrep, ids):
        """Call sortrep for given ids -- possibly a list of list. We
        recurse until we have a list of ids.
        """
        if not ids:
            return ids
        if isinstance(ids[0], list):
            res = [self._sort_repr(sortrep, i) for i in ids]
        else:
            res = [sortrep(self.cls, i, self.name) for i in ids]
        return res

    def __repr__(self):
        r = ["proptree:" + self.name]
        for n in self:
            r.append("proptree:" + "    " * n.depth + n.name)
        return '\n'.join(r)
    __str__ = __repr__


#
# the base Database class
#
class DatabaseError(ValueError):
    """Error to be raised when there is some problem in the database code
    """
    pass


class Database(object):
    """A database for storing records containing flexible data types.

This class defines a hyperdatabase storage layer, which the Classes use to
store their data.


Transactions
------------
The Database should support transactions through the commit() and
rollback() methods. All other Database methods should be transaction-aware,
using data from the current transaction before looking up the database.

An implementation must provide an override for the get() method so that the
in-database value is returned in preference to the in-transaction value.
This is necessary to determine if any values have changed during a
transaction.


Implementation
--------------

All methods except __repr__ must be implemented by a concrete backend Database.

"""

    # flag to set on retired entries
    RETIRED_FLAG = '__hyperdb_retired'

    BACKEND_MISSING_STRING = None
    BACKEND_MISSING_NUMBER = None
    BACKEND_MISSING_BOOLEAN = None

    def __init__(self, config, journaltag=None):
        """Open a hyperdatabase given a specifier to some storage.

        The 'storagelocator' is obtained from config.DATABASE.
        The meaning of 'storagelocator' depends on the particular
        implementation of the hyperdatabase.  It could be a file name,
        a directory path, a socket descriptor for a connection to a
        database over the network, etc.

        The 'journaltag' is a token that will be attached to the journal
        entries for any edits done on the database.  If 'journaltag' is
        None, the database is opened in read-only mode: the Class.create(),
        Class.set(), and Class.retire() methods are disabled.
        """
        raise NotImplementedError

    def post_init(self):
        """Called once the schema initialisation has finished.
           If 'refresh' is true, we want to rebuild the backend
           structures. Note that post_init can be called multiple times,
           at least during regression testing.
        """
        done = getattr(self, 'post_init_done', None)
        for cn in self.getclasses():
            cl = self.getclass(cn)
            # This will change properties if a back-multilink happens to
            # have the same class, so we need to iterate over .keys()
            for p in cl.properties.keys():
                prop = cl.properties[p]
                if not isinstance (prop, (Link, Multilink)):
                    continue
                if prop.rev_multilink:
                    linkcls = self.getclass(prop.classname)
                    if prop.rev_multilink in linkcls.properties:
                        if not done:
                            raise ValueError(
                                "%s already a property of class %s"%
                                (prop.rev_multilink, linkcls.classname))
                    else:
                        linkcls.properties[prop.rev_multilink] = Multilink(
                            cl.classname, rev_property=prop)
        self.post_init_done = True

    def refresh_database(self):
        """Called to indicate that the backend should rebuild all tables
           and structures. Not called in normal usage."""
        raise NotImplementedError

    def __getattr__(self, classname):
        """A convenient way of calling self.getclass(classname)."""
        raise NotImplementedError

    def addclass(self, cl):
        """Add a Class to the hyperdatabase.
        """
        raise NotImplementedError

    def getclasses(self):
        """Return a list of the names of all existing classes."""
        raise NotImplementedError

    def getclass(self, classname):
        """Get the Class object representing a particular class.

        If 'classname' is not a valid class name, a KeyError is raised.
        """
        raise NotImplementedError

    def clear(self):
        """Delete all database contents.
        """
        raise NotImplementedError

    def getclassdb(self, classname, mode='r'):
        """Obtain a connection to the class db that will be used for
           multiple actions.
        """
        raise NotImplementedError

    def addnode(self, classname, nodeid, node):
        """Add the specified node to its class's db.
        """
        raise NotImplementedError

    def serialise(self, classname, node):
        """Copy the node contents, converting non-marshallable data into
           marshallable data.
        """
        return node

    def setnode(self, classname, nodeid, node):
        """Change the specified node.
        """
        raise NotImplementedError

    def unserialise(self, classname, node):
        """Decode the marshalled node data
        """
        return node

    def getnode(self, classname, nodeid):
        """Get a node from the database.

        'cache' exists for backwards compatibility, and is not used.
        """
        raise NotImplementedError

    def hasnode(self, classname, nodeid):
        """Determine if the database has a given node.
        """
        raise NotImplementedError

    def countnodes(self, classname):
        """Count the number of nodes that exist for a particular Class.
        """
        raise NotImplementedError

    def storefile(self, classname, nodeid, property, content):
        """Store the content of the file in the database.

           The property may be None, in which case the filename does not
           indicate which property is being saved.
        """
        raise NotImplementedError

    def getfile(self, classname, nodeid, property):
        """Get the content of the file in the database.
        """
        raise NotImplementedError

    def addjournal(self, classname, nodeid, action, params):
        """ Journal the Action
        'action' may be:

            'set' -- 'params' is a dictionary of property values
            'create' -- 'params' is an empty dictionary as of
                      Wed Nov 06 11:38:43 2002 +0000
            'link' or 'unlink' -- 'params' is (classname, nodeid, propname)
            'retired' or 'restored'-- 'params' is None
        """
        raise NotImplementedError

    def getjournal(self, classname, nodeid):
        """ get the journal for id
        """
        raise NotImplementedError

    def pack(self, pack_before):
        """ pack the database
        """
        raise NotImplementedError

    def commit(self):
        """ Commit the current transactions.

        Save all data changed since the database was opened or since the
        last commit() or rollback().
        """
        raise NotImplementedError

    def rollback(self):
        """ Reverse all actions from the current transaction.

        Undo all the changes made since the database was opened or the last
        commit() or rollback() was performed.
        """
        raise NotImplementedError

    def close(self):
        """Close the database.

        This method must be called at the end of processing.

        """


def iter_roles(roles):
    ''' handle the text processing of turning the roles list
        into something python can use more easily
    '''
    if not roles or not roles.strip():
        return
    for role in [x.lower().strip() for x in roles.split(',')]:
        yield role


#
# The base Class class
#
class Class:
    """ The handle to a particular class of nodes in a hyperdatabase.

        All methods except __repr__ and getnode must be implemented by a
        concrete backend Class.
    """

    class_re = r'^([A-Za-z](?:[A-Za-z_0-9]*[A-Za-z_]+)?)$'

    def __init__(self, db, classname, **properties):
        """Create a new class with a given name and property specification.

        'classname' must not collide with the name of an existing class,
        or a ValueError is raised. 'classname' must start with an
        alphabetic letter. It must end with an alphabetic letter or '_'.
        Internal characters can be alphanumeric or '_'. ValueError is
        raised if the classname is not correct.
        The keyword arguments in 'properties' must map names to property
        objects, or a TypeError is raised.
        """
        for name in 'creation activity creator actor'.split():
            if name in properties:
                raise ValueError('"creation", "activity", "creator" and '
                                 '"actor" are reserved')

        if not re.match(self.class_re, classname):
            raise ValueError('Class name %s is not valid. It must start '
                             'with a letter, end with a letter or "_", and '
                             'only have alphanumerics and "_" in the '
                             'middle.' % (classname,))

        self.classname = classname
        self.properties = properties
        # Make the class and property name known to the property
        for p in properties:
            properties[p].register(self, p)
        self.db = weakref.proxy(db)       # use a weak ref to avoid circularity
        self.key = ''

        # should we journal changes (default yes)
        self.do_journal = 1

        # do the db-related init stuff
        db.addclass(self)

        actions = "create set retire restore".split()
        self.auditors = dict([(a, PrioList()) for a in actions])
        self.reactors = dict([(a, PrioList()) for a in actions])

    def __repr__(self):
        """Slightly more useful representation
           Note that an error message can be raised at a point
           where self.classname isn't known yet if the error
           occurs during schema parsing.
        """
        cn = getattr (self, 'classname', 'Unknown')
        return '<hyperdb.Class "%s">' % cn

    # Editing nodes:

    def create(self, **propvalues):
        """Create a new node of this class and return its id.

        The keyword arguments in 'propvalues' map property names to values.

        The values of arguments must be acceptable for the types of their
        corresponding properties or a TypeError is raised.

        If this class has a key property, it must be present and its value
        must not collide with other key strings or a ValueError is raised.

        Any other properties on this class that are missing from the
        'propvalues' dictionary are set to None.

        If an id in a link or multilink property does not refer to a valid
        node, an IndexError is raised.
        """
        raise NotImplementedError

    _marker = []

    def get(self, nodeid, propname, default=_marker, cache=1):
        """Get the value of a property on an existing node of this class.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.  'propname' must be the name of a property
        of this class or a KeyError is raised.

        'cache' exists for backwards compatibility, and is not used.
        """
        raise NotImplementedError

    # not in spec
    def getnode(self, nodeid):
        """ Return a convenience wrapper for the node.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.

        'cache' exists for backwards compatibility, and is not used.
        """
        return Node(self, nodeid)

    def getnodeids(self, retired=None):
        """Retrieve all the ids of the nodes for a particular Class.
        """
        raise NotImplementedError

    def set(self, nodeid, **propvalues):
        """Modify a property on an existing node of this class.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.

        Each key in 'propvalues' must be the name of a property of this
        class or a KeyError is raised.

        All values in 'propvalues' must be acceptable types for their
        corresponding properties or a TypeError is raised.

        If the value of the key property is set, it must not collide with
        other key strings or a ValueError is raised.

        If the value of a Link or Multilink property contains an invalid
        node id, a ValueError is raised.
        """
        raise NotImplementedError

    def retire(self, nodeid):
        """Retire a node.

        The properties on the node remain available from the get() method,
        and the node's id is never reused.

        Retired nodes are not returned by the find(), list(), or lookup()
        methods, and other nodes may reuse the values of their key properties.
        """
        raise NotImplementedError

    def restore(self, nodeid):
        """Restpre a retired node.

        Make node available for all operations like it was before retirement.
        """
        raise NotImplementedError

    def is_retired(self, nodeid):
        """Return true if the node is rerired
        """
        raise NotImplementedError

    def destroy(self, nodeid):
        """Destroy a node.

        WARNING: this method should never be used except in extremely rare
                 situations where there could never be links to the node being
                 deleted

        WARNING: use retire() instead

        WARNING: the properties of this node will not be available ever again

        WARNING: really, use retire() instead

        Well, I think that's enough warnings. This method exists mostly to
        support the session storage of the cgi interface.

        The node is completely removed from the hyperdb, including all journal
        entries. It will no longer be available, and will generally break code
        if there are any references to the node.
        """

    def history(self, nodeid, enforceperm=True, skipquiet=True):
        """Retrieve the journal of edits on a particular node.

        'nodeid' must be the id of an existing node of this class or an
        IndexError is raised.

        The returned list contains tuples of the form

            (date, tag, action, params)

        'date' is a Timestamp object specifying the time of the change and
        'tag' is the journaltag specified when the database was opened.

        If the property to be displayed is a quiet property, it will
        not be shown. This can be disabled by setting skipquiet=False.

        If the user requesting the history does not have View access
        to the property, the journal entry will not be shown. This can
        be disabled by setting enforceperm=False.

        Note that there is a check for obsolete properties and classes
        resulting from history changes. These are also only checked if
        enforceperm is True.
        """
        if not self.do_journal:
            raise ValueError('Journalling is disabled for this class')

        perm = self.db.security.hasPermission
        journal = []

        uid = self.db.getuid()  # id of the person requesting the history

        # Roles of the user and the configured obsolete_history_roles
        hr = set(iter_roles(self.db.config.OBSOLETE_HISTORY_ROLES))
        ur = set(self.db.user.get_roles(uid))
        allow_obsolete = bool(hr & ur)

        for j in self.db.getjournal(self.classname, nodeid):
            # hide/remove journal entry if:
            #   property is quiet
            #   property is not (viewable or editable)
            #   property is obsolete and not allow_obsolete
            id, evt_date, user, action, args = j
            if logger.isEnabledFor(logging.DEBUG):
                j_repr = "%s" % (j,)
            else:
                j_repr = ''
            if args and isinstance(args, type({})):
                for key in list(args.keys()):
                    if key not in self.properties:
                        if enforceperm and not allow_obsolete:
                            del args[key]
                        continue
                    if skipquiet and self.properties[key].quiet:
                        logger.debug("skipping quiet property"
                                     " %s::%s in %s",
                                     self.classname, key, j_repr)
                        del args[key]
                        continue
                    if enforceperm and not (perm("View",
                                                 uid,
                                                 self.classname,
                                                 property=key) or
                                            perm("Edit",
                                                 uid,
                                                 self.classname,
                                                 property=key)):
                        logger.debug("skipping unaccessible property "
                                     "%s::%s seen by user%s in %s",
                                     self.classname, key, uid, j_repr)
                        del args[key]
                        continue
                if not args:
                    logger.debug("Omitting journal entry for  %s%s"
                                 " all props removed in: %s",
                                 self.classname, nodeid, j_repr)
                    continue
                journal.append(j)
            elif action in ['link', 'unlink'] and isinstance(args, type(())):
                # definitions:
                # myself - object whose history is being filtered
                # linkee - object/class whose property is changing to
                #          include/remove myself
                # link property - property of the linkee class that is changing
                #
                # Remove the history item if
                #   linkee.link property (key) is quiet
                #   linkee class.link property is not (viewable or editable)
                #       to user
                #   [ should linkee object.link property is not
                #      (viewable or editable) to user be included?? ]
                #   linkee object (linkcl, linkid) is not
                #       (viewable or editable) to user
                if len(args) == 3:
                    # e.g. for issue3 blockedby adds link to issue5 with:
                    # j = id, evt_date, user, action, args
                    # 3|20170528045201.484|5|link|('issue', '5', 'blockedby')
                    linkcl, linkid, key = args
                    cls = None
                    try:
                        cls = self.db.getclass(linkcl)
                    except KeyError:
                        pass
                    # obsolete property or class
                    if not cls or key not in cls.properties:
                        if not enforceperm or allow_obsolete:
                            journal.append(j)
                        continue
                    # obsolete linked-to item
                    try:
                        cls.get(linkid, key)  # does linkid exist
                    except IndexError:
                        if not enforceperm or allow_obsolete:
                            journal.append(j)
                        continue
                    # is the updated property quiet?
                    if skipquiet and cls.properties[key].quiet:
                        logger.debug("skipping quiet property: "
                                     "%s %sed %s%s",
                                     j_repr, action, self.classname, nodeid)
                        continue
                    # can user view the property in linkee class
                    if enforceperm and not (perm("View",
                                                 uid,
                                                 linkcl,
                                                 property=key) or
                                            perm("Edit",
                                                 uid,
                                                 linkcl,
                                                 property=key)):
                        logger.debug("skipping unaccessible property: "
                                     "%s with uid %s %sed %s%s",
                                     j_repr, uid, action,
                                     self.classname, nodeid)
                        continue
                    # check access to linkee object
                    if enforceperm and not (perm("View",
                                                 uid,
                                                 cls.classname,
                                                 itemid=linkid) or
                                            perm("Edit",
                                                 uid,
                                                 cls.classname,
                                                 itemid=linkid)):
                        logger.debug("skipping unaccessible object: "
                                     "%s uid %s %sed %s%s",
                                     j_repr, uid, action,
                                     self.classname, nodeid)
                        continue
                    journal.append(j)
                else:
                    logger.error("Invalid %s journal entry for %s%s: %s",
                                 action, self.classname, nodeid, j)
            elif action in ['create', 'retired', 'restored']:
                journal.append(j)
            else:
                logger.warning("Possibly malformed journal for %s%s %s",
                               self.classname, nodeid, j)
        return journal

    # Locating nodes:
    def hasnode(self, nodeid):
        """Determine if the given nodeid actually exists
        """
        raise NotImplementedError

    def setkey(self, propname):
        """Select a String property of this class to be the key property.

        'propname' must be the name of a String property of this class or
        None, or a TypeError is raised.  The values of the key property on
        all existing nodes must be unique or a ValueError is raised.
        """
        raise NotImplementedError

    def setlabelprop(self, labelprop):
        """Set the label property. Used for override of labelprop
           resolution order.
        """
        if labelprop not in self.getprops():
            raise ValueError(_("Not a property name: %s") % labelprop)
        self._labelprop = labelprop

    def setorderprop(self, orderprop):
        """Set the order property. Used for override of orderprop
           resolution order
        """
        if orderprop not in self.getprops():
            raise ValueError(_("Not a property name: %s") % orderprop)
        self._orderprop = orderprop

    def getkey(self):
        """Return the name of the key property for this class or None."""
        raise NotImplementedError

    def labelprop(self, default_to_id=0):
        """Return the property name for a label for the given node.

        This method attempts to generate a consistent label for the node.
        It tries the following in order:

        0. self._labelprop if set
        1. key property
        2. "name" property
        3. "title" property
        4. first property from the sorted property name list
        """
        if hasattr(self, '_labelprop'):
            return self._labelprop
        k = self.getkey()
        if k:
            return k
        props = self.getprops()
        if 'name' in props:
            return 'name'
        elif 'title' in props:
            return 'title'
        if default_to_id:
            return 'id'
        props = sorted(props.keys())
        return props[0]

    def orderprop(self):
        """Return the property name to use for sorting for the given node.

        This method computes the property for sorting.
        It tries the following in order:

        0. self._orderprop if set
        1. "order" property
        2. self.labelprop()
        """

        if hasattr(self, '_orderprop'):
            return self._orderprop
        props = self.getprops()
        if 'order' in props:
            return 'order'
        return self.labelprop()

    def lookup(self, keyvalue):
        """Locate a particular node by its key property and return its id.

        If this class has no key property, a TypeError is raised.  If the
        'keyvalue' matches one of the values for the key property among
        the nodes in this class, the matching node's id is returned;
        otherwise a KeyError is raised.
        """
        raise NotImplementedError

    def find(self, **propspec):
        """Get the ids of nodes in this class which link to the given nodes.

        'propspec' consists of keyword args propname={nodeid:1,}
        'propname' must be the name of a property in this class, or a
        KeyError is raised.  That property must be a Link or Multilink
        property, or a TypeError is raised.

        Any node in this class whose 'propname' property links to any of the
        nodeids will be returned. Used by the full text indexing, which knows
        that "foo" occurs in msg1, msg3 and file7, so we have hits on these
        issues:

            db.issue.find(messages={'1':1,'3':1}, files={'7':1})
        """
        raise NotImplementedError

    def _filter(self, search_matches, filterspec, sort=(None, None),
                group=(None, None), retired=False, exact_match_spec={}):
        """For some backends this implements the non-transitive
        search, for more information see the filter method.
        """
        raise NotImplementedError

    def _proptree(self, filterspec, exact_match_spec={}, sortattr=[],
                  retr=False):
        """Build a tree of all transitive properties in the given
        exact_match_spec/filterspec.
        If we retrieve (retr is True) linked items we don't follow
        across multilinks or links.
        """
        proptree = Proptree(self.db, self, '', self.getprops(), retr=retr)
        for exact, spec in enumerate((filterspec, exact_match_spec)):
            for key, v in spec.items():
                keys = key.split('.')
                p = proptree
                mlseen = False
                for k in keys:
                    if isinstance(p.propclass, Multilink):
                        mlseen = True
                    isnull = v == '-1' or v is None
                    islist = isinstance(v, type([]))
                    nullin = islist and ('-1' in v or None in v)
                    r = retr and not mlseen and not isnull and not nullin
                    p = p.append(k, retr=r)
                if exact:
                    if isinstance(v, type([])):
                        vv = []
                        for x in v:
                            vv.append(Exact_Match(x))
                        p.set_val(vv, result=False)
                    else:
                        p.set_val([Exact_Match(v)], result=False)
                else:
                    p.set_val(v, result=False)
        multilinks = {}
        for s in sortattr:
            keys = s[1].split('.')
            p = proptree
            mlseen = False
            for k in keys:
                if isinstance(p.propclass, Multilink):
                    mlseen = True
                r = retr and not mlseen
                p = p.append(k, need_for='sort', retr=r)
                if isinstance(p.propclass, Multilink):
                    multilinks[p] = True
            if p.cls:
                p = p.append(p.cls.orderprop(), need_for='sort')
            if p.sort_direction:  # if orderprop is also specified explicitly
                continue
            p.sort_direction = s[0]
            proptree.sortattr.append(p)
        for p in multilinks.keys():
            sattr = {}
            for c in p:
                if c.sort_direction:
                    sattr[c] = True
            for sa in proptree.sortattr:
                if sa in sattr:
                    p.sortattr.append(sa)
        return proptree

    def get_transitive_prop(self, propname_path, default=None):
        """Expand a transitive property (individual property names
        separated by '.' into a new property at the end of the path. If
        one of the names does not refer to a valid property, we return
        None.
        Example propname_path (for class issue): "messages.author"
        """
        props = self.db.getclass(self.classname).getprops()
        for k in propname_path.split('.'):
            try:
                prop = props[k]
            except (KeyError, TypeError):
                return default
            cl = getattr(prop, 'classname', None)
            props = None
            if cl:
                props = self.db.getclass(cl).getprops()
        return prop

    def _sortattr(self, sort=[], group=[]):
        """Build a single list of sort attributes in the correct order
        with sanity checks (no duplicate properties) included. Always
        sort last by id -- if id is not already in sortattr.
        """
        seen = {}
        sortattr = []
        for srt in group, sort:
            if not isinstance(srt, list):
                srt = [srt]
            for s in srt:
                if s[1] and s[1] not in seen:
                    sortattr.append((s[0] or '+', s[1]))
                    seen[s[1]] = True
        if 'id' not in seen:
            sortattr.append(('+', 'id'))
        return sortattr

    def filter(self, search_matches, filterspec, sort=[], group=[],
               retired=False, exact_match_spec={}, limit=None, offset=None):
        """Return a list of the ids of the active nodes in this class that
        match the 'filter' spec, sorted by the group spec and then the
        sort spec.

        "search_matches" is a container type which by default is None
        and optionally contains IDs of items to match. If non-empty only
        IDs of the initial set are returned.

        "filterspec" is {propname: value(s)}
        "exact_match_spec" is the same format as "filterspec" but
        specifies exact match for the given propnames. This only makes a
        difference for String properties, these specify case insensitive
        substring search when in "filterspec" and exact match when in
        exact_match_spec.

        "sort" and "group" are [(dir, prop), ...] where dir is '+', '-'
        or None and prop is a prop name or None. Note that for
        backward-compatibility reasons a single (dir, prop) tuple is
        also allowed.

        The parameter retired when set to False, returns only live
        (un-retired) results. When setting it to True, only retired
        items are returned. If None, both retired and unretired items
        are returned. The default is False, i.e. only live items are
        returned by default.

        The "limit" and "offset" parameters define a limit on the number
        of results returned and an offset before returning any results,
        respectively. These can be used when displaying a number of
        items in a pagination application or similar. A common use-case
        is returning the first item of a sorted search by specifying
        limit=1 (i.e. the maximum or minimum depending on sort order).

        The filter must match all properties specificed. If the property
        value to match is a list:

        1. String properties must match all elements in the list, and
        2. Other properties must match any of the elements in the list.

        This also means that for strings in exact_match_spec it doesn't
        make sense to specify multiple values because those cannot all
        be matched exactly.

        For Link and Multilink properties the special ID value '-1'
        matches empty Link or Multilink fields. For Multilinks a postfix
        expression syntax using negative ID numbers (as strings) as
        operators is supported. Each non-negative number (or '-1') is
        pushed on an operand stack. A negative number pops the required
        number of arguments from the stack, applies the operator, and
        pushes the result. The following operators are supported:
        - -2 stands for 'NOT' and takes one argument
        - -3 stands for 'AND' and takes two arguments
        - -4 stands for 'OR' and takes two arguments
        Note that this special handling of ID arguments is applied only
        when a negative number smaller than -1 is encountered as an ID
        in the filter call. Otherwise the implicit OR default applies.
        Examples of using Multilink expressions would be
        - '1', '2', '-4', '3', '4', '-4', '-3'
          would search for IDs (1 or 2) and (3 or 4)
        - '-1' '-2' would search for all non-empty Multilinks


        The propname in filterspec and prop in a sort/group spec may be
        transitive, i.e., it may contain properties of the form
        link.link.link.name, e.g. you can search for all issues where a
        message was added by a certain user in the last week with a
        filterspec of
        {'messages.author' : '42', 'messages.creation' : '.-1w;'}

        Implementation note:
        This implements a non-optimized version of Transitive search
        using _filter implemented in a backend class. A more efficient
        version can be implemented in the individual backends -- e.g.,
        an SQL backend will want to create a single SQL statement and
        override the filter method instead of implementing _filter.
        """
        sortattr = self._sortattr(sort=sort, group=group)
        proptree = self._proptree(filterspec, exact_match_spec, sortattr)
        proptree.search(search_matches, retired=retired)
        if offset is not None or limit is not None:
            items = proptree.sort()
            if limit and offset:
                return items[offset:offset+limit]
            elif offset is not None:
                return items[offset:]
            else:
                return items[:limit]
        return proptree.sort()

    # non-optimized filter_iter, a backend may chose to implement a
    # better version that provides a real iterator that pre-fills the
    # cache for each id returned. Note that the filter_iter doesn't
    # promise to correctly sort by multilink (which isn't sane to do
    # anyway).
    filter_iter = filter

    def count(self):
        """Get the number of nodes in this class.

        If the returned integer is 'numnodes', the ids of all the nodes
        in this class run from 1 to numnodes, and numnodes+1 will be the
        id of the next node to be created in this class.
        """
        raise NotImplementedError

    # Manipulating properties:
    def getprops(self, protected=1):
        """Return a dictionary mapping property names to property objects.
           If the "protected" flag is true, we include protected properties -
           those which may not be modified.
        """
        raise NotImplementedError

    def get_required_props(self, propnames=[]):
        """Return a dict of property names mapping to property objects.
        All properties that have the "required" flag set will be
        returned in addition to all properties in the propnames
        parameter.
        """
        props = self.getprops(protected=False)
        pdict = dict([(p, props[p]) for p in propnames])
        pdict.update([(k, v) for k, v in props.items() if v.required])
        return pdict

    def addprop(self, **properties):
        """Add properties to this class.

        The keyword arguments in 'properties' must map names to property
        objects, or a TypeError is raised.  None of the keys in 'properties'
        may collide with the names of existing properties, or a ValueError
        is raised before any properties have been added.
        """
        raise NotImplementedError

    def index(self, nodeid):
        """Add (or refresh) the node to search indexes"""
        raise NotImplementedError

    #
    # Detector interface
    #
    def audit(self, event, detector, priority=100):
        """Register an auditor detector"""
        self.auditors[event].append((priority, detector.__name__, detector))

    def fireAuditors(self, event, nodeid, newvalues):
        """Fire all registered auditors"""
        for _prio, _name, audit in self.auditors[event]:
            try:
                audit(self.db, self, nodeid, newvalues)
            except (EnvironmentError, ArithmeticError) as e:
                tb = traceback.format_exc()
                html = ("<h1>Traceback</h1>" + str(tb).replace('\n', '<br>').
                        replace(' ', '&nbsp;'))
                txt = 'Caught exception %s: %s\n%s' % (str(type(e)), e, tb)
                exc_info = sys.exc_info()
                subject = "Error: %s" % exc_info[1]
                raise DetectorError(subject, html, txt)

    def react(self, event, detector, priority=100):
        """Register a reactor detector"""
        self.reactors[event].append((priority, detector.__name__, detector))

    def fireReactors(self, event, nodeid, oldvalues):
        """Fire all registered reactors"""
        for _prio, _name, react in self.reactors[event]:
            try:
                react(self.db, self, nodeid, oldvalues)
            except (EnvironmentError, ArithmeticError) as e:
                tb = traceback.format_exc()
                html = ("<h1>Traceback</h1>" + str(tb).replace('\n', '<br>').
                        replace(' ', '&nbsp;'))
                txt = 'Caught exception %s: %s\n%s' % (str(type(e)), e, tb)
                exc_info = sys.exc_info()
                subject = "Error: %s" % exc_info[1]
                raise DetectorError(subject, html, txt)

    #
    # import / export support
    #
    def export_propnames(self):
        """List the property names for export from this Class"""
        propnames = sorted(self.getprops().keys())
        return propnames

    def import_journals(self, entries):
        """Import a class's journal.

        Uses setjournal() to set the journal for each item.
        Strategy for import: Sort first by id, then import journals for
        each id, this way the memory footprint is a lot smaller than the
        initial implementation which stored everything in a big hash by
        id and then proceeded to import journals for each id."""
        properties = self.getprops()
        a = []
        for l in entries:
            # first element in sorted list is the (numeric) id
            # in python2.4 and up we would use sorted with a key...
            a.append((int(l[0].strip("'")), l))
        a.sort()

        last = 0
        r = []
        for n, l in a:
            nodeid, jdate, user, action, params = map(eval_import, l)
            assert (str(n) == nodeid)
            if n != last:
                if r:
                    self.db.setjournal(self.classname, str(last), r)
                last = n
                r = []

            if action == 'set':
                for propname, value in params.items():
                    prop = properties[propname]
                    if value is None:
                        pass
                    elif isinstance(prop, Date):
                        value = date.Date(value)
                    elif isinstance(prop, Interval):
                        value = date.Interval(value)
                    elif isinstance(prop, Password):
                        value = password.JournalPassword(encrypted=value)
                    params[propname] = value
            elif action == 'create' and params:
                # old tracker with data stored in the create!
                params = {}
            r.append((nodeid, date.Date(jdate), user, action, params))
        if r:
            self.db.setjournal(self.classname, nodeid, r)

    #
    # convenience methods
    #
    def get_roles(self, nodeid):
        """Return iterator for all roles for this nodeid.

           Yields string-processed roles.
           This method can be overridden to provide a hook where we can
           insert other permission models (e.g. get roles from database)
           In standard schemas only a user has a roles property but
           this may be different in customized schemas.
           Note that this is the *central place* where role
           processing happens!
        """
        node = self.db.getnode(self.classname, nodeid)
        return iter_roles(node['roles'])

    def has_role(self, nodeid, *roles):
        '''See if this node has any roles that appear in roles.

           For convenience reasons we take a list.
           In standard schemas only a user has a roles property but
           this may be different in customized schemas.
        '''
        roles = dict.fromkeys([r.strip().lower() for r in roles])
        for role in self.get_roles(nodeid):
            if role in roles:
                return True
        return False


class HyperdbValueError(ValueError):
    """ Error converting a raw value into a Hyperdb value """
    pass


def convertLinkValue(db, propname, prop, value, idre=re.compile(r'^\d+$')):
    """ Convert the link value (may be id or key value) to an id value. """
    linkcl = db.classes[prop.classname]
    if not idre or not idre.match(value):
        if linkcl.getkey():
            try:
                value = linkcl.lookup(value)
            except KeyError:
                raise HyperdbValueError(_('property %s: %r is not a %s.') % (
                    propname, value, prop.classname))
        else:
            raise HyperdbValueError(_('you may only enter ID values '
                                      'for property %s') % propname)
    return value


def fixNewlines(text):
    """ Homogenise line endings.

        Different web clients send different line ending values, but
        other systems (eg. email) don't necessarily handle those line
        endings. Our solution is to convert all line endings to LF.
    """
    if text is not None:
        text = text.replace('\r\n', '\n')
        return text.replace('\r', '\n')
    return text


def rawToHyperdb(db, klass, itemid, propname, value, **kw):
    """ Convert the raw (user-input) value to a hyperdb-storable value. The
        value is for the "propname" property on itemid (may be None for a
        new item) of "klass" in "db".

        The value is usually a string, but in the case of multilink inputs
        it may be either a list of strings or a string with comma-separated
        values.
    """
    properties = klass.getprops()

    # ensure it's a valid property name
    propname = propname.strip()
    try:
        proptype = properties[propname]
    except KeyError:
        raise HyperdbValueError(_('%r is not a property of %s') % (
            propname, klass.classname))

    # if we got a string, strip it now
    if isinstance(value, type('')):
        value = value.strip()

    # convert the input value to a real property value
    value = proptype.from_raw(value, db=db, klass=klass,
                              propname=propname, itemid=itemid, **kw)

    return value


class FileClass:
    """ A class that requires the "content" property and stores it on
        disk.
    """
    default_mime_type = 'text/plain'

    def __init__(self, db, classname, **properties):
        """The newly-created class automatically includes the "content"
        property.
        """
        if 'content' not in properties:
            properties['content'] = String(indexme='yes')

    def export_propnames(self):
        """ Don't export the "content" property
        """
        propnames = list(self.getprops().keys())
        propnames.remove('content')
        propnames.sort()
        return propnames

    def exportFilename(self, dirname, nodeid):
        """ Returns destination filename for a exported file

            Called by export function in roundup admin to generate
            the <class>-files subdirectory
        """
        subdir_filename = self.db.subdirFilename(self.classname, nodeid)
        return os.path.join(dirname, self.classname+'-files', subdir_filename)

    def export_files(self, dirname, nodeid):
        """ Export the "content" property as a file, not csv column
        """
        source = self.db.filename(self.classname, nodeid)

        dest = self.exportFilename(dirname, nodeid)
        ensureParentsExist(dest)
        shutil.copyfile(source, dest)

    def import_files(self, dirname, nodeid):
        """ Import the "content" property as a file
        """
        source = self.exportFilename(dirname, nodeid)

        dest = self.db.filename(self.classname, nodeid, create=1)
        ensureParentsExist(dest)
        shutil.copyfile(source, dest)

        mime_type = None
        props = self.getprops()
        if 'type' in props:
            mime_type = self.get(nodeid, 'type')
        if not mime_type:
            mime_type = self.default_mime_type
        if props['content'].indexme:
            index_content = self.get(nodeid, 'binary_content')
            if bytes != str and isinstance(index_content, bytes):
                index_content = index_content.decode('utf-8', errors='ignore')
            # indexer will only index text mime type. It will skip
            # other types. So if mime type of file is correct, we
            # call add_text on content.
            self.db.indexer.add_text((self.classname, nodeid, 'content'),
                                     index_content, mime_type)


class Node:
    """ A convenience wrapper for the given node
    """
    def __init__(self, cl, nodeid, cache=1):
        self.__dict__['cl'] = cl
        self.__dict__['nodeid'] = nodeid

    def keys(self, protected=1):
        return list(self.cl.getprops(protected=protected).keys())

    def values(self, protected=1):
        l = []
        for name in self.cl.getprops(protected=protected).keys():
            l.append(self.cl.get(self.nodeid, name))
        return l

    def items(self, protected=1):
        l = []
        for name in self.cl.getprops(protected=protected).keys():
            l.append((name, self.cl.get(self.nodeid, name)))
        return l

    def has_key(self, name):
        return name in self.cl.getprops()

    def get(self, name, default=None):
        if name in self:
            return self[name]
        else:
            return default

    def __getattr__(self, name):
        if name in self.__dict__:
            return self.__dict__[name]
        try:
            return self.cl.get(self.nodeid, name)
        except KeyError as value:
            # we trap this but re-raise it as AttributeError - all other
            # exceptions should pass through untrapped
            raise AttributeError(str(value))

    def __getitem__(self, name):
        return self.cl.get(self.nodeid, name)

    def __setattr__(self, name, value):
        try:
            return self.cl.set(self.nodeid, **{name: value})
        except KeyError as value:
            # we trap this but re-raise it as AttributeError - all other
            # exceptions should pass through untrapped
            raise AttributeError(str(value))

    def __setitem__(self, name, value):
        self.cl.set(self.nodeid, **{name: value})

    def history(self, enforceperm=True, skipquiet=True):
        return self.cl.history(self.nodeid,
                               enforceperm=enforceperm,
                               skipquiet=skipquiet)

    def retire(self):
        return self.cl.retire(self.nodeid)


def Choice(name, db, *options):
    """Quick helper to create a simple class with choices
    """
    cl = Class(db, name, name=String(), order=String())
    for i in range(len(options)):
        cl.create(name=options[i], order=i)
    return Link(name)

