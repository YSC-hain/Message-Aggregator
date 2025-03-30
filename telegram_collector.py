import asyncio
import logging
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import InputPeerChannel, MessageMediaPhoto, MessageMediaDocument
import os
from typing import List, Dict, Any, Optional
import json

class TelegramCollector:
    def __init__(self, api_id: str, api_hash: str, session_name: str = "telegram_collector"):
        """
        Initialize the Telegram collector.
        
        Args:
            api_id: Telegram API ID
            api_hash: Telegram API hash
            session_name: Session name for Telethon client
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.logger = logging.getLogger(__name__)
        
        # Create directory for downloaded media
        self.media_dir = os.path.join(os.getcwd(), "media")
        os.makedirs(self.media_dir, exist_ok=True)
    
    async def start(self):
        """Start the Telegram client."""
        await self.client.start()
        self.logger.info("Telegram client started")
    
    async def stop(self):
        """Stop the Telegram client."""
        await self.client.disconnect()
        self.logger.info("Telegram client stopped")
    
    async def get_channel_info(self, channel_username: str) -> Dict[str, Any]:
        """
        Get information about a channel.
        
        Args:
            channel_username: Channel username or ID
            
        Returns:
            Dictionary with channel info
        """
        entity = await self.client.get_entity(channel_username)
        return {
            "id": entity.id,
            "title": entity.title if hasattr(entity, "title") else None,
            "username": entity.username if hasattr(entity, "username") else None,
            "description": entity.about if hasattr(entity, "about") else None,
            "participants_count": await self.client.get_participants_count(entity) if hasattr(self.client, "get_participants_count") else None
        }
    
    async def download_media(self, message) -> Optional[str]:
        """
        Download media from a message and return the local path.
        
        Args:
            message: Telegram message object
            
        Returns:
            Path to downloaded media or None
        """
        if message.media:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{message.id}_{timestamp}"
            path = await self.client.download_media(message.media, file=os.path.join(self.media_dir, filename))
            return path
        return None
    
    # Add this function to the TelegramCollector class
    async def verify_channels(self, channel_usernames: List[str]) -> List[str]:
        """Verify channel usernames and return the list of accessible channels."""
        accessible_channels = []
        
        for username in channel_usernames:
            try:
                entity = await self.client.get_entity(username)
                self.logger.info(f"Channel {username} is accessible (ID: {entity.id})")
                accessible_channels.append(username)
            except Exception as e:
                self.logger.error(f"Cannot access channel {username}: {str(e)}")
        
        return accessible_channels

    async def get_new_messages_without_duplication(self, channel_usernames: List[str], limit: int = 100, fallback_hours: int = 24):
        """
        Collect only genuinely new messages without duplication.
        
        Args:
            channel_usernames: List of channel usernames to collect from
            limit: Maximum number of messages to collect per channel
            fallback_hours: Hours to look back if message ID tracking is unavailable
            
        Returns:
            List of processed message dictionaries
        """
        all_messages = []
        last_message_tracking = self._load_last_message_tracking()
        
        for username in channel_usernames:
            try:
                self.logger.info(f"Attempting to access channel: {username}")
                entity = await self.client.get_entity(username)
                channel_id = str(entity.id)
                self.logger.info(f"Successfully resolved entity for {username}: ID {entity.id}")
                
                # Get channel information
                channel_info = await self.get_channel_info(username)
                
                # Determine collection strategy
                use_id_tracking = channel_id in last_message_tracking and last_message_tracking[channel_id] > 0
                
                if use_id_tracking:
                    # Get messages newer than the last processed message ID
                    last_message_id = last_message_tracking[channel_id]
                    self.logger.info(f"Retrieving messages newer than ID {last_message_id} for {username}")
                    
                    messages = await self.client(GetHistoryRequest(
                        peer=entity,
                        limit=limit,
                        offset_date=None,
                        offset_id=0,
                        max_id=0,
                        min_id=last_message_id + 1,
                        add_offset=0,
                        hash=0
                    ))
                else:
                    # Fallback: Get messages from the last fallback_hours
                    from datetime import timezone, datetime, timedelta
                    since_date = datetime.now(timezone.utc) - timedelta(hours=fallback_hours)
                    self.logger.info(f"No message tracking data for {username}, falling back to time-based retrieval (since {since_date.isoformat()})")
                    
                    messages = await self.client(GetHistoryRequest(
                        peer=entity,
                        limit=limit,
                        offset_date=None,
                        offset_id=0,
                        max_id=0,
                        min_id=0,
                        add_offset=0,
                        hash=0
                    ))
                
                self.logger.info(f"Retrieved {len(messages.messages)} raw messages from {username}")
                
                # Process messages
                message_count = 0
                channel_messages = []
                
                for msg in messages.messages:
                    # If using time-based fallback, filter by date
                    if not use_id_tracking:
                        msg_date = msg.date
                        if msg_date.tzinfo is None:
                            msg_date = msg_date.replace(tzinfo=timezone.utc)
                        
                        if msg_date < since_date:
                            continue
                    
                    # Download media if present
                    media_path = await self.download_media(msg)
                    media_type = None
                    
                    if isinstance(msg.media, MessageMediaPhoto):
                        media_type = "photo"
                    elif isinstance(msg.media, MessageMediaDocument):
                        media_type = "document"
                    
                    # Handle reply relationships
                    reply_to_msg_id = None
                    reply_to_msg_text = None
                    
                    if hasattr(msg, 'reply_to') and msg.reply_to:
                        reply_to_msg_id = msg.reply_to.reply_to_msg_id
                        
                        try:
                            # Find the original message in the current batch first
                            original_msg = next((m for m in messages.messages if m.id == reply_to_msg_id), None)
                            
                            # If not found in the current batch, try to fetch it from the server
                            if not original_msg:
                                original_msg = await self.client.get_messages(entity, ids=reply_to_msg_id)
                                
                            # If we found the original message, get its text
                            if original_msg:
                                reply_to_msg_text = original_msg.message if hasattr(original_msg, "message") else ""
                                
                        except Exception as e:
                            self.logger.warning(f"Could not fetch replied-to message {reply_to_msg_id}: {str(e)}")
                    
                    # Create message data dictionary
                    message_data = {
                        "id": msg.id,
                        "channel_id": entity.id,
                        "channel_title": channel_info.get("title"),
                        "channel_username": channel_info.get("username"),
                        "channel_description": channel_info.get("description"),
                        "date": msg.date.isoformat(),
                        "text": msg.message if hasattr(msg, "message") else "",
                        "media_path": media_path,
                        "media_type": media_type,
                        "views": msg.views if hasattr(msg, "views") else None,
                        "forwards": msg.forwards if hasattr(msg, "forwards") else None,
                        "reply_to_msg_id": reply_to_msg_id,
                        "reply_to_msg_text": reply_to_msg_text
                    }
                    
                    channel_messages.append(message_data)
                    message_count += 1
                
                # Update message tracking with the newest message ID
                if channel_messages and use_id_tracking:
                    newest_id = max(msg["id"] for msg in channel_messages)
                    last_message_tracking[channel_id] = max(newest_id, last_message_tracking[channel_id])
                elif channel_messages:
                    # Initialize tracking for this channel
                    newest_id = max(msg["id"] for msg in channel_messages)
                    last_message_tracking[channel_id] = newest_id
                
                # Add all messages from this channel to the main collection
                all_messages.extend(channel_messages)
                self.logger.info(f"Added {message_count} messages from {username}")
                
            except Exception as e:
                self.logger.error(f"Error retrieving messages from {username}: {str(e)}")
        
        # Save updated tracking information
        self._save_last_message_tracking(last_message_tracking)
        
        # Sort messages by date
        all_messages.sort(key=lambda x: x["date"])
        self.logger.info(f"Total messages collected from all channels: {len(all_messages)}")
        return all_messages

    def _load_last_message_tracking(self) -> Dict[str, int]:
        """Load the tracking data for last processed message IDs."""
        tracking_file = os.path.join(os.getcwd(), "data", "last_message_tracking.json")
        
        if os.path.exists(tracking_file):
            try:
                with open(tracking_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"Error loading message tracking data: {str(e)}")
        
        return {}  # Return empty dict if file doesn't exist or has errors

    def _save_last_message_tracking(self, tracking_data: Dict[str, int]):
        """Save the tracking data for last processed message IDs."""
        os.makedirs(os.path.join(os.getcwd(), "data"), exist_ok=True)
        tracking_file = os.path.join(os.getcwd(), "data", "last_message_tracking.json")
        
        try:
            with open(tracking_file, 'w', encoding='utf-8') as f:
                json.dump(tracking_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving message tracking data: {str(e)}")

    async def get_new_messages(self, channel_usernames: List[str], limit: int = 100, since_hours: int = 24) -> List[Dict[str, Any]]:
        all_messages = []
        
        # Create timezone-aware datetime for comparison
        from datetime import timezone
        since_date = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        
        for username in channel_usernames:
            try:
                self.logger.info(f"Attempting to access channel: {username}")
                
                try:
                    entity = await self.client.get_entity(username)
                except ValueError as e:
                    self.logger.error(f"Invalid channel identifier for {username}: {str(e)}")
                    continue
                except Exception as e:
                    self.logger.error(f"Failed to get entity for {username}: {str(e)}")
                    continue
                    
                self.logger.info(f"Successfully resolved entity for {username}: ID {entity.id}")
                
                try:
                    channel_info = await self.get_channel_info(username)
                except Exception as e:
                    self.logger.error(f"Failed to get channel info for {username}: {str(e)}")
                    channel_info = {"id": entity.id, "title": username}
                
                # Get message history
                self.logger.info(f"Retrieving message history for {username}")
                messages = await self.client(GetHistoryRequest(
                    peer=entity,
                    limit=limit,
                    offset_date=None,
                    offset_id=0,
                    max_id=0,
                    min_id=0,
                    add_offset=0,
                    hash=0
                ))
                
                self.logger.info(f"Retrieved {len(messages.messages)} raw messages from {username}")
                
                message_count = 0
                channel_messages = []  # Track messages from this channel
                
                for msg in messages.messages:
                    # Ensure message date is timezone-aware for comparison
                    msg_date = msg.date
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                    
                    if msg_date < since_date:
                        continue
                    
                    # Download media if present
                    media_path = await self.download_media(msg)
                    media_type = None
                    
                    if isinstance(msg.media, MessageMediaPhoto):
                        media_type = "photo"
                    elif isinstance(msg.media, MessageMediaDocument):
                        media_type = "document"
                    
                    # Check if this message is a reply
                    reply_to_msg_id = None
                    reply_to_msg_text = None
                    
                    if hasattr(msg, 'reply_to') and msg.reply_to:
                        # Get the ID of the message being replied to
                        reply_to_msg_id = msg.reply_to.reply_to_msg_id
                        
                        # Try to fetch the original message
                        try:
                            # Find the original message in the current batch first
                            original_msg = next((m for m in messages.messages if m.id == reply_to_msg_id), None)
                            
                            # If not found in the current batch, try to fetch it from the server
                            if not original_msg:
                                original_msg = await self.client.get_messages(entity, ids=reply_to_msg_id)
                                
                            # If we found the original message, get its text
                            if original_msg:
                                reply_to_msg_text = original_msg.message if hasattr(original_msg, "message") else ""
                                
                        except Exception as e:
                            self.logger.warning(f"Could not fetch replied-to message {reply_to_msg_id}: {str(e)}")
                    
                    # Extract message data as before
                    message_data = {
                        "id": msg.id,
                        "channel_id": entity.id,
                        "channel_title": channel_info.get("title"),
                        "channel_username": channel_info.get("username"),
                        "channel_description": channel_info.get("description"),
                        "date": msg_date.isoformat(),
                        "text": msg.message if hasattr(msg, "message") else "",
                        "media_path": media_path,
                        "media_type": media_type,
                        "views": msg.views if hasattr(msg, "views") else None,
                        "forwards": msg.forwards if hasattr(msg, "forwards") else None,
                        # Add reply information
                        "reply_to_msg_id": reply_to_msg_id,
                        "reply_to_msg_text": reply_to_msg_text
                    }
                                    
                    channel_messages.append(message_data)
                    message_count += 1
                
                # Add all messages from this channel to the main collection
                all_messages.extend(channel_messages)
                
                self.logger.info(f"Added {message_count} messages from {username} after filtering")
                
            except Exception as e:
                self.logger.error(f"Error retrieving messages from {username}: {str(e)}")
        
        # Sort messages by date
        all_messages.sort(key=lambda x: x["date"])
        self.logger.info(f"Total messages collected from all channels: {len(all_messages)}")
        return all_messages
    
    def save_messages_to_json(self, messages: List[Dict[str, Any]], filepath: str):
        """
        Save collected messages to a JSON file.
        
        Args:
            messages: List of message dictionaries
            filepath: Path to save the JSON file
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        self.logger.info(f"Saved {len(messages)} messages to {filepath}")


async def main():
    """Example usage of the TelegramCollector."""
    # Replace with your API credentials
    api_id = "YOUR_API_ID"
    api_hash = "YOUR_API_HASH"
    
    collector = TelegramCollector(api_id, api_hash)
    await collector.start()
    
    channels = ["channel1", "channel2", "channel3"]
    messages = await collector.get_new_messages(channels, limit=50, since_hours=24)
    
    collector.save_messages_to_json(messages, "collected_messages.json")
    await collector.stop()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())