"""
WebSocket KPI Stream — real-time intent health broadcasting.

Clients connect to /ws/kpi-stream and receive:
  - Live KPI observations as they are ingested
  - State machine snapshots after each tick
  - Drift events and causal links
  - System health changes

Message format (JSON):
  {
    "type": "kpi_update" | "state_snapshot" | "drift_alert" | "health_change",
    "payload": { ... },
    "ts": <unix_timestamp>
  }
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts."""

    def __init__(self) -> None:
        self._active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._active:
            self._active.remove(ws)

    async def broadcast(self, msg_type: str, payload: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        message = json.dumps({
            "type": msg_type,
            "payload": payload,
            "ts": time.time(),
        })
        dead: list[WebSocket] = []
        for ws in list(self._active):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def connection_count(self) -> int:
        return len(self._active)


# Global manager — shared across the app
manager = ConnectionManager()


async def kpi_stream_endpoint(websocket: WebSocket) -> None:
    """
    WebSocket endpoint handler.

    On connect: sends a welcome snapshot.
    On message: accepts KPI observation JSON and echoes processed result.
    Continuous: receives server-side broadcasts from the MILD tick loop.
    """
    await manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps({
            "type": "connected",
            "payload": {
                "message": "Connected to intent-drift-engine KPI stream",
                "active_connections": manager.connection_count(),
            },
            "ts": time.time(),
        }))
        # Keep connection alive — broadcasts are pushed from the tick loop
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Echo received data back as acknowledgement
                await websocket.send_text(json.dumps({
                    "type": "ack",
                    "payload": {"received": data},
                    "ts": time.time(),
                }))
            except asyncio.TimeoutError:
                # Send heartbeat ping
                await websocket.send_text(json.dumps({
                    "type": "heartbeat",
                    "payload": {"active_connections": manager.connection_count()},
                    "ts": time.time(),
                }))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
