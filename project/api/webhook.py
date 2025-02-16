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
            logger.debug(f"Full poll data: {poll_data}")
            
            # Get selected options
            selected_options = []
            if "votes" in poll_data:
                for vote in poll_data["votes"]:
                    if "optionVoters" in vote and chat_id in vote.get("optionVoters", []):
                        selected_options.append(vote["optionName"])
            
            if selected_options:
                selected_option = selected_options[0]
                logger.info(f"User {chat_id} selected option: {selected_option}")
                
                # Check if this is a trigger phrase for any survey
                trigger_found = False
                for survey in whatsapp.surveys:
                    logger.debug(f"Checking triggers for survey: {survey.name}")
                    for trigger in survey.trigger_phrases:
                        if trigger.lower() in selected_option.lower():
                            logger.info(f"Found matching trigger '{trigger}' in option '{selected_option}' for survey: {survey.name}")
                            trigger_found = True
                            break
                    if trigger_found:
                        break
                
                if trigger_found:
                    logger.info(f"Found trigger in option, handling as text message first")
                    # Handle as text first to trigger the survey
                    await whatsapp.handle_text_message(chat_id, selected_option, sender_contact_name or sender_name)
                else:
                    logger.info(f"No trigger found in option, checking if in active survey")
                    # Only handle as poll response if we're in an active survey
                    if chat_id in whatsapp.survey_state:
                        logger.info(f"User is in active survey, handling poll response")
                        await whatsapp.handle_poll_response(chat_id, poll_data)
                    else:
                        logger.info(f"User is not in active survey and no trigger found in option: {selected_option}")
            
    except Exception as e:
        logger.error(f"Error handling webhook data: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise 
