import json
import os
from typing import Dict, List
from survey_definitions import SurveyDefinition

def load_survey_from_json(file_path: str) -> SurveyDefinition:
    """Load survey definition from a JSON file"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    required_fields = ['name', 'trigger_phrases', 'airtable_table_id', 'questions']
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field in survey JSON: {field}")
    
    return SurveyDefinition(
        name=data['name'],
        trigger_phrases=data['trigger_phrases'],
        airtable_table_id=data['airtable_table_id'],
        questions=data['questions']
    )

def load_all_surveys(surveys_dir: str = 'surveys') -> List[SurveyDefinition]:
    """Load all survey definitions from JSON files in the specified directory"""
    if not os.path.exists(surveys_dir):
        os.makedirs(surveys_dir)
        
    surveys = []
    for filename in os.listdir(surveys_dir):
        if filename.endswith('.json'):
            file_path = os.path.join(surveys_dir, filename)
            try:
                survey = load_survey_from_json(file_path)
                surveys.append(survey)
            except Exception as e:
                print(f"Error loading survey from {filename}: {str(e)}")
    
    return surveys

def create_survey_template(output_path: str) -> None:
    """Create a template JSON file for a new survey"""
    template = {
        "name": "new_survey",
        "trigger_phrases": [
            "התחל שאלון חדש",
            "שאלון חדש"
        ],
        "airtable_table_id": "YOUR_TABLE_ID_HERE",
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

if __name__ == "__main__":
    # Create a template if running directly
    create_survey_template('surveys/template_survey.json') 