import socketio
from typing import Dict
from datetime import datetime

# Database imports removed - Socket.IO uses in-memory storage only
from services.chat.auth import authenticate_socket_user

def serialize_datetime_fields(data: dict) -> dict:
    """Convert datetime objects to ISO format strings for JSON serialization"""
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
            elif isinstance(value, dict):
                data[key] = serialize_datetime_fields(value)
            elif isinstance(value, list):
                data[key] = [
                    serialize_datetime_fields(item) if isinstance(item, dict) else item
                    for item in value
                ]
    return data

class ChatSocketManager:
    def __init__(self):
        # Create Socket.IO server
        self.sio = socketio.AsyncServer(
            cors_allowed_origins="*",  # Configure based on your frontend domains
            logger=True,
            engineio_logger=True,
            async_mode="asgi",
        )
        
        # Track connected users: {socket_id: user_data}
        self.connected_users: Dict[str, dict] = {}
        
        # Setup event handlers
        self.setup_events()
    
    def setup_events(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect(sid, environ, auth):
            """Handle user connection"""
            print(f"🔌 User connecting: {sid}")
            
            # Authenticate user
            token = None
            if auth and 'token' in auth:
                token = auth['token']
                print(f"🎫 Token from auth: {token[:20]}...")
            elif environ.get('HTTP_AUTHORIZATION'):
                token = environ['HTTP_AUTHORIZATION']
                print(f"🎫 Token from headers: {token[:20]}...")
            else:
                print("⚠️ No token found in auth or headers")
            
            # For testing, allow connections without token
            if not token:
                print("⚠️ No token provided, allowing connection for testing")
                await self.sio.emit('connected', {'message': 'Connected without authentication'}, room=sid)
                return True
            
            # Authenticate user
            try:
                user_data = await authenticate_socket_user(token)
                if user_data:
                    # Store user connection
                    self.connected_users[sid] = {
                        **user_data,
                        'connected_at': datetime.utcnow(),
                        'last_activity': datetime.utcnow()
                    }
                    
                    print(f"✅ User authenticated: {user_data['username']} ({user_data['user_id']})")
                    
                    # Send current online users list to the newly connected user
                    online_users = []
                    for socket_id, connected_user_data in self.connected_users.items():
                        online_users.append({
                            "user_id": connected_user_data["user_id"],
                            "username": connected_user_data.get("username"),
                            "full_name": connected_user_data.get("full_name"),
                            "socket_id": socket_id,
                        })

                    await self.sio.emit(
                        "online-users-list",
                        {"online_users": online_users, "total_count": len(online_users)},
                        room=sid,
                    )
                    
                    # Broadcast to all other users that this user is online
                    await self.sio.emit(
                        "user-online",
                        {
                            "user_id": user_data["user_id"],
                            "username": user_data.get("username"),
                            "full_name": user_data.get("full_name"),
                        },
                        skip_sid=sid,  # Skip sending to the user who just connected
                    )
                    
                    return True
                else:
                    print("❌ Authentication failed")
                    await self.sio.emit('auth_error', {'message': 'Authentication failed'}, room=sid)
                    return False
            except Exception as e:
                print(f"❌ Authentication error: {e}")
                await self.sio.emit('auth_error', {'message': str(e)}, room=sid)
                return False

        @self.sio.event
        async def disconnect(sid):
            """Handle user disconnection"""
            print(f"🔌 User disconnecting: {sid}")
            
            if sid in self.connected_users:
                user_data = self.connected_users[sid]
                user_id = user_data["user_id"]
                username = user_data.get("username")
                
                print(f"👋 User {username} ({user_id}) disconnected")
                
                # Broadcast to all other users that this user is offline
                await self.sio.emit(
                    "user-offline",
                    {
                        "user_id": user_id,
                        "username": username,
                        "full_name": user_data.get("full_name"),
                    },
                    skip_sid=sid,  # Skip sending to the disconnected user
                )
                
                # Remove from connected users
                del self.connected_users[sid]
            else:
                print(f"⚠️ Unknown user disconnected: {sid}")

        # ========================================
        # USER PRESENCE EVENTS
        # ========================================

        # ========================================
        # NOTE: user-online and user-offline events are automatically 
        # triggered by connect/disconnect events. Frontend should NOT 
        # manually send these events to avoid infinite loops.
        # ========================================

        @self.sio.event
        async def get_online_users(sid, data=None):
            """Send list of all online users to requesting client"""
            if sid not in self.connected_users:
                await self.sio.emit(
                    "error", {"message": "User not authenticated"}, room=sid
                )
                return

            # Get all online users from connected_users
            online_users = []
            for socket_id, user_data in self.connected_users.items():
                online_users.append(
                    {
                        "user_id": user_data["user_id"],
                        "username": user_data.get("username"),
                        "full_name": user_data.get("full_name"),
                        "socket_id": socket_id,
                    }
                )

            print(f"📋 Sending online users list: {len(online_users)} users")

            # Send online users list to requesting client
            await self.sio.emit(
                "online-users-list",
                {"online_users": online_users, "total_count": len(online_users)},
                room=sid,
            )

        # Handle both underscore and hyphen versions
        @self.sio.on("get-online-users")
        async def get_online_users_hyphen(sid, data=None):
            """Send list of all online users to requesting client (hyphen version)"""
            if sid not in self.connected_users:
                await self.sio.emit(
                    "error", {"message": "User not authenticated"}, room=sid
                )
                return

            # Get all online users from connected_users
            online_users = []
            for socket_id, user_data in self.connected_users.items():
                online_users.append(
                    {
                        "user_id": user_data["user_id"],
                        "username": user_data.get("username"),
                        "full_name": user_data.get("full_name"),
                        "socket_id": socket_id,
                    }
                )

            print(f"📋 Sending online users list (hyphen): {len(online_users)} users")

            # Send online users list to requesting client
            await self.sio.emit(
                "online-users-list",
                {"online_users": online_users, "total_count": len(online_users)},
                room=sid,
            )

    # Database storage methods removed - Socket.IO uses in-memory storage only
    # This provides better performance and simpler code for real-time presence

    async def get_connected_users(self):
        """Get all currently connected users"""
        connected_users = []
        for socket_id, user_data in self.connected_users.items():
            connected_users.append({
                "socket_id": socket_id,
                "user_id": user_data["user_id"],
                "username": user_data.get("username"),
                "full_name": user_data.get("full_name"),
                "avatar_url": user_data.get("avatar_url"),
                "connected_at": user_data.get("connected_at"),
                "last_activity": user_data.get("last_activity"),
                "is_online": True
            })
        return connected_users

    async def get_connection_stats(self):
        """Get connection statistics"""
        total_connections = len(self.connected_users)
        return {
            "total_connections": total_connections,
            "total_users": total_connections,
            "timestamp": datetime.utcnow().isoformat()
        }

# Create global instance
socket_manager = ChatSocketManager()
