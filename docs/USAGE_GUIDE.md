# Ctrl+Apply — Complete Setup & Testing Guide

## Overview

This guide walks through setting up Ctrl+Apply from scratch on Linux, configuring it with your real profile and resume, and testing it on a live internship application. The tool uses a Python backend (FastAPI + Playwright + Claude) paired with a Chrome extension to extract, analyze, and fill job application forms.

---

## Phase 1: Create the Python Environment

```bash
cd /home/zi/Work/github/Ctrl+Apply

# Create the micromamba environment (installs Python 3.12 + all dependencies)
micromamba create -f environment.yml -y

# Install the Playwright Chromium browser binary (~110 MB)
micromamba run -n ctrl-apply playwright install chromium
```

**Verify** the install succeeded:
```bash
micromamba run -n ctrl-apply python -c "from backend.main import app; print('Import OK')"
```

---

## Phase 2: Configure Your Profile & Resume

### 2a. Create `data/profile.yaml`

```bash
cp data/profile.template.yaml data/profile.yaml
```

Open `data/profile.yaml` in your editor and fill in your real information. The file has these sections:

| Section | What to fill | Notes |
|---------|-------------|-------|
| `personal_info` | Name, email, phone, address, LinkedIn/GitHub URLs | `first_name`, `last_name`, `email` are **required** |
| `education` | Degree(s), institution, field, GPA, dates | List — add one `- degree:` block per entry |
| `experience` | Job title, company, dates, description | List — add one `- title:` block per entry (include internships) |
| `projects` | Project name, description, technologies | List — add notable projects |
| `skills` | `technical`, `frameworks`, `tools` sub-lists | Flat string lists, e.g. `["Python", "C++"]` |
| `languages` | Language + proficiency | Pre-filled with English/Native |
| `demographics` | Gender, ethnicity, veteran/disability status | Optional — leave blank to skip; many applications ask these |
| `work_authorization` | `us_authorized`, `requires_sponsorship`, `visa_status` | Defaults to US authorized, no sponsorship |
| `preferences` | Relocate, remote preference, start date | e.g. `start_date: "2026-06"` for summer internship |
| `common_answers` | "How did you hear about us", cover letter, extras | The `extra: {}` dict can hold any custom Q&A pairs |

**Tips for internship applications:**
- Under `experience`, include any relevant internships, research positions, or TA roles
- Under `preferences.start_date`, put your actual availability (e.g. `"2026-05"` or `"Immediately"`)
- Under `work_authorization.visa_status`, be specific (e.g. `"US Citizen"`, `"F-1 OPT"`, `"F-1 CPT"`)
- Under `demographics`, fill these out if you want them auto-filled (many US applications have optional EEO questions)
- Under `common_answers.extra`, add any recurring answers, e.g. `years_of_experience: "1"` or `salary_expectation: "Negotiable"`

### 2b. Place your resume

Copy your resume PDF into the data directory:
```bash
cp /path/to/your/resume.pdf data/resume.pdf
```

This file is used when applications have a file upload field — Playwright will upload it automatically.

---

## Phase 3: Launch Chrome with Remote Debugging

Playwright needs a CDP (Chrome DevTools Protocol) connection to fill forms in your real browser. This requires Chrome to be started with a debugging flag.

**Important:** You must close ALL existing Chrome windows/processes first, then relaunch. If any Chrome process is already running, the debugging flag is silently ignored.

```bash
# 1. Close all Chrome instances
# (save your work in any open tabs first)
pkill -f chrome || true

# 2. Wait a moment for processes to terminate, then relaunch
# Option A: Use the included script (auto-detects Chrome binary)
./scripts/launch-chrome.sh

# Option B: Launch manually (recommended — uses your existing profile)
google-chrome --remote-debugging-port=9222 &
```

> **Note on the launch script:** If you use `./scripts/launch-chrome.sh` without setting `CHROME_USER_DATA`, it passes an empty `--user-data-dir` to Chrome, which creates a temporary profile. This means your existing extensions and bookmarks won't be available. To use your normal profile with the script, run:
> ```bash
> CHROME_USER_DATA=~/.config/google-chrome ./scripts/launch-chrome.sh
> ```
> Or just use **Option B** above (manual launch), which uses your default profile automatically.

