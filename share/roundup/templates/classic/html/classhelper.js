/**
 * Properties for the ClassHelper component, 
 * made into a type for better readability.
 * @typedef {Object} HelpUrlProps
 * Type of data that needs to be shown (eg. issue, user, keywords) parsed from helpurl
 * @property {string} apiClassName
 * @property {number} width // width of the popup window
 * @property {number} height // height of the popup window
 * The form on which the classhelper is being used
 * @property {string | null} formName
 * The form property on which the classhelper is being used
 * @property {string | null} formProperty
 * @property {string | null} tableSelectionType // it has to be "checkbox" or "radio"(if any)
 * The fields on which the table is sorted
 * @property {string[] | undefined} sort
 * The actual fields to be displayed in the table
 * @property {string[] | undefined} fields
 * @property {number} pageIndex
 * @property {number} pageSize
 */


// change this to true to disable the classhelper
const DISABLE_CLASSHELPER = false

// Let user customize the css file name
const CSS_STYLESHEET_FILE_NAME = "@@file/classhelper.css";

const CLASSHELPER_TAG_NAME = "roundup-classhelper";
const CLASSHELPER_ATTRIBUTE_SEARCH_WITH = "data-search-with";
const CLASSHELPER_ATTRIBUTE_POPUP_TITLE = "data-popup-title";
const CLASSHELPER_ATTRIBUTE_POPUP_TITLE_ITEM_CLASS_LOOKUP = "{className}";
const CLASSHELPER_ATTRIBUTE_POPUP_TITLE_ITEM_DESIGNATOR_LOOKUP = "{itemDesignator}";
const CLASSHELPER_POPUP_FEATURES = (width, height) => `popup=yes,width=${width},height=${height}`;
const CLASSHELPER_POPUP_URL = "about:blank";
const CLASSHELPER_POPUP_TARGET = "_blank";

const CLASSHELPER_READONLY_POPUP_TITLE = "Info on {className} - {itemDesignator} - Classhelper"
const CLASSHELPER_TABLE_SELECTION_NONE = "table-selection-none";
const CLASSHELPER_TRANSLATION_KEYWORDS = ["apply", "cancel", "next", "prev", "search", "reset", CLASSHELPER_READONLY_POPUP_TITLE ];

const ALTERNATIVE_DROPDOWN_PATHNAMES = {
    "roles": "/rest/data/user/roles"
}

/**
 * This is a custom web component(user named html tag) that wraps a helpurl link 
 * and provides additional functionality.
 * 
 * The classhelper is an interactive popup window that displays a table of data.
 * Users can interact with this window to search, navigate and select data from the table.
 * The selected data is either "Id" or "a Value" from the table row.
 * There can be multiple selections in the table.
 * The selected data is then populated in a form field in the main window.
 * 
 * How to use.
 * ------------
 * The helpurl must be wrapped under this web component(user named html tag).
 * ```html
 * <roundup-classhelper data-popup-title="info - {itemDesignator} - Classhelper" data-search-with="title,status[],keyword[]+name">
 *   ( helpurl template here, this can be tal, chameleon, jinja2.
 *     In HTML DOM this is an helpurl anchor tag.
 *    )
 * </roundup-classhelper>
 * ```
 * 
 * The data-search-with attribute of the web component is optional.
 * 
 * data-search-with attribute value is a list of comma separated names of table data fields.
 * (It is possible that a data field is present in search form but absent in the table).
 * 
 * A square parentheses open+close ("[]") can be added to the column name eg."status[]",
 * this will make that search field as a dropdown in the search form in popup window, 
 * then a user can see all the possible values that column can have.
 * 
 * eg. data-search-with="title,status[],keyword[]+name" where status can have values like "open", 
 * "closed" a dropdown will be shown with null, open and closed. This is an aesthetic usage 
 * instead of writing in a text field for options in status.
 * 
 * A plus sign or minus sign with data field can be used to specify the sort order of the dropdown.
 * In the above example, keyword[]+name will sort the dropdown in ascending order(a-z) of name of the keyword.
 * A value keyword[]-name will sort the dropdown in descending order(z-a) of name of the keyword.
 * 
 * data-search-with="<<column name>>[]{+|-}{id|name}"
 * Here column name is required,
 * optionally there can be [] for a dropdown,
 * optionally with "[]" present to a column name there can be 
 * [+ or -] with succeeding "id" or "name" for sorting dropdown.
 * 
 * The data-popup-title attribute of the web component is optional.
 * the value of this attribute is the title of the popup window.
 * the user can use "{itemDesignator}" in the title to replace in the attribute value.
 * and the current context of classhelper will replace "{itemDesignator}".
 * 
 */
class ClassHelper extends HTMLElement {

    static observedAttributes = [CLASSHELPER_ATTRIBUTE_SEARCH_WITH]

    /** @type {Window} handler to popup window */
    popupRef = null;

    /** 
     * Result from making a call to the rest api, for the translation keywords.
     * @type {Object.<string, string>} */
    static translations = null;

    /** 
     * Stores the result from api calls made to rest api,
     * for the parameters in data-search-with attribute of this web component
     * where a parameter is defined as a dropdown in 
     * @type {Object.<string, Map.<string, string>>} */
    dropdownsData = null;

    /** @type {HTMLAnchorElement} */
    helpurl = null;

    /** @type {string} */
    helpurlScript = null;

    /** @type {HelpUrlProps} */
    helpurlProps = null;

