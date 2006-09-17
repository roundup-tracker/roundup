// initial values for either Nosy, Superseder, Topic and Waiting On,
// depending on which has called
original_field = form[field].value;

// Some browsers (ok, IE) don't define the "undefined" variable.
undefined = document.geez_IE_is_really_friggin_annoying;

function trim(value) {
  var temp = value;
  var obj = /^(\s*)([\W\w]*)(\b\s*$)/;
  if (obj.test(temp)) { temp = temp.replace(obj, '$2'); }
  var obj = /  /g;
  while (temp.match(obj)) { temp = temp.replace(obj, " "); }
  return temp;
}

function determineList() {
     // generate a comma-separated list of the checked items
     var list = new String('');
 
     // either a checkbox object or an array of checkboxes
     var check = document.frm_help.check;
 
     if ((check.length == undefined) && (check.checked != undefined)) {
         // only one checkbox on page
         if (check.checked) {
             list = check.value;
         }
     } else {
         // array of checkboxes
         for (box=0; box < check.length; box++) {
             if (check[box].checked) {
                 if (list.length == 0) {
                     separator = '';
                 }
                 else {
                     separator = ',';
                 }
                 // we used to use an Array and push / join, but IE5.0 sux
                 list = list + separator + check[box].value;
             }
         }
     }
     return list;  
}

/**
 * update the field in the opening window;
 * the text_field variable must be set in the calling page
 */
function updateOpener() {
  // write back to opener window
  if (document.frm_help.check==undefined) { return; }
  form[field].value = text_field.value;
}

function updateList() {
  // write back to opener window
  if (document.frm_help.check==undefined) { return; }
  form[field].value = determineList();
}

function updatePreview() {
  // update the preview box
  if (document.frm_help.check==undefined) { return; }
  writePreview(determineList());
}

function clearList() {
  // uncheck all checkboxes
  if (document.frm_help.check==undefined) { return; }
  for (box=0; box < document.frm_help.check.length; box++) {
      document.frm_help.check[box].checked = false;
  }
}

function reviseList_framed(form, textfield) {
  // update the checkboxes based on the preview field
  // alert('reviseList_framed')
  // alert(form)
  if (form.check==undefined)
      return;
  // alert(textfield)
  var to_check;
  var list = textfield.value.split(",");
  if (form.check.length==undefined) {
      check = form.check;
      to_check = false;
      for (val in list) {
          if (check.value==trim(list[val])) {
              to_check = true;
              break;
          }
      }
      check.checked = to_check;
  } else {
    for (box=0; box < form.check.length; box++) {
      check = form.check[box];
      to_check = false;
      for (val in list) {
          if (check.value==trim(list[val])) {
              to_check = true;
              break;
          }
      }
      check.checked = to_check;
    }
  }
}

function reviseList(vals) {
  // update the checkboxes based on the preview field
  if (document.frm_help.check==undefined) { return; }
  var to_check;
  var list = vals.split(",");
  if (document.frm_help.check.length==undefined) {
      check = document.frm_help.check;
      to_check = false;
      for (val in list) {
          if (check.value==trim(list[val])) {
              to_check = true;
              break;
          }
      }
      check.checked = to_check;
  } else {
    for (box=0; box < document.frm_help.check.length; box++) {
      check = document.frm_help.check[box];
      to_check = false;
      for (val in list) {
          if (check.value==trim(list[val])) {
              to_check = true;
              break;
          }
      }
      check.checked = to_check;
    }
  }
}

function resetList() {
  // reset preview and check boxes to initial values
  if (document.frm_help.check==undefined) { return; }
  writePreview(original_field);
  reviseList(original_field);
}

function writePreview(val) {
   // writes a value to the text_preview
   document.frm_help.text_preview.value = val;
}

function focusField(name) {
    for(i=0; i < document.forms.length; ++i) {
      var obj = document.forms[i].elements[name];
      if (obj && obj.focus) {obj.focus();}
    }
}

function selectField(name) {
    for(i=0; i < document.forms.length; ++i) {
      var obj = document.forms[i].elements[name];
      if (obj && obj.focus){obj.focus();} 
      if (obj && obj.select){obj.select();}
    }
}

function checkRequiredFields(fields)
{
    var bonk='';
    var res='';
    var argv = checkRequiredFields.arguments;
    var argc = argv.length;
    var input = '';
    var val='';

    for (var i=0; i < argc; i++) {
        fi = argv[i];
        input = document.getElementById(fi);
        if (input) {
            val = input.value
            if (val == '' || val == '-1' || val == -1) {
                if (res == '') {
                    res = fi;
                    bonk = input;
                } else {
                    res += ', '+fi;
                }
            }
        } else {
            alert('Field with id='+fi+' not found!')
        }
    }
    if (res == '') {
        return submit_once();
    } else {
        alert('Missing value here ('+res+')!');
        if (window.event && window.event.returnvalue) {
            event.returnValue = 0;    // work-around for IE
        }
        bonk.focus();
        return false;
    }
}

