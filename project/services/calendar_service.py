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

    def get_available_slots(self, settings: Dict, date: datetime) -> List[TimeSlot]:
        """Get available time slots for a given date"""
        try:
            # Get working hours with default values
            default_working_hours = {
                'sunday': {'start': '09:00', 'end': '14:00'},
                'monday': {'start': '09:00', 'end': '14:00'},
                'tuesday': {'start': '09:00', 'end': '11:00'},
                'wednesday': {'start': '09:00', 'end': '14:00'},
                'thursday': {'start': '09:00', 'end': '11:00'}
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
            
            # Calculate minimum start time (2 hours from now)
            now = datetime.now(self.timezone)
            min_start_time = now + timedelta(hours=2)
            
            # If minimum start time is after today's end time, return empty list
            if min_start_time.date() == date.date() and min_start_time >= day_end:
                return []
            
            # Adjust day_start if minimum start time is later
            if min_start_time.date() == date.date() and min_start_time > day_start:
                day_start = min_start_time
            
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
                        # Jump to the end of this event for next slot
                        current_slot_start = event_end
                        break
                
                if is_available:
                    available_slots.append(TimeSlot(current_slot_start, slot_end))
                    current_slot_start = slot_end + buffer_time
                elif not is_available and current_slot_start == day_start:
                    # If first slot is not available, add buffer time
                    current_slot_start += buffer_time
            
            return available_slots
            
        except Exception as e:
            logger.error(f"Error getting available slots: {e}")
            return []

    def schedule_meeting(self, settings: Dict, slot: TimeSlot, attendee_data: Dict) -> Optional[Dict]:
        """Schedule a meeting in the selected time slot"""
        try:
            # Get meeting title and description from templates
            title = settings.get('meeting_title_template', 'פגישה')
            description = settings.get('meeting_description_template', 'פגישה שנקבעה דרך הבוט')
            
            # Replace placeholders in title and description
            for key, value in attendee_data.items():
                title = title.replace(f"{{{{שם מלא}}}}", attendee_data.get('שם מלא', ''))
                description = description.replace(f"{{{{phone}}}}", attendee_data.get('phone', ''))
            
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
