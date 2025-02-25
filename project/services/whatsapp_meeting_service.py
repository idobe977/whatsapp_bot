import asyncio
import json
import traceback
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import os
from project.utils.logger import logger
from project.models.survey import SurveyDefinition
from .whatsapp_base_service import WhatsAppBaseService
from .calendar_service import CalendarService, TimeSlot
import aiohttp

class WhatsAppMeetingService(WhatsAppBaseService):
    def __init__(self, instance_id: str, api_token: str):
        super().__init__(instance_id, api_token)
        self.calendar_manager = CalendarService()

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
                table = self.airtable.table(os.getenv("AIRTABLE_BASE_ID"), state['survey'].airtable_table_id)
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
                    table = self.airtable.table(os.getenv("AIRTABLE_BASE_ID"), state['survey'].airtable_table_id)
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