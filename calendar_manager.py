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
        logger.info("Initializing CalendarManager")
        self.SERVICE_ACCOUNT_FILE = service_account_file
        self.service = None
        self.timezone = pytz.timezone('Asia/Jerusalem')
        self.available_slots_cache = {}
        self.cache_expiry = 300  # 5 minutes
        
        try:
            # Validate service account file
            self._validate_service_account_file()
            
            # Get absolute path of service account file
            abs_path = os.path.abspath(self.SERVICE_ACCOUNT_FILE)
            logger.info(f"Using service account file at: {abs_path}")
            
            # Initialize the Calendar API
            logger.info("Creating service account credentials")
            
            # Read the service account file again after validation
            with open(self.SERVICE_ACCOUNT_FILE, 'r') as f:
                service_account_info = json.load(f)
            
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=['https://www.googleapis.com/auth/calendar']
            )
            
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
            
        except FileNotFoundError:
            logger.error(f"Service account file not found at: {self.SERVICE_ACCOUNT_FILE}")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize calendar service: {str(e)}")
            raise

    def _validate_service_account_file(self) -> None:
        """Validate service account file format and JWT components."""
        try:
            logger.info("Starting service account file validation")
            
            # Check file exists and is readable
            if not os.path.exists(self.SERVICE_ACCOUNT_FILE):
                logger.error(f"Service account file does not exist at: {self.SERVICE_ACCOUNT_FILE}")
                raise FileNotFoundError(f"Service account file not found at: {self.SERVICE_ACCOUNT_FILE}")
                
            # Read and parse JSON
            with open(self.SERVICE_ACCOUNT_FILE, 'r') as f:
                logger.info("Reading service account file")
                try:
                    json_content = json.load(f)
                    logger.info(f"Successfully read JSON file, size: {len(str(json_content))} bytes")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON: {str(e)}")
                    raise
                
            # Validate required fields
            required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 
                             'client_email', 'client_id']
            
            missing_fields = []
            for field in required_fields:
                if field not in json_content:
                    missing_fields.append(field)
                else:
                    # Log field presence (without sensitive data)
                    if field in ['private_key', 'private_key_id']:
                        logger.info(f"Found {field} (value hidden)")
                    else:
                        logger.info(f"Found {field}: {json_content[field]}")
            
            if missing_fields:
                logger.error(f"Missing required fields: {', '.join(missing_fields)}")
                raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")
            
            # Clean and validate private key format
            private_key = json_content['private_key']
            
            # Remove any extra whitespace and ensure proper line endings
            private_key = private_key.strip()
            
            # Validate key markers
            if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
                logger.error("Private key missing BEGIN marker")
                raise ValueError("Invalid private key format - missing BEGIN marker")
            if not private_key.endswith('-----END PRIVATE KEY-----'):
                logger.error("Private key missing END marker")
                raise ValueError("Invalid private key format - missing END marker")
            
            # Split the key into lines
            key_lines = private_key.split('\n')
            if len(key_lines) < 3:
                logger.error("Private key too short")
                raise ValueError("Invalid private key format - key too short")
            
            # Reconstruct the key with proper formatting
            formatted_key = '\n'.join([
                '-----BEGIN PRIVATE KEY-----',
                *[line.strip() for line in key_lines[1:-1] if line.strip()],
                '-----END PRIVATE KEY-----\n'
            ])
            
            # Update the private key in the JSON content
            json_content['private_key'] = formatted_key
            
            # Write back the cleaned JSON
            with open(self.SERVICE_ACCOUNT_FILE, 'w') as f:
                json.dump(json_content, f, indent=2)
                logger.info("Wrote back cleaned service account file")
            
            logger.info("Service account file validation completed successfully")
            
        except Exception as e:
            logger.error(f"Service account validation failed: {str(e)}")
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
