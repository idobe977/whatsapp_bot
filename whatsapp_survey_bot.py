import google.generativeai as genai
import requests
import json
import os
from typing import Dict, Union, List, Optional
import base64
from pyairtable import Api
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta
import traceback
from mutagen.oggopus import OggOpus
import tempfile
from survey_definitions import SurveyDefinition
from survey_loader import load_all_surveys
import threading
import asyncio
from fastapi import FastAPI
import aiohttp
import re
import time

# Configure logging with more detailed format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('whatsapp_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
logger.info("Loading environment variables...")

# Validate environment variables
required_env_vars = [
    "ID_INSTANCE",
    "API_TOKEN_INSTANCE",
    "GEMINI_API_KEY",
    "AIRTABLE_API_KEY",
    "AIRTABLE_BASE_ID",
    "AIRTABLE_BUSINESS_SURVEY_TABLE_ID",
    "AIRTABLE_RESEARCH_SURVEY_TABLE_ID",
    "AIRTABLE_SATISFACTION_SURVEY_TABLE_ID"
]

missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Green API Configuration
ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")
GREEN_API_BASE_URL = f"https://api.greenapi.com/waInstance{ID_INSTANCE}"
logger.info(f"Configured Green API with instance ID: {ID_INSTANCE}")

# Gemini Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash-exp")
logger.info("Configured Gemini API")

# Airtable Configuration
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")

# Load all surveys from JSON files
AVAILABLE_SURVEYS = load_all_surveys()
logger.info(f"Loaded {len(AVAILABLE_SURVEYS)} surveys from JSON files")

# Load survey table IDs
SURVEY_TABLE_IDS = {
    "business_survey": os.getenv("AIRTABLE_BUSINESS_SURVEY_TABLE_ID"),
    "research_survey": os.getenv("AIRTABLE_RESEARCH_SURVEY_TABLE_ID"),
    "satisfaction_survey": os.getenv("AIRTABLE_SATISFACTION_SURVEY_TABLE_ID")
}

logger.info(f"Configured Airtable with base ID: {AIRTABLE_BASE_ID}")
logger.info(f"Loaded survey table IDs: {list(SURVEY_TABLE_IDS.keys())}")

