# # # """
# # # MQTT Client for TheSports API Live Scores

# # # This module provides an async MQTT client that connects to TheSports API
# # # via MQTT over WebSocket to receive real-time live scores for various sports.
# # # """

# # # import json
# # # import asyncio
# # # import logging
# # # from typing import Dict, List, Callable, Optional, Set
# # # from threading import Thread
# # # from paho.mqtt import client as mqtt
# # # from core.config import settings
# # # from collections import deque
# # # import threading
# # # from datetime import datetime

# # # logger = logging.getLogger(__name__)


# # # class SportsMQTTClient:
# # #     """
# # #     MQTT Client for TheSports API Live Scores
    
# # #     Connects to mq.thesports.com via MQTT over WebSocket (TLS)
# # #     Uses username and password authentication (same as HTTP API)
# # #     """
    
# # #     def __init__(self):
# # #         self.client: Optional[mqtt.Client] = None
# # #         self.connected = False
# # #         self.subscribed_topics: Set[str] = set()
# # #         self.message_callbacks: Dict[str, List[Callable]] = {}  # topic -> [callbacks]
# # #         self.all_callbacks: List[Callable] = []  # Callbacks for all messages
# # #         self._loop_thread: Optional[Thread] = None
# # #         # Thread-safe message queue for async processing
# # #         self._message_queue = deque()
# # #         self._queue_lock = threading.Lock()
# # #         # Store latest match updates by match_id (thread-safe)
# # #         self._latest_match_updates: Dict[str, dict] = {}  # match_id -> latest update data
# # #         self._updates_lock = threading.Lock()
        
# # #     def _on_connect(self, client, userdata, flags, rc):
# # #         """Connection callback"""
# # #         if rc == 0:
# # #             logger.info("✅ Successfully connected to TheSports MQTT broker")
# # #             self.connected = True
            
# # #             # Resubscribe to all previously subscribed topics
# # #             for topic in self.subscribed_topics:
# # #                 client.subscribe(topic)
# # #                 logger.info(f"📡 Resubscribed to topic: {topic}")
# # #         elif rc in [4, 5]:
# # #             logger.error(
# # #                 "❌ MQTT authentication failed. "
# # #                 "Please confirm username, password, and authorized IP are correct."
# # #             )
# # #             self.connected = False
# # #         else:
# # #             logger.error(f"❌ MQTT connection failed with code: {rc}")
# # #             self.connected = False
    
# # #     def _on_disconnect(self, client, userdata, rc):
# # #         """Disconnection callback"""
# # #         self.connected = False
# # #         if rc != 0:
# # #             logger.warning(f"⚠️ Unexpected MQTT disconnection (rc={rc})")
# # #         else:
# # #             logger.info("ℹ️ Disconnected from MQTT broker")
    
# # #     def _on_message(self, client, userdata, msg):
# # #         """Message callback - handles incoming messages"""
# # #         try:
# # #             topic = msg.topic
# # #             payload = msg.payload.decode('utf-8')
            
# # #             # Parse JSON payload
# # #             try:
# # #                 data = json.loads(payload)
# # #             except json.JSONDecodeError:
# # #                 logger.warning(f"⚠️ Invalid JSON in message from topic {topic}")
# # #                 data = {"raw": payload}
            
# # #             logger.info(f"📨 [MQTT Client] Received message from topic {topic}")
# # #             print(f"📨 [MQTT Client] Received message from topic {topic}")
            
# # #             # Add to queue for async processing
# # #             with self._queue_lock:
# # #                 self._message_queue.append((topic, data))
            
# # #             # Store latest match update by match_id (if available in data)
# # #             # Extract match_id from various possible fields
# # #             match_id = None
# # #             if isinstance(data, dict):
# # #                 match_id = (
# # #                     data.get("match_id") or 
# # #                     data.get("matchId") or 
# # #                     data.get("id") or
# # #                     data.get("data", {}).get("match_id") if isinstance(data.get("data"), dict) else None
# # #                 )
                
# # #                 if match_id:
# # #                     # Store latest update for this match
# # #                     with self._updates_lock:
# # #                         self._latest_match_updates[str(match_id)] = {
# # #                             "topic": topic,
# # #                             "data": data,
# # #                             "timestamp": datetime.now().isoformat()
# # #                         }
            
