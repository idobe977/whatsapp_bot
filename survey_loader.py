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
            
        required_fields = ['name', 'trigger_phrases', 'airtable', 'questions']
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field in survey JSON: {field}")
                
        if 'table_id' not in data['airtable']:
            raise ValueError("Missing table_id in airtable configuration")
        
        return SurveyDefinition(
            name=data['name'],
            trigger_phrases=data['trigger_phrases'],
            airtable_table_id=data['airtable']['table_id'],
            airtable_base_id=data['airtable'].get('base_id'),
            questions=data['questions']
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
        "questions": [
            {
                "id": "שם_מלא",
                "type": "text",
                "text": "מה השם המלא שלך?"
            },
            {
                "id": "גיל",
                "type": "text",
                "text": "מה הגיל שלך?"
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
                "multipleAnswers": True
            }
        ]
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
        logger.info(f"Created survey template at: {output_path}")

if __name__ == "__main__":
    # Create a template if running directly
    create_survey_template('surveys/template_survey.json') 
