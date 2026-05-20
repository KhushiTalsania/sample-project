from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from .routes.registration import router as registration_router
from .routes.login import router as login_router
from .routes.email_login import router as email_login_router
from .routes.password_reset import router as password_reset_router
from .routes.social_login import router as social_login_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from .routes.trial_membership import router as trial_membership_router
from .routes.moderator_membership import router as moderator_membership_router

# from .routes.webhooks import router as webhook_router
import os

app = FastAPI(
    title="Betting Auth Service",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    swagger_ui_parameters={
        "persistAuthorization": True,  # Remember auth across page reloads
    },
    # root_path="/auth"
    # openapi_url="/openapi.json",
)

# ✅ COMPLETE CORS CONFIGURATION
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
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)


# Custom validation error handler for better error messages
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(f"🔍 Validation error handler called: {exc}")

    # Extract the first validation error for a cleaner message
    if exc.errors():
        first_error = exc.errors()[0]
        field_name = first_error["loc"][-1] if first_error["loc"] else "field"
        error_type = first_error["type"]
        error_msg = first_error.get("msg", "Validation failed")
        
        # Clean up Pydantic error message prefixes
        if error_msg.startswith("Value error, "):
            error_msg = error_msg.replace("Value error, ", "")

        # Customize error messages for better user experience
        if "password" in field_name.lower():
            if "string_too_short" in error_type:
                return JSONResponse(
                    status_code=422,
                    content={
                        "message": "Password should have at least 8 characters",
                        "error": "validation_failed",
                        "field": field_name,
                    },
                )
            elif "value_error" in error_type:
                # Use the cleaned error message from the validator
                return JSONResponse(
                    status_code=422,
                    content={
                        "message": error_msg,
                        "error": "validation_failed",
                        "field": field_name,
                    },
                )

        # For other fields, provide clean messages based on error type
        if "string_too_short" in error_type:
            min_length = first_error.get("ctx", {}).get("min_length", 0)
            return JSONResponse(
                status_code=422,
                content={
                    "message": f"{field_name.replace('_', ' ').title()} should have at least {min_length} characters",
                    "error": "validation_failed",
                    "field": field_name,
                },
            )
        elif "string_too_long" in error_type:
            max_length = first_error.get("ctx", {}).get("max_length", 0)
            return JSONResponse(
                status_code=422,
                content={
                    "message": f"{field_name.replace('_', ' ').title()} should have at most {max_length} characters",
                    "error": "validation_failed",
                    "field": field_name,
                },
            )
        elif "value_error" in error_type:
            # Use the cleaned validator message
            return JSONResponse(
                status_code=422,
                content={
                    "message": error_msg,
                    "error": "validation_failed",
                    "field": field_name,
                },
            )
        else:
            # For other error types, provide a generic but clean message
            return JSONResponse(
                status_code=422,
                content={
                    "message": f"{field_name.replace('_', ' ').title()} validation failed",
                    "error": "validation_failed",
                    "field": field_name,
                },
            )

    # Fallback for unexpected validation errors
    return JSONResponse(
        status_code=422,
        content={"message": "Invalid request data", "error": "validation_failed"},
    )


# Custom exception handler to format error messages
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    print(f"🔍 Global exception handler called for {exc.status_code}: {exc.detail}")

    # For 403 errors, let the route handle them (they have custom formatting)
    if exc.status_code == 403:
        print(f"⚠️ 403 error - letting route handle it: {exc.detail}")
        # Re-raise to let the route handle it
        raise exc

    # For other HTTP exceptions, return standard format
    print(f"⚠️ Handling other HTTP error: {exc.status_code} - {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# Also catch general exceptions to see what's happening
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    print(f"🔍 General exception handler called: {type(exc).__name__} - {str(exc)}")
    return JSONResponse(
        status_code=500, content={"detail": f"Internal server error: {str(exc)}"}
    )


# Include routers
app.include_router(registration_router, prefix="/auth", tags=["Registration"])
app.include_router(login_router, prefix="/auth", tags=["OTP Login"])
app.include_router(email_login_router, prefix="/auth", tags=["Email Login"])
app.include_router(password_reset_router, prefix="/auth", tags=["Password Reset"])
app.include_router(social_login_router, tags=["Social Login"])
app.include_router(trial_membership_router, tags=["Trial Membership"])
app.include_router(moderator_membership_router, tags=["Moderator Membership"])
# app.include_router(webhook_router, tags=["Webhooks"])

# Mount static files
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)))
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Serve HTML files directly
from fastapi.responses import FileResponse

# @app.get("/payment_success.html")
# async def payment_success():
#     return FileResponse(os.path.join(static_dir, "payment_success.html"))

# @app.get("/payment_cancel.html")
# async def payment_cancel():
#     return FileResponse(os.path.join(static_dir, "payment_cancel.html"))


# Root endpoint
@app.get("/")
async def root():
    return {"message": "Betting Auth Service API", "status": "running"}