# # #             # Call topic-specific callbacks
# # #             if topic in self.message_callbacks:
# # #                 print(f"📞 [MQTT Client] Calling {len(self.message_callbacks[topic])} topic-specific callbacks for {topic}")
# # #                 for callback in self.message_callbacks[topic]:
# # #                     try:
# # #                         print(f"📞 [MQTT Client] Executing topic callback for {topic}")
# # #                         callback(topic, data)
# # #                         print(f"✅ [MQTT Client] Topic callback executed successfully for {topic}")
# # #                     except Exception as e:
# # #                         logger.error(f"❌ Error in topic callback for {topic}: {str(e)}")
# # #                         print(f"❌ [MQTT Client] Error in topic callback for {topic}: {e}")
# # #                         import traceback
# # #                         traceback.print_exc()
# # #             else:
# # #                 print(f"⚠️ [MQTT Client] No topic-specific callbacks registered for {topic}")
            
# # #             # Call all-messages callbacks
# # #             if self.all_callbacks:
# # #                 print(f"📞 [MQTT Client] Calling {len(self.all_callbacks)} global callbacks")
# # #                 for callback in self.all_callbacks:
# # #                     try:
# # #                         print(f"📞 [MQTT Client] Executing global callback")
# # #                         callback(topic, data)
# # #                         print(f"✅ [MQTT Client] Global callback executed successfully")
# # #                     except Exception as e:
# # #                         logger.error(f"❌ Error in global callback: {str(e)}")
# # #                         print(f"❌ [MQTT Client] Error in global callback: {e}")
# # #                         import traceback
# # #                         traceback.print_exc()
# # #             else:
# # #                 print(f"⚠️ [MQTT Client] No global callbacks registered")
                    
# # #         except Exception as e:
# # #             logger.error(f"❌ Error processing MQTT message: {str(e)}")
    
# # #     def get_pending_messages(self) -> List[tuple]:
# # #         """Get all pending messages from the queue (thread-safe)"""
# # #         with self._queue_lock:
# # #             messages = list(self._message_queue)
# # #             self._message_queue.clear()
# # #             return messages
    
# # #     def _on_subscribe(self, client, userdata, mid, granted_qos):
# # #         """Subscribe callback"""
# # #         logger.info(f"✅ Successfully subscribed (mid={mid}, qos={granted_qos})")
    
# # #     def _on_log(self, client, userdata, level, buf):
# # #         """Log callback - useful for debugging"""
# # #         if level <= mqtt.MQTT_LOG_WARNING:
# # #             logger.debug(f"MQTT: {buf}")
    
# # #     def connect(self) -> bool:
# # #         """
# # #         Connect to TheSports MQTT broker
        
# # #         Returns:
# # #             bool: True if connection successful, False otherwise
# # #         """
# # #         try:
# # #             # Create MQTT client with WebSocket transport
# # #             self.client = mqtt.Client(transport='websockets')
            
# # #             # Enable TLS
# # #             self.client.tls_set()
            
# # #             # Set authentication (uses same credentials as HTTP API)
# # #             self.client.username_pw_set(
# # #                 username=settings.SPORTS_USER_TOKEN,
# # #                 password=settings.SPORTS_SECRET_TOKEN
# # #             )
            
# # #             # Set callbacks
# # #             self.client.on_connect = self._on_connect
# # #             self.client.on_disconnect = self._on_disconnect
# # #             self.client.on_message = self._on_message
# # #             self.client.on_subscribe = self._on_subscribe
# # #             self.client.on_log = self._on_log
            
# # #             # Connect to broker
# # #             logger.info(f"🔌 Connecting to MQTT broker at {settings.SPORTS_MQTT_HOST}:{settings.SPORTS_MQTT_PORT}")
# # #             self.client.connect(settings.SPORTS_MQTT_HOST, settings.SPORTS_MQTT_PORT, 60)
            
# # #             # Start network loop in a separate thread
# # #             self._loop_thread = Thread(target=self._network_loop, daemon=True)
# # #             self._loop_thread.start()
            
# # #             # Wait for connection (with timeout)
# # #             import time
# # #             timeout = 10
# # #             elapsed = 0
# # #             while not self.connected and elapsed < timeout:
# # #                 time.sleep(0.1)
# # #                 elapsed += 0.1
            
