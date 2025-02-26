import os
from typing import Dict, List, Optional
import aiohttp
from project.utils.logger import logger
from project.utils.cache import Cache
from project.models.survey import SurveyDefinition

class AirtableService:
    def __init__(self):
        self.api_key = os.getenv("AIRTABLE_API_KEY")
        self.base_id = os.getenv("AIRTABLE_BASE_ID")
        self.base_url = f"https://api.airtable.com/v0/{self.base_id}"
        self.cache = Cache()
        self._batch_queue: List[Dict] = []

    async def get_record(self, record_id: str, table_id: str) -> Optional[Dict]:
        """
        מקבל רשומה מאירטייבל לפי מזהה
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/{table_id}/{record_id}"
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("fields", {})
                    else:
                        error_text = await response.text()
                        logger.error(f"Airtable API error: {response.status} - {error_text}")
                        return None

        except Exception as e:
            logger.error(f"Error in get_record: {str(e)}")
            return None

    async def create_record(self, table_id: str, data: Dict) -> Optional[str]:
        """יצירת רשומה חדשה באירטייבל"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "fields": data
            }
            
            logger.debug(f"Creating record in table {table_id} with data: {data}")  # הוספת לוג
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/{table_id}"
                async with session.post(url, headers=headers, json=payload) as response:
                    response_text = await response.text()
                    logger.debug(f"Airtable response: {response.status} - {response_text}")  # הוספת לוג
                    
                    if response.status == 200:
                        data = await response.json()
                        return data.get("id")
                    else:
                        logger.error(f"Airtable API error: {response.status} - {response_text}")
                        return None

        except Exception as e:
            logger.error(f"Error creating record: {str(e)}")
            return None

    async def update_record(self, table_id: str, record_id: str, data: Dict) -> bool:
        """עדכון רשומה באירטייבל"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "fields": data
            }
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/{table_id}/{record_id}"
                async with session.patch(url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Airtable API error: {response.status} - {error_text}")
                        return False

        except Exception as e:
            logger.error(f"Error updating record: {str(e)}")
            return False

    def _process_batch(self) -> None:
        """Process batched updates"""
        if not self._batch_queue:
            return

        try:
            # Group updates by table
            updates_by_table = {}
            for update in self._batch_queue:
                table_id = update['table_id']
                if table_id not in updates_by_table:
                    updates_by_table[table_id] = []
                updates_by_table[table_id].append({
                    'id': update['record_id'],
                    'fields': update['data']
                })

            # Process each table's updates
            for table_id, records in updates_by_table.items():
                table = self.api.table(self.base_id, table_id)
                table.batch_update(records)

            # Clear the queue
            self._batch_queue.clear()

        except Exception as e:
            logger.error(f"Error processing Airtable batch: {e}")

    async def get_existing_record_id(self, table_id: str, chat_id: str) -> Optional[str]:
        """מציאת מזהה רשומה קיימת לפי מזהה צ'אט"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            formula = f"SEARCH('{chat_id}', {{מזהה צ'אט וואטסאפ}})"
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/{table_id}?filterByFormula={formula}"
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        records = data.get("records", [])
                        if records:
                            return records[-1]["id"]
                    return None

        except Exception as e:
            logger.error(f"Error getting existing record: {str(e)}")
            return None

    async def create_initial_record(self, chat_id: str, sender_name: str, survey: SurveyDefinition) -> Optional[str]:
        """יצירת רשומה התחלתית כשמתחיל שאלון"""
        try:
            record = {
                "מזהה צ'אט וואטסאפ": chat_id,
                "שם מלא": sender_name,
                "סטטוס": "חדש"
            }
            logger.debug(f"Creating initial record for survey {survey.name} with data: {record}")  # הוספת לוג
            return await self.create_record(survey.airtable_table_id, record)
        except Exception as e:
            logger.error(f"Error creating initial record: {str(e)}")
            return None 
