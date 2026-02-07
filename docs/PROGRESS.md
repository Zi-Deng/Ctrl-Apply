# Development Progress

## Session: 2026-02-04

### Summary

Took Ctrl+Apply from initial setup through live testing on a real Workday job application (Analog Devices ML Intern, PhD). Identified and fixed two major gaps in the form-filling pipeline: custom ARIA dropdown support and repeatable section handling. The tool went from filling 13 flat fields on page 1 to filling 124 fields across multiple Work Experience, Education, and Language entries on Workday's "My Experience" page.

---

### Phase 1: Initial Setup and First Test

Executed the full setup workflow:
- Verified the `ctrl-apply` micromamba environment, all imports, and Playwright
- Configured `data/profile.yaml` with user data and `data/resume.pdf`
- Launched Brave (not Chrome) with `--remote-debugging-port=9222` — CDP works identically
- Loaded the extension from `extension/` in `brave://extensions/`
- Started the backend: profile loaded, Playwright connected, WebSocket bridge active

**First test** on Workday page 1 (personal info): 13 of 14 fields mapped successfully. One unmapped field identified a gap.

---

### Phase 2: ARIA Combobox Support

**Problem:** Workday uses custom ARIA dropdown widgets (`role="combobox"`, `role="listbox"`, `role="option"`) instead of native `<select>` elements. The extractor only queried `input, select, textarea, [contenteditable="true"]` and missed these entirely. The "How Did You Hear About Us" dropdown was invisible to the tool.

**Root cause:** The DOM query in `extractor.js` didn't include ARIA combobox selectors, and the pipeline had no concept of a `combobox` field type.

**Fix — full pipeline changes across 6 files:**

| File | Change |
|---|---|
| `extension/content/extractor.js` | Expanded DOM query to include `[role="combobox"], [aria-haspopup="listbox"]`. Added `findAssociatedListbox()` to locate the listbox element via `aria-owns`/`aria-controls`, sibling traversal, ancestor search, and Workday `data-automation-id` patterns. Updated `getFieldType()` to detect combobox on both `<input>` and non-input elements. Updated `extractOptions()` to read `[role="option"]` elements from ARIA listboxes. Added guard to skip `role="option"` and `role="listbox"` elements from being treated as standalone fields. |
| `backend/models/form.py` | Added `listbox_selector: str` and `options_deferred: bool` to `FormField` and `ExtractedField`. Updated `field_type` description to include `combobox`. |
| `backend/services/llm_service.py` | Updated `FORM_ANALYSIS_SYSTEM` prompt with combobox rules. Updated `FormField` construction in `analyze_form()` to pass through `listbox_selector` and `options_deferred`. |
| `backend/services/playwright_service.py` | Added `_fill_combobox()` method: click trigger, wait for listbox, read live options if deferred, fuzzy match with `match_dropdown()`, click the matched option, Escape on failure. Added dispatch branch for `field.field_type == "combobox"`. |
| `backend/config.py` | Added `combobox_open_timeout: int = 3000` (ms to wait for ARIA listbox). |
| `extension/sidepanel/panel.js` | Updated field rendering: combobox with options renders as `<select>`, deferred combobox renders as text input with note "(options load when dropdown opens)". |

---

### Phase 3: Repeatable Section Support

**Problem:** Workday's "My Experience" page has repeatable sections (Work Experience, Education, Certifications, Languages, Websites). Each requires clicking an "Add" button to create entries before fields can be filled. The pipeline was a single-pass extract-analyze-fill that couldn't click buttons, wait for new DOM, or loop over profile entries.

