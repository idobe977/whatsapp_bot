import asyncio
import json
import aiohttp
from typing import Dict, List, AsyncGenerator, Any, Optional
from aiohttp import ClientTimeout, TCPConnector, ClientSession
from contextlib import asynccontextmanager
from project.utils.logger import logger
from project.models.survey import SurveyDefinition
import os
import glob
from datetime import datetime, timedelta
import google.generativeai as genai
import traceback
import time
from dotenv import load_dotenv
import re
from .calendar_service import CalendarService, TimeSlot
from pyairtable import Api

load_dotenv()

# Get environment variables
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")

# Initialize Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-pro-exp-02-05")

class WhatsAppService:
    def __init__(self, instance_id: str, api_token: str):
        try:
            self.instance_id = instance_id
            self.api_token = api_token
            self.base_url = f"https://api.greenapi.com/waInstance{instance_id}"
            
            # Initialize Airtable client
            self.airtable = Api(AIRTABLE_API_KEY)
            logger.info("Initialized Airtable client")
            
            self.surveys = self.load_surveys()
            self.survey_state = {}  # Track survey state for each user
            self.reflection_cache = {}  # Cache for AI reflections
            self.airtable_cache = {}  # Cache for Airtable records
            self.airtable_cache_timeout = 300  # 5 minutes
            self.contacts_table_id = "tblContacts"  # Airtable table ID for contacts
            
            # Initialize calendar manager
            self.calendar_manager = CalendarService()
            
            # Connection pool settings
            self.MAX_CONNECTIONS = 100
            self.KEEPALIVE_TIMEOUT = 75
            self.DNS_CACHE_TTL = 300
            self.CONNECTION_TIMEOUT = 10
            self.SOCKET_TIMEOUT = 5
            self.MAX_RETRIES = 3
            self.RETRY_DELAY = 2
            self.SURVEY_TIMEOUT = 30  # Minutes
            
            logger.info("WhatsAppService initialized successfully")
            logger.info(f"Loaded {len(self.surveys)} surveys")
            for survey in self.surveys:
                logger.info(f"Survey loaded: {survey.name} with {len(survey.trigger_phrases)} trigger phrases")
        except Exception as e:
            logger.error(f"Error initializing WhatsAppService: {str(e)}")
            raise

    def load_surveys(self) -> List[SurveyDefinition]:
        """Load all survey definitions during initialization"""
        logger.info("Loading surveys...")
        surveys = load_surveys_from_json()
        if not surveys:
            logger.warning("No surveys were loaded!")
        else:
            logger.info(f"Loaded {len(surveys)} surveys with triggers:")
            for survey in surveys:
                logger.info(f"Survey '{survey.name}' triggers: {survey.trigger_phrases}")
        return surveys

    async def handle_text_message(self, chat_id: str, text: str, sender_name: str) -> None:
        """Handle incoming text message"""
        try:
            logger.info(f"Handling text message from {chat_id}")
            
            # Check if user is in a survey
            if chat_id in self.survey_state:
                state = self.survey_state[chat_id]
                
                # Check for survey timeout
                if (datetime.now() - state["last_activity"]).total_seconds() > (self.SURVEY_TIMEOUT * 60):
                    logger.info(f"Survey timeout for {chat_id}")
                    del self.survey_state[chat_id]
                    await self.send_message_with_retry(
                        chat_id,
                        "חלף זמן רב מדי מאז התשובה האחרונה. נא להתחיל את השאלון מחדש."
                    )
                    return
                
                # Update last activity
                state["last_activity"] = datetime.now()
                
                # Process answer
                await self.process_survey_answer(chat_id, text)
                return
            
            # If not in survey, first check if this is a contact
            contact = await self.get_contact(chat_id)
            
            if not contact:
                # Not a contact, ask for name
                logger.info(f"New contact {chat_id}, asking for name")
                await self.send_message_with_retry(
                    chat_id,
                    "היי! אשמח לדעת מה שמך המלא?"
                )
                self.survey_state[chat_id] = {
                    "waiting_for_name": True,
                    "last_activity": datetime.now()
                }
                return
            
            # Check for trigger phrases
            for survey in self.surveys:
                logger.debug(f"Checking triggers for survey: {survey.name}")
                
                for trigger in survey.trigger_phrases:
                    if trigger.lower() in text.lower():
                        logger.info(f"Found trigger phrase '{trigger}' for survey: {survey.name}")
                        
                        # Create initial record in Airtable
                        record_id = await self.create_initial_record(chat_id, contact["שם מלא"], survey)
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
            
            # If we get here, user is not in a survey and no trigger was found
            if chat_id in self.survey_state and self.survey_state[chat_id].get("waiting_for_name"):
                # User was asked for their name
                await self.save_contact(chat_id, text)
                await self.send_message_with_retry(
                    chat_id,
                    "תודה! במה אוכל לעזור לך?"
                )
                del self.survey_state[chat_id]
            else:
                logger.info(f"No trigger phrases found in message from {chat_id}")
                
        except Exception as e:
            logger.error(f"Error handling text message: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(
                chat_id,
                "מצטערים, הייתה שגיאה בטיפול בהודעה. נא לנסות שוב."
            )

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
        if chat_id not in self.survey_state:
            logger.warning(f"Received poll response for unknown chat_id: {chat_id}")
            return

        state = self.survey_state[chat_id]
        state['last_activity'] = datetime.now()

        # Check if this is a meeting scheduler response
        scheduler_state = state.get('meeting_scheduler')
        if scheduler_state:
            selected_options = []
            if "votes" in poll_data:
                for vote in poll_data["votes"]:
                    if "optionVoters" in vote and chat_id in vote.get("optionVoters", []):
                        selected_options.append(vote["optionName"])
            
            if selected_options:
                selected_option = selected_options[0]
                
                # Check if this is date selection or time selection
                if scheduler_state.get('selected_date') is None:
                    # This is date selection
                    await self.handle_meeting_date_selection(chat_id, selected_option)
                else:
                    # This is time selection
                    await self.handle_meeting_time_selection(chat_id, selected_option)
            return

        # Regular poll handling
        current_question = state["survey"].questions[state["current_question"]]
        question_id = current_question["id"]
        
        # Check if current question is a poll question
        if current_question["type"] != "poll":
            logger.warning(f"Ignoring poll response as current question {question_id} is not a poll question")
            return
            
        # Check if this poll response matches the current question's name
        if poll_data.get("name") != current_question["text"]:
            logger.warning(f"Ignoring poll response as it doesn't match current question. Expected: {current_question['text']}, Got: {poll_data.get('name')}")
            return
        
        logger.info(f"Processing poll response for question: {question_id}")
        logger.debug(f"Poll data: {json.dumps(poll_data, ensure_ascii=False)}")
        
        selected_options = []
        if "votes" in poll_data:
            for vote in poll_data["votes"]:
                if "optionVoters" in vote and chat_id in vote.get("optionVoters", []):
                    selected_options.append(vote["optionName"])
        
        if selected_options:
            # Use the full selected option text without processing
            answer_content = selected_options[0]
            await self.process_poll_answer(chat_id, answer_content, question_id)
        else:
            logger.warning(f"No valid options selected for chat_id: {chat_id}")

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

    async def get_airtable_field_value(self, record_id: str, field_name: str, survey: SurveyDefinition) -> Optional[str]:
        """Get field value from Airtable record"""
        try:
            # Check cache first
            cached_record = self.get_cached_airtable_record(record_id, survey.airtable_table_id)
            if cached_record and field_name in cached_record:
                return cached_record[field_name]
            
            # If not in cache, fetch from Airtable
            table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
            record = table.get(record_id)
            
            if record and "fields" in record:
                # Cache the record
                self.cache_airtable_record(record_id, survey.airtable_table_id, record["fields"])
                return record["fields"].get(field_name)
                
            return None
        except Exception as e:
            logger.error(f"Error getting Airtable field value: {e}")
            return None

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[ClientSession, None]:
        """Get aiohttp session with optimal settings"""
        timeout = ClientTimeout(
            total=self.CONNECTION_TIMEOUT,
            connect=2,
            sock_read=self.SOCKET_TIMEOUT
        )
        connector = TCPConnector(
            limit=self.MAX_CONNECTIONS,
            ttl_dns_cache=self.DNS_CACHE_TTL,
            keepalive_timeout=self.KEEPALIVE_TIMEOUT
        )
        async with ClientSession(
            timeout=timeout,
            connector=connector,
            headers={'Connection': 'keep-alive'}
        ) as session:
            yield session

    async def send_message_with_retry(self, chat_id: str, message: str) -> Dict:
        """Send a message with retry mechanism"""
        retries = 0
        last_error = None
        
        while retries < self.MAX_RETRIES:
            try:
                async with self.get_session() as session:
                    url = f"{self.base_url}/sendMessage/{self.api_token}"
                    payload = {
                        "chatId": chat_id,
                        "message": message
                    }
                    
                    logger.debug(f"Sending message to {chat_id}: {message[:100]}...")
                    async with session.post(url, json=payload) as response:
                        if response.status == 200:
                            response_data = await response.json()
                            logger.info(f"Message sent successfully to {chat_id}")
                            return response_data
                        
                        last_error = f"HTTP {response.status}"
                        logger.warning(f"Failed to send message (attempt {retries + 1}): {last_error}")
                        
            except Exception as e:
                last_error = str(e)
                logger.error(f"Error sending message (attempt {retries + 1}): {last_error}")
            
            retries += 1
            if retries < self.MAX_RETRIES:
                delay = self.RETRY_DELAY * retries
                logger.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
        
        logger.error(f"Failed to send message after {self.MAX_RETRIES} retries: {last_error}")
        return {"error": f"Failed after {self.MAX_RETRIES} retries: {last_error}"}

    async def send_poll(self, chat_id: str, question: Dict) -> Dict:
        """Send a poll message"""
        try:
            url = f"{self.base_url}/sendPoll/{self.api_token}"
            formatted_options = [{"optionName": opt} for opt in question["options"]]
            
            payload = {
                "chatId": chat_id,
                "message": question["text"],
                "options": formatted_options,
                "multipleAnswers": question.get("multipleAnswers", False)
            }
            
            logger.debug(f"Sending poll to {chat_id}: {question['text']}")
            logger.debug(f"Poll options: {question['options']}")
            
            async with self.get_session() as session:
                async with session.post(url, json=payload) as response:
                    response_text = await response.text()
                    
                    if response.status != 200:
                        logger.error(f"Poll request failed: {response.status}")
                        return {"error": f"Request failed: {response.status}"}
                    
                    try:
                        result = await response.json()
                        logger.info(f"Poll sent successfully to {chat_id}")
                        return result
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON response: {e}")
                        return {"error": "Invalid JSON response"}
                        
        except Exception as e:
            logger.error(f"Error sending poll: {e}")
            return {"error": str(e)}

    async def send_file(self, chat_id: str, file_path: str, caption: str = None) -> Dict:
        """Send a file as attachment"""
        try:
            url = f"{self.base_url}/sendFileByUpload/{self.api_token}"
            
            form = aiohttp.FormData()
            form.add_field('chatId', chat_id)
            if caption:
                form.add_field('caption', caption)
            
            logger.debug(f"Sending file to {chat_id}: {file_path}")
            
            with open(file_path, 'rb') as f:
                file_content = f.read()
                form.add_field('file', file_content, 
                    filename=file_path.split('/')[-1],
                    content_type='application/octet-stream')
                
                async with self.get_session() as session:
                    async with session.post(url, data=form) as response:
                        if response.status == 200:
                            logger.info(f"File sent successfully to {chat_id}")
                            return await response.json()
                        logger.error(f"Failed to send file: HTTP {response.status}")
                        return {"error": f"Failed to send file: HTTP {response.status}"}
                        
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            return {"error": str(e)}

    async def send_messages_batch(self, messages: List[Dict]) -> List[Dict]:
        """Send multiple messages in batch"""
        async def send_single(msg: Dict) -> Dict:
            return await self.send_message_with_retry(msg['chat_id'], msg['text'])
        
        logger.info(f"Sending batch of {len(messages)} messages")
        tasks = []
        for i, msg in enumerate(messages):
            if i > 0 and i % 5 == 0:  # Rate limit: 5 messages at a time
                logger.debug("Rate limit reached, waiting 1 second...")
                await asyncio.sleep(1)
            tasks.append(asyncio.create_task(send_single(msg)))
        
        results = await asyncio.gather(*tasks)
        logger.info(f"Batch sending completed. {len(results)} messages sent.")
        return results

    async def transcribe_voice(self, voice_url: str) -> str:
        """Transcribe voice message using Gemini API"""
        try:
            async with self.get_session() as session:
                async with session.get(voice_url) as response:
                    if response.status != 200:
                        return "שגיאה בהורדת הקובץ הקולי"
                    
                    content = await response.read()
                    
                    gemini_response = model.generate_content([
                        "Please transcribe this audio file and respond in Hebrew:",
                        {"mime_type": "audio/ogg", "data": content}
                    ])
                    
                    return gemini_response.text
                    
        except Exception as e:
            logger.error(f"Error in voice transcription: {e}")
            return "שגיאה בתהליך התמלול"

    async def generate_response_reflection(self, question: str, answer: str, survey: SurveyDefinition, question_data: Dict) -> Optional[str]:
        """Generate a reflective response based on the user's answer with caching"""
        try:
            # Check if reflection is enabled for this question
            reflection_config = question_data.get('reflection', {"type": "none", "enabled": False})
            if not reflection_config["enabled"] or reflection_config["type"] == "none":
                return None

            # Create a cache key from question and answer
            cache_key = f"{question}:{answer}"
            
            # Check cache first
            if cache_key in self.reflection_cache:
                logger.info("Using cached reflection response")
                return self.reflection_cache[cache_key]
            
            # Get reflection prompt from survey configuration
            reflection_type = reflection_config["type"]
            if reflection_type not in survey.ai_prompts["reflections"]:
                logger.error(f"Invalid reflection type: {reflection_type}")
                return None
                
            reflection_prompt = survey.ai_prompts["reflections"][reflection_type].get("prompt")
            if not reflection_prompt:
                logger.error(f"No prompt found for reflection type: {reflection_type}")
                return None

            # Get previous question and answer if available
            current_question_index = next((i for i, q in enumerate(survey.questions) if q["text"] == question), -1)
            previous_context = ""
            if current_question_index > 0:
                previous_question = survey.questions[current_question_index - 1]
                previous_answer = self.survey_state.get(question_data.get("chat_id", ""), {}).get("answers", {}).get(previous_question["id"])
                if previous_answer:
                    previous_context = f"""
                    שאלה קודמת: {previous_question["text"]}
                    תשובה קודמת: {previous_answer}
                    """

            prompt = f"""
            {reflection_prompt}
            
            {previous_context}
            שאלה נוכחית: {question}
            תשובה נוכחית: {answer}
            """
            
            response = model.generate_content(prompt)
            reflection = response.text.strip()
            
            # Cache the response
            self.reflection_cache[cache_key] = reflection
            
            # Limit cache size to prevent memory issues
            if len(self.reflection_cache) > 1000:  # Keep last 1000 responses
                self.reflection_cache.pop(next(iter(self.reflection_cache)))
                
            return reflection
        except Exception as e:
            logger.error(f"Error generating reflection: {str(e)}")
            return None

    def generate_summary(self, answers: Dict[str, str], survey: SurveyDefinition) -> str:
        """Generate a summary of the survey answers using the language model"""
        try:
            if not answers:
                return "לא נמצאו תשובות לסיכום."
                
            summary_config = survey.ai_prompts.get("summary", {})
            if not summary_config:
                logger.error("No summary configuration found in survey")
                return "לא הצלחנו ליצור סיכום כרגע."
                
            summary_prompt = summary_config.get("prompt")
            if not summary_prompt:
                logger.error("No summary prompt found in survey configuration")
                return "לא הצלחנו ליצור סיכום כרגע."

            # Add recommendations flag to prompt if configured
            if summary_config.get("include_recommendations", False):
                summary_prompt += "\nאנא כלול גם המלצות מעשיות לשיפור."

            prompt = f"""
            {summary_prompt}

            תשובות המשתמש:
            {chr(10).join([f"שאלה: {q}{chr(10)}תשובה: {a}" for q, a in answers.items()])}
            """
            
            response = model.generate_content([prompt])
            summary = response.text.strip()
            
            # Validate summary length if configured
            max_length = summary_config.get("max_length")
            if max_length and len(summary) > max_length:
                summary = summary[:max_length] + "..."
                
            return summary
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return "לא הצלחנו ליצור סיכום כרגע."

    async def start_cleanup_task(self) -> None:
        """Start the cleanup task for stale survey states"""
        async def cleanup_loop():
            while True:
                current_time = datetime.now()
                to_remove = []
                
                for chat_id, state in self.survey_state.items():
                    if 'last_activity' in state:
                        if (current_time - state['last_activity']).total_seconds() > self.SURVEY_TIMEOUT * 60:
                            to_remove.append(chat_id)
                            
                for chat_id in to_remove:
                    state = self.survey_state.pop(chat_id)
                    logger.info(f"Cleaned up stale survey state for {chat_id}")
                    await self.send_message_with_retry(chat_id, "השאלון בוטל עקב חוסר פעילות. אנא התחל מחדש.")
                
                # Wait for 5 minutes before next cleanup
                await asyncio.sleep(300)
        
        # Create the cleanup task
        self.cleanup_task = asyncio.create_task(cleanup_loop())

    async def process_survey_answer(self, chat_id: str, answer: str) -> None:
        """Process an answer in an ongoing survey"""
        try:
            state = self.survey_state[chat_id]
            survey = state["survey"]
            current_question = state["current_question"]
            
            if current_question >= len(survey.questions):
                logger.warning(f"Invalid question index {current_question} for survey {survey.name}")
                return
            
            question = survey.questions[current_question]
            
            # Store the answer
            state["answers"][question["field"]] = answer
            
            # Update Airtable with the answer
            await self.update_airtable_record(
                state["record_id"],
                {question["field"]: answer},
                survey
            )
            
            # Move to next question
            state["current_question"] += 1
            
            # Check if survey is complete
            if state["current_question"] >= len(survey.questions):
                logger.info(f"Survey completed for {chat_id}")
                
                # Update status in Airtable
                await self.update_airtable_record(
                    state["record_id"],
                    {"סטטוס": "הושלם"},
                    survey
                )
                
                # Send completion message
                if "completion" in survey.messages:
                    await self.send_message_with_retry(chat_id, survey.messages["completion"])
                
                # Clean up state
                del self.survey_state[chat_id]
                return
            
            # Send next question
            await self.send_next_question(chat_id)
            
        except Exception as e:
            logger.error(f"Error processing survey answer: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(
                chat_id,
                "מצטערים, הייתה שגיאה בשמירת התשובה. נא לנסות שוב."
            )

    async def finish_survey(self, chat_id: str) -> None:
        """Finish the survey and send a summary"""
        try:
            state = self.survey_state.get(chat_id)
            if not state:
                return

            survey = state["survey"]
            
            # Generate and send summary if configured
            if survey.messages["completion"].get("should_generate_summary", True):
                summary = self.generate_summary(state["answers"], survey)
                await self.send_message_with_retry(chat_id, f"*סיכום השאלון שלך:*\n{summary}")
                await asyncio.sleep(1.5)

            # Send completion message
            await self.send_message_with_retry(chat_id, survey.messages["completion"]["text"])
            
            # Clean up state
            del self.survey_state[chat_id]
            
        except Exception as e:
            logger.error(f"Error finishing survey: {str(e)}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בסיום השאלון.")

    async def send_next_question(self, chat_id: str) -> None:
        """Send the next question in the survey"""
        try:
            state = self.survey_state[chat_id]
            survey = state["survey"]
            current_question = state["current_question"]
            
            if current_question >= len(survey.questions):
                logger.warning(f"Invalid question index {current_question} for survey {survey.name}")
                return
            
            question = survey.questions[current_question]
            
            # Send the question text
            await self.send_message_with_retry(chat_id, question["text"])
            
            # If it's a poll question, send the poll
            if question.get("type") == "poll":
                await self.send_poll(chat_id, {
                    'text': question["text"],
                    'options': question["options"],
                    'type': 'poll'
                })
            
        except Exception as e:
            logger.error(f"Error sending next question: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(
                chat_id,
                "מצטערים, הייתה שגיאה בשליחת השאלה הבאה. נא לנסות שוב."
            )

    def get_cached_airtable_record(self, record_id: str, table_id: str) -> Optional[Dict]:
        """Get record from cache if available and not expired"""
        cache_key = f"{table_id}:{record_id}"
        cached_data = self.airtable_cache.get(cache_key)
        if cached_data:
            timestamp, record = cached_data
            if time.time() - timestamp < self.airtable_cache_timeout:
                return record
            else:
                del self.airtable_cache[cache_key]
        return None

    def cache_airtable_record(self, record_id: str, table_id: str, record: Dict) -> None:
        """Cache Airtable record with timestamp"""
        cache_key = f"{table_id}:{record_id}"
        self.airtable_cache[cache_key] = (time.time(), record)
        
        # Cleanup old cache entries
        current_time = time.time()
        expired_keys = [k for k, v in self.airtable_cache.items() 
                       if current_time - v[0] > self.airtable_cache_timeout]
        for k in expired_keys:
            del self.airtable_cache[k]

    async def update_airtable_record(self, record_id: str, data: Dict, survey: SurveyDefinition) -> bool:
        """Update Airtable record."""
        try:
            # Get cached record if available
            cached_record = self.get_cached_airtable_record(record_id, survey.airtable_table_id)
            if cached_record:
                # Merge new data with cached record
                cached_record.update(data)
                self.cache_airtable_record(record_id, survey.airtable_table_id, cached_record)
            
            # Update Airtable directly
            table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
            table.update(record_id, data)
            return True
            
        except Exception as e:
            logger.error(f"Error updating Airtable record: {e}")
            return False

    def clean_text_for_airtable(self, text: str) -> str:
        """Clean text by replacing special characters for Airtable compatibility"""
        if not text:
            return text
            
        # Replace various types of dashes with regular dash
        text = text.replace('–', '-').replace('—', '-').replace('‒', '-').replace('―', '-')
        
        # Remove multiple spaces and trim
        text = ' '.join(text.split())
        
        return text.strip()

    async def handle_meeting_scheduler(self, chat_id: str, question: Dict) -> None:
        """Handle meeting scheduler question type."""
        try:
            state = self.survey_state[chat_id]
            survey = state["survey"]
            
            # Get calendar settings from survey
            calendar_settings = survey.calendar_settings if hasattr(survey, 'calendar_settings') else None
            if not calendar_settings:
                logger.error("No calendar settings found in survey configuration")
                await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בתהליך קביעת הפגישה.")
                return
            
            # Get next N days based only on working hours availability
            available_dates = []
            current_date = datetime.now()
            days_checked = 0
            days_to_show = calendar_settings.get('days_to_show', 7)
            
            while len(available_dates) < days_to_show and days_checked < days_to_show * 2:
                slots = self.calendar_manager.get_available_slots(calendar_settings, current_date)
                if slots:
                    available_dates.append(current_date.date())
                current_date += timedelta(days=1)
                days_checked += 1
            
            if not available_dates:
                await self.send_message_with_retry(
                    chat_id,
                    question.get('no_slots_message', f"מצטערים, אין זמנים פנויים ב-{days_to_show} הימים הקרובים.")
                )
                return
            
            # Store available dates in state
            state['meeting_scheduler'] = {
                'available_dates': available_dates,
                'calendar_settings': calendar_settings,
                'question': question
            }
            
            # Create date selection poll with formatted dates
            date_options = [self.calendar_manager._format_date_for_display(datetime.combine(d, datetime.min.time())) 
                          for d in available_dates]
            
            # Send poll for date selection
            await self.send_poll(chat_id, {
                'text': "באיזה יום נקבע את הפגישה? 📅",
                'options': date_options,
                'type': 'poll'
            })
            
        except Exception as e:
            logger.error(f"Error in handle_meeting_scheduler: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בתהליך קביעת הפגישה.")

    async def handle_meeting_date_selection(self, chat_id: str, selected_date_str: str) -> None:
        """Handle meeting date selection."""
        try:
            state = self.survey_state[chat_id]
            scheduler_state = state.get('meeting_scheduler')
            
            if not scheduler_state:
                logger.error("No meeting scheduler state found")
                return
            
            # Parse day name and date from selected format
            day_name_map = {
                'ראשון': 'Sunday',
                'שני': 'Monday',
                'שלישי': 'Tuesday',
                'רביעי': 'Wednesday',
                'חמישי': 'Thursday',
                'שישי': 'Friday',
                'שבת': 'Saturday'
            }
            
            # Extract date from format "יום שלישי 13/2"
            date_parts = selected_date_str.split(' ')
            date_str = date_parts[-1]  # Get the actual date part
            day, month = map(int, date_str.split('/'))
            year = datetime.now().year
            
            # Find matching date from available dates
            selected_date = None
            for date in scheduler_state['available_dates']:
                if date.day == day and date.month == month:
                    selected_date = datetime.combine(date, datetime.min.time())
                    break
            
            if not selected_date:
                await self.send_message_with_retry(
                    chat_id,
                    "מצטערים, התאריך שנבחר אינו זמין יותר. אנא בחר תאריך אחר."
                )
                return
            
            # Get available slots for selected date
            slots = self.calendar_manager.get_available_slots(
                scheduler_state['calendar_settings'],
                selected_date
            )
            
            if not slots:
                await self.send_message_with_retry(
                    chat_id,
                    "מצטערים, אין זמנים פנויים בתאריך שנבחר. אנא בחר תאריך אחר."
                )
                return
            
            # Store slots in state
            scheduler_state['selected_date'] = selected_date
            scheduler_state['available_slots'] = slots
            
            # Format time slots for better readability
            time_options = [str(slot) for slot in slots]
            time_options.append("בעצם אני רוצה לבדוק יום אחר😅")  # Add option to select different day
            
            # Send poll for time selection
            await self.send_poll(chat_id, {
                'text': f"באיזו שעה יהיה לך נוח ב{selected_date_str}? ⏰",
                'options': time_options,
                'type': 'poll'
            })
            
        except Exception as e:
            logger.error(f"Error in handle_meeting_date_selection: {str(e)}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בבחירת התאריך.")

    async def handle_meeting_time_selection(self, chat_id: str, selected_time_str: str) -> None:
        """Handle meeting time selection."""
        try:
            state = self.survey_state[chat_id]
            scheduler_state = state.get('meeting_scheduler')
            
            if not scheduler_state:
                logger.error("No meeting scheduler state found")
                return
            
            # Check if user wants to select a different day
            if selected_time_str == "בעצם אני רוצה לבדוק יום אחר😅":
                await self.handle_meeting_scheduler(chat_id, scheduler_state['question'])
                return
            
            # Parse time from format "HH:MM - HH:MM"
            start_time = selected_time_str.split(' - ')[0]
            hour, minute = map(int, start_time.split(':'))
            
            selected_date = scheduler_state['selected_date']
            
            # Create TimeSlot object for comparison
            selected_slot = TimeSlot(
                start_time=selected_date.replace(hour=hour, minute=minute),
                end_time=selected_date.replace(hour=hour, minute=minute) + timedelta(minutes=scheduler_state['calendar_settings'].get('slot_duration_minutes', 30))
            )
            
            # Get available slots for selected date
            available_slots = self.calendar_manager.get_available_slots(
                scheduler_state['calendar_settings'],
                selected_date
            )
            
            # Check if selected slot matches any available slot
            slot_is_available = False
            for slot in available_slots:
                if slot.start_time.hour == hour and slot.start_time.minute == minute:
                    slot_is_available = True
                    selected_slot = slot  # Use the actual slot from available slots
                    break
            
            if not slot_is_available:
                await self.send_message_with_retry(
                    chat_id,
                    "מצטערים, השעה שנבחרה אינה זמינה יותר. אנא בחר שעה אחרת."
                )
                return
            
            # Get attendee data from previous answers
            attendee_data = {
                'שם מלא': state['answers'].get('שם מלא', ''),
                'phone': chat_id.split('@')[0],  # Extract phone number from chat_id
            }
            
            # Fetch meeting type from Airtable
            try:
                table = self.airtable.table(AIRTABLE_BASE_ID, state['survey'].airtable_table_id)
                record = table.get(state["record_id"])
                if record and "fields" in record:
                    meeting_type = record["fields"].get("סוג הפגישה", "")
                    logger.info(f"Fetched meeting type from Airtable: {meeting_type}")
                    attendee_data['סוג הפגישה'] = meeting_type
                else:
                    logger.warning("Could not find meeting type in Airtable record")
                    attendee_data['סוג הפגישה'] = ""
            except Exception as e:
                logger.error(f"Error fetching meeting type from Airtable: {str(e)}")
                attendee_data['סוג הפגישה'] = ""
            
            logger.info(f"Scheduling meeting with data: {json.dumps(attendee_data, ensure_ascii=False)}")
            
            # Schedule the meeting
            result = self.calendar_manager.schedule_meeting(
                scheduler_state['calendar_settings'],
                selected_slot,
                attendee_data
            )
            
            if result:
                # Store event ID in state
                scheduler_state['event_id'] = result['event_id']
                
                # Format date and time for display
                formatted_date_display = selected_date.strftime("%d/%m/%Y")
                formatted_time = selected_time_str
                
                # Format date for Airtable (YYYY-MM-DD HH:mm)
                formatted_date_airtable = selected_slot.start_time.strftime("%Y-%m-%d %H:%M")
                
                logger.info(f"Saving meeting to Airtable with date: {formatted_date_airtable}")
                
                # Save meeting details to Airtable
                try:
                    # Update existing record instead of creating new one
                    table = self.airtable.table(AIRTABLE_BASE_ID, state['survey'].airtable_table_id)
                    meeting_data = {
                        "תאריך פגישה": formatted_date_airtable
                    }
                    logger.debug(f"Updating Airtable record with data: {json.dumps(meeting_data, ensure_ascii=False)}")
                    
                    response = table.update(state["record_id"], meeting_data)
                    logger.info(f"Updated meeting record in Airtable: {json.dumps(response, ensure_ascii=False)}")
                except Exception as e:
                    logger.error(f"Error updating meeting in Airtable: {str(e)}")
                    if hasattr(e, 'response'):
                        logger.error(f"Airtable API response: {e.response.text}")
                
                # Send confirmation messages
                await self.send_message_with_retry(
                    chat_id, 
                    f"*הפגישה נקבעה בהצלחה! 🎉*\n\n"
                    f"📅 תאריך: {formatted_date_display}\n"
                    f"🕒 שעה: {formatted_time}\n\n"
                    f"אשלח לך כעת קובץ להוספת הפגישה ליומן שלך:"
                )
                await asyncio.sleep(1)
                
                # Send ICS file
                try:
                    url = f"https://api.greenapi.com/waInstance{self.instance_id}/sendFileByUpload/{self.api_token}"
                    
                    form = aiohttp.FormData()
                    form.add_field('chatId', chat_id)
                    form.add_field('caption', "בלחיצה על הקובץ, הפגישה תישמר ביומן שלך 🔥")
                    
                    with open(result['ics_file'], 'rb') as f:
                        file_content = f.read()
                        form.add_field('file', file_content, 
                            filename='meeting.ics',
                            content_type='text/calendar')
                    
                        async with aiohttp.ClientSession() as session:
                            async with session.post(url, data=form) as response:
                                if response.status != 200:
                                    logger.error(f"Failed to send ICS file: {await response.text()}")
                    
                    # Clean up temporary file
                    os.remove(result['ics_file'])
                    
                except Exception as e:
                    logger.error(f"Error sending ICS file: {str(e)}")
                
                # Move to next question
                state["current_question"] += 1
                await self.send_next_question(chat_id)
            else:
                await self.send_message_with_retry(
                    chat_id,
                    "מצטערים, הייתה שגיאה בקביעת הפגישה. אנא נסה שוב."
                )
            
        except Exception as e:
            logger.error(f"Error in handle_meeting_time_selection: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בקביעת הפגישה.")

    def create_initial_record(self, chat_id: str, sender_name: str, survey: SurveyDefinition) -> Optional[str]:
        """Create initial record when survey starts"""
        try:
            logger.info(f"Creating initial record for chat_id: {chat_id}, sender_name: {sender_name}, survey: {survey.name}")
            record = {
                "מזהה צ'אט וואטסאפ": chat_id,
                "שם מלא": sender_name,
                "סטטוס": "חדש"
            }
            logger.debug(f"Record data to be created: {json.dumps(record, ensure_ascii=False)}")
            
            table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
            response = table.create(record)
            logger.info(f"Created initial record: {response}")
            return response["id"]
        except Exception as e:
            logger.error(f"Error creating initial record: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response content: {e.response.text}")
            return None

    async def get_contact(self, chat_id: str) -> Optional[Dict]:
        """Get contact from Airtable if exists"""
        try:
            # Check cache first
            cache_key = f"contact_{chat_id}"
            if cache_key in self.airtable_cache:
                cache_entry = self.airtable_cache[cache_key]
                if (datetime.now() - cache_entry["timestamp"]).total_seconds() < self.airtable_cache_timeout:
                    return cache_entry["data"]
            
            # Query Airtable
            table = self.airtable.table(AIRTABLE_BASE_ID, self.contacts_table_id)
            records = table.all(formula=f"{{מזהה צ'אט בוואטסאפ}} = '{chat_id}'")
            
            if records:
                contact = records[0]["fields"]
                # Update cache
                self.airtable_cache[cache_key] = {
                    "timestamp": datetime.now(),
                    "data": contact
                }
                return contact
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting contact: {str(e)}")
            return None

    async def save_contact(self, chat_id: str, full_name: str) -> Optional[str]:
        """Save new contact to Airtable"""
        try:
            logger.info(f"Saving new contact {full_name} with chat_id {chat_id}")
            
            record = {
                "מזהה צ'אט בוואטסאפ": chat_id,
                "שם מלא": full_name,
                "תיוג": f"ליד- {full_name}"
            }
            
            table = self.airtable.table(AIRTABLE_BASE_ID, self.contacts_table_id)
            response = table.create(record)
            
            # Update cache
            cache_key = f"contact_{chat_id}"
            self.airtable_cache[cache_key] = {
                "timestamp": datetime.now(),
                "data": record
            }
            
            logger.info(f"Successfully saved contact: {response}")
            return response["id"]
            
        except Exception as e:
            logger.error(f"Error saving contact: {str(e)}")
            return None

