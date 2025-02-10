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
from dataclasses import dataclass
import threading
import asyncio
from fastapi import FastAPI
import aiohttp
import re
import time
import glob
from calendar_manager import CalendarManager

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
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_PROJECT_ID"
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
model = genai.GenerativeModel("gemini-2.0-pro-exp-02-05")
logger.info("Configured Gemini API")

# Airtable Configuration
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")

@dataclass
class SurveyDefinition:
    name: str
    trigger_phrases: List[str]
    airtable_table_id: str
    questions: List[Dict]
    airtable_base_id: str = None
    messages: Dict = None
    ai_prompts: Dict = None

    def __post_init__(self):
        self.airtable_base_id = self.airtable_base_id or os.getenv("AIRTABLE_BASE_ID")
        self.messages = self.messages or {
            "welcome": "ברוכים הבאים לשאלון!",
            "completion": {
                "text": "תודה רבה על מילוי השאלון!",
                "should_generate_summary": True
            },
            "timeout": "השאלון בוטל עקב חוסר פעילות. אנא התחל מחדש.",
            "error": "מצטערים, הייתה שגיאה בעיבוד התשובה. נא לנסות שוב."
        }
        self.ai_prompts = self.ai_prompts or {
            "reflections": {
                "empathetic": {
                    "name": "תגובה אמפתית",
                    "prompt": "צור תגובה אמפתית וחמה"
                },
                "professional": {
                    "name": "תגובה מקצועית",
                    "prompt": "צור תגובה מקצועית ותכליתית"
                }
            },
            "summary": {
                "prompt": "צור סיכום מקיף של כל התשובות בשאלון",
                "max_length": 500,
                "include_recommendations": True
            }
        }

