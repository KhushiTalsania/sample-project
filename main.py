"""
Monolithic Betting Application

This is the main FastAPI application that consolidates all microservices
into a single monolithic architecture with centralized components.

Services included:
- Authentication Service
- Admin Service  
- Chat Service
- Club Service
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import logging
from datetime import datetime
import socketio

# Import centralized core components
from core.database.connection import initialize_database_manager, close_database_connections
from core.utils.response_utils import create_error_response, create_success_response
from core.utils.stripe_price import initialize_stripe_products
# Import service routers
from services.auth import router as auth_router
from services.admin.routes import router as admin_router
from services.chat.routes import router as chat_router
from services.club.routes import router as club_router
from services.club.club_picks_routes import router as club_picks_router
from services.club.my_picks_routes import router as my_picks_router
from services.notifications import router as notifications_router
from services.webhooks import router as webhooks_router
from services.club.captain_revenue_routes import router as captain_revenue_router
from services.sports.routes import router as sports_router
# from services.sports.socket_manager_sport import socket_app as sports_socket_app
# Import Socket.IO manager from core
from core.socket import socket_manager
from core.sports_mqtt_client import start_mqtt_background # Setup logging
import asyncio
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Handles startup and shutdown events for the monolithic application.
    """
    # Startup
    logger.info("🚀 Starting Monolithic Betting Application...")
    from core.utils.stripe_price import create_or_update_product
    
    print("🚀 App starting...")
    initialize_stripe_products()
    # loop = asyncio.get_event_loop()
    loop = asyncio.get_running_loop()
    start_mqtt_background(loop)

    
    try:
        # Initialize database connections
        db_manager = await initialize_database_manager()
        logger.info("✅ Database connections initialized")
        
        # Perform database health check
        health_status = await db_manager.health_check()
        for service, is_healthy in health_status.items():
            status_emoji = "✅" if is_healthy else "❌"
            logger.info(f"  {status_emoji} {service.title()} Database: {'Healthy' if is_healthy else 'Unhealthy'}")
        
        # Start trial expiration scheduler (cron job)
        try:
            from services.club.cron_scheduler import start_trial_expiration_scheduler
            start_trial_expiration_scheduler()
            logger.info("✅ Trial expiration scheduler started")
        except Exception as cron_error:
            logger.error(f"❌ Failed to start trial expiration scheduler: {cron_error}")
            # Don't fail the entire application if cron fails
        
        # Initialize Firebase Admin SDK for push notifications
        try:
            from services.notifications.firebase_config import initialize_firebase
            initialize_firebase()
            logger.info("✅ Firebase Admin SDK initialized for push notifications")
        except Exception as firebase_error:
            logger.error(f"❌ Failed to initialize Firebase Admin SDK: {firebase_error}")
            # Don't fail the entire application if Firebase initialization fails
        
        # Setup notification database indexes and verify collections
        try:
            from services.notifications.db_setup import create_notification_indexes, verify_notification_collections
            
            # Verify collections are accessible
            collection_status = await verify_notification_collections()
            logger.info("✅ Notification collections verified")
            
            # Create indexes
            await create_notification_indexes()
            logger.info("✅ Notification database indexes created")
            
        except Exception as db_error:
            logger.error(f"❌ Failed to setup notification database: {db_error}")
            # Don't fail the entire application if database setup fails
        
        # # Initialize Sports MQTT client for live scores (optional - lazy connection on demand)
        # try:
        #     from core.sports_mqtt_client import get_sports_mqtt_client
        #     # Note: We don't connect immediately, but initialize on first WebSocket connection
        #     # This allows the app to start even if MQTT credentials are not configured
        #     mqtt_client = get_sports_mqtt_client()
        #     logger.info("✅ Sports MQTT client initialized (will connect on demand)")
        # except Exception as mqtt_error:
        #     logger.warning(f"⚠️ Failed to initialize Sports MQTT client: {mqtt_error}")
        #     # Don't fail the entire application if MQTT initialization fails
        
        # # Start heartbeat task for /sports namespace
        # try:
        #     from core.socket import socket_manager
        #     import asyncio
            
        #     # Create the heartbeat task - it runs continuously in the background
        #     heartbeat_task = asyncio.create_task(socket_manager._sports_heartbeat_task())
        #     logger.info("✅ Sports heartbeat task started (emits every 30 seconds)")
        # except Exception as heartbeat_error:
        #     logger.warning(f"⚠️ Failed to start sports heartbeat task: {heartbeat_error}")
        
        # logger.info("🎉 Monolithic application started successfully!")
        
    except Exception as e:
        logger.error(f"❌ Failed to start application: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Monolithic Betting Application...")
    
    try:
        # Stop trial expiration scheduler
        try:
            from services.club.cron_scheduler import stop_trial_expiration_scheduler
            stop_trial_expiration_scheduler()
            logger.info("✅ Trial expiration scheduler stopped")
        except Exception as cron_error:
            logger.error(f"❌ Error stopping trial expiration scheduler: {cron_error}")
        
        await close_database_connections()
        logger.info("✅ Database connections closed")
        
        # Disconnect Sports MQTT client
        # try:
        #     from core.sports_mqtt_client import get_sports_mqtt_client
        #     mqtt_client = get_sports_mqtt_client()
        #     if mqtt_client.is_connected():
        #         mqtt_client.disconnect()
        #         logger.info("✅ Sports MQTT client disconnected")
        # except Exception as mqtt_error:
        #     logger.warning(f"⚠️ Error disconnecting Sports MQTT client: {mqtt_error}")
    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")
    
    logger.info("👋 Application shutdown complete")

