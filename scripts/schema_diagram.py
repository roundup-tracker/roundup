#! /usr/bin/python
#
# Schema diagram generator contributed by Stefan Seefeld of the fresco
# project http://www.fresco.org/.
#
# It generates a 'dot file' that is then fed into the 'dot'
# tool (http://www.graphviz.org) to generate a graph:
#
# %> ./schema.py
# %> dot -Tps schema.dot -o schema.ps
# %> gv schema.ps
#
from __future__ import print_function
import sys
import roundup.instance

# open the instance
instance = roundup.instance.open(sys.argv[1])
db = instance.open()

# diagram preamble
print('digraph schema {')
print('size="8,6"')
print('node [shape="record" bgcolor="#ffe4c4" style=filled]')
print('edge [taillabel="1" headlabel="1" dir=back arrowtail=ediamond]')

# get all the classes
types = list(db.classes.keys())

# one record node per class
for i in range(len(types)):
    print('node%d [label=\"{%s|}"]'%(i, types[i]))

# now draw in the relations
for name in db.classes.keys():
    type = db.classes[name]
    attributes = type.getprops()
    for a in attributes.keys():
        attribute = attributes[a]
        if isinstance(attribute, roundup.hyperdb.Link):
            print('node%d -> node%d [label=%s]'%(types.index(name),
                                                 types.index(attribute.classname),
                                                 a))
        elif isinstance(attribute, roundup.hyperdb.Multilink):
            print('node%d -> node%d [taillabel="*" label=%s]'%(types.index(name),
                                                 types.index(attribute.classname),
                                                 a))
# all done
print('}')
