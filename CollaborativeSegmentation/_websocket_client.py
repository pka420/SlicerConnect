# CollaborativeSegmentation/websocket_client.py
import websocket
import json
import threading
from typing import Callable, Optional
import logging

logger = logging.getLogger(__name__)


class CollaborationWebSocketClient:
    """WebSocket client for real-time collaborative segmentation updates"""

    def __init__(self, ws_url: str, session_id: str, token: str, logic):
        self.ws_url = f"{ws_url}/ws/sessions/{session_id}?token={token}"
        self.ws = None
        self.logic = logic

        # Callbacks
        self.on_user_joined: Optional[Callable[[str], None]] = None
        self.on_user_left: Optional[Callable[[str], None]] = None
        self.on_delta_received: Optional[Callable[[dict, str], None]] = None
        self.on_session_ended: Optional[Callable[[], None]] = None

        self.running = False
        self.thread = None

    def connect(self):
        """Start WebSocket connection in background thread"""
        if self.running:
            return

        self.running = True

        def on_message(ws, message):
            try:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "user_joined":
                    if self.on_user_joined:
                        self.on_user_joined(data["username"])
                elif msg_type == "user_left":
                    if self.on_user_left:
                        self.on_user_left(data["username"])
                elif msg_type == "delta":
                    if self.on_delta_received:
                        self.on_delta_received(data["delta"], data["username"])
                elif msg_type == "session_ended":
                    if self.on_session_ended:
                        self.on_session_ended()
                else:
                    logger.debug(f"Unknown message type: {msg_type}")

            except Exception as e:
                logger.error(f"Error processing websocket message: {e}")

        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            logger.info("WebSocket closed")
            self.running = False

        def on_open(ws):
            logger.info("WebSocket connection opened")

        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )

        self.thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.thread.start()

    def disconnect(self):
        """Close WebSocket connection"""
        self.running = False
        if self.ws:
            self.ws.close()
        if self.thread and self.thread.is_alive():
            # Give thread a moment to finish
            self.thread.join(timeout=2.0)

    def send_delta(self, delta: dict):
        """Send segmentation change (delta) to other users"""
        if not self.ws or not self.ws.sock or not self.ws.sock.connected:
            return

        message = {
            "type": "delta",
            "delta": delta,
            # username is usually added by server, but can be sent for info
        }
        try:
            self.ws.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send delta: {e}")
