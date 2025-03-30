import os
import json
import logging
from typing import Dict, Any, List, Optional

class ConfigManager:
    def __init__(self, config_file: str = "config.json"):
        """
        Initialize the configuration manager.
        
        Args:
            config_file: Path to the configuration file
        """
        self.config_file = config_file
        self.logger = logging.getLogger(__name__)
        self.config = self._load_config()
        
    def _load_config(self) -> Dict[str, Any]:
        """
        Load configuration from file.
        
        Returns:
            Configuration dictionary
        """
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                # Create default configuration
                default_config = self._create_default_config()
                self._save_config(default_config)
                return default_config
                
        except Exception as e:
            self.logger.error(f"Error loading configuration: {str(e)}")
            return self._create_default_config()
    
    def _create_default_config(self) -> Dict[str, Any]:
        """
        Create default configuration.
        
        Returns:
            Default configuration dictionary
        """
        return {
            "telegram": {
                "api_id": "",
                "api_hash": "",
                "bot_token": "",
                "channels": [],
                "subscribers": []
            },
            "llm": {
                "api_key": "",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4-vision-preview",
                "max_tokens": 1000
            },
            "scheduler": {
                "collection_interval": "1h",
                "analysis_interval": "3h",
                "cleanup_interval": "24h"  # Add cleanup interval
            },
            # Add cleanup configuration
            "cleanup": {
                "folders": {
                    "media": {"max_age_days": 7, "keep_latest": 100},
                    "logs": {"max_age_days": 30, "keep_latest": 10},
                    "data": {"max_age_days": 14, "keep_latest": 20},
                    "analysis": {"max_age_days": 30, "keep_latest": 50}
                }
            },
            "channel_descriptions": {},
            "analysis_prompts": {
                "default": "Analyze the following messages from various Telegram channels. Provide a concise summary highlighting key information, trends, and insights. Include the most important points from each channel, considering their context and focus.",
                "tech_news": "Analyze these technology news updates. Focus on emerging trends, significant product launches, and important developments in the tech industry. Highlight potential impacts on the market and consumers.",
                "finance": "Analyze these financial updates. Identify key market movements, important economic indicators, and significant company announcements. Provide context on how these developments might affect investors."
            },
        }
        
    def _save_config(self, config: Dict[str, Any] = None):
        """
        Save configuration to file.
        
        Args:
            config: Configuration dictionary to save (uses self.config if None)
        """
        try:
            config_to_save = config if config is not None else self.config
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, ensure_ascii=False, indent=2)
                
            self.logger.info(f"Configuration saved to {self.config_file}")
            
        except Exception as e:
            self.logger.error(f"Error saving configuration: {str(e)}")
    
    def get_config(self, section: str = None, key: str = None) -> Any:
        """
        Get configuration value.
        
        Args:
            section: Configuration section (optional)
            key: Configuration key within section (optional)
            
        Returns:
            Configuration value, section, or entire config
        """
        if section is None:
            return self.config
        
        if section not in self.config:
            return None
            
        if key is None:
            return self.config[section]
            
        return self.config[section].get(key)
    
    def set_config(self, section: str, key: str, value: Any) -> bool:
        """
        Set configuration value.
        
        Args:
            section: Configuration section
            key: Configuration key within section
            value: Value to set
            
        Returns:
            Success flag
        """
        try:
            if section not in self.config:
                self.config[section] = {}
                
            self.config[section][key] = value
            self._save_config()
            return True
            
        except Exception as e:
            self.logger.error(f"Error setting configuration {section}.{key}: {str(e)}")
            return False
    
    def add_channel(self, channel: str, description: str = None) -> bool:
        """
        Add a channel to the configuration.
        
        Args:
            channel: Channel username or ID
            description: Optional channel description
            
        Returns:
            Success flag
        """
        try:
            channels = self.config["telegram"]["channels"]
            
            if channel not in channels:
                channels.append(channel)
                
            if description and channel not in self.config.get("channel_descriptions", {}):
                if "channel_descriptions" not in self.config:
                    self.config["channel_descriptions"] = {}
                    
                self.config["channel_descriptions"][channel] = description
                
            self._save_config()
            return True
            
        except Exception as e:
            self.logger.error(f"Error adding channel {channel}: {str(e)}")
            return False
    
    def remove_channel(self, channel: str) -> bool:
        """
        Remove a channel from the configuration.
        
        Args:
            channel: Channel username or ID
            
        Returns:
            Success flag
        """
        try:
            channels = self.config["telegram"]["channels"]
            
            if channel in channels:
                channels.remove(channel)
                
            if "channel_descriptions" in self.config and channel in self.config["channel_descriptions"]:
                del self.config["channel_descriptions"][channel]
                
            self._save_config()
            return True
            
        except Exception as e:
            self.logger.error(f"Error removing channel {channel}: {str(e)}")
            return False
    
    def add_subscriber(self, user_id: str) -> bool:
        """
        Add a subscriber to the configuration.
        
        Args:
            user_id: User ID to add
            
        Returns:
            Success flag
        """
        try:
            subscribers = self.config["telegram"]["subscribers"]
            
            if user_id not in subscribers:
                subscribers.append(user_id)
                self._save_config()
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error adding subscriber {user_id}: {str(e)}")
            return False
    
    def remove_subscriber(self, user_id: str) -> bool:
        """
        Remove a subscriber from the configuration.
        
        Args:
            user_id: User ID to remove
            
        Returns:
            Success flag
        """
        try:
            subscribers = self.config["telegram"]["subscribers"]
            
            if user_id in subscribers:
                subscribers.remove(user_id)
                self._save_config()
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error removing subscriber {user_id}: {str(e)}")
            return False
    
    def get_channels(self) -> List[str]:
        """
        Get list of configured channels.
        
        Returns:
            List of channel usernames/IDs
        """
        return self.config.get("telegram", {}).get("channels", [])
    
    def get_subscribers(self) -> List[str]:
        """
        Get list of subscribers.
        
        Returns:
            List of user IDs
        """
        return self.config.get("telegram", {}).get("subscribers", [])
    
    def get_channel_descriptions(self) -> Dict[str, str]:
        """
        Get channel descriptions.
        
        Returns:
            Dictionary mapping channels to descriptions
        """
        return self.config.get("channel_descriptions", {})
    
    def get_analysis_prompt(self, prompt_type: str = "default") -> str:
        """
        Get analysis prompt by type.
        
        Args:
            prompt_type: Prompt type
            
        Returns:
            Prompt string
        """
        prompts = self.config.get("analysis_prompts", {})
        return prompts.get(prompt_type, prompts.get("default", ""))
    
    def set_analysis_prompt(self, prompt_type: str, prompt: str) -> bool:
        """
        Set analysis prompt.
        
        Args:
            prompt_type: Prompt type
            prompt: Prompt string
            
        Returns:
            Success flag
        """
        try:
            if "analysis_prompts" not in self.config:
                self.config["analysis_prompts"] = {}
                
            self.config["analysis_prompts"][prompt_type] = prompt
            self._save_config()
            return True
            
        except Exception as e:
            self.logger.error(f"Error setting analysis prompt {prompt_type}: {str(e)}")
            return False


