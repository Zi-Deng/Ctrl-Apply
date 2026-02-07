"""LLM service wrapping claude-agent-sdk.

Routes to Claude cloud (Max subscription) or local Ollama based on config.
Uses the `query()` async iterator API from claude-agent-sdk.
"""

from __future__ import annotations

import json
import logging
import os
import re

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from backend.config import settings
from backend.models.form import ExtractedForm, FormAnalysis, FormField, SelectOption

logger = logging.getLogger(__name__)

FORM_ANALYSIS_SYSTEM = """\
You are a job application form analyzer. Given a user's profile and extracted \
form fields from a job application page, map each form field to the correct \
profile value.

Return ONLY valid JSON matching this schema — no markdown, no explanation:
{
  "fields": [
    {
      "selector": "<CSS selector from input>",
      "field_type": "<field type from input>",
      "label": "<label from input>",
      "required": <bool>,
      "options": [{"value": "...", "text": "..."}],
      "mapped_value": "<value to fill from profile>",
      "confidence": <0.0-1.0>,
      "source_field": "<dotted profile path, e.g. personal_info.email>",
      "listbox_selector": "<CSS selector from input, for combobox fields>",
      "options_deferred": <bool from input>
    }
  ],
  "has_file_upload": <bool>,
  "has_cover_letter": <bool>,
  "unmapped_fields": ["<labels of fields you couldn't map>"]
}

Rules:
- For each field, find the best matching value from the user profile.
- Set confidence to 1.0 for exact matches (e.g. "Email" -> personal_info.email).
- Set confidence to 0.8-0.9 for strong semantic matches.
- Set confidence to 0.5-0.7 for uncertain matches — the user will review these.
- Set confidence to 0.0 and mapped_value to "" for fields you cannot map.
- For select/radio fields, pick the option that best matches the profile value.
- For combobox fields (custom ARIA dropdowns), treat them like select fields and \
pick the best matching option. If the options list is empty (options_deferred is \
true), set mapped_value to the plain text value from the profile that should be \
selected — the system will fuzzy-match it when the dropdown opens.
- For file upload fields, set mapped_value to "resume" and source_field to "resume".
- If a textarea mentions "cover letter", set has_cover_letter to true.
- Preserve the original selector, field_type, label, required, options, \
listbox_selector, and options_deferred from input.
"""


def _configure_env() -> None:
    """Set environment variables for cloud vs local mode."""
    if settings.llm_mode == "local":
        os.environ["ANTHROPIC_BASE_URL"] = settings.local_ollama_url
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "ollama"
        os.environ["ANTHROPIC_API_KEY"] = ""
        logger.info(
            "LLM mode: local (Ollama at %s, model: %s)",
            settings.local_ollama_url,
            settings.local_model,
        )
    else:
        # Cloud mode: uses Claude Max subscription via claude CLI auth
        for var in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
            os.environ.pop(var, None)
        logger.info("LLM mode: cloud (Claude Max subscription)")


def _build_options(system: str) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions with the right system prompt and no tools."""
    opts = ClaudeAgentOptions(
        system_prompt=system,
        allowed_tools=[],  # no tools needed — pure text completion
        max_turns=1,
    )
    if settings.llm_mode == "local":
        opts.model = settings.local_model
    return opts


async def _query_llm(system: str, prompt: str) -> str:
    """Send a prompt to the LLM via claude-agent-sdk and collect the text response."""
    options = _build_options(system)
    text_parts: list[str] = []

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
        elif isinstance(message, ResultMessage):
            if message.is_error:
                logger.error("LLM query returned error: %s", message.result)
                raise RuntimeError(f"LLM error: {message.result}")

    return "".join(text_parts)


class LLMService:
    """Wraps claude-agent-sdk for form analysis and other LLM tasks."""

    _initialized: bool = False

    async def initialize(self) -> None:
        _configure_env()
        self._initialized = True
        logger.info("LLM service initialized (mode: %s)", settings.llm_mode)

    async def analyze_form(self, extracted: ExtractedForm, profile_context: str) -> FormAnalysis:
        """Send extracted form + profile to Claude for field mapping."""
        if not self._initialized:
            await self.initialize()

        fields_json = json.dumps([f.model_dump() for f in extracted.fields], indent=2)
        prompt = (
            f"ATS Platform: {extracted.ats_platform}\n"
            f"Page URL: {extracted.url}\n"
            f"Page Title: {extracted.page_title}\n\n"
            f"=== EXTRACTED FORM FIELDS ===\n{fields_json}\n\n"
            f"{profile_context}\n\n"
            "Analyze the form fields above and map them to profile values. "
            "Return the JSON response."
        )

        response_text = await _query_llm(FORM_ANALYSIS_SYSTEM, prompt)

        # Parse the JSON response
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
            else:
                logger.error("Failed to parse LLM response as JSON: %s", response_text[:500])
                return FormAnalysis(
                    page_url=extracted.url,
                    ats_platform=extracted.ats_platform,
                    unmapped_fields=[f.label for f in extracted.fields],
                )

        # Build FormAnalysis from response
        fields = []
        for fd in data.get("fields", []):
            fields.append(
                FormField(
                    selector=fd.get("selector", ""),
                    field_type=fd.get("field_type", "text"),
                    label=fd.get("label", ""),
                    required=fd.get("required", False),
                    options=[SelectOption(**o) for o in fd.get("options", [])],
                    mapped_value=fd.get("mapped_value", ""),
                    confidence=fd.get("confidence", 0.0),
                    source_field=fd.get("source_field", ""),
                    listbox_selector=fd.get("listbox_selector", ""),
                    options_deferred=fd.get("options_deferred", False),
                )
            )

        return FormAnalysis(
            page_url=extracted.url,
            ats_platform=extracted.ats_platform,
            fields=fields,
            has_file_upload=data.get("has_file_upload", False),
            has_cover_letter=data.get("has_cover_letter", False),
            unmapped_fields=data.get("unmapped_fields", []),
        )

    async def generate_text(self, system: str, prompt: str) -> str:
        """General-purpose text generation."""
        if not self._initialized:
            await self.initialize()
        return await _query_llm(system, prompt)


llm_service = LLMService()
