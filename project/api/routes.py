from fastapi import FastAPI, Request
import traceback
from project.services.whatsapp_service import WhatsAppService
from project.utils.logger import logger
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
        
        if webhook_data["typeWebhook"] != "incomingMessageReceived":
            logger.debug(f"Ignoring webhook of type: {webhook_data['typeWebhook']}")
            return {"status": "ok"}

        message_data = webhook_data["messageData"]
        sender_data = webhook_data["senderData"]
        chat_id = sender_data["chatId"]
        
        # Ignore group chats
        if not chat_id.endswith("@c.us"):
            logger.info(f"Ignoring group chat message from {chat_id}")
            return {"status": "ok"}
            
        sender_name = sender_data.get("senderName", "")
        
        logger.info(f"Processing message from {chat_id} ({sender_name})")
        logger.debug(f"Message type: {message_data['typeMessage']}")

        if message_data["typeMessage"] == "textMessage":
            text = message_data["textMessageData"]["textMessage"]
            logger.info(f"Received text message: {text[:100]}...")  # Log first 100 chars
            await whatsapp.handle_text_message(chat_id, text, sender_name)
            
        elif message_data["typeMessage"] == "audioMessage":
            voice_url = message_data["fileMessageData"]["downloadUrl"]
            logger.info(f"Received voice message from URL: {voice_url}")
            await whatsapp.handle_voice_message(chat_id, voice_url)
            
        elif message_data["typeMessage"] == "pollUpdateMessage":
            poll_data = message_data["pollMessageData"]
            logger.info("Received poll update")
            logger.debug(f"Poll data: {poll_data}")
            await whatsapp.handle_poll_response(chat_id, poll_data)
            
        return {"status": "ok"}
            
    except Exception as e:
        logger.error(f"Error handling webhook: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"} 
