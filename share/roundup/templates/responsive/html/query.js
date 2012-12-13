var action;

function display(data)
{
  var list = $("div.list");
  list.empty();
  list.append(data);
}

// Run a query with a specific starting point and size
function query_start(start, size)
{
  var inputs = $(":input");
  var data = {}
  if (start > 0) data['@startwith'] = start
  if (size > -1) data['@pagesize'] = size
  for (var i = 0; i < inputs.length; i++)
    data[inputs[i].name] = inputs[i].value;
  jQuery.get(action, data, display);
  return false;
}

// Run a query, starting at the first element
function query()
{
  return query_start(0, -1)
}

// Deactivate the form's submit action, and instead
// invoke the action as part of (inline) query.
function replace_submit()
{
  var form = $("form");
  action = form.attr("action");
  form.attr("action",""); // reset
  form.submit(query);
}


$(document).ready(replace_submit);
