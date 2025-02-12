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
from datetime import datetime
import google.generativeai as genai

# Initialize Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-pro")

class WhatsAppService:
    def __init__(self, instance_id: str, api_token: str):
        self.instance_id = instance_id
        self.api_token = api_token
        self.base_url = f"https://api.greenapi.com/waInstance{instance_id}"
        self.surveys = self.load_surveys()
        self.survey_state = {}  # Track survey state for each user
        self.reflection_cache = {}  # Cache for AI reflections
        
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

    def load_surveys(self) -> List[SurveyDefinition]:
        """Load all survey definitions during initialization"""
        logger.info("Loading surveys...")
        return load_surveys_from_json()

    async def handle_text_message(self, chat_id: str, text: str, sender_name: str = "") -> None:
        """Handle incoming text message and check for survey triggers"""
        logger.info(f"Processing text message from {chat_id} (sender: {sender_name})")
        logger.debug(f"Message content: {text[:100]}...")  # Log first 100 chars
        
        # Check for trigger phrases in all surveys
        for survey in self.surveys:
            logger.debug(f"Checking triggers for survey: {survey.name}")
            
            for trigger in survey.trigger_phrases:
                if trigger.lower() in text.lower():
                    logger.info(f"Found trigger phrase '{trigger}' for survey: {survey.name}")
                    
                    # Send welcome message
                    welcome_msg = survey.messages.get('welcome', "ברוכים הבאים לשאלון!")
                    logger.info(f"Sending welcome message to {chat_id}")
                    await self.send_message(chat_id, welcome_msg)
                    
                    # Send first question
                    if survey.questions:
                        first_question = survey.questions[0]
                        logger.info(f"Sending first question to {chat_id}")
                        
                        if first_question.get('type') == 'poll':
                            logger.info("Question type: poll")
                            await self.send_poll(chat_id, first_question)
                        else:
                            logger.info("Question type: text")
                            await self.send_message(chat_id, first_question['text'])
                    
                    return  # Exit after finding first matching trigger
        
        logger.info(f"No trigger phrases found in message from {chat_id}")

    async def handle_voice_message(self, chat_id: str, voice_url: str) -> None:
        """Handle incoming voice message"""
        logger.info(f"Processing voice message from {chat_id}")
        logger.info("Voice message handling not implemented yet")
        await self.send_message(chat_id, "מצטערים, אך כרגע איננו תומכים בהודעות קוליות. אנא שלח/י הודעת טקסט.")

    async def handle_poll_response(self, chat_id: str, poll_data: Dict) -> None:
        """Handle poll response"""
        logger.info(f"Processing poll response from {chat_id}")
        logger.debug(f"Poll data: {poll_data}")
        # TODO: Implement poll response handling
        logger.info("Poll response handling not implemented yet")

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

    async def send_message(self, chat_id: str, message: str) -> Dict:
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
            return await self.send_message(msg['chat_id'], msg['text'])
        
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
        """Generate a reflective response based on the user's answer"""
        try:
            # Check if reflection is enabled for this question
            reflection_config = question_data.get('reflection', {"type": "none", "enabled": False})
            if not reflection_config["enabled"] or reflection_config["type"] == "none":
                return None

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
            return response.text.strip()
            
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
                    await self.send_message(chat_id, "השאלון בוטל עקב חוסר פעילות. אנא התחל מחדש.")
                
                # Wait for 5 minutes before next cleanup
                await asyncio.sleep(300)
        
        # Create the cleanup task
        self.cleanup_task = asyncio.create_task(cleanup_loop())

    async def process_survey_answer(self, chat_id: str, answer: Dict[str, str]) -> None:
        """Process a survey answer"""
        try:
            logger.info(f"Processing survey answer for chat_id: {chat_id}")
            
            state = self.survey_state.get(chat_id)
            if not state:
                logger.error(f"No survey state found for chat_id: {chat_id}")
                return

            state['last_activity'] = datetime.now()
            survey = state["survey"]
            current_question = survey.questions[state["current_question"]]
            
            # Save answer to state
            if "answers" not in state:
                state["answers"] = {}
            state["answers"][current_question["id"]] = answer["content"]
            
            # Generate reflection if enabled
            reflection = await self.generate_response_reflection(
                current_question["text"],
                answer["content"],
                survey,
                {"chat_id": chat_id, **current_question}
            )
            
            if reflection:
                await self.send_message(chat_id, reflection)
                await asyncio.sleep(1.5)  # Small delay between messages
            
            # Move to next question
            state["current_question"] += 1
            
            # Check if survey is complete
            if state["current_question"] >= len(survey.questions):
                await self.finish_survey(chat_id)
            else:
                await self.send_next_question(chat_id)
                
        except Exception as e:
            logger.error(f"Error processing survey answer: {str(e)}")
            await self.send_message(chat_id, "מצטערים, הייתה שגיאה בעיבוד התשובה. נא לנסות שוב.")

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
                await self.send_message(chat_id, f"*סיכום השאלון שלך:*\n{summary}")
                await asyncio.sleep(1.5)

            # Send completion message
            await self.send_message(chat_id, survey.messages["completion"]["text"])
            
            # Clean up state
            del self.survey_state[chat_id]
            
        except Exception as e:
            logger.error(f"Error finishing survey: {str(e)}")
            await self.send_message(chat_id, "מצטערים, הייתה שגיאה בסיום השאלון.")

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
            else:
                await self.send_message(chat_id, question["text"])
        else:
            await self.finish_survey(chat_id)

def load_surveys_from_json() -> List[SurveyDefinition]:
    """Load all survey definitions from JSON files in the surveys directory"""
    surveys = []
    surveys_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'surveys')
    
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