def main():
    """Example usage of the ConfigManager."""
    # Initialize config manager
    config_manager = ConfigManager()
    
    # Set configuration values
    config_manager.set_config("telegram", "api_id", "YOUR_API_ID")
    config_manager.set_config("telegram", "api_hash", "YOUR_API_HASH")
    config_manager.set_config("telegram", "bot_token", "YOUR_BOT_TOKEN")
    
    # Add channels with descriptions
    config_manager.add_channel("techcrunch", "Technology news and startup updates")
    config_manager.add_channel("financenews", "Financial market analysis and updates")
    config_manager.add_channel("worldevents", "Global news and current events")
    
    # Add subscribers
    config_manager.add_subscriber("USER_ID_1")
    config_manager.add_subscriber("USER_ID_2")
    
    # Set a custom analysis prompt
    custom_prompt = (
        "Analyze these messages with a focus on identifying key trends and patterns. "
        "Highlight important information that would be valuable for users interested in "
        "staying informed about developments in technology, finance, and global events."
    )
    config_manager.set_analysis_prompt("custom", custom_prompt)
    
    # Display current configuration
    full_config = config_manager.get_config()
    print("Current configuration:")
    print(json.dumps(full_config, indent=2))
    
    # Get specific configuration values
    api_key = config_manager.get_config("llm", "api_key")
    channels = config_manager.get_channels()
    channel_descriptions = config_manager.get_channel_descriptions()
    
    print(f"\nConfigured channels: {channels}")
    print(f"Channel descriptions: {channel_descriptions}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()