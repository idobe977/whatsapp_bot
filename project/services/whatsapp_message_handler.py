import asyncio
import json
import traceback
from typing import Dict, List, Optional
from datetime import datetime
from project.utils.logger import logger
from project.models.survey import SurveyDefinition
from .whatsapp_base_service import WhatsAppBaseService
import re

class WhatsAppMessageHandler(WhatsAppBaseService):
    async def handle_text_message(self, chat_id: str, text: str, sender_name: str = "") -> None:
        """Handle incoming text messages"""
        try:
            logger.info(f"Processing text message from {chat_id} (sender: {sender_name})")
            logger.debug(f"Message content: {text[:100]}...")  # Log first 100 chars
            
            # Check for stop phrases
            stop_phrases = ["הפסקת שאלון", "בוא נפסיק"]
            if chat_id in self.survey_state and any(phrase in text.lower() for phrase in stop_phrases):
                logger.info(f"User requested to stop survey: {chat_id}")
                await self.send_message_with_retry(chat_id, "השאלון הופסק. תודה על ההשתתפות!")
                
                # Update Airtable status
                state = self.survey_state[chat_id]
                await self.update_airtable_record(
                    state["record_id"],
                    {"סטטוס": "בוטל"},
                    state["survey"]
                )
                
                # Clean up state
                del self.survey_state[chat_id]
                return
            
            # First check if user is in middle of a survey
            if chat_id in self.survey_state:
                state = self.survey_state[chat_id]
                # Process as answer to current question
                await self.process_survey_answer(chat_id, {"type": "text", "content": text})
                return

            # If not in survey, check for trigger phrase
            for survey in self.surveys:
                logger.debug(f"Checking triggers for survey: {survey.name}")
                
                for trigger in survey.trigger_phrases:
                    if trigger.lower() in text.lower():
                        logger.info(f"Found trigger phrase '{trigger}' for survey: {survey.name}")
                        
                        # Create initial record in Airtable
                        record_id = self.create_initial_record(chat_id, sender_name, survey)
                        if record_id:
                            # Initialize survey state
                            self.survey_state[chat_id] = {
                                "current_question": 0,
                                "answers": {},
                                "record_id": record_id,
                                "survey": survey,
                                "last_activity": datetime.now()
                            }
                            
                            # Send welcome message
                            await self.send_message_with_retry(chat_id, survey.messages["welcome"])
                            await asyncio.sleep(1.5)  # Add a small delay between messages
                            
                            # Send first question
                            await self.send_next_question(chat_id)
                        else:
                            await self.send_message_with_retry(
                                chat_id, 
                                "מצטערים, הייתה שגיאה בהתחלת השאלון. נא לנסות שוב."
                            )
                        return
            
            logger.info(f"No trigger phrases found in message from {chat_id}")
            
        except Exception as e:
            logger.error(f"Error handling text message: {str(e)}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד ההודעה. נא לנסות שוב.")

    async def handle_file_message(self, chat_id: str, message_data: Dict) -> None:
        """Handle incoming file messages"""
        try:
            logger.info(f"Processing file message from {chat_id}")
            logger.debug(f"File message data: {json.dumps(message_data, ensure_ascii=False)}")

            # Check if user is in middle of a survey
            if chat_id not in self.survey_state:
                logger.info(f"Received file from {chat_id} but not in survey")
                return

            state = self.survey_state[chat_id]
            state['last_activity'] = datetime.now()
            current_question = state["survey"].questions[state["current_question"]]

            # Check if current question expects a file
            if current_question["type"] != "file":
                logger.info(f"Received file but current question type is {current_question['type']}")
                return

            # Get file data
            file_data = message_data.get("fileMessageData", {})
            mime_type = file_data.get("mimeType")
            file_size = len(file_data.get("file", "")) if "file" in file_data else None
            download_url = file_data.get("downloadUrl")

            # Validate file type
            allowed_types = current_question.get("allowed_types", ["any"])
            if "any" not in allowed_types:
                valid_mime_types = []
                for file_type in allowed_types:
                    valid_mime_types.extend(self.ALLOWED_FILE_TYPES.get(file_type, []))
                
                if mime_type not in valid_mime_types:
                    await self.send_message_with_retry(
                        chat_id, 
                        state["survey"].messages["file_upload"]["invalid_type"].format(
                            allowed_types=", ".join(allowed_types)
                        )
                    )
                    return

            # Validate file size
            if file_size and file_size > self.MAX_FILE_SIZE:
                await self.send_message_with_retry(
                    chat_id,
                    state["survey"].messages["file_upload"]["too_large"]
                )
                return

            # Save file data to Airtable
            file_info = {
                "url": download_url,
                "mime_type": mime_type,
                "file_name": file_data.get("fileName", ""),
                "caption": file_data.get("caption", "")
            }

            # Update Airtable
            if await self.update_airtable_record(
                state["record_id"],
                {current_question["field"]: json.dumps(file_info)},
                state["survey"]
            ):
                # Send success message
                await self.send_message_with_retry(
                    chat_id,
                    state["survey"].messages["file_upload"]["success"]
                )

                # Move to next question
                state["current_question"] += 1
                await self.send_next_question(chat_id)
            else:
                await self.send_message_with_retry(
                    chat_id,
                    "מצטערים, הייתה שגיאה בשמירת הקובץ. נא לנסות שוב."
                )

        except Exception as e:
            logger.error(f"Error handling file message: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד הקובץ. נא לנסות שוב.")

    async def handle_voice_message(self, chat_id: str, voice_url: str) -> None:
        """Handle incoming voice messages"""
        if chat_id not in self.survey_state:
            return

        try:
            state = self.survey_state[chat_id]
            state['last_activity'] = datetime.now()
            survey = state["survey"]
            current_question = survey.questions[state["current_question"]]
            question_id = current_question["id"]

            # Do the transcription
            transcribed_text = await self.transcribe_voice(voice_url)
            if not transcribed_text or transcribed_text in ["שגיאה בהורדת הקובץ הקולי", "שגיאה בתהליך התמלול"]:
                await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בתמלול ההקלטה. נא לנסות שוב.")
                return
            
            # Save to Airtable
            update_data = {
                current_question["id"]: transcribed_text,
                "סטטוס": "בטיפול"
            }
            
            try:
                if await self.update_airtable_record(state["record_id"], update_data, survey):
                    logger.info(f"Saved transcription for question {current_question['id']}")
                    
                    # Move to next question without generating reflection here
                    # (reflection will be generated in process_survey_answer)
                    await self.process_survey_answer(chat_id, {
                        "type": "voice",
                        "content": transcribed_text,
                        "original_url": voice_url,
                        "is_final": True
                    })
                else:
                    logger.error("Failed to save transcription to Airtable")
                    await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בשמירת התשובה. נא לנסות שוב.")
            except Exception as airtable_error:
                logger.error(f"Airtable error: {str(airtable_error)}")
                await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בשמירת התשובה באירטייבל. נא לנסות שוב.")

        except Exception as e:
            logger.error(f"Error handling voice message: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד ההודעה הקולית. נא לנסות שוב.")

    async def handle_poll_response(self, chat_id: str, poll_data: Dict) -> None:
        """Handle poll response"""
        try:
            logger.info(f"Processing poll response from {chat_id}")
            logger.debug(f"Poll data: {json.dumps(poll_data, ensure_ascii=False)}")
            
            # Get selected options
            selected_options = []
            if "votes" in poll_data:
                for vote in poll_data["votes"]:
                    if "optionVoters" in vote and chat_id in vote.get("optionVoters", []):
                        selected_options.append(vote["optionName"])
            
            if not selected_options:
                logger.warning(f"No valid options selected for chat_id: {chat_id}")
                return
                
            selected_option = selected_options[0]
            logger.info(f"Selected option: {selected_option}")

            # Check if user is in middle of a survey
            if chat_id in self.survey_state:
                state = self.survey_state[chat_id]
                state['last_activity'] = datetime.now()
                
                # Check if this is a meeting scheduler response
                scheduler_state = state.get('meeting_scheduler')
                if scheduler_state:
                    if scheduler_state.get('selected_date') is None:
                        await self.handle_meeting_date_selection(chat_id, selected_option)
                    else:
                        await self.handle_meeting_time_selection(chat_id, selected_option)
                    return
                
                # Regular poll handling for survey
                current_question = state["survey"].questions[state["current_question"]]
                question_id = current_question["id"]
                
                if current_question["type"] == "poll":
                    await self.process_poll_answer(chat_id, selected_option, question_id)
                    return
            
            # If not in survey, check if selected option is a trigger phrase
            for survey in self.surveys:
                if selected_option in survey.trigger_phrases:
                    logger.info(f"Found trigger phrase '{selected_option}' for survey: {survey.name}")
                    
                    # Create initial record in Airtable
                    record_id = self.create_initial_record(chat_id, "", survey)
                    if record_id:
                        # Initialize survey state
                        self.survey_state[chat_id] = {
                            "current_question": 0,
                            "answers": {},
                            "record_id": record_id,
                            "survey": survey,
                            "last_activity": datetime.now()
                        }
                        
                        # Send welcome message
                        await self.send_message_with_retry(chat_id, survey.messages["welcome"])
                        await asyncio.sleep(1.5)
                        
                        # Send first question
                        await self.send_next_question(chat_id)
                    else:
                        await self.send_message_with_retry(
                            chat_id, 
                            "מצטערים, הייתה שגיאה בהתחלת השאלון. נא לנסות שוב."
                        )
                    return
                    
            logger.info(f"Selected option '{selected_option}' is not a trigger phrase")
            
        except Exception as e:
            logger.error(f"Error handling poll response: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד התשובה. נא לנסות שוב.")

    async def process_poll_answer(self, chat_id: str, answer_content: str, question_id: str) -> None:
        """Process poll answer and update Airtable"""
        try:
            state = self.survey_state[chat_id]
            survey = state["survey"]
            
            # Clean the answer by removing emojis and special characters
            cleaned_answer = answer_content
            for emoji in ["⚡", "⏱️", "⏰", "😊", "🙈", "🎁", "🎉"]:
                cleaned_answer = cleaned_answer.replace(emoji, "")
            cleaned_answer = cleaned_answer.strip()
            
            # Get the original options from the question
            current_question = survey.questions[state["current_question"]]
            if current_question["type"] == "poll" and "options" in current_question:
                # Find the matching original option
                original_option = next(
                    (opt for opt in current_question["options"] 
                     if self.clean_text_for_airtable(opt) == cleaned_answer),
                    cleaned_answer
                )
                cleaned_answer = original_option
            
            # Update Airtable with the cleaned answer
            await self.update_airtable_record(
                state["record_id"],
                {question_id: cleaned_answer},
                survey
            )
            
            # Process flow logic if this is the last question
            if "flow" in current_question:
                flow = current_question["flow"]
                if "if" in flow and flow["if"]["answer"] == cleaned_answer:
                    if "say" in flow["if"]["then"]:
                        message = flow["if"]["then"]["say"]
                        # Replace Airtable field placeholders
                        if "{{" in message and "}}" in message:
                            placeholders = re.findall(r'\{\{(.*?)\}\}', message)
                            for field_name in placeholders:
                                field_value = await self.get_airtable_field_value(state["record_id"], field_name, survey)
                                if field_value:
                                    message = message.replace(f"{{{{{field_name}}}}}", str(field_value))
                        
                        await self.send_message_with_retry(chat_id, message)
                        await asyncio.sleep(1.5)
                elif "else_if" in flow:
                    for else_if in flow["else_if"]:
                        if else_if["answer"] == cleaned_answer:
                            if "say" in else_if["then"]:
                                message = else_if["then"]["say"]
                                # Replace Airtable field placeholders
                                if "{{" in message and "}}" in message:
                                    placeholders = re.findall(r'\{\{(.*?)\}\}', message)
                                    for field_name in placeholders:
                                        field_value = await self.get_airtable_field_value(state["record_id"], field_name, survey)
                                        if field_value:
                                            message = message.replace(f"{{{{{field_name}}}}}", str(field_value))
                                
                                await self.send_message_with_retry(chat_id, message)
                                await asyncio.sleep(1.5)
                            break
            
            # Move to next question
            state["current_question"] += 1
            await self.send_next_question(chat_id)
            
        except Exception as e:
            logger.error(f"Error processing poll answer: {str(e)}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד התשובה. נא לנסות שוב.") 