def load_surveys_from_json() -> List[SurveyDefinition]:
    """Load all survey definitions from JSON files in the surveys directory"""
    surveys = []
    surveys_dir = 'surveys'  # Changed from complex path to simple directory name
    
    if not os.path.exists(surveys_dir):
        os.makedirs(surveys_dir)
        logger.info(f"Created surveys directory: {surveys_dir}")
        return []

    logger.info(f"Loading surveys from: {surveys_dir}")
    for file_path in glob.glob(os.path.join(surveys_dir, '*.json')):
        try:
            logger.debug(f"Reading survey file: {file_path}")
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            survey = SurveyDefinition(
                name=data['name'],
                trigger_phrases=data['trigger_phrases'],
                airtable_table_id=data['airtable']['table_id'],
                airtable_base_id=data['airtable'].get('base_id'),
                questions=data['questions'],
                messages=data.get('messages'),
                ai_prompts=data.get('ai_prompts'),
                calendar_settings=data.get('calendar_settings')
            )
            surveys.append(survey)
            logger.info(f"Successfully loaded survey: {survey.name} from {file_path}")
            logger.debug(f"Survey details: {len(survey.questions)} questions, {len(survey.trigger_phrases)} triggers")
        except Exception as e:
            logger.error(f"Error loading survey from {file_path}: {str(e)}")
            
    return surveys 
