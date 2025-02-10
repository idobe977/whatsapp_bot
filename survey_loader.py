import json
import os
from typing import Dict, List
from survey_definitions import SurveyDefinition
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_survey_from_json(file_path: str) -> SurveyDefinition:
    """Load survey definition from a JSON file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        required_fields = ['name', 'trigger_phrases', 'airtable', 'questions', 'messages', 'ai_prompts']
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field in survey JSON: {field}")
                
        if 'table_id' not in data['airtable']:
            raise ValueError("Missing table_id in airtable configuration")
            
        # וידוא שדות חובה בהודעות
        required_messages = ['welcome', 'completion', 'timeout', 'error']
        for msg in required_messages:
            if msg not in data['messages']:
                raise ValueError(f"Missing '{msg}' in messages")
                
        # וידוא שדות חובה ב-AI prompts
        if 'reflections' not in data['ai_prompts'] or 'summary' not in data['ai_prompts']:
            raise ValueError("Missing required sections in ai_prompts")
            
        # וידוא שיש לפחות סוג אחד של תגובה רפלקטיבית
        if len(data['ai_prompts']['reflections']) == 0:
            raise ValueError("At least one reflection type must be defined")
            
        # וידוא שלכל שאלה יש הגדרות תגובה רפלקטיבית תקינות
        for question in data['questions']:
            if 'reflection' not in question:
                question['reflection'] = {"type": "none", "enabled": False}
            elif question['reflection']['type'] != 'none' and question['reflection']['type'] not in data['ai_prompts']['reflections']:
                raise ValueError(f"Invalid reflection type '{question['reflection']['type']}' in question '{question['id']}'")
        
        return SurveyDefinition(
            name=data['name'],
            trigger_phrases=data['trigger_phrases'],
            airtable_table_id=data['airtable']['table_id'],
            airtable_base_id=data['airtable'].get('base_id'),
            questions=data['questions'],
            messages=data['messages'],
            ai_prompts=data['ai_prompts']
        )
    except Exception as e:
        logger.error(f"Error loading survey from {file_path}: {str(e)}")
        raise

def load_all_surveys(surveys_dir: str = 'surveys') -> List[SurveyDefinition]:
    """Load all survey definitions from JSON files in the specified directory"""
    if not os.path.exists(surveys_dir):
        os.makedirs(surveys_dir)
        logger.info(f"Created surveys directory: {surveys_dir}")
        
    surveys = []
    for filename in os.listdir(surveys_dir):
        if filename.endswith('.json'):
            file_path = os.path.join(surveys_dir, filename)
            try:
                survey = load_survey_from_json(file_path)
                surveys.append(survey)
                logger.info(f"Successfully loaded survey: {survey.name} from {filename}")
            except Exception as e:
                logger.error(f"Error loading survey from {filename}: {str(e)}")
    
    return surveys

def create_survey_template(output_path: str) -> None:
    """Create a template JSON file for a new survey"""
    template = {
        "name": "new_survey",
        "trigger_phrases": [
            "התחל שאלון חדש",
            "שאלון חדש"
        ],
        "airtable": {
            "table_id": "YOUR_TABLE_ID_HERE",
            "base_id": "OPTIONAL_BASE_ID"  # אופציונלי
        },
        "messages": {
            "welcome": "ברוכים הבאים לשאלון! 👋\nנשמח לשמוע את דעתך.",
            "completion": {
                "text": "תודה רבה על מילוי השאלון! 🙏\nנשמח להיות איתך בקשר בקרוב.",
                "should_generate_summary": True
            },
            "timeout": "השאלון בוטל עקב חוסר פעילות. אנא התחל מחדש.",
            "error": "מצטערים, הייתה שגיאה בעיבוד התשובה. נא לנסות שוב."
        },
        "ai_prompts": {
            "reflections": {
                "empathetic": {
                    "name": "תגובה אמפתית",
                    "prompt": """
                    בהתבסס על התשובה של המשתמש לשאלה, צור תגובה אמפתית וחמה שמשקפת את מה שהוא אמר.
                    התגובה צריכה להיות קצרה (1-2 משפטים) ולהראות הבנה רגשית.
                    
                    הנחיות:
                    1. שקף את הרגשות והתחושות שעולים מהתשובה
                    2. השתמש בשפה חמה ותומכת
                    3. הראה הבנה והזדהות
                    4. הוסף אימוגי מתאים
                    5. שמור על טון אישי וחברותי
                    """
                },
                "professional": {
                    "name": "תגובה מקצועית",
                    "prompt": """
                    בהתבסס על התשובה של המשתמש לשאלה, צור תגובה מקצועית ותכליתית.
                    התגובה צריכה להיות קצרה (1-2 משפטים) ולהדגיש את ההיבטים העסקיים.
                    
                    הנחיות:
                    1. התמקד בתובנות המקצועיות
                    2. השתמש בשפה עסקית ומדויקת
                    3. הדגש נקודות מפתח
                    4. שמור על טון מקצועי ומכבד
                    5. הוסף ערך באמצעות תובנה קצרה
                    """
                }
            },
            "summary": {
                "prompt": """
                צור סיכום מקיף של כל התשובות בשאלון.
                הדגש את הנקודות העיקריות והתובנות המרכזיות.
                
                הנחיות:
                1. התמקד בתובנות המשמעותיות ביותר
                2. שמור על פרטיות המשיב
                3. כתוב בצורה מובנת וברורה
                4. הוסף המלצות אם רלוונטי
                5. שמור על טון מקצועי ואמפתי
                """,
                "max_length": 500,  # אורך מקסימלי לסיכום
                "include_recommendations": True  # האם לכלול המלצות בסיכום
            }
        },
        "questions": [
            {
                "id": "שם_מלא",
                "type": "text",
                "text": "מה השם המלא שלך?",
                "reflection": {
                    "type": "empathetic",  # סוג התגובה הרפלקטיבית: empathetic/professional
                    "enabled": True  # האם להגיב רפלקטיבית
                }
            },
            {
                "id": "גיל",
                "type": "text",
                "text": "מה הגיל שלך?",
                "reflection": {
                    "type": "none",  # ללא תגובה רפלקטיבית
                    "enabled": False
                }
            },
            {
                "id": "תחביבים",
                "type": "poll",
                "text": "מה התחביבים שלך?",
                "options": [
                    "ספורט",
                    "קריאה",
                    "מוזיקה",
                    "אחר"
                ],
                "multipleAnswers": True,
                "reflection": {
                    "type": "professional",
                    "enabled": True
                }
            }
        ]
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
        logger.info(f"Created survey template at: {output_path}")

if __name__ == "__main__":
    # Create a template if running directly
    create_survey_template('surveys/template_survey.json') 
