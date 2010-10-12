// Inspect a form element to construct a 'get' request,
// register it to the 'submit' event, and deactivate the
// form's submit action.
function bind_search()
{
  var form = $("form");
  var action = form.attr("action");
  form.attr("action",""); // reset

  function display(data)
  {
    var list = $("div.list");
    list.empty();
    list.append(data);
  }

  function query()
  {
    var inputs = $(":input");
    var data = {}
    for (var i = 0; i < inputs.length; i++)
      data[inputs[i].name] = inputs[i].value;
    jQuery.get(action, data, display);
    return false;
  }

  form.submit(query);
}


$(document).ready(bind_search);
