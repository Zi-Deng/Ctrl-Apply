# Ctrl+Apply

A semi-automated job application tool that combines a Python FastAPI backend with a Chrome extension to analyze and fill job application forms. The backend uses Claude (via `claude-agent-sdk`) to intelligently map form fields to your profile data, and Playwright to fill forms through Chrome's DevTools Protocol (CDP). The Chrome extension provides a side panel UI and read-only DOM extraction — it never modifies the page itself.

**Tested on Workday with 124 fields filled across Work Experience, Education, and Language sections.**

## Table of Contents

- [How It Works](#how-it-works)
- [Features](#features)
- [Quick Start](#quick-start)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Supported ATS Platforms](#supported-ats-platforms)
- [Profile Configuration](#profile-configuration)
- [Troubleshooting](#troubleshooting)
- [Architecture](#architecture)
- [API Reference](#api-reference)
- [Development](#development)
- [Known Issues](#known-issues)

## How It Works

```
Chrome Extension                              Python Backend (FastAPI)
┌─────────────────────────────┐               ┌─────────────────────────────┐
│                             │               │                             │
│  1. Detect ATS platform     │               │                             │
│  2. Extract form fields     │──WebSocket──▶│  3. Load user profile       │
│     + repeatable sections   │               │  4. Send fields + profile   │
│     (read-only DOM scan)    │               │     to Claude LLM           │
│                             │               │  5. Claude returns field    │
│                             │◀─────────────│     mappings + confidence   │
│  6. Show mappings in        │               │                             │
│     side panel for review   │               │                             │
│  7. User edits & clicks     │               │                             │
│     "Fill Form"             │──WebSocket──▶│  8. For each section:       │
│                             │               │     - Fill flat fields      │
│                             │               │     - Click "Add" buttons   │
│  9. See progress updates    │◀─────────────│     - Re-extract new fields │
│                             │               │     - Analyze & fill        │
│ 10. Review & submit         │               │  9. Playwright fills via    │
│     manually                │               │     CDP (port 9222)         │
│                             │               │                             │
└─────────────────────────────┘               └─────────────────────────────┘
```

### Workflow

1. A content script detects the ATS platform from the URL and extracts all visible form fields (labels, types, options, selectors) plus repeatable sections (Work Experience, Education, etc.) without modifying the DOM.
2. The extension's service worker relays the extracted form data to the backend over a persistent WebSocket connection.
3. The backend loads the user's profile from a YAML file and serializes it into a text prompt.
4. The profile context and extracted fields are sent to Claude via `claude-agent-sdk`'s `query()` async iterator. Claude returns a JSON mapping of each field to the appropriate profile value, along with a confidence score (0-1).
5. The side panel displays the mappings as interactive cards. Each card shows the field label, the proposed value, the source profile field, and a color-coded confidence bar (green >= 0.8, orange 0.5-0.79, red < 0.5). Users can edit any value before filling.
6. When the user clicks "Fill Form":
   - **Flat fields** (non-section) are filled first
   - **Repeatable sections** are processed: for each Work Experience/Education/Language entry in your profile, the tool clicks "Add", waits for new fields, re-extracts, analyzes with focused context, and fills
   - Progress updates are shown in real-time
7. The user reviews the filled form and submits manually.

## Features

### Core Capabilities

- **LLM-powered field mapping** — Claude analyzes form structure and maps fields to profile data with confidence scoring, handling arbitrary form layouts without hardcoded selectors.
- **ARIA combobox support** — Handles custom dropdown widgets (`role="combobox"`, `role="listbox"`) used by Workday and other modern ATS platforms. Opens dropdowns, reads live options, fuzzy-matches values, and clicks the right option.
- **Repeatable section filling** — Automatically handles Work Experience, Education, Certifications, and Languages sections that require clicking "Add" buttons to create new entries.
- **Human-in-the-loop** — All mappings are shown for review before filling. The extension never submits forms automatically.
- **Fuzzy dropdown matching** — Uses rapidfuzz (WRatio scorer, threshold 70) to match profile values to dropdown options even when wording differs (e.g., "United States" matching "United States of America").

### Platform Support

- **11 ATS platforms detected** — Greenhouse, Workday, Lever, iCIMS, SmartRecruiters, Ashby, BambooHR, Jobvite, Taleo, Breezy HR, and Recruitee, plus a generic fallback.
- **Auto-extraction** — On recognized platforms, form fields are automatically extracted 1.5 seconds after page load.
- **Workday-optimized** — Special handling for Workday's `data-automation-id` attributes, multi-select search comboboxes, and repeatable section structure.

### Technical Features

- **Cloud and local LLM modes** — Default uses Claude Max subscription; local mode routes through Ollama for fully offline operation.
- **Comprehensive profile model** — Supports personal info, education (multiple entries), experience (multiple entries), projects, skills, publications, languages, certifications, demographics, work authorization, and common application answers.
- **Job and application tracking** — DuckDB database for recording job listings and application history.
- **Real-time progress** — WebSocket-based progress updates during multi-step section filling.

## Quick Start

```bash
# 1. Create the environment
micromamba create -f environment.yml -y

# 2. Install Playwright browser
micromamba run -n ctrl-apply playwright install chromium

# 3. Set up your profile
cp data/profile.template.yaml data/profile.yaml
# Edit data/profile.yaml with your information

# 4. Copy your resume
cp /path/to/your/resume.pdf data/resume.pdf

# 5. Launch Chrome/Brave with remote debugging
# For Chrome:
google-chrome --remote-debugging-port=9222
# For Brave:
brave --remote-debugging-port=9222

# 6. Load the extension in chrome://extensions/ (Developer mode → Load unpacked → select extension/)

# 7. Start the backend
micromamba run -n ctrl-apply python -m backend.main

# 8. Open a job application, click the extension icon, and click "Analyze Form"
```

## Prerequisites

- **Python 3.12** (managed via micromamba)
- **micromamba** — [Installation guide](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html)
- **Google Chrome, Chromium, or Brave** — Must be launchable with `--remote-debugging-port`
- **Claude Max subscription** (for cloud LLM mode) or **Ollama** with a local model (for local mode)

## Installation

### 1. Create the micromamba environment

```bash
micromamba create -f environment.yml -y
```

This creates a `ctrl-apply` environment with Python 3.12 and installs all dependencies (FastAPI, Playwright, claude-agent-sdk, DuckDB, Polars, rapidfuzz, etc.) in editable mode.

### 2. Install the Playwright browser

```bash
micromamba run -n ctrl-apply playwright install chromium
```

### 3. Set up your profile

```bash
cp data/profile.template.yaml data/profile.yaml
```

Edit `data/profile.yaml` with your information. This is the most important step — the quality of form filling depends on the completeness and accuracy of your profile. See [Profile Configuration](#profile-configuration) for detailed guidance.

### 4. Add your resume

```bash
cp /path/to/your/resume.pdf data/resume.pdf
```

This file is uploaded to file input fields (e.g., "Upload Resume").

### 5. Install the Chrome extension

1. Open `chrome://extensions/` in Chrome (or `brave://extensions/` in Brave).
2. Enable **Developer mode** (top right toggle).
3. Click **Load unpacked** and select the `extension/` directory.
4. The Ctrl+Apply icon appears in the toolbar. Click it to open the side panel.

## Usage

### Step 1: Launch your browser with remote debugging

**Option A: Use the provided script (Chrome only)**

```bash
./scripts/launch-chrome.sh
```

**Option B: Launch manually**

```bash
# Chrome
google-chrome --remote-debugging-port=9222

# Brave
brave --remote-debugging-port=9222

# Chromium
chromium --remote-debugging-port=9222
```

You can customize the port:

```bash
CDP_PORT=9333 ./scripts/launch-chrome.sh
```

### Step 2: Start the backend server

```bash
micromamba run -n ctrl-apply python -m backend.main
```

The server starts on `http://127.0.0.1:8765`. On startup it:
- Creates the `data/` directory and subdirectories if missing
- Initializes the DuckDB database at `data/jobs.duckdb`
- Configures the LLM service (cloud or local mode)
- Attempts to connect to Chrome via CDP (non-fatal if Chrome isn't running yet)

Verify the server is running:

```bash
curl http://127.0.0.1:8765/health
```

Returns:
```json
{"status": "ok", "playwright_connected": true, "llm_mode": "cloud"}
```

### Step 3: Fill a job application

1. **Navigate** to a job application page in the browser instance you launched with remote debugging.

2. **Open the side panel** by clicking the Ctrl+Apply extension icon.

3. **Check connection status**:
   - Green dot next to "Backend" = WebSocket connected
   - Green dot next to "CDP" = Playwright connected to browser
   - If either is red, click "Reconnect"

4. **Click "Analyze Form"**. The extension:
   - Extracts all visible form fields
   - Detects repeatable sections (Work Experience, Education, etc.)
   - Sends data to the backend for LLM analysis

5. **Review the field mappings**. Each field card shows:
   - The field label and type badge (text, email, select, combobox, etc.)
   - The proposed value (editable — click to modify)
   - The source profile field (e.g., `personal_info.email`)
   - A confidence bar (green = high, orange = medium, red = low)

6. **Review repeatable sections** (if detected). The side panel shows:
   - Section name (e.g., "Work Experience")
   - Number of existing entries on the page
   - Profile mapping (e.g., "experience")

7. **Edit any values** as needed. Changes are saved automatically.

8. **Click "Fill Form"**. The backend:
   - Fills flat (non-section) fields first
   - For each repeatable section:
     - Fills existing entry fields with corresponding profile data
     - Clicks "Add" for each additional entry needed
     - Waits for new fields to appear
     - Re-extracts, analyzes, and fills
   - Shows progress updates in real-time

9. **Review the filled form** and submit manually.

### Understanding Confidence Scores

| Color | Score Range | Meaning |
|-------|-------------|---------|
| Green | 0.8 - 1.0 | High confidence — exact or near-exact match |
| Orange | 0.5 - 0.79 | Medium confidence — semantic match, review recommended |
| Red | 0.0 - 0.49 | Low confidence — uncertain match, definitely review |

## Configuration

All backend settings use the `CTRL_APPLY_` environment variable prefix via pydantic-settings.

### Server Settings

| Setting | Default | Env Variable | Description |
|---------|---------|--------------|-------------|
| `host` | `127.0.0.1` | `CTRL_APPLY_HOST` | Server bind address |
| `port` | `8765` | `CTRL_APPLY_PORT` | Server port |

### LLM Settings

| Setting | Default | Env Variable | Description |
|---------|---------|--------------|-------------|
| `llm_mode` | `cloud` | `CTRL_APPLY_LLM_MODE` | `cloud` (Claude Max) or `local` (Ollama) |
| `local_model` | `qwen3-coder` | `CTRL_APPLY_LOCAL_MODEL` | Model name for local/Ollama mode |
| `local_ollama_url` | `http://localhost:11434` | `CTRL_APPLY_LOCAL_OLLAMA_URL` | Ollama server endpoint |

### CDP Settings

| Setting | Default | Env Variable | Description |
|---------|---------|--------------|-------------|
| `cdp_url` | `http://localhost:9222` | `CTRL_APPLY_CDP_URL` | Chrome DevTools Protocol endpoint |

### Form Filling Settings

| Setting | Default | Env Variable | Description |
|---------|---------|--------------|-------------|
| `fill_delay_min` | `0.2` | `CTRL_APPLY_FILL_DELAY_MIN` | Minimum delay between field fills (seconds) |
| `fill_delay_max` | `0.8` | `CTRL_APPLY_FILL_DELAY_MAX` | Maximum delay between field fills (seconds) |
| `dropdown_match_threshold` | `70` | `CTRL_APPLY_DROPDOWN_MATCH_THRESHOLD` | Fuzzy match threshold for dropdowns (0-100) |
| `combobox_open_timeout` | `3000` | `CTRL_APPLY_COMBOBOX_OPEN_TIMEOUT` | Timeout for ARIA listbox to appear (ms) |

### Repeatable Section Settings

| Setting | Default | Env Variable | Description |
|---------|---------|--------------|-------------|
| `add_button_wait` | `1.5` | `CTRL_APPLY_ADD_BUTTON_WAIT` | Seconds to wait after clicking Add button |
| `extraction_timeout` | `10.0` | `CTRL_APPLY_EXTRACTION_TIMEOUT` | Timeout for re-extraction requests (seconds) |
| `max_section_entries` | `10` | `CTRL_APPLY_MAX_SECTION_ENTRIES` | Maximum entries to fill per section (safety limit) |

### Using Local LLM Mode

To use a locally-hosted model via Ollama instead of Claude:

```bash
# Start Ollama with your preferred model
ollama serve
ollama pull qwen3-coder

# Start the backend in local mode
export CTRL_APPLY_LLM_MODE=local
export CTRL_APPLY_LOCAL_MODEL=qwen3-coder
micromamba run -n ctrl-apply python -m backend.main
```

The backend sets `ANTHROPIC_BASE_URL` to point at Ollama. The same `claude-agent-sdk` code path is used for both modes.

## Supported ATS Platforms

| Platform | URL Pattern | Notes |
|----------|-------------|-------|
| Greenhouse | `boards.greenhouse.io/*`, `job-boards.greenhouse.io/*` | Standard form extraction |
| **Workday** | `*.myworkdayjobs.com/*`, `*.myworkdaysite.com/*` | Full support including repeatable sections, ARIA comboboxes |
| Lever | `jobs.lever.co/*`, `*.lever.co/*` | Standard form extraction |
| iCIMS | `*.icims.com/*` | Standard form extraction |
| SmartRecruiters | `*.smartrecruiters.com/*` | Standard form extraction |
| Ashby | `*.ashbyhq.com/*` | Standard form extraction |
| BambooHR | `*.bamboohr.com/*` | Standard form extraction |
| Jobvite | `*.jobvite.com/*` | Standard form extraction |
| Taleo | `*.taleo.net/*` | Standard form extraction |
| Breezy HR | `*.breezy.hr/*` | Standard form extraction |
| Recruitee | `*.recruitee.com/*` | Standard form extraction |

On recognized platforms, the content script auto-extracts form fields 1.5 seconds after page load. On unrecognized platforms, click "Analyze Form" to trigger manual extraction.

## Profile Configuration

Your profile at `data/profile.yaml` is the source of truth for all form filling. The more complete and accurate it is, the better the results.

### Structure Overview

```yaml
personal_info:
  first_name: "John"
  last_name: "Doe"
  email: "john.doe@example.com"
  phone: "+1-555-123-4567"
  address:
    street: "123 Main St"
    city: "Boston"
    state: "MA"
    zip: "02101"
    country: "United States"
  linkedin_url: "https://linkedin.com/in/johndoe"
  github_url: "https://github.com/johndoe"
  portfolio_url: "https://johndoe.dev"

education:
  - degree: "Ph.D."
    field: "Electrical Engineering"
    institution: "MIT"
    gpa: "3.9"
    start_date: "2020-09"
    end_date: "2025-05"
    description: "Research focus on machine learning and signal processing"
  - degree: "B.S."
    field: "Computer Science"
    institution: "Stanford University"
    gpa: "3.8"
    start_date: "2016-09"
    end_date: "2020-05"

experience:
  - title: "Machine Learning Research Intern"
    company: "Google"
    location: "Mountain View, CA"
    start_date: "2023-05"
    end_date: "2023-08"
    description: "Developed novel transformer architectures for speech recognition"
  - title: "Software Engineering Intern"
    company: "Meta"
    location: "Menlo Park, CA"
    start_date: "2022-05"
    end_date: "2022-08"
    description: "Built recommendation systems serving millions of users"

projects:
  - name: "Neural Speech Synthesis"
    description: "End-to-end TTS system using diffusion models"
    url: "https://github.com/johndoe/neural-tts"
    technologies: ["Python", "PyTorch", "CUDA"]

skills:
  technical: ["Python", "C++", "CUDA", "TensorFlow", "PyTorch"]
  frameworks: ["FastAPI", "React", "Docker"]
  tools: ["Git", "Linux", "AWS", "GCP"]

publications:
  - title: "Efficient Attention Mechanisms for Long Sequences"
    venue: "NeurIPS 2024"
    year: "2024"
    url: "https://arxiv.org/abs/2024.xxxxx"

languages:
  - language: "English"
    proficiency: "Native"  # Use "Fluent" or "Advanced" for Workday compatibility
  - language: "Spanish"
    proficiency: "Intermediate"

certifications:
  - "AWS Certified Machine Learning - Specialty"
  - "Google Cloud Professional ML Engineer"

demographics:
  gender: ""           # Leave blank to skip
  ethnicity: ""        # Leave blank to skip
  veteran_status: ""   # Leave blank to skip
  disability_status: "" # Leave blank to skip

work_authorization:
  us_authorized: true
  requires_sponsorship: false
  visa_status: "F-1 OPT"

preferences:
  willing_to_relocate: true
  remote_preference: "Hybrid"
  start_date: "2025-06-01"

common_answers:
  hear_about_us: "LinkedIn"
  cover_letter_template: ""
  extra:
    years_of_experience: "5"
    salary_expectation: "150000"
```

### Section Details

#### personal_info
Basic contact information. All fields are used frequently.

#### education (list)
Add multiple entries for each degree. The order matters — most recent first. Each entry can include:
- `degree`: "Ph.D.", "M.S.", "B.S.", "B.A.", etc.
- `field`: Your major/field of study
- `institution`: Full university name
- `gpa`: Your GPA (optional)
- `start_date`, `end_date`: Format as "YYYY-MM" or "YYYY"
- `description`: Relevant coursework, thesis topic, honors (optional)

#### experience (list)
Add multiple entries for each position. Most recent first. Each entry includes:
- `title`: Your job title
- `company`: Company name
- `location`: City, State or City, Country
- `start_date`, `end_date`: Format as "YYYY-MM"
- `description`: Key responsibilities and achievements

#### languages (list)
For Workday compatibility, use proficiency levels like:
- "Native" or "Fluent" for native/bilingual
- "Advanced" for professional working proficiency
- "Intermediate" for limited working proficiency
- "Beginner" for elementary proficiency

Note: Some ATS platforms (like Workday) use different dropdown options. If you see "No matching option" errors, check what options are available and update your profile accordingly.

#### work_authorization
Critical for filtering and auto-filling authorization questions:
- `us_authorized`: Can you legally work in the US?
- `requires_sponsorship`: Do you need visa sponsorship?
- `visa_status`: Current status (e.g., "F-1 OPT", "H-1B", "Green Card", "Citizen")

## Troubleshooting

### Connection Issues

**Backend not connected (red dot)**
```bash
# Check if server is running
curl http://127.0.0.1:8765/health

# Restart the server
micromamba run -n ctrl-apply python -m backend.main
```

**CDP not connected (red dot)**
```bash
# Check if Chrome is running with remote debugging
curl http://localhost:9222/json/version

# Relaunch Chrome with the flag
google-chrome --remote-debugging-port=9222
```

### Form Filling Issues

**"No matching option for 'X'"**
- The profile value doesn't match any dropdown option
- Check the actual dropdown options on the page
- Update your profile.yaml to use compatible terminology

**Fields not being detected**
- Click "Analyze Form" manually
- Some dynamic forms need time to load — wait a few seconds
- Check the browser console for extraction errors

**Page navigates away during fill**
- This usually happens with section fields on multi-step forms
- The tool should now handle this correctly
- If it persists, fill sections one at a time

**Combobox not filling correctly**
- Some comboboxes require typing to trigger options
- The tool attempts multiple strategies (click, type first char, etc.)
- Check the backend logs for specific errors

### Performance Issues

**LLM analysis is slow**
- Cloud mode depends on API latency
- Try local mode with Ollama for faster responses
- Reduce the number of fields by focusing on one section at a time

**Too many entries being added**
- Adjust `max_section_entries` in configuration
- Or reduce the number of entries in your profile

### Viewing Logs

The backend logs to stdout. Look for:
- `INFO`: Normal operations
- `WARNING`: Non-fatal issues (e.g., dropdown match failures)
- `ERROR`: Problems that need attention

```bash
# Run with more verbose output
micromamba run -n ctrl-apply python -m backend.main 2>&1 | tee backend.log
```

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Chrome Browser                                  │
│  ┌─────────────────┐    ┌──────────────────┐    ┌─────────────────────┐    │
│  │  Content Script │    │  Service Worker  │    │     Side Panel      │    │
│  │   extractor.js  │◀──▶│ service-worker.js│◀──▶│     panel.js        │    │
│  │   detector.js   │    │                  │    │                     │    │
│  └────────┬────────┘    └────────┬─────────┘    └─────────────────────┘    │
│           │                      │                                          │
└───────────┼──────────────────────┼──────────────────────────────────────────┘
            │                      │ WebSocket
            │ CDP (port 9222)      │ (port 8765)
            ▼                      ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                           Python Backend                                   │
│  ┌────────────────┐    ┌────────────────┐    ┌────────────────────────┐  │
│  │   ws.py        │◀──▶│ form_service.py│◀──▶│    llm_service.py     │  │
│  │  (WebSocket)   │    │ (Orchestrator) │    │  (Claude/Ollama)      │  │
│  └────────────────┘    └───────┬────────┘    └────────────────────────┘  │
│                                │                                          │
│                                ▼                                          │
│                    ┌────────────────────────┐                             │
│                    │ playwright_service.py  │◀──── CDP ────┐              │
│                    │    (Form Filling)      │              │              │
│                    └────────────────────────┘              │              │
│                                                            │              │
└────────────────────────────────────────────────────────────┼──────────────┘
                                                             │
                                                     Fills forms via
                                                     Chrome DevTools
                                                     Protocol
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| **Extractor** | `extension/content/extractor.js` | DOM scanning, field detection, section detection |
| **Detector** | `extension/content/detector.js` | ATS platform identification |
| **Service Worker** | `extension/service-worker.js` | WebSocket bridge, message routing |
| **Side Panel** | `extension/sidepanel/panel.js` | UI, user interaction, result display |
| **WebSocket Router** | `backend/routers/ws.py` | Message handling, concurrency management |
| **Form Service** | `backend/services/form_service.py` | Orchestration, section filling logic |
| **LLM Service** | `backend/services/llm_service.py` | Claude/Ollama integration |
| **Playwright Service** | `backend/services/playwright_service.py` | Browser automation, field filling |
| **Profile Service** | `backend/services/profile_service.py` | YAML loading, prompt generation |

### Repeatable Section Flow

```
1. Initial extraction detects sections with "Add" buttons
   └── extractRepeatableSections() in extractor.js

2. Analysis resolves section names to profile keys
   └── "Work Experience" → profile.experience
   └── "Education" → profile.education

3. fill_with_sections() orchestrates multi-step fill:
   a. Fill flat fields (non-section)
   b. For each section with profile entries:
      i.   Fill existing entry fields
      ii.  Click "Add" button via Playwright
      iii. Wait for DOM to update
      iv.  Request re-extraction via WebSocket
      v.   Diff to find new fields
      vi.  Analyze new fields with focused context
      vii. Fill new fields
      viii. Repeat for next entry
```

## API Reference

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Server health check. Returns `{status, playwright_connected, llm_mode}`. |
| `GET` | `/api/profile/` | Returns the current user profile as JSON. |
| `POST` | `/api/profile/reload` | Reloads the profile from disk and returns it. |
| `POST` | `/api/form/analyze` | Accepts an `ExtractedForm` JSON body, returns a `FormAnalysis`. |
| `POST` | `/api/form/fill` | Accepts a `FormAnalysis` JSON body, fills the form, returns `{filled, failed, errors}`. |

### WebSocket Protocol

Connect to `ws://127.0.0.1:8765/ws`. Messages are JSON objects with a `type` field.

**Client to server:**

| Type | Data | Description |
|------|------|-------------|
| `ping` | — | Health check. Server replies with `pong`. |
| `form_extracted` | `ExtractedForm` | Submit extracted form fields for LLM analysis. |
| `fill_form` | `FormAnalysis` | Fill form fields via Playwright. |
| `update_field` | Field update | Acknowledge a client-side field edit. |
| `connect_cdp` | — | Trigger CDP reconnection. |
| `status` | — | Request Playwright connection status. |

**Server to client:**

| Type | Data | Description |
|------|------|-------------|
| `pong` | — | Response to `ping`. |
| `form_analysis` | `FormAnalysis` | LLM field mapping results with `repeatable_sections`. |
| `fill_result` | `{filled, failed, errors}` | Form fill results. |
| `fill_progress` | `{message}` | Real-time progress during section filling. |
| `analyzing` | `{message}` | Status update: analysis in progress. |
| `filling` | `{message}` | Status update: filling in progress. |
| `cdp_connected` | — | CDP connection established. |
| `status` | `{playwright_connected}` | Current Playwright connection state. |
| `error` | `{message}` | Error message. |

**Internal (backend-initiated):**

| Type | Direction | Description |
|------|-----------|-------------|
| `request_extraction` | Server → Extension | Request fresh DOM extraction during section filling. |
| `extraction_result` | Extension → Server | Response with extracted fields. |

## Development

All commands must be run in the `ctrl-apply` micromamba environment.

| Action | Command |
|--------|---------|
| Run server | `micromamba run -n ctrl-apply python -m backend.main` |
| Lint check | `micromamba run -n ctrl-apply ruff check backend/` |
| Lint fix | `micromamba run -n ctrl-apply ruff check --fix backend/` |
| Format check | `micromamba run -n ctrl-apply ruff format --check backend/` |
| Format fix | `micromamba run -n ctrl-apply ruff format backend/` |
| Import check | `micromamba run -n ctrl-apply python -c "from backend.main import app"` |
| Reinstall deps | `micromamba run -n ctrl-apply pip install -e ".[dev]"` |

### Code Style

- Python: Ruff with `line-length=100`, `target-version="py310"`, rules `E`, `F`, `I`
- JavaScript: Vanilla JS, no build step, IIFE pattern for content scripts
- All Python files start with `from __future__ import annotations`

### Project Structure

```
Ctrl+Apply/
├── backend/                        Python FastAPI backend
│   ├── main.py                     App entry point
│   ├── config.py                   Settings (pydantic-settings)
│   ├── db.py                       DuckDB connection
│   ├── models/
│   │   ├── form.py                 FormField, FormAnalysis, RepeatableSection
│   │   ├── profile.py              UserProfile (13 Pydantic models)
│   │   ├── job.py                  JobListing
│   │   └── application.py          Application tracking
│   ├── services/
│   │   ├── form_service.py         Orchestrator (fill_with_sections)
│   │   ├── llm_service.py          Claude/Ollama wrapper
│   │   ├── playwright_service.py   CDP + form filling
│   │   └── profile_service.py      YAML loading
│   └── routers/
│       ├── ws.py                   WebSocket (concurrency, re-extraction)
│       ├── profile.py              Profile REST API
│       └── form.py                 Form REST API
├── extension/                      Chrome MV3 extension
│   ├── manifest.json
│   ├── service-worker.js           WebSocket bridge
│   ├── content/
│   │   ├── detector.js             ATS detection
│   │   └── extractor.js            DOM extraction + sections
│   └── sidepanel/
│       ├── index.html
│       ├── panel.js                UI logic
│       └── panel.css
├── data/                           User data (gitignored)
├── scripts/
│   └── launch-chrome.sh
├── docs/
│   ├── PROGRESS.md                 Development progress
│   └── USAGE_GUIDE.md              Step-by-step setup guide
├── pyproject.toml
└── environment.yml
```

## Known Issues

| Issue | Severity | Workaround |
|-------|----------|------------|
| CDP connection fails at startup if Chrome not running | Low | Click "Reconnect" in side panel after launching Chrome |
| Language proficiency "Native" may not match Workday options | Low | Use "Advanced" or "Fluent" in profile.yaml |
| Date fields on some platforms use custom widgets | Medium | Manual date entry may be required |
| No test suite | Medium | All testing is currently manual |
| No CI/CD pipeline | Low | — |

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run `ruff check` and `ruff format` before committing
4. Submit a pull request

See `docs/PROGRESS.md` for current development status and planned improvements.
