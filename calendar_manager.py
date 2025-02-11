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

SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/calendar.settings.readonly'
]
SERVICE_ACCOUNT_FILE = 'credentials/service-account.json'

@dataclass
class TimeSlot:
    start_time: datetime
    end_time: datetime
    
    def __str__(self) -> str:
        return f"{self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')}"

class CalendarManager:
    def __init__(self, service_account_file: str = 'credentials/service-account.json'):
        """Initialize the calendar manager with service account credentials."""
        self.service = None
        self.timezone = pytz.timezone('Asia/Jerusalem')
        self.available_slots_cache = {}
        self.cache_expiry = 300  # 5 minutes
        
        try:
            # Try different possible file names
            possible_files = [
                service_account_file,
                service_account_file + '.json',
                service_account_file.replace('.json', '') + '.json'
            ]
            
            self.SERVICE_ACCOUNT_FILE = None
            for file_path in possible_files:
                if os.path.exists(file_path):
                    self.SERVICE_ACCOUNT_FILE = file_path
                    break
            
            if not self.SERVICE_ACCOUNT_FILE:
                raise FileNotFoundError(f"Service account file not found. Tried: {', '.join(possible_files)}")
            
            # Get absolute path and log it
            abs_path = os.path.abspath(self.SERVICE_ACCOUNT_FILE)
            logger.info(f"Found service account file at: {abs_path}")
            
            # Read and validate the file content
            with open(self.SERVICE_ACCOUNT_FILE, 'r') as f:
                try:
                    json_content = json.load(f)
                    logger.info(f"Successfully read service account file, size: {len(str(json_content))} bytes")
                    
                    # Validate required fields
                    required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 
                                     'client_email', 'client_id']
                    missing_fields = [field for field in required_fields if field not in json_content]
                    if missing_fields:
                        raise ValueError(f"Missing required fields in service account JSON: {', '.join(missing_fields)}")
                    
                    # Store client email for later use
                    self.client_email = json_content['client_email']
                    
                    # Clean and validate private key
                    private_key = json_content['private_key']
                    if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
                        raise ValueError("Invalid private key format - missing BEGIN marker")
                    if not private_key.strip().endswith('-----END PRIVATE KEY-----'):
                        raise ValueError("Invalid private key format - missing END marker")
                    
                    # Remove any extra whitespace or newlines
                    private_key_lines = private_key.strip().split('\n')
                    if len(private_key_lines) < 3:
                        raise ValueError("Invalid private key format - key too short")
                    
                    # Reconstruct private key with proper line breaks
                    json_content['private_key'] = '\n'.join([
                        '-----BEGIN PRIVATE KEY-----',
                        *[line.strip() for line in private_key_lines[1:-1]],
                        '-----END PRIVATE KEY-----\n'
                    ])
                    
                    logger.info("Service account file validated successfully")
                    
                    # Write back the cleaned private key
                    with open(self.SERVICE_ACCOUNT_FILE, 'w') as f:
                        json.dump(json_content, f, indent=2)
                    
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON format in service account file: {str(e)}")
            
            # Initialize the Calendar API with explicit timezone
            credentials = service_account.Credentials.from_service_account_file(
                self.SERVICE_ACCOUNT_FILE,
                scopes=['https://www.googleapis.com/auth/calendar.events']
            )
            
            self.service = build('calendar', 'v3', credentials=credentials)
            
            # Test API access
            try:
                # Try to access the calendar directly instead of listing calendars
                test_date = datetime.now()
                test_query = {
                    "timeMin": test_date.isoformat() + 'Z',
                    "timeMax": (test_date + timedelta(minutes=1)).isoformat() + 'Z',
                    "items": [{"id": "primary"}]
                }
                self.service.freebusy().query(body=test_query).execute()
                logger.info("Successfully verified calendar API access")
                
            except Exception as api_error:
                error_message = str(api_error)
                if 'invalid_grant' in error_message:
                    logger.error(f"Calendar API access denied. Please verify:")
                    logger.error(f"1. Project '{json_content['project_id']}' is enabled in Google Cloud Console")
                    logger.error(f"2. Google Calendar API is enabled for the project")
                    logger.error(f"3. Calendar is shared with: {self.client_email}")
                    raise ValueError("Calendar API access denied - see logs for details")
                else:
                    raise
            
            logger.info("Calendar service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize calendar service: {str(e)}")
            if isinstance(e, FileNotFoundError):
                logger.error(f"Service account file not found at any of these locations: {', '.join(possible_files)}")
            elif isinstance(e, json.JSONDecodeError):
                logger.error("Service account file contains invalid JSON")
            elif isinstance(e, ValueError):
                logger.error(f"Service account validation error: {str(e)}")
            else:
                logger.error(f"Unexpected error type: {type(e).__name__}")
                if hasattr(e, 'response'):
                    logger.error(f"Response content: {e.response.text}")
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
            events_result = self.service.freebusy().query(
                body={
                    "timeMin": start_time.isoformat(),
                    "timeMax": end_time.isoformat(),
                    "items": [{"id": calendar_id}]
                }
            ).execute()
            
            return events_result['calendars'][calendar_id]['busy']
            
        except Exception as e:
            logger.error(f"Error getting busy periods: {str(e)}")
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

    def schedule_meeting(self, settings: Dict, slot: TimeSlot, attendee_data: Dict) -> Optional[str]:
        """Schedule a meeting in Google Calendar."""
        try:
            if not self.ensure_authenticated():
                logger.error("Calendar service not initialized")
                return None

            calendar_id = settings.get('calendar_id', 'primary')
            
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
            
            event = {
                'summary': title,
                'description': description,
                'start': {
                    'dateTime': slot.start_time.isoformat(),
                    'timeZone': self.timezone.zone,
                },
                'end': {
                    'dateTime': slot.end_time.isoformat(),
                    'timeZone': self.timezone.zone,
                }
            }
            
            # Add attendee email if provided
            if 'email' in attendee_data:
                event['attendees'] = [{'email': attendee_data['email']}]
            
            event = self.service.events().insert(
                calendarId=calendar_id,
                body=event,
                sendUpdates='all' if 'email' in attendee_data else 'none'
            ).execute()
            
            logger.info(f"Successfully scheduled meeting: {event.get('id')}")
            return event.get('id')
            
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