**Verify** Chrome debugging is active by visiting this URL in Chrome:
```
http://localhost:9222/json/version
```
You should see a JSON response with Chrome version info. If you get a connection error, Chrome was not launched with the debugging port.

---

## Phase 4: Install the Chrome Extension

1. In Chrome, navigate to `chrome://extensions/`
2. Enable **Developer mode** (toggle in the top-right corner)
3. Click **"Load unpacked"**
4. Select the `extension/` directory inside the repository:
   `/home/zi/Work/github/Ctrl+Apply/extension`
5. The extension "Ctrl+Apply" (v0.1.0) should appear in the list
6. Pin the extension icon in your toolbar (click the puzzle piece icon in Chrome's toolbar, then pin Ctrl+Apply)

The extension will show a red "Disconnected" indicator until the backend is running.

---

## Phase 5: Start the Backend Server

Open a new terminal (keep Chrome running):

```bash
cd /home/zi/Work/github/Ctrl+Apply
micromamba run -n ctrl-apply python -m backend.main
```

You should see startup logs similar to:
```
Starting Ctrl+Apply backend on 127.0.0.1:8765
LLM mode: cloud (Claude Max subscription)
```

If Chrome is running with debugging, you'll also see a successful CDP connection log. If not, you'll see a warning — that's fine, it retries on demand.

**Verify** the backend in another terminal:
```bash
curl http://127.0.0.1:8765/health
```

Expected response:
```json
{"status": "ok", "playwright_connected": true, "llm_mode": "cloud"}
```

- `playwright_connected: true` — Playwright successfully connected to Chrome via CDP
- `playwright_connected: false` — Chrome isn't running with debugging, or CDP connection failed. Use the "Reconnect" button in the side panel after ensuring Chrome is running correctly.

**Verify** your profile loaded correctly:
```bash
curl http://127.0.0.1:8765/api/profile/
```

This should return your profile data as JSON. If you get a 404, check that `data/profile.yaml` exists and is valid YAML.

---

## Phase 6: Test with a Real Internship Application

### Supported ATS Platforms

The extension auto-detects and extracts forms on these platforms (commonly used for internship postings):

| Platform | URL pattern | Commonly used by |
|----------|------------|------------------|
| **Greenhouse** | `boards.greenhouse.io/*` | Tech startups, mid-size companies |
| **Workday** | `*.myworkdayjobs.com/*` | Large enterprises (Google, Amazon, etc.) |
| **Lever** | `jobs.lever.co/*` | Tech companies |
| **iCIMS** | `*.icims.com/*` | Enterprise companies |
| **SmartRecruiters** | `*.smartrecruiters.com/*` | Various |
| **Ashby** | `*.ashbyhq.com/*` | Tech startups |
| **BambooHR** | `*.bamboohr.com/*` | SMBs |
| **Jobvite** | `*.jobvite.com/*` | Various |
| **Taleo** | `*.taleo.net/*` | Enterprise (Oracle) |
| **Breezy** | `*.breezy.hr/*` | SMBs |
| **Recruitee** | `*.recruitee.com/*` | SMBs |

### Step-by-step walkthrough

**1. Find an internship posting on a supported platform**

Search for internships on job boards and look for application pages hosted on one of the platforms above. Greenhouse and Lever are the most common for tech internships. The URL in your browser bar will tell you which platform it is (e.g. `https://boards.greenhouse.io/companyname/jobs/12345`).

**2. Navigate to the application form**

Click "Apply" on the job listing to reach the actual application form page (where you see input fields for name, email, resume upload, etc.).

**3. Open the Ctrl+Apply side panel**

Click the Ctrl+Apply extension icon in your Chrome toolbar. The side panel opens on the right side of the browser. Check the status indicators in the top-right:
- **Backend** dot should be **green** ("Connected")
- **CDP** dot should be **green** ("Connected")

If backend shows red, ensure the server is running. If CDP shows red, click the **"Reconnect"** button.

**4. Click "Analyze Form"**

This triggers the following chain:
1. Content script extracts all visible form fields from the page
2. Fields are sent to the backend via WebSocket
3. Backend sends fields + your profile to Claude for analysis
4. Claude maps each form field to the corresponding value from your `profile.yaml`
5. Results appear in the side panel

You'll see a brief "Extracting form fields..." then "Analyzing..." message.

**5. Review the field mappings**

After analysis completes, the side panel shows each form field with:
- **Label** — the field name from the application form
- **Type badge** — `text`, `email`, `select`, `file`, etc.
- **Required badge** — red tag if the field is mandatory
- **Mapped value** — what Claude thinks should go in this field (editable)
- **Source** — which profile field it came from (e.g. `personal_info.email`)
- **Confidence bar** — color-coded:
  - Green (80-100%): high confidence, likely correct
  - Orange (50-79%): medium confidence, review recommended
  - Red (below 50%): low confidence, likely needs manual correction

**Unmapped fields** are listed separately at the bottom — these are fields Claude couldn't match to your profile.

**6. Edit any values that need correction**

Click on any mapped value field to edit it directly in the side panel. Common things to review:
- Cover letter or "additional information" textareas (may need custom content)
- Dropdown selections (verify the right option was matched)
- Checkboxes (verify true/false)
- Any field with an orange or red confidence bar

**7. Click "Fill Form"**

Once you're satisfied with the mappings, click **"Fill Form"**. Playwright fills each field in the actual browser page with human-like delays (0.2–0.8s between fields). You'll see the form being filled in real-time in the browser.

The side panel shows a results summary:
- "Filled X fields, Y failed"
- Any errors are listed (e.g. a dropdown option couldn't be matched)

**8. Review the filled form manually**

Scroll through the application form in Chrome and verify all fields were filled correctly. Pay special attention to:
- Dropdowns (fuzzy matching may have picked a wrong option)
- File upload (verify your resume was attached)
- Any field that was listed as "failed"
- Fields that were unmapped (you need to fill these manually)

**9. Submit manually**

The tool **never auto-submits**. Review everything, fill any remaining gaps, and click the application's submit button yourself.

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Backend dot is red | Server isn't running | Start the backend with `micromamba run -n ctrl-apply python -m backend.main` |
| CDP dot is red | Chrome not launched with debugging | Close all Chrome, relaunch with `google-chrome --remote-debugging-port=9222 &` |
| "Analyze Form" does nothing | Page isn't on a supported ATS platform | Check the URL matches one of the supported patterns above |
| `playwright_connected: false` in health check | CDP connection failed | Verify `http://localhost:9222/json/version` returns JSON, then click "Reconnect" in side panel |
| Profile 404 from `/api/profile/` | `data/profile.yaml` missing or invalid | Verify the file exists and is valid YAML (check for indentation errors) |
| LLM error in server logs | Claude authentication issue | Ensure `claude` CLI is authenticated: run `claude` in a terminal to verify |
| Extension not detecting the form | Form loaded dynamically after page load | Wait for the page to fully load, then click "Analyze Form" (manual trigger) |
| Dropdown fill failed | Fuzzy match score below threshold (70) | Edit the mapped value in the side panel to exactly match one of the dropdown options, then re-fill |
| File upload failed | `data/resume.pdf` missing | Place your resume at `data/resume.pdf` |

---

## Quick-Reference: Full Startup Sequence

Run these in order each time you want to use the tool:

```bash
# Terminal 1: Launch Chrome with debugging
pkill -f chrome || true
sleep 2
google-chrome --remote-debugging-port=9222 &

# Terminal 2: Start the backend
cd /home/zi/Work/github/Ctrl+Apply
micromamba run -n ctrl-apply python -m backend.main
```

Then in Chrome:
1. Navigate to a job application form (supported ATS platform)
2. Click the Ctrl+Apply extension icon to open the side panel
3. Verify both status dots are green
4. Click "Analyze Form" → review mappings → "Fill Form" → review → submit manually
