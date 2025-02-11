from typing import Dict
from ..services.whatsapp_service import WhatsAppService
from ..utils.logger import logger

async def handle_webhook_data(webhook_data: Dict, whatsapp: WhatsAppService) -> None:
    """Process incoming webhook data"""
    try:
        if webhook_data["typeWebhook"] != "incomingMessageReceived":
            logger.debug(f"Ignoring webhook of type: {webhook_data['typeWebhook']}")
            return

        message_data = webhook_data["messageData"]
        sender_data = webhook_data["senderData"]
        chat_id = sender_data["chatId"]
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
            
    except Exception as e:
        logger.error(f"Error handling webhook data: {str(e)}")
        raise 