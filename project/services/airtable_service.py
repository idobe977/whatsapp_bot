import os
from typing import Dict, List, Optional
from pyairtable import Api
from project.utils.logger import logger
from project.utils.cache import Cache
from project.models.survey import SurveyDefinition
import aiohttp

class AirtableService:
    def __init__(self):
        self.api_key = os.getenv("AIRTABLE_API_KEY")
        self.base_url = "https://api.airtable.com/v0"
        self.cache = Cache()
        self._batch_queue: List[Dict] = []

    async def get_record(self, record_id: str, table_name: str) -> Optional[Dict]:
        """
        מקבל רשומה מאירטייבל לפי מזהה
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/{table_name}/{record_id}"
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

    def create_record(self, table_id: str, data: Dict) -> Optional[str]:
        """Create new record in Airtable"""
        try:
            table = self.api.table(self.base_id, table_id)
            response = table.create(data)
            return response["id"]
        except Exception as e:
            logger.error(f"Error creating Airtable record: {e}")
            return None

    def update_record(self, table_id: str, record_id: str, data: Dict) -> bool:
        """Update record in Airtable with batching support"""
        try:
            # Update cache
            cache_key = f"{table_id}:{record_id}"
            cached_record = self.cache.get(cache_key)
            if cached_record:
                cached_record.update(data)
                self.cache.set(cache_key, cached_record)

            # Add to batch queue
            self._batch_queue.append({
                'table_id': table_id,
                'record_id': record_id,
                'data': data
            })

            # Process batch if queue is full
            if len(self._batch_queue) >= 10:
                self._process_batch()

            return True
        except Exception as e:
            logger.error(f"Error updating Airtable record: {e}")
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

    def get_existing_record_id(self, table_id: str, chat_id: str) -> Optional[str]:
        """Get existing record ID for a chat_id"""
        try:
            table = self.api.table(self.base_id, table_id)
            records = table.all(formula=f"{{מזהה צ'אט בוואטסאפ}} = '{chat_id}'")
            if records:
                return records[-1]["id"]
            return None
        except Exception as e:
            logger.error(f"Error getting record ID: {e}")
            return None

    def create_initial_record(self, chat_id: str, sender_name: str, survey: SurveyDefinition) -> Optional[str]:
        """Create initial record when survey starts"""
        try:
            record = {
                "מזהה צ'אט וואטסאפ": chat_id,
                "שם מלא": sender_name,
                "סטטוס": "חדש"
            }
            return self.create_record(survey.airtable_table_id, record)
        except Exception as e:
            logger.error(f"Error creating initial record: {e}")
            return None 
