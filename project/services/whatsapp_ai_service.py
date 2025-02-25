import asyncio
import json
import traceback
from typing import Dict, List, Optional
from datetime import datetime
import google.generativeai as genai
import os
from dotenv import load_dotenv
from project.utils.logger import logger
from project.models.survey import SurveyDefinition
from .whatsapp_base_service import WhatsAppBaseService

load_dotenv()

# Initialize Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-pro-exp-02-05")

class WhatsAppAIService(WhatsAppBaseService):
    def __init__(self, instance_id: str, api_token: str):
        super().__init__(instance_id, api_token)
        self.reflection_cache = {}  # Cache for AI reflections

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
                    table = self.airtable.table(os.getenv("AIRTABLE_BASE_ID"), survey.airtable_table_id)
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