# # #             if self.connected:
# # #                 logger.info("✅ MQTT client connected and ready")
# # #                 return True
# # #             else:
# # #                 logger.error("❌ MQTT connection timeout")
# # #                 return False
                
# # #         except Exception as e:
# # #             logger.error(f"❌ Error connecting to MQTT broker: {str(e)}")
# # #             return False
    
# # #     def _network_loop(self):
# # #         """Run MQTT network loop in a separate thread"""
# # #         if self.client:
# # #             self.client.loop_forever()
    
# # #     def disconnect(self):
# # #         """Disconnect from MQTT broker"""
# # #         if self.client:
# # #             self.client.loop_stop()
# # #             self.client.disconnect()
# # #             self.connected = False
# # #             self.subscribed_topics.clear()
# # #             logger.info("ℹ️ Disconnected from MQTT broker")
    
# # #     def subscribe(self, topic: str, callback: Optional[Callable] = None):
# # #         """
# # #         Subscribe to a topic
        
# # #         Args:
# # #             topic: MQTT topic to subscribe to
# # #             callback: Optional callback function(topic, data) called when message received
# # #         """
# # #         if not self.client or not self.connected:
# # #             logger.error("❌ MQTT client not connected. Call connect() first.")
# # #             return False
        
# # #         try:
# # #             # Subscribe to topic
# # #             result, mid = self.client.subscribe(topic, qos=1)
# # #             if result == mqtt.MQTT_ERR_SUCCESS:
# # #                 self.subscribed_topics.add(topic)
# # #                 logger.info(f"📡 Subscribed to topic: {topic}")
                
# # #                 # Add callback if provided
# # #                 if callback:
# # #                     if topic not in self.message_callbacks:
# # #                         self.message_callbacks[topic] = []
# # #                     self.message_callbacks[topic].append(callback)
                
# # #                 return True
# # #             else:
# # #                 logger.error(f"❌ Failed to subscribe to topic {topic}: error code {result}")
# # #                 return False
# # #         except Exception as e:
# # #             logger.error(f"❌ Error subscribing to topic {topic}: {str(e)}")
# # #             return False
    
# # #     def unsubscribe(self, topic: str):
# # #         """Unsubscribe from a topic"""
# # #         if not self.client or not self.connected:
# # #             return False
        
# # #         try:
# # #             self.client.unsubscribe(topic)
# # #             self.subscribed_topics.discard(topic)
# # #             if topic in self.message_callbacks:
# # #                 del self.message_callbacks[topic]
# # #             logger.info(f"📡 Unsubscribed from topic: {topic}")
# # #             return True
# # #         except Exception as e:
# # #             logger.error(f"❌ Error unsubscribing from topic {topic}: {str(e)}")
# # #             return False
    
# # #     def add_global_callback(self, callback: Callable):
# # #         """
# # #         Add a callback that receives all messages from all topics
        
# # #         Args:
# # #             callback: Function(topic, data) called for every message
# # #         """
# # #         self.all_callbacks.append(callback)
    
# # #     def remove_global_callback(self, callback: Callable):
# # #         """Remove a global callback"""
# # #         if callback in self.all_callbacks:
# # #             self.all_callbacks.remove(callback)
    
# # #     def is_connected(self) -> bool:
# # #         """Check if client is connected"""
# # #         return self.connected and self.client is not None
    
# # #     def get_subscribed_topics(self) -> Set[str]:
# # #         """Get set of currently subscribed topics"""
# # #         return self.subscribed_topics.copy()
    
# # #     def get_latest_match_updates(self, match_ids: Optional[List[str]] = None) -> Dict[str, dict]:
# # #         """
# # #         Get latest match updates from MQTT
        
# # #         Args:
# # #             match_ids: Optional list of match_ids to filter. If None, returns all updates.
        
# # #         Returns:
# # #             Dict mapping match_id -> latest update data
# # #         """
# # #         with self._updates_lock:
# # #             if match_ids:
# # #                 return {
# # #                     match_id: self._latest_match_updates.get(match_id)
# # #                     for match_id in match_ids
# # #                     if match_id in self._latest_match_updates
# # #                 }
# # #             return self._latest_match_updates.copy()
    
# # #     def get_latest_updates_for_topic(self, topic: str) -> List[dict]:
# # #         """
# # #         Get latest updates for a specific topic
        
