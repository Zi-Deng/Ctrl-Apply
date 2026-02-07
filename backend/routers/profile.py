"""Profile REST endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.models.profile import UserProfile
from backend.services.profile_service import profile_service

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("/", response_model=UserProfile)
async def get_profile() -> UserProfile:
    try:
        return profile_service.profile
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/reload", response_model=UserProfile)
async def reload_profile() -> UserProfile:
    try:
        return profile_service.reload()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
