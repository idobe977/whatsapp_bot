from typing import Dict
from project.services.whatsapp_service import WhatsAppService
from project.utils.logger import logger
import traceback

async def handle_webhook_data(webhook_data: Dict, whatsapp: WhatsAppService) -> None:
    """Process incoming webhook data"""
    try:
        if webhook_data["typeWebhook"] != "incomingMessageReceived":
            logger.debug(f"Ignoring webhook of type: {webhook_data['typeWebhook']}")
            return

        message_data = webhook_data["messageData"]
        sender_data = webhook_data["senderData"]
        chat_id = sender_data["chatId"]
        
        # Ignore group chats
        if not chat_id.endswith("@c.us"):
            logger.info(f"Ignoring group chat message from {chat_id}")
            return
            
        sender_name = sender_data.get("senderName", "")
        sender_contact_name = sender_data.get("senderContactName", "")
        
        logger.info(f"Processing message from {chat_id} ({sender_name})")
        logger.debug(f"Message type: {message_data['typeMessage']}")

        if message_data["typeMessage"] == "textMessage":
            text = message_data["textMessageData"]["textMessage"]
            logger.info(f"Received text message: {text[:100]}...")  # Log first 100 chars
            await whatsapp.handle_text_message(chat_id, text, sender_contact_name or sender_name)
            
        elif message_data["typeMessage"] == "audioMessage":
            voice_url = message_data["fileMessageData"]["downloadUrl"]
            logger.info(f"Received voice message from URL: {voice_url}")
            await whatsapp.handle_voice_message(chat_id, voice_url)
            
        elif message_data["typeMessage"] == "pollUpdateMessage":
            poll_data = message_data["pollMessageData"]
            logger.info("Received poll update")
            logger.debug(f"Poll data: {poll_data}")
            
            # Get selected options
            selected_options = []
            if "votes" in poll_data:
                for vote in poll_data["votes"]:
                    if "optionVoters" in vote and chat_id in vote.get("optionVoters", []):
                        selected_options.append(vote["optionName"])
            
            if selected_options:
                selected_option = selected_options[0]
                logger.info(f"Selected option: {selected_option}")
                
                # First check if the selected option triggers a survey
                # This needs to happen before handling the poll response
                # because handle_text_message might start a new survey
                await whatsapp.handle_text_message(chat_id, selected_option, sender_contact_name or sender_name)
                
                # Only handle poll response if we're in an active survey
                # This prevents the "unknown chat_id" warning
                if chat_id in whatsapp.survey_state:
                    logger.info(f"Processing poll response for active survey")
                    await whatsapp.handle_poll_response(chat_id, poll_data)
                else:
                    logger.info(f"No active survey for {chat_id}, skipping poll response handling")
            
    except Exception as e:
        logger.error(f"Error handling webhook data: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise 