Additionally: buttons with `type="button"` and `aria-haspopup="listbox"` (like Workday's Degree dropdown) were incorrectly skipped by the extractor.

**Investigation:** Inspected the live Workday DOM via Playwright CDP:
- All "Add" buttons share `data-automation-id="add-button"` (5 buttons, not unique)
- Buttons mapped by proximity to headings: Work Experience, Education, Certifications, Languages, Websites
- Work Experience section has NO visible fields until "Add" is clicked
- Education 1 has: School/University (multiselect search combobox), Degree (button combobox), Field of Study (multiselect search combobox)
- Workday uses IDs like `education-4--school`, `workExperience-1--jobTitle` for section entry fields

**Fix — changes across 8 files:**

| File | Change |
|---|---|
| `extension/content/extractor.js` | **Bug fix:** buttons with `aria-haspopup="listbox"` or `role="combobox"` are no longer skipped. **New:** `extractRepeatableSections()` detects "Add" buttons (Workday `data-automation-id="add-button"` first, generic text fallback), walks DOM for section headings, counts existing sub-entries. Both `extractAndSend()` and message handlers now include `repeatable_sections`. New `extract_section` message handler for backend-initiated re-extraction. |
| `backend/models/form.py` | **New:** `RepeatableSection` model (`section_name`, `add_button_index`, `add_button_selector`, `add_button_text`, `existing_entries`, `profile_section`). Extended `FormAnalysis` and `ExtractedForm` with `repeatable_sections: list[RepeatableSection]`. |
| `extension/service-worker.js` | `ws.onmessage` now intercepts `request_extraction` messages from backend instead of broadcasting. **New:** `handleBackendExtractionRequest()` sends `extract_section` to content script and relays result back as `extraction_result`. |
| `backend/config.py` | Added `add_button_wait: 1.5` (seconds after clicking Add), `extraction_timeout: 10.0` (seconds for re-extraction response), `max_section_entries: 10` (safety limit). |
| `backend/routers/ws.py` | **New:** `_safe_send()` with `asyncio.Lock` prevents interleaved WS writes. `request_extraction()` sends request via WS and awaits `asyncio.Future` resolved by incoming `extraction_result`. `fill_form` handler changed to `asyncio.create_task()` so WS loop stays free. New `extraction_result` message handler resolves pending futures. Injects `request_extraction` into `form_service` on connect. |
| `backend/services/form_service.py` | **New:** `SECTION_PROFILE_MAP` maps section headings to profile attributes. `_is_section_field()` uses regex to detect section selectors (e.g. `education-4--school`). `_build_entry_context()` builds focused LLM prompt for a single profile entry. `analyze()` now resolves `profile_section` for each repeatable section. **New:** `fill_with_sections()` — fills flat fields first (excluding section fields), then for each section: fills existing entry fields with per-entry context, clicks "Add" for new entries, re-extracts, diffs, analyzes, fills. |
| `extension/sidepanel/index.html` | Added `<section id="repeatable-sections">` with `<div id="sections-list">` between field mappings and fill results. |
| `extension/sidepanel/panel.js` | New `fill_progress` message handler. `handleFormAnalysis()` displays detected repeatable sections with existing entry counts and profile mappings. Sections display hidden on reset. |

**Concurrency design:**

```
WS receive loop --> fill_form msg --> asyncio.create_task(_handle_fill_form)
     |                                       |
     | (loop continues receiving)            v
     |                              fill flat fields
     |                                       |
     |                              click "Add" button
     |                                       |
     |                              send request_extraction --> WS send
     |                                       | (await future)
     v                                       |
receives extraction_result --> resolve future |
                                             v
                                    re-extract result received
                                             |
                                    diff -> analyze -> fill
                                             |
                                    send fill_result --> WS send
```

**Critical fix during testing:** The initial implementation filled ALL mapped fields (including section fields like School, Degree) during Step 1 (flat fill). Workday's combobox interactions inside section entries triggered page navigation back to the form's beginning. Fixed by:
1. Using regex patterns to identify section field selectors (e.g. `education-\d`, `workExperience-\d`)
2. Excluding section fields from the flat fill
3. Filling existing section entries separately with focused per-entry LLM context

---

### Test Results

**Workday "My Experience" page — final run:**

| Metric | Value |
|---|---|
| Fields filled | 124 |
| Fields failed | 3 |
| Sections processed | Work Experience, Education, Languages |
| Sections skipped | Certifications (none in profile), Websites (no profile mapping) |

**Failures (3):**
1. `Verbal*` proficiency — profile says "Native", Workday dropdown has options like "Advanced"/"Intermediate"/"Beginner"/"Fluent". Fuzzy match threshold (70) not met.
2. `Written*` proficiency — same issue as Verbal.
3. One other field (likely a combobox timeout).

**Root cause of remaining failures:** Language proficiency mismatch between profile terminology ("Native") and Workday's dropdown options. Fix: update `data/profile.yaml` to use Workday-compatible proficiency levels, or add synonym mappings.

---

### Known Issues

| Issue | Severity | Notes |
|---|---|---|
| Language proficiency "Native" doesn't match Workday dropdown options | Low | User can update profile.yaml to use "Advanced" or similar |
| Date fields may not fill correctly on all ATS platforms | Medium | Workday date pickers are custom widgets, not standard inputs |
| Section field detection uses hardcoded regex patterns | Medium | Works for Workday; other ATS platforms may use different ID conventions |
| `_is_section_field()` regex may match non-section fields on other platforms | Low | Only active when `repeatable_sections` are detected |
| No test suite | Medium | All testing is manual against live Workday pages |
| Cover letter generation not yet implemented | Low | Pipeline exists but not connected |

### Architecture After Changes

```
Content Script (extractor.js)
  |
  |-- extractFormFields()          Extracts all visible form fields
  |-- extractRepeatableSections()  Detects "Add" buttons + section headings
  |-- extract_section handler      Responds to backend re-extraction requests
  |
  v
Service Worker (service-worker.js)
  |
  |-- Relays form_extracted to backend
  |-- Intercepts request_extraction from backend
  |-- Sends extract_section to content script, returns extraction_result
  |
  v
WebSocket Router (ws.py)
  |
  |-- _safe_send() with asyncio.Lock
  |-- request_extraction() sends request, awaits Future
  |-- extraction_result resolves pending Future
  |-- fill_form runs as asyncio.create_task()
  |
  v
Form Service (form_service.py)
  |
  |-- analyze()                    LLM analysis + section resolution
  |-- fill()                       Simple flat field fill
  |-- fill_with_sections()         Multi-step orchestration:
  |     |-- Step 1: Fill flat fields (exclude section fields)
  |     |-- Step 2a: Fill existing section entries with per-entry context
  |     |-- Step 2b: Click Add -> re-extract -> diff -> analyze -> fill
  |
  v
Playwright Service (playwright_service.py)
  |
  |-- fill_form()                  Fills fields by type
  |-- _fill_combobox()             ARIA combobox: click -> wait -> match -> click option
  |-- match_dropdown()             Fuzzy matching with rapidfuzz WRatio
```

### Files Modified (Complete List)

| File | Lines | Type of Change |
|---|---|---|
| `extension/content/extractor.js` | 408 | Bug fix, combobox detection, section detection, new handlers |
| `backend/models/form.py` | 79 | New RepeatableSection model, extended existing models |
| `backend/services/form_service.py` | 478 | New fill_with_sections orchestration, section field detection |
| `backend/routers/ws.py` | 251 | Concurrency refactor, request-response extraction protocol |
| `backend/services/playwright_service.py` | 281 | New combobox fill method |
| `backend/services/llm_service.py` | 198 | Updated LLM system prompt for combobox |
| `backend/config.py` | 43 | New settings for combobox and repeatable sections |
| `extension/service-worker.js` | 155 | Backend extraction request handler |
| `extension/sidepanel/panel.js` | 424 | Section display, fill progress, combobox rendering |
| `extension/sidepanel/index.html` | 69 | Repeatable sections display area |

### Next Steps

1. **Fix language proficiency mapping** — add synonym support or update profile.yaml
2. **Date picker handling** — Workday uses custom date widgets that may need special Playwright interaction
3. **Education combobox refinement** — School/University is a multiselect search that may need typing + selection
4. **Test on other ATS platforms** — verify no regressions on Greenhouse, Lever, etc.
5. **Add automated tests** — at minimum, unit tests for `_is_section_field()`, `match_dropdown()`, `_resolve_profile_section()`
6. **Update README.md** — add combobox and repeatable sections to feature list and WebSocket protocol docs