def load_surveys_from_json() -> List[SurveyDefinition]:
    """Load all survey definitions from JSON files in the surveys directory"""
    surveys = []
    surveys_dir = 'surveys'
    
    logger.info(f"Loading surveys from directory: {surveys_dir}")
    
    if not os.path.exists(surveys_dir):
        logger.warning(f"Surveys directory {surveys_dir} does not exist, creating it")
        os.makedirs(surveys_dir)
        logger.info(f"Created surveys directory: {surveys_dir}")
        return []

    json_files = glob.glob(os.path.join(surveys_dir, '*.json'))
    logger.info(f"Found {len(json_files)} survey definition files")
    
    for file_path in json_files:
        try:
            logger.info(f"Loading survey from {file_path}")
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Validate required fields
            required_fields = ['name', 'trigger_phrases', 'airtable', 'questions']
            missing_fields = [field for field in required_fields if field not in data]
            if missing_fields:
                logger.error(f"Survey file {file_path} missing required fields: {missing_fields}")
                continue
                
            # Validate airtable configuration
            if 'table_id' not in data['airtable']:
                logger.error(f"Survey file {file_path} missing airtable.table_id")
                continue
                
            # Log survey details before creating
            logger.debug(f"Survey name: {data['name']}")
            logger.debug(f"Trigger phrases: {data['trigger_phrases']}")
            logger.debug(f"Number of questions: {len(data['questions'])}")
                
            survey = SurveyDefinition(
                name=data['name'],
                trigger_phrases=data['trigger_phrases'],
                airtable_table_id=data['airtable']['table_id'],
                airtable_base_id=data['airtable'].get('base_id'),
                questions=data['questions'],
                messages=data.get('messages'),  # Optional
                ai_prompts=data.get('ai_prompts')  # Optional
            )
            surveys.append(survey)
            logger.info(f"Successfully loaded survey: {survey.name} from {file_path}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in survey file {file_path}: {str(e)}")
        except Exception as e:
            logger.error(f"Error loading survey from {file_path}: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            
    if not surveys:
        logger.warning("No valid surveys were loaded")
    else:
        logger.info(f"Successfully loaded {len(surveys)} surveys")
        
    return surveys

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
        
        # Initialize emoji and special characters mapping
        self.emoji_mapping = {
            "⚡": "",
            "⏱️": "",
            "⏰": "",
            "✅": "",
            "❌": "",
            "💭": "",
            "😊": "",
            "🙈": "",
            "–": "-"  # Replace special dash with regular dash
        }
        
        # Initialize Airtable client
        self.airtable = Api(AIRTABLE_API_KEY)
        logger.info("Initialized Airtable client")
        
        # Initialize aiohttp session for reuse
        self.session = None
        
        # Load surveys once during initialization
        try:
            self.surveys = load_surveys_from_json()
            self.survey_table_ids = {}
            for survey in self.surveys:
                self._validate_survey_definition(survey)
                self.survey_table_ids[survey.name] = survey.airtable_table_id
                logger.info(f"Loaded survey: {survey.name} with table ID: {survey.airtable_table_id}")
        except Exception as e:
            logger.error(f"Error loading surveys: {str(e)}")
            self.surveys = []
            self.survey_table_ids = {}

        self.calendar_manager = CalendarManager()
        self.meeting_state = {}

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
        
        # Clean message for WhatsApp
        message = message.replace('**', '*').replace('__', '_')  # Convert markdown
        message = '\n'.join(line.strip() for line in message.split('\n'))  # Clean newlines
        message = message.strip()
        
        logger.debug(f"Sending message to {chat_id}: {message[:100]}...")  # Log first 100 chars
        
        while retries < self.MAX_RETRIES:
            try:
                url = f"{GREEN_API_BASE_URL}/sendMessage/{API_TOKEN_INSTANCE}"
                payload = {
                    "chatId": chat_id,
                    "message": message
                }
                
                async with session.post(url, json=payload) as response:
                    response_text = await response.text()
                    logger.debug(f"Response from API: {response_text}")
                    
                    if response.status == 200:
                        try:
                            response_data = json.loads(response_text)
                            logger.info(f"Message sent successfully to {chat_id}")
                            return response_data
                        except json.JSONDecodeError as e:
                            logger.error(f"Invalid JSON response: {str(e)}")
                            logger.error(f"Response text: {response_text}")
                            last_error = "Invalid JSON response"
                    else:
                        logger.error(f"API error: {response.status} - {response_text}")
                        last_error = f"HTTP {response.status}"
                    
                retries += 1
                if retries < self.MAX_RETRIES:
                    logger.info(f"Retrying in {self.RETRY_DELAY} seconds...")
                    await asyncio.sleep(self.RETRY_DELAY)
                
            except Exception as e:
                logger.error(f"Error sending message: {str(e)}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
                last_error = str(e)
                retries += 1
                if retries < self.MAX_RETRIES:
                    logger.info(f"Retrying in {self.RETRY_DELAY} seconds...")
                    await asyncio.sleep(self.RETRY_DELAY)
                
        logger.error(f"Failed to send message after {self.MAX_RETRIES} retries: {last_error}")
        return {"error": f"Failed after {self.MAX_RETRIES} retries: {last_error}"}

    def get_survey_by_trigger(self, message: str) -> Optional[SurveyDefinition]:
        """Find the appropriate survey based on trigger phrase"""
        try:
            logger.info(f"Looking for survey trigger in message: {message}")
            
            if not message:
                logger.warning("Empty message received")
                return None
                
            # Clean and normalize message for comparison
            clean_message = message.lower().strip()
            clean_message = ' '.join(clean_message.split())  # Normalize whitespace
            clean_message = clean_message.replace('–', '-').replace('—', '-')  # Normalize dashes
            logger.debug(f"Cleaned message: {clean_message}")
            
            # Log available surveys and triggers
            logger.debug(f"Available surveys: {[s.name for s in self.surveys]}")
            all_triggers = [(s.name, t) for s in self.surveys for t in s.trigger_phrases]
            logger.debug(f"Available triggers: {all_triggers}")
            
            for survey in self.surveys:
                for trigger in survey.trigger_phrases:
                    # Clean and normalize trigger
                    clean_trigger = trigger.lower().strip()
                    clean_trigger = ' '.join(clean_trigger.split())
                    clean_trigger = clean_trigger.replace('–', '-').replace('—', '-')
                    
                    # Try exact match first
                    if clean_message == clean_trigger:
                        logger.info(f"Found exact match for survey: {survey.name} with trigger: {trigger}")
                        return survey
                        
                    # Then try contains match
                    if clean_trigger in clean_message:
                        logger.info(f"Found partial match for survey: {survey.name} with trigger: {trigger}")
                        return survey
                        
            logger.info("No matching survey found")
            return None
            
        except Exception as e:
            logger.error(f"Error in get_survey_by_trigger: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
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
            
            # Validate required fields
            if 'text' not in question or 'options' not in question:
                logger.error("Missing required fields in poll question")
                return {"error": "Missing required fields"}
                
            if not question['options']:
                logger.error("No options provided for poll")
                return {"error": "No options provided"}
            
            # Clean text and options
            question_text = question['text']
            question_text = question_text.replace('**', '*').replace('__', '_')  # Convert markdown
            question_text = '\n'.join(line.strip() for line in question_text.split('\n'))  # Clean newlines
            question_text = question_text.strip()
            
            # Format options according to API spec
            formatted_options = []
            for opt in question["options"]:
                # Clean option text
                opt_text = opt.strip()
                opt_text = opt_text.replace('**', '*').replace('__', '_')  # Convert markdown
                formatted_options.append({"optionName": opt_text})
            
            # Construct the full URL according to the API documentation
            url = f"https://api.greenapi.com/waInstance{ID_INSTANCE}/sendPoll/{API_TOKEN_INSTANCE}"
            
            payload = {
                "chatId": chat_id,
                "message": question_text,
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

    def clean_text_for_airtable(self, text: str) -> str:
        """Clean text by replacing special characters for Airtable compatibility"""
        if not text:
            return text
            
        # Replace various types of dashes with regular dash
        text = text.replace('–', '-').replace('—', '-').replace('‒', '-').replace('―', '-')
        
        # Remove multiple spaces and trim
        text = ' '.join(text.split())
        
        return text.strip()

    async def process_survey_answer(self, chat_id: str, answer: Dict[str, str]) -> None:
        """Process a survey answer"""
        try:
            logger.info(f"Starting process_survey_answer for chat_id: {chat_id}")
            logger.debug(f"Answer data: {json.dumps(answer, ensure_ascii=False)}")
            
            # Validate input parameters
            if not chat_id or not answer:
                logger.error("Missing required parameters")
                return
                
            if not isinstance(answer, dict) or "type" not in answer or "content" not in answer:
                logger.error(f"Invalid answer format: {answer}")
                return

            # Validate survey state
            if chat_id not in self.survey_state:
                logger.warning(f"No active survey found for chat_id: {chat_id}")
                return

            state = self.survey_state[chat_id]
            state['last_activity'] = datetime.now()
            
            # Validate required state fields
            if "survey" not in state:
                logger.error(f"Invalid survey state for chat_id {chat_id}: missing survey")
                await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד השאלון. נא להתחיל מחדש.")
                del self.survey_state[chat_id]
                return
                
            if "current_question" not in state:
                logger.error(f"Invalid survey state for chat_id {chat_id}: missing current_question")
                await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד השאלון. נא להתחיל מחדש.")
                del self.survey_state[chat_id]
                return
                
            survey = state["survey"]
            current_question_index = state["current_question"]
            
            # Validate question index
            if current_question_index >= len(survey.questions):
                logger.error(f"Invalid question index {current_question_index} for chat_id {chat_id}")
                await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד השאלון. נא להתחיל מחדש.")
                del self.survey_state[chat_id]
                return
                
            current_question = survey.questions[current_question_index]
            question_id = current_question["id"]
            
            logger.info(f"Processing answer for chat_id: {chat_id}, question: {question_id}")
            logger.debug(f"Current question: {json.dumps(current_question, ensure_ascii=False)}")
            
            # Initialize answers if not exists
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
                    # Clean text for regular answers
                    formatted_answer = ' '.join(formatted_answer.split())  # Remove extra spaces
                    formatted_answer = formatted_answer.replace('–', '-').replace('—', '-')  # Normalize dashes
                    formatted_answer = formatted_answer.strip()
                
                state["answers"][question_id] = formatted_answer
                logger.info(f"Formatted answer: {formatted_answer}")
                logger.debug(f"Updated state answers: {json.dumps(state['answers'], ensure_ascii=False)}")
                
            except Exception as e:
                logger.error(f"Error formatting answer: {str(e)}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
                await self.send_message_with_retry(
                    chat_id, 
                    survey.messages["error"]
                )
                return
            
            # Prepare Airtable update data
            update_data = {question_id: formatted_answer}
            if state["current_question"] > 0:
                update_data["סטטוס"] = "בטיפול"
            
            logger.info(f"Updating Airtable with data: {json.dumps(update_data, ensure_ascii=False)}")
            
            # First update Airtable
            airtable_success = await self.update_airtable_record(state["record_id"], update_data, survey)
            logger.info(f"Airtable update success: {airtable_success}")
            
            if not airtable_success:
                logger.error("Failed to update Airtable, sending error message")
                await self.send_message_with_retry(
                    chat_id, 
                    survey.messages["error"]
                )
                return
            
            try:
                # Then generate reflection if needed
                reflection = await self.generate_response_reflection(
                    current_question["text"], 
                    answer["content"], 
                    survey, 
                    {**current_question, "chat_id": chat_id}
                )
                
                if reflection:
                    logger.info("Sending reflection message")
                    logger.debug(f"Reflection: {reflection}")
                    await self.send_message_with_retry(chat_id, reflection)
                    await asyncio.sleep(1.5)
                
                # Move to next question
                state["current_question"] += 1
                state.pop("selected_options", None)
                state.pop("last_poll_response", None)
                
                logger.info(f"Moving to next question: {state['current_question']}")
                
                if state["current_question"] >= len(survey.questions):
                    logger.info("Survey completed, updating final status")
                    await self.update_airtable_record(
                        state["record_id"], 
                        {"סטטוס": "הושלם"}, 
                        survey
                    )
                    await self.finish_survey(chat_id)
                else:
                    await self.send_next_question(chat_id)
                    
            except Exception as e:
                logger.error(f"Error processing reflection or next question: {str(e)}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
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
        try:
            logger.info(f"Starting handle_meeting_poll_response for chat_id: {chat_id}")
            logger.info(f"Selected option: {selected_option}")
            
            state = self.survey_state.get(chat_id)
            if not state:
                logger.error(f"No state found for chat_id: {chat_id}")
                return
                
            if not state.get("waiting_for_meeting_response"):
                logger.error("State not waiting for meeting response")
                return
                
            if "survey" not in state:
                logger.error(f"Invalid survey state for chat_id {chat_id}: missing survey")
                return
                
            if "record_id" not in state:
                logger.error(f"Invalid survey state for chat_id {chat_id}: missing record_id")
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
                        if not record or "fields" not in record:
                            logger.error(f"Invalid record data for {state['record_id']}")
                            await self.send_default_thank_you(chat_id)
                            return
                            
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
                logger.error(f"Error updating Airtable: {str(e)}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
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

    async def get_airtable_field_value(self, record_id: str, field_name: str, survey: SurveyDefinition) -> Optional[str]:
        """Get a specific field value from an Airtable record"""
        try:
            # Check cache first
            cached_record = self.get_cached_airtable_record(record_id, survey.airtable_table_id)
            if cached_record and field_name in cached_record:
                return cached_record[field_name]
            
            # If not in cache, fetch from Airtable
            table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
            record = table.get(record_id)
            if record and "fields" in record and field_name in record["fields"]:
                # Update cache
                self.cache_airtable_record(record_id, survey.airtable_table_id, record["fields"])
                return record["fields"][field_name]
            return None
        except Exception as e:
            logger.error(f"Error getting Airtable field value: {e}")
            return None

    async def send_next_question(self, chat_id: str) -> None:
        """Send the next survey question"""
        try:
            state = self.survey_state.get(chat_id)
            if not state:
                logger.warning(f"No survey state found for chat_id: {chat_id}")
                return

            survey = state["survey"]
            if state["current_question"] >= len(survey.questions):
                logger.info(f"Survey completed for chat_id: {chat_id}")
                await self.finish_survey(chat_id)
                return
                
            question = survey.questions[state["current_question"]]
            logger.info(f"Sending question {state['current_question']} to {chat_id}")
            logger.debug(f"Question data: {json.dumps(question, ensure_ascii=False)}")
            
            # Check if question text contains Airtable field placeholders
            question_text = question["text"]
            if "{{" in question_text and "}}" in question_text:
                try:
                    # Find all placeholders in format {{field_name}}
                    placeholders = re.findall(r'\{\{(.*?)\}\}', question_text)
                    logger.debug(f"Found placeholders: {placeholders}")
                    for field_name in placeholders:
                        field_value = await self.get_airtable_field_value(state["record_id"], field_name, survey)
                        if field_value:
                            question_text = question_text.replace(f"{{{{{field_name}}}}}", str(field_value))
                            logger.debug(f"Replaced placeholder {field_name} with value: {field_value}")
                except Exception as e:
                    logger.error(f"Error processing placeholders: {str(e)}")
                    logger.error(f"Stack trace: {traceback.format_exc()}")
            
            if question["type"] == "poll":
                logger.info("Sending poll question")
                response = await self.send_poll(chat_id, {**question, "text": question_text})
                if "error" in response:
                    logger.error(f"Error sending poll: {response['error']}")
                    await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בשליחת השאלה. נא לנסות שוב.")
                    return
            else:
                logger.info("Sending text question")
                response = await self.send_message_with_retry(chat_id, question_text)
                if "error" in response:
                    logger.error(f"Error sending message: {response['error']}")
                    return
                    
        except Exception as e:
            logger.error(f"Error in send_next_question: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בשליחת השאלה. נא לנסות שוב.")

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
        """Update Airtable record with retries"""
        try:
            logger.info(f"Starting Airtable update for record {record_id}")
            logger.debug(f"Update data: {json.dumps(data, ensure_ascii=False)}")
            
            if not record_id or not data or not survey:
                logger.error("Missing required parameters for Airtable update")
                return False
            
            # Get cached record if available
            cached_record = self.get_cached_airtable_record(record_id, survey.airtable_table_id)
            if cached_record:
                # Merge new data with cached record
                cached_record.update(data)
                self.cache_airtable_record(record_id, survey.airtable_table_id, cached_record)
                logger.debug("Updated cache with new data")
            
            # Update Airtable with retries
            retries = 0
            max_retries = 3
            retry_delay = 2  # seconds
            
            while retries < max_retries:
                try:
                    table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
                    table.update(record_id, data)
                    logger.info(f"Successfully updated Airtable record {record_id}")
                    
                    # Update cache with new data
                    if not cached_record:
                        self.cache_airtable_record(record_id, survey.airtable_table_id, data)
                    
                    return True
                    
                except Exception as e:
                    retries += 1
                    logger.warning(f"Airtable update attempt {retries} failed: {str(e)}")
                    
                    if hasattr(e, 'response'):
                        logger.error(f"Airtable error response: {e.response.text if hasattr(e.response, 'text') else e.response}")
                    
                    if retries < max_retries:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    else:
                        logger.error(f"Failed to update Airtable after {max_retries} attempts")
                        return False
                
        except Exception as e:
            logger.error(f"Error updating Airtable record: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
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

    async def handle_survey_response(self, chat_id: str, message: str) -> bool:
        """Handle a response when user is in an active survey. Returns True if handled, False otherwise."""
        try:
            if chat_id not in self.survey_state:
                return False
                
            state = self.survey_state[chat_id]
            if "survey" not in state or "current_question" not in state:
                logger.error(f"Invalid survey state for {chat_id}")
                return False
                
            logger.info(f"Processing survey response for question {state['current_question']}")
            await self.process_survey_answer(chat_id, {"type": "text", "content": message})
            return True
            
        except Exception as e:
            logger.error(f"Error in handle_survey_response: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            return False

    async def handle_text_message(self, chat_id: str, message: str, sender_name: str = "") -> None:
        """Handle incoming text messages"""
        try:
            logger.info(f"Starting handle_text_message for chat_id: {chat_id}, message: {message}")
            message = message.strip()

            # First check if user is in an active survey
            if chat_id in self.survey_state:
                state = self.survey_state[chat_id]
                logger.info(f"Found active survey state for {chat_id}")
                # Create a copy of state without the survey object for logging
                log_state = {k: v for k, v in state.items() if k != 'survey'}
                logger.debug(f"Current survey state: {json.dumps(log_state, ensure_ascii=False)}")
                
                # Check for stop survey command
                if message.lower() in ["הפסקת שאלון", "עצור שאלון", "ביטול שאלון", "stop"]:
                    logger.info(f"Received stop survey command from {chat_id}")
                    survey = state.get("survey")
                    record_id = state.get("record_id")
                    
                    if survey and record_id:
                        # Update Airtable record status
                        await self.update_airtable_record(
                            record_id,
                            {"סטטוס": "בוטל"},
                            survey
                        )
                    
                    # Clean up state
                    del self.survey_state[chat_id]
                    await self.send_message_with_retry(
                        chat_id,
                        "השאלון הופסק. אתה מוזמן להתחיל מחדש בכל זמן שתרצה 😊"
                    )
                    return

                # Process as survey answer if we have valid survey state
                if "survey" in state and "current_question" in state:
                    logger.info(f"Processing survey answer for chat_id: {chat_id}, question index: {state['current_question']}")
                    await self.process_survey_answer(chat_id, {"type": "text", "content": message})
                    return
                else:
                    logger.error(f"Invalid survey state for {chat_id}: {state}")
                    del self.survey_state[chat_id]

            # Then check if we're in the middle of scheduling a meeting
            if chat_id in self.meeting_state:
                meeting_state = self.meeting_state[chat_id]
                if meeting_state['state'] == 'waiting_for_day':
                    logger.info(f"Handling day selection for meeting: {message}")
                    await self.handle_day_selection(chat_id, message)
                    return
                elif meeting_state['state'] == 'waiting_for_time':
                    logger.info(f"Handling time selection for meeting: {message}")
                    await self.handle_time_selection(chat_id, message)
                    return

            # Check for meeting request keywords
            if message.lower() in ["פגישה", "קביעת פגישה", "תיאום פגישה"]:
                logger.info("Handling new meeting request")
                await self.handle_meeting_request(chat_id)
                return

            # Only check for new survey trigger if not in any active state
            if chat_id not in self.survey_state and chat_id not in self.meeting_state:
                logger.info("Checking for new survey trigger")
                new_survey = self.get_survey_by_trigger(message)
                if new_survey:
                    logger.info(f"Found new survey trigger: {new_survey.name}")
                    record_id = self.create_initial_record(chat_id, sender_name, new_survey)
                    if record_id:
                        self.survey_state[chat_id] = {
                            "current_question": 0,
                            "answers": {},
                            "record_id": record_id,
                            "survey": new_survey,
                            "last_activity": datetime.now()
                        }
                        await self.send_message_with_retry(chat_id, new_survey.messages["welcome"])
                        await asyncio.sleep(1.5)
                        await self.send_next_question(chat_id)
                    else:
                        await self.send_message_with_retry(
                            chat_id, 
                            "מצטערים, הייתה שגיאה בהתחלת השאלון. נא לנסות שוב."
                        )
                    return

        except Exception as e:
            logger.error(f"Error handling text message: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד ההודעה. נא לנסות שוב.")

    async def handle_poll_response(self, chat_id: str, poll_data: Dict) -> None:
        """Handle poll response"""
        try:
            logger.info(f"Starting handle_poll_response for chat_id: {chat_id}")
            logger.debug(f"Poll data: {json.dumps(poll_data, ensure_ascii=False)}")
            
            if chat_id not in self.survey_state:
                logger.warning(f"Received poll response for unknown chat_id: {chat_id}")
                return

            state = self.survey_state[chat_id]
            state['last_activity'] = datetime.now()

            # Check if this is a meeting scheduling poll response
            if state.get("waiting_for_meeting_response"):
                logger.info("Processing meeting scheduling poll response")
                selected_options = []
                if "votes" in poll_data:
                    for vote in poll_data["votes"]:
                        if "optionVoters" in vote and chat_id in vote.get("optionVoters", []):
                            selected_options.append(vote["optionName"])
                
                if selected_options:
                    logger.info(f"Selected meeting option: {selected_options[0]}")
                    await self.handle_meeting_poll_response(chat_id, selected_options[0])
                else:
                    logger.warning("No meeting option selected")
                return

            # Regular poll handling continues...
            if "survey" not in state:
                logger.error(f"Invalid survey state for chat_id {chat_id}: missing survey")
                return
                
            if "current_question" not in state:
                logger.error(f"Invalid survey state for chat_id {chat_id}: missing current_question")
                return
                
            survey = state["survey"]
            if state["current_question"] >= len(survey.questions):
                logger.error(f"Invalid question index {state['current_question']} for chat_id {chat_id}")
                return
                
            current_question = survey.questions[state["current_question"]]
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
            
            # Store the last poll response time for multiple choice questions
            if current_question.get("multipleAnswers", False):
                current_time = datetime.now()
                state["last_poll_response"] = current_time
                state.setdefault("selected_options", set())
            
            selected_options = []
            if "votes" in poll_data:
                for vote in poll_data["votes"]:
                    if "optionVoters" in vote and chat_id in vote.get("optionVoters", []):
                        selected_options.append(vote["optionName"])
            
            if selected_options:
                if current_question.get("multipleAnswers", False):
                    # For multiple choice questions, update the set of selected options
                    state["selected_options"].update(selected_options)
                    answer_content = ", ".join(state["selected_options"])
                    logger.info(f"Updated multiple choice selections: {answer_content}")
                    
                    # Save the current selections but don't move to next question yet
                    await self.process_survey_answer(chat_id, {
                        "type": "poll",
                        "content": answer_content,
                        "is_final": False
                    })
                    
                    # Send a message to inform the user they can select more options
                    await self.send_message_with_retry(chat_id, "ניתן לבחור אפשרויות נוספות. כשסיימת, המתן 3 שניות והשאלון ימשיך אוטומטית.")
                    
                    # Schedule a check to move to the next question after 3 seconds
                    asyncio.create_task(self.schedule_next_question(chat_id, 3))
                else:
                    # For single choice questions, proceed as normal
                    answer_content = ", ".join(selected_options)
                    logger.info(f"Poll response processed - Question: {question_id}, Selected options: {answer_content}")
                    
                    await self.process_survey_answer(chat_id, {
                        "type": "poll",
                        "content": answer_content,
                        "is_final": True
                    })
            else:
                logger.warning(f"No valid options selected for chat_id: {chat_id}")
                
        except Exception as e:
            logger.error(f"Error handling poll response: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד התשובה. נא לנסות שוב.")

    async def handle_meeting_request(self, chat_id: str) -> None:
        """טיפול בבקשה לקביעת פגישה"""
        available_days = self.calendar_manager.get_available_days(datetime.now())
        
        # יצירת לוח שנה ויזואלי
        calendar_view = self._create_calendar_view(available_days)
        await self.send_message_with_retry(chat_id, 
            "בחר את היום המועדף לפגישה מהימים הפנויים (מסומנים בכחול):\n\n" + calendar_view)
        
        # שמירת מצב הפגישה
        self.meeting_state[chat_id] = {
            'state': 'waiting_for_day',
            'available_days': available_days
        }

    def _create_calendar_view(self, available_days: List[datetime]) -> str:
        """יצירת תצוגת לוח שנה ויזואלית"""
        today = datetime.now()
        month_start = today.replace(day=1)
        
        # כותרת החודש
        calendar_str = f"{month_start.strftime('%B %Y')}\n"
        calendar_str += "א  ב  ג  ד  ה  ו  ש\n"
        
        # מילוי ימי החודש
        week = []
        first_day = month_start.weekday()
        
        # רווחים לתחילת החודש
        for _ in range(first_day):
            week.append("  ")
            
        for day in range(1, 32):
            try:
                current = month_start.replace(day=day)
                if current in available_days:
                    week.append(f"{day:02d}")
                else:
                    week.append("--")
                    
                if len(week) == 7:
                    calendar_str += "  ".join(week) + "\n"
                    week = []
            except ValueError:  # חודש נגמר
                break
                
        if week:
            calendar_str += "  ".join(week)
            
        return f"```\n{calendar_str}\n```"

    async def handle_day_selection(self, chat_id: str, message: str) -> None:
        """טיפול בבחירת יום"""
        try:
            selected_day = int(message)
            state = self.meeting_state.get(chat_id)
            
            if not state or state['state'] != 'waiting_for_day':
                return
                
            # מציאת היום הנבחר
            selected_date = None
            for day in state['available_days']:
                if day.day == selected_day:
                    selected_date = day
                    break
                    
            if not selected_date:
                await self.send_message_with_retry(chat_id, "נא לבחור יום פנוי מהלוח המוצג")
                return
                
            # קבלת חלונות זמן פנויים
            slots = self.calendar_manager.get_available_slots(selected_date)
            slots_message = "בחר שעה מהשעות הפנויות:\n\n"
            
            for i, slot in enumerate(slots, 1):
                slots_message += f"{i}. {slot['start']}-{slot['end']}\n"
                
            await self.send_message_with_retry(chat_id, slots_message)
            
            # עדכון מצב
            self.meeting_state[chat_id].update({
                'state': 'waiting_for_time',
                'selected_date': selected_date,
                'available_slots': slots
            })
            
        except ValueError:
            await self.send_message_with_retry(chat_id, "נא להזין מספר יום תקין")

    async def handle_time_selection(self, chat_id: str, message: str) -> None:
        """טיפול בבחירת שעה"""
        try:
            slot_index = int(message) - 1
            state = self.meeting_state.get(chat_id)
            
            if not state or state['state'] != 'waiting_for_time':
                return
                
            slots = state['available_slots']
            if slot_index < 0 or slot_index >= len(slots):
                await self.send_message_with_retry(chat_id, "נא לבחור מספר חלון זמן תקין")
                return
                
            selected_slot = slots[slot_index]
            selected_date = state['selected_date']
            
            # יצירת אובייקט datetime לזמן הנבחר
            hour, minute = map(int, selected_slot['start'].split(':'))
            meeting_time = selected_date.replace(hour=hour, minute=minute)
            
            # קביעת הפגישה
            if self.calendar_manager.schedule_meeting(meeting_time):
                confirmation = (
                    f"*הפגישה נקבעה בהצלחה!*\n\n"
                    f"📅 תאריך: {meeting_time.strftime('%d/%m/%Y')}\n"
                    f"🕒 שעה: {selected_slot['start']}\n"
                    f"⏱️ משך: 30 דקות\n\n"
                    f"הפגישה נוספה ליומן שלך ותקבל תזכורת לפני הפגישה."
                )
                await self.send_message_with_retry(chat_id, confirmation)
            else:
                await self.send_message_with_retry(chat_id, "מצטערים, הייתה בעיה בקביעת הפגישה. נא לנסות שוב.")
                
            # ניקוי מצב
            del self.meeting_state[chat_id]
            
        except ValueError:
            await self.send_message_with_retry(chat_id, "נא להזין מספר חלון זמן תקין")

    async def process_message(self, message_data: Dict) -> None:
        """עדכון הפונקציה הקיימת לטיפול בהודעות"""
        chat_id = message_data.get('chatId')
        message_text = message_data.get('messageText', '').strip()
        
        # טיפול בבקשות פגישה
        if message_text.lower() in ["פגישה", "קביעת פגישה", "תיאום פגישה"]:
            await self.handle_meeting_request(chat_id)
            return
            
        # טיפול בבחירת יום
        if chat_id in self.meeting_state and self.meeting_state[chat_id]['state'] == 'waiting_for_day':
            await self.handle_day_selection(chat_id, message_text)
            return
            
        # טיפול בבחירת שעה
        if chat_id in self.meeting_state and self.meeting_state[chat_id]['state'] == 'waiting_for_time':
            await self.handle_time_selection(chat_id, message_text)
            return
        
        # המשך הטיפול הרגיל בהודעות
        # Process the rest of the message handling logic

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

@app.post("/webhook")
async def webhook(request: dict):
    """Handle incoming webhook from Green API"""
    try:
        logger.info("Received webhook request")
        logger.debug(f"Request data: {json.dumps(request, ensure_ascii=False)}")
        
        await handle_webhook(request)
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        return {"status": "error", "message": str(e)}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

async def handle_webhook(webhook_data: Dict) -> None:
    """Handle incoming webhook data"""
    try:
        logger.info("Processing webhook data")
        logger.debug(f"Webhook data: {json.dumps(webhook_data, ensure_ascii=False)}")
        
        # Validate webhook data structure
        if not isinstance(webhook_data, dict):
            logger.error(f"Invalid webhook data type: {type(webhook_data)}")
            return
            
        if "typeWebhook" not in webhook_data:
            logger.error("Missing typeWebhook in webhook data")
            return
            
        webhook_type = webhook_data["typeWebhook"]
        if webhook_type != "incomingMessageReceived":
            logger.debug(f"Ignoring webhook of type: {webhook_type}")
            return

        # Extract and validate message data
        message_data = webhook_data.get("messageData")
        sender_data = webhook_data.get("senderData")
        
        if not message_data or not sender_data:
            logger.error("Missing message_data or sender_data")
            return
            
        chat_id = sender_data.get("chatId")
        if not chat_id:
            logger.error("Missing chatId in sender data")
            return
            
        message_type = message_data.get("typeMessage")
        if not message_type:
            logger.error("Missing typeMessage in message data")
            return
            
        sender_name = sender_data.get("senderName", "")
        logger.info(f"Processing {message_type} from {chat_id} ({sender_name})")

        # Handle different message types
        if message_type == "textMessage":
            text_data = message_data.get("textMessageData", {})
            text = text_data.get("textMessage", "").strip()
            
            if not text:
                logger.warning("Empty text message received")
                return
                
            logger.info(f"Processing text message: {text[:100]}...")  # Log first 100 chars
            await bot.handle_text_message(chat_id, text, sender_name)
            
        elif message_type == "audioMessage":
            file_data = message_data.get("fileMessageData", {})
            voice_url = file_data.get("downloadUrl")
            
            if not voice_url:
                logger.error("Missing voice message URL")
                return
                
            logger.info(f"Processing voice message from URL: {voice_url}")
            await bot.handle_voice_message(chat_id, voice_url)
            
        elif message_type == "pollUpdateMessage":
            poll_data = message_data.get("pollMessageData")
            if not poll_data:
                logger.error("Missing poll message data")
                return
                
            logger.info("Processing poll update")
            logger.debug(f"Poll data: {json.dumps(poll_data, ensure_ascii=False)}")
            await bot.handle_poll_response(chat_id, poll_data)
            
        else:
            logger.warning(f"Unhandled message type: {message_type}")
            
    except Exception as e:
        logger.error(f"Error in handle_webhook: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        # Don't re-raise to keep webhook endpoint running 
