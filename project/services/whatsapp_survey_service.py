import asyncio
import json
import glob
import os
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from project.utils.logger import logger
from project.models.survey import SurveyDefinition
from .whatsapp_ai_service import WhatsAppAIService
from .whatsapp_meeting_service import WhatsAppMeetingService

class WhatsAppSurveyService(WhatsAppAIService, WhatsAppMeetingService):
    def __init__(self, instance_id: str, api_token: str):
        super().__init__(instance_id, api_token)
        self.surveys = self.load_surveys()
        self.survey_state = {}  # Track survey state for each user
        self.SURVEY_TIMEOUT = 30  # Minutes
        self.ALLOWED_FILE_TYPES = {
            'image': ['image/jpeg', 'image/png', 'image/gif'],
            'document': ['application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
            'any': None  # None means accept any file type
        }
        self.MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB in bytes
        
        logger.info(f"Loaded {len(self.surveys)} surveys")
        for survey in self.surveys:
            logger.info(f"Survey loaded: {survey.name} with {len(survey.trigger_phrases)} trigger phrases")

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

            # Get file data
            file_data = message_data.get("fileMessageData", {})
            mime_type = file_data.get("mimeType")
            download_url = file_data.get("downloadUrl")
            caption = file_data.get("caption", "")
            file_name = file_data.get("fileName", "")

            # Prepare file attachment object for Airtable
            attachment = {
                "url": download_url,
                "filename": file_name or f"file_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            }

            # Update Airtable with the attachment
            if await self.update_airtable_record(
                state["record_id"],
                {current_question["field"]: [attachment]},  # Airtable expects a list of attachment objects
                state["survey"]
            ):
                # Send success message
                await self.send_message_with_retry(
                    chat_id,
                    state["survey"].messages.get("file_upload", {}).get("success", "הקובץ נשמר בהצלחה!")
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
            await self.send_message_with_retry(
                chat_id,
                "מצטערים, הייתה שגיאה בעיבוד הקובץ. נא לנסות שוב."
            )

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
            elif question["type"] == "file":
                # הוספת הודעה מותאמת לשאלת קובץ
                file_message = question.get("text", "אנא שלח קובץ")
                if "allowed_types" in question:
                    allowed_types = question["allowed_types"]
                    if "any" not in allowed_types:
                        file_types_str = ", ".join(allowed_types)
                        file_message += f"\nסוגי קבצים מותרים: {file_types_str}"
                await self.send_message_with_retry(chat_id, file_message)
            else:
                await self.send_message_with_retry(chat_id, question["text"])
        else:
            await self.finish_survey(chat_id)

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
