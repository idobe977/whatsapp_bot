from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import json
import os
from project.api.routes import router as api_router
from project.api.webhook import router as webhook_router
from project.config import API_PREFIX
from project.utils.logger import logger
from project.services.whatsapp_service import WhatsAppService
from project.services.airtable_service import AirtableService

# Initialize FastAPI app
app = FastAPI(
    title="WhatsApp Survey Bot",
    description="API for managing WhatsApp surveys and responses",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Initialize services
whatsapp_service = None
airtable_service = None

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    global whatsapp_service, airtable_service
    try:
        # Initialize services
        airtable_service = AirtableService()
        whatsapp_service = WhatsAppService(
            instance_id=os.getenv("ID_INSTANCE"),
            api_token=os.getenv("API_TOKEN_INSTANCE")
        )
        
        # Start cleanup task for stale survey states
        await whatsapp_service.start_cleanup_task()
        
        logger.info("Services initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing services: {str(e)}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    if whatsapp_service and hasattr(whatsapp_service, 'cleanup_task'):
        whatsapp_service.cleanup_task.cancel()
    logger.info("Application shutdown complete")

# Include routers
app.include_router(api_router, prefix=API_PREFIX)
app.include_router(webhook_router, prefix=API_PREFIX)

# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Global error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    ) 
