# This module is free software, you may redistribute it
# and/or modify under the same terms as Python.

WINDOW_CONTENT = r'''
<h3>Keyword Expression Editor:</h3>
<hr/>
<div id="content"></div>
<script nonce="%(nonce)s" type="text/javascript">
<!--

var NOT_OP = "-2";
var AND_OP = "-3";
var OR_OP  = "-4";

var original = "%(original)s";
var current = original;
var undo = [];

var KEYWORDS = [
    %(keywords)s
];

function find_keyword(x) {
    for (var i = 0; i < KEYWORDS.length; ++i) {
        if (KEYWORDS[i][0] == x) {
            return KEYWORDS[i][1];
        }
    }
    return "unknown";
}

function Equals(x) {
    this.x = x;
    this.brackets = false;

    this.infix = function() {
        return find_keyword(this.x);
    }

    this.postfix = function() {
        return this.x;
    }
}

function Not(x) {
    this.x = x;
    this.brackets = false;

    this.infix = function() {
        return this.x.brackets 
            ? "NOT(" + this.x.infix() + ")"
            : "NOT " + this.x.infix();
    }

    this.postfix = function() {
        return this.x.postfix() + "," + NOT_OP;
    }
}

function And(x, y) {
    this.x = x;
    this.y = y;
    this.brackets = true;

    this.infix = function() {
        var a = this.x.brackets ? "(" + this.x.infix() + ")" : this.x.infix();
        var b = this.y.brackets ? "(" + this.y.infix() + ")" : this.y.infix();
        return a + " AND " + b;
    }
    this.postfix = function() {
        return this.x.postfix() + "," + this.y.postfix() + "," + AND_OP;
    }
}

function Or(x, y) {
    this.x = x;
    this.y = y;
    this.brackets = true;

    this.infix = function() {
        var a = this.x.brackets ? "(" + this.x.infix() + ")" : this.x.infix();
        var b = this.y.brackets ? "(" + this.y.infix() + ")" : this.y.infix();
        return a + " OR " + b;
    }

    this.postfix = function() {
        return this.x.postfix() + "," + this.y.postfix() + "," + OR_OP;
    }
}

function trim(s) {
    return s.replace (/^\s+/, '').replace(/\s+$/, '');
}

function parse(s) {
    var operators = s.split(",");
    var stack = [];
    for (var i = 0; i < operators.length; ++i) {
        var operator = trim(operators[i]);
        if (operator == "") continue;
        if (operator == NOT_OP) {
            stack.push(new Not(stack.pop()));
        }
        else if (operator == AND_OP) {
            var a = stack.pop();
            var b = stack.pop();
            stack.push(new And(b, a));
        }
        else if (operator == OR_OP) {
            var a = stack.pop();
            var b = stack.pop();
            stack.push(new Or(b, a));
        }
        else {
            stack.push(new Equals(operator));
        }
    }
    return stack.length > 0 ? stack.pop() : null;
}

function render_select(handler) {
    var out = '<select name="keyword" id="keyword"';
    if (handler != null) {
        out += ' onchange="' + handler + '"';
    }
    out += '>';
    out += '<option value="-1"><\/option>';
    for (var i = 0; i < KEYWORDS.length; ++i) {
        out += '<option value="' + KEYWORDS[i][0] + 
               '">' + KEYWORDS[i][1] + "<\/option>";
    }
    out += '<\/select>';
    return out;
}

function first_select() {
    var value = document.getElementById("keyword").value;
    current = value;
    set_content();
}

function not_clicked() {
    var expr = parse(current);
    if (expr == null) return;
    undo.push(current);
    current = expr instanceof Not
        ? expr.x.postfix()
        : new Not(expr).postfix();
    set_content();
}

function not_b_wrap(expr) {
    var value = document.getElementById("not_b").checked;
    return value ? new Not(expr) : expr;
}

function and_clicked() {
    var expr = parse(current);
    if (expr == null) return;
    var value = document.getElementById("keyword").value;
    if (value == "-1") return;
    undo.push(current);
    current = new And(expr, not_b_wrap(new Equals(value))).postfix();
    set_content();
}

function or_clicked() {
    var expr = parse(current);
    if (expr == null) return;
    var value = document.getElementById("keyword").value;
    if (value == "-1") return;
    undo.push(current);
    current = new Or(expr, not_b_wrap(new Equals(value))).postfix();
    set_content();
}

function undo_clicked() {
    current = undo.length > 0 
        ? undo.pop()
        : original;
    set_content();
}

function enable_and_or() {
    var value = document.getElementById("keyword").value;
    value = value == "-1";
    document.getElementById("and").disabled = value;
    document.getElementById("or").disabled = value;
    document.getElementById("not_b").disabled = value;
}

function create() {
    var expr = parse(current);
    var out = "";
    if (expr == null) {
        out += "Keyword: ";
        out += render_select("first_select();");
    }
    else {
        out += '<table><tr>'
        out += '<td><input type="button" name="not" onclick="not_clicked();" value="NOT"\/><\/td>';
        out += "<td><tt><strong>" + expr.infix() + "<\/strong><\/tt><\/td>";
        out += '<td><table>';
        out += '<tr><td><input type="button" id="and" name="and" onclick="and_clicked();"'
            +  ' value="AND" disabled="disabled"\/><\/td><\/tr>';
        out += '<tr><td><input type="button" id="or" name="or" onclick="or_clicked();"'
            +  ' value="OR" disabled="disabled"\/><\/td><\/tr>';
        out += '<\/table><\/td>';
        out += '<td><label for="not_b">NOT<\/label><br/>'
            +  '<input type="checkbox" name="not_b" id="not_b" disabled="disabled"\/><\/td>';
        out += '<td>' + render_select("enable_and_or();") + '<\/td>';
        out += '<\/tr><\/table>'
    }
    out += '<hr\/>';
    if (undo.length > 0 || (undo.length == 0 && current != original)) {
        out += '<input type="button" onclick="undo_clicked();" value="Undo"\/>';
    }
    out += '<input type="button" onclick="modify_main();" value="Apply"\/>'
        +  '<input type="button" onclick="window.close();" value="Close Window"\/>';
    return out;
}

function main_display() {
    var out = '';
    out += '<span id="display_%(prop)s">' + parse(current).infix() + '<\/span>';
    return out;
}

function main_input() {
    var out = '';
    out += '<input type="hidden" name="%(prop)s" value="' + current + '"\/>';
    return out;
}

function modify_main() {
    /* if display form of expression exists, overwrite */
    display = window.opener.document.getElementById('display_%(prop)s');
    if ( display ) {
      display.outerHTML = main_display();
    }

    /* overwrite select if present, otherwise overwrite the hidden input */
    input = window.opener.document.querySelector('select[name="%(prop)s"]');
    if (! input) {
       input = window.opener.document.querySelector('input[name="%(prop)s"]');
    }

    /* if display exists, only update hidden input. If display doesn't
       exist, inject both hidden input and display. */
    if ( display ) {
       content = main_input();
    } else {
       content = main_input() + main_display();
    }
    input.outerHTML = content;
}

function set_content() {
    document.getElementById("content").innerHTML = create();
}

set_content();
//-->
</script>
'''


def list_nodes(request):
    prop = request.form.getfirst("property")
    cls = request.client.db.getclass(prop)
    items = []
    for nodeid in cls.getnodeids(retired=0):
        l = cls.getnode(nodeid).items()
        l = dict([x for x in l if len(x) == 2])
        try:
            items.append((l['id'], l['name']))
        except KeyError:
            pass
    items.sort(key=lambda x: int(x[0]))
    return items


def items_to_keywords(items):
    return ',\n    '.join(['["%s", "%s"]' % x for x in items])


def render_keywords_expression_editor(request):
    prop = request.form.getfirst("property")

    window_content = WINDOW_CONTENT % {
        'prop': prop,
        'keywords': items_to_keywords(list_nodes(request)),
        'original': '',
        'nonce': request.client.client_nonce
    }

    return window_content

# vim: set et sts=4 sw=4 :
