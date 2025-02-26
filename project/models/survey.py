from dataclasses import dataclass
from typing import Dict, List, Optional
import os

@dataclass
class SurveyDefinition:
    name: str
    trigger_phrases: List[str]
    airtable_table_id: str
    questions: List[Dict]
    airtable_base_id: str = None
    messages: Dict = None
    ai_prompts: Dict = None
    calendar_settings: Dict = None

    def __post_init__(self):
        self.airtable_base_id = self.airtable_base_id or os.getenv("AIRTABLE_BASE_ID")
        self.messages = self.messages or {
            "welcome": "ברוכים הבאים לשאלון!",
            "completion": {
                "text": "תודה רבה על מילוי השאלון!",
                "should_generate_summary": True
            },
            "timeout": "השאלון בוטל עקב חוסר פעילות. אנא התחל מחדש.",
            "error": "מצטערים, הייתה שגיאה בעיבוד התשובה. נא לנסות שוב.",
            "file_upload": {
                "success": "הקובץ התקבל בהצלחה!",
                "invalid_type": "סוג הקובץ שנשלח אינו נתמך. אנא שלח קובץ מסוג: {allowed_types}",
                "too_large": "הקובץ גדול מדי. הגודל המקסימלי המותר הוא 5MB",
                "missing": "אנא שלח קובץ כדי להמשיך"
            }
        }
        self.ai_prompts = self.ai_prompts or {
            "reflections": {
                "empathetic": {
                    "name": "תגובה אמפתית",
                    "prompt": "צור תגובה אמפתית וחמה"
                },
                "professional": {
                    "name": "תגובה מקצועית",
                    "prompt": "צור תגובה מקצועית ותכליתית"
                }
            },
            "summary": {
                "prompt": "צור סיכום מקיף של כל התשובות בשאלון",
                "max_length": 500,
                "include_recommendations": True
            }
        }
        self.calendar_settings = self.calendar_settings or {} 
