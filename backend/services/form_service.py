"""Form analysis orchestration: receives extracted DOM, sends to LLM, returns mappings."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

from backend.config import settings
from backend.models.form import (
    ExtractedField,
    ExtractedForm,
    FormAnalysis,
    RepeatableSection,
)
from backend.services.llm_service import llm_service
from backend.services.playwright_service import playwright_service
from backend.services.profile_service import profile_service

logger = logging.getLogger(__name__)

# Maps section heading substrings to profile attribute names
SECTION_PROFILE_MAP = {
    "work experience": "experience",
    "education": "education",
    "certifications": "certifications",
    "languages": "languages",
}

# Patterns in CSS selectors that indicate a field belongs to a repeatable section.
# Workday uses IDs like "education-4--school", "workExperience-1--jobTitle", etc.
_SECTION_SELECTOR_PATTERNS = [
    re.compile(r"education-?\d", re.IGNORECASE),
    re.compile(r"workExperience-?\d", re.IGNORECASE),
    re.compile(r"work-experience-?\d", re.IGNORECASE),
    re.compile(r"certification-?\d", re.IGNORECASE),
    re.compile(r"language-?\d", re.IGNORECASE),
]


def _resolve_profile_section(section_name: str) -> str:
    """Match a section heading to a profile attribute key."""
    name_lower = section_name.lower()
    for keyword, profile_key in SECTION_PROFILE_MAP.items():
        if keyword in name_lower:
            return profile_key
    return ""


def _is_section_field(selector: str) -> bool:
    """Check if a CSS selector belongs to a repeatable section entry."""
    for pattern in _SECTION_SELECTOR_PATTERNS:
        if pattern.search(selector):
            return True
    return False


def _build_entry_context(profile_section: str, entry: object, entry_idx: int) -> str:
    """Build a focused LLM prompt context for a single profile entry."""
    p = profile_service.profile
    lines = [
        "=== USER PROFILE (focused on a single entry) ===",
        f"Name: {p.personal_info.first_name} {p.personal_info.last_name}",
        f"\nFill the new fields with ONLY this specific entry (entry #{entry_idx + 1}):",
    ]

    if profile_section == "experience":
        exp = entry
        lines.append(f"Job Title: {exp.title}")
        lines.append(f"Company: {exp.company}")
        if exp.location:
            lines.append(f"Location: {exp.location}")
        if exp.start_date:
            lines.append(f"Start Date: {exp.start_date}")
        if exp.end_date:
            lines.append(f"End Date: {exp.end_date}")
        if exp.description:
            lines.append(f"Description: {exp.description}")

    elif profile_section == "education":
        edu = entry
        lines.append(f"Degree: {edu.degree}")
        lines.append(f"Field of Study: {edu.field}")
        lines.append(f"Institution: {edu.institution}")
        if edu.gpa:
            lines.append(f"GPA: {edu.gpa}")
        if edu.start_date:
            lines.append(f"Start Date: {edu.start_date}")
        if edu.end_date:
            lines.append(f"End Date: {edu.end_date}")
        if edu.description:
            lines.append(f"Description: {edu.description}")

    elif profile_section == "certifications":
        lines.append(f"Certification: {entry}")

    elif profile_section == "languages":
        lang = entry
        lines.append(f"Language: {lang.language}")
        if lang.proficiency:
            lines.append(f"Proficiency: {lang.proficiency}")

    else:
        lines.append(f"Value: {entry}")

    return "\n".join(lines)


class FormService:
    def __init__(self) -> None:
        self._extraction_fn: Callable[..., Awaitable[dict]] | None = None

    def set_extraction_fn(self, fn: Callable[..., Awaitable[dict]]) -> None:
        """Inject the extraction request function from ws.py to avoid circular imports."""
        self._extraction_fn = fn

    async def analyze(self, extracted: ExtractedForm) -> FormAnalysis:
        """Analyze extracted form fields and map them to profile values."""
        profile_context = profile_service.to_prompt_context()
        analysis = await llm_service.analyze_form(extracted, profile_context)

        # Carry through repeatable sections and resolve profile mappings
        if extracted.repeatable_sections:
            resolved = []
            for section in extracted.repeatable_sections:
                profile_key = _resolve_profile_section(section.section_name)
                resolved.append(
                    RepeatableSection(
                        section_name=section.section_name,
                        add_button_index=section.add_button_index,
                        add_button_selector=section.add_button_selector,
                        add_button_text=section.add_button_text,
                        existing_entries=section.existing_entries,
                        profile_section=profile_key,
                    )
                )
            analysis.repeatable_sections = resolved

        logger.info(
            "Form analysis: %d fields mapped, %d unmapped, %d sections, url=%s",
            len(analysis.fields),
            len(analysis.unmapped_fields),
            len(analysis.repeatable_sections),
            analysis.page_url,
        )
        return analysis

    async def fill(self, analysis: FormAnalysis) -> dict:
        """Fill the analyzed form using Playwright."""
        if not playwright_service.is_connected:
            return {"filled": 0, "failed": 0, "errors": ["Playwright not connected to Chrome"]}

        # Only fill fields that have a mapped value
        fields_to_fill = [f for f in analysis.fields if f.mapped_value]
        result = await playwright_service.fill_form(fields_to_fill, target_url=analysis.page_url)
        return result

    async def fill_with_sections(
        self,
        analysis: FormAnalysis,
        progress_cb: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict:
        """Fill form fields including repeatable sections.

        Algorithm:
        1. Fill flat (non-section) fields only — skip any field whose selector
           indicates it belongs to a repeatable section entry.
        2. For each repeatable section:
           a. Fill existing entry fields with per-entry profile context
           b. Click "Add" for each new entry, re-extract, diff, analyze, fill
        """
        if not playwright_service.is_connected:
            return {
                "filled": 0,
                "failed": 0,
                "errors": ["Playwright not connected to Chrome"],
            }

        total_filled = 0
        total_failed = 0
        all_errors: list[str] = []

        has_mapped_sections = any(s.profile_section for s in analysis.repeatable_sections)

        # Step 1: Fill flat fields (excluding fields inside repeatable sections).
        # Workday section fields (comboboxes like School, Degree) can trigger
        # page navigation if filled out of context, so we handle them per-entry.
        if has_mapped_sections:
            flat_fields = [
                f for f in analysis.fields if f.mapped_value and not _is_section_field(f.selector)
            ]
            if flat_fields:
                if progress_cb:
                    await progress_cb(f"Filling {len(flat_fields)} standard fields...")
                flat_result = await playwright_service.fill_form(
                    flat_fields, target_url=analysis.page_url
                )
            else:
                if progress_cb:
                    await progress_cb("No flat fields to fill, processing sections...")
                flat_result = {"filled": 0, "failed": 0, "errors": []}
        else:
            if progress_cb:
                await progress_cb("Filling standard fields...")
            flat_result = await self.fill(analysis)
        total_filled += flat_result["filled"]
        total_failed += flat_result["failed"]
        all_errors.extend(flat_result["errors"])

        # Step 2: Process repeatable sections
        for section in analysis.repeatable_sections:
            if not section.profile_section:
                logger.info(
                    "Skipping section '%s' — no profile mapping",
                    section.section_name,
                )
                continue

            profile = profile_service.profile
            entries = getattr(profile, section.profile_section, [])
            if not entries:
                logger.info(
                    "Skipping section '%s' — no entries in profile.%s",
                    section.section_name,
                    section.profile_section,
                )
                continue

            page = await playwright_service.get_active_page(analysis.page_url)
            if not page:
                all_errors.append(f"No active page for section '{section.section_name}'")
                continue

            total_entries = min(len(entries), settings.max_section_entries)
            entries_to_add = max(0, total_entries - section.existing_entries)

            if progress_cb:
                msg = f"Processing {section.section_name}: "
                if section.existing_entries > 0:
                    msg += f"{section.existing_entries} existing"
                if entries_to_add > 0:
                    if section.existing_entries > 0:
                        msg += f" + {entries_to_add} to add"
                    else:
                        msg += f"{entries_to_add} to add"
                await progress_cb(msg)

            # Step 2a: Fill EXISTING section entry fields with per-entry context.
            # These were skipped during flat fill above.
            if section.existing_entries > 0:
                section_fields = [f for f in analysis.fields if _is_section_field(f.selector)]
                if section_fields:
                    for entry_idx in range(min(section.existing_entries, len(entries))):
                        entry = entries[entry_idx]
                        entry_num = entry_idx + 1

                        existing_extracted = ExtractedForm(
                            url=analysis.page_url,
                            ats_platform=analysis.ats_platform,
                            fields=[
                                ExtractedField(
                                    selector=f.selector,
                                    field_type=f.field_type,
                                    label=f.label,
                                    required=f.required,
                                    options=f.options,
                                    listbox_selector=f.listbox_selector,
                                    options_deferred=f.options_deferred,
                                )
                                for f in section_fields
                            ],
                        )
                        entry_context = _build_entry_context(
                            section.profile_section, entry, entry_idx
                        )

                        if progress_cb:
                            await progress_cb(
                                f"{section.section_name} entry {entry_num}: "
                                f"filling existing fields..."
                            )

                        try:
                            entry_analysis = await llm_service.analyze_form(
                                existing_extracted, entry_context
                            )
                            to_fill = [f for f in entry_analysis.fields if f.mapped_value]
                            if to_fill:
                                fill_result = await playwright_service.fill_form(
                                    to_fill, target_url=analysis.page_url
                                )
                                total_filled += fill_result["filled"]
                                total_failed += fill_result["failed"]
                                all_errors.extend(fill_result["errors"])
                        except Exception as e:
                            msg = (
                                f"Failed to fill existing "
                                f"{section.section_name} entry {entry_num}: {e}"
                            )
                            logger.warning(msg)
                            all_errors.append(msg)
                            total_failed += 1

            # Step 2b: Add NEW entries
            if entries_to_add <= 0:
                logger.info(
                    "Section '%s': no new entries to add (have %d, profile has %d)",
                    section.section_name,
                    section.existing_entries,
                    len(entries),
                )
                continue

            baseline_selectors = {f.selector for f in analysis.fields}

            for entry_idx in range(section.existing_entries, total_entries):
                entry = entries[entry_idx]
                entry_num = entry_idx + 1

                if progress_cb:
                    await progress_cb(
                        f"{section.section_name}: adding entry {entry_num}/{total_entries}..."
                    )

                # Click the "Add" button
                try:
                    add_buttons = await page.query_selector_all('[data-automation-id="add-button"]')
                    if section.add_button_index < len(add_buttons):
                        await add_buttons[section.add_button_index].click()
                    else:
                        await page.click(section.add_button_selector)
                except Exception as e:
                    msg = f"Failed to click Add for '{section.section_name}' entry {entry_num}: {e}"
                    logger.warning(msg)
                    all_errors.append(msg)
                    total_failed += 1
                    continue

                # Wait for new fields to render
                await asyncio.sleep(settings.add_button_wait)

                # Re-extract from content script
                if not self._extraction_fn:
                    all_errors.append("No extraction function available for re-extraction")
                    break

                try:
                    raw_extraction = await self._extraction_fn()
                except Exception as e:
                    msg = (
                        f"Re-extraction failed for '{section.section_name}' entry {entry_num}: {e}"
                    )
                    logger.warning(msg)
                    all_errors.append(msg)
                    total_failed += 1
                    continue

                if not raw_extraction or not raw_extraction.get("fields"):
                    msg = f"Empty re-extraction for '{section.section_name}' entry {entry_num}"
                    logger.warning(msg)
                    all_errors.append(msg)
                    total_failed += 1
                    continue

                # Diff: find new fields not in baseline
                new_fields = [
                    fd
                    for fd in raw_extraction["fields"]
                    if fd.get("selector") not in baseline_selectors
                ]

                if not new_fields:
                    msg = (
                        f"No new fields detected after clicking Add "
                        f"for '{section.section_name}' entry {entry_num}"
                    )
                    logger.warning(msg)
                    all_errors.append(msg)
                    continue

                logger.info(
                    "Section '%s' entry %d: %d new fields detected",
                    section.section_name,
                    entry_num,
                    len(new_fields),
                )

                new_extracted = ExtractedForm(
                    url=analysis.page_url,
                    ats_platform=analysis.ats_platform,
                    fields=[ExtractedField.model_validate(f) for f in new_fields],
                    page_title=raw_extraction.get("page_title", ""),
                )
                entry_context = _build_entry_context(section.profile_section, entry, entry_idx)

                try:
                    entry_analysis = await llm_service.analyze_form(new_extracted, entry_context)
                except Exception as e:
                    msg = f"LLM analysis failed for '{section.section_name}' entry {entry_num}: {e}"
                    logger.warning(msg)
                    all_errors.append(msg)
                    total_failed += 1
                    continue

                new_to_fill = [f for f in entry_analysis.fields if f.mapped_value]
                if new_to_fill:
                    if progress_cb:
                        await progress_cb(
                            f"{section.section_name} entry {entry_num}: "
                            f"filling {len(new_to_fill)} fields..."
                        )
                    fill_result = await playwright_service.fill_form(
                        new_to_fill, target_url=analysis.page_url
                    )
                    total_filled += fill_result["filled"]
                    total_failed += fill_result["failed"]
                    all_errors.extend(fill_result["errors"])

                # Update baseline for next iteration
                for fd in raw_extraction["fields"]:
                    baseline_selectors.add(fd.get("selector", ""))

        result = {
            "filled": total_filled,
            "failed": total_failed,
            "errors": all_errors,
        }
        logger.info(
            "Section-aware fill complete: %d filled, %d failed",
            total_filled,
            total_failed,
        )
        return result


form_service = FormService()
