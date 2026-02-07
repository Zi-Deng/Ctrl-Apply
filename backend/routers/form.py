"""Form analysis and filling REST endpoints (alternative to WebSocket flow)."""
from __future__ import annotations

from fastapi import APIRouter

from backend.models.form import ExtractedForm, FormAnalysis
from backend.services.form_service import form_service

router = APIRouter(prefix="/api/form", tags=["form"])


@router.post("/analyze", response_model=FormAnalysis)
async def analyze_form(extracted: ExtractedForm) -> FormAnalysis:
    """Analyze extracted form and return field mappings."""
    return await form_service.analyze(extracted)


@router.post("/fill")
async def fill_form(analysis: FormAnalysis) -> dict:
    """Fill form fields using Playwright."""
    return await form_service.fill(analysis)
