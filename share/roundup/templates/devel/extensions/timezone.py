# Utility for replacing the simple input field for the timezone with
# a select-field that lists the available values.

import cgi

try:
    import pytz
except ImportError:
    pytz = None


def tzfield(prop, name, default):
    if pytz:
        value = prop.plain()        
        if '' == value:
            value = default
        else:
            try:
                value = "Etc/GMT%+d" % int(value)
            except ValueError:
                pass

        l = ['<select name="%s">' % name]
        for zone in pytz.all_timezones:
            s = ' '
            if zone == value:
                s = 'selected=selected '
            z = cgi.escape(zone)
            l.append('<option %svalue="%s">%s</option>' % (s, z, z))
        l.append('</select>')
        return '\n'.join(l)
        
    else:
        return prop.field()

def init(instance):
    instance.registerUtil('tzfield', tzfield)
