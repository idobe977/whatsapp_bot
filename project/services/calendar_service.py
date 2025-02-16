import os
import json
import tempfile
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pytz
from project.utils.logger import logger
from dataclasses import dataclass
import traceback

@dataclass
class TimeSlot:
    start_time: datetime
    end_time: datetime

    def __str__(self) -> str:
        return f"{self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')}"

class CalendarService:
    def __init__(self):
        """Initialize the Calendar API service"""
        self.service = None
        self.timezone = pytz.timezone('Asia/Jerusalem')
        self.setup_service()
        self.day_name_map = {
            'Sunday': 'ראשון',
            'Monday': 'שני',
            'Tuesday': 'שלישי',
            'Wednesday': 'רביעי',
            'Thursday': 'חמישי',
            'Friday': 'שישי',
            'Saturday': 'שבת'
        }

    def setup_service(self) -> None:
        """Initialize Google Calendar service"""
        try:
            service_account_json = os.getenv('GOOGLE_SERVICE_ACCOUNT')
            if not service_account_json:
                raise ValueError("GOOGLE_SERVICE_ACCOUNT environment variable not set")
            
            service_account_info = json.loads(service_account_json)
            service_account_info['private_key'] = self._format_private_key(service_account_info['private_key'])
            
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=['https://www.googleapis.com/auth/calendar']
            )
            self.service = build('calendar', 'v3', credentials=credentials)
            logger.info("Calendar service initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing calendar service: {e}")
            raise

    def _format_private_key(self, key: str) -> str:
        """Format private key for proper use"""
        if not key:
            raise ValueError("Private key is empty")
            
        key = key.strip()
        if len(key) < 100:  # Basic length check
            raise ValueError("Private key seems too short")
            
        # Ensure proper start and end markers
        if not key.startswith("-----BEGIN PRIVATE KEY-----"):
            key = "-----BEGIN PRIVATE KEY-----\n" + key
        if not key.endswith("-----END PRIVATE KEY-----"):
            key = key + "\n-----END PRIVATE KEY-----"
            
        return key

    def _format_date_for_display(self, date: datetime) -> str:
        """Format date as 'יום שלישי 13/2'."""
        # Get Hebrew day name
        day_name = self.day_name_map[date.strftime('%A')]
        
        # Format as D/M
        date_str = date.strftime('%-d/%-m')  # Use - to remove leading zeros
        
        return f'יום {day_name} {date_str}'

    def get_available_slots(self, calendar_settings: Dict, date: datetime) -> List[TimeSlot]:
        """Get available time slots for a specific date"""
        try:
            # Convert date to timezone-aware if it isn't already
            timezone = pytz.timezone(calendar_settings.get('timezone', 'Asia/Jerusalem'))
            if date.tzinfo is None:
                date = timezone.localize(date)
            
            day_name = date.strftime('%A').lower()
            working_hours = calendar_settings.get('working_hours', {}).get(day_name)
            
            if not working_hours:
                logger.info(f"No working hours defined for {day_name}, skipping")
                return []
            
            # Parse working hours and create timezone-aware datetime objects
            start_time = datetime.strptime(working_hours['start'], '%H:%M').time()
            end_time = datetime.strptime(working_hours['end'], '%H:%M').time()
            
            # Create timezone-aware datetime objects for start and end
            start_datetime = timezone.localize(datetime.combine(date.date(), start_time))
            end_datetime = timezone.localize(datetime.combine(date.date(), end_time))
            
            # Get slot duration and buffer
            slot_duration = timedelta(minutes=calendar_settings.get('meeting_duration', 45))
            buffer_time = timedelta(minutes=calendar_settings.get('buffer_between_meetings', 15))
            
            # Check if current time is after start time for today's date
            now = timezone.localize(datetime.now())
            if date.date() == now.date() and now > start_datetime:
                # Round up to next slot
                minutes_since_start = (now - start_datetime).total_seconds() / 60
                slots_passed = int((minutes_since_start + slot_duration.total_seconds()/60 - 1) // (slot_duration.total_seconds()/60 + buffer_time.total_seconds()/60))
                current_time = start_datetime + slots_passed * (slot_duration + buffer_time)
            else:
                current_time = start_datetime
            
            # Generate all possible slots
            slots = []
            while current_time + slot_duration <= end_datetime:
                slot = TimeSlot(
                    start_time=current_time,
                    end_time=current_time + slot_duration
                )
                slots.append(slot)
                current_time += slot_duration + buffer_time
            
            # Filter out booked slots
            available_slots = self.filter_booked_slots(slots, calendar_settings)
            
            return available_slots
            
        except Exception as e:
            logger.error(f"Error getting available slots: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            return []

    def filter_booked_slots(self, slots: List[TimeSlot], calendar_settings: Dict) -> List[TimeSlot]:
        """Filter out slots that are already booked"""
        try:
            if not self.service:
                logger.error("Calendar service not initialized")
                return []
            
            timezone = pytz.timezone(calendar_settings.get('timezone', 'Asia/Jerusalem'))
            now = timezone.localize(datetime.now())
            
            # Get earliest and latest times from slots
            if not slots:
                return []
            
            min_time = min(slot.start_time for slot in slots)
            max_time = max(slot.end_time for slot in slots)
            
            # Get events from calendar
            events_result = self.service.events().list(
                calendarId=calendar_settings.get('calendar_id', 'primary'),
                timeMin=min_time.isoformat(),
                timeMax=max_time.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Convert event times to datetime objects
            booked_slots = []
            for event in events:
                start = event['start'].get('dateTime')
                end = event['end'].get('dateTime')
                
                if start and end:
                    start_dt = datetime.fromisoformat(start)
                    end_dt = datetime.fromisoformat(end)
                    
                    # Make timezone-aware if needed
                    if start_dt.tzinfo is None:
                        start_dt = timezone.localize(start_dt)
                    if end_dt.tzinfo is None:
                        end_dt = timezone.localize(end_dt)
                        
                    booked_slots.append((start_dt, end_dt))
            
            # Filter available slots
            available_slots = []
            for slot in slots:
                # Skip slots in the past
                if slot.start_time <= now:
                    continue
                
                is_available = True
                for booked_start, booked_end in booked_slots:
                    # Check for overlap
                    if not (slot.end_time <= booked_start or slot.start_time >= booked_end):
                        is_available = False
                        break
                
                if is_available:
                    available_slots.append(slot)
            
            return available_slots
            
        except Exception as e:
            logger.error(f"Error filtering booked slots: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            return []

    def schedule_meeting(self, settings: Dict, slot: TimeSlot, attendee_data: Dict) -> Optional[Dict]:
        """Schedule a meeting in the selected time slot"""
        try:
            # Get meeting title and description from templates
            title = settings.get('meeting_title_template', 'פגישה')
            description = settings.get('meeting_description_template', 'פגישה שנקבעה דרך הבוט')
            
            logger.info(f"Original description template: {description}")
            logger.info(f"Attendee data: {json.dumps(attendee_data, ensure_ascii=False)}")
            
            # Replace placeholders in title and description
            for key, value in attendee_data.items():
                title = title.replace(f"{{{{שם מלא}}}}", attendee_data.get('שם מלא', ''))
                description = description.replace(f"{{{{phone}}}}", attendee_data.get('phone', ''))
                
                # Handle meeting type replacement
                if key == 'סוג הפגישה':
                    logger.info(f"Found meeting type key in attendee_data with value: '{value}'")
                    meeting_type = value if value and value.strip() else "לא צוין"  # Default value if empty
                    logger.info(f"Using meeting type value: '{meeting_type}'")
                    description = description.replace("{{סוג הפגישה}}", meeting_type)
                    description = description.replace("{{סוג פגישה}}", meeting_type)  # Try both variants
            
            # Ensure meeting type is replaced even if not in attendee_data
            if "{{סוג הפגישה}}" in description or "{{סוג פגישה}}" in description:
                meeting_type = attendee_data.get('סוג הפגישה', '')
                logger.info(f"Checking meeting type from attendee_data: '{meeting_type}'")
                if meeting_type and meeting_type.strip():
                    logger.info(f"Using meeting type from attendee_data: '{meeting_type}'")
                    description = description.replace("{{סוג הפגישה}}", meeting_type)
                    description = description.replace("{{סוג פגישה}}", meeting_type)
                else:
                    logger.info("Meeting type is empty or not found, using default value: 'לא צוין'")
                    description = description.replace("{{סוג הפגישה}}", "לא צוין")
                    description = description.replace("{{סוג פגישה}}", "לא צוין")
            
            logger.info(f"Final description after all replacements: {description}")
            
            event = {
                'summary': title,
                'description': description,
                'start': {
                    'dateTime': slot.start_time.isoformat(),
                    'timeZone': self.timezone.zone
                },
                'end': {
                    'dateTime': slot.end_time.isoformat(),
                    'timeZone': self.timezone.zone
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 24 * 60},  # 24 hours before
                        {'method': 'popup', 'minutes': 60}  # 1 hour before
                    ]
                },
                'visibility': 'default',  # Use calendar's default visibility
                'transparency': 'opaque',  # Show as busy
                'guestsCanModify': False,  # Prevent guests from modifying
                'guestsCanInviteOthers': False,  # Prevent guests from inviting others
                'guestsCanSeeOtherGuests': False  # Prevent guests from seeing other guests
            }
            
            # Create the event
            event = self.service.events().insert(
                calendarId=settings.get('calendar_id', 'primary'),
                body=event,
                sendUpdates='none'  # Don't send emails since we're using WhatsApp
            ).execute()
            
            logger.info(f"Successfully created calendar event: {event.get('id')}")
            
            # Generate ICS file
            # Pre-process description to handle newlines
            escaped_description = description.replace('\n', '\\n')
            
            ics_lines = [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//WhatsApp Survey Bot//Calendar Manager//EN",
                "CALSCALE:GREGORIAN",
                "METHOD:REQUEST",
                "BEGIN:VEVENT",
                f"UID:{event.get('id')}",
                f"DTSTAMP:{datetime.now(self.timezone).strftime('%Y%m%dT%H%M%SZ')}",
                f"DTSTART;TZID={self.timezone.zone}:{slot.start_time.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID={self.timezone.zone}:{slot.end_time.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:{title}",
                f"DESCRIPTION:{escaped_description}",
                "SEQUENCE:0",
                "STATUS:CONFIRMED",
                "TRANSP:OPAQUE",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                "DESCRIPTION:תזכורת לפגישה",
                "TRIGGER:-P1D",
                "END:VALARM",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                "DESCRIPTION:תזכורת לפגישה",
                "TRIGGER:-PT1H",
                "END:VALARM",
                "END:VEVENT",
                "END:VCALENDAR"
            ]
            
            ics_content = "\r\n".join(ics_lines)
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.ics', delete=False, encoding='utf-8') as f:
                f.write(ics_content)
                temp_file = f.name
            
            return {
                'event_id': event['id'],
                'html_link': event['htmlLink'],
                'ics_file': temp_file
            }
            
        except Exception as e:
            logger.error(f"Error scheduling meeting: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"API Error response: {e.response.text}")
            return None
