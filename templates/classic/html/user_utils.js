// User Editing Utilities

/**
 * for new users:
 * Depending on the input field which calls it, takes the value
 * and dispatches it to certain other input fields:
 *
 * address
 *  +-> username
 *  |    `-> realname
 *  `-> organisation
 */
function split_name(that) {
    var raw = that.value
    var val = trim(raw)
    if (val == '') {
        return
    }
    var username=''
    var realname=''
    var address=''
    switch (that.name) {
        case 'address':
            address=val
            break
        case 'username':
            username=val
            break
        case 'realname':
            realname=val
            break
        case 'firstname':
        case 'lastname':
           return
        default:
            alert('Ooops - unknown name field '+that.name+'!')
            return
    }
    var the_form = that.form;

    function field_empty(name) {
        return the_form[name].value == ''
    }

    // no break statements - on purpose!
    switch (that.name) {
        case 'address':
            var split1 = address.split('@')
            if (field_empty('username')) {
                username = split1[0]
                the_form.username.value = username
            }
            if (field_empty('organisation')) {
                the_form.organisation.value = default_organisation(split1[1])
            }
        case 'username':
            if (field_empty('realname')) {
                realname = Cap(username.split('.').join(' '))
                the_form.realname.value = realname
            }
        case 'realname':
            if (field_empty('username')) {
                username = Cap(realname.replace(' ', '.'))
                the_form.username.value = username
            }
            if (the_form.firstname && the_form.lastname) {
                var split2 = realname.split(' ')
                var firstname='', lastname=''
                firstname = split2[0]
                lastname = split2.slice(1).join(' ')
                if (field_empty('firstname')) {
                    the_form.firstname.value = firstname
                }
                if (field_empty('lastname')) {
                    the_form.lastname.value = lastname
                }
            }
    }
}

function SubCap(str) {
    switch (str) {
        case 'de': case 'do': case 'da':
        case 'du': case 'von':
            return str;
    }
    if (str.toLowerCase().slice(0,2) == 'mc') {
        return 'Mc'+str.slice(2,3).toUpperCase()+str.slice(3).toLowerCase()
    }
    return str.slice(0,1).toUpperCase()+str.slice(1).toLowerCase()
}

function Cap(str) {
    var liz = str.split(' ')
    for (var i=0; i<liz.length; i++) {
        liz[i] = SubCap(liz[i])
    }
    return liz.join(' ')
}

/**
 * Takes a domain name (behind the @ part of an email address)
 * Customise this to handle the mail domains you're interested in 
 */
function default_organisation(orga) {
    switch (orga.toLowerCase()) {
        case 'gmx':
        case 'yahoo':
            return ''
        default:
            return orga
    }
}

