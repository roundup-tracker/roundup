import mimetypes
import re

from roundup import hyperdb, date, password
from roundup.cgi import TranslationService
from roundup.cgi.exceptions import FormError


class FormParser:
    # edit form variable handling (see unit tests)
    FV_LABELS = r'''
       ^(
         (?P<note>[@:]note)|
         (?P<file>[@:]file)|
         (
          ((?P<classname>%s)(?P<id>[-\d]+))?  # optional leading designator
          ((?P<required>[@:]required$)|       # :required
           (
            (
             (?P<add>[@:]add[@:])|            # :add:<prop>
             (?P<remove>[@:]remove[@:])|      # :remove:<prop>
             (?P<confirm>[@:]confirm[@:])|    # :confirm:<prop>
             (?P<link>[@:]link[@:])|          # :link:<prop>
             ([@:])                           # just a separator
            )?
            (?P<propname>[^@:]+)             # <prop>
           )
          )
         )
        )$'''

    def __init__(self, client):
        self.client = client
        self.db = client.db
        self.form = client.form
        self.classname = client.classname
        self.nodeid = client.nodeid
        try:
            self._ = self.gettext = client.gettext
            self.ngettext = client.ngettext
        except AttributeError:
            _translator = TranslationService.get_translation()
            self._ = self.gettext = _translator.gettext
            self.ngettext = _translator.ngettext

    def parse(self, create=0):
        """ Item properties and their values are edited with html FORM
            variables and their values. You can:

            - Change the value of some property of the current item.
            - Create a new item of any class, and edit the new item's
              properties,
            - Attach newly created items to a multilink property of the
              current item.
            - Remove items from a multilink property of the current item.
            - Specify that some properties are required for the edit
              operation to be successful.

            In the following, <bracketed> values are variable, "@" may be
            either ":" or "@", and other text "required" is fixed.

            Most properties are specified as form variables:

             <propname>
              - property on the current context item

             <designator>"@"<propname>
              - property on the indicated item (for editing related
                information)

            Designators name a specific item of a class.

            <classname><N>

                Name an existing item of class <classname>.

            <classname>"-"<N>

                Name the <N>th new item of class <classname>. If the form
                submission is successful, a new item of <classname> is
                created. Within the submitted form, a particular
                designator of this form always refers to the same new
                item.

            Once we have determined the "propname", we look at it to see
            if it's special:

            @required
                The associated form value is a comma-separated list of
                property names that must be specified when the form is
                submitted for the edit operation to succeed.

                When the <designator> is missing, the properties are
                for the current context item.  When <designator> is
                present, they are for the item specified by
                <designator>.

                The "@required" specifier must come before any of the
                properties it refers to are assigned in the form.

            @remove@<propname>=id(s) or @add@<propname>=id(s)
                The "@add@" and "@remove@" edit actions apply only to
                Multilink properties.  The form value must be a
                comma-separate list of keys for the class specified by
                the simple form variable.  The listed items are added
                to (respectively, removed from) the specified
                property.

            @link@<propname>=<designator>
                If the edit action is "@link@", the simple form
                variable must specify a Link or Multilink property.
                The form value is a comma-separated list of
                designators.  The item corresponding to each
                designator is linked to the property given by simple
                form variable.  These are collected up and returned in
                all_links.

            None of the above (ie. just a simple form value)
                The value of the form variable is converted
                appropriately, depending on the type of the property.

                For a Link('klass') property, the form value is a
                single key for 'klass', where the key field is
                specified in dbinit.py.

                For a Multilink('klass') property, the form value is a
                comma-separated list of keys for 'klass', where the
                key field is specified in dbinit.py.

                Note that for simple-form-variables specifiying Link
                and Multilink properties, the linked-to class must
                have a key field.

                For a String() property specifying a filename, the
                file named by the form value is uploaded. This means we
                try to set additional properties "filename" and "type" (if
                they are valid for the class).  Otherwise, the property
                is set to the form value.

                For Date(), Interval(), Boolean(), and Number(), Integer()
                properties, the form value is converted to the
                appropriate

            Any of the form variables may be prefixed with a classname or
            designator.

            Two special form values are supported for backwards
            compatibility:

            @note
                This is equivalent to::

                    @link@messages=msg-1
                    msg-1@content=value

                except that in addition, the "author" and "date"
                properties of "msg-1" are set to the userid of the
                submitter, and the current time, respectively.

            @file
                This is equivalent to::

                    @link@files=file-1
                    file-1@content=value

                The String content value is handled as described above for
                file uploads.
                If "multiple" is turned on for file uploads in the html
                template, multiple links are generated::

                    @link@files=file-2
                    file-2@content=value
                    ...

                depending on how many files the user has attached.

            If both the "@note" and "@file" form variables are
            specified, the action::

                    @link@msg-1@files=file-1

            is also performed. If "multiple" is specified this is
            carried out for each of the attached files.

            We also check that FileClass items have a "content" property with
            actual content, otherwise we remove them from all_props before
            returning.

            The return from this method is a dict of
                (classname, id): properties
            ... this dict _always_ has an entry for the current context,
            even if it's empty (ie. a submission for an existing issue that
            doesn't result in any changes would return {('issue','123'): {}})
            The id may be None, which indicates that an item should be
            created.
        """
        # some very useful variables
        db = self.db
        form = self.form

        if not hasattr(self, 'FV_SPECIAL'):
            # generate the regexp for handling special form values
            classes = '|'.join(db.classes.keys())
            # specials for parsePropsFromForm
            # handle the various forms (see unit tests)
            self.FV_SPECIAL = re.compile(self.FV_LABELS % classes, re.VERBOSE)
            self.FV_DESIGNATOR = re.compile(r'(%s)([-\d]+)' % classes)

        # these indicate the default class / item
        default_cn = self.classname
        default_cl = self.db.classes[default_cn]
        default_nodeid = self.nodeid

        # we'll store info about the individual class/item edit in these
        all_required = {}       # required props per class/item
        all_props = {}          # props to set per class/item
        got_props = {}          # props received per class/item
        all_propdef = {}        # note - only one entry per class
        all_links = []          # as many as are required

        # we should always return something, even empty, for the context
        all_props[(default_cn, default_nodeid)] = {}

        keys = form.keys()
        timezone = db.getUserTimezone()

        # sentinels for the :note and :file props
        have_note = have_file = 0

        # extract the usable form labels from the form
        matches = []
        for key in keys:
            m = self.FV_SPECIAL.match(key)
            if m:
                matches.append((key, m.groupdict()))

        # now handle the matches
        for key, d in matches:
            if d['classname']:
                # we got a designator
                cn = d['classname']
                cl = self.db.classes[cn]
                nodeid = d['id']
                propname = d['propname']
            elif d['note']:
                # the special note field
                cn = 'msg'
                cl = self.db.classes[cn]
                nodeid = '-1'
                propname = 'content'
                all_links.append((default_cn, default_nodeid, 'messages',
                                  [('msg', '-1')]))
                have_note = 1
            elif d['file']:
                # the special file field
                cn = default_cn
                cl = default_cl
                nodeid = default_nodeid
                propname = 'files'
            else:
                # default
                cn = default_cn
                cl = default_cl
                nodeid = default_nodeid
                propname = d['propname']

            # the thing this value relates to is...
            this = (cn, nodeid)

            # skip implicit create if this isn't a create action
            if not create and nodeid is None:
                continue

            # get more info about the class, and the current set of
            # form props for it
            if cn not in all_propdef:
                all_propdef[cn] = cl.getprops()
            propdef = all_propdef[cn]
            if this not in all_props:
                all_props[this] = {}
            props = all_props[this]
            if this not in got_props:
                got_props[this] = {}

            # is this a link command?
            if d['link']:
                value = []
                for entry in self.extractFormList(form[key]):
                    m = self.FV_DESIGNATOR.match(entry)
                    if not m:
                        raise FormError(self._(
                            'link "%(key)s" '
                            'value "%(entry)s" not a designator') % locals())
                    value.append((m.group(1), m.group(2)))

                    # get details of linked class
                    lcn = m.group(1)
                    lcl = self.db.classes[lcn]
                    lnodeid = m.group(2)
                    if lcn not in all_propdef:
                        all_propdef[lcn] = lcl.getprops()
                    if (lcn, lnodeid) not in all_props:
                        all_props[(lcn, lnodeid)] = {}
                    if (lcn, lnodeid) not in got_props:
                        got_props[(lcn, lnodeid)] = {}

                # make sure the link property is valid
                if (not isinstance(propdef[propname], hyperdb.Multilink) and
                        not isinstance(propdef[propname], hyperdb.Link)):
                    raise FormError(self._(
                        '%(class)s %(property)s '
                        'is not a link or multilink property') % {
                            'class': cn, 'property': propname})

                all_links.append((cn, nodeid, propname, value))
                continue

            # detect the special ":required" variable
            if d['required']:
                for entry in self.extractFormList(form[key]):
                    m = self.FV_SPECIAL.match(entry)
                    if not m:
                        raise FormError(self._(
                            'The form action claims to '
                            'require property "%(property)s" '
                            'which doesn\'t exist') % {
                                'property': propname})
                    if m.group('classname'):
                        this = (m.group('classname'), m.group('id'))
                        entry = m.group('propname')
                    if this not in all_required:
                        all_required[this] = []
                    all_required[this].append(entry)
                continue

            # see if we're performing a special multilink action
            mlaction = 'set'
            if d['remove']:
                mlaction = 'remove'
            elif d['add']:
                mlaction = 'add'

            # does the property exist?
            if propname not in propdef:
                if mlaction != 'set':
                    raise FormError(self._(
                        'You have submitted a %(action)s '
                        'action for the property "%(property)s" '
                        'which doesn\'t exist') % {
                            'action': mlaction, 'property': propname})
                # the form element is probably just something we don't care
                # about - ignore it
                continue
            proptype = propdef[propname]

            # Get the form value. This value may be a MiniFieldStorage
            # or a list of MiniFieldStorages.
            value = form[key]

            # handle unpacking of the MiniFieldStorage / list form value
            if d['file']:
                assert isinstance(proptype, hyperdb.Multilink)
                # value is a file upload... we *always* handle multiple
                # files here (html5)
                if not isinstance(value, type([])):
                    value = [value]
            elif isinstance(proptype, hyperdb.Multilink):
                value = self.extractFormList(value)
            else:
                # multiple values are not OK
                if isinstance(value, type([])):
                    raise FormError(self._(
                        'You have submitted more than one '
                        'value for the %s property') % propname)
                # value might be a single file upload
                if not getattr(value, 'filename', None):
                    value = value.value.strip()

            # now that we have the props field, we need a teensy little
            # extra bit of help for the old :note field...
            if d['note'] and value:
                props['author'] = self.db.getuid()
                props['date'] = date.Date()

            # handle by type now
            if isinstance(proptype, hyperdb.Password):
                if not value:
                    # ignore empty password values
                    continue
                if d['confirm']:
                    # ignore the "confirm" password value by itself
                    continue
                for key, d in matches:
                    if d['confirm'] and d['propname'] == propname:
                        confirm = form[key]
                        break
                else:
                    raise FormError(self._('Password and confirmation text '
                                           'do not match'))
                if isinstance(confirm, type([])):
                    raise FormError(self._(
                        'You have submitted more than one '
                        'value for the %s property') % propname)
                if value != confirm.value:
                    raise FormError(self._('Password and confirmation text '
                                           'do not match'))
                try:
                    value = password.Password(value, scheme=proptype.scheme,
                                              config=self.db.config)
                except hyperdb.HyperdbValueError as msg:
                    raise FormError(msg)
            elif d['file']:
                # This needs to be a Multilink and is checked above
                fcn = 'file'
                fcl = self.db.classes[fcn]
                fpropname = 'content'
                if fcn not in all_propdef:
                    all_propdef[fcn] = fcl.getprops()
                fpropdef = all_propdef[fcn]
                have_file = []
                for n, v in enumerate(value):
                    if not hasattr(v, 'filename'):
                        raise FormError(self._('Not a file attachment'))
                    # skip if the upload is empty
                    if not v.filename:
                        continue
                    fnodeid = str(-(n+1))
                    have_file.append(fnodeid)
                    fthis = (fcn, fnodeid)
                    if fthis not in all_props:
                        all_props[fthis] = {}
                    fprops = all_props[fthis]
                    all_links.append((cn, nodeid, 'files',
                                      [('file', fnodeid)]))

                    fprops['content'] = self.parse_file(fpropdef, fprops, v)
                value = None
                nodeid = None
            elif isinstance(proptype, hyperdb.Multilink):
                # convert input to list of ids
                try:
                    id_list = hyperdb.rawToHyperdb(self.db, cl, nodeid,
                                                   propname, value)
                except hyperdb.HyperdbValueError as msg:
                    raise FormError(msg)

                # now use that list of ids to modify the multilink
                if mlaction == 'set':
                    value = id_list
                else:
                    # we're modifying the list - get the current list of ids
                    if propname in props:
                        existing = props[propname]
                    elif nodeid and not nodeid.startswith('-'):
                        existing = cl.get(nodeid, propname, [])
                    else:
                        existing = []

                    # now either remove or add
                    if mlaction == 'remove':
                        # remove - handle situation where the id isn't in
                        # the list
                        for entry in id_list:
                            try:
                                existing.remove(entry)
                            except ValueError:
                                raise FormError(self._(
                                    'property '
                                    '"%(propname)s": "%(value)s" '
                                    'not currently in list') % {
                                        'propname': propname, 'value': entry})
                    else:
                        # add - easy, just don't dupe
                        for entry in id_list:
                            if entry not in existing:
                                existing.append(entry)
                    value = existing
                    # Sort the value in the same order used by
                    # Multilink.from_raw.
                    value.sort(key=int)

            elif value == '' or value == b'':
                # other types should be None'd if there's no value
                value = None
            else:
                # handle all other types
                try:
                    # Try handling file upload
                    if (isinstance(proptype, hyperdb.String) and
                            hasattr(value, 'filename') and
                            value.filename is not None):
                        value = self.parse_file(propdef, props, value)
                    else:
                        value = hyperdb.rawToHyperdb(self.db, cl, nodeid,
                                                     propname, value)
                except hyperdb.HyperdbValueError as msg:
                    raise FormError(msg)

            # register that we got this property
            if isinstance(proptype, hyperdb.Multilink):
                if value != []:
                    got_props[this][propname] = 1
            elif value is not None:
                got_props[this][propname] = 1

            # get the old value
            if nodeid and not nodeid.startswith('-'):
                try:
                    existing = cl.get(nodeid, propname)
                except KeyError:
                    # this might be a new property for which there is
                    # no existing value
                    if propname not in propdef:
                        raise
                except IndexError as message:
                    raise FormError(str(message))

                # make sure the existing multilink is sorted.  We must
                # be sure to use the same sort order in all places,
                # since we want to compare values with "=" or "!=".
                # The canonical order (given in Multilink.from_raw) is
                # by the numeric value of the IDs.
                if isinstance(proptype, hyperdb.Multilink):
                    existing.sort(key=int)

                # "missing" existing values may not be None
                if not existing:
                    if isinstance(proptype, hyperdb.String):
                        # some backends store "missing" Strings as
                        # empty strings
                        if existing == self.db.BACKEND_MISSING_STRING:
                            existing = None
                    elif (isinstance(proptype, hyperdb.Number) or
                          isinstance(proptype, hyperdb.Integer)):
                        # some backends store "missing" Numbers as 0 :(
                        if existing == self.db.BACKEND_MISSING_NUMBER:
                            existing = None
                    elif isinstance(proptype, hyperdb.Boolean):
                        # likewise Booleans
                        if existing == self.db.BACKEND_MISSING_BOOLEAN:
                            existing = None

                # if changed, set it
                if value != existing:
                    props[propname] = value
            else:
                # don't bother setting empty/unset values
                if value is None:
                    continue
                elif isinstance(proptype, hyperdb.Multilink) and value == []:
                    continue
                elif isinstance(proptype, hyperdb.String) and value == '':
                    continue

                props[propname] = value

        # check to see if we need to specially link files to the note
        if have_note and have_file:
            for fid in have_file:
                all_links.append(('msg', '-1', 'files', [('file', fid)]))

        # see if all the required properties have been supplied
        s = []
        for thing, required in all_required.items():
            # register the values we got
            got = got_props.get(thing, {})
            for entry in required[:]:
                if entry in got:
                    required.remove(entry)

            # If a user doesn't have edit permission for a given property,
            # but the property is already set in the database, we don't
            # require a value.
            if not (create or nodeid is None):
                for entry in required[:]:
                    if not self.db.security.hasPermission('Edit',
                                                          self.client.userid,
                                                          self.classname,
                                                          entry):
                        cl = self.db.classes[self.classname]
                        if cl.get(nodeid, entry) is not None:
                            required.remove(entry)

            # any required values not present?
            if not required:
                continue

            # tell the user to entry the values required
            s.append(self.ngettext(
                'Required %(class)s property %(property)s not supplied',
                'Required %(class)s properties %(property)s not supplied',
                len(required)
            ) % {
                'class': self._(thing[0]),
                'property': ', '.join(map(self.gettext, required))
            })
        if s:
            raise FormError('\n'.join(s))

        # When creating a FileClass node, it should have a non-empty content
        # property to be created. When editing a FileClass node, it should
        # either have a non-empty content property or no property at all. In
        # the latter case, nothing will change.
        for (cn, id), props in list(all_props.items()):
            if id is not None and id.startswith('-') and not props:
                # new item (any class) with no content - ignore
                del all_props[(cn, id)]
            elif isinstance(self.db.classes[cn], hyperdb.FileClass):
                # three cases:
                # id references existng file. If content is empty,
                #    remove content from form so we don't wipe
                #    existing file contents.
                # id is -1, -2 ... I.E. a new file.
                #  if content is not defined remove all fields that
                #     reference that file.
                #  if content is defined, let it pass through even if
                #     content is empty. Yes people can upload/create
                #     empty files.
                if 'content' in props:
                    if id is not None and \
                       not id.startswith('-') and \
                       not props['content']:
                        # This is an existing file with emtpy content
                        # value in the form.
                        del props['content']
                else:
                    # this is a new file without any content property.
                    if id is not None and id.startswith('-'):
                        del all_props[(cn, id)]
                # if this is a new file with content (even 0 length content)
                # allow it through and create the zero length file.
        return all_props, all_links

    def parse_file(self, fpropdef, fprops, v):
        # try to determine the file content-type
        fn = v.filename.split('\\')[-1]
        if 'name' in fpropdef:
            fprops['name'] = fn
        # use this info as the type/filename properties
        if 'type' in fpropdef:
            if hasattr(v, 'type') and v.type:
                fprops['type'] = v.type
            elif mimetypes.guess_type(fn)[0]:
                fprops['type'] = mimetypes.guess_type(fn)[0]
            else:
                fprops['type'] = "application/octet-stream"
        # finally, read the content RAW
        return v.value

    def extractFormList(self, value):
        ''' Extract a list of values from the form value.

            It may be one of:
             [MiniFieldStorage('value'),
             MiniFieldStorage('value','value',...), ...]
             MiniFieldStorage('value,value,...')
             MiniFieldStorage('value')
        '''
        # multiple values are OK
        if isinstance(value, type([])):
            # it's a list of MiniFieldStorages - join then into
            values = ','.join([i.value.strip() for i in value])
        else:
            # it's a MiniFieldStorage, but may be a comma-separated list
            # of values
            values = value.value

        value = [i.strip() for i in values.split(',')]

        # filter out the empty bits
        return list(filter(None, value))

# vim: set et sts=4 sw=4 :
