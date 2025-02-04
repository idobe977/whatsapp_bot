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
from survey_definitions import AVAILABLE_SURVEYS, SurveyDefinition
import threading
import asyncio
from fastapi import FastAPI
import aiohttp

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
        self.waiting_for_transcription = {}
        self.MAX_RETRIES = 3
        self.RETRY_DELAY = 2  # seconds
        self.SURVEY_TIMEOUT = 30  # minutes
        self.cleanup_task = None
        
        # Initialize Airtable client
        self.airtable = Api(AIRTABLE_API_KEY)
        logger.info("Initialized Airtable client")
        
        # Validate all survey definitions
        for survey in AVAILABLE_SURVEYS:
            self._validate_survey_definition(survey)
            if survey.name not in SURVEY_TABLE_IDS:
                raise ValueError(f"Missing table ID for survey: {survey.name}")
            survey.airtable_table_id = SURVEY_TABLE_IDS[survey.name]

    def _validate_survey_definition(self, survey: SurveyDefinition) -> None:
        """Validate survey definition has all required fields"""
        required_fields = ['name', 'trigger_phrases', 'questions']
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

    async def send_message_with_retry(self, chat_id: str, message: str) -> Dict:
        """Send a message with retry mechanism"""
        retries = 0
        last_error = None
        
        while retries < self.MAX_RETRIES:
            try:
                response = self.send_message(chat_id, message)
                if 'error' not in response:
                    return response
                    
                last_error = response['error']
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
            if any(trigger in message for trigger in survey.trigger_phrases):
                return survey
        return None

    def get_answer_type_for_airtable(self, answer_type: str) -> str:
        """Convert internal answer type to Airtable single select value"""
        type_mapping = {
            "text": "טקסט",
            "voice": "הקלטה",
            "poll": "סקר"
        }
        return type_mapping.get(answer_type, "טקסט")

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

    def send_message(self, chat_id: str, message: str) -> Dict:
        """Send a message to a WhatsApp user"""
        try:
            logger.info(f"Sending WhatsApp message to {chat_id}")
            logger.debug(f"Message content: {message[:100]}...")  # Log first 100 chars
            
            url = f"{GREEN_API_BASE_URL}/sendMessage/{API_TOKEN_INSTANCE}"
            payload = {
                "chatId": chat_id,
                "message": message
            }
            response = requests.post(url, json=payload)
            response.raise_for_status()
            
            response_data = response.json()
            logger.info(f"Message sent successfully to {chat_id}")
            logger.debug(f"Green API response: {response_data}")
            return response_data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send WhatsApp message to {chat_id}: {str(e)}")
            logger.error(f"Response status code: {getattr(e.response, 'status_code', 'N/A')}")
            logger.error(f"Response content: {getattr(e.response, 'text', 'N/A')}")
            return {"error": str(e)}

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

    def get_audio_duration(self, audio_path: str) -> Optional[float]:
        """Get duration of audio file in seconds"""
        try:
            audio = OggOpus(audio_path)
            return audio.info.length
        except Exception as e:
            logger.error(f"Error getting audio duration: {str(e)}")
            return None

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
                    
                    # Generate and send reflection
                    reflection = await self.generate_response_reflection(current_question["text"], transcribed_text)
                    if reflection:
                        await self.send_message_with_retry(chat_id, reflection)
                        await asyncio.sleep(1.5)  # Add a small delay before next question
                    
                    # Move to next question
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

    async def generate_response_reflection(self, question: str, answer: str) -> Optional[str]:
        """Generate a reflective response based on the user's answer"""
        try:
            prompt = f"""
            בהתבסס על התשובה של המשתמש לשאלה, צור תגובה קצרה ואמפתית שמשקפת את מה שהוא אמר.
            השתמש בטון חם ואנושי. התגובה צריכה להיות קצרה (1-2 משפטים).
            
            שאלה: {question}
            תשובה: {answer}
            
            הנחיות:
            1. שקף את התוכן העיקרי של התשובה
            2. השתמש בשפה חיובית ומעריכה
            3. הימנע מלחזור על התשובה מילה במילה
            4. אל תוסיף מידע חדש
            """
            
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"Error generating reflection: {str(e)}")
            return None

    async def handle_transcription_summary(self, chat_id: str, summary: str) -> None:
        """Handle incoming transcription summary from the other bot"""
        logger.info(f"Received transcription summary for chat_id: {chat_id}")
        logger.debug(f"Summary content: {summary[:100]}...")  # Log first 100 chars

        if chat_id not in self.waiting_for_transcription:
            logger.warning(f"Received transcription summary for {chat_id} but not waiting for one")
            return

        if chat_id not in self.survey_state:
            logger.warning(f"Received transcription summary for {chat_id} but user is no longer in survey")
            self.waiting_for_transcription.pop(chat_id)
            return

        waiting_info = self.waiting_for_transcription.pop(chat_id)
        
        # Check if the summary is coming within reasonable time (2 minutes)
        if datetime.now() - waiting_info["timestamp"] > timedelta(minutes=2):
            logger.warning(f"Received transcription summary for {chat_id} but it's too old")
            await self.send_message_with_retry(chat_id, "התמלול לקח יותר מדי זמן. נא לשלוח את ההקלטה שוב.")
            return

        # Validate summary
        if not summary or len(summary.strip()) < 10:
            logger.warning(f"Received invalid or too short summary for {chat_id}")
            await self.send_message_with_retry(chat_id, "התמלול שהתקבל אינו תקין. נא לשלוח את ההקלטה שוב.")
            return

        # Continue to next question
        logger.info(f"Continuing survey after receiving transcription for {chat_id}")
        state = self.survey_state[chat_id]
        state["current_question"] += 1
        await self.send_next_question(chat_id)

    def clean_old_transcription_states(self) -> None:
        """Clean up old transcription states"""
        current_time = datetime.now()
        to_remove = []
        
        for chat_id, info in self.waiting_for_transcription.items():
            if current_time - info["timestamp"] > timedelta(minutes=2):
                to_remove.append(chat_id)
                
        for chat_id in to_remove:
            info = self.waiting_for_transcription.pop(chat_id)
            logger.info(f"Cleaned up old transcription state for {chat_id}")
            if chat_id in self.survey_state:
                self.send_message(chat_id, "התמלול לקח יותר מדי זמן. נא לשלוח את ההקלטה שוב.")

    def extract_transcription_content(self, message: str) -> Optional[str]:
        """Extract the actual content from the transcription message"""
        try:
            if "🤖 עיבוד אוטומטי של הודעה קולית:" in message:
                # Try to get the summary first
                if "📌 סיכום:" in message:
                    summary_start = message.find("📌 סיכום:")
                    summary_end = len(message)
                    summary = message[summary_start:summary_end].replace("📌 סיכום:", "").strip()
                    if summary:
                        return summary
                
                # If no summary or empty, get the transcription
                if "📝 תמלול:" in message:
                    transcription_start = message.find("📝 תמלול:")
                    summary_start = message.find("📌 סיכום:")
                    if summary_start > -1:
                        transcription = message[transcription_start:summary_start]
                    else:
                        transcription = message[transcription_start:]
                    return transcription.replace("📝 תמלול:", "").strip()
            
            return message
        except Exception as e:
            logger.error(f"Error extracting transcription content: {e}")
            return message

    async def handle_text_message(self, chat_id: str, message: str, sender_name: str = "") -> None:
        """Handle incoming text messages"""
        # Regular text message handling
        message = message.strip()
        
        if chat_id not in self.survey_state:
            # Check if this is a trigger for a new survey
            survey = self.get_survey_by_trigger(message)
            if survey:
                # Create initial record and start survey
                record_id = self.create_initial_record(chat_id, sender_name, survey)
                if record_id:
                    self.survey_state[chat_id] = {
                        "current_question": 0,
                        "answers": {},
                        "record_id": record_id,
                        "survey": survey,
                        "last_activity": datetime.now()
                    }
                    await self.send_next_question(chat_id)
                else:
                    await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בהתחלת השאלון. נא לנסות שוב.")
        else:
            state = self.survey_state[chat_id]
            
            # Check if we're waiting for a meeting poll response
            if state.get("waiting_for_meeting_response") and state.get("poll_options"):
                if message in ["1", "2"]:
                    selected_option = state["poll_options"][int(message) - 1]
                    await self.handle_meeting_poll_response(chat_id, selected_option)
                    return
                else:
                    await self.send_message_with_retry(chat_id, "אנא השב/י 1 או 2")
                    return
            
            # Regular survey answer handling
            await self.process_survey_answer(chat_id, {"type": "text", "content": message})

    async def handle_poll_response(self, chat_id: str, poll_data: Dict) -> None:
        """Handle poll response"""
        if chat_id not in self.survey_state:
            logger.warning(f"Received poll response for unknown chat_id: {chat_id}")
            return

        state = self.survey_state[chat_id]
        state['last_activity'] = datetime.now()

        # Check if this is a meeting scheduling poll response
        if state.get("waiting_for_meeting_response"):
            selected_options = []
            if "votes" in poll_data:
                for vote in poll_data["votes"]:
                    if "optionVoters" in vote and chat_id in vote.get("optionVoters", []):
                        selected_options.append(vote["optionName"])
            
            if selected_options:
                await self.handle_meeting_poll_response(chat_id, selected_options[0])
            return

        # Regular poll handling continues...
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

    async def process_survey_answer(self, chat_id: str, answer: Dict[str, str]) -> None:
        """Process a survey answer and update Airtable record"""
        try:
            logger.info(f"Processing survey answer for chat_id: {chat_id}")
            logger.debug(f"Answer data: {json.dumps(answer, ensure_ascii=False)}")
            
            state = self.survey_state.get(chat_id)
            if not state or "record_id" not in state:
                logger.error(f"No valid state found for chat_id: {chat_id}")
                return

            state['last_activity'] = datetime.now()
            survey = state["survey"]
            current_question = survey.questions[state["current_question"]]
            question_id = current_question["id"]
            logger.info(f"Current question: {question_id}")
            
            try:
                # Save answer to state
                state["answers"][question_id] = answer["content"]
                logger.debug(f"Updated state answers: {json.dumps(state['answers'], ensure_ascii=False)}")
                
                # Generate and send reflection before updating Airtable
                reflection = await self.generate_response_reflection(current_question["text"], answer["content"])
                if reflection:
                    await self.send_message_with_retry(chat_id, reflection)
                    await asyncio.sleep(1.5)  # Add a small delay after reflection
                
                # Prepare Airtable update
                update_data = {
                    question_id: answer["content"]
                }

                # Update status to "בטיפול" when answering questions
                if state["current_question"] > 0:  # Not the first question
                    update_data["סטטוס"] = "בטיפול"
                
                logger.info(f"Updating Airtable record {state['record_id']}")
                logger.debug(f"Update data: {json.dumps(update_data, ensure_ascii=False)}")
                
                if self.update_record(state["record_id"], update_data, survey):
                    logger.info(f"Successfully updated record for question {question_id}")
                    
                    if answer.get("is_final", True):
                        state["current_question"] += 1
                        state.pop("selected_options", None)
                        state.pop("last_poll_response", None)
                        logger.info(f"Moving to next question (index: {state['current_question']})")
                        
                        # If this was the last question, update status to "הושלם"
                        if state["current_question"] >= len(survey.questions):
                            self.update_record(state["record_id"], {"סטטוס": "הושלם"}, survey)
                        
                        await self.send_next_question(chat_id)
                else:
                    logger.error(f"Failed to update record for question {question_id}")
                    await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בשמירת התשובה. נא לנסות שוב.")
            except Exception as inner_e:
                logger.error(f"Error in inner try block: {str(inner_e)}")
                logger.error(f"Stack trace: {traceback.format_exc()}")
                await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בעיבוד התשובה. נא לנסות שוב.")
                
        except Exception as e:
            logger.error(f"Error processing answer: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            await self.send_message_with_retry(chat_id, "מצטערים, הייתה שגיאה בשמירת התשובה. נא לנסות שוב.")

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

    def generate_summary(self, answers: Dict[str, str]) -> str:
        """Generate a summary of the survey answers using the language model"""
        try:
            prompt = """
            בהתבסס על התשובות הבאות, אנא צור סיכום תמציתי בעברית:
            {}

            הסיכום צריך להיות:
            1. קצר ותמציתי
            2. מדגיש את הנקודות העיקריות
            3. כתוב בשפה מקצועית אך ידידותית
            4. בעל נראות טובה, ואם מתאים, מכיל אימוגים
            אני רוצה שהפלט שלך יתחיל ישר מהסיכום ללא הקדמות.
            """.format(json.dumps(answers, ensure_ascii=False))
            
            response = model.generate_content([prompt])
            return response.text
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return "לא הצלחנו ליצור סיכום כרגע."

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
            
            # Generate and send summary
            logger.info("Generating summary")
            summary = self.generate_summary(state["answers"])
            logger.debug(f"Generated summary: {summary[:100]}...")  # Log first 100 chars
            
            logger.info("Sending summary")
            summary_response = await self.send_message_with_retry(chat_id, f"*סיכום השאלון שלך:*\n{summary}")
            if "error" in summary_response:
                logger.error(f"Failed to send summary: {summary_response['error']}")
                del self.survey_state[chat_id]
                return

            # Add delay after summary
            await asyncio.sleep(2)

            if survey.name == "business_survey":
                try:
                    logger.info("Preparing to send meeting poll")
                    poll_data = {
                        "text": "האם לקבוע לנו כבר פגישת סיכום אפיון? 📅",
                        "options": [
                            "כן, אשמח כבר לקבוע זמן לפגישה 😊",
                            "אשמח לתזכורת בהמשך"
                        ],
                        "multipleAnswers": False
                    }
                    
                    logger.debug(f"Meeting poll data: {json.dumps(poll_data, ensure_ascii=False)}")
                    poll_response = await self.send_poll(chat_id, poll_data)
                    logger.debug(f"Poll response: {json.dumps(poll_response, ensure_ascii=False)}")
                    
                    if "error" in poll_response:
                        logger.error(f"Failed to send meeting poll: {poll_response['error']}")
                        await self.send_default_thank_you(chat_id)
                        del self.survey_state[chat_id]
                        return
                        
                    # Keep the state for handling the poll response
                    logger.info("Setting waiting_for_meeting_response flag")
                    state["waiting_for_meeting_response"] = True
                    return  # Don't delete state yet
                    
                except Exception as e:
                    logger.error(f"Error sending meeting poll: {str(e)}")
                    logger.error(f"Stack trace: {traceback.format_exc()}")
                    await self.send_default_thank_you(chat_id)
                    del self.survey_state[chat_id]
                    return
                    
            elif survey.name == "research_survey":
                logger.info("Sending research survey thank you message")
                thank_you_message = """*תודה רבה על השתתפותך במחקר!* 🙏

התשובות שלך יעזרו לנו להבין טוב יותר את האתגרים של עסקים כמו שלך.
*אשמח לקבוע איתך פגישת אפיון עסקי במתנה* 🎁

נדבר בקרוב! 💫"""
                await self.send_message_with_retry(chat_id, thank_you_message)
                
            elif survey.name == "satisfaction_survey":
                logger.info("Sending satisfaction survey thank you message")
                thank_you_message = """*תודה רבה על המשוב החשוב שלך!* 🙏

המשוב שלך יעזור לנו להשתפר ולהעניק שירות טוב יותר.
נשמח לעמוד לשירותך גם בעתיד! 💫"""
                await self.send_message_with_retry(chat_id, thank_you_message)
                
            else:
                logger.info("Sending default thank you message")
                await self.send_default_thank_you(chat_id)
                
            # Clean up state if we're not waiting for meeting response
            if not state.get("waiting_for_meeting_response"):
                logger.info("Cleaning up state (not waiting for meeting response)")
                del self.survey_state[chat_id]
                
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

async def generate_response_reflection(question, answer):
    """Generate a reflective response based on the user's answer."""
    try:
        prompt = f"""
        בהתבסס על התשובה של המשתמש לשאלה, צור תגובה קצרה ואמפתית שמשקפת את מה שהוא אמר.
        השתמש בטון חם ואנושי. התגובה צריכה להיות קצרה (1-2 משפטים).
        
        שאלה: {question}
        תשובה: {answer}
        
        הנחיות:
        1. שקף את התוכן העיקרי של התשובה
        2. השתמש בשפה חיובית ומעריכה
        3. הימנע מלחזור על התשובה מילה במילה
        4. אל תוסיף מידע חדש
        """
        
        response = await genai.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Error generating reflection: {str(e)}")
        return None

async def handle_survey_response(chat_id, message):
    """Handle survey responses and generate appropriate reflections."""
    try:
        state = get_state(chat_id)
        if not state:
            logger.warning(f"No state found for chat_id {chat_id}")
            return
        
        current_question = state.get('current_question')
        if not current_question:
            return
        
        # Save the response
        save_response(chat_id, current_question, message)
        
        # Generate reflection
        reflection = await generate_response_reflection(current_question, message)
        if reflection:
            # Send the reflection
            await send_message(chat_id, reflection)
            # Add a small delay before next question
            await asyncio.sleep(1.5)
        
        # Get next question
        next_question = get_next_question(state)
        if next_question:
            state['current_question'] = next_question
            update_state(chat_id, state)
            await send_message(chat_id, next_question)
        else:
            await finish_survey(chat_id)
            
    except Exception as e:
        logger.error(f"Error in handle_survey_response: {str(e)}")
        await send_message(chat_id, "מצטער, נתקלתי בבעיה בעיבוד התשובה שלך. אנא נסה שוב.")

def get_next_question(state):
    """Get the next question based on the survey type and current progress."""
    survey_type = state.get('survey_type')
    current_question = state.get('current_question')
    
    if survey_type == "business_survey":
        questions = [
            "מה שם העסק שלך?",
            "באיזה תחום העסק שלך פועל?",
            "מה האתגר העיקרי שאתה מתמודד איתו כרגע בעסק?",
            "מה המטרה העיקרית שלך לשנה הקרובה?",
            "איך שמעת עלינו?"
        ]
    elif survey_type == "research_survey":
        questions = [
            "מה התחום שבו אתה עורך את המחקר?",
            "מה השאלה המרכזית של המחקר שלך?",
            "באיזה שלב המחקר נמצא כרגע?",
            "מה האתגר העיקרי שאתה מתמודד איתו במחקר?",
            "איזה סוג עזרה אתה מחפש?"
        ]
    elif survey_type == "satisfaction_survey":
        questions = [
            "איך היית מדרג את השירות שקיבלת? (1-10)",
            "מה הדבר שהכי אהבת בשירות?",
            "מה לדעתך אפשר לשפר?",
            "האם תמליץ עלינו לאחרים? למה?",
            "יש לך הצעות נוספות לשיפור?"
        ]
    else:
        return None
    
    try:
        current_index = questions.index(current_question)
        if current_index + 1 < len(questions):
            return questions[current_index + 1]
    except ValueError:
        return questions[0]
    
    return None

def save_response(chat_id, question, answer):
    """Save the response to Airtable."""
    try:
        state = get_state(chat_id)
        if not state:
            return
        
        survey_type = state.get('survey_type')
        table_id = get_table_id_for_survey_type(survey_type)
        
        if not table_id:
            logger.error(f"No table ID found for survey type: {survey_type}")
            return
            
        # Get existing record or create new one
        record = get_or_create_survey_record(chat_id, table_id)
        
        # Update the record with the new response
        fields = record.get('fields', {})
        fields[question] = answer
        fields['סטטוס'] = 'בטיפול'
        fields['תאריך עדכון'] = datetime.now().isoformat()
        
        # Update record in Airtable
        table = airtable.table(AIRTABLE_BASE_ID, table_id)
        table.update(record['id'], fields)
        
    except Exception as e:
        logger.error(f"Error saving response: {str(e)}")

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
    """Cancel the cleanup task when the application shuts down"""
    if bot.cleanup_task:
        bot.cleanup_task.cancel()
        try:
            await bot.cleanup_task
        except asyncio.CancelledError:
            pass

# Webhook handler function
async def handle_webhook(webhook_data: Dict) -> None:
    """Handle incoming webhook data"""
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