# # #         Args:
# # #             topic: MQTT topic to filter updates
        
# # #         Returns:
# # #             List of latest update data for the topic
# # #         """
# # #         with self._updates_lock:
# # #             return [
# # #                 update_data
# # #                 for match_id, update_data in self._latest_match_updates.items()
# # #                 if update_data.get("topic") == topic
# # #             ]


# # # # Global MQTT client instance
# # # _sports_mqtt_client: Optional[SportsMQTTClient] = None


# # # def get_sports_mqtt_client() -> SportsMQTTClient:
# # #     """
# # #     Get or create the global Sports MQTT client instance
    
# # #     Returns:
# # #         SportsMQTTClient: The global MQTT client instance
# # #     """
# # #     global _sports_mqtt_client
    
# # #     if _sports_mqtt_client is None:
# # #         _sports_mqtt_client = SportsMQTTClient()
    
# # #     return _sports_mqtt_client


# # # async def initialize_sports_mqtt():
# # #     """Initialize and connect the Sports MQTT client"""
# # #     client = get_sports_mqtt_client()
# # #     if not client.is_connected():
# # #         success = client.connect()
# # #         if success:
# # #             logger.info("✅ Sports MQTT client initialized successfully")
# # #         else:
# # #             logger.warning("⚠️ Failed to initialize Sports MQTT client")
# # #     return client



# # """
# # Real-Time Sports MQTT Listener
# # Connects to TheSports.com MQTT WebSocket and emits live updates to frontend via Socket.IO
# # """

# # import json
# # import asyncio
# # import logging
# # from datetime import datetime, timezone
# # import paho.mqtt.client as mqtt

# # from services.socket_manager import sio  # use your existing socket_manager

# # logger = logging.getLogger("sports_mqtt_listener")

# # # TheSports MQTT Configuration
# # MQTT_BROKER = "mq.thesports.com"
# # MQTT_PORT = 8083  # WebSocket port
# # MQTT_USERNAME = "mvpsports"
# # MQTT_PASSWORD = "55df235bf1c0a03e4236c5b413b38c1a"
# # MQTT_TOPICS = [
# #     # "basketball/match/lineup_live",
# #     "basketball/match/detail_live",
# # ]

# # # Global client
# # mqtt_client = None


# # def on_connect(client, userdata, flags, rc):
# #     """When connected to TheSports MQTT server"""
# #     if rc == 0:
# #         logger.info("✅ Connected to TheSports MQTT broker")
# #         # Subscribe to topics for live updates
# #         for topic in MQTT_TOPICS:
# #             client.subscribe(topic)
# #             logger.info(f"📡 Subscribed to topic: {topic}")
# #     else:
# #         logger.error(f"❌ Failed to connect to TheSports MQTT broker, code: {rc}")


# # def on_disconnect(client, userdata, rc):
# #     logger.warning(f"🔴 Disconnected from MQTT broker (code={rc})")
# #     # Optional: try reconnect
# #     try:
# #         client.reconnect()
# #         logger.info("🔁 Reconnected to MQTT broker")
# #     except Exception as e:
# #         logger.error(f"⚠️ MQTT reconnect failed: {e}")


# # def on_message(client, userdata, msg):
# #     """Handle incoming live updates"""
# #     try:
# #         payload = msg.payload.decode("utf-8")
# #         data = json.loads(payload)
# #         topic = msg.topic
# #         logger.info(f"📨 MQTT message received on {topic}")

# #         # Extract live player or score data
# #         match_id = data.get("id") or data.get("match_id")
# #         live_data = {
# #             "topic": topic,
# #             "match_id": match_id,
# #             "data": data,
# #             "timestamp": datetime.now(timezone.utc).isoformat(),
# #         }

# #         # Emit live updates via Socket.IO to all connected clients
# #         sio.start_background_task(
# #             sio.emit,
# #             "live_player_update" if "lineup_live" in topic else "live_score_update",
# #             live_data,
# #             namespace="/sports",
# #         )
# #     except Exception as e:
# #         logger.error(f"⚠️ Error processing MQTT message: {e}")


# # def start_mqtt_listener():
# #     """Initialize and start MQTT client"""
# #     global mqtt_client

# #     logger.info("🚀 Starting TheSports MQTT listener...")

# #     mqtt_client = mqtt.Client(
# #         client_id="BettingAppClient",
# #         transport="websockets"
# #     )
# #     mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

