import os
import json
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import base64
import urllib.parse
from functools import lru_cache
import hashlib

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar']

@dataclass
class TimeSlot:
    start_time: datetime
    end_time: datetime
    
    def __str__(self) -> str:
        return f"{self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')}"

class CalendarManager:
    def __init__(self):
        """Initialize the calendar manager with service account credentials from environment."""
        self.service = None
        self.timezone = pytz.timezone('Asia/Jerusalem')
        self.available_slots_cache = {}
        self.cache_expiry = 300  # 5 minutes
        
        try:
            service_account_json = os.getenv('GOOGLE_SERVICE_ACCOUNT')
            if not service_account_json:
                raise ValueError("GOOGLE_SERVICE_ACCOUNT environment variable not set")
            
            service_account_info = json.loads(service_account_json)
            
            # Validate required fields
            required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 
                             'client_email', 'client_id']
            
            missing_fields = [field for field in required_fields if field not in service_account_info]
            if missing_fields:
                raise ValueError(f"Missing required fields in service account: {', '.join(missing_fields)}")
            
            # Format private key
            private_key = service_account_info['private_key'].strip()
            service_account_info['private_key'] = self._format_private_key(private_key)
            
            # Create credentials
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=SCOPES
            )
            
            # Store service account email for later use
            self.service_account_email = service_account_info['client_email']
            
            self.service = build('calendar', 'v3', credentials=credentials)
            
            # Test API access
            self._test_api_access()
            
        except Exception as e:
            logger.error(f"Failed to initialize calendar service: {str(e)}")
            raise

    def _format_private_key(self, private_key: str) -> str:
        """Format private key for proper use."""
        if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
            raise ValueError("Invalid private key format - missing BEGIN marker")
        if not private_key.endswith('-----END PRIVATE KEY-----'):
            raise ValueError("Invalid private key format - missing END marker")
        
        key_lines = private_key.split('\n')
        if len(key_lines) < 3:
            raise ValueError("Invalid private key format - key too short")
        
        return '\n'.join([
            '-----BEGIN PRIVATE KEY-----',
            *[line.strip() for line in key_lines[1:-1] if line.strip()],
            '-----END PRIVATE KEY-----\n'
        ])

    def _test_api_access(self) -> None:
        """Test calendar API access."""
        try:
            test_date = datetime.now()
            test_query = {
                "timeMin": test_date.isoformat() + 'Z',
                "timeMax": (test_date + timedelta(minutes=1)).isoformat() + 'Z',
                "items": [{"id": "primary"}]
            }
            self.service.freebusy().query(body=test_query).execute()
        except Exception as api_error:
            logger.error("Calendar API test failed")
            if hasattr(api_error, 'response') and api_error.response:
                logger.error(f"API Error response: {api_error.response.text}")
            raise

    def ensure_authenticated(self) -> bool:
        """Check if service is initialized."""
        return self.service is not None

    @lru_cache(maxsize=100)
    def get_working_hours(self, settings_hash: str) -> Dict[str, Dict[str, str]]:
        """Get working hours from settings with caching."""
        settings = json.loads(settings_hash)
        return settings.get('working_hours', {
            'sunday': {'start': '09:00', 'end': '17:00'},
            'monday': {'start': '09:00', 'end': '17:00'},
            'tuesday': {'start': '09:00', 'end': '17:00'},
            'wednesday': {'start': '09:00', 'end': '17:00'},
            'thursday': {'start': '09:00', 'end': '17:00'}
        })

    def _hash_settings(self, settings: Dict) -> str:
        """Create a hash of settings for cache key."""
        return hashlib.md5(json.dumps(settings, sort_keys=True).encode()).hexdigest()

    def _is_within_working_hours(self, dt: datetime, working_hours: Dict) -> bool:
        """Check if datetime is within working hours."""
        day_name = dt.strftime('%A').lower()
        if day_name not in working_hours:
            return False
            
        hours = working_hours[day_name]
        start_time = datetime.strptime(hours['start'], '%H:%M').time()
        end_time = datetime.strptime(hours['end'], '%H:%M').time()
        return start_time <= dt.time() <= end_time

    def _get_busy_periods(self, calendar_id: str, start_time: datetime, end_time: datetime) -> List[Dict]:
        """Get busy time periods from Google Calendar."""
        try:
            logger.info(f"Getting busy periods for calendar {calendar_id}")
            logger.info(f"Time range: {start_time.isoformat()} to {end_time.isoformat()}")
            
            if not self.ensure_authenticated():
                logger.error("Calendar service not initialized")
                return []
            
            events_result = self.service.freebusy().query(
                body={
                    "timeMin": start_time.isoformat(),
                    "timeMax": end_time.isoformat(),
                    "items": [{"id": calendar_id}]
                }
            ).execute()
            
            logger.info("Successfully retrieved busy periods")
            return events_result['calendars'][calendar_id]['busy']
            
        except Exception as e:
            logger.error(f"Error getting busy periods: {str(e)}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"API Error response: {e.response.text}")
            return []

    def _format_date_for_display(self, date: datetime) -> str:
        """Format date as 'יום שלישי 13/2'."""
        day_name_map = {
            'Sunday': 'ראשון',
            'Monday': 'שני',
            'Tuesday': 'שלישי',
            'Wednesday': 'רביעי',
            'Thursday': 'חמישי',
            'Friday': 'שישי',
            'Saturday': 'שבת'
        }
        
        # Get Hebrew day name
        day_name = day_name_map[date.strftime('%A')]
        
        # Format as D/M
        date_str = date.strftime('%-d/%-m')  # Use - to remove leading zeros
        
        return f'יום {day_name} {date_str}'

    def get_available_slots(self, settings: Dict, date: datetime) -> List[TimeSlot]:
        """Get available time slots for a specific date."""
        if not settings or not self.ensure_authenticated():
            return []

        try:
            # Create cache key
            settings_hash = self._hash_settings(settings)
            cache_key = f"{date.date()}_{settings_hash}"
            
            # Check cache
            if cache_key in self.available_slots_cache:
                cache_time, slots = self.available_slots_cache[cache_key]
                if (datetime.now() - cache_time).total_seconds() < self.cache_expiry:
                    return slots

            calendar_id = settings.get('calendar_id', 'primary')
            meeting_duration = settings.get('meeting_duration', 30)
            buffer_time = settings.get('buffer_between_meetings', 15)
            working_hours = self.get_working_hours(json.dumps(settings))
            
            # Set time range
            start_time = self.timezone.localize(datetime.combine(date.date(), datetime.min.time()))
            end_time = self.timezone.localize(datetime.combine(date.date(), datetime.max.time()))
            
            # Get busy periods
            busy_periods = self._get_busy_periods(calendar_id, start_time, end_time)
            
            # Generate available slots
            available_slots = []
            current_time = start_time
            
            while current_time < end_time:
                if self._is_within_working_hours(current_time, working_hours):
                    slot_end = current_time + timedelta(minutes=meeting_duration)
                    
                    if not any(
                        current_time < datetime.fromisoformat(busy['end'].replace('Z', '+00:00')) and
                        slot_end > datetime.fromisoformat(busy['start'].replace('Z', '+00:00'))
                        for busy in busy_periods
                    ):
                        available_slots.append(TimeSlot(current_time, slot_end))
                
                current_time += timedelta(minutes=meeting_duration + buffer_time)
            
            # Update cache
            self.available_slots_cache[cache_key] = (datetime.now(), available_slots)
            
            # Cleanup old cache entries if needed
            if len(self.available_slots_cache) > 1000:
                oldest_key = min(self.available_slots_cache.keys(), 
                               key=lambda k: self.available_slots_cache[k][0])
                del self.available_slots_cache[oldest_key]
            
            return available_slots
            
        except Exception as e:
            logger.error(f"Error getting available slots: {str(e)}")
            return []

    def schedule_meeting(self, settings: Dict, slot: TimeSlot, attendee_data: Dict) -> Optional[Dict]:
        """Schedule a meeting in Google Calendar and generate ICS file."""
        try:
            if not self.ensure_authenticated():
                logger.error("Calendar service not initialized")
                return None

            # Get calendar ID from settings - this should be the email address of the calendar owner
            calendar_id = settings.get('calendar_id')
            if not calendar_id:
                logger.error("No calendar_id provided in settings")
                return None
                
            # Validate calendar_id format
            if not '@' in calendar_id or not '.' in calendar_id:
                logger.error(f"Invalid calendar_id format: {calendar_id}")
                return None
                
            logger.info(f"Scheduling meeting in calendar: {calendar_id}")
            
            # Verify the calendar exists and is accessible
            try:
                self.service.calendars().get(calendarId=calendar_id).execute()
            except Exception as e:
                logger.error(f"Calendar {calendar_id} not found or not accessible: {str(e)}")
                return None
            
            # Format meeting title and description using templates
            title_template = settings.get('meeting_title_template', 'פגישה עם {{שם מלא}}')
            desc_template = settings.get('meeting_description_template', 
                'נקבע דרך בוט WhatsApp\nטלפון: {{phone}}')
            
            # Replace placeholders with actual values
            title = title_template
            description = desc_template
            for key, value in attendee_data.items():
                title = title.replace(f"{{{{{key}}}}}", str(value))
                description = description.replace(f"{{{{{key}}}}}", str(value))
            
            # Ensure timezone is properly set
            start_time = slot.start_time
            end_time = slot.end_time
            if not start_time.tzinfo:
                start_time = self.timezone.localize(start_time)
            if not end_time.tzinfo:
                end_time = self.timezone.localize(end_time)
            
            logger.info(f"Creating event: {title}")
            logger.info(f"Start time: {start_time.isoformat()}")
            logger.info(f"End time: {end_time.isoformat()}")
            logger.info(f"Timezone: {self.timezone.zone}")
            
            event = {
                'summary': title,
                'description': description,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': self.timezone.zone,
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': self.timezone.zone,
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 24 * 60},  # 24 hours before
                        {'method': 'popup', 'minutes': 60},  # 1 hour before
                    ]
                },
                'visibility': 'default',  # Use calendar's default visibility
                'transparency': 'opaque',  # Show as busy
                'guestsCanModify': False,  # Prevent guests from modifying
                'guestsCanInviteOthers': False,  # Prevent guests from inviting others
                'guestsCanSeeOtherGuests': False  # Prevent guests from seeing other guests
            }
            
            try:
                event = self.service.events().insert(
                    calendarId=calendar_id,
                    body=event,
                    sendUpdates='none',
                    supportsAttachments=True
                ).execute()
                
                logger.info(f"Successfully scheduled meeting: {event.get('id')}")
                logger.info(f"Event link: {event.get('htmlLink')}")
                
                # Generate ICS file content
                description_escaped = description.replace('\n', '\\n')
                ics_content = '\r\n'.join([
                    "BEGIN:VCALENDAR",
                    "VERSION:2.0",
                    "PRODID:-//WhatsApp Survey Bot//Calendar Manager//EN",
                    "BEGIN:VEVENT",
                    f"DTSTART;TZID={self.timezone.zone}:{start_time.strftime('%Y%m%dT%H%M%S')}",
                    f"DTEND;TZID={self.timezone.zone}:{end_time.strftime('%Y%m%dT%H%M%S')}",
                    f"DTSTAMP:{datetime.now(self.timezone).strftime('%Y%m%dT%H%M%S')}",
                    f"UID:{event.get('id')}@whatsapp-survey-bot",
                    f"CREATED:{datetime.now(self.timezone).strftime('%Y%m%dT%H%M%S')}",
                    f"DESCRIPTION:{description_escaped}",
                    f"LAST-MODIFIED:{datetime.now(self.timezone).strftime('%Y%m%dT%H%M%S')}",
                    "LOCATION:",
                    "SEQUENCE:0",
                    "STATUS:CONFIRMED",
                    f"SUMMARY:{title}",
                    "TRANSP:OPAQUE",
                    "BEGIN:VALARM",
                    "TRIGGER:-P1D",
                    "ACTION:DISPLAY",
                    "DESCRIPTION:תזכורת לפגישה",
                    "END:VALARM",
                    "BEGIN:VALARM",
                    "TRIGGER:-PT1H",
                    "ACTION:DISPLAY",
                    "DESCRIPTION:תזכורת לפגישה",
                    "END:VALARM",
                    "END:VEVENT",
                    "END:VCALENDAR"
                ])
                
                # Create temporary file
                temp_file = f"/tmp/meeting_{event.get('id')}.ics"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    f.write(ics_content)
                
                return {
                    'event_id': event.get('id'),
                    'html_link': event.get('htmlLink'),
                    'ics_file': temp_file
                }
                
            except Exception as api_error:
                logger.error(f"Google Calendar API error: {str(api_error)}")
                if hasattr(api_error, 'response') and api_error.response:
                    logger.error(f"API Error response: {api_error.response.text}")
                raise
            
        except Exception as e:
            logger.error(f"Error scheduling meeting: {str(e)}")
            return None

    def clear_cache(self) -> None:
        """Clear all caches."""
        self.available_slots_cache.clear()
        self.get_working_hours.cache_clear()  # Clear LRU cache
        logger.info("Cleared calendar cache") 
