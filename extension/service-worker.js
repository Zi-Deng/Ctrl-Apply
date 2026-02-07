/**
 * Ctrl+Apply service worker.
 * Maintains WebSocket connection to the Python backend and relays messages
 * between the content scripts / side panel and the backend.
 */

const BACKEND_WS_URL = "ws://127.0.0.1:8765/ws";
const RECONNECT_INTERVAL_MS = 3000;

let ws = null;
let wsReady = false;
let reconnectTimer = null;

// --- WebSocket management ---

function connectWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  ws = new WebSocket(BACKEND_WS_URL);

  ws.onopen = () => {
    console.log("[Ctrl+Apply] WebSocket connected to backend");
    wsReady = true;
    clearTimeout(reconnectTimer);
    // Notify side panel
    broadcastToExtension({ type: "backend_connected" });
  };

  ws.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      console.log("[Ctrl+Apply] Backend ->", message.type);

      if (message.type === "request_extraction") {
        // Backend is requesting a fresh DOM extraction (during fill_with_sections)
        handleBackendExtractionRequest(message);
      } else {
        // Forward to side panel
        broadcastToExtension(message);
      }
    } catch (e) {
      console.error("[Ctrl+Apply] Failed to parse backend message:", e);
    }
  };

  ws.onclose = () => {
    console.log("[Ctrl+Apply] WebSocket disconnected");
    wsReady = false;
    broadcastToExtension({ type: "backend_disconnected" });
    scheduleReconnect();
  };

  ws.onerror = (err) => {
    console.error("[Ctrl+Apply] WebSocket error:", err);
    ws.close();
  };
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    console.log("[Ctrl+Apply] Attempting reconnect...");
    connectWebSocket();
  }, RECONNECT_INTERVAL_MS);
}

function sendToBackend(message) {
  if (ws && wsReady) {
    ws.send(JSON.stringify(message));
    return true;
  }
  console.warn("[Ctrl+Apply] WebSocket not ready, message dropped:", message.type);
  return false;
}

// --- Message relay ---

/**
 * Broadcast a message to the side panel and any listening content scripts.
 */
function broadcastToExtension(message) {
  chrome.runtime.sendMessage(message).catch(() => {
    // Side panel might not be open — that's fine
  });
}

/**
 * Handle extraction requests from the backend (during repeatable section filling).
 * Sends extract_section to the content script and returns the result to the backend.
 */
function handleBackendExtractionRequest(message) {
  const requestId = message.request_id || "";
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs[0]?.id) {
      sendToBackend({
        type: "extraction_result",
        request_id: requestId,
        data: null,
        error: "No active tab",
      });
      return;
    }
    chrome.tabs.sendMessage(tabs[0].id, { type: "extract_section" }, (response) => {
      if (chrome.runtime.lastError) {
        sendToBackend({
          type: "extraction_result",
          request_id: requestId,
          data: null,
          error: chrome.runtime.lastError.message,
        });
      } else {
        sendToBackend({
          type: "extraction_result",
          request_id: requestId,
          data: response || null,
        });
      }
    });
  });
}

/**
 * Listen for messages from content scripts and side panel.
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const { type } = message;

  if (type === "form_extracted") {
    // Content script extracted form fields -> forward to backend
    sendToBackend(message);
    sendResponse({ ok: true });
  } else if (type === "fill_form" || type === "update_field" || type === "connect_cdp") {
    // Side panel actions -> forward to backend
    sendToBackend(message);
    sendResponse({ ok: true });
  } else if (type === "get_status") {
    // Side panel asking for connection status
    sendResponse({ wsReady });
  } else if (type === "extract_form") {
    // Side panel requesting content script to extract form on active tab
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]?.id) {
        chrome.tabs.sendMessage(tabs[0].id, { type: "extract_form" }, (response) => {
          sendResponse(response || { error: "No response from content script" });
        });
      } else {
        sendResponse({ error: "No active tab" });
      }
    });
    return true; // keep sendResponse channel open for async
  }

  return false;
});

// Open side panel when extension icon is clicked
chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ tabId: tab.id });
});

// Connect on startup
connectWebSocket();