    /** 
 * The qualified domain name with protocol and port(if any)
 * with the tracker name if any.
 * eg. http://localhost:8080/demo or https://demo.roundup-tracker.org
 * @type {string} */
    trackerBaseURL = null;

    /** no-op function */
    preventDefault = e => e.preventDefault();

    connectedCallback() {
        try {
            this.helpurl = this.findClassHelpLink();

            // Removing the helpurl click behavior
            this.helpurlScript = this.helpurl.getAttribute("onclick");
            this.helpurl.removeAttribute("onclick", "");
            this.helpurl.addEventListener("click", this.preventDefault);

            this.helpurlProps = ClassHelper.parseHelpUrlProps(this.helpurl);

            this.trackerBaseURL = window.location.href.substring(0, window.location.href.lastIndexOf("/"));

        } catch (err) {
            console.warn("Classhelper not intercepting helpurl.");
            if (this.helpurl != null) {
                this.helpurl.removeEventListener("click", this.preventDefault);
                this.helpurl.setAttribute("onclick", this.helpurlScript);
            }
            console.error(err);
            return;
        }

        const initialRequestURL = ClassHelper.getRestURL(this.trackerBaseURL, this.helpurlProps);

        this.fetchDropdownsData()
            .catch(error => {
                // Top level handling for dropdowns errors.
                console.error(error);
            });

        const cleanUpClosure = () => {
            console.warn("Classhelper not intercepting helpurl.");
            this.removeEventListener("click", handleClickEvent);
            this.helpurl.removeEventListener("click", this.preventDefault);
            this.helpurl.setAttribute("onclick", this.helpurlScript);
        }

        const handleClickEvent = (event) => {
            if (this.popupRef != null && !this.popupRef.closed) {
                this.popupRef.focus();
                return;
            }

            this.openPopUp(initialRequestURL, this.helpurlProps)
                .catch(error => {
                    // Top level error handling for openPopUp method.
                    cleanUpClosure();
                    console.error(error);
                    if (this.popupRef != null) {
                        this.popupRef.close();
                    }
                    window.alert("Error: Failed to open classhelper, check console for more details.");
                    this.helpurl.click();
                });
        };

        const handlePopupReadyEvent = (event) => {
            // we get a document Fragment in event.detail we replace it with the root
            // replaceChild method consumes the documentFragment content, subsequent calls will be no-op.
            if (event.detail.childElementCount === 1) {
                this.popupRef.document.replaceChild(event.detail, this.popupRef.document.documentElement);
            }
        }

        const handleNextPageEvent = (event) => {
            this.pageChange(event.detail.value, this.helpurlProps)
                .catch(error => {
                    // Top level error handling for nextPage method.
                    cleanUpClosure();
                    console.error(error, `request data url: ${event.detail.value}`);
                    if (this.popupRef != null) {
                        this.popupRef.close();
                    }
                    window.alert("Error: Failed to load next page, check console for more details.");
                    this.helpurl.click();
                });
        }

        const handlePrevPageEvent = (event) => {
            this.pageChange(event.detail.value, this.helpurlProps)
                .catch(error => {
                    // Top level error handling for prevPage method.
                    cleanUpClosure();
                    console.error(error, `request data url: ${event.detail.value}`);
                    if (this.popupRef != null) {
                        this.popupRef.close();
                    }
                    window.alert("Error: Failed to load next page, check console for more details.");
                    this.helpurl.click();
                });
        }

        const handleValueSelectedEvent = (event) => {
            // does not throw error
            this.valueSelected(this.helpurlProps, event.detail.value);
        }

        const handleSearchEvent = (event) => {
            this.helpurlProps.pageIndex = 1;
            const searchURL = ClassHelper.getSearchURL(this.trackerBaseURL, this.helpurlProps, event.detail.value);
            this.searchEvent(searchURL, this.helpurlProps)
                .catch(error => {
                    // Top level error handling for searchEvent method.
                    cleanUpClosure();
                    console.error(error, `request data url: ${event.detail.value}`);
                    if (this.popupRef != null) {
                        this.popupRef.close();
                    }
                    window.alert("Error: Failed to load next page, check console for more details.");
                    this.helpurl.click();
                });
        }

        const handleSelectionEvent = (event) => {
            // does not throw error
            this.selectionEvent(event.detail.value);
        }

        this.addEventListener("click", handleClickEvent);
        this.addEventListener("popupReady", handlePopupReadyEvent);
        this.addEventListener("prevPage", handlePrevPageEvent);
        this.addEventListener("nextPage", handleNextPageEvent);
        this.addEventListener("valueSelected", handleValueSelectedEvent);
        this.addEventListener("search", handleSearchEvent);
        this.addEventListener("selection", handleSelectionEvent);
    }

    attributeChangedCallback(name, oldValue, _newValue) {
        if (name === CLASSHELPER_ATTRIBUTE_SEARCH_WITH) {
            if (!oldValue || oldValue === _newValue) {
                return;
            }
            this.fetchDropdownsData().catch(error => {
                // Top level handling for dropdowns errors.
                console.error(error.message);
            });

            let oldForm = this.popupRef.document.getElementById("popup-search");
            let newForm = this.getSearchFragment();
            this.popupRef.document.body.replaceChild(newForm, oldForm);
        }
    }

