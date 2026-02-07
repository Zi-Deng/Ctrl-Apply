"""WebSocket endpoint for Chrome extension communication."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.config import settings
from backend.models.form import ExtractedForm
from backend.services.form_service import form_service
from backend.services.playwright_service import playwright_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Track connected extension clients
_clients: list[WebSocket] = []

# Concurrency primitives for request-response extraction protocol
_active_ws: WebSocket | None = None
_ws_send_lock = asyncio.Lock()
_pending_extractions: dict[str, asyncio.Future] = {}


async def _safe_send(ws: WebSocket, data: dict) -> None:
    """Send JSON to a WebSocket with a lock to prevent interleaved writes."""
    async with _ws_send_lock:
        await ws.send_text(json.dumps(data))


async def broadcast(message: dict) -> None:
    """Send a message to all connected extension clients."""
    for ws in _clients[:]:
        try:
            await _safe_send(ws, message)
        except Exception:
            _clients.remove(ws)


async def request_extraction(timeout: float | None = None) -> dict:
    """Request a fresh DOM extraction from the extension via the active WebSocket.

    This is called from form_service during repeatable section filling.
    It sends a request_extraction message and waits for the corresponding
    extraction_result to arrive on the WS receive loop.
    """
    if not _active_ws:
        raise RuntimeError("No active WebSocket connection to extension")

    timeout = timeout or settings.extraction_timeout
    request_id = uuid.uuid4().hex[:12]
    future: asyncio.Future = asyncio.get_event_loop().create_future()
    _pending_extractions[request_id] = future

    try:
        await _safe_send(
            _active_ws,
            {
                "type": "request_extraction",
                "request_id": request_id,
            },
        )
        result = await asyncio.wait_for(future, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        logger.error("Extraction request %s timed out after %.1fs", request_id, timeout)
        raise RuntimeError(f"Extraction request timed out after {timeout}s")
    finally:
        _pending_extractions.pop(request_id, None)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    global _active_ws

    await websocket.accept()
    _clients.append(websocket)
    _active_ws = websocket
    logger.info("Extension connected (total: %d)", len(_clients))

    # Inject the extraction function into form_service so it can request
    # re-extractions during fill_with_sections without circular imports.
    form_service.set_extraction_fn(request_extraction)

    try:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            msg_type = message.get("type", "")

            if msg_type == "ping":
                await _safe_send(websocket, {"type": "pong"})

            elif msg_type == "form_extracted":
                # Content script sent extracted form fields
                await _handle_form_extracted(websocket, message)

            elif msg_type == "fill_form":
                # User clicked "Fill Form" in side panel
                # Run as a task so the WS loop can keep receiving messages
                # (needed for extraction_result during section filling)
                asyncio.create_task(_handle_fill_form(websocket, message))

            elif msg_type == "extraction_result":
                # Response to a request_extraction we sent during section filling
                req_id = message.get("request_id", "")
                future = _pending_extractions.get(req_id)
                if future and not future.done():
                    future.set_result(message.get("data") or {})

            elif msg_type == "update_field":
                # User edited a field mapping in side panel
                await _handle_update_field(websocket, message)

            elif msg_type == "connect_cdp":
                # Request to connect/reconnect Playwright
                await _handle_connect_cdp(websocket)

            elif msg_type == "status":
                # Status check
                await _safe_send(
                    websocket,
                    {
                        "type": "status",
                        "playwright_connected": playwright_service.is_connected,
                    },
                )

            else:
                logger.warning("Unknown message type: %s", msg_type)
                await _safe_send(
                    websocket,
                    {
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}",
                    },
                )

    except WebSocketDisconnect:
        logger.info("Extension disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        if websocket in _clients:
            _clients.remove(websocket)
        if _active_ws is websocket:
            _active_ws = None


async def _handle_form_extracted(ws: WebSocket, message: dict) -> None:
    """Handle form extraction from content script -> send to LLM for analysis."""
    try:
        extracted = ExtractedForm.model_validate(message.get("data", {}))
        await _safe_send(
            ws,
            {
                "type": "analyzing",
                "message": f"Analyzing {len(extracted.fields)} fields...",
            },
        )

        analysis = await form_service.analyze(extracted)
        await _safe_send(
            ws,
            {
                "type": "form_analysis",
                "data": analysis.model_dump(),
            },
        )
    except Exception as e:
        logger.error("Form analysis failed: %s", e)
        await _safe_send(
            ws,
            {
                "type": "error",
                "message": f"Form analysis failed: {e}",
            },
        )


async def _handle_fill_form(ws: WebSocket, message: dict) -> None:
    """Handle fill request: use Playwright to fill fields."""
    try:
        from backend.models.form import FormAnalysis

        analysis = FormAnalysis.model_validate(message.get("data", {}))

        await _safe_send(
            ws,
            {
                "type": "filling",
                "message": "Filling form fields...",
            },
        )

        # Define a progress callback for section filling
        async def progress_cb(msg: str) -> None:
            await _safe_send(ws, {"type": "fill_progress", "message": msg})

        # Use section-aware fill if repeatable sections are present
        if analysis.repeatable_sections:
            result = await form_service.fill_with_sections(analysis, progress_cb)
        else:
            result = await form_service.fill(analysis)

        await _safe_send(
            ws,
            {
                "type": "fill_result",
                "data": result,
            },
        )
    except Exception as e:
        logger.error("Form fill failed: %s", e)
        await _safe_send(
            ws,
            {
                "type": "error",
                "message": f"Form fill failed: {e}",
            },
        )


async def _handle_update_field(ws: WebSocket, message: dict) -> None:
    """Handle user editing a single field mapping."""
    # This is purely client-side state management; the extension updates its
    # local FormAnalysis. We just acknowledge.
    await _safe_send(ws, {"type": "field_updated", "ok": True})


async def _handle_connect_cdp(ws: WebSocket) -> None:
    """Connect or reconnect Playwright to Chrome via CDP."""
    try:
        if playwright_service.is_connected:
            await playwright_service.disconnect()
        await playwright_service.connect()
        await _safe_send(
            ws,
            {
                "type": "cdp_connected",
                "message": "Connected to Chrome via CDP",
            },
        )
    except Exception as e:
        await _safe_send(
            ws,
            {
                "type": "error",
                "message": f"CDP connection failed: {e}",
            },
        )
