"""
Supplies a Python-2.3 Object Craft csv module work-alike to the extent
needed by Roundup using the Python 2.3 csv module.

"""

from roundup.i18n import _
error = """
Sorry, you need a csv module. Either upgrade your Python to 2.3 or later,
or get and install the csv module from:
http://www.object-craft.com.au/projects/csv/
"""
try:
    import csv
    try:
        reader = csv.reader
        writer = csv.writer
        excel = csv.excel
        error = ''
    except AttributeError:
        # fake it all up using the Object-Craft CSV module
        class excel:
            delimiter = ','
        if hasattr(csv, 'parser'):
            error = ''
            def reader(fileobj, dialect=excel):
                # note real readers take an iterable but 2.1 doesn't
                # support iterable access to file objects.
                result = []
                p = csv.parser(field_sep=dialect.delimiter)

                while 1:
                    line = fileobj.readline()
                    if not line: break
 
                    # parse lines until we get a complete entry
                    while 1:
                        fields = p.parse(line)
                        if fields: break
                        line = fileobj.readline()
                        if not line:
                            raise ValueError, "Unexpected EOF during CSV parse"
                    result.append(fields)
                return result
            class writer:
                def __init__(self, fileobj, dialect=excel):
                    self.fileobj = fileobj
                    self.p = csv.parser(field_sep = dialect.delimiter)
                def writerow(self, fields):
                    print >>self.fileobj, self.p.join(fields)
                def writerows(self, rows):
                    for fields in rows:
                        print >>self.fileobj, self.p.join(fields)

except ImportError:
    class excel:
        pass
       
class colon_separated(excel):
    delimiter = ':' 
class comma_separated(excel):
    delimiter = ',' 


if __name__ == "__main__":
    f=open('testme.txt', 'r')
    r = reader(f, colon_separated)
    remember = []
    for record in r:
        print record
        remember.append(record)
    f.close()
    import sys
    w = writer(sys.stdout, colon_separated)
    w.writerows(remember)