    static async fetchTranslations() {
        // Singleton implementation
        if (ClassHelper.translations != null) {
            return;
        }

        const keys = new Set();

        const classhelpers = document.getElementsByTagName(CLASSHELPER_TAG_NAME);
        for (let classhelper of classhelpers) {
            if (classhelper.dataset.searchWith) {
                classhelper.dataset.searchWith
                    .split(',')
                    .forEach(param => {
                        keys.add(param.split("[]")[0]);
                    });
            }

	    if (classhelper.dataset.popupTitle) {
		keys.add(classhelper.dataset.popupTitle)
	    }

            const a = classhelper.querySelector("a");
            if (a && a.dataset.helpurl) {
                let searchParams = new URLSearchParams(a.dataset.helpurl.split("?")[1]);
                let properties = searchParams.get("properties");
                if (properties) {
                    properties.split(',').forEach(key => keys.add(key));
                }
            }
        }

        CLASSHELPER_TRANSLATION_KEYWORDS.forEach(key => keys.add(key));

        ClassHelper.translations = {};
        for (let key of keys) {
            ClassHelper.translations[key] = key;
        }

        let tracker = window.location.pathname.split('/')[1];
        let url = new URL(window.location.origin + "/" + tracker + '/');
        url.searchParams.append("@template", "translation");
        url.searchParams.append("properties", Array.from(keys.values()).join(','));

        let resp, json;

        try {
            resp = await fetch(url);
        } catch (error) {
            let message = `Error fetching translations from roundup rest api\n`;
            message += `url: ${url.toString()}\n`;
            throw new Error(message, { cause: error });
        }

        try {
            json = await resp.json();
        } catch (error) {
            let message = `Error parsing json from roundup rest api\n`;
            message += `url: ${url.toString()}\n`;
            throw new Error(message, { cause: error });
        }

        if (!resp.ok) {
            let message = `Unexpected response\n`;
            message += `url: ${url.toString()}\n`;
            message += `response status: ${resp.status}\n`;
            message += `response body: ${JSON.stringify(json)}\n`;
            throw new Error(message);
        }

        for (let entry of Object.entries(json)) {
            ClassHelper.translations[entry[0]] = entry[1];
        }
    }

    async fetchDropdownsData() {
        // Singleton implementation
        if (this.dropdownsData != null) {
            return;
        }
        this.dropdownsData = {};

        if (this.dataset.searchWith == null) {
            return;
        }

        const params = this.dataset.searchWith.split(',');

        for (let param of params) {
            if (param.includes("[]")) {
                const segments = param.split("[]");
                param = segments[0];
                const sortOrder = segments[1];

                let url = this.trackerBaseURL;
                if (ALTERNATIVE_DROPDOWN_PATHNAMES[param]) {
                    url += ALTERNATIVE_DROPDOWN_PATHNAMES[param];
                } else {
                    url += `/rest/data/${param}`;
                }
                url += "?@verbose=2";

                if (sortOrder) {
                    url += `&@sort=${sortOrder}`;
                }

                let resp, json;
                try {
                    resp = await fetch(url);
                } catch (error) {
                    let message = `Error fetching translations from roundup rest api\n`;
                    message += `url: ${url.toString()}\n`;
                    throw new Error(message, { cause: error });
                }

                try {
                    json = await resp.json();
                } catch (error) {
                    let message = `Error parsing json from roundup rest api\n`;
                    message += `url: ${url.toString()}\n`;
                    throw new Error(message, { cause: error });
                }

                if (!resp.ok) {
                    let message = `Unexpected response\n`;
                    message += `url: ${url.toString()}\n`;
                    message += `response status: ${resp.status}\n`;
                    message += `response body: ${JSON.stringify(json)}\n`;
                    throw new Error(message);
                }

                let list = new Map();

                if (json.data.collection.length > 0) {
                    let idKey = "id";
                    let valueKey = Object.keys(json.data.collection[0]).find(key => key !== "id" && key !== "link");

                    if (!valueKey) {
                        let message = `No suitable key found for value in dropdown data\n`;
                        message += `url: ${url.toString()}\n`;
                        throw new Error("No value key found in dropdown data for: " + url);
                    }

                    for (let entry of json.data.collection) {
                        list.set(entry[idKey], entry[valueKey]);
                    }

                }
                this.dropdownsData[param] = list;
            }
        }
    }

    /**
     * Find the anchor tag that provides the classhelp link.
     * @returns {HTMLAnchorElement}
     * @throws {Error} when the anchor tag is not classhelp link
     */
    findClassHelpLink() {
        const links = this.querySelectorAll("a");
        if (links.length != 1) {
            throw new Error("roundup-classhelper must wrap a single classhelp link");
        }
        const link = links.item(0);

        if (!link.dataset.helpurl) {
            throw new Error("roundup-classhelper link must have a data-helpurl attribute");
        }

        if (!link.dataset.width) {
            throw new Error("roundup-classhelper link must have a data-width attribute");
        }

        if (!link.dataset.height) {
            throw new Error("roundup-classhelper link must have a data-height attribute");
        }

        if (!link.getAttribute("onclick")) {
            throw new Error("roundup-classhelper link should have an onclick attribute set");
        }

        return link;
    }

