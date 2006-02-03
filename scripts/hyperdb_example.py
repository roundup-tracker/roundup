from roundup.hyperdb import String, Number, Multilink
from roundup.backends.back_bsddb import Database, Class

class config:
    DATABASE='/tmp/hyperdb_example'

db = Database(config, 'admin')
spam = Class(db, 'spam', name=String(), size=Number())
widget = Class(db, 'widget', title=String(), spam=Multilink('spam'))

oneid = spam.create(name='one', size=1)
twoid = spam.create(name='two', size=2)

widgetid = widget.create(title='a widget', spam=[oneid, twoid])

# dumb, simple query
print widget.find(spam=oneid)
print widget.history(widgetid)
print widget.search_text(
