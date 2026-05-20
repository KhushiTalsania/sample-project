from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pathlib import Path
from .routes import router as club_router
# from .pricing_routes import router as pricing_router
from .stripe_routes import router as stripe_router
from .club_picks_routes import router as club_picks_router
from .captain_revenue_routes import router as captain_revenue_router
from .db import init_db, check_db_health
# Import hub router lazily to avoid circular imports
hub_router = None
import asyncio

app = FastAPI(
    title="Betting Club Service",
    version="1.0.0",
    description="RESTful API for managing betting clubs with search, filter, and sort capabilities",
    docs_url="/docs",
    redoc_url="/redoc",
    # root_path="/club",
     swagger_ui_parameters={
        "persistAuthorization": True,  # Remember auth across page reloads
    },
)

# Custom exception handler for Pydantic validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors with user-friendly messages"""
    
    errors = []
    error_details = []
    
    for error in exc.errors():
        field_name = " -> ".join(str(loc) for loc in error["loc"][1:])  # Skip 'body' prefix
        field = error.get('loc', ['unknown'])[-1]  # Get the field name
        error_type = error["type"]
        error_message = error["msg"]
        
        # Clean up Pydantic error message prefixes
        if error_message.startswith("Value error, "):
            error_message = error_message.replace("Value error, ", "")
        
        input_value = error.get("input", "")
        
        # Create user-friendly error messages
        if field == 'name':
            if error_type == 'string_too_short':
                errors.append(f"Club name needs at least 3 characters (you have {len(input_value)})")
            elif error_type == 'string_too_long':
                errors.append(f"Club name is too long (max 100 characters)")
            elif error_type == 'string_type':
                errors.append("Club name must be text only")
            else:
                errors.append("Please enter a valid club name")
        
        elif field == 'description':
            if error_type == 'string_too_short':
                errors.append(f"Description needs at least 10 characters (you have {len(input_value)})")
            elif error_type == 'string_too_long':
                errors.append(f"Description is too long (max 500 characters)")
            elif error_type == 'string_type':
                errors.append("Description must be text only")
            else:
                errors.append("Please enter a valid description")
        
        elif field == 'sub_description':
            if error_type == 'string_too_short':
                errors.append(f"Subtitle needs at least 5 characters (you have {len(input_value)})")
            elif error_type == 'string_too_long':
                errors.append(f"Subtitle is too long (max 200 characters)")
            elif error_type == 'string_type':
                errors.append("Subtitle must be text only")
            else:
                errors.append("Please enter a valid subtitle")
        
        elif field == 'name_based_id':
            if error_type == 'string_type':
                errors.append("Club URL must be text only")
            else:
                errors.append("Please enter a valid club URL")
        
        elif field == 'result':
            # Use the cleaned error message from the validator
            errors.append(error_message)
        
        else:
            # Generic error message for other fields
            errors.append(f"Please check {field}")
        
        error_details.append({
            "field": field_name,
            "type": error_type,
            "message": error_message,
            "input": input_value
        })
    
    # Create user-friendly response
    if len(errors) == 1:
        message = errors[0]
    else:
        message = "Errors:\n• " + "\n• ".join(errors)
    
    # Return formatted error response
    return JSONResponse(
        status_code=422,
        content={
            "status_code": 422,
            "status": "error",
            "message": message,
            "data": None,
            "validation_errors": error_details
        }
    )

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://simbet.websitetestingbox.com",
        "http://simbet.websitetestingbox.com", 
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://localhost:8500",
        "http://127.0.0.1:8500",
        "http://localhost:8501",  # Club service port
        "http://127.0.0.1:8501"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

# Mount static files for uploaded images
uploads_dir = Path("uploads")
if uploads_dir.exists():
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
    print(f"📁 Static files mounted at /uploads from {uploads_dir.absolute()}")

