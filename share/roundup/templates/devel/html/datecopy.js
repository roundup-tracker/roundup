/* Capture double-click on a date element. Turn element in text element
   and select date for copying. Return to date element saving change on
   focusout or Enter. Return to date element with original value on Escape.
   Derived from
   https://stackoverflow.com/questions/49981660/enable-copy-paste-on-html5-date-field
*/

/* TODO: keyboard support should be added to allow entering text mode. */

// use iife to encapsulate handleModeExitKeys
(function () {
  "use strict";

  // Define named function so it can be added/removed as event handler
  //   in different scopes of the code
  function handleModeExitKeys (event) {
    if (event.key !== "Escape" && event.key !== "Enter") return;
    event.preventDefault();
    if (event.key === "Escape") {
	event.target.value = event.target.original_value;
    }
    let focusout = new Event("focusout");
    event.target.dispatchEvent(focusout);
  }


  document.querySelector("body").addEventListener("dblclick", (evt) => {
    if (evt.target.tagName !== "INPUT") return;

    if (! ["date", "datetime-local"].includes(
	evt.target.attributes.type.value.toLowerCase())) return;

    // we have a date type input
    let target = evt.target;
    let original_type = target.attributes.type.value;
    target.type = "text";

    target.original_value = target.value;

    // allow admin to set CSS to change input
    target.classList.add("mode_textdate");
    // After changing input type with JS .select() won't
    // work as usual
    // Needs timeout fn() to make it work
    setTimeout(() => {
	target.select();
    });

    // register the focusout event to reset the input back
    // to a date input field. Once it triggers the handler
    // is deleted to be added on the next doubleclick.
    // This also should end the closure of original_type.
    target.addEventListener("focusout", () => {
	target.type = original_type;
	delete event.target.original_value;

	target.classList.remove("mode_textdate");

	target.removeEventListener("keydown", handleModeExitKeys);
    }, {once: true});

    // called on every keypress including editing the field,
    // so can not be set with "once" like "focusout".
    target.addEventListener("keydown", handleModeExitKeys);
  });
})()

/* Some failed experiments that I would have liked to have work */
/* With the date element focused, type ^c or ^v to copy/paste
   evt.target always seems to be inconsistent. Sometimes I get the
   input but usually I get the body.

   I can find the date element using document.activeElement, but
   this seems like a kludge.
 */
/*
body.addEventListener("copy", (evt) => {
    // target = document.activeElement;
    target = evt.target;
    if (target.tagName != "INPUT") {
	//alert("copy received non-date"  + target.tagName);
	return;
    }

    if (! ["date", "datetime-local"].includes(
	    target.attributes.type.value)) {
	//alert("copy received non-date");
	return;
	}

    evt.clipboardData.setData("text/plain",
			      target.value);
    // default behaviour is to copy any selected text
    // overwriting what we set
    evt.preventDefault();
    //alert("copy received date");
})

body.addEventListener("paste", (evt) => {
    if (evt.target.tagName != "INPUT") {
	//alert("paste received non-date");
	return;
    }

    if (! ["date", "datetime-local"].includes(
	    evt.target.attributes.type.value)) {
	//alert("paste received non-date");
	return;
	}

    data = evt.clipboardData.getData("text/plain");
    evt.preventDefault();
    evt.target.value = data;
    //alert("paste received date " + data);
})
*/
