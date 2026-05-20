#!/usr/bin/env python3
import uvicorn
import os

if __name__ == "__main__":
    # Load environment variables from .env file if it exists
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("⚠️ python-dotenv not installed, skipping .env file loading")
    
    # Get port from environment or default to 8000
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    print(f"🚀 Starting Betting Monolithic Service on {host}:{port}")
    print(f"📖 API Documentation: http://{host}:{port}/docs")
    print(f"🔄 ReDoc Documentation: http://{host}:{port}/redoc")
    print(f"💡 To install dependencies: pip3 install -r requirements.txt")
    
    uvicorn.run(
        "main:socket_app",
        host=host,
        port=port,
        reload=True,  # Enable auto-reload for development
        log_level="info"
    ) 