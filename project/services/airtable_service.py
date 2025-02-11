from typing import Dict, List, Optional
from pyairtable import Api
from ..utils.logger import logger
from ..utils.cache import Cache
from ..models.survey import SurveyDefinition

class AirtableService:
    def __init__(self, api_key: str, base_id: str):
        self.api = Api(api_key)
        self.base_id = base_id
        self.cache = Cache()
        self._batch_queue: List[Dict] = []

    def get_record(self, table_id: str, record_id: str) -> Optional[Dict]:
        """Get record from Airtable with caching"""
        cache_key = f"{table_id}:{record_id}"
        cached_record = self.cache.get(cache_key)
        if cached_record:
            return cached_record

        try:
            table = self.api.table(self.base_id, table_id)
            record = table.get(record_id)
            if record and "fields" in record:
                self.cache.set(cache_key, record["fields"])
                return record["fields"]
        except Exception as e:
            logger.error(f"Error getting Airtable record: {e}")
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