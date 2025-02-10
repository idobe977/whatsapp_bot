import os
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle
from typing import List, Dict, Optional
import pytz

class CalendarManager:
    """מנהל הפגישות והסנכרון עם Google Calendar"""
    
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    TOKEN_FILE = 'token.pickle'
    
    def __init__(self):
        self.timezone = pytz.timezone('Asia/Jerusalem')
        self.service = self._get_calendar_service()
        self.calendar_id = 'primary'  # משתמש ביומן הראשי
        
    def _get_calendar_service(self):
        """יצירת חיבור לשירות Google Calendar"""
        creds = None
        is_production = os.getenv('ENVIRONMENT') == 'production'
        
        # בסביבת ייצור - נשתמש בטוקנים מוגדרים מראש
        if is_production:
            creds = Credentials(
                token=os.getenv('GOOGLE_ACCESS_TOKEN'),
                refresh_token=os.getenv('GOOGLE_REFRESH_TOKEN'),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=os.getenv("GOOGLE_CLIENT_ID"),
                client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
                scopes=self.SCOPES
            )
            return build('calendar', 'v3', credentials=creds)
        
        # בסביבת פיתוח - נשתמש בקובץ token.pickle
        if os.path.exists(self.TOKEN_FILE):
            with open(self.TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
                
        # בדיקה אם ההרשאות תקפות
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # הגדרת תצורת OAuth
                client_config = {
                    "installed": {
                        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                        "project_id": os.getenv("GOOGLE_PROJECT_ID"),
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                        "redirect_uris": ["http://localhost:8080/"]
                    }
                }
                
                flow = InstalledAppFlow.from_client_config(client_config, self.SCOPES)
                # Try different ports if 8080 is taken
                for port in [8080, 8081, 8082, 8083, 8084, 8085]:
                    try:
                        creds = flow.run_local_server(port=port)
                        # Print tokens for production setup
                        print("\n=== Production Tokens ===")
                        print(f"GOOGLE_ACCESS_TOKEN={creds.token}")
                        print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
                        print("======================\n")
                        break
                    except OSError:
                        if port == 8085:  # Last attempt
                            raise
                        continue
                
                # שמירת ההרשאות לשימוש עתידי
                with open(self.TOKEN_FILE, 'wb') as token:
                    pickle.dump(creds, token)
                    
        return build('calendar', 'v3', credentials=creds)
    
    def get_available_days(self, start_date: datetime, days_ahead: int = 14) -> List[datetime]:
        """קבלת רשימת הימים הזמינים לפגישות"""
        end_date = start_date + timedelta(days=days_ahead)
        
        # קבלת כל האירועים בטווח התאריכים
        events_result = self.service.events().list(
            calendarId=self.calendar_id,
            timeMin=start_date.isoformat() + 'Z',
            timeMax=end_date.isoformat() + 'Z',
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        
        # מציאת ימים עם פחות מ-8 שעות תפוסות
        available_days = []
        current_date = start_date
        
        while current_date <= end_date:
            if current_date.weekday() < 5:  # רק ימי חול
                day_events = [e for e in events if current_date.date() == datetime.fromisoformat(e['start'].get('dateTime', e['start'].get('date'))).date()]
                total_hours = sum((datetime.fromisoformat(e['end'].get('dateTime')) - 
                                 datetime.fromisoformat(e['start'].get('dateTime'))).total_seconds() / 3600 
                                for e in day_events if 'dateTime' in e['start'])
                
                if total_hours < 8:
                    available_days.append(current_date)
            
            current_date += timedelta(days=1)
            
        return available_days
    
    def get_available_slots(self, date: datetime) -> List[Dict]:
        """קבלת חלונות זמן פנויים ביום מסוים"""
        # הגדרת שעות העבודה
        work_start = date.replace(hour=9, minute=0, second=0, microsecond=0)
        work_end = date.replace(hour=17, minute=0, second=0, microsecond=0)
        
        # קבלת אירועים מהיומן
        events_result = self.service.events().list(
            calendarId=self.calendar_id,
            timeMin=work_start.isoformat() + 'Z',
            timeMax=work_end.isoformat() + 'Z',
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        
        # יצירת חלונות זמן של 30 דקות
        slots = []
        current_time = work_start
        
        while current_time < work_end:
            slot_end = current_time + timedelta(minutes=30)
            is_available = True
            
            # בדיקה אם החלון פנוי
            for event in events:
                event_start = datetime.fromisoformat(event['start'].get('dateTime'))
                event_end = datetime.fromisoformat(event['end'].get('dateTime'))
                
                if (current_time < event_end and slot_end > event_start):
                    is_available = False
                    break
            
            if is_available:
                slots.append({
                    'start': current_time.strftime('%H:%M'),
                    'end': slot_end.strftime('%H:%M')
                })
            
            current_time = slot_end
            
        return slots
    
    def schedule_meeting(self, start_time: datetime, duration: int = 30, 
                        subject: str = "פגישת ייעוץ", description: str = "") -> bool:
        """קביעת פגישה ביומן"""
        end_time = start_time + timedelta(minutes=duration)
        
        event = {
            'summary': subject,
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Jerusalem',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Jerusalem',
            },
            'reminders': {
                'useDefault': True
            }
        }
        
        try:
            self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
            return True
        except Exception as e:
            print(f"Error scheduling meeting: {e}")
            return False 
