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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
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
        logger.info("Initializing CalendarManager")
        self.service = None
        
        # Validate timezone
        try:
            self.timezone = pytz.timezone('Asia/Jerusalem')
        except pytz.exceptions.UnknownTimeZoneError:
            logger.error("Invalid timezone: Asia/Jerusalem")
            self.timezone = pytz.UTC
            logger.info("Defaulting to UTC timezone")
            
        self.available_slots_cache = {}
        self.cache_expiry = 300  # 5 minutes
        
        try:
            # Get service account info from environment variable
            service_account_json = os.getenv('GOOGLE_SERVICE_ACCOUNT')
            if not service_account_json:
                raise ValueError("GOOGLE_SERVICE_ACCOUNT environment variable not set")
            
            try:
                service_account_info = json.loads(service_account_json)
                logger.info("Successfully parsed service account JSON from environment")
            except json.JSONDecodeError:
                logger.error("Invalid JSON in GOOGLE_SERVICE_ACCOUNT environment variable")
                raise
            
            # Validate required fields
            required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 
                             'client_email', 'client_id']
            
            missing_fields = [field for field in required_fields if field not in service_account_info]
            if missing_fields:
                raise ValueError(f"Missing required fields in service account: {', '.join(missing_fields)}")
            
            # Clean and validate private key format
            private_key = service_account_info['private_key'].strip()
            
            # Validate key markers
            if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
                raise ValueError("Invalid private key format - missing BEGIN marker")
            if not private_key.endswith('-----END PRIVATE KEY-----'):
                raise ValueError("Invalid private key format - missing END marker")
            
            # Format private key
            key_lines = private_key.split('\n')
            if len(key_lines) < 3:
                raise ValueError("Invalid private key format - key too short")
            
            service_account_info['private_key'] = '\n'.join([
                '-----BEGIN PRIVATE KEY-----',
                *[line.strip() for line in key_lines[1:-1] if line.strip()],
                '-----END PRIVATE KEY-----\n'
            ])
            
            # Create credentials
            logger.info("Creating service account credentials")
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=['https://www.googleapis.com/auth/calendar']
            )
            
            # Store service account email for later use
            self.service_account_email = service_account_info['client_email']
            logger.info(f"Created credentials for subject: {credentials.service_account_email}")
            
            # Test credentials
            if not credentials.valid:
                logger.error("Credentials are not valid")
                if credentials.expired:
                    logger.error("Credentials are expired")
                if not credentials.has_scopes(['https://www.googleapis.com/auth/calendar']):
                    logger.error("Credentials missing required scopes")
            
            logger.info("Building calendar service")
            self.service = build('calendar', 'v3', credentials=credentials)
            
            # Test API access
            logger.info("Testing calendar API access")
            try:
                test_date = datetime.now()
                test_query = {
                    "timeMin": test_date.isoformat() + 'Z',
                    "timeMax": (test_date + timedelta(minutes=1)).isoformat() + 'Z',
                    "items": [{"id": "primary"}]
                }
                self.service.freebusy().query(body=test_query).execute()
                logger.info("Successfully verified calendar API access")
            except Exception as api_error:
                logger.error(f"Calendar API test failed: {str(api_error)}")
                if hasattr(api_error, 'response') and api_error.response:
                    logger.error(f"API Error response: {api_error.response.text}")
                raise
            
            logger.info("Calendar service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize calendar service: {str(e)}")
            raise

    def ensure_authenticated(self) -> bool:
        """Check if service is initialized."""
        return self.service is not None

    def get_working_hours(self, settings: Dict) -> Dict[str, Dict[str, str]]:
        """Get working hours from settings."""
        return settings.get('working_hours', {
            'sunday': {'start': '09:00', 'end': '17:00'},
            'monday': {'start': '09:00', 'end': '17:00'},
            'tuesday': {'start': '09:00', 'end': '17:00'},
            'wednesday': {'start': '09:00', 'end': '17:00'},
            'thursday': {'start': '09:00', 'end': '17:00'}
        })

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
        if not settings:
            logger.error("No calendar settings provided")
            return []

        if not self.ensure_authenticated():
            logger.error("Calendar service not initialized")
            return []

        try:
            # Check cache first
            cache_key = f"{date.date()}_{json.dumps(settings)}"
            if cache_key in self.available_slots_cache:
                cache_time, slots = self.available_slots_cache[cache_key]
                if (datetime.now() - cache_time).total_seconds() < self.cache_expiry:
                    return slots

            calendar_id = settings.get('calendar_id', 'primary')
            meeting_duration = settings.get('meeting_duration', 30)
            buffer_time = settings.get('buffer_between_meetings', 15)
            working_hours = self.get_working_hours(settings)
            
            # Set start and end time for the day
            start_time = datetime.combine(date.date(), datetime.min.time())
            end_time = datetime.combine(date.date(), datetime.max.time())
            start_time = self.timezone.localize(start_time)
            end_time = self.timezone.localize(end_time)
            
            # Get busy periods
            busy_periods = self._get_busy_periods(calendar_id, start_time, end_time)
            
            # Generate all possible slots
            available_slots = []
            current_time = start_time
            
            while current_time < end_time:
                if self._is_within_working_hours(current_time, working_hours):
                    slot_end = current_time + timedelta(minutes=meeting_duration)
                    
                    # Check if slot overlaps with any busy period
                    is_available = True
                    for busy in busy_periods:
                        busy_start = datetime.fromisoformat(busy['start'].replace('Z', '+00:00'))
                        busy_end = datetime.fromisoformat(busy['end'].replace('Z', '+00:00'))
                        
                        if (current_time < busy_end and 
                            slot_end > busy_start):
                            is_available = False
                            break
                    
                    if is_available:
                        available_slots.append(TimeSlot(current_time, slot_end))
                
                current_time += timedelta(minutes=meeting_duration + buffer_time)
            
            # Cache the results
            self.available_slots_cache[cache_key] = (datetime.now(), available_slots)
            
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
                ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//WhatsApp Survey Bot//Calendar Manager//EN
