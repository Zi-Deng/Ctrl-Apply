from __future__ import annotations

from pydantic import BaseModel, Field


class SelectOption(BaseModel):
    value: str
    text: str


class FormField(BaseModel):
    selector: str = Field(description="CSS selector or Playwright locator string")
    field_type: str = Field(
        description="text | email | tel | select | combobox | checkbox | radio | file | textarea"
    )
    label: str = Field(description="Human-readable label text")
    required: bool = False
    options: list[SelectOption] = Field(
        default_factory=list, description="Available options for select/radio/combobox fields"
    )
    mapped_value: str = Field("", description="Value from profile to fill")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Mapping confidence 0-1")
    source_field: str = Field("", description="Profile field path, e.g. 'personal_info.email'")
    listbox_selector: str = Field(
        "", description="CSS selector for associated ARIA listbox (combobox fields)"
    )
    options_deferred: bool = Field(
        False, description="True when combobox options are only available after opening"
    )


class RepeatableSection(BaseModel):
    """A repeatable section with an 'Add' button (e.g. Work Experience, Education)."""

    section_name: str
    add_button_index: int
    add_button_selector: str
    add_button_text: str = "Add"
    existing_entries: int = 0
    profile_section: str = Field(
        "", description="Resolved profile key: 'experience', 'education', etc."
    )


class FormAnalysis(BaseModel):
    page_url: str
    ats_platform: str = "generic"
    fields: list[FormField] = []
    has_file_upload: bool = False
    has_cover_letter: bool = False
    unmapped_fields: list[str] = Field(
        default_factory=list, description="Labels of fields that couldn't be mapped"
    )
    repeatable_sections: list[RepeatableSection] = Field(
        default_factory=list,
        description="Detected repeatable sections with Add buttons",
    )


class ExtractedField(BaseModel):
    """Raw field data extracted from the DOM by the content script."""

    selector: str
    field_type: str
    label: str
    name: str = ""
    id: str = ""
    required: bool = False
    placeholder: str = ""
    options: list[SelectOption] = []
    current_value: str = ""
    listbox_selector: str = ""
    options_deferred: bool = False


class ExtractedForm(BaseModel):
    """Raw form data sent from the content script."""

    url: str
    ats_platform: str = "generic"
    fields: list[ExtractedField] = []
    page_title: str = ""
    repeatable_sections: list[RepeatableSection] = []
