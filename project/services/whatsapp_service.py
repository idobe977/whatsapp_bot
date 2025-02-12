import asyncio
import json
import aiohttp
from typing import Dict, List, AsyncGenerator, Any
from aiohttp import ClientTimeout, TCPConnector, ClientSession
from contextlib import asynccontextmanager
from project.utils.logger import logger
from project.models.survey import SurveyDefinition
import os
import glob

class WhatsAppService:
    def __init__(self, instance_id: str, api_token: str):
        self.instance_id = instance_id
        self.api_token = api_token
        self.base_url = f"https://api.greenapi.com/waInstance{instance_id}"
        
        # Connection pool settings
        self.MAX_CONNECTIONS = 100
        self.KEEPALIVE_TIMEOUT = 75
        self.DNS_CACHE_TTL = 300
        self.CONNECTION_TIMEOUT = 10
        self.SOCKET_TIMEOUT = 5
        self.MAX_RETRIES = 3
        self.RETRY_DELAY = 2

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

    async def send_message(self, chat_id: str, message: str) -> Dict:
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
                    
                    async with session.post(url, json=payload) as response:
                        if response.status == 200:
                            response_data = await response.json()
                            logger.info(f"Message sent successfully to {chat_id}")
                            return response_data
                        
                        last_error = f"HTTP {response.status}"
                        
            except Exception as e:
                last_error = str(e)
            
            retries += 1
            if retries < self.MAX_RETRIES:
                await asyncio.sleep(self.RETRY_DELAY * retries)
        
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
            
            async with self.get_session() as session:
                async with session.post(url, json=payload) as response:
                    response_text = await response.text()
                    
                    if response.status != 200:
                        logger.error(f"Poll request failed: {response.status}")
                        return {"error": f"Request failed: {response.status}"}
                    
                    try:
                        return await response.json()
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
            
            with open(file_path, 'rb') as f:
                file_content = f.read()
                form.add_field('file', file_content, 
                    filename=file_path.split('/')[-1],
                    content_type='application/octet-stream')
                
                async with self.get_session() as session:
                    async with session.post(url, data=form) as response:
                        if response.status == 200:
                            return await response.json()
                        return {"error": f"Failed to send file: HTTP {response.status}"}
                        
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            return {"error": str(e)}

    async def send_messages_batch(self, messages: List[Dict]) -> List[Dict]:
        """Send multiple messages in batch"""
        async def send_single(msg: Dict) -> Dict:
            return await self.send_message(msg['chat_id'], msg['text'])
        
        tasks = []
        for i, msg in enumerate(messages):
            if i > 0 and i % 5 == 0:  # Rate limit: 5 messages at a time
                await asyncio.sleep(1)
            tasks.append(asyncio.create_task(send_single(msg)))
        
        return await asyncio.gather(*tasks)

def load_surveys_from_json() -> List[SurveyDefinition]:
    """Load all survey definitions from JSON files in the surveys directory"""
    surveys = []
    surveys_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'surveys')
    
    if not os.path.exists(surveys_dir):
        os.makedirs(surveys_dir)
        logger.info(f"Created surveys directory: {surveys_dir}")
        return []

    for file_path in glob.glob(os.path.join(surveys_dir, '*.json')):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            survey = SurveyDefinition(
                name=data['name'],
                trigger_phrases=data['trigger_phrases'],
                airtable_table_id=data['airtable']['table_id'],
                airtable_base_id=data['airtable'].get('base_id'),
                questions=data['questions'],
                messages=data.get('messages'),
                ai_prompts=data.get('ai_prompts'),
                calendar_settings=data.get('calendar_settings')
            )
            surveys.append(survey)
            logger.info(f"Successfully loaded survey: {survey.name} from {file_path}")
        except Exception as e:
            logger.error(f"Error loading survey from {file_path}: {str(e)}")
            
    return surveys 