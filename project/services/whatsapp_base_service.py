import asyncio
import json
import aiohttp
from typing import Dict, List, AsyncGenerator, Any, Optional
from aiohttp import ClientTimeout, TCPConnector, ClientSession
from contextlib import asynccontextmanager
from project.utils.logger import logger
from project.models.survey import SurveyDefinition
import os
import time
from dotenv import load_dotenv
from pyairtable import Api

load_dotenv()

# Get environment variables
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")

class WhatsAppBaseService:
    def __init__(self, instance_id: str, api_token: str):
        try:
            self.instance_id = instance_id
            self.api_token = api_token
            self.base_url = f"https://api.greenapi.com/waInstance{instance_id}"
            
            # Initialize Airtable client
            self.airtable = Api(AIRTABLE_API_KEY)
            logger.info("Initialized Airtable client")
            
            # Connection pool settings
            self.MAX_CONNECTIONS = 100
            self.KEEPALIVE_TIMEOUT = 75
            self.DNS_CACHE_TTL = 300
            self.CONNECTION_TIMEOUT = 10
            self.SOCKET_TIMEOUT = 5
            self.MAX_RETRIES = 3
            self.RETRY_DELAY = 2
            
            # Airtable cache
            self.airtable_cache = {}  # Cache for Airtable records
            self.airtable_cache_timeout = 300  # 5 minutes
            
            logger.info("WhatsAppBaseService initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing WhatsAppBaseService: {str(e)}")
            raise

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[ClientSession, None]:
        """Get aiohttp session with optimal settings"""
        timeout = ClientTimeout(
            total=self.CONNECTION_TIMEOUT,
            connect=2,
            sock_read=self.SOCKET_TIMEOUT
        )
        connector = TCPConnector(
            limit=self.MAX_CONNECTIONS,
            ttl_dns_cache=self.DNS_CACHE_TTL,
            keepalive_timeout=self.KEEPALIVE_TIMEOUT
        )
        async with ClientSession(
            timeout=timeout,
            connector=connector,
            headers={'Connection': 'keep-alive'}
        ) as session:
            yield session

    async def send_message_with_retry(self, chat_id: str, message: str) -> Dict:
        """Send a message with retry mechanism"""
        retries = 0
        last_error = None
        
        while retries < self.MAX_RETRIES:
            try:
                async with self.get_session() as session:
                    url = f"{self.base_url}/sendMessage/{self.api_token}"
                    payload = {
                        "chatId": chat_id,
                        "message": message
                    }
                    
                    logger.debug(f"Sending message to {chat_id}: {message[:100]}...")
                    async with session.post(url, json=payload) as response:
                        if response.status == 200:
                            response_data = await response.json()
                            logger.info(f"Message sent successfully to {chat_id}")
                            return response_data
                        
                        last_error = f"HTTP {response.status}"
                        logger.warning(f"Failed to send message (attempt {retries + 1}): {last_error}")
                        
            except Exception as e:
                last_error = str(e)
                logger.error(f"Error sending message (attempt {retries + 1}): {last_error}")
            
            retries += 1
            if retries < self.MAX_RETRIES:
                delay = self.RETRY_DELAY * retries
                logger.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
        
        logger.error(f"Failed to send message after {self.MAX_RETRIES} retries: {last_error}")
        return {"error": f"Failed after {self.MAX_RETRIES} retries: {last_error}"}

    async def send_poll(self, chat_id: str, question: Dict) -> Dict:
        """Send a poll message"""
        try:
            url = f"{self.base_url}/sendPoll/{self.api_token}"
            formatted_options = [{"optionName": opt} for opt in question["options"]]
            
            payload = {
                "chatId": chat_id,
                "message": question["text"],
                "options": formatted_options,
                "multipleAnswers": question.get("multipleAnswers", False)
            }
            
            logger.debug(f"Sending poll to {chat_id}: {question['text']}")
            logger.debug(f"Poll options: {question['options']}")
            
            async with self.get_session() as session:
                async with session.post(url, json=payload) as response:
                    response_text = await response.text()
                    
                    if response.status != 200:
                        logger.error(f"Poll request failed: {response.status}")
                        return {"error": f"Request failed: {response.status}"}
                    
                    try:
                        result = await response.json()
                        logger.info(f"Poll sent successfully to {chat_id}")
                        return result
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON response: {e}")
                        return {"error": "Invalid JSON response"}
                        
        except Exception as e:
            logger.error(f"Error sending poll: {e}")
            return {"error": str(e)}

    async def send_file(self, chat_id: str, file_path: str, caption: str = None) -> Dict:
        """Send a file as attachment"""
        try:
            url = f"{self.base_url}/sendFileByUpload/{self.api_token}"
            
            form = aiohttp.FormData()
            form.add_field('chatId', chat_id)
            if caption:
                form.add_field('caption', caption)
            
            logger.debug(f"Sending file to {chat_id}: {file_path}")
            
            with open(file_path, 'rb') as f:
                file_content = f.read()
                form.add_field('file', file_content, 
                    filename=file_path.split('/')[-1],
                    content_type='application/octet-stream')
                
                async with self.get_session() as session:
                    async with session.post(url, data=form) as response:
                        if response.status == 200:
                            logger.info(f"File sent successfully to {chat_id}")
                            return await response.json()
                        logger.error(f"Failed to send file: HTTP {response.status}")
                        return {"error": f"Failed to send file: HTTP {response.status}"}
                        
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            return {"error": str(e)}

    async def send_messages_batch(self, messages: List[Dict]) -> List[Dict]:
        """Send multiple messages in batch"""
        async def send_single(msg: Dict) -> Dict:
            return await self.send_message_with_retry(msg['chat_id'], msg['text'])
        
        logger.info(f"Sending batch of {len(messages)} messages")
        tasks = []
        for i, msg in enumerate(messages):
            if i > 0 and i % 5 == 0:  # Rate limit: 5 messages at a time
                logger.debug("Rate limit reached, waiting 1 second...")
                await asyncio.sleep(1)
            tasks.append(asyncio.create_task(send_single(msg)))
        
        results = await asyncio.gather(*tasks)
        logger.info(f"Batch sending completed. {len(results)} messages sent.")
        return results

    def get_cached_airtable_record(self, record_id: str, table_id: str) -> Optional[Dict]:
        """Get record from cache if available and not expired"""
        cache_key = f"{table_id}:{record_id}"
        cached_data = self.airtable_cache.get(cache_key)
        if cached_data:
            timestamp, record = cached_data
            if time.time() - timestamp < self.airtable_cache_timeout:
                return record
            else:
                del self.airtable_cache[cache_key]
        return None

    def cache_airtable_record(self, record_id: str, table_id: str, record: Dict) -> None:
        """Cache Airtable record with timestamp"""
        cache_key = f"{table_id}:{record_id}"
        self.airtable_cache[cache_key] = (time.time(), record)
        
        # Cleanup old cache entries
        current_time = time.time()
        expired_keys = [k for k, v in self.airtable_cache.items() 
                       if current_time - v[0] > self.airtable_cache_timeout]
        for k in expired_keys:
            del self.airtable_cache[k]

    async def update_airtable_record(self, record_id: str, data: Dict, survey: SurveyDefinition) -> bool:
        """Update Airtable record."""
        try:
            # Get cached record if available
            cached_record = self.get_cached_airtable_record(record_id, survey.airtable_table_id)
            if cached_record:
                # Merge new data with cached record
                cached_record.update(data)
                self.cache_airtable_record(record_id, survey.airtable_table_id, cached_record)
            
            # Update Airtable directly
            table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
            table.update(record_id, data)
            return True
            
        except Exception as e:
            logger.error(f"Error updating Airtable record: {e}")
            return False

    def clean_text_for_airtable(self, text: str) -> str:
        """Clean text by replacing special characters for Airtable compatibility"""
        if not text:
            return text
            
        # Replace various types of dashes with regular dash
        text = text.replace('–', '-').replace('—', '-').replace('‒', '-').replace('―', '-')
        
        # Remove multiple spaces and trim
        text = ' '.join(text.split())
        
        return text.strip()

    async def get_airtable_field_value(self, record_id: str, field_name: str, survey: SurveyDefinition) -> Optional[str]:
        """Get field value from Airtable record"""
        try:
            # Check cache first
            cached_record = self.get_cached_airtable_record(record_id, survey.airtable_table_id)
            if cached_record and field_name in cached_record:
                return cached_record[field_name]
            
            # If not in cache, fetch from Airtable
            table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
            record = table.get(record_id)
            
            if record and "fields" in record:
                # Cache the record
                self.cache_airtable_record(record_id, survey.airtable_table_id, record["fields"])
                return record["fields"].get(field_name)
                
            return None
        except Exception as e:
            logger.error(f"Error getting Airtable field value: {e}")
            return None

    def create_initial_record(self, chat_id: str, sender_name: str, survey: SurveyDefinition) -> Optional[str]:
        """Create initial record when survey starts"""
        try:
            logger.info(f"Creating initial record for chat_id: {chat_id}, sender_name: {sender_name}, survey: {survey.name}")
            record = {
                "מזהה צ'אט וואטסאפ": chat_id,
                "שם מלא": sender_name,
                "סטטוס": "חדש"
            }
            logger.debug(f"Record data to be created: {json.dumps(record, ensure_ascii=False)}")
            
            table = self.airtable.table(AIRTABLE_BASE_ID, survey.airtable_table_id)
            response = table.create(record)
            logger.info(f"Created initial record: {response}")
            return response["id"]
        except Exception as e:
            logger.error(f"Error creating initial record: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response content: {e.response.text}")
            return None 