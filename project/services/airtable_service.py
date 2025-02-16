from typing import Dict, List, Optional, Any
from pyairtable import Api
from project.utils.logger import logger
from project.utils.cache import Cache
from project.models.survey import SurveyDefinition
from cachetools import TTLCache
import time
from project.config import AIRTABLE_API_KEY, AIRTABLE_BASE_ID, CACHE_TTL, MAX_CACHE_SIZE

class AirtableService:
    def __init__(self):
        self.api = Api(AIRTABLE_API_KEY)
        self.cache = TTLCache(maxsize=MAX_CACHE_SIZE, ttl=CACHE_TTL)
        self.base_id = AIRTABLE_BASE_ID
        self._batch_queue: List[Dict] = []

    def _get_cache_key(self, table_id: str, record_id: str) -> str:
        return f"{table_id}:{record_id}"

    def get_record(self, table_id: str, record_id: str) -> Optional[Dict]:
        """Get a record from Airtable with caching"""
        try:
            # Check cache first
            cache_key = self._get_cache_key(table_id, record_id)
            if cache_key in self.cache:
                logger.debug(f"Cache hit for record {record_id}")
                return self.cache[cache_key]

            # If not in cache, fetch from Airtable
            table = self.api.table(self.base_id, table_id)
            record = table.get(record_id)
            
            if record and "fields" in record:
                # Cache the record
                self.cache[cache_key] = record["fields"]
                return record["fields"]
            
            return None

        except Exception as e:
            logger.error(f"Error getting record from Airtable: {str(e)}")
            return None

    def create_record(self, table_id: str, data: Dict[str, Any]) -> Optional[str]:
        """Create a new record in Airtable"""
        try:
            table = self.api.table(self.base_id, table_id)
            response = table.create(data)
            
            if response and "id" in response:
                # Cache the new record
                cache_key = self._get_cache_key(table_id, response["id"])
                self.cache[cache_key] = response["fields"]
                return response["id"]
            
            return None

        except Exception as e:
            logger.error(f"Error creating record in Airtable: {str(e)}")
            return None

    def update_record(self, table_id: str, record_id: str, data: Dict[str, Any]) -> bool:
        """Update an existing record in Airtable"""
        try:
            table = self.api.table(self.base_id, table_id)
            response = table.update(record_id, data)
            
            if response and "fields" in response:
                # Update cache
                cache_key = self._get_cache_key(table_id, record_id)
                self.cache[cache_key] = response["fields"]
                return True
            
            return False

        except Exception as e:
            logger.error(f"Error updating record in Airtable: {str(e)}")
            return False

    def get_records(self, table_id: str, formula: Optional[str] = None) -> list:
        """Get multiple records from Airtable"""
        try:
            table = self.api.table(self.base_id, table_id)
            
            if formula:
                records = table.all(formula=formula)
            else:
                records = table.all()
            
            # Cache all records
            for record in records:
                if "id" in record and "fields" in record:
                    cache_key = self._get_cache_key(table_id, record["id"])
                    self.cache[cache_key] = record["fields"]
            
            return records

        except Exception as e:
            logger.error(f"Error getting records from Airtable: {str(e)}")
            return []

    def delete_record(self, table_id: str, record_id: str) -> bool:
        """Delete a record from Airtable"""
        try:
            table = self.api.table(self.base_id, table_id)
            table.delete(record_id)
            
            # Remove from cache
            cache_key = self._get_cache_key(table_id, record_id)
            if cache_key in self.cache:
                del self.cache[cache_key]
            
            return True

        except Exception as e:
            logger.error(f"Error deleting record from Airtable: {str(e)}")
            return False

    def clear_cache(self):
        """Clear the entire cache"""
        self.cache.clear()
        logger.info("Airtable cache cleared")

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