// initial values for either Nosy, Superseder, Keyword and Waiting On,
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
    for (box=0; box < document.frm_help.check.length; box++) {
        if (document.frm_help.check[box].checked) {
            if (list.length == 0) {
                separator = '';
            }
            else {
                separator = ',';
            }
            // we used to use an Array and push / join, but IE5.0 sux
            list = list + separator + document.frm_help.check[box].value;
        }
    }
    return list;
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

