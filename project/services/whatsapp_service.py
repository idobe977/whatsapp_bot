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
import base64
import tempfile
import mimetypes

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

    async def handle_text_message(self, chat_id: str, text: str, sender_name: str = "") -> None:
        """Handle incoming text messages"""
        try:
            logger.info(f"[handle_text_message] התחלת טיפול בהודעת טקסט מ: {chat_id}")
            logger.debug(f"[handle_text_message] תוכן ההודעה: {text[:100]}...")
            
            # Check for stop phrases
            stop_phrases = ["הפסקת שאלון", "בוא נפסיק"]
            if chat_id in self.survey_state and any(phrase in text.lower() for phrase in stop_phrases):
                logger.info(f"[handle_text_message] המשתמש ביקש להפסיק את השאלון: {chat_id}")
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
                logger.info(f"[handle_text_message] המשתמש נמצא באמצע שאלון")
                state = self.survey_state[chat_id]
                state['last_activity'] = datetime.now()
                survey = state["survey"]
                current_question = survey.questions[state["current_question"]]
                logger.info(f"[handle_text_message] שאלה נוכחית: {current_question['id']}, סוג: {current_question.get('type', 'unknown')}")

                # Check if this is a file upload question and we already have a file
                if "last_file_upload" in state:
                    logger.info(f"[handle_text_message] נמצא מידע על קובץ קודם: {state['last_file_upload']}")
                    if state["last_file_upload"]["question_id"] == current_question["id"]:
                        logger.info(f"[handle_text_message] כבר יש קובץ לשאלה הנוכחית, מדלג על עיבוד הטקסט")
                        return

                # Process the answer
                logger.info(f"[handle_text_message] מעבד תשובה טקסטואלית")
                await self.process_survey_answer(chat_id, {
                    "type": "text",
                    "content": text
                })
                return

            # If not in survey, check for trigger phrase
            logger.info(f"[handle_text_message] בודק אם ההודעה מכילה מילת טריגר להתחלת שאלון")
            for survey in self.surveys:
                logger.debug(f"[handle_text_message] בודק טריגרים עבור שאלון: {survey.name}")
                
                for trigger in survey.trigger_phrases:
                    if trigger.lower() in text.lower():
                        logger.info(f"[handle_text_message] נמצאה מילת טריגר '{trigger}' עבור שאלון: {survey.name}")
                        
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
                    
            logger.info(f"[handle_text_message] לא נמצאו מילות טריגר בהודעה מ: {chat_id}")

        except Exception as e:
            logger.error(f"[handle_text_message] שגיאה בטיפול בהודעת טקסט: {str(e)}")
            logger.error(f"[handle_text_message] Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד ההודעה. נא לנסות שוב.")

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

    async def process_survey_answer(self, chat_id: str, answer: Dict[str, str]) -> None:
        """Process a survey answer"""
        try:
            logger.info(f"Processing survey answer for chat_id: {chat_id}")
            
            state = self.survey_state.get(chat_id)
            if not state or "record_id" not in state:
                logger.error(f"No valid state found for chat_id: {chat_id}")
                return

            state['last_activity'] = datetime.now()
            survey = state["survey"]
            current_question = survey.questions[state["current_question"]]
            question_id = current_question["id"]
            
            # Save answer to state
            if "answers" not in state:
                state["answers"] = {}
            
            try:
                # Format answer based on question type
                formatted_answer = answer["content"]
                if current_question["type"] == "poll":
                    formatted_answer = answer["content"].split(", ")
                    # For poll answers, strip emojis and clean text
                    formatted_answer = [opt.split('⚡')[0].split('⏱️')[0].split('⏰')[0].strip() for opt in formatted_answer]
                    formatted_answer = formatted_answer[0] if formatted_answer else ""
                else:
                    formatted_answer = self.clean_text_for_airtable(formatted_answer)
                
                state["answers"][question_id] = formatted_answer
                logger.debug(f"Updated state answers: {json.dumps(state['answers'], ensure_ascii=False)}")
            except Exception as e:
                logger.error(f"Error formatting answer: {str(e)}")
                await self.send_message_with_retry(
                    chat_id, 
                    survey.messages["error"]
                )
                return
            
            # Prepare Airtable update data
            update_data = {question_id: formatted_answer}
            if state["current_question"] > 0:
                update_data["סטטוס"] = "בטיפול"
            
            # Run tasks concurrently
            tasks = [
                self.generate_response_reflection(
                    current_question["text"], 
                    answer["content"], 
                    survey, 
                    {**current_question, "chat_id": chat_id}
                ),
                self.update_airtable_record(state["record_id"], update_data, survey)
            ]
            reflection, airtable_success = await asyncio.gather(*tasks)
            
            if reflection:
                await self.send_message_with_retry(chat_id, reflection)
                await asyncio.sleep(1.5)
            
            if airtable_success and answer.get("is_final", True):
                # Handle flow logic
                next_question_id = None
                custom_message = None
                
                if "flow" in current_question:
                    flow = current_question["flow"]
                    user_answer = answer["content"]
                    
                    # For poll questions, get the full answer text
                    if current_question["type"] == "poll":
                        user_answer = user_answer.split(", ")[0]  # Get first selected option
                    
                    # Check if conditions
                    if "if" in flow:
                        if_condition = flow["if"]
                        if user_answer == if_condition["answer"]:
                            next_question_id = if_condition["then"].get("goto")
                            custom_message = if_condition["then"].get("say")
                        elif "else_if" in flow:
                            # Handle else_if as a list of conditions
                            if isinstance(flow["else_if"], list):
                                for else_if_condition in flow["else_if"]:
                                    if user_answer == else_if_condition["answer"]:
                                        next_question_id = else_if_condition["then"].get("goto")
                                        custom_message = else_if_condition["then"].get("say")
                                        break
                            # Handle else_if as a single condition
                            elif isinstance(flow["else_if"], dict):
                                else_if_condition = flow["else_if"]
                                if user_answer == else_if_condition["answer"]:
                                    next_question_id = else_if_condition["then"].get("goto")
                                    custom_message = else_if_condition["then"].get("say")
                    # Check for simple then flow
                    elif "then" in flow:
                        next_question_id = flow["then"].get("goto")
                        custom_message = flow["then"].get("say")
                
                # Send custom message if exists
                if custom_message:
                    await self.send_message_with_retry(chat_id, custom_message)
                    await asyncio.sleep(1.5)
                
                # Find next question index
                if next_question_id:
                    next_index = next((i for i, q in enumerate(survey.questions) if q["id"] == next_question_id), None)
                    if next_index is not None:
                        state["current_question"] = next_index
                    else:
                        state["current_question"] += 1
                else:
                    state["current_question"] += 1
                
                state.pop("selected_options", None)
                state.pop("last_poll_response", None)
                
                if state["current_question"] >= len(survey.questions):
                    asyncio.create_task(
                        self.update_airtable_record(
                            state["record_id"], 
                            {"סטטוס": "הושלם"}, 
                            survey
                        )
                    )
                    await self.finish_survey(chat_id)
                else:
                    await self.send_next_question(chat_id)
                    
            elif not airtable_success:
                await self.send_message_with_retry(
                    chat_id, 
                    survey.messages["error"]
                )
            
        except Exception as e:
            logger.error(f"Error processing answer: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(
                chat_id, 
                survey.messages["error"]
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
            
            # Get customer name from answers or state
            customer_name = state["answers"].get("שם מלא", "")
            if not customer_name:
                # Try to get from Airtable
                try:
                    table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
                    record = table.get(state["record_id"])
                    if record and "fields" in record:
                        customer_name = record["fields"].get("שם מלא", "")
                except Exception as e:
                    logger.error(f"Error getting customer name from Airtable: {str(e)}")
                    customer_name = ""

            # Send notification to group
            notification_group_id = "120363021225440995@g.us"
            notification_message = (
                f"✨ *שאלון הושלם בהצלחה!* ✨\n\n"
                f"🌟 *שם השאלון:* {survey.name}\n"
                f"👤 *שם הלקוח:* {customer_name or 'לא צוין'}\n\n"
                f"תודה על שיתוף הפעולה! 🙏"
            )
            
            try:
                await self.send_message_with_retry(notification_group_id, notification_message)
                logger.info(f"Sent completion notification to group for survey: {survey.name}")
            except Exception as e:
                logger.error(f"Error sending group notification: {str(e)}")
            
            # Clean up state
            del self.survey_state[chat_id]
            
        except Exception as e:
            logger.error(f"Error finishing survey: {str(e)}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בסיום השאלון.")

    async def send_next_question(self, chat_id: str) -> None:
        """Send the next survey question"""
        state = self.survey_state.get(chat_id)
        if not state:
            return

        survey = state["survey"]
        if state["current_question"] < len(survey.questions):
            question = survey.questions[state["current_question"]]
            
            if question["type"] == "poll":
                await self.send_poll(chat_id, question)
            elif question["type"] == "meeting_scheduler":
                await self.handle_meeting_scheduler(chat_id, question)
            else:
                await self.send_message_with_retry(chat_id, question["text"])
        else:
            await self.finish_survey(chat_id)

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
            logger.info(f"[update_airtable_record] מתחיל עדכון רשומה באירטייבל. מזהה: {record_id}")
            logger.debug(f"[update_airtable_record] מידע לעדכון: {json.dumps(data, ensure_ascii=False)}")
            
            # Get cached record if available
            cached_record = self.get_cached_airtable_record(record_id, survey.airtable_table_id)
            if cached_record:
                logger.info("[update_airtable_record] נמצאה רשומה במטמון")
                # Merge new data with cached record
                for key, value in data.items():
                    # אם זה מערך של אובייקטים (למשל קבצים), נחליף את הערך הקיים
                    if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                        logger.debug(f"[update_airtable_record] מחליף ערך קיים בשדה {key} עם מערך של אובייקטים")
                        cached_record[key] = value
                    else:
                        # אחרת נעדכן את הערך הקיים
                        cached_record[key] = value
                
                self.cache_airtable_record(record_id, survey.airtable_table_id, cached_record)
                logger.debug(f"[update_airtable_record] רשומה מאוחדת: {json.dumps(cached_record, ensure_ascii=False)}")
            
            # Update Airtable directly
            table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
            
            # וידוא שהנתונים בפורמט הנכון
            processed_data = {}
            for key, value in data.items():
                logger.debug(f"[update_airtable_record] מעבד שדה: {key}, סוג: {type(value).__name__}")
                
                # טיפול מיוחד בקבצים ומערכים של אובייקטים
                if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                    # בדיקה שכל האובייקטים במערך מכילים את השדות הנדרשים לקבצים
                    if all(isinstance(item, dict) and "url" in item for item in value):
                        logger.debug(f"[update_airtable_record] שדה {key} מכיל מערך של קבצים תקין")
                        processed_data[key] = value
                    else:
                        logger.warning(f"[update_airtable_record] שדה {key} מכיל מערך של אובייקטים לא תקין")
                        logger.debug(f"[update_airtable_record] ערך: {json.dumps(value, ensure_ascii=False)}")
                        # ננסה לתקן את הפורמט אם אפשר
                        if all(isinstance(item, dict) for item in value):
                            logger.info(f"[update_airtable_record] מנסה לתקן את הפורמט של שדה {key}")
                            processed_data[key] = value
                        else:
                            logger.error(f"[update_airtable_record] לא ניתן לתקן את הפורמט של שדה {key}")
                            # נשמור כמחרוזת JSON אם לא ניתן לתקן
                            processed_data[key] = json.dumps(value, ensure_ascii=False)
                else:
                    # אחרת נשמור את הערך כמו שהוא
                    processed_data[key] = value
                    logger.debug(f"[update_airtable_record] שדה {key} נשמר כערך פשוט")
            
            logger.info("[update_airtable_record] שולח עדכון לאירטייבל")
            logger.debug(f"[update_airtable_record] מידע מעובד לשליחה: {json.dumps(processed_data, ensure_ascii=False)}")
            
            response = table.update(record_id, processed_data)
            logger.info("[update_airtable_record] העדכון הושלם בהצלחה")
            logger.debug(f"[update_airtable_record] תגובת אירטייבל: {json.dumps(response, ensure_ascii=False)}")
            return True
            
        except Exception as e:
            logger.error(f"[update_airtable_record] שגיאה בעדכון רשומת אירטייבל: {e}")
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                logger.error(f"[update_airtable_record] תגובת API של אירטייבל: {e.response.text}")
            logger.error(f"[update_airtable_record] פרטי השגיאה: {traceback.format_exc()}")
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

    async def handle_file_message(self, chat_id: str, file_url: str, file_type: str, caption: str = "", file_name: str = "", mime_type: str = "") -> None:
        """Handle incoming file messages (images and documents)"""
        logger.info(f"[handle_file_message] התחלת טיפול בקובץ מ: {chat_id}")
        logger.info(f"[handle_file_message] סוג קובץ: {file_type}, URL: {file_url}")
        logger.info(f"[handle_file_message] שם קובץ: {file_name}, MIME: {mime_type}")
        logger.info(f"[handle_file_message] כיתוב: {caption if caption else 'ללא כיתוב'}")

        if chat_id not in self.survey_state:
            logger.info(f"[handle_file_message] אין שאלון פעיל עבור: {chat_id}")
            return

        try:
            state = self.survey_state[chat_id]
            state['last_activity'] = datetime.now()
            survey = state["survey"]
            current_question = survey.questions[state["current_question"]]
            question_id = current_question["id"]
            
            logger.info(f"[handle_file_message] מעבד קובץ עבור שאלה: {question_id}")
            logger.info(f"[handle_file_message] מצב נוכחי בשאלון - שאלה מספר: {state['current_question'] + 1} מתוך {len(survey.questions)}")
            logger.debug(f"[handle_file_message] פרטי השאלה הנוכחית: {json.dumps(current_question, ensure_ascii=False)}")

            # וידוא שה-URL נגיש
            try:
                async with self.get_session() as session:
                    async with session.head(file_url) as response:
                        if response.status != 200:
                            logger.error(f"[handle_file_message] ה-URL של הקובץ לא נגיש: {file_url}")
                            logger.error(f"[handle_file_message] קוד תגובה: {response.status}")
                            await self.send_message_with_retry(chat_id, "מצטערים, לא ניתן לשמור את הקובץ כרגע. נא לנסות שוב.")
                            return
                        logger.info(f"[handle_file_message] URL הקובץ נגיש")
                        logger.debug(f"[handle_file_message] Headers של הקובץ: {dict(response.headers)}")
            except Exception as e:
                logger.error(f"[handle_file_message] שגיאה בבדיקת נגישות הקובץ: {e}")
                logger.error(f"[handle_file_message] פרטי השגיאה: {traceback.format_exc()}")
                await self.send_message_with_retry(chat_id, "מצטערים, לא ניתן לשמור את הקובץ כרגע. נא לנסות שוב.")
                return

            # וידוא סוג הקובץ
            if not mime_type:
                mime_type = 'application/octet-stream'
                if file_name:
                    guessed_type = mimetypes.guess_type(file_name)[0]
                    if guessed_type:
                        mime_type = guessed_type
            logger.info(f"[handle_file_message] MIME type סופי: {mime_type}")
            logger.debug(f"[handle_file_message] תהליך קביעת MIME type: מקורי={mime_type}, שם קובץ={file_name}")

            # יצירת שם קובץ אם לא סופק
            if not file_name:
                extension = mimetypes.guess_extension(mime_type) or ''
                file_name = f"file_{datetime.now().strftime('%Y%m%d_%H%M%S')}{extension}"
                logger.info(f"[handle_file_message] נוצר שם קובץ אוטומטי: {file_name}")
            logger.info(f"[handle_file_message] שם קובץ סופי: {file_name}")

            # הכנת הנתונים לאירטייבל בפורמט הנכון
            # אירטייבל מצפה למערך של אובייקטים עם השדות url, filename, ו-type
            attachments = [{
                "url": file_url,
                "filename": file_name,
                "type": mime_type
            }]
            
            # בדיקה שהפורמט תקין
            if not isinstance(attachments, list) or not all(isinstance(item, dict) and "url" in item for item in attachments):
                logger.error(f"[handle_file_message] פורמט הקובץ לא תקין: {json.dumps(attachments, ensure_ascii=False)}")
                await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד הקובץ. נא לנסות שוב.")
                return
                
            logger.info(f"[handle_file_message] מידע הקובץ לאירטייבל: {json.dumps(attachments, ensure_ascii=False)}")

            # שמירה באירטייבל
            update_data = {
                question_id: attachments,
                "סטטוס": "בטיפול"
            }

            logger.info(f"[handle_file_message] מנסה לשמור קובץ באירטייבל עבור שאלה {question_id}")
            logger.debug(f"[handle_file_message] מידע לעדכון: {json.dumps(update_data, ensure_ascii=False)}")

            # ניסיון לשמור באירטייבל
            success = await self.update_airtable_record(state["record_id"], update_data, survey)
            
            if success:
                logger.info(f"[handle_file_message] הקובץ נשמר בהצלחה באירטייבל עבור שאלה {question_id}")
                
                # שמירת מידע על הקובץ במצב השאלון
                state["last_file_upload"] = {
                    "question_id": question_id,
                    "file_url": file_url,
                    "file_name": file_name,
                    "mime_type": mime_type
                }
                logger.info(f"[handle_file_message] עודכן מידע הקובץ האחרון במצב השאלון: {json.dumps(state['last_file_upload'], ensure_ascii=False)}")
                
                # מעבר לשאלה הבאה
                state["current_question"] += 1
                logger.info(f"[handle_file_message] מתקדם לשאלה הבאה (מספר {state['current_question'] + 1})")
                await self.send_next_question(chat_id)
            else:
                logger.error(f"[handle_file_message] נכשל בשמירת הקובץ באירטייבל עבור שאלה {question_id}")
                await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בשמירת הקובץ. נא לנסות שוב.")

        except Exception as e:
            logger.error(f"[handle_file_message] שגיאה בטיפול בקובץ: {str(e)}")
            logger.error(f"[handle_file_message] Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד הקובץ. נא לנסות שוב.")

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
