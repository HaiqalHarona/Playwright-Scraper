"""
WebSocket client for connecting to webtop virtual desktop.
Provides real-time status updates and remote control capabilities.
"""

import asyncio
import json
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Optional, Union

try:
    import websockets  # type: ignore
    from websockets.exceptions import ConnectionClosed, InvalidURI  # type: ignore

    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

    # Create dummy classes for type checking
    class ConnectionClosed(Exception):
        pass

    class InvalidURI(Exception):
        pass


logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client for connecting to remote webtop virtual desktop."""

    def __init__(
        self,
        url: str,
        auth_token: Optional[str] = None,
        reconnect_interval: int = 10,
        heartbeat_interval: int = 30,
    ):
        """
        Initialize WebSocket client.

        Args:
            url: WebSocket URL (wss:// or ws://)
            auth_token: Optional authentication token
            reconnect_interval: Seconds between reconnection attempts
            heartbeat_interval: Seconds between heartbeat messages
        """
        self.url = url
        self.auth_token = auth_token
        self.reconnect_interval = reconnect_interval
        self.heartbeat_interval = heartbeat_interval
        self.websocket = None
        self.connected = False
        self.should_reconnect = True
        self.message_handlers: Dict[str, Callable] = {}
        self.event_handlers: Dict[str, Callable] = {}
        self.loop = None
        self.thread = None

    def register_message_handler(self, message_type: str, handler: Callable):
        """Register a handler for specific message types."""
        self.message_handlers[message_type] = handler

    def register_event_handler(self, event: str, handler: Callable):
        """Register a handler for connection events."""
        self.event_handlers[event] = handler

    def _trigger_event(self, event: str, *args, **kwargs):
        """Trigger an event handler if registered."""
        if event in self.event_handlers:
            try:
                self.event_handlers[event](*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in event handler for {event}: {e}")

    async def connect(self):
        """Establish WebSocket connection."""
        if not WEBSOCKETS_AVAILABLE:
            logger.error(
                "[WSS] websockets module not available. Install with: pip install websockets"
            )
            return

        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        try:
            logger.info(f"[WSS] Connecting to {self.url}")
            self.websocket = await websockets.connect(
                self.url,
                extra_headers=headers,
                ping_interval=None,  # We'll handle heartbeats manually
            )
            self.connected = True
            self._trigger_event("connected")
            logger.info("[WSS] Connected successfully")

            # Start heartbeat task
            asyncio.create_task(self._heartbeat_task())

            # Start message receiving task
            asyncio.create_task(self._receive_messages())

        except (ConnectionClosed, InvalidURI, OSError) as e:
            logger.error(f"[WSS] Connection failed: {e}")
            self.connected = False
            self._trigger_event("connection_failed", e)
            raise

    async def _heartbeat_task(self):
        """Send periodic heartbeat messages to keep connection alive."""
        while self.connected and self.websocket:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                if self.connected and self.websocket:
                    heartbeat_msg = json.dumps(
                        {
                            "type": "heartbeat",
                            "timestamp": time.time(),
                            "status": "alive",
                        }
                    )
                    await self.websocket.send(heartbeat_msg)
            except Exception as e:
                logger.error(f"[WSS] Heartbeat failed: {e}")
                break

    async def _receive_messages(self):
        """Continuously receive and process messages from WebSocket."""
        while self.connected and self.websocket:
            try:
                message = await self.websocket.recv()
                await self._process_message(message)
            except ConnectionClosed:
                logger.warning("[WSS] Connection closed")
                self.connected = False
                self._trigger_event("disconnected")
                break
            except Exception as e:
                logger.error(f"[WSS] Error receiving message: {e}")
                self.connected = False
                self._trigger_event("error", e)
                break

    async def _process_message(self, message: str):
        """Process incoming WebSocket message."""
        try:
            data = json.loads(message)
            message_type = data.get("type", "unknown")

            # Log received message
            logger.debug(f"[WSS] Received message type: {message_type}")

            # Call registered handler if exists
            if message_type in self.message_handlers:
                try:
                    await self.message_handlers[message_type](data)
                except Exception as e:
                    logger.error(f"[WSS] Error in handler for {message_type}: {e}")
            else:
                # Default handling for common message types
                if message_type == "ping":
                    await self.send({"type": "pong", "timestamp": time.time()})
                elif message_type == "command":
                    await self._handle_command(data)

        except json.JSONDecodeError:
            # Handle non-JSON messages
            logger.debug(f"[WSS] Received non-JSON message: {message[:100]}")
            self._trigger_event("raw_message", message)

    async def _handle_command(self, data: Dict[str, Any]):
        """Handle command messages from server."""
        command = data.get("command")
        params = data.get("params", {})

        logger.info(f"Received command: {command}")

        # Trigger command event
        self._trigger_event("command", command, params)

        # Send acknowledgment
        await self.send(
            {
                "type": "command_ack",
                "command": command,
                "status": "received",
                "timestamp": time.time(),
            }
        )

    async def send(self, data: Dict[str, Any]):
        """Send JSON data through WebSocket."""
        if not self.connected or not self.websocket:
            logger.warning("Cannot send message, WebSocket not connected")
            return False

        try:
            message = json.dumps(data)
            await self.websocket.send(message)
            return True
        except Exception as e:
            logger.error(f"Failed to send WebSocket message: {e}")
            self.connected = False
            return False

    async def send_status_update(
        self, status: str, details: Optional[Dict[str, Any]] = None
    ):
        """Send a status update to the server."""
        if details is None:
            details = {}

        return await self.send(
            {
                "type": "status_update",
                "status": status,
                "details": details,
                "timestamp": time.time(),
            }
        )

    async def send_log_message(
        self, level: str, message: str, context: Optional[Dict[str, Any]] = None
    ):
        """Send a log message to the server."""
        if context is None:
            context = {}

        return await self.send(
            {
                "type": "log",
                "level": level,
                "message": message,
                "context": context,
                "timestamp": time.time(),
            }
        )

    async def disconnect(self):
        """Disconnect from WebSocket server."""
        self.should_reconnect = False
        self.connected = False

        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.websocket = None

        self._trigger_event("disconnected")
        logger.info("WebSocket disconnected")

    async def run_with_reconnect(self):
        """Run the client with automatic reconnection."""
        while self.should_reconnect:
            try:
                await self.connect()

                # Wait until connection is closed
                while self.connected:
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"WebSocket error: {e}")

            # Wait before reconnecting
            if self.should_reconnect:
                logger.info(f"Reconnecting in {self.reconnect_interval} seconds...")
                await asyncio.sleep(self.reconnect_interval)

    def start_in_thread(self):
        """Start the WebSocket client in a separate thread."""
        if self.thread and self.thread.is_alive():
            logger.warning("WebSocket client already running in thread")
            return

        def run_in_thread():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.run_with_reconnect())

        self.thread = threading.Thread(target=run_in_thread, daemon=True)
        self.thread.start()
        logger.info("WebSocket client started in background thread")

    def stop(self):
        """Stop the WebSocket client."""
        self.should_reconnect = False

        if self.loop and self.loop.is_running():
            # Schedule disconnect in the event loop
            asyncio.run_coroutine_threadsafe(self.disconnect(), self.loop)

        if self.thread:
            self.thread.join(timeout=5)

        logger.info("WebSocket client stopped")


def create_client_from_env() -> Optional[WebSocketClient]:
    """
    Create a WebSocket client from environment variables.
    Returns None if WebSocket is not enabled.
    """
    if not WEBSOCKETS_AVAILABLE:
        logger.warning(
            "websockets module not available. Install with: pip install websockets"
        )
        return None

    wss_enabled = os.getenv("WSS_ENABLED", "false").lower() == "true"
    if not wss_enabled:
        return None

    wss_url = os.getenv("WSS_URL", "").strip()
    if not wss_url:
        logger.warning("WSS_ENABLED is true but WSS_URL is not set")
        return None

    auth_token = os.getenv("WSS_AUTH_TOKEN", "").strip()
    if not auth_token:
        auth_token = None

    try:
        reconnect_interval = int(os.getenv("WSS_RECONNECT_INTERVAL", "10"))
    except ValueError:
        reconnect_interval = 10

    try:
        heartbeat_interval = int(os.getenv("WSS_HEARTBEAT_INTERVAL", "30"))
    except ValueError:
        heartbeat_interval = 30

    return WebSocketClient(
        url=wss_url,
        auth_token=auth_token,
        reconnect_interval=reconnect_interval,
        heartbeat_interval=heartbeat_interval,
    )


# Global WebSocket client instance
_global_client: Optional[WebSocketClient] = None


def init_websocket_client() -> Optional[WebSocketClient]:
    """
    Initialize and start the global WebSocket client.
    Should be called once at application startup.
    """
    global _global_client

    if _global_client is not None:
        return _global_client

    client = create_client_from_env()
    if client:
        # Register default event handlers
        client.register_event_handler(
            "connected", lambda: logger.info("WebSocket connected")
        )
        client.register_event_handler(
            "disconnected", lambda: logger.warning("WebSocket disconnected")
        )
        client.register_event_handler(
            "command", lambda cmd, params: logger.info(f"Command received: {cmd}")
        )

        # Start client in background thread
        client.start_in_thread()
        _global_client = client

    return client


def get_websocket_client() -> Optional[WebSocketClient]:
    """Get the global WebSocket client instance."""
    return _global_client


def send_status(status: str, details: Optional[Dict[str, Any]] = None):
    """Send status update via WebSocket if client is available."""
    client = get_websocket_client()
    if client and client.connected:
        # Use asyncio to send in the client's event loop
        if client.loop and client.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                client.send_status_update(status, details or {}), client.loop
            )


def send_log(level: str, message: str, context: Optional[Dict[str, Any]] = None):
    """Send log message via WebSocket if client is available."""
    client = get_websocket_client()
    if client and client.connected:
        if client.loop and client.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                client.send_log_message(level, message, context or {}), client.loop
            )
