from fastapi import FastAPI, Request
from whatsapp_survey_bot import bot, handle_webhook
import uvicorn
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="WhatsApp Survey Bot")

@app.get("/")
async def root():
    return {
        "status": "WhatsApp Survey Bot is running",
        "version": "2.0",
        "endpoints": {
            "webhook": "/webhook"
        }
    }

@app.post("/webhook")
async def webhook(request: Request):
    try:
        webhook_data = await request.json()
        logger.info(f"Received webhook: {webhook_data}")
        await handle_webhook(webhook_data)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    logger.info("Starting WhatsApp Survey Bot server...")
    uvicorn.run(app, host="0.0.0.0", port=3000) 