# Create FastAPI application with lifespan management
app = FastAPI(
    title="Betting Monolithic Service",
    description="Unified monolithic application combining all betting services",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    swagger_ui_parameters={
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "filter": True,
        "showExtensions": True,
        "showCommonExtensions": True,
    },
    lifespan=lifespan
)

# ========================================
# MIDDLEWARE CONFIGURATION
# ========================================

# CORS middleware with comprehensive configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)
# Mount Socket.IO with /ws/sports endpoint
# Mount at /ws, and socketio_path="/sports" makes it /ws/sports
# app.mount("/ws", sports_socket_app)
# ========================================
# EXCEPTION HANDLERS
# ========================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handle validation errors with detailed, user-friendly messages.
    """
    logger.warning(f"🔍 Validation error on {request.url}: {exc}")
    
    if exc.errors():
        first_error = exc.errors()[0]
        field_name = first_error["loc"][-1] if first_error["loc"] else "field"
        error_type = first_error["type"]
        error_msg = first_error.get("msg", "Validation failed")
        
        # Clean up Pydantic error message prefixes
        if error_msg.startswith("Value error, "):
            error_msg = error_msg.replace("Value error, ", "")
        
        # Customize error messages for better UX
        if isinstance(field_name, str) and "password" in field_name.lower():
            if "string_too_short" in error_type:
                return create_error_response(
                    "Password should have at least 8 characters",
                    error="validation_failed",
                    status_code=422
                )
            elif "value_error" in error_type:
                return create_error_response(
                    error_msg,
                    error="validation_failed", 
                    status_code=422
                )
        
        # Handle other validation errors
        if "string_too_short" in error_type:
            min_length = first_error.get("ctx", {}).get("min_length", 0)
            return create_error_response(
                f"{field_name.replace('_', ' ').title()} should have at least {min_length} characters",
                error="validation_failed",
                status_code=422
            )
        elif "string_too_long" in error_type:
            max_length = first_error.get("ctx", {}).get("max_length", 0)
            return create_error_response(
                f"{field_name.replace('_', ' ').title()} should have at most {max_length} characters",
                error="validation_failed",
                status_code=422
            )
        else:
            return create_error_response(
                error_msg,
                error="validation_failed",
                status_code=422
            )
    
    return create_error_response(
        "Invalid request data",
        error="validation_failed",
        status_code=422
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Handle HTTP exceptions with consistent formatting.
    """
    logger.warning(f"🔍 HTTP exception on {request.url}: {exc.status_code} - {exc.detail}")
    
    # Return proper error response for all HTTP exceptions
    return create_error_response(
        str(exc.detail),
        error="http_error",
        status_code=exc.status_code
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """
    Handle unexpected exceptions with proper logging.
    """
    logger.error(f"🔍 Unexpected error on {request.url}: {type(exc).__name__} - {str(exc)}")
    
    return create_error_response(
        "Internal server error occurred",
        error="internal_error", 
        status_code=500
    )

# ========================================
# SERVICE ROUTERS
# ========================================

# Include service routers
app.include_router(auth_router, tags=["Authentication"])
app.include_router(admin_router, prefix="/admin", tags=["Administration"]) 
app.include_router(chat_router, prefix="/chat/api/v1")
app.include_router(club_router, prefix="/club/api/v1", tags=["Clubs"])
app.include_router(club_picks_router, prefix="/club/api/v1", tags=["Club Picks"])
app.include_router(my_picks_router, prefix="/api/v1", tags=["My Picks"])
app.include_router(notifications_router, prefix="/api/v1", tags=["Notifications"])
app.include_router(webhooks_router, prefix="/api/v1", tags=["Webhooks"])
app.include_router(captain_revenue_router, prefix="/club/api/v1", tags=["Captain Revenue"])
app.include_router(sports_router, tags=["Sports"])

# Create Socket.IO ASGI app
socket_app = socketio.ASGIApp(socket_manager.sio, app)

# ========================================
# STATIC FILES
# ========================================

# Mount static files for payment pages and other assets
# Mount uploads directory for file serving
uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
if os.path.exists(uploads_dir):
    app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")
    app.mount("/admin/uploads", StaticFiles(directory=uploads_dir), name="admin-uploads")
    logger.info(f"📁 Upload files mounted from: {uploads_dir}")
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    logger.info(f"📁 Static files mounted from: {static_dir}")

# ========================================
# ROOT ENDPOINTS
# ========================================

@app.get("/")
async def root():
    """Root endpoint with service information."""
    return create_success_response(
        "Betting Monolithic Service API - All Services Integrated",
        data={
            "version": "1.0.0",
            "services": {
                "auth": {
                    "description": "Authentication and user management",
                    "endpoints": 24,
                    "features": ["JWT Auth", "OTP Login", "Social Login", "Trial Management"]
                },
                "admin": {
                    "description": "Administrative functions",
                    "endpoints": 30,
                    "features": ["User Management", "Club Management", "Analytics", "Audit Logs"]
                },
                "chat": {
                    "description": "Real-time chat functionality",
                    "endpoints": 15,
                    "features": ["WebSocket", "File Upload", "Reactions", "Moderation"]
                },
                "club": {
                    "description": "Club and membership management",
                    "endpoints": 25,
                    "features": ["Club Creation", "Membership", "Payments", "Performance Tracking"]
                },
                "notifications": {
                    "description": "Push notification management",
                    "endpoints": 12,
                    "features": ["FCM Push Notifications", "Device Token Management", "Notification History", "Preferences"]
                },
                "sports": {
                    "description": "Sports and leagues data integration",
                    "endpoints": 1,
                    "features": ["TheSports API Integration", "League Data", "Sport Competitions"]
                }
            },
            "total_endpoints": 107,
            "architecture": "monolithic",
            "converted_from": "microservices",
            "centralized_components": [
                "Database Manager", "JWT Handler", "Password Utils", "Email Service",
                "SMS Service", "File Utils", "Validation Utils", "Response Utils"
            ]
        }
    )

@app.get("/health")
async def health_check():
    """
    Comprehensive health check for all services and dependencies.
    """
    from core.database import get_database_manager
    
    try:
        db_manager = get_database_manager()
        db_health = await db_manager.health_check()
        
        # Calculate overall health
        all_healthy = all(db_health.values())
        
        health_data = {
            "status": "healthy" if all_healthy else "degraded",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "services": {
                "auth": "operational",
                "admin": "operational", 
                "chat": "operational",
                "club": "operational"
            },
            "databases": db_health,
            "overall": "operational" if all_healthy else "degraded"
        }
        
        status_code = 200 if all_healthy else 503
        message = "All services operational" if all_healthy else "Some services degraded"
        
        return create_success_response(
            message,
            data=health_data,
            status_code=status_code
        )
        
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return create_error_response(
            "Health check failed",
            error="health_check_error",
            status_code=503,
            data={"error_details": str(e)}
        )

@app.get("/socketio/health")
async def socketio_health():
    """Socket.IO specific health check"""
    connected_users = len(socket_manager.connected_users)

    return create_success_response(
        "Socket.IO service operational",
        data={
            "status": "operational",
            "connected_users": connected_users,
            "endpoint": "/socket.io/",
            "features": [
                "Real-time messaging",
                "User authentication",
                "User presence",
                "Connected users tracking",
            ],
        },
    )

@app.get("/socketio/stats")
async def socketio_stats():
    """Get Socket.IO connection statistics"""
    connected_users = len(socket_manager.connected_users)

    return create_success_response(
        "Socket.IO statistics retrieved",
        data={
            "total_connections": connected_users,
            "total_users": connected_users,
            "connected_users": list(socket_manager.connected_users.keys()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )

@app.get("/info")
async def service_info():
    """
    Detailed service information and capabilities.
    """
    return create_success_response(
        "Service information retrieved successfully",
        data={
            "application": "Betting Monolithic Service",
            "version": "1.0.0",
            "architecture": "monolithic",
            "converted_from": "microservices",
            "features": {
                "centralized_database": "Unified database connections across all services",
                "centralized_auth": "Shared authentication and authorization",
                "centralized_utils": "Common utilities and helpers",
                "standardized_responses": "Consistent API response format",
                "comprehensive_logging": "Unified logging across all services"
            },
            "endpoints": {
                "documentation": "/docs",
                "redoc": "/redoc", 
                "health": "/health",
                "info": "/info"
            }
        }
    ) 