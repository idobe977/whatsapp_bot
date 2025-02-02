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
    "AIRTABLE_TABLE_ID"
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
AIRTABLE_TABLE_ID = os.getenv("AIRTABLE_TABLE_ID")
logger.info(f"Configured Airtable with base ID: {AIRTABLE_BASE_ID}")

class WhatsAppSurveyBot:
    def __init__(self):
        self.survey_state = {}  # Track survey state for each user
        self.trigger_phrases = [
            "שאלון אפיון",
            "אשמח להתחיל את שאלון האפיון 😊",
            "אפיון",
            "להתחיל שאלון",
            "התחל שאלון",
            "אפיון עסקי",
            "שאלון אפיון עסקי"
        ]
        self.questions = [
            {
                "id": "שם מלא",
                "type": "text",
                "text": """*ברוכים הבאים לשאלון האפיון שלנו!* 🤝

יחד נגלה את הדרך הנכונה להצמיח את העסק שלך 🚀

*איך אוכל לפנות אליך?* (שם מלא) 👋"""
            },
            {
                "id": "שם העסק",
                "type": "text",
                "text": "מה שם העסק שלך? 🏢"
            },
            {
                "id": "בכללי על העסק",
                "type": "text",
                "text": """אשמח לשמוע על העסק שלך 💼
תחום הפעילות, היקף, מספר עובדים והחזון שמניע אותך קדימה

*אפשר להקליד ⌨️ או להקליט 🎤 (ה-AI 🤖 שלנו יפענח את ההקלטה 😊)*"""
            },
            {
                "id": "יעדים לשנה הקרובה",
                "type": "text",
                "text": "מהם היעדים המרכזיים שלך לשנה הקרובה, ומה מקשה עליך להשיג אותם? 🎯"
            },
            {
                "id": "תהליכי עבודה וכלים",
                "type": "text",
                "text": """מה שגרת העבודה בעסק? ⚡
אילו תהליכים מרכזיים קיימים ואילו כלים או תוכנות משמשים אותך כיום?"""
            },
            {
                "id": "תהליכים גוזלי זמן",
                "type": "text",
                "text": """אילו תהליכים בעסק גוזלים את הזמן היקר ביותר או דורשים מעקב ידני מתמיד? ⏳
(למשל: הפקת דוחות, תיאומי פגישות, מעקב תשלומים)"""
            },
            {
                "id": "ניהול קשר לקוחות",
                "type": "text",
                "text": "איך מתנהל הקשר עם הלקוחות שלך לאורך מסע הלקוח, ואיפה אתה רואה מקום לשיפור? 🤝"
            },
            {
                "id": "מפתח לחוויית לקוח",
                "type": "text",
                "text": "מה המפתח לחוויית לקוח מוצלחת בעיניך? 💫"
            },
            {
                "id": "מערכות נדרשות",
                "type": "text",
                "text": "אילו מערכות חשוב לך לשלב בפתרון, ומה התקציב החודשי המתוכנן? 💰"
            },
            {
                "id": "הגדרת הצלחה",
                "type": "text",
                "text": """מה תחשיב כהצלחה לאחר הטמעת האוטומציה? 📈
(למשל: חיסכון בזמן, הגדלת מספר לקוחות)"""
            },
            {
                "id": "דגשים לתהליך",
                "type": "text",
                "text": "מה הדבר שהכי חשוב לכם בתהליך העבודה איתי? 🎯"
            },
            {
                "id": "הערות נוספות",
                "type": "text",
                "text": "יש משהו נוסף שחשוב לך שאדע או שנתייחס אליו? 💭"
            }
        ]
        self.airtable = Api(AIRTABLE_API_KEY)
        self.table = self.airtable.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_ID)
        self.waiting_for_transcription = {}  # Track chats waiting for transcription

    def get_answer_type_for_airtable(self, answer_type: str) -> str:
        """Convert internal answer type to Airtable single select value"""
        type_mapping = {
            "text": "טקסט",
            "voice": "הקלטה",
            "poll": "סקר"
        }
        return type_mapping.get(answer_type, "טקסט")

    def get_existing_record_id(self, chat_id: str) -> Optional[str]:
        """Get existing record ID for a chat_id"""
        try:
            records = self.table.all(formula=f"{{מזהה צ'אט בוואטסאפ}} = '{chat_id}'")
            if records:
                # Get the most recent record if multiple exist
                return records[-1]["id"]
            return None
        except Exception as e:
            logger.error(f"Error getting record ID: {e}")
            return None

    def create_initial_record(self, chat_id: str, sender_name: str) -> Optional[str]:
        """Create initial record when survey starts"""
        try:
            logger.info(f"Creating initial record for chat_id: {chat_id}, sender_name: {sender_name}")
            record = {
                "מזהה צ'אט וואטסאפ": chat_id,
                "תאריך מילוי": datetime.now().strftime("%Y-%m-%d"),
                "שם מלא": sender_name,
                "סטטוס": "חדש"
            }
            logger.debug(f"Record data to be created: {json.dumps(record, ensure_ascii=False)}")
            
            response = self.table.create(record)
            logger.info(f"Created initial record: {response}")
            return response["id"]
        except Exception as e:
            logger.error(f"Error creating initial record: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response content: {e.response.text}")
            return None

    def update_record(self, record_id: str, data: Dict) -> bool:
        """Update existing record with new data"""
        try:
            self.table.update(record_id, data)
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

    def send_poll(self, chat_id: str, question: Dict) -> Dict:
        """Send a poll message to WhatsApp user"""
        try:
            logger.info(f"Sending poll to {chat_id}")
            logger.debug(f"Poll question: {question['text']}")
            logger.debug(f"Poll options: {question['options']}")
            
            url = f"{GREEN_API_BASE_URL}/sendPoll/{API_TOKEN_INSTANCE}"
            payload = {
                "chatId": chat_id,
                "message": question["text"],
                "options": question["options"],
                "multipleAnswers": question.get("multipleAnswers", False)
            }
            response = requests.post(url, json=payload)
            response.raise_for_status()
            
            response_data = response.json()
            logger.info(f"Poll sent successfully to {chat_id}")
            logger.debug(f"Green API response: {response_data}")
            return response_data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send poll to {chat_id}: {str(e)}")
            logger.error(f"Response status code: {getattr(e.response, 'status_code', 'N/A')}")
            logger.error(f"Response content: {getattr(e.response, 'text', 'N/A')}")
            return {"error": str(e)}

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
            # Get current question index
            current_question_index = self.survey_state[chat_id]["current_question"]
            current_question = self.questions[current_question_index]

            # Do the transcription
            transcribed_text = await self.transcribe_voice(voice_url)
            if not transcribed_text or transcribed_text in ["שגיאה בהורדת הקובץ הקולי", "שגיאה בתהליך התמלול"]:
                self.send_message(chat_id, "מצטערים, הייתה שגיאה בתמלול ההקלטה. נא לנסות שוב.")
                return
            
            # Save to Airtable
            update_data = {
                current_question["id"]: transcribed_text,
                "סטטוס": "בטיפול"
            }
            
            try:
                if self.update_record(self.survey_state[chat_id]["record_id"], update_data):
                    logger.info(f"Saved transcription for question {current_question['id']}")
                    # Move to next question immediately
                    self.process_survey_answer(chat_id, {
                        "type": "voice",
                        "content": transcribed_text,
                        "original_url": voice_url,
                        "is_final": True
                    })
                else:
                    logger.error("Failed to save transcription to Airtable")
                    self.send_message(chat_id, "מצטערים, הייתה שגיאה בשמירת התשובה. נא לנסות שוב.")
            except Exception as airtable_error:
                logger.error(f"Airtable error: {str(airtable_error)}")
                self.send_message(chat_id, "מצטערים, הייתה שגיאה בשמירת התשובה באירטייבל. נא לנסות שוב.")

        except Exception as e:
            logger.error(f"Error handling voice message: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            self.send_message(chat_id, "מצטערים, הייתה שגיאה בעיבוד ההודעה הקולית. נא לנסות שוב.")

    def handle_transcription_summary(self, chat_id: str, summary: str) -> None:
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
            self.send_message(chat_id, "התמלול לקח יותר מדי זמן. נא לשלוח את ההקלטה שוב.")
            return

        # Validate summary
        if not summary or len(summary.strip()) < 10:
            logger.warning(f"Received invalid or too short summary for {chat_id}")
            self.send_message(chat_id, "התמלול שהתקבל אינו תקין. נא לשלוח את ההקלטה שוב.")
            return

        # Continue to next question
        logger.info(f"Continuing survey after receiving transcription for {chat_id}")
        state = self.survey_state[chat_id]
        state["current_question"] += 1
        self.send_next_question(chat_id)

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

    def handle_text_message(self, chat_id: str, message: str, sender_name: str = "") -> None:
        """Handle incoming text messages"""
        # Regular text message handling
        message = message.strip()
        if any(trigger in message.lower() for trigger in self.trigger_phrases):
            # Create initial record and start survey
            record_id = self.create_initial_record(chat_id, sender_name)
            if record_id:
                self.survey_state[chat_id] = {
                    "current_question": 0,
                    "answers": {},
                    "record_id": record_id
                }
                self.send_next_question(chat_id)
            else:
                self.send_message(chat_id, "מצטערים, הייתה שגיאה בהתחלת השאלון. נא לנסות שוב.")
        elif chat_id in self.survey_state:
            self.process_survey_answer(chat_id, {"type": "text", "content": message})

    def handle_poll_response(self, chat_id: str, poll_data: Dict) -> None:
        """Handle poll response"""
        if chat_id not in self.survey_state:
            logger.warning(f"Received poll response for unknown chat_id: {chat_id}")
            return

        state = self.survey_state[chat_id]
        current_question = self.questions[state["current_question"]]
        question_id = current_question["id"]
        
        # Check if current question is a poll question
        if current_question["type"] != "poll":
            logger.warning(f"Ignoring poll response as current question {question_id} is not a poll question")
            return
            
        # Check if this poll response matches the current question's name
        if poll_data["name"] != current_question["text"]:
            logger.warning(f"Ignoring poll response as it doesn't match current question. Expected: {current_question['text']}, Got: {poll_data['name']}")
            return
        
        logger.info(f"Processing poll response for question: {question_id}")
        logger.info(f"Poll data: {json.dumps(poll_data, ensure_ascii=False)}")
        
        # Store the last poll response time for multiple choice questions
        if current_question.get("multipleAnswers", False):
            current_time = datetime.now()
            state["last_poll_response"] = current_time
            state.setdefault("selected_options", set())
        
        selected_options = []
        if "votes" in poll_data:
            for vote in poll_data["votes"]:
                if "optionVoters" in vote and chat_id in vote.get("optionVoters", []):
                    # Clean and map the option text
                    clean_option = self.clean_option_text(vote["optionName"], question_id)
                    selected_options.append(clean_option)
        
        if selected_options:
            if current_question.get("multipleAnswers", False):
                # For multiple choice questions, update the set of selected options
                state["selected_options"].update(selected_options)
                answer_content = ", ".join(state["selected_options"])
                logger.info(f"Updated multiple choice selections: {answer_content}")
                
                # Save the current selections but don't move to next question yet
                self.process_survey_answer(chat_id, {
                    "type": "poll",
                    "content": answer_content,
                    "is_final": False
                })
                
                # Send a message to inform the user they can select more options
                self.send_message(chat_id, "ניתן לבחור אפשרויות נוספות. כשסיימת, המתן 3 שניות והשאלון ימשיך אוטומטית.")
                
                # Schedule a check to move to the next question after 3 seconds
                self.schedule_next_question(chat_id, 3)
            else:
                # For single choice questions, proceed as normal
                answer_content = ", ".join(selected_options)
                logger.info(f"Poll response processed - Question: {question_id}, Selected options (mapped): {answer_content}")
                
                self.process_survey_answer(chat_id, {
                    "type": "poll",
                    "content": answer_content,
                    "is_final": True
                })
        else:
            logger.warning(f"No valid options selected for chat_id: {chat_id}")

    def schedule_next_question(self, chat_id: str, delay_seconds: int) -> None:
        """Schedule moving to the next question after a delay"""
        def check_and_advance():
            state = self.survey_state.get(chat_id)
            if not state:
                return
            
            last_response_time = state.get("last_poll_response")
            if last_response_time and (datetime.now() - last_response_time).total_seconds() >= delay_seconds:
                logger.info(f"Advancing to next question for chat_id: {chat_id} after {delay_seconds} seconds of inactivity")
                state["current_question"] += 1
                state.pop("selected_options", None)
                state.pop("last_poll_response", None)
                self.send_next_question(chat_id)

        # Use threading to schedule the check
        import threading
        threading.Timer(delay_seconds, check_and_advance).start()

    def generate_summary(self, answers: Dict[str, str]) -> str:
        """Generate a summary of the survey answers using the language model"""
        try:
            prompt = """
            Based on the following answers, provide a concise summary in Hebrew:
            {}
            """.format(json.dumps(answers, ensure_ascii=False))
            response = model.generate_content([prompt])
            return response.text
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return "לא הצלחנו ליצור סיכום כרגע."

    def finish_survey(self, chat_id: str) -> None:
        """Finish the survey and send a summary"""
        state = self.survey_state.get(chat_id)
        if not state:
            return

        # Generate a summary of the answers
        summary = self.generate_summary(state["answers"])

        # Send the summary to the user
        self.send_message(chat_id, f"*סיכום השאלון שלך:*\n{summary}")

        # Send the final thank you message
        self.send_message(chat_id, """*תודה רבה על  מילוי השאלון!* 🙏

אני אחזור אליך בקרוב עם תובנות מעמיקות ותוכנית פעולה מותאמת אישית.

בינתיים, אם יש לך שאלות נוספות או דברים שברצונך להוסיף, אשמח לשמוע! 💭""")
        del self.survey_state[chat_id]

    def send_next_question(self, chat_id: str) -> None:
        """Send the next survey question"""
        state = self.survey_state.get(chat_id)
        if not state:
            return

        if state["current_question"] < len(self.questions):
            question = self.questions[state["current_question"]]
            if question["type"] == "poll":
                self.send_poll(chat_id, question)
            else:
                self.send_message(chat_id, question["text"])
        else:
            self.finish_survey(chat_id)

    def process_survey_answer(self, chat_id: str, answer: Dict[str, str]) -> None:
        """Process a survey answer and update Airtable record"""
        try:
            logger.info(f"Processing survey answer for chat_id: {chat_id}")
            logger.debug(f"Answer data: {json.dumps(answer, ensure_ascii=False)}")
            
            state = self.survey_state.get(chat_id)
            if not state or "record_id" not in state:
                logger.error(f"No valid state found for chat_id: {chat_id}")
                return

            current_question = self.questions[state["current_question"]]
            question_id = current_question["id"]
            logger.info(f"Current question: {question_id}")
            
            # Save answer to state
            state["answers"][question_id] = answer["content"]
            logger.debug(f"Updated state answers: {json.dumps(state['answers'], ensure_ascii=False)}")
            
            # Prepare Airtable update
            update_data = {
                question_id: answer["content"]
            }

            # Update status to "בטיפול" when answering questions
            if state["current_question"] > 0:  # Not the first question
                update_data["סטטוס"] = "בטיפול"
            
            logger.info(f"Updating Airtable record {state['record_id']}")
            logger.debug(f"Update data: {json.dumps(update_data, ensure_ascii=False)}")
            
            if self.update_record(state["record_id"], update_data):
                logger.info(f"Successfully updated record for question {question_id}")
                
                if answer.get("is_final", True):
                    state["current_question"] += 1
                    state.pop("selected_options", None)
                    state.pop("last_poll_response", None)
                    logger.info(f"Moving to next question (index: {state['current_question']})")
                    
                    # If this was the last question, update status to "הושלם"
                    if state["current_question"] >= len(self.questions):
                        self.update_record(state["record_id"], {"סטטוס": "הושלם"})
                    
                    self.send_next_question(chat_id)
            else:
                logger.error(f"Failed to update record for question {question_id}")
                self.send_message(chat_id, "מצטערים, הייתה שגיאה בשמירת התשובה. נא לנסות שוב.")
                
        except Exception as e:
            logger.error(f"Error processing answer: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            self.send_message(chat_id, "מצטערים, הייתה שגיאה בשמירת התשובה. נא לנסות שוב.")

# Initialize the bot
logger.info("Initializing WhatsApp Survey Bot...")
bot = WhatsAppSurveyBot()
logger.info("Bot initialized successfully")

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
            bot.handle_text_message(chat_id, text, sender_name)
            
        elif message_data["typeMessage"] == "audioMessage":
            voice_url = message_data["fileMessageData"]["downloadUrl"]
            logger.info(f"Received voice message from URL: {voice_url}")
            await bot.handle_voice_message(chat_id, voice_url)
            
        elif message_data["typeMessage"] == "pollUpdateMessage":
            poll_data = message_data["pollMessageData"]
            logger.info("Received poll update")
            logger.debug(f"Poll data: {json.dumps(poll_data, ensure_ascii=False)}")
            bot.handle_poll_response(chat_id, poll_data)
            
    except Exception as e:
        logger.error(f"Error handling webhook: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        raise 