BEGIN:VEVENT
DTSTART;TZID={self.timezone.zone}:{start_time.strftime('%Y%m%dT%H%M%S')}
DTEND;TZID={self.timezone.zone}:{end_time.strftime('%Y%m%dT%H%M%S')}
DTSTAMP:{datetime.now(self.timezone).strftime('%Y%m%dT%H%M%S')}
UID:{event.get('id')}@whatsapp-survey-bot
CREATED:{datetime.now(self.timezone).strftime('%Y%m%dT%H%M%S')}
DESCRIPTION:{description.replace('\n', '\\n')}
LAST-MODIFIED:{datetime.now(self.timezone).strftime('%Y%m%dT%H%M%S')}
LOCATION:
SEQUENCE:0
STATUS:CONFIRMED
SUMMARY:{title}
TRANSP:OPAQUE
BEGIN:VALARM
TRIGGER:-P1D
ACTION:DISPLAY
DESCRIPTION:תזכורת לפגישה
END:VALARM
BEGIN:VALARM
TRIGGER:-PT1H
ACTION:DISPLAY
DESCRIPTION:תזכורת לפגישה
END:VALARM
END:VEVENT
END:VCALENDAR""".replace('\n', '\r\n')
                
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

    def cancel_meeting(self, event_id: str, calendar_id: str = 'primary') -> bool:
        """Cancel a scheduled meeting."""
        try:
            if not self.ensure_authenticated():
                logger.error("Calendar service not initialized")
                return False

            self.service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
                sendUpdates='all'
            ).execute()
            
            logger.info(f"Successfully cancelled meeting: {event_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling meeting: {str(e)}")
            return False

    def reschedule_meeting(self, event_id: str, new_slot: TimeSlot, 
                         calendar_id: str = 'primary') -> Optional[str]:
        """Reschedule an existing meeting to a new time slot."""
        try:
            if not self.ensure_authenticated():
                logger.error("Calendar service not initialized")
                return None

            # Get existing event
            event = self.service.events().get(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            
            # Update time
            event['start'] = {
                'dateTime': new_slot.start_time.isoformat(),
                'timeZone': self.timezone.zone
            }
            event['end'] = {
                'dateTime': new_slot.end_time.isoformat(),
                'timeZone': self.timezone.zone
            }
            
            # Update event
            updated_event = self.service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event,
                sendUpdates='all'
            ).execute()
            
            logger.info(f"Successfully rescheduled meeting: {event_id}")
            return updated_event.get('id')
            
        except Exception as e:
            logger.error(f"Error rescheduling meeting: {str(e)}")
            return None

    def clear_cache(self) -> None:
        """Clear the available slots cache."""
        self.available_slots_cache = {}
        logger.info("Cleared calendar cache") 
