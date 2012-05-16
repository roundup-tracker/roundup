
def eml_to_mht(db, cl, nodeid, newvalues):
    '''This auditor fires whenever a new file entity is created.

    If the file is of type message/rfc822, we tack onthe extension .eml.

    The reason for this is that Microsoft Internet Explorer will not open
    things with a .eml attachment, as they deem it 'unsafe'. Worse yet,
    they'll just give you an incomprehensible error message. For more 
    information, please see: 

    http://support.microsoft.com/default.aspx?scid=kb;EN-US;825803

    Their suggested work around is (excerpt):

     WORKAROUND

     To work around this behavior, rename the .EML file that the URL
     links to so that it has a .MHT file name extension, and then update
     the URL to reflect the change to the file name. To do this:

     1. In Windows Explorer, locate and then select the .EML file that
        the URL links.
     2. Right-click the .EML file, and then click Rename.
     3. Change the file name so that the .EML file uses a .MHT file name
        extension, and then press ENTER.
     4. Updated the URL that links to the file to reflect the new file
        name extension.

    So... we do that. :)'''
    if newvalues.get('type', '').lower() == "message/rfc822":
        if not newvalues.has_key('name'):
            newvalues['name'] = 'email.mht'
            return
        name = newvalues['name']
        if name.endswith('.eml'):
            name = name[:-4]
        newvalues['name'] = name + '.mht'

def init(db):
    db.file.audit('create', eml_to_mht)