# #     mqtt_client.on_connect = on_connect
# #     mqtt_client.on_message = on_message
# #     mqtt_client.on_disconnect = on_disconnect

# #     mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)

# #     # Run MQTT loop forever in a background thread
# #     mqtt_client.loop_start()
# #     logger.info("✅ MQTT listener started and running in background.")


# # def stop_mqtt_listener():
# #     """Stop MQTT listener cleanly"""
# #     global mqtt_client
# #     if mqtt_client:
# #         mqtt_client.loop_stop()
# #         mqtt_client.disconnect()
# #         logger.info("🛑 MQTT listener stopped")


# import asyncio
# import json
# import ssl
# import paho.mqtt.client as mqtt

# # from chat_socket_manager import socket_manager  # Your ChatSocketManager from above

# # ===========================================
# # ⚽ CONFIGURATION
# # ===========================================

# MQTT_HOST = "mq.thesports.com"
# MQTT_PORT = 443
# MQTT_TRANSPORT = "websockets"

# USERNAME = "YOUR_THESPORTS_USERNAME"
# PASSWORD = "YOUR_THESPORTS_SECRET_KEY"

# # Subscribe topics — check docs for correct topic names
# FOOTBALL_TOPIC = "football/live"
# BASKETBALL_TOPIC = "basketball/live"
# TENNIS_TOPIC = "tennis/live"

# # ===========================================
# # 🧠 MQTT -> SOCKET.IO BRIDGE
# # ===========================================

# def on_connect(client, userdata, flags, rc):
#     """Called when the MQTT client connects."""
#     if rc == 0:
#         print("✅ Connected to TheSports MQTT WebSocket")
#         client.subscribe(FOOTBALL_TOPIC)
#         client.subscribe(BASKETBALL_TOPIC)
#         client.subscribe(TENNIS_TOPIC)
#         print(f"📡 Subscribed to topics: {FOOTBALL_TOPIC}, {BASKETBALL_TOPIC}, {TENNIS_TOPIC}")
#     elif rc in [4, 5]:
#         print("❌ Authentication failed — check username, secret, or IP whitelist")
#     else:
#         print(f"⚠️ Connection failed with code {rc}")

# def on_message(client, userdata, msg):
#     """Called when a message is received from TheSports."""
#     try:
#         payload = json.loads(msg.payload.decode("utf-8"))
#         topic = msg.topic
#         print(f"📨 Received update from topic: {topic}")
#         print(json.dumps(payload, indent=2))

#         # Push real-time update to all connected Socket.IO clients
#         asyncio.run_coroutine_threadsafe(
#             socket_manager.sio.emit(
#                 "live_score_update",
#                 {"topic": topic, "data": payload}
#             ),
#             asyncio.get_event_loop()
#         )
#     except Exception as e:
#         print(f"❌ Error processing message: {e}")

# # ===========================================
# # 🚀 MQTT CLIENT STARTUP
# # ===========================================

# def start_mqtt_client():
#     client = mqtt.Client(transport=MQTT_TRANSPORT)
#     client.username_pw_set(username=USERNAME, password=PASSWORD)
#     client.on_connect = on_connect
#     client.on_message = on_message

#     # Use TLS (secure websocket)
#     client.tls_set(cert_reqs=ssl.CERT_NONE)
#     client.tls_insecure_set(True)

#     client.connect(MQTT_HOST, MQTT_PORT)
#     client.loop_start()  # Run MQTT in background thread

#     print("🏁 MQTT client started (background mode)")
#     return client

# # ===========================================
# # 🧩 MAIN ENTRY POINT
# # ===========================================

# # if __name__ == "__main__":
# #     print("🔗 Starting TheSports live data bridge...")
# #     mqtt_client = start_mqtt_client()

# #     # Run your ASGI server (example: FastAPI + Socket.IO)
# #     import uvicorn
# #     from fastapi import FastAPI
# #     import socketio

# #     app = FastAPI()
# #     sio_app = socketio.ASGIApp(socket_manager.sio, app)

# #     print("🚀 Running ASGI app with Socket.IO support...")
# #     uvicorn.run(sio_app, host="0.0.0.0", port=8000)




