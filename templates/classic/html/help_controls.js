// initial values for either Nosy, Superseder, Topic and Waiting On,
// depending on which has called

original_field = window.opener.document.itemSynopsis[field].value;


// pop() and push() methods for pre5.5 IE browsers

function bName() {
    // test for IE 
    if (navigator.appName == "Microsoft Internet Explorer")
      return 1;
    return 0;
}

function bVer() {
    // return version number (e.g., 4.03)
    msieIndex = navigator.appVersion.indexOf("MSIE") + 5;
    return(parseFloat(navigator.appVersion.substr(msieIndex,3)));
}

function pop() {
    // make a pop method for old IE browsers
    var lastElement = this[this.length - 1];
    this.length--;
    return lastElement;
}

function push() {
    // make a pop method for old IE browsers
    var sub = this.length;
    for (var i = 0; i < push.arguments.length; ++i) {
      this[sub] = push.arguments[i];
        sub++;
  }
}

// add the pop() and push() method to Array prototype for old IE browser
if (bName() == 1 && bVer() >= 5.5);
else {
    Array.prototype.pop = pop;
    Array.prototype.push = push;
}

function trim(value) {
  var temp = value;
  var obj = /^(\s*)([\W\w]*)(\b\s*$)/;
  if (obj.test(temp)) { temp = temp.replace(obj, '$2'); }
  var obj = /  /g;
  while (temp.match(obj)) { temp = temp.replace(obj, " "); }
  return temp;
}

function updateList() {
  // write back to opener window
  var list = new Array();
  for (box=0; box < document.frm_help.check.length; box++) {
      if (document.frm_help.check[box].checked) {
          list.push(document.frm_help.check[box].value);
      }
  }
  window.opener.document.itemSynopsis[field].value = list.join(",");
}

function updatePreview() {
  // add new checkbox selections to preview
  var list = new Array();
  for (box=0; box < document.frm_help.check.length; box++) {
      if (document.frm_help.check[box].checked) {
          list.push(document.frm_help.check[box].value);
      }
  }
  listString = new String(list.join(','));
  writePreview(listString);
}

function clearList() {
  // uncheck all checkboxes
  for (box=0; box < document.frm_help.check.length; box++) {
      document.frm_help.check[box].checked = false;
  }
}

function reviseList(vals) {
  // update the checkboxes based on the preview field
  var to_check;
  var list = vals.split(",");
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

function resetList() {
  // reset preview and check boxes to initial values
  var to_check;
  var list = original_field.split(',');
  writePreview(list);
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