    /**
     * This method parses the helpurl link to get the necessary data for the classhelper.
     * @param {HTMLAnchorElement} link
     * @returns {HelpUrlProps}
     * @throws {Error} when the helpurl link is not proper
     */
    static parseHelpUrlProps(link) {
        const width = parseInt(link.dataset.width);
        if (isNaN(width)) {
            throw new Error("width in helpurl must be a number");
        }

        const height = parseInt(link.dataset.height);
        if (isNaN(height)) {
            throw new Error("height in helpurl must be a number");
        }

        const urlParts = link.dataset.helpurl.split("?");

        if (urlParts.length != 2) {
            throw new Error("invalid helpurl from link, missing query params");
        }

        const apiClassName = urlParts[0];
        const searchParams = new URLSearchParams(urlParts[1]);

        const tableSelectionType = searchParams.get("type");
        const formName = searchParams.get("form");
        const formProperty = searchParams.get("property");

        const startWith = parseInt(searchParams.get("@startwith"));
        if (isNaN(startWith)) {
            throw new Error("startwith in helpurl must be a number");
        }

        const pageIndex = startWith + 1;
        const pageSize = parseInt(searchParams.get("@pagesize"));

        if (isNaN(pageSize)) {
            throw new Error("pagesize in helpurl must be a number");
        }

        const sort = searchParams.get("@sort")?.split(",");
        const fields = searchParams.get("properties")?.split(",");

        return {
            width,
            height,
            apiClassName,
            tableSelectionType,
            formName,
            formProperty,
            pageIndex,
            pageSize,
            sort,
            fields
        }
    }

    /** 
     * from roundup docs rest api url - "{host}/{tracker}
     * we pass helpurl which is parsed from anchor tag and return a URL.
     * @param {HelpUrlProps} props
     * @returns {URL}
     */
    static getRestURL(trackerBaseURL, props) {
        const restDataPath = "rest/data";
        const base = trackerBaseURL + "/" + restDataPath + "/" + props.apiClassName;
        let url = new URL(base);

        url.searchParams.append("@page_index", props.pageIndex);
        url.searchParams.append("@page_size", props.pageSize);
        let fields = props.fields.join(',');
        url.searchParams.append("@fields", fields);

        if (props.sort) {
            let sort = props.sort.join(',');
            url.searchParams.append("@sort", sort);
        }

        return url;
    }

    static getSearchURL(trackerBaseURL, props, formData) {
        const url = new URL(ClassHelper.getRestURL(trackerBaseURL, props).toString());
        for (let entry of formData.entries()) {
            if (entry[1] != null && entry[1] != "") {
                url.searchParams.append(entry[0], entry[1]);
            }
        }
        return url;
    }

    getSearchFragment(formData) {
        const fragment = document.createDocumentFragment();
        const form = document.createElement("form");
        form.setAttribute("id", "popup-search");
        form.classList.add("popup-search"); // Add class for styling

        const params = this.dataset.searchWith.split(',');

        const table = document.createElement("table");
        table.classList.add("search-table"); // Add class for styling
        table.setAttribute("role", "presentation");

        for (var param of params) {
            param = param.split("[]")[0];

            const row = document.createElement("tr");
            const labelCell = document.createElement("td");
            const inputCell = document.createElement("td");

            const label = document.createElement("label");
            label.classList.add("search-label"); // Add class for styling
            label.setAttribute("for", param);
            label.textContent = ClassHelper.translations[param] + ":";

            let focusSet = false
            let input;
            if (this.dropdownsData[param]) {
                input = document.createElement("select");

                let nullOption = document.createElement("option");
                nullOption.value = "";
                nullOption.textContent = "---";
                input.appendChild(nullOption);

                for (let key of this.dropdownsData[param].keys()) {
                    let option = document.createElement("option");
                    option.value = key;
                    option.textContent = this.dropdownsData[param].get(key);
                    if (formData) {
                        let value = formData.get(param);
                        if (value && value == key) {
                            option.selected = "selected";
                        }
                    }
                    input.appendChild(option);
                }
            } else {
                input = document.createElement("input");
                input.setAttribute("type", "text");
                input.setAttribute("autocapitalize", "off")

                if (formData) {
                    let value = formData.get(param);
                    if (value) {
                        input.value = value;
                    }
                }
            }

            input.setAttribute("name", param);
            input.setAttribute("id", param);
            input.classList.add("search-input"); // Add class for styling   
	    if (!focusSet) {
	      input.setAttribute("autofocus", "");
	      focusSet = true;
	    }

            labelCell.appendChild(label);
            inputCell.appendChild(input);

            row.appendChild(labelCell);
            row.appendChild(inputCell);

            table.appendChild(row);
        }

        // Add search and reset buttons
        const buttonRow = document.createElement("tr");
        const emptyButtonCell = document.createElement("td");
        const buttonCell = document.createElement("td");
        buttonCell.colSpan = 1;

        const search = document.createElement("button");
        search.textContent = ClassHelper.translations["search"];
        search.classList.add("search-button"); // Add class for styling
        search.addEventListener("click", (e) => {
            e.preventDefault();
            let fd = new FormData(form);

            let hasError = this.popupRef.document.getElementsByClassName("search-error").item(0);
            if (hasError != null) {
                let current = fd.get(hasError.dataset.errorField)
                let prev = hasError.dataset.errorValue;
                if (current === prev) {
                    return;
                }
            }

            this.dispatchEvent(new CustomEvent("search", {
                detail: {
                    value: fd
                }
            }));
        });

        const reset = document.createElement("button");
        reset.textContent = ClassHelper.translations["reset"];
        reset.classList.add("reset-button"); // Add class for styling
        reset.addEventListener("click", (e) => {
            e.preventDefault();
            form.reset();
            let fd = new FormData(form);
            this.dispatchEvent(new CustomEvent("search", {
                detail: {
                    value: fd
                }
            }));
        });

        buttonCell.appendChild(search);
        buttonCell.appendChild(reset);
        buttonRow.appendChild(emptyButtonCell);
        buttonRow.appendChild(buttonCell);

        table.appendChild(buttonRow);

        form.appendChild(table);
        fragment.appendChild(form);

        return fragment;
    }