# import asyncio
# import json
# import ssl
# import paho.mqtt.client as mqtt
# # from chat_socket_manager import socket_manager  # your ChatSocketManager instance
# from core.socket import socket_manager
# # ======================================
# # CONFIGURATION
# # ======================================
# MQTT_HOST = "mq.thesports.com"
# MQTT_PORT = 443
# MQTT_TRANSPORT = "websockets"

# USERNAME = "mvpsports"
# PASSWORD = "55df235bf1c0a03e4236c5b413b38c1a"

# # Topics you want to subscribe to
# TOPICS = [
#     "football/live",
#     "basketball/live",
#     "tennis/live"
# ]

# # ======================================
# # MQTT EVENT HANDLERS
# # ======================================

# def on_connect(client, userdata, flags, rc):
#     """Handle successful MQTT connection."""
#     if rc == 0:
#         print("✅ Connected to TheSports MQTT WebSocket")
#         for topic in TOPICS:
#             client.subscribe(topic)
#             print(f"📡 Subscribed to: {topic}")
#     elif rc in [4, 5]:
#         print("❌ Authentication failed. Check username, key, and IP whitelist.")
#     else:
#         print(f"⚠️ Connection failed with code {rc}")

# def on_message(client, userdata, msg):
#     """Handle incoming MQTT messages."""
#     print("gaya")
#     try:
#         payload = json.loads(msg.payload.decode("utf-8"))
#         topic = msg.topic

#         print(f"📨 MQTT Update Received from: {topic}")
#         print(json.dumps(payload, indent=2))

#         # Forward to all Socket.IO clients
#         asyncio.run_coroutine_threadsafe(
#             socket_manager.sio.emit(
#                 "live_score_update",
#                 {"topic": topic, "data": payload}
#             ),
#             asyncio.get_event_loop()
#         )

#     except Exception as e:
#         print(f"❌ Error processing MQTT message: {e}")

# def on_disconnect(client, userdata, rc):
#     print("⚡ MQTT disconnected. Will attempt reconnect.")
#     # You could implement auto-reconnect here if needed.

# # ======================================
# # MQTT CLIENT INITIALIZATION
# # ======================================

# def start_mqtt_client():
#     client = mqtt.Client(transport=MQTT_TRANSPORT)
#     client.username_pw_set(username=USERNAME, password=PASSWORD)
#     client.on_connect = on_connect
#     client.on_message = on_message
#     client.on_disconnect = on_disconnect

#     # Secure WebSocket
#     client.tls_set(cert_reqs=ssl.CERT_NONE)
#     client.tls_insecure_set(True)

#     client.connect(MQTT_HOST, MQTT_PORT)
#     client.loop_start()

#     print("🚀 MQTT client running in background thread")
#     return client

# # ======================================
# # ASGI + SOCKET.IO SERVER
# # ======================================

# # if __name__ == "__main__":
# #     print("🔗 Starting TheSports MQTT bridge...")

# #     mqtt_client = start_mqtt_client()

# #     import uvicorn
# #     from fastapi import FastAPI
# #     import socketio

# #     app = FastAPI()
# #     sio_app = socketio.ASGIApp(socket_manager.sio, app)

# #     print("🚀 Running ASGI app with Socket.IO enabled...")
# #     uvicorn.run(sio_app, host="0.0.0.0", port=8000)





import asyncio
import json
import ssl
import paho.mqtt.client as mqtt
from core.socket import socket_manager

# ======================================
# CONFIGURATION
# ======================================
MQTT_HOST = "mq.thesports.com"
MQTT_PORT = 443
MQTT_TRANSPORT = "websockets"

USERNAME = "mvpsports"
PASSWORD = "55df235bf1c0a03e4236c5b413b38c1a"

# Topics you want to subscribe to
TOPICS = [
    # "football/live",
    "thesports/american_football/match/v1",
    "thesports/basketball/match/v1"
    # "tennis/live"
]

# # ======================================
# # MQTT EVENT HANDLERS
# # ======================================
# mqtt_message_queue = asyncio.Queue()  # Async queue for MQTT → Socket.IO
# async def hello():
#     await socket_manager.sio.emit(
#         "live_score_update",
#         {"topic": "topic", "data": {"message": "Connected to TheSports MQTT WebSocket"}},
#     )
#     print("Connected to TheSports MQTT WebSocket ppppp")

