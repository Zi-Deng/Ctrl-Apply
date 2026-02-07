/**
 * DOM form field extraction (READ-ONLY).
 * Extracts all visible form fields, their labels, types, and options.
 * Sends the result to the service worker for backend analysis.
 *
 * This script never modifies the DOM — Playwright handles all filling via CDP.
 */

(function () {
  "use strict";

  /**
   * Find the label text for a form element.
   */
  function findLabel(el) {
    // 1. Explicit <label for="id">
    if (el.id) {
      const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (label) return label.textContent.trim();
    }

    // 2. Wrapping <label>
    const parent = el.closest("label");
    if (parent) {
      // Get text excluding the input itself
      const clone = parent.cloneNode(true);
      const inputs = clone.querySelectorAll("input, select, textarea");
      inputs.forEach((i) => i.remove());
      const text = clone.textContent.trim();
      if (text) return text;
    }

    // 3. aria-label or aria-labelledby
    if (el.getAttribute("aria-label")) {
      return el.getAttribute("aria-label").trim();
    }
    if (el.getAttribute("aria-labelledby")) {
      const labelEl = document.getElementById(el.getAttribute("aria-labelledby"));
      if (labelEl) return labelEl.textContent.trim();
    }

    // 4. Previous sibling text or nearby label-like element
    const prev = el.previousElementSibling;
    if (prev && (prev.tagName === "LABEL" || prev.tagName === "SPAN" || prev.tagName === "DIV")) {
      const text = prev.textContent.trim();
      if (text && text.length < 100) return text;
    }

    // 5. Placeholder
    if (el.placeholder) {
      return el.placeholder.trim();
    }

    // 6. Name attribute as fallback
    if (el.name) {
      return el.name.replace(/[_\-\[\]]/g, " ").trim();
    }

    return "";
  }

  /**
   * Build a robust CSS selector for an element.
   */
  function buildSelector(el) {
    // Prefer data-automation-id (Workday)
    if (el.getAttribute("data-automation-id")) {
      return `[data-automation-id="${el.getAttribute("data-automation-id")}"]`;
    }

    // Prefer id
    if (el.id) {
      return `#${CSS.escape(el.id)}`;
    }

    // Prefer name
    if (el.name) {
      const tag = el.tagName.toLowerCase();
      return `${tag}[name="${CSS.escape(el.name)}"]`;
    }

    // Build path-based selector
    const parts = [];
    let current = el;
    while (current && current !== document.body) {
      let selector = current.tagName.toLowerCase();
      if (current.id) {
        selector = `#${CSS.escape(current.id)}`;
        parts.unshift(selector);
        break;
      }
      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter(
          (c) => c.tagName === current.tagName
        );
        if (siblings.length > 1) {
          const index = siblings.indexOf(current) + 1;
          selector += `:nth-of-type(${index})`;
        }
      }
      parts.unshift(selector);
      current = current.parentElement;
    }
    return parts.join(" > ");
  }

  /**
   * Determine field type from element.
   */
  function getFieldType(el) {
    const tag = el.tagName.toLowerCase();
    if (tag === "select") return "select";
    if (tag === "textarea") return "textarea";
    if (tag === "input") {
      // Check if this input is actually an ARIA combobox (e.g. Workday)
      if (
        el.getAttribute("role") === "combobox" ||
        el.getAttribute("aria-haspopup") === "listbox"
      ) {
        return "combobox";
      }
      const type = (el.type || "text").toLowerCase();
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (type === "file") return "file";
      if (type === "email") return "email";
      if (type === "tel") return "tel";
      if (type === "hidden") return "hidden";
      return "text";
    }
    // Non-input elements with combobox role (div/button/span triggers)
    if (
      el.getAttribute("role") === "combobox" ||
      el.getAttribute("aria-haspopup") === "listbox"
    ) {
      return "combobox";
    }
    // contenteditable divs (sometimes used for textareas)
    if (el.getAttribute("contenteditable") === "true") return "textarea";
    return "text";
  }

  /**
   * Find the ARIA listbox associated with a combobox trigger element.
   */
  function findAssociatedListbox(triggerEl) {
    // 1. aria-owns or aria-controls pointing to a listbox by ID
    const ownedId =
      triggerEl.getAttribute("aria-owns") || triggerEl.getAttribute("aria-controls");
    if (ownedId) {
      // aria-owns can contain space-separated IDs
      for (const id of ownedId.split(/\s+/)) {
        const el = document.getElementById(id);
        if (el) return el;
      }
    }

    // 2. Sibling listbox within the same parent
    const parent = triggerEl.parentElement;
    if (parent) {
      const sibling = parent.querySelector('[role="listbox"]');
      if (sibling && sibling !== triggerEl) return sibling;
    }

    // 3. Walk up a few levels and look for a listbox descendant
    let container = triggerEl.parentElement;
    for (let i = 0; i < 3 && container; i++) {
      const lb = container.querySelector('[role="listbox"]');
      if (lb) return lb;
      container = container.parentElement;
    }

    // 4. Workday-specific: match data-automation-id variations
    const automationId = triggerEl.getAttribute("data-automation-id");
    if (automationId) {
      const variations = [
        `[data-automation-id="${automationId}-list"]`,
        `[data-automation-id="${automationId}List"]`,
        `[data-automation-id="${automationId}-options"]`,
      ];
      for (const sel of variations) {
        const lb = document.querySelector(sel);
        if (lb) return lb;
      }
    }

    return null;
  }

  /**
   * Extract options from a <select> element or ARIA listbox.
   */
  function extractOptions(el, listboxEl) {
    // Native <select>
    if (el.tagName.toLowerCase() === "select") {
      return Array.from(el.options)
        .filter((opt) => opt.value !== "") // skip placeholder options
        .map((opt) => ({
          value: opt.value,
          text: opt.textContent.trim(),
        }));
    }

    // ARIA listbox (for combobox fields)
    if (listboxEl) {
      const optionEls = listboxEl.querySelectorAll('[role="option"]');
      return Array.from(optionEls)
        .map((opt) => ({
          value:
            opt.getAttribute("data-value") ||
            opt.getAttribute("value") ||
            opt.id ||
            opt.textContent.trim(),
          text: opt.textContent.trim(),
        }))
        .filter((opt) => opt.text !== "");
    }

    return [];
  }

  /**
   * Check if an element is visible.
   */
  function isVisible(el) {
    if (el.offsetParent === null && getComputedStyle(el).position !== "fixed") return false;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    if (el.type === "hidden") return false;
    return true;
  }

  /**
   * Extract all form fields from the page.
   */
  function extractFormFields() {
    const fields = [];
    const seen = new Set();

    // Query all form-relevant elements (including ARIA combobox widgets)
    const elements = document.querySelectorAll(
      'input, select, textarea, [contenteditable="true"], ' +
        '[role="combobox"], [aria-haspopup="listbox"]'
    );

    for (const el of elements) {
      // Skip elements that are part of a listbox, not standalone fields
      const role = el.getAttribute("role");
      if (role === "option" || role === "listbox") continue;

      // Skip invisible, already-processed, or submit buttons
      if (!isVisible(el)) continue;
      if (
        (el.type === "submit" || el.type === "button" || el.type === "reset") &&
        el.getAttribute("aria-haspopup") !== "listbox" &&
        el.getAttribute("role") !== "combobox"
      ) continue;
      if (el.type === "hidden") continue;

      const selector = buildSelector(el);
      if (seen.has(selector)) continue;
      seen.add(selector);

      const fieldType = getFieldType(el);
      const label = findLabel(el);

      if (fieldType === "combobox") {
        const listboxEl = findAssociatedListbox(el);
        const listboxSelector = listboxEl ? buildSelector(listboxEl) : "";
        const opts = extractOptions(el, listboxEl);

        fields.push({
          selector: selector,
          field_type: fieldType,
          label: label,
          name: el.name || "",
          id: el.id || "",
          required: el.required || el.getAttribute("aria-required") === "true",
          placeholder: el.placeholder || el.getAttribute("aria-placeholder") || "",
          options: opts,
          current_value: el.value || el.textContent?.trim() || "",
          listbox_selector: listboxSelector,
          options_deferred: opts.length === 0,
        });
      } else {
        fields.push({
          selector: selector,
          field_type: fieldType,
          label: label,
          name: el.name || "",
          id: el.id || "",
          required: el.required || el.getAttribute("aria-required") === "true",
          placeholder: el.placeholder || "",
          options: extractOptions(el, null),
          current_value: el.value || "",
        });
      }
    }

    return fields;
  }

  /**
   * Detect repeatable sections with "Add" buttons (e.g. Work Experience, Education).
   * Returns an array of section descriptors.
   */
  function extractRepeatableSections() {
    const sections = [];

    // 1. Workday-specific: data-automation-id="add-button"
    let addButtons = Array.from(
      document.querySelectorAll('[data-automation-id="add-button"]')
    ).filter((btn) => isVisible(btn));

    // 2. Fallback for non-Workday: buttons with text starting with "Add"
    if (addButtons.length === 0) {
      addButtons = Array.from(
        document.querySelectorAll('button, [role="button"]')
      ).filter((btn) => {
        if (!isVisible(btn)) return false;
        const text = (btn.textContent || "").trim();
        return /^add\b/i.test(text) && text.length < 50;
      });
    }

    for (let i = 0; i < addButtons.length; i++) {
      const btn = addButtons[i];
      const btnText = (btn.textContent || "").trim();

      // Walk up to find the nearest heading (H2, H3, H4) for section name
      let sectionName = "";
      let container = btn.parentElement;
      for (let depth = 0; depth < 10 && container; depth++) {
        // Look for a heading inside or before this container
        const heading = container.querySelector("h2, h3, h4");
        if (heading) {
          sectionName = heading.textContent.trim();
          break;
        }
        // Also check previous siblings of the container
        let prev = container.previousElementSibling;
        while (prev) {
          if (/^H[2-4]$/.test(prev.tagName)) {
            sectionName = prev.textContent.trim();
            break;
          }
          prev = prev.previousElementSibling;
        }
        if (sectionName) break;
        container = container.parentElement;
      }

      // Count existing sub-entries (H4 within the section container)
      let existingEntries = 0;
      if (container) {
        const subHeadings = container.querySelectorAll("h4");
        existingEntries = subHeadings.length;
      }

      sections.push({
        section_name: sectionName || `Section ${i + 1}`,
        add_button_index: i,
        add_button_selector: buildSelector(btn),
        add_button_text: btnText,
        existing_entries: existingEntries,
      });
    }

    return sections;
  }

  /**
   * Build the full extraction payload and send to service worker.
   */
  function extractAndSend() {
    const fields = extractFormFields();
    const platform = typeof detectATS === "function" ? detectATS() : "generic";
    const repeatableSections = extractRepeatableSections();

    const payload = {
      type: "form_extracted",
      data: {
        url: window.location.href,
        ats_platform: platform,
        fields: fields,
        page_title: document.title,
        repeatable_sections: repeatableSections,
      },
    };

    console.log(
      `[Ctrl+Apply] Extracted ${fields.length} fields, ${repeatableSections.length} repeatable sections (${platform})`
    );
    chrome.runtime.sendMessage(payload);
  }

  // Listen for extraction requests from the side panel or backend
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === "extract_form" || message.type === "extract_section") {
      const fields = extractFormFields();
      const platform = typeof detectATS === "function" ? detectATS() : "generic";
      const repeatableSections = extractRepeatableSections();
      sendResponse({
        url: window.location.href,
        ats_platform: platform,
        fields: fields,
        page_title: document.title,
        repeatable_sections: repeatableSections,
      });
    }
  });

  // Auto-extract on page load for known ATS platforms
  const platform = typeof detectATS === "function" ? detectATS() : "generic";
  if (platform !== "generic") {
    // Wait a bit for dynamic content to render
    setTimeout(extractAndSend, 1500);
  }
})();