    getPaginationFragment(prevUrl, nextUrl, index, size, total) {
        const fragment = document.createDocumentFragment();

        const container = document.createElement("div");
        container.id = "popup-pagination";
        container.classList.add("popup-pagination");

        const info = document.createElement('span');

        let startNumber = 0, endNumber = 0;

        if (total > 0) {
            startNumber = (parseInt(index) - 1) * parseInt(size) + 1;
            if (total < size) {
                endNumber = startNumber + total - 1;
            } else {
                endNumber = parseInt(index) * parseInt(size);
            }
        }

        info.textContent = `${startNumber} - ${endNumber}`;

        const prev = document.createElement("button");
        prev.innerHTML = "<";
        prev.setAttribute("aria-label", ClassHelper.translations["prev"]);
        prev.setAttribute("disabled", "disabled");
        if (prevUrl) {
            prev.removeAttribute("disabled");
            prev.addEventListener("click", () => {
                this.dispatchEvent(new CustomEvent("prevPage", {
                    detail: {
                        value: prevUrl
                    }
                }));
            });
        }

        const next = document.createElement("button");
        next.innerHTML = ">";
        next.setAttribute("aria-label", ClassHelper.translations["next"]);
        next.setAttribute("disabled", "disabled");
        if (nextUrl) {
            next.removeAttribute("disabled");
            next.addEventListener("click", () => {
                this.dispatchEvent(new CustomEvent("nextPage", {
                    detail: {
                        value: nextUrl
                    }
                }));
            });
        }

        container.append(prev, info, next);
        fragment.appendChild(container);
        return fragment;
    }

    getAccumulatorFragment(preSelectedValues) {
        const fragment = document.createDocumentFragment();
        const container = document.createElement("div");
        container.id = "popup-control";

        const form = document.createElement("form")
        form.id = "accumulator-form"
        form.classList.add("popup-control");

        const preview = document.createElement("input");
        preview.id = "popup-preview";
        preview.classList.add("popup-preview");
        preview.type = "text";
        preview.name = "preview";
        if (preSelectedValues.length > 0) {
            preview.value = preSelectedValues.join(',');
        }

        const cancel = document.createElement("button");
        cancel.textContent = ClassHelper.translations["cancel"];
        cancel.setAttribute("type", "button");
        cancel.addEventListener("click", () => {
            this.popupRef.close();
        });

        const apply = document.createElement("button");
        apply.id = "popup-apply";
        apply.classList.add("popup-apply");
        apply.textContent = ClassHelper.translations["apply"];
        apply.addEventListener("click", () => {
            this.dispatchEvent(new CustomEvent("valueSelected", {
                detail: {
                    value: preview.value
                }
            }))
        })

        form.append(preview, apply, cancel);
        container.append(form)
        fragment.appendChild(container);

        return fragment;
    }

