"""Playwright service: connects to Chrome via CDP and fills forms."""

from __future__ import annotations

import asyncio
import logging
import random

from playwright.async_api import Browser, Page, Playwright, async_playwright
from rapidfuzz import fuzz, process

from backend.config import settings
from backend.models.form import FormField

logger = logging.getLogger(__name__)


def match_dropdown(value: str, options: list[dict]) -> str | None:
    """Find the best matching dropdown option for a profile value.

    Returns the option *value* attribute (what gets submitted), or None.
    """
    if not options:
        return None

    # Build lookup: text -> value
    text_to_value = {}
    for opt in options:
        text_to_value[opt["text"].strip()] = opt["value"]
        # Also index by value itself for exact-match cases
        text_to_value[opt["value"].strip()] = opt["value"]

    candidates = list(text_to_value.keys())
    value_lower = value.strip().lower()

    # 1. Exact case-insensitive match
    for candidate in candidates:
        if candidate.strip().lower() == value_lower:
            return text_to_value[candidate]

    # 2. Fuzzy match with rapidfuzz
    result = process.extractOne(
        value,
        candidates,
        scorer=fuzz.WRatio,
        score_cutoff=settings.dropdown_match_threshold,
    )
    if result:
        matched_text, score, _ = result
        logger.info("Fuzzy matched '%s' -> '%s' (score: %d)", value, matched_text, score)
        return text_to_value[matched_text]

    logger.warning("No dropdown match for '%s' among %d options", value, len(options))
    return None