# def on_connect(client, userdata, flags, rc):
#     """Handle successful MQTT connection."""
#     if rc == 0:
#         print("✅ Connected to TheSports MQTT WebSocket")
#         hello()
#         for topic in TOPICS:
#             client.subscribe(topic)
#             print(f"📡 Subscribed to: {topic}")
#     elif rc in [4, 5]:
#         print("❌ Authentication failed. Check username, key, and IP whitelist.")
#     else:
#         print(f"⚠️ Connection failed with code {rc}")

# def on_message(client, userdata, msg):
#     """Handle incoming MQTT messages."""
#     print("gaya")
#     try:
#         payload = json.loads(msg.payload)
#         print(payload)
#         topic = msg.topic

#         print(f"📨 MQTT Update from {topic}")

#         # Forward to all clients in that sport’s room
#         # send message to the async queue:
#         asyncio.run_coroutine_threadsafe(
#             mqtt_message_queue.put({"topic": topic, "data": payload}),
#             asyncio.get_event_loop()
#         )

#     except Exception as e:
#         print(f"❌ Error processing MQTT message: {e}")

# # def on_disconnect(client, userdata, rc):
# #     print("⚡ MQTT disconnected. Attempting reconnect...")

# # ======================================
# # STARTUP FUNCTION
# # ======================================

# def start_mqtt_client():
#     """Initialize and start the MQTT WebSocket client"""
#     client = mqtt.Client(transport=MQTT_TRANSPORT)
#     client.username_pw_set(username=USERNAME, password=PASSWORD)
#     client.on_connect = on_connect
#     client.on_message = on_message
#     # client.on_disconnect = on_disconnect

#     # Secure WebSocket - Required for port 443
#     client.tls_set(cert_reqs=ssl.CERT_NONE)
#     client.tls_insecure_set(True)

#     client.connect(MQTT_HOST, MQTT_PORT)
#     client.loop_start()

#     print("🚀 MQTT client running in background thread")
#     return client

# import asyncio
# import json
# import threading
# import paho.mqtt.client as mqtt
# import socketio
# from fastapi import FastAPI
# import uvicorn
# # from core.socket import socket_manager as sio
# # # --- Setup Socket.IO server ---
# # sio = socketio.AsyncServer(cors_allowed_origins="*")
# # app = FastAPI()
# # socket_app = socketio.ASGIApp(sio, app)

# # --- MQTT Credentials (TheSports) ---
# MQTT_HOST = "mq.thesports.com"
# MQTT_PORT = 443
# MQTT_USERNAME = "mvpsports"
# MQTT_PASSWORD = "55df235bf1c0a03e4236c5b413b38c1a"

# FOOTBALL_TOPIC = "thesports/american_football/match/v1e"
# BASKETBALL_TOPIC = "thesports/basketball/match/v1"
# TENNIS_TOPIC = "tennis/live"


# # --- MQTT callbacks ---
# def on_connect(client, userdata, flags, rc):
#     if rc == 0:
#         print("✅ Connected to TheSports MQTT Broker")
#         client.subscribe(FOOTBALL_TOPIC)
#         client.subscribe(BASKETBALL_TOPIC)
#         client.subscribe(TENNIS_TOPIC)
#     elif rc in [4, 5]:
#         print("❌ Authentication failed — check username/password/IP authorization.")
#     else:
#         print(f"⚠️ Connection failed with code {rc}")

# def on_message(client, userdata, msg):
#     """Receive live data from TheSports and forward to frontend."""
#     try:
#         payload = json.loads(msg.payload)
#         # print(payload)
#         topic = msg.topic
#         print(f"📡 Received update on {topic}")

#         # Decide event type based on topic
#         if "football" in topic:
#             event = "football_update"
#         elif "basketball" in topic:
#             event = "basketball_update"
#         elif "tennis" in topic:
#             event = "tennis_update"
#         else:
#             event = "sports_update"

#        # ✅ Emit safely using the running event loop
#         loop = asyncio.get_event_loop()
#         if loop.is_running():
#             # Schedule in the existing event loop
#             asyncio.run_coroutine_threadsafe(
#                 socket_manager.sio.emit(event, {"topic": topic, "data": payload}),
#                 loop
#             )
#         else:
#             # For standalone testing (no running loop)
#             asyncio.run(socket_manager.sio.emit(event, {"topic": topic, "data": payload}))


