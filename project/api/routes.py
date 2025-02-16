from fastapi import FastAPI, Request
import traceback
from project.services.whatsapp_service import WhatsAppService
from project.utils.logger import logger
from project.api.webhook import handle_webhook_data
import os

app = FastAPI()

whatsapp = WhatsAppService(
    instance_id=os.getenv("ID_INSTANCE"),
    api_token=os.getenv("API_TOKEN_INSTANCE")
)

@app.post("/webhook")
async def webhook(request: Request):
    """Handle incoming webhook data"""
    try:
        webhook_data = await request.json()
        logger.info("Received new webhook")
        logger.debug(f"Webhook data: {webhook_data}")
        
        await handle_webhook_data(webhook_data, whatsapp)
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Error in webhook endpoint: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"} 
