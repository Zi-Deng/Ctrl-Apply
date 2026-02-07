/**
 * Ctrl+Apply side panel logic.
 * Communicates with the service worker (which relays to the backend).
 */

(function () {
  "use strict";

  // --- DOM references ---
  const btnExtract = document.getElementById("btn-extract");
  const btnFill = document.getElementById("btn-fill");
  const btnReconnect = document.getElementById("btn-reconnect");
  const backendDot = document.getElementById("backend-status");
  const cdpDot = document.getElementById("cdp-status");
  const statusText = document.getElementById("status-text");
  const messageArea = document.getElementById("message-area");
  const platformInfo = document.getElementById("platform-info");
  const platformName = document.getElementById("platform-name");
  const fieldMappings = document.getElementById("field-mappings");
  const fieldsList = document.getElementById("fields-list");
  const unmappedSection = document.getElementById("unmapped-section");
  const unmappedList = document.getElementById("unmapped-list");
  const repeatableSections = document.getElementById("repeatable-sections");
  const sectionsList = document.getElementById("sections-list");
  const fillResults = document.getElementById("fill-results");
  const resultsSummary = document.getElementById("results-summary");
  const resultsErrors = document.getElementById("results-errors");

  // --- State ---
  let currentAnalysis = null; // FormAnalysis from backend
  let backendConnected = false;

  // --- Messages ---

  function showMessage(text, level = "info") {
    const div = document.createElement("div");
    div.className = `message ${level}`;
    div.textContent = text;
    messageArea.innerHTML = "";
    messageArea.appendChild(div);
  }

  function clearMessages() {
    messageArea.innerHTML = "";
  }

  // --- Status ---

  function updateStatus(backend, cdp) {
    if (backend !== undefined) {
      backendConnected = backend;
      backendDot.className = `status-dot ${backend ? "connected" : "disconnected"}`;
    }
    if (cdp !== undefined) {
      cdpDot.className = `status-dot ${cdp ? "connected" : "disconnected"}`;
    }
    btnExtract.disabled = !backendConnected;
    statusText.textContent = backendConnected ? "Connected" : "Disconnected";
  }

  // Check initial status
  chrome.runtime.sendMessage({ type: "get_status" }, (response) => {
    if (response) {
      updateStatus(response.wsReady, false);
    }
  });

  // --- Listen for messages from service worker ---

  chrome.runtime.onMessage.addListener((message) => {
    switch (message.type) {
      case "backend_connected":
        updateStatus(true, undefined);
        showMessage("Backend connected", "success");
        break;

      case "backend_disconnected":
        updateStatus(false, undefined);
        showMessage("Backend disconnected — is the server running?", "error");
        break;

      case "analyzing":
        showMessage(message.message, "info");
        btnExtract.disabled = true;
        break;

      case "form_analysis":
        handleFormAnalysis(message.data);
        break;

      case "filling":
        showMessage(message.message, "info");
        btnFill.disabled = true;
        break;

      case "fill_progress":
        showMessage(message.message, "info");
        break;

      case "fill_result":
        handleFillResult(message.data);
        break;

      case "cdp_connected":
        updateStatus(undefined, true);
        showMessage("Chrome CDP connected", "success");
        break;

      case "status":
        updateStatus(undefined, message.playwright_connected);
        break;

      case "error":
        showMessage(message.message, "error");
        btnExtract.disabled = !backendConnected;
        btnFill.disabled = !currentAnalysis;
        break;

      case "form_extracted":
        // Auto-extracted by content script on ATS page
        showMessage(
          `Auto-detected form with ${message.data?.fields?.length || 0} fields`,
          "info"
        );
        break;
    }
  });

  // --- Actions ---

  btnExtract.addEventListener("click", () => {
    clearMessages();
    showMessage("Extracting form fields...", "info");
    fieldMappings.classList.add("hidden");
    repeatableSections.classList.add("hidden");
    fillResults.classList.add("hidden");
    currentAnalysis = null;
    btnFill.disabled = true;

    // Ask content script to extract, then forward to backend
    chrome.runtime.sendMessage({ type: "extract_form" }, (response) => {
      if (response && response.fields) {
        // Show platform
        if (response.ats_platform && response.ats_platform !== "generic") {
          platformName.textContent = response.ats_platform;
          platformInfo.classList.remove("hidden");
        } else {
          platformInfo.classList.add("hidden");
        }

        showMessage(`Extracted ${response.fields.length} fields. Analyzing...`, "info");

        // Send to backend for LLM analysis
        chrome.runtime.sendMessage({
          type: "form_extracted",
          data: response,
        });
      } else {
        showMessage(
          response?.error || "Could not extract form. Make sure you're on a job application page.",
          "error"
        );
        btnExtract.disabled = false;
      }
    });
  });

  btnFill.addEventListener("click", () => {
    if (!currentAnalysis) return;

    // Update analysis with any user edits
    updateAnalysisFromUI();

    clearMessages();
    showMessage("Filling form...", "info");
    fillResults.classList.add("hidden");
    btnFill.disabled = true;

    chrome.runtime.sendMessage({
      type: "fill_form",
      data: currentAnalysis,
    });
  });

  btnReconnect.addEventListener("click", () => {
    showMessage("Reconnecting...", "info");
    chrome.runtime.sendMessage({ type: "connect_cdp" });
  });

  // --- Render field mappings ---

  function handleFormAnalysis(analysis) {
    currentAnalysis = analysis;
    clearMessages();

    if (analysis.ats_platform && analysis.ats_platform !== "generic") {
      platformName.textContent = analysis.ats_platform;
      platformInfo.classList.remove("hidden");
    }

    renderFields(analysis.fields);

    // Unmapped fields
    if (analysis.unmapped_fields && analysis.unmapped_fields.length > 0) {
      unmappedList.innerHTML = "";
      for (const label of analysis.unmapped_fields) {
        const li = document.createElement("li");
        li.textContent = label;
        unmappedList.appendChild(li);
      }
      unmappedSection.classList.remove("hidden");
    } else {
      unmappedSection.classList.add("hidden");
    }

    fieldMappings.classList.remove("hidden");

    // Repeatable sections
    if (analysis.repeatable_sections && analysis.repeatable_sections.length > 0) {
      sectionsList.innerHTML = "";
      for (const sec of analysis.repeatable_sections) {
        const div = document.createElement("div");
        div.className = "section-card";
        const name = document.createElement("strong");
        name.textContent = sec.section_name;
        div.appendChild(name);
        const info = document.createElement("span");
        const profileKey = sec.profile_section || "unmapped";
        info.textContent = ` — ${sec.existing_entries} existing (profile: ${profileKey})`;
        info.style.fontSize = "12px";
        info.style.color = "#6b7280";
        div.appendChild(info);
        sectionsList.appendChild(div);
      }
      repeatableSections.classList.remove("hidden");
    } else {
      repeatableSections.classList.add("hidden");
    }

    btnExtract.disabled = false;
    btnFill.disabled = false;

    const mapped = analysis.fields.filter((f) => f.mapped_value).length;
    const sectionCount = (analysis.repeatable_sections || []).filter(
      (s) => s.profile_section
    ).length;
    let msg = `${mapped} of ${analysis.fields.length} fields mapped.`;
    if (sectionCount > 0) {
      msg += ` ${sectionCount} repeatable section(s) detected.`;
    }
    msg += " Review and click Fill Form.";
    showMessage(msg, "success");
  }

  function renderFields(fields) {
    fieldsList.innerHTML = "";

    for (let i = 0; i < fields.length; i++) {
      const field = fields[i];
      const conf = field.confidence;
      const level = conf >= 0.8 ? "high" : conf >= 0.5 ? "medium" : "low";

      const card = document.createElement("div");
      card.className = `field-card ${level}`;
      card.dataset.index = i;

      // Header: label + badges
      const header = document.createElement("div");
      header.className = "field-header";

      const labelSpan = document.createElement("span");
      labelSpan.className = "field-label";
      labelSpan.textContent = field.label || "(no label)";
      header.appendChild(labelSpan);

      const badges = document.createElement("span");
      if (field.required) {
        const req = document.createElement("span");
        req.className = "field-badge required";
        req.textContent = "required";
        badges.appendChild(req);
      }
      const typeB = document.createElement("span");
      typeB.className = "field-badge type";
      typeB.textContent = field.field_type;
      badges.appendChild(typeB);
      header.appendChild(badges);
      card.appendChild(header);

      // Editable value
      const valueDiv = document.createElement("div");
      valueDiv.className = "field-value";

      if (
        (field.field_type === "select" || field.field_type === "combobox") &&
        field.options &&
        field.options.length > 0
      ) {
        const select = document.createElement("select");
        select.dataset.fieldIndex = i;
        // Add empty option
        const emptyOpt = document.createElement("option");
        emptyOpt.value = "";
        emptyOpt.textContent = "— Select —";
        select.appendChild(emptyOpt);
        for (const opt of field.options) {
          const o = document.createElement("option");
          o.value = opt.value;
          o.textContent = opt.text;
          if (opt.value === field.mapped_value || opt.text === field.mapped_value) {
            o.selected = true;
          }
          select.appendChild(o);
        }
        valueDiv.appendChild(select);
      } else if (
        field.field_type === "combobox" &&
        (!field.options || field.options.length === 0)
      ) {
        // Deferred options — show text input for the value to be matched at fill time
        const input = document.createElement("input");
        input.type = "text";
        input.dataset.fieldIndex = i;
        input.value = field.mapped_value || "";
        input.placeholder = "Type value to match...";
        valueDiv.appendChild(input);
        const note = document.createElement("span");
        note.textContent = "(options load when dropdown opens)";
        note.style.fontSize = "11px";
        note.style.color = "#9ca3af";
        note.style.display = "block";
        note.style.marginTop = "2px";
        valueDiv.appendChild(note);
      } else if (field.field_type === "textarea") {
        const ta = document.createElement("textarea");
        ta.dataset.fieldIndex = i;
        ta.value = field.mapped_value || "";
        ta.placeholder = "Enter value...";
        valueDiv.appendChild(ta);
      } else if (field.field_type === "checkbox") {
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.dataset.fieldIndex = i;
        cb.checked =
          field.mapped_value &&
          ["true", "yes", "1", "checked"].includes(field.mapped_value.toLowerCase());
        valueDiv.appendChild(cb);
      } else if (field.field_type === "file") {
        const span = document.createElement("span");
        span.textContent = field.mapped_value === "resume" ? "resume.pdf" : field.mapped_value;
        span.style.fontSize = "12px";
        span.style.color = "#6b7280";
        valueDiv.appendChild(span);
      } else {
        const input = document.createElement("input");
        input.type = "text";
        input.dataset.fieldIndex = i;
        input.value = field.mapped_value || "";
        input.placeholder = "Enter value...";
        valueDiv.appendChild(input);
      }
      card.appendChild(valueDiv);

      // Source info
      if (field.source_field) {
        const src = document.createElement("div");
        src.className = "field-source";
        src.textContent = `Source: ${field.source_field}`;
        card.appendChild(src);
      }

      // Confidence bar
      const bar = document.createElement("div");
      bar.className = "confidence-bar";
      const fill = document.createElement("div");
      fill.className = `confidence-fill ${level}`;
      fill.style.width = `${Math.round(conf * 100)}%`;
      bar.appendChild(fill);
      card.appendChild(bar);

      fieldsList.appendChild(card);
    }
  }

  /**
   * Read edited values from the UI back into currentAnalysis.
   */
  function updateAnalysisFromUI() {
    if (!currentAnalysis) return;

    const inputs = fieldsList.querySelectorAll("input, select, textarea");
    for (const input of inputs) {
      const idx = parseInt(input.dataset.fieldIndex, 10);
      if (isNaN(idx) || !currentAnalysis.fields[idx]) continue;

      if (input.type === "checkbox") {
        currentAnalysis.fields[idx].mapped_value = input.checked ? "true" : "false";
      } else {
        currentAnalysis.fields[idx].mapped_value = input.value;
      }
    }
  }

  // --- Fill results ---

  function handleFillResult(result) {
    fillResults.classList.remove("hidden");
    btnFill.disabled = false;

    const { filled, failed, errors } = result;
    resultsSummary.textContent = `Filled ${filled} fields, ${failed} failed.`;
    resultsSummary.className = failed > 0 ? "has-errors" : "all-good";

    resultsErrors.innerHTML = "";
    if (errors && errors.length > 0) {
      for (const err of errors) {
        const li = document.createElement("li");
        li.textContent = err;
        resultsErrors.appendChild(li);
      }
    }

    if (failed === 0) {
      showMessage("All fields filled. Review the form and submit manually.", "success");
    } else {
      showMessage(`${failed} field(s) could not be filled. See errors below.`, "error");
    }
  }
})();
