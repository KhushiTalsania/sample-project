# # # socket_manager.py
# # import socketio
# # from datetime import datetime, timezone

# # # Create Socket.IO server
# # sio = socketio.AsyncServer(
# #     cors_allowed_origins="*",  # allow all origins for dev
# #     async_mode="asgi"
# # )

# # # Create ASGI app for /sports namespace
# # socket_app = socketio.ASGIApp(sio, socketio_path="/sports")

# # # Track connected clients
# # connected_clients = {}


# # @sio.event
# # async def connect(sid, environ):
# #     print(f"🟢 Client connected to /sports: {sid}")
# #     connected_clients[sid] = {"connected_at": datetime.now(timezone.utc).isoformat()}
# #     await sio.emit("connection_ack", {"message": "Connected to /sports successfully!"}, to=sid)


# # @sio.event
# # async def disconnect(sid):
# #     print(f"🔴 Client disconnected from /sports: {sid}")
# #     connected_clients.pop(sid, None)


# # # @sio.event
# # # async def join_club(sid, data):
# # #     """Frontend emits {club_id: 'abc123'} to join a specific club room"""
# # #     club_id = data.get("club_id")
# # #     if club_id:
# # #         await sio.save_session(sid, {"club_id": club_id})
# # #         await sio.enter_room(sid, club_id)
# # #         print(f"✅ Client {sid} joined club room: {club_id}")
# # #         await sio.emit("joined_club", {"club_id": club_id}, to=sid)


# # # @sio.event
# # # async def leave_club(sid, data):
# # #     """Frontend emits {club_id: 'abc123'} to leave the club room"""
# # #     club_id = data.get("club_id")
# # #     if club_id:
# # #         await sio.leave_room(sid, club_id)
# # #         print(f"🚪 Client {sid} left club room: {club_id}")



# # socket_manager.py
# import socketio
# from datetime import datetime, timezone

# # Create Socket.IO server
# sio = socketio.AsyncServer(
#     cors_allowed_origins="*",  # Configure properly for production
#     async_mode="asgi"
# )

# # Create ASGI app - the path here is the Socket.IO endpoint path
# socket_app = socketio.ASGIApp(sio, socketio_path="sports")

# # Track connected clients
# connected_clients = {}

# @sio.event
# async def connect(sid, environ, auth):
#     print(f"🟢 Client connected: {sid}")
#     # Verify token from auth
#     token = auth.get("token") if auth else None
#     if not token:
#         print(f"❌ No token provided for {sid}")
#         return False  # Reject connection
    
#     # TODO: Validate token here
    
#     connected_clients[sid] = {"connected_at": datetime.now(timezone.utc).isoformat()}
#     print(f"Connected clients: {connected_clients}")
#     await sio.emit("connection_ack", {"message": "Connected successfully!"}, to=sid)

# @sio.event
# async def disconnect(sid):
#     print(f"🔴 Client disconnected: {sid}")
#     connected_clients.pop(sid, None)

# @sio.event
# async def join_club(sid, data):
#     """Frontend emits {club_id: 'abc123'} to join a specific club room"""
#     club_id = data.get("club_id")
#     if club_id:
#         await sio.enter_room(sid, club_id)
#         print(f"✅ Client {sid} joined club room: {club_id}")
#         await sio.emit("joined_club", {"club_id": club_id}, to=sid)

# @sio.event
# async def leave_club(sid, data):
#     """Frontend emits {club_id: 'abc123'} to leave the club room"""
#     club_id = data.get("club_id")
#     if club_id:
#         await sio.leave_room(sid, club_id)
#         print(f"🚪 Client {sid} left club room: {club_id}")