# Include routers
app.include_router(club_router, prefix="/api/v1", tags=["Clubs"])
# app.include_router(pricing_router, prefix="/api/v1", tags=["Club Pricing & Membership"])
app.include_router(stripe_router, prefix="/api/v1", tags=["Stripe Integration"])
app.include_router(club_picks_router, prefix="/api/v1", tags=["Club Picks"])
app.include_router(captain_revenue_router, prefix="/api/v1/captain/revenue", tags=["Captain Revenue"])

# Hub endpoints are now integrated into the clubs router
print("ℹ️ Hub endpoints are integrated into the clubs router")

# Startup event to initialize database
@app.on_event("startup")
async def startup_event():
    """Initialize database connection and setup on startup"""
    print("🚀 Starting Betting Club Service...")
    success = await init_db()
    if success:
        print("✅ Club service initialized successfully")
        
        # Initialize hub database indexes (lazy initialization)
        print("ℹ️ Hub database indexes will be created on first use")
        
        # Initialize hub database indexes (lazy initialization)
        print("ℹ️ Hub database indexes will be created on first use")
    else:
        print("❌ Club service initialization failed")

# Health check endpoints
@app.get("/")
async def root():
    """Root endpoint with service information"""
    return {
        "message": "Betting Club Service API",
        "status": "running",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "api_base": "/api/v1"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    db_health = await check_db_health()
    return {
        "status": "healthy" if db_health["status"] == "healthy" else "unhealthy",
        "service": "betting-club-service",
        "database": db_health
    }

@app.get("/api/v1/health")
async def api_health_check():
    """API-specific health check"""
    db_health = await check_db_health()
    return {
        "api_status": "operational",
        "database_status": db_health["status"],
        "endpoints": {
            "clubs": "/api/v1/clubs",
            "search": "/api/v1/clubs/search",
            "my_clubs": "/api/v1/my-clubs",
            "stripe_pricing": "/api/v1/clubs/{club_id}/pricing-plans",
            "stripe_details": "/api/v1/clubs/{club_id}/stripe-pricing-details",
            "captain_summary": "/api/v1/captains/{captain_id}/stripe-pricing-summary",
            "stripe_webhook": "/api/v1/webhooks/stripe",
            "stripe_health": "/api/v1/stripe/health-check",
            "hub": {
                "create_hub": "/api/v1/hub/create-hub",
                "get_hub": "/api/v1/hub/{hub_id}",
                "get_hubs_by_club": "/api/v1/hub/club/{club_name_based_id}",
                "get_hubs_by_captain": "/api/v1/hub/captain/{captain_id}"
            },
            "picks": {
                "create_pick": "/api/v1/club-picks/",
                "get_club_picks": "/api/v1/club-picks/club/{club_id}",
                "get_pick": "/api/v1/club-picks/{pick_id}",
                "update_pick": "/api/v1/club-picks/{pick_id}",
                "delete_pick": "/api/v1/club-picks/{pick_id}",
                "get_statistics": "/api/v1/club-picks/club/{club_id}/statistics",
                "club_leaderboard": "/api/v1/club-picks/club/{club_id}/leaderboard",
                "global_leaderboard": "/api/v1/club-picks/leaderboard/global?search=term",
                "clubwise_leaderboard": "/api/v1/club-picks/leaderboard/clubwise?search=term",
                "upload_slip": "/api/v1/club-picks/upload-slip",
                "debug_clubs": "/api/v1/club-picks/debug/clubs"
            },
            "user": {
                "eligibility_status": "/api/v1/user/moderator-status"
            },
            "captain_revenue": {
                "comprehensive_stats": "/api/v1/captain/revenue/comprehensive-stats",
                "monthly_breakdown": "/api/v1/captain/revenue/monthly-breakdown?months=12",
                "club_breakdown": "/api/v1/captain/revenue/club-breakdown",
                "summary": "/api/v1/captain/revenue/summary",
                "recent_earnings": "/api/v1/captain/revenue/recent-earnings?page=1&limit=20",
                "export_csv": "/api/v1/captain/revenue/recent-earnings/export-csv",
                "monthwise_revenue": "/api/v1/captain/revenue/monthwise-revenue?year=2025&month=10&page=1&limit=12"
            }
        }
    } 