    /**
     * 
     * @param {string[]} headers 
     * @param {Object.<string, any>[]} data 
     * @returns 
     */
    getTableFragment(headers, data, preSelectedValues) {
        let includeCheckbox = !this.popupRef.document.body.classList.contains(CLASSHELPER_TABLE_SELECTION_NONE);

        const fragment = document.createDocumentFragment();

        const container = document.createElement('div');
        container.id = "popup-tablediv";
        container.classList.add("popup-tablediv");

        const table = document.createElement('table');
        table.classList.add("popup-table");
        const thead = document.createElement('thead');
        const tbody = document.createElement('tbody');
        const tfoot = document.createElement('tfoot');

        // Create table headers
        const headerRow = document.createElement('tr');

        if (includeCheckbox) {
            let thx = document.createElement("th");
            thx.textContent = "X";
            thx.classList.add("table-header");
            headerRow.appendChild(thx);
        }

        headers.forEach(header => {
            const th = document.createElement('th');
            th.textContent = ClassHelper.translations[header];
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);

        // Create table body with data
        data.forEach((entry) => {
            const row = document.createElement('tr');
            row.dataset.id = entry[headers[0]];
            row.setAttribute("tabindex", 0);
            row.classList.add("row-style");

            if (includeCheckbox) {
                const td = document.createElement('td');
                const checkbox = document.createElement("input");
                checkbox.setAttribute("type", "checkbox");
                checkbox.checked = false;
                checkbox.setAttribute("tabindex", -1);
                td.appendChild(checkbox)
                row.appendChild(td);
                if (preSelectedValues.includes(entry[headers[0]])) {
                    checkbox.checked = true;
                }
            }

            headers.forEach(header => {
                const td = document.createElement('td');
                td.textContent = entry[header];
                row.appendChild(td);
            });
            tbody.appendChild(row);
        });

        if (includeCheckbox) {
            tbody.addEventListener("click", (e) => {
                let id, tr;
                if (e.target.tagName === "INPUT" ) {
                    tr = e.target.parentElement.parentElement;
                    id = tr.dataset.id;
	        } else if (e.target.tagName === "TD") {
                    tr = e.target.parentElement;
                    id = tr.dataset.id;
                } else if (e.target.tagName === "TR") {
                    tr = e.target;
                    id = tr.dataset.id;
                }

              if (e.target.tagName !== "INPUT") {
		/* checkbox is only child of the first td of the table row */
		let checkbox = tr.children.item(0).children.item(0);
		checkbox.checked = !checkbox.checked;
                }

                this.dispatchEvent(new CustomEvent("selection", {
                    detail: {
                        value: id
                    }
                }));
            });

        }

        // Create table footer with the same column values as headers
        const footerRow = headerRow.cloneNode(true);
        tfoot.appendChild(footerRow);

        // Assemble the table
        table.appendChild(thead);
        table.appendChild(tbody);
        table.appendChild(tfoot); // Append the footer

        container.appendChild(table);

        fragment.appendChild(container);

        return fragment;
    }

    /**
     * main method called when classhelper is clicked
     * @param {URL | string} apiURL
     * @param {HelpUrlProps} props 
     * @param {string[]} preSelectedValues
     * @param {FormData} formData
     * @throws {Error} when fetching or parsing data from roundup rest api fails
     */
    async openPopUp(apiURL, props) {

        /** @type {Response} */
        let resp, json;
        /** @type {any} */
        let collection;
        /** @type {string} */
        let prevPageURL;
        /** @type {string} */
        let nextPageURL;
        /** @type {string[]} */
        let preSelectedValues = [];

        if (document.URL.endsWith("#classhelper-abort")) {
          throw new Error("Aborting due to #classhelper-abort fragment",
			  { cause: "Abort requested." });
        }

        try {
            resp = await fetch(apiURL);
        } catch (error) {
            let message = `Error fetching data from roundup rest api`;
            message += `url: ${apiURL.toString()}\n`;
            throw new Error(message, { cause: error });
        }

        try {
            json = await resp.json();
        } catch (error) {
            let message = "Error parsing json from roundup rest api\n";
            message += `url: ${apiURL.toString()}\n`;
            throw new Error(message, { cause: error });
        }

        if (!resp.ok) {
            let message = `Unexpected response\n`;
            message += `url: ${apiURL.toString()}\n`;
            message += `response status: ${resp.status}\n`;
            message += `response body: ${JSON.stringify(json)}\n`;
            throw new Error(message);
        }

        collection = json.data.collection;

        const links = json.data["@links"];
        if (links?.prev?.length > 0) {
            prevPageURL = links.prev[0].uri;
        }
        if (links?.next?.length > 0) {
            nextPageURL = links.next[0].uri;
        }

        if (props.formProperty) {
            // Find preselected values
            const input = document.getElementsByName(props.formProperty).item(0);
            if (input?.value) {
                preSelectedValues = input.value.split(',');
            }
        }

        const popupFeatures = CLASSHELPER_POPUP_FEATURES(props.width, props.height);
        this.popupRef = window.open(CLASSHELPER_POPUP_URL, CLASSHELPER_POPUP_TARGET, popupFeatures);

        if (this.popupRef == null) {
            throw new Error("Browser Failed to open Popup Window");
        }

        // Create the popup root level page
        const page = document.createDocumentFragment();
        const html = document.createElement("html");
        const head = document.createElement("head");
        const body = document.createElement("body");

        body.classList.add("flex-container");
        if (!props.formProperty) {
            this.popupRef.document.body.classList.add(CLASSHELPER_TABLE_SELECTION_NONE);
            body.classList.add(CLASSHELPER_TABLE_SELECTION_NONE);
        }

        const itemDesignator = window.location.pathname.split("/").at(-1);
        let titleText;

        if (this.dataset.popupTitle) {
            titleText = ClassHelper.translations[this.dataset.popupTitle];
            titleText = titleText.replace(
		CLASSHELPER_ATTRIBUTE_POPUP_TITLE_ITEM_DESIGNATOR_LOOKUP,
		itemDesignator);
        } else {
            titleText = `${itemDesignator} - Classhelper`;
            if (props.formProperty) {
                // use the formProperty as the label for the window
                titleText = props.formProperty + " - " + titleText;
            } else if (props.apiClassName) {
                titleText = ClassHelper.translations[
                    CLASSHELPER_READONLY_POPUP_TITLE
		].replace(
		    CLASSHELPER_ATTRIBUTE_POPUP_TITLE_ITEM_DESIGNATOR_LOOKUP,
		    itemDesignator);
                titleText = titleText.replace(
		    CLASSHELPER_ATTRIBUTE_POPUP_TITLE_ITEM_CLASS_LOOKUP,
		    props.apiClassName);
            }
        }

        const titleTag = document.createElement("title");
        titleTag.textContent = titleText;
        head.appendChild(titleTag);

        const styleSheet = document.createElement("link");
        styleSheet.rel = "stylesheet";
        styleSheet.type = "text/css";
        styleSheet.href = this.trackerBaseURL + '/' + CSS_STYLESHEET_FILE_NAME;
        head.appendChild(styleSheet);

        if (this.dataset.searchWith) {
            const searchFrag = this.getSearchFragment(null);
            body.appendChild(searchFrag);
        }

        const paginationFrag = this.getPaginationFragment(prevPageURL, nextPageURL, props.pageIndex, props.pageSize, collection.length);
        body.appendChild(paginationFrag);

        const tableFrag = this.getTableFragment(props.fields, collection, preSelectedValues);
        body.appendChild(tableFrag);

        const separator = document.createElement("div");
        separator.classList.add("separator");
        body.appendChild(separator);

        if (props.formProperty) {
            const accumulatorFrag = this.getAccumulatorFragment(preSelectedValues);
            body.appendChild(accumulatorFrag);
        }

        html.appendChild(head);
        html.appendChild(body);
        page.appendChild(html);

        const dispatchPopupReady = () => this.dispatchEvent(new CustomEvent("popupReady", { detail: page }));

        // Wait for the popup window to load, onload fire popupReady event on the classhelper
        this.popupRef.addEventListener("load", dispatchPopupReady);

        // If load event was already fired way before the event listener was attached
        // we need to trigger it manually if popupRef is readyState complete
        if (this.popupRef.document.readyState === "complete") {
            dispatchPopupReady();
            // if we did successfully trigger the event, we can remove the event listener
            // else wait for it to be removed with closing of popup window, this cleaning up closure
            this.popupRef.removeEventListener("load", dispatchPopupReady);
        }

        this.popupRef.addEventListener("keydown", (e) => {
            if (e.key === "ArrowDown") {
                if (e.target.tagName === "TR") {
                    e.preventDefault();
                    if (e.target.nextElementSibling != null) {
                        e.target.nextElementSibling.focus();
                    } else {
                        e.target.parentElement.firstChild.focus();
                    }
                } else if (e.target.tagName != "INPUT" && e.target.tagName != "SELECT") {
                    e.preventDefault();
                    this.popupRef.document.querySelector("tr.row-style").parentElement.firstChild.focus();
                }
            } else if (e.key === "ArrowUp") {
                if (e.target.tagName === "TR") {
                    e.preventDefault();
                    if (e.target.previousElementSibling != null) {
                        e.target.previousElementSibling.focus();
                    } else {
                        e.target.parentElement.lastChild.focus();
                    }
                } else if (e.target.tagName != "INPUT" && e.target.tagName != "SELECT") {
                    e.preventDefault();
                    this.popupRef.document.querySelector("tr.row-style").parentElement.lastChild.focus();
                }
            } else if (e.key === ">") {
                if (e.target.tagName === "TR" || e.target.tagName != "INPUT" && e.target.tagName != "SELECT") {
                    this.popupRef.document.getElementById("popup-pagination").lastChild.focus();
                }
            } else if (e.key === "<") {
                if (e.target.tagName === "TR" || e.target.tagName != "INPUT" && e.target.tagName != "SELECT") {
                    this.popupRef.document.getElementById("popup-pagination").firstChild.focus();
                }
            } else if (e.key === "Enter") {
                if (e.target.tagName == "TR" && e.shiftKey == false) {
                    e.preventDefault();
                    let tr = e.target;
                    let checkbox = tr.children.item(0).children.item(0)
                    checkbox.checked = !checkbox.checked;
                    this.dispatchEvent(new CustomEvent("selection", {
                        detail: {
                            value: tr.dataset.id
                        }
                    }));
                } else if (e.shiftKey) {
                    e.preventDefault();
                    const applyBtn = this.popupRef.document.getElementById("popup-apply");
                    if (applyBtn) {
                        applyBtn.focus();
                    }
                }
            } else if (e.key === " ") {
                if (e.target.tagName == "TR" && e.shiftKey == false) {
                    e.preventDefault();
                    let tr = e.target;
                    let checkbox = tr.children.item(0).children.item(0)
                    checkbox.checked = !checkbox.checked;
                    this.dispatchEvent(new CustomEvent("selection", {
                        detail: {
                            value: tr.dataset.id
                        }
                    }));
                }
            }
        });
    }

    /** method when next or previous button is clicked
     * @param {URL | string} apiURL
     * @param {HelpUrlProps} props
     * @throws {Error} when fetching or parsing data from roundup rest api fails
     */
    async pageChange(apiURL, props) {

        /** @type {Response} */
        let resp, json;
        /** @type {any} */
        let collection;
        /** @type {string} */
        let prevPageURL;
        /** @type {string} */
        let nextPageURL;
        /** @type {URL} */
        let selfPageURL;
        /** @type {string[]} */
        let accumulatorValues = [];

        try {
            resp = await fetch(apiURL);
        } catch (error) {
            let message = `Error fetching data from roundup rest api`;
            message += `url: ${apiURL.toString()}\n`;
            throw new Error(message, { cause: error });
        }

        try {
            json = await resp.json();
        } catch (error) {
            let message = "Error parsing json from roundup rest api\n";
            message += `url: ${apiURL.toString()}\n`;
            throw new Error(message, { cause: error });
        }

        if (!resp.ok) {
            let message = `Unexpected response\n`;
            message += `url: ${apiURL.toString()}\n`;
            message += `response status: ${resp.status}\n`;
            message += `response body: ${JSON.stringify(json)}\n`;
            throw new Error(message);
        }

        collection = json.data.collection;

        const links = json.data["@links"];
        if (links?.prev?.length > 0) {
            prevPageURL = links.prev[0].uri;
        }
        if (links?.next?.length > 0) {
            nextPageURL = links.next[0].uri;
        }
        if (links?.self?.length > 0) {
            selfPageURL = new URL(links.self[0].uri);
        }

        const preview = this.popupRef.document.getElementById("popup-preview");
        if (preview) {
            accumulatorValues = preview.value.split(",");
        }

        const popupDocument = this.popupRef.document;
        const popupBody = this.popupRef.document.body;
        const pageIndex = selfPageURL.searchParams.get("@page_index");

        const oldPaginationFrag = popupDocument.getElementById("popup-pagination");
        const newPaginationFrag = this.getPaginationFragment(prevPageURL, nextPageURL, pageIndex, props.pageSize, collection.length);
        popupBody.replaceChild(newPaginationFrag, oldPaginationFrag);

        let oldTableFrag = popupDocument.getElementById("popup-tablediv");
        let newTableFrag = this.getTableFragment(props.fields, collection, accumulatorValues);
        popupBody.replaceChild(newTableFrag, oldTableFrag);
    }

    /** method when a value is selected in 
     * @param {HelpUrlProps} props
     * @param {string} value
     */
    valueSelected(props, value) {
        if (!props.formProperty) {
            return;
        }

        const input = document.getElementsByName(props.formProperty).item(0);
        input.value = value;
        this.popupRef.close();
    }

    /** method when search is performed within classhelper, here we need to update the classhelper table with search results
     * @param {URL} apiURL
     * @param {HelpUrlProps} props
     * @throws {Error} when fetching or parsing data from roundup rest api fails
     */
    async searchEvent(apiURL, props) {

        /** @type {Response} */
        let resp, json;
        /** @type {any} */
        let collection;
        /** @type {string} */
        let prevPageURL;
        /** @type {string} */
        let nextPageURL;
        /** @type {URL} */
        let selfPageURL;
        /** @type {string[]} */
        let accumulatorValues = [];

        try {
            resp = await fetch(apiURL);
        } catch (error) {
            let message = `Error fetching data from roundup rest api`;
            message += `url: ${apiURL.toString()}\n`;
            throw new Error(message, { cause: error });
        }

        try {
            json = await resp.json();
        } catch (error) {
            let message = "Error parsing json from roundup rest api\n";
            message += `url: ${apiURL.toString()}\n`;
            throw new Error(message, { cause: error });
        }

        if (!resp.ok && resp.status === 400) {
            // In the error message we will have the field name that caused the error.
            // and the value that caused the error, in a double quoted string
            // <some text> "(value)" <some text> "(key)", this regex is a capture group
            // that captures the value and key in the error message.
            let regexCaptureDoubleQuotedString = /"(.*?)"/g;
            let iterator = json.error.msg.matchAll(regexCaptureDoubleQuotedString);
            let results = Array.from(iterator);

            if (results.length == 2) {
                let value = results[0][1];
                let field = results[1][1];

                // Find the input element with the name of the key
                let input = this.popupRef.document.getElementsByName(field).item(0);
                if (input) {
                    let parent = input.parentElement;
                    parent.classList.add("search-error");
                    parent.dataset.errorValue = value;
                    parent.dataset.errorField = field;
                    // remove if there was already an error message
                    parent.getElementsByClassName("error-message").item(0)?.remove();
                    let span = document.createElement("div");
                    span.classList.add("error-message");
                    span.textContent = `Invalid value: ${value}`;
                    parent.appendChild(span);
                    return;
                }
            }
        }

        if (!resp.ok && resp.status === 403) {
            this.popupRef.alert(json.error.msg);
            return;
        }

        if (!resp.ok) {
            let message = `Unexpected response\n`;
            message += `url: ${apiURL.toString()}\n`;
            message += `response status: ${resp.status}\n`;
            message += `response body: ${JSON.stringify(json)}\n`;
            throw new Error(message);
        }

        collection = json.data.collection;

        const links = json.data["@links"];
        if (links?.prev?.length > 0) {
            prevPageURL = links.prev[0].uri;
        }
        if (links?.next?.length > 0) {
            nextPageURL = links.next[0].uri;
        }
        if (links?.self?.length > 0) {
            selfPageURL = new URL(links.self[0].uri);
        }

        const preview = this.popupRef.document.getElementById("popup-preview");
        if (preview) {
            accumulatorValues = preview.value.split(",");
        }

        const popupDocument = this.popupRef.document;
        const popupBody = this.popupRef.document.body;
        const pageIndex = selfPageURL.searchParams.get("@page_index");

        // remove any previous error messages
        let errors = Array.from(popupDocument.getElementsByClassName("search-error"));
        errors.forEach(element => {
            element.classList.remove("search-error");
            element.getElementsByClassName("error-message").item(0)?.remove();
        });

        const oldPaginationFrag = popupDocument.getElementById("popup-pagination");
        let newPaginationFrag = this.getPaginationFragment(prevPageURL, nextPageURL, pageIndex, props.pageSize, collection.length);
        popupBody.replaceChild(newPaginationFrag, oldPaginationFrag);


        let oldTableFrag = popupDocument.getElementById("popup-tablediv");
        let newTableFrag = this.getTableFragment(props.fields, collection, accumulatorValues);
        popupBody.replaceChild(newTableFrag, oldTableFrag);
    }

    /** method when an entry in classhelper table is selected
     * @param {string} value
     */
    selectionEvent(value) {
        const preview = this.popupRef.document.getElementById("popup-preview");
        if (!preview) {
            return;
        }

        if (preview.value == "" || preview.value == null) {
            preview.value = value
        } else {
            const values = preview.value.split(',');
            const exists = values.findIndex(v => v == value.toString());

            if (exists > -1) {
                values.splice(exists, 1);
                preview.value = values.join(',');
            } else {
                preview.value += ',' + value;
            }
        }
    }
}

function enableClassHelper() {
    if (document.URL.endsWith("#classhelper-wc-toggle")) {
        return;
    }

    if (DISABLE_CLASSHELPER) {
      return;
    }

    /** make api call if error then do not register*/
    // http://localhost/demo/rest

    fetch("rest")
        .then(resp => resp.json())
        .then(json => {
            if (json.error) {
                console.log(json.error);
                return;
            }
            customElements.define(CLASSHELPER_TAG_NAME, ClassHelper);
            ClassHelper.fetchTranslations()
            .catch(error => {
                console.warn("Classhelper failed in translating.")
                console.error(error);
            });
        }).catch(err => {
            console.error(err);
        });
}

enableClassHelper();
