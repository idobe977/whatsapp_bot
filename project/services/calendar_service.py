import os
import json
import tempfile
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pytz
from project.utils.logger import logger

class TimeSlot:
    def __init__(self, start_time: datetime, end_time: datetime):
        self.start_time = start_time
        self.end_time = end_time

    def __str__(self) -> str:
        return f"{self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')}"

class CalendarService:
    def __init__(self):
        """Initialize the Calendar API service"""
        self.service = None
        self.timezone = pytz.timezone('Asia/Jerusalem')
        self.setup_service()

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

    def get_available_slots(self, settings: Dict, date: datetime) -> List[TimeSlot]:
        """Get available time slots for a given date"""
        try:
            # Get working hours with default values
            default_working_hours = {
                'sunday': {'start': '09:00', 'end': '17:00'},
                'monday': {'start': '09:00', 'end': '17:00'},
                'tuesday': {'start': '09:00', 'end': '17:00'},
                'wednesday': {'start': '09:00', 'end': '17:00'},
                'thursday': {'start': '09:00', 'end': '17:00'}
            }
            working_hours = settings.get('working_hours', default_working_hours)
            
            # Get current day's working hours
            day_name = date.strftime('%A').lower()
            if day_name not in working_hours:
                logger.warning(f"No working hours defined for {day_name}")
                return []
                
            day_hours = working_hours[day_name]
            
            # Parse working hours
            start_hour, start_minute = map(int, day_hours['start'].split(':'))
            end_hour, end_minute = map(int, day_hours['end'].split(':'))
            
            # Create datetime objects for start and end of working day
            day_start = self.timezone.localize(date.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0))
            day_end = self.timezone.localize(date.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0))
            
            # Get existing events
            events_result = self.service.events().list(
                calendarId=settings.get('calendar_id', 'primary'),
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            
            # Create time slots
            slot_duration = timedelta(minutes=settings.get('slot_duration_minutes', 60))
            buffer_time = timedelta(minutes=settings.get('buffer_between_meetings', 15))
            current_slot_start = day_start
            available_slots = []
            
            while current_slot_start + slot_duration <= day_end:
                slot_end = current_slot_start + slot_duration
                is_available = True
                
                # Check if slot overlaps with any existing event
                for event in events:
                    event_start = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')))
                    event_end = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')))
                    
                    if (current_slot_start < event_end and slot_end > event_start):
                        is_available = False
                        break
                
                if is_available:
                    available_slots.append(TimeSlot(current_slot_start, slot_end))
                
                current_slot_start = slot_end + buffer_time
            
            return available_slots
            
        except Exception as e:
            logger.error(f"Error getting available slots: {e}")
            return []

    def schedule_meeting(self, settings: Dict, slot: TimeSlot, attendee_data: Dict) -> Optional[Dict]:
        """Schedule a meeting in the selected time slot"""
        try:
            event = {
                'summary': settings.get('event_title', 'פגישה'),
                'description': settings.get('event_description', 'פגישה שנקבעה דרך הבוט'),
                'start': {
                    'dateTime': slot.start_time.isoformat(),
                    'timeZone': self.timezone.zone
                },
                'end': {
                    'dateTime': slot.end_time.isoformat(),
                    'timeZone': self.timezone.zone
                },
                'attendees': [
                    {'email': settings.get('organizer_email')},
                    {'email': attendee_data.get('email')}
                ] if attendee_data.get('email') else None,
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 30},
                        {'method': 'email', 'minutes': 60}
                    ]
                }
            }
            
            # Create the event
            event = self.service.events().insert(
                calendarId=settings.get('calendar_id', 'primary'),
                body=event,
                sendUpdates='all'
            ).execute()
            
            # Generate ICS file
            ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//WhatsApp Survey Bot//Calendar Manager//EN
BEGIN:VEVENT
DTSTART;TZID={self.timezone.zone}:{slot.start_time.strftime('%Y%m%dT%H%M%S')}
DTEND;TZID={self.timezone.zone}:{slot.end_time.strftime('%Y%m%dT%H%M%S')}
SUMMARY:{event.get('summary', 'פגישה')}
DESCRIPTION:{event.get('description', 'פגישה שנקבעה דרך הבוט')}
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:תזכורת לפגישה
TRIGGER:-PT30M
END:VALARM
END:VEVENT
END:VCALENDAR""".replace('\n', '\r\n')
            
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
            return None
