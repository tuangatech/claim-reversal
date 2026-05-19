# shared/mcp_client.py
"""Async MCP client — connects to the MCP server via SSE and exposes typed tool methods."""

import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.sse import sse_client


class McpClient:
    """Async MCP client that connects to the shared MCP server on :8002 via SSE transport."""

    def __init__(self, server_url: str | None = None):
        port = os.environ.get("MCP_SERVER_PORT", "8002")
        self._server_url = server_url or f"http://localhost:{port}/sse"
        self._session: ClientSession | None = None
        self._read_stream = None
        self._write_stream = None
        self._cm = None

    async def connect(self, max_retries: int = 3) -> None:
        """Establishes SSE connection to the MCP server with retry/backoff."""
        delays = [1, 2, 4]
        last_error = None

        for attempt in range(max_retries):
            try:
                self._cm = sse_client(self._server_url)
                self._read_stream, self._write_stream = await self._cm.__aenter__()
                self._session = ClientSession(self._read_stream, self._write_stream)
                await self._session.__aenter__()
                await self._session.initialize()
                return
            except Exception as exc:
                last_error = exc
                # Clean up partial connection before retry
                await self._cleanup_partial()
                if attempt < max_retries - 1:
                    await asyncio.sleep(delays[attempt])

        raise ConnectionError(
            f"Failed to connect to MCP server at {self._server_url} after {max_retries} attempts: {last_error}"
        )

    async def _cleanup_partial(self) -> None:
        """Cleans up partially established connections."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
        if self._cm:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
            self._cm = None

    async def disconnect(self) -> None:
        """Cleanly closes the SSE session."""
        if self._session:
            await self._session.__aexit__(None, None, None)
            self._session = None
        if self._cm:
            await self._cm.__aexit__(None, None, None)
            self._cm = None

    def _ensure_connected(self) -> ClientSession:
        """Raises if not connected."""
        if self._session is None:
            raise RuntimeError("McpClient not connected. Call await client.connect() first.")
        return self._session

    async def _call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Calls a tool on the MCP server and returns the parsed result."""
        session = self._ensure_connected()
        result = await session.call_tool(tool_name, arguments=arguments)
        # MCP tool results come as content blocks; parse the text content as JSON
        if result.content and len(result.content) > 0:
            text = result.content[0].text
            return json.loads(text)
        return {}

    async def lookup_clinical_guideline(self, diagnosis_code: str) -> dict:
        """Returns clinical guideline criteria for a diagnosis code."""
        return await self._call_tool("lookup_clinical_guideline", {"diagnosis_code": diagnosis_code})

    async def get_payer_appeal_rules(self, payer_id: str) -> dict:
        """Returns payer-specific appeal rules."""
        return await self._call_tool("get_payer_appeal_rules", {"payer_id": payer_id})

    async def log_appeal_event(self, claim_id: str, event_type: str, payload: dict, agent_name: str) -> dict:
        """Writes an appeal event to the audit log via MCP."""
        return await self._call_tool("log_appeal_event", {
            "claim_id": claim_id,
            "event_type": event_type,
            "payload": json.dumps(payload),
            "agent_name": agent_name,
        })

    async def get_claim_history(self, claim_id: str) -> dict:
        """Retrieves prior denial and appeal history for a claim."""
        return await self._call_tool("get_claim_history", {"claim_id": claim_id})

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