class PlaywrightService:
    """Manages CDP connection to user's Chrome and performs form filling."""

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None

    async def connect(self, cdp_url: str | None = None) -> None:
        """Connect to user's running Chrome via CDP."""
        cdp_url = cdp_url or settings.cdp_url
        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.connect_over_cdp(cdp_url)
            logger.info("Connected to Chrome via CDP at %s", cdp_url)
        except Exception as e:
            logger.error("Failed to connect to Chrome CDP at %s: %s", cdp_url, e)
            raise

    async def disconnect(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None
        logger.info("Disconnected from Chrome")

    @property
    def is_connected(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def get_active_page(self, target_url: str | None = None) -> Page | None:
        """Find the page matching target_url, or the first visible page."""
        if not self._browser:
            return None

        for context in self._browser.contexts:
            for page in context.pages:
                if target_url and target_url in page.url:
                    return page
        # Fallback: return the last page (most recently opened)
        for context in self._browser.contexts:
            if context.pages:
                return context.pages[-1]
        return None

    async def fill_form(self, fields: list[FormField], target_url: str | None = None) -> dict:
        """Fill form fields using native Playwright methods.

        Returns a summary: {filled: int, failed: int, errors: [...]}
        """
        page = await self.get_active_page(target_url)
        if not page:
            return {"filled": 0, "failed": 0, "errors": ["No active page found"]}

        filled = 0
        failed = 0
        errors = []

        for field in fields:
            if not field.mapped_value:
                continue

            # Human-like delay between actions
            delay = random.uniform(settings.fill_delay_min, settings.fill_delay_max)
            await asyncio.sleep(delay)

            try:
                await self._fill_field(page, field)
                filled += 1
                logger.debug(
                    "Filled %s (%s) = %s", field.label, field.selector, field.mapped_value[:50]
                )
            except Exception as e:
                failed += 1
                msg = f"Failed to fill '{field.label}': {e}"
                errors.append(msg)
                logger.warning(msg)

        result = {"filled": filled, "failed": failed, "errors": errors}
        logger.info("Form fill complete: %d filled, %d failed", filled, failed)
        return result

    async def _fill_field(self, page: Page, field: FormField) -> None:
        """Fill a single field using the appropriate Playwright method."""
        selector = field.selector

        if field.field_type in ("text", "email", "tel"):
            await page.fill(selector, field.mapped_value)

        elif field.field_type == "textarea":
            await page.fill(selector, field.mapped_value)

        elif field.field_type == "select":
            # Try to match dropdown option
            options_dicts = [o.model_dump() for o in field.options]
            matched_value = match_dropdown(field.mapped_value, options_dicts)
            if matched_value:
                await page.select_option(selector, matched_value)
            else:
                raise ValueError(f"No matching option for '{field.mapped_value}' in {field.label}")

        elif field.field_type == "combobox":
            await self._fill_combobox(page, field)

        elif field.field_type == "radio":
            # For radio, the mapped_value should be the value to select
            await page.check(f"{selector}[value='{field.mapped_value}']")

        elif field.field_type == "checkbox":
            if field.mapped_value.lower() in ("true", "yes", "1", "checked"):
                await page.check(selector)
            else:
                await page.uncheck(selector)

        elif field.field_type == "file":
            file_path = str(settings.resume_path)
            await page.set_input_files(selector, file_path)

        else:
            # Fallback: try fill
            await page.fill(selector, field.mapped_value)

    async def _fill_combobox(self, page: Page, field: FormField) -> None:
        """Fill a custom ARIA combobox dropdown via click interaction."""
        selector = field.selector
        timeout = settings.combobox_open_timeout

        # Step 1: Click the trigger to open the dropdown
        await page.click(selector)

        # Step 2: Wait for the listbox to appear
        listbox_sel = field.listbox_selector or '[role="listbox"]'
        try:
            await page.wait_for_selector(listbox_sel, state="visible", timeout=timeout)
        except Exception:
            # Some comboboxes need typing to trigger the options list
            try:
                await page.fill(selector, field.mapped_value[:1])
                await page.wait_for_selector(listbox_sel, state="visible", timeout=timeout)
            except Exception:
                raise ValueError(f"Combobox listbox did not appear for '{field.label}'")

        # Step 3: Read live options if they were deferred or empty at extraction
        if field.options_deferred or not field.options:
            option_els = await page.query_selector_all(f'{listbox_sel} [role="option"]')
            live_options = []
            for opt_el in option_els:
                text = (await opt_el.text_content() or "").strip()
                value = (
                    await opt_el.get_attribute("data-value")
                    or await opt_el.get_attribute("value")
                    or await opt_el.get_attribute("id")
                    or text
                )
                if text:
                    live_options.append({"value": value, "text": text})
            options_to_match = live_options
        else:
            options_to_match = [o.model_dump() for o in field.options]

        # Step 4: Fuzzy match the desired value against available options
        matched_value = match_dropdown(field.mapped_value, options_to_match)
        if not matched_value:
            await page.keyboard.press("Escape")
            raise ValueError(
                f"No matching combobox option for '{field.mapped_value}' in {field.label}"
            )

        # Step 5: Find the matched option text for clicking
        matched_text = None
        for opt in options_to_match:
            if opt["value"] == matched_value:
                matched_text = opt["text"]
                break

        # Step 6: Click the matching option element
        option_clicked = False
        option_els = await page.query_selector_all(f'{listbox_sel} [role="option"]')
        for opt_el in option_els:
            el_text = (await opt_el.text_content() or "").strip()
            el_value = (
                await opt_el.get_attribute("data-value")
                or await opt_el.get_attribute("value")
                or ""
            )
            if el_value == matched_value or el_text == matched_text:
                await opt_el.click()
                option_clicked = True
                break

        if not option_clicked:
            # Fallback: use Playwright text selector
            try:
                await page.click(f'{listbox_sel} [role="option"]:has-text("{matched_text}")')
            except Exception:
                await page.keyboard.press("Escape")
                raise ValueError(f"Could not click option '{matched_text}' for {field.label}")

        # Brief wait for the selection to register
        await asyncio.sleep(0.2)
        logger.info(
            "Combobox filled '%s' -> '%s' (matched: '%s')",
            field.label,
            field.mapped_value,
            matched_text,
        )

    async def upload_file(
        self, selector: str, file_path: str, target_url: str | None = None
    ) -> bool:
        """Upload a file to a specific input."""
        page = await self.get_active_page(target_url)
        if not page:
            return False
        try:
            await page.set_input_files(selector, file_path)
            return True
        except Exception as e:
            logger.error("File upload failed: %s", e)
            return False


playwright_service = PlaywrightService()
