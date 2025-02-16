from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from typing import Dict, Any
import json
from project.utils.logger import logger
from project.services.whatsapp_service import WhatsAppService
from project.main import whatsapp_service

router = APIRouter()

@router.post("/webhook")
async def webhook_handler(request: Request, background_tasks: BackgroundTasks):
    """Handle incoming WhatsApp webhook events"""
    try:
        # Validate webhook data
        if not whatsapp_service:
            raise HTTPException(status_code=500, detail="WhatsApp service not initialized")
            
        # Get webhook data
        webhook_data = await request.json()
        logger.debug(f"Received webhook data: {json.dumps(webhook_data, ensure_ascii=False)}")
        
        # Extract message details
        message_data = webhook_data.get('messageData', {})
        message_type = message_data.get('typeMessage')
        
        if not message_type:
            return {"status": "ignored"}
        
        # Get chat details
        chat_id = webhook_data.get('senderData', {}).get('chatId')
        sender_name = webhook_data.get('senderData', {}).get('senderName', '')
        
        if not chat_id:
            logger.error("No chat ID in webhook data")
            return {"status": "error", "detail": "No chat ID provided"}
        
        # Process different message types
        if message_type == 'textMessage':
            text = message_data.get('textMessageData', {}).get('textMessage', '')
            if text:
                background_tasks.add_task(
                    whatsapp_service.handle_text_message,
                    chat_id,
                    text,
                    sender_name
                )
                
        elif message_type == 'extendedTextMessage':
            text = message_data.get('extendedTextMessageData', {}).get('text', '')
            if text:
                background_tasks.add_task(
                    whatsapp_service.handle_text_message,
                    chat_id,
                    text,
                    sender_name
                )
                
        elif message_type == 'voiceMessage':
            voice_url = message_data.get('downloadUrl')
            if voice_url:
                background_tasks.add_task(
                    whatsapp_service.handle_voice_message,
                    chat_id,
                    voice_url
                )
                
        elif message_type == 'pollMessageData':
            poll_data = message_data.get('pollMessageData', {})
            if poll_data:
                background_tasks.add_task(
                    whatsapp_service.handle_poll_response,
                    chat_id,
                    poll_data
                )
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Error processing webhook") 