class WhatsAppSurveyBot:
    def __init__(self):
        self.survey_state = {}
        self.MAX_RETRIES = 3
        self.RETRY_DELAY = 2
        self.SURVEY_TIMEOUT = 30
        self.cleanup_task = None
        self.reflection_cache = {}
        self.airtable_cache = {}
        self.airtable_cache_timeout = 300
        
        # Initialize Airtable client
        self.airtable = Api(AIRTABLE_API_KEY)
        logger.info("Initialized Airtable client")
        
        # Initialize aiohttp session for reuse
        self.session = None
        
        # Load surveys dynamically
        self.survey_table_ids = {}
        for survey in AVAILABLE_SURVEYS:
            self._validate_survey_definition(survey)
            self.survey_table_ids[survey.name] = survey.airtable_table_id
            logger.info(f"Loaded survey: {survey.name} with table ID: {survey.airtable_table_id}")

    def _validate_survey_definition(self, survey: SurveyDefinition) -> None:
        """Validate survey definition has all required fields"""
        required_fields = ['name', 'trigger_phrases', 'questions', 'airtable_table_id']
        for field in required_fields:
            if not hasattr(survey, field) or not getattr(survey, field):
                raise ValueError(f"Survey {survey.name} missing required field: {field}")
        
        for i, question in enumerate(survey.questions):
            if 'id' not in question or 'type' not in question or 'text' not in question:
                raise ValueError(f"Question {i} in survey {survey.name} missing required fields")
            
            if question['type'] == 'poll' and ('options' not in question or not question['options']):
                raise ValueError(f"Poll question {i} in survey {survey.name} missing options")

    async def start_cleanup_task(self) -> None:
        """Start the cleanup task"""
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

    async def get_aiohttp_session(self):
        """Get or create aiohttp session with optimal settings"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(
                total=10,        # Total timeout
                connect=2,       # Connection timeout
                sock_read=5      # Socket read timeout
            )
            connector = aiohttp.TCPConnector(
                limit=100,           # Max concurrent connections
                ttl_dns_cache=300,   # DNS cache TTL (5 minutes)
                force_close=False    # Keep-alive connections
            )
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={'Connection': 'keep-alive'}
            )
        return self.session

    async def send_message_with_retry(self, chat_id: str, message: str) -> Dict:
        """Send a message with retry mechanism using aiohttp"""
        retries = 0
        last_error = None
        session = await self.get_aiohttp_session()
        
        while retries < self.MAX_RETRIES:
            try:
                url = f"{GREEN_API_BASE_URL}/sendMessage/{API_TOKEN_INSTANCE}"
                payload = {
                    "chatId": chat_id,
                    "message": message
                }
                
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        logger.info(f"Message sent successfully to {chat_id}")
                        return response_data
                    
                last_error = f"HTTP {response.status}"
                retries += 1
                if retries < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_DELAY)
                
            except Exception as e:
                last_error = str(e)
                retries += 1
                if retries < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_DELAY)
                
        logger.error(f"Failed to send message after {self.MAX_RETRIES} retries: {last_error}")
        return {"error": f"Failed after {self.MAX_RETRIES} retries: {last_error}"}

    def get_survey_by_trigger(self, message: str) -> Optional[SurveyDefinition]:
        """Find the appropriate survey based on trigger phrase"""
        message = message.lower()
        for survey in AVAILABLE_SURVEYS:
            if any(trigger.lower() in message for trigger in survey.trigger_phrases):
                return survey
        return None

    def get_existing_record_id(self, chat_id: str, survey: SurveyDefinition) -> Optional[str]:
        """Get existing record ID for a chat_id"""
        try:
            table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
            records = table.all(formula=f"{{מזהה צ'אט בוואטסאפ}} = '{chat_id}'")
            if records:
                # Get the most recent record if multiple exist
                return records[-1]["id"]
            return None
        except Exception as e:
            logger.error(f"Error getting record ID: {e}")
            return None

    def create_initial_record(self, chat_id: str, sender_name: str, survey: SurveyDefinition) -> Optional[str]:
        """Create initial record when survey starts"""
        try:
            logger.info(f"Creating initial record for chat_id: {chat_id}, sender_name: {sender_name}, survey: {survey.name}")
            record = {
                "מזהה צ'אט וואטסאפ": chat_id,
                "תאריך מילוי": datetime.now().strftime("%Y-%m-%d"),
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

    def update_record(self, record_id: str, data: Dict, survey: SurveyDefinition) -> bool:
        """Update existing record with new data"""
        try:
            table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
            table.update(record_id, data)
            return True
        except Exception as e:
            logger.error(f"Error updating record: {e}")
            return False

    async def send_poll(self, chat_id: str, question: Dict) -> Dict:
        """Send a poll message to WhatsApp user"""
        try:
            logger.info(f"Sending poll to {chat_id}")
            logger.debug(f"Poll question: {question['text']}")
            logger.debug(f"Poll options: {question['options']}")
            
            # Construct the full URL according to the API documentation
            url = f"https://api.greenapi.com/waInstance{ID_INSTANCE}/sendPoll/{API_TOKEN_INSTANCE}"
            
            # Format options according to API spec
            formatted_options = [{"optionName": opt} for opt in question["options"]]
            
            payload = {
                "chatId": chat_id,
                "message": question["text"],
                "options": formatted_options,
                "multipleAnswers": question.get("multipleAnswers", False)
            }
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            logger.debug(f"Poll payload: {json.dumps(payload, ensure_ascii=False)}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    response_text = await response.text()
                    logger.debug(f"Raw response: {response_text}")
                    
                    if response.status != 200:
                        logger.error(f"Poll request failed with status {response.status}")
                        logger.error(f"Response content: {response_text}")
                        return {"error": f"Request failed with status {response.status}"}
                    
                    try:
                        response_data = json.loads(response_text)
                        logger.info(f"Poll sent successfully to {chat_id}")
                        logger.debug(f"Green API response: {response_data}")
                        return response_data
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse response JSON: {str(e)}")
                        logger.error(f"Raw response: {response_text}")
                        return {"error": "Invalid JSON response from API"}
            
        except aiohttp.ClientError as e:
            error_msg = f"Failed to send poll to {chat_id}: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"Unexpected error sending poll: {str(e)}"
            logger.error(error_msg)
            logger.error(f"Stack trace: {traceback.format_exc()}")
            return {"error": error_msg}

    async def transcribe_voice(self, voice_url: str) -> str:
        """Transcribe voice message using Gemini"""
        try:
            logger.info(f"Starting voice transcription from URL: {voice_url}")
            
            response = requests.get(voice_url)
            response.raise_for_status()
            logger.info("Voice file downloaded successfully")
            
            logger.debug(f"File size: {len(response.content)} bytes")
            logger.debug("Sending to Gemini for transcription")
            
            gemini_response = model.generate_content([
                "Please transcribe this audio file and respond in Hebrew:",
                {"mime_type": "audio/ogg", "data": response.content}
            ])
            
            transcribed_text = gemini_response.text
            logger.info("Voice transcription completed successfully")
            logger.debug(f"Transcribed text: {transcribed_text[:100]}...")  # Log first 100 chars
            
            return transcribed_text
        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading voice file: {str(e)}")
            return "שגיאה בהורדת הקובץ הקולי"
        except Exception as e:
            logger.error(f"Error in voice transcription: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            return "שגיאה בתהליך התמלול"

    async def handle_voice_message(self, chat_id: str, voice_url: str) -> None:
        """Handle incoming voice messages"""
        if chat_id not in self.survey_state:
            return

        try:
            state = self.survey_state[chat_id]
            state['last_activity'] = datetime.now()
            survey = state["survey"]
            current_question_index = state["current_question"]
            current_question = survey.questions[current_question_index]

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
                if self.update_record(state["record_id"], update_data, survey):
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
            reflection_prompt = survey.ai_prompts["reflections"].get(reflection_type, {}).get("prompt")
            if not reflection_prompt:
                logger.error(f"No prompt found for reflection type: {reflection_type}")
                return None

            prompt = f"""
            {reflection_prompt}
            
            שאלה: {question}
            תשובה: {answer}
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
            summary_prompt = summary_config.get("prompt")
            if not summary_prompt:
                logger.error("No summary prompt found in survey configuration")
                return "לא הצלחנו ליצור סיכום כרגע."

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

    async def process_survey_answer(self, chat_id: str, answer: Dict[str, str]) -> None:
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
                    formatted_answer = [opt.split(' ')[0] for opt in formatted_answer]
                
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
                self.generate_response_reflection(current_question["text"], answer["content"], survey, current_question),
                self.update_airtable_record(state["record_id"], update_data, survey)
            ]
            reflection, airtable_success = await asyncio.gather(*tasks)
            
            if reflection:
                await self.send_message_with_retry(chat_id, reflection)
                await asyncio.sleep(1.5)
            
            if airtable_success and answer.get("is_final", True):
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
            logger.info(f"Starting finish_survey for chat_id: {chat_id}")
            state = self.survey_state.get(chat_id)
            if not state:
                logger.warning(f"No state found for chat_id {chat_id} in finish_survey")
                return

            survey = state["survey"]
            logger.info(f"Survey type: {survey.name}")
            
            # Get all answers from state
            answers = {}
            for question in survey.questions:
                question_id = question["id"]
                if question_id in state.get("answers", {}):
                    answers[question["text"]] = state["answers"][question_id]
            
            # Generate and send summary if configured
            completion_config = survey.messages.get("completion", {})
            if completion_config.get("should_generate_summary", True):
                logger.info("Generating summary")
                logger.debug(f"Answers for summary: {json.dumps(answers, ensure_ascii=False)}")
                summary = self.generate_summary(answers, survey)
                logger.debug(f"Generated summary: {summary[:100]}...")  # Log first 100 chars
                
                logger.info("Sending summary")
                summary_response = await self.send_message_with_retry(chat_id, f"*סיכום השאלון שלך:*\n{summary}")
                if "error" in summary_response:
                    logger.error(f"Failed to send summary: {summary_response['error']}")
                    del self.survey_state[chat_id]
                    return

            # Add delay after summary
            await asyncio.sleep(2)

            # Send completion message
            await self.send_message_with_retry(chat_id, completion_config.get("text", "תודה על מילוי השאלון!"))

        except Exception as e:
            logger.error(f"Error in finish_survey: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בסיום השאלון. נא לנסות שוב.")
            if chat_id in self.survey_state:
                del self.survey_state[chat_id]

    async def send_default_thank_you(self, chat_id: str) -> None:
        """Send the default thank you message"""
        thank_you_message = """*תודה רבה על מילוי שאלון האפיון!* 🙏

אני אחזור אליך בקרוב עם תובנות מעמיקות ותוכנית פעולה מותאמת אישית.

בינתיים, אם יש לך שאלות נוספות או דברים שברצונך להוסיף, אשמח לשמוע! 💭"""
        await self.send_message_with_retry(chat_id, thank_you_message)

    async def handle_meeting_poll_response(self, chat_id: str, selected_option: str) -> None:
        """Handle response to meeting scheduling poll"""
        logger.info(f"Starting handle_meeting_poll_response for chat_id: {chat_id}")
        logger.info(f"Selected option: {selected_option}")
        
        state = self.survey_state.get(chat_id)
        if not state:
            logger.error(f"No state found for chat_id: {chat_id}")
            return
            
        if not state.get("waiting_for_meeting_response"):
            logger.error("State not waiting for meeting response")
            return

        try:
            logger.info("Updating Airtable with meeting preference")
            survey = state["survey"]
            table_id = survey.airtable_table_id
            
            # Update Airtable with the response
            update_data = {
                "מעוניין לקבוע פגישה": selected_option,
                "סטטוס": "הושלם"  # Make sure to update status to completed
            }
            
            logger.debug(f"Update data for Airtable: {json.dumps(update_data, ensure_ascii=False)}")
            table = self.airtable.table(AIRTABLE_BASE_ID, table_id)
            table.update(state["record_id"], update_data)
            logger.info("Successfully updated Airtable with meeting preference")
            
            if selected_option == "כן, אשמח כבר לקבוע זמן לפגישה 😊":
                try:
                    logger.info("User wants to schedule meeting, fetching meeting link")
                    # Get the meeting link from Airtable
                    record = table.get(state["record_id"])
                    meeting_link = record.get("fields", {}).get("קישור לפגישה")
                    
                    if meeting_link:
                        logger.info("Found meeting link, sending to user")
                        await self.send_message_with_retry(chat_id, f"""מעולה! 🎉
אשמח להיפגש ולדבר על הפתרונות שיכולים לעזור לך.

לקביעת הפגישה: {meeting_link}""")
                    else:
                        logger.error(f"Meeting link not found for record {state['record_id']}")
                        await self.send_default_thank_you(chat_id)
                except Exception as e:
                    logger.error(f"Error getting meeting link: {str(e)}")
                    logger.error(f"Stack trace: {traceback.format_exc()}")
                    await self.send_default_thank_you(chat_id)
            else:
                # Send thank you message for users who want a reminder later
                logger.info("Sending thank you message")
                await self.send_default_thank_you(chat_id)
                
        except Exception as e:
            logger.error(f"Error in handle_meeting_poll_response: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_default_thank_you(chat_id)
            
        finally:
            # Clean up state
            logger.info(f"Cleaning up state for chat_id: {chat_id}")
            if chat_id in self.survey_state:
                del self.survey_state[chat_id]
                logger.info("State cleaned up successfully")

    async def send_next_question(self, chat_id: str) -> None:
        """Send the next survey question"""
        state = self.survey_state.get(chat_id)
        if not state:
            return

        survey = state["survey"]
        if state["current_question"] < len(survey.questions):
            question = survey.questions[state["current_question"]]
            if question["type"] == "poll":
                response = await self.send_poll(chat_id, question)
                if "error" in response:
                    await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בשליחת השאלה. נא לנסות שוב.")
                    return
            else:
                response = await self.send_message_with_retry(chat_id, question["text"])
                if "error" in response:
                    return
        else:
            await self.finish_survey(chat_id)

    async def cleanup(self):
        """Cleanup resources"""
        try:
            if self.session and not self.session.closed:
                await self.session.close()
            if self.cleanup_task:
                self.cleanup_task.cancel()
                try:
                    await self.cleanup_task
                except asyncio.CancelledError:
                    pass
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

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
        """Update Airtable record asynchronously"""
        try:
            # Get cached record if available
            cached_record = self.get_cached_airtable_record(record_id, survey.airtable_table_id)
            if cached_record:
                # Merge new data with cached record
                cached_record.update(data)
                self.cache_airtable_record(record_id, survey.airtable_table_id, cached_record)
            
            # Update Airtable
            table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
            table.update(record_id, data)
            
            # Update cache with new data
            if not cached_record:
                self.cache_airtable_record(record_id, survey.airtable_table_id, data)
            
            return True
        except Exception as e:
            logger.error(f"Error updating Airtable record: {e}")
            return False

    async def schedule_next_question(self, chat_id: str, delay_seconds: int) -> None:
        """Schedule moving to the next question after a delay"""
        await asyncio.sleep(delay_seconds)
        
        state = self.survey_state.get(chat_id)
        if not state:
            return
        
        last_response_time = state.get("last_poll_response")
        if last_response_time and (datetime.now() - last_response_time).total_seconds() >= delay_seconds:
            logger.info(f"Advancing to next question for chat_id: {chat_id} after {delay_seconds} seconds of inactivity")
            state["current_question"] += 1
            state.pop("selected_options", None)
            state.pop("last_poll_response", None)
            await self.send_next_question(chat_id)

# Initialize the bot
logger.info("Initializing WhatsApp Survey Bot...")
bot = WhatsAppSurveyBot()
logger.info("Bot initialized successfully")

# FastAPI app
app = FastAPI()

@app.on_event("startup")
async def startup_event():
    """Start the cleanup task when the application starts"""
    await bot.start_cleanup_task()

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources when the application shuts down"""
    logger.info("Application shutting down, cleaning up resources...")
    await bot.cleanup()
    logger.info("Cleanup completed")

# Webhook handler function
async def handle_webhook(webhook_data: Dict) -> None:
    """Handle incoming webhook data"""
    session = None
    try:
        logger.info("Received new webhook")
        logger.debug(f"Webhook data: {json.dumps(webhook_data, ensure_ascii=False)}")
        
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
            await bot.handle_text_message(chat_id, text, sender_name)
            
        elif message_data["typeMessage"] == "audioMessage":
            voice_url = message_data["fileMessageData"]["downloadUrl"]
            logger.info(f"Received voice message from URL: {voice_url}")
            await bot.handle_voice_message(chat_id, voice_url)
            
        elif message_data["typeMessage"] == "pollUpdateMessage":
            poll_data = message_data["pollMessageData"]
            logger.info("Received poll update")
            logger.debug(f"Poll data: {json.dumps(poll_data, ensure_ascii=False)}")
            await bot.handle_poll_response(chat_id, poll_data)
            
    except Exception as e:
        logger.error(f"Error handling webhook: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise
    finally:
        if session and not session.closed:
            await session.close() 
