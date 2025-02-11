import os
import json
import logging
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
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

# If modifying these scopes, delete the stored credentials
SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_DIR = 'credentials'

@dataclass
class TimeSlot:
    start_time: datetime
    end_time: datetime
    
    def __str__(self) -> str:
        return f"{self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')}"

class CalendarManager:
    def __init__(self):
        self.service = None
        self.credentials = None
        self.timezone = pytz.timezone('Asia/Jerusalem')
        self.available_slots_cache = {}
        self.cache_expiry = 300  # 5 minutes
        logger.info("Calendar Manager initialized without authentication")

    def _get_credentials_path(self, user_id: str = 'default') -> str:
        """Get the path for storing credentials."""
        if not os.path.exists(CREDENTIALS_DIR):
            os.makedirs(CREDENTIALS_DIR)
        return os.path.join(CREDENTIALS_DIR, f'{user_id}_token.json')

    def _get_credentials_from_file(self, user_id: str) -> Optional[Credentials]:
        """Get credentials from file."""
        try:
            creds_path = self._get_credentials_path(user_id)
            if os.path.exists(creds_path):
                with open(creds_path, 'r') as token:
                    creds_dict = json.load(token)
                    return Credentials.from_authorized_user_info(creds_dict)
            return None
        except Exception as e:
            logger.error(f"Error getting credentials from file: {str(e)}")
            return None

    def _save_credentials_to_file(self, user_id: str, credentials: Credentials) -> bool:
        """Save credentials to file."""
        try:
            creds_path = self._get_credentials_path(user_id)
            creds_dict = {
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': credentials.scopes
            }
            with open(creds_path, 'w') as token:
                json.dump(creds_dict, token)
            return True
        except Exception as e:
            logger.error(f"Error saving credentials to file: {str(e)}")
            return False

    def ensure_authenticated(self, user_id: str = 'default') -> bool:
        """Ensure the service is authenticated before use."""
        try:
            if self.service is not None:
                return True

            creds = self._get_credentials_from_file(user_id)
                
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    self._save_credentials_to_file(user_id, creds)
                else:
                    return False

            self.service = build('calendar', 'v3', credentials=creds)
            logger.info("Successfully initialized Google Calendar service")
            return True
            
        except Exception as e:
            logger.error(f"Error ensuring authentication: {str(e)}")
            return False

    def start_auth_flow(self, user_id: str = 'default') -> str:
        """Start the OAuth flow and return the authorization URL."""
        try:
            client_config = {
                "web": {
                    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                    "redirect_uris": [os.getenv("GOOGLE_REDIRECT_URI")],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            }
            
            flow = InstalledAppFlow.from_client_config(
                client_config,
                SCOPES,
                redirect_uri=os.getenv("GOOGLE_REDIRECT_URI")
            )
            
            auth_url, state = flow.authorization_url(access_type='offline')
            
            # Store flow configuration in a temporary file
            flow_config = {
                'client_id': os.getenv("GOOGLE_CLIENT_ID"),
                'client_secret': os.getenv("GOOGLE_CLIENT_SECRET"),
                'redirect_uri': os.getenv("GOOGLE_REDIRECT_URI"),
                'state': state,
                'scope': SCOPES
            }
            
            flow_path = os.path.join(CREDENTIALS_DIR, f'{user_id}_flow.json')
            with open(flow_path, 'w') as f:
                json.dump(flow_config, f)
            
            return auth_url
            
        except Exception as e:
            logger.error(f"Error starting auth flow: {str(e)}")
            raise

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

    def get_available_slots(self, settings: Dict, date: datetime) -> List[TimeSlot]:
        """Get available time slots for a specific date."""
        if not self.ensure_authenticated():
            raise Exception("Authentication required")

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
