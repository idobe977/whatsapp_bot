from fastapi import FastAPI, Request, HTTPException
import uvicorn
import logging
import os
from whatsapp_survey_bot import bot, handle_webhook

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - INFO - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request):
    """Handle incoming webhooks from Green API"""
    try:
        webhook_data = await request.json()
        logger.info(f"Received webhook: {webhook_data}")
        await handle_webhook(webhook_data)
        return {"status": "OK"}
    except Exception as e:
        logger.error(f"Error in webhook handler: {str(e)}")
        return {"status": "Error", "message": str(e)}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    # Get port from environment variable (Render.com sets this)
    port = int(os.environ.get("PORT", 8003))
    
    # Log the port being used
    logger.info(f"Starting server on port {port}")
    
    # Run the server
    uvicorn.run(app, host="0.0.0.0", port=port) 