#     except Exception as e:
#         print(f"Error in on_message: {e}")

# def start_mqtt():
#     """Run MQTT loop in background thread."""
#     client = mqtt.Client(transport='websockets')
#     client.tls_set()
#     client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
#     client.on_connect = on_connect
#     client.on_message = on_message
#     client.connect(MQTT_HOST, MQTT_PORT)
#     client.loop_forever()

# # Start MQTT background thread when server starts
# threading.Thread(target=start_mqtt, daemon=True).start()



import asyncio
import json
import threading
import paho.mqtt.client as mqtt
from core.socket import socket_manager

# --- MQTT Credentials ---
MQTT_HOST = "mq.thesports.com"
MQTT_PORT = 443
MQTT_USERNAME = "mvpsports"
MQTT_PASSWORD = "55df235bf1c0a03e4236c5b413b38c1a"

FOOTBALL_TOPIC = "thesports/american_football/match/v1"
BASKETBALL_TOPIC = "thesports/basketball/match/v1"
TENNIS_TOPIC = "tennis/live"

# Global loop reference (will be set at startup)
MAIN_EVENT_LOOP = None


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Connected to TheSports MQTT Broker")
        client.subscribe(FOOTBALL_TOPIC)
        client.subscribe(BASKETBALL_TOPIC)
        client.subscribe(TENNIS_TOPIC)
    elif rc in [4, 5]:
        print("❌ Authentication failed — check username/password/IP authorization.")
    else:
        print(f"⚠️ Connection failed with code {rc}")


def on_message(client, userdata, msg):
    """Receive live data from TheSports and forward to frontend."""
    global MAIN_EVENT_LOOP
    try:
        payload = json.loads(msg.payload)
        if isinstance(payload, list):
            payload = {"results": payload}
        topic = msg.topic
        print(f"📡 Received update on {topic}")

        if "football" in topic:
            event = "football_update"
        elif "basketball" in topic:
            event = "basketball_update"
        elif "tennis" in topic:
            event = "tennis_update"
        else:
            event = "sports_update"

        # Basketball-specific enrichment: totals + finished result handling
        if "basketball" in topic:
            results = payload.get("results") or []
            for match in results:
                score = match.get("score") or []
                home_scores = score[3] if len(score) > 3 and isinstance(score[3], list) else []
                away_scores = score[4] if len(score) > 4 and isinstance(score[4], list) else []

                home_total = sum(x for x in home_scores if isinstance(x, (int, float)))
                away_total = sum(x for x in away_scores if isinstance(x, (int, float)))

                match["home_total"] = home_total
                match["away_total"] = away_total

                status_code = score[1] if len(score) > 1 else None

                if status_code == 10:
                    if home_total > away_total:
                        outcome = "Home Win"
                    elif away_total > home_total:
                        outcome = "Away Win"
                    else:
                        outcome = "Draw"

                    match["match_result"] = outcome

                    match_id = match.get("id") or (score[0] if score else None)
                    if match_id and MAIN_EVENT_LOOP is not None:
                        match_result_payload = {
                            "status": "Finished",
                            "status_code": status_code,
                            "home_total": home_total,
                            "away_total": away_total,
                            "result": outcome,
                        }
                        from services.sports.routes import update_pick_result_in_db

                        asyncio.run_coroutine_threadsafe(
                            update_pick_result_in_db(str(match_id), match_result_payload),
                            MAIN_EVENT_LOOP,
                        )

        # ✅ Schedule emit on the main FastAPI event loop
        if MAIN_EVENT_LOOP is not None:
            asyncio.run_coroutine_threadsafe(
                socket_manager.sio.emit(event, {"topic": topic, "data": payload}),
                MAIN_EVENT_LOOP
            )
        else:
            print("⚠️ MAIN_EVENT_LOOP not yet set — skipping emit")

    except Exception as e:
        print(f"Error in on_message: {e}")


def start_mqtt():
    """Run MQTT loop in background thread."""
    client = mqtt.Client(transport='websockets')
    client.tls_set()
    client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_forever()


def start_mqtt_background(loop: asyncio.AbstractEventLoop):
    """Store main loop and start MQTT thread."""
    global MAIN_EVENT_LOOP
    MAIN_EVENT_LOOP = loop
    print("🔁 Main event loop captured for MQTT thread")

    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()
