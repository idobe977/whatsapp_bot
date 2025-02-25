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
        state = self.survey_state.get(chat_id)
        if not state or state["current_question"] >= len(state["survey"].questions):
            return

        current_question = state["survey"].questions[state["current_question"]]
        if current_question["type"] != "file":
            return

        file_data = message_data.get("fileMessageData", {})
        mime_type = file_data.get("mimeType")
        file_size = len(file_data.get("file", "")) if "file" in file_data else None
        download_url = file_data.get("downloadUrl")

        # בדיקת סוג הקובץ
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

        # בדיקת גודל הקובץ
        if file_size and file_size > self.MAX_FILE_SIZE:
            await self.send_message_with_retry(
                chat_id,
                state["survey"].messages["file_upload"]["too_large"]
            )
            return

        # שמירת המידע על הקובץ
        answer = {
            "url": download_url,
            "mime_type": mime_type,
            "file_name": file_data.get("fileName", ""),
            "caption": file_data.get("caption", "")
        }

        # עדכון התשובה במצב השאלון
        state["answers"][current_question["field"]] = answer
        state["current_question"] += 1
        state["last_activity"] = datetime.now()

        # שליחת הודעת אישור
        await self.send_message_with_retry(
            chat_id,
            state["survey"].messages["file_upload"]["success"]
        )

        # המשך לשאלה הבאה
        await self.send_next_question(chat_id)

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