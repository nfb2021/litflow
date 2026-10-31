"""
Minimal MCP client for the Zotero MCP plugin's Streamable HTTP server.

The plugin (https://github.com/cookjohn/zotero-mcp) runs inside Zotero and listens on
http://127.0.0.1:23120/mcp. Override with $ZOTERO_MCP_URL.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "http://127.0.0.1:23120/mcp"
PROTOCOL_VERSION = "2025-03-26"

WRITE_HINT = (
    "Enable write operations in Zotero: Settings → Zotero MCP Plugin → "
    "'Enable Write Operations'"
)


class ZoteroError(RuntimeError):
    """Zotero or the plugin returned an error"""


class ZoteroNotRunning(ZoteroError):
    """Nothing answers on the plugin's port"""


def server_url() -> str:
    return os.environ.get("ZOTERO_MCP_URL", DEFAULT_URL)


class ZoteroMCP:
    """One MCP session with the plugin; call tools with .call(name, **args)"""

    def __init__(self, url: str | None = None, timeout: float = 120):
        self.url = url or server_url()
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 0
        self.server_info: dict = {}

    def _post(self, body: dict) -> Any:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(
            self.url, json.dumps(body).encode(), headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self.session_id = response.headers.get("Mcp-Session-Id") or (
                    self.session_id
                )
                content_type = response.headers.get("Content-Type", "")
                raw = response.read().decode()
        except urllib.error.URLError as e:
            if isinstance(e, urllib.error.HTTPError):
                raise ZoteroError(f"HTTP {e.code} from {self.url}") from e
            raise ZoteroNotRunning(
                f"No Zotero MCP server at {self.url}. Start Zotero and check that "
                "the Zotero MCP plugin is installed and its server is enabled."
            ) from e
        if not raw.strip():
            return None
        if "text/event-stream" in content_type:
            # Streamable HTTP may answer as SSE: keep the last data: line
            data = [
                line[5:].strip()
                for line in raw.splitlines()
                if line.startswith("data:")
            ]
            raw = data[-1] if data else "null"
        return json.loads(raw)

    def _rpc(self, method: str, params: dict | None = None) -> Any:
        self._next_id += 1
        body = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            body["params"] = params
        reply = self._post(body)
        if reply and reply.get("error"):
            raise ZoteroError(reply["error"].get("message", str(reply["error"])))
        return (reply or {}).get("result")

    def connect(self) -> "ZoteroMCP":
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "zot", "version": "0"},
            },
        )
        self.server_info = (result or {}).get("serverInfo", {})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def tools(self) -> list[str]:
        return [t["name"] for t in (self._rpc("tools/list") or {}).get("tools", [])]

    def call(self, tool: str, /, **args) -> Any:
        """Call a tool; returns its JSON payload (or plain text)"""
        if not self.session_id:
            self.connect()
        args = {k: v for k, v in args.items() if v is not None}
        result = self._rpc("tools/call", {"name": tool, "arguments": args}) or {}
        text = "\n".join(
            c.get("text", "")
            for c in result.get("content", [])
            if c.get("type") == "text"
        )
        if result.get("isError"):
            raise ZoteroError(_write_hint(text))
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(payload, dict) and payload.get("error") and len(payload) <= 3:
            raise ZoteroError(_write_hint(str(payload["error"])))
        return payload


def _write_hint(message: str) -> str:
    if "Write operations are currently disabled" in message:
        return f"Write operations are disabled. {WRITE_HINT}"
    return message


# ---------------------------------------------------------------------------
# Helpers on top of the plugin's tools
# ---------------------------------------------------------------------------


def find_collection(zot: ZoteroMCP, name_or_key: str) -> dict | None:
    """Collection by 8-character key or by exact (case-insensitive) name or path"""
    collections = zot.call("get_collections", recursive=True, limit=1000) or []
    wanted = name_or_key.strip().casefold()
    for c in collections:
        if c["key"] == name_or_key:
            return c
    for c in collections:
        if wanted in (c["name"].casefold(), collection_path(c).casefold()):
            return c
    return None


def collection_path(collection: dict) -> str:
    """'Parent/Child' (the plugin writes 'Parent > Child')"""
    return (collection.get("path") or collection["name"]).replace(" > ", "/")


def collection_items(zot: ZoteroMCP, key: str) -> list[dict]:
    """All regular items of a collection, with their attachments"""
    items, offset, page = [], 0, 100
    while True:
        batch = zot.call(
            "get_collection_items", collectionKey=key, limit=page, offset=offset
        )
        if not isinstance(batch, list) or not batch:
            return items
        items.extend(batch)
        if len(batch) < page:
            return items
        offset += page


def pdf_paths(item: dict) -> list[str]:
    """Local paths of an item's PDF attachments that exist on disk"""
    return [
        a["path"]
        for a in item.get("attachments") or []
        if a.get("contentType") == "application/pdf"
        and a.get("path")
        and os.path.exists(a["path"])
    ]
