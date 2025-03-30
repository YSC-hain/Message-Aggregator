import asyncio
import logging
import os
import json
from datetime import datetime
import argparse
# from typing import Dict, Any, List, Optional

# Import modules
from config_manager import ConfigManager
from telegram_collector import TelegramCollector
from llm_analyzer import LLMAnalyzer
from telegram_bot import TelegramBot
from scheduler import TaskScheduler

class Application:
    def __init__(self, config_file: str = "config.json"):
        """
        Initialize the application.
        
        Args:
            config_file: Path to configuration file
        """
        # Set up logging
        self._setup_logging()
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing application")
        
        # Initialize configuration manager
        self.config_manager = ConfigManager(config_file)
        
        # Initialize components
        self._init_components()
        
        # Initialize scheduler
        self.scheduler = TaskScheduler()
    
    def _setup_logging(self):
        """Set up logging configuration."""
        # Create logs directory if it doesn't exist
        logs_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        
        # Configure logging
        log_file = os.path.join(logs_dir, f"app_{datetime.now().strftime('%Y%m%d')}.log")
        
        # Set Telethon to a higher log level to reduce verbosity
        logging.getLogger('telethon').setLevel(logging.WARNING)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
    
    def _init_components(self):
        """Initialize application components."""
        try:
            # Get configuration values
            telegram_config = self.config_manager.get_config("telegram")
            llm_config = self.config_manager.get_config("llm")
            
            # Initialize Telegram collector
            user_config = telegram_config.get("user", {})
            self.collector = TelegramCollector(
                api_id=user_config.get("api_id"),
                api_hash=user_config.get("api_hash")
            )
            
            # Initialize LLM analyzer
            self.analyzer = LLMAnalyzer(
                api_key=llm_config.get("api_key"),
                base_url=llm_config.get("base_url"),
                model=llm_config.get("model"),
                max_tokens=llm_config.get("max_tokens")
            )
            
            # Initialize Telegram bot
            bot_config = telegram_config.get("bot", {})
            self.bot = TelegramBot(bot_config.get("token"))
            
            self.logger.info("All components initialized")
            
        except Exception as e:
            self.logger.error(f"Error initializing components: {str(e)}")
            raise
    
    async def collect_and_analyze(self):
        """Collect and analyze messages from Telegram channels."""
        try:
            # Get channels
            channels = self.config_manager.get_channels()
            if not channels:
                self.logger.warning("No channels configured")
                return
                
            # Get channel descriptions
            channel_descriptions = self.config_manager.get_channel_descriptions()
                
            # Start collector
            await self.collector.start()

            # Verify channel access
            accessible_channels = await self.collector.verify_channels(channels)
            if not accessible_channels:
                self.logger.warning("No channels are accessible")
                await self.collector.stop()
                return
            
            # Collect messages
            self.logger.info(f"Collecting messages from {len(channels)} channels")
            messages = await self.collector.get_new_messages_without_duplication(
                channel_usernames=channels,
                limit=80
            )
            
            # Stop collector
            await self.collector.stop()
            
            # Save collected messages
            output_dir = os.path.join(os.getcwd(), "data")
            os.makedirs(output_dir, exist_ok=True)
            output_file = os.path.join(output_dir, f"messages_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            self.collector.save_messages_to_json(messages, output_file)
            
            if not messages:
                self.logger.info("No new messages collected")
                return
                
            # Analyze messages
            self.logger.info(f"Analyzing {len(messages)} messages")
            analysis_prompt = self.config_manager.get_analysis_prompt()
            analysis = self.analyzer.analyze_messages(
                messages=messages,
                channel_descriptions=channel_descriptions,
                # analysis_prompt=analysis_prompt TODO
            )
            
            if "error" in analysis:
                self.logger.error(f"Analysis error: {analysis['error']}")
                return
                
            # Add source information
            channel_stats = {}
            for msg in messages:
                channel_id = msg.get("channel_id")
                channel_title = msg.get("channel_title")
                
                if channel_id not in channel_stats:
                    channel_stats[channel_id] = {
                        "channel_id": channel_id,
                        "channel_name": channel_title,
                        "message_count": 0
                    }
                    
                channel_stats[channel_id]["message_count"] += 1
                
            analysis["sources"] = list(channel_stats.values())
            
            # Save analysis
            analysis_dir = os.path.join(os.getcwd(), "analysis")
            os.makedirs(analysis_dir, exist_ok=True)
            analysis_file = os.path.join(analysis_dir, f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            
            with open(analysis_file, 'w', encoding='utf-8') as f:
                json.dump(analysis, f, ensure_ascii=False, indent=2)
                
            self.logger.info(f"Analysis saved to {analysis_file}")
            
            # Distribute analysis to subscribers
            subscribers = self.config_manager.get_subscribers()
            if subscribers:
                self.logger.info(f"Sending analysis to {len(subscribers)} subscribers")
                await self.bot.send_analysis_to_users(analysis, subscribers)
            
        except Exception as e:
            self.logger.error(f"Error in collect_and_analyze: {str(e)}")
    
    def schedule_tasks(self):
        """Schedule regular tasks."""
        try:
            # Get scheduler configuration
            scheduler_config = self.config_manager.get_config("scheduler")
            collection_interval = scheduler_config.get("collection_interval", "12h")
            cleanup_interval = scheduler_config.get("cleanup_interval", "48h")
            
            # Schedule collection and analysis task
            self.scheduler.add_task(
                task_id="collect_and_analyze",
                task_func=self._run_collect_and_analyze,
                interval=collection_interval
            )
            
            # Schedule cleanup task
            self.scheduler.add_task(
                task_id="cleanup_files",
                task_func=self._run_cleanup,
                interval=cleanup_interval
            )
            
            self.logger.info(f"Scheduled collection and analysis task with interval {collection_interval}")
            self.logger.info(f"Scheduled cleanup task with interval {cleanup_interval}")
            
        except Exception as e:
            self.logger.error(f"Error scheduling tasks: {str(e)}")
    
    def _run_collect_and_analyze(self):
        """Run the collect_and_analyze coroutine."""
        asyncio.run(self.collect_and_analyze())
    
    async def start(self):
        """Start the application."""
        try:
            # Start the bot
            self.logger.info("Starting Telegram bot")
            await self.bot.start_polling()
            
            # Schedule tasks
            self.logger.info("Scheduling tasks")
            self.schedule_tasks()
            
            # Start the scheduler
            self.logger.info("Starting scheduler")
            self.scheduler.start()
            
            self.logger.info("Application started")
            
        except Exception as e:
            self.logger.error(f"Error starting application: {str(e)}")
            raise
    
    async def stop(self):
        """Stop the application."""
        try:
            # Stop the scheduler
            self.logger.info("Stopping scheduler")
            self.scheduler.stop()
            
            # Stop the bot
            self.logger.info("Stopping Telegram bot")
            await self.bot.stop()
            
            self.logger.info("Application stopped")
            
        except Exception as e:
            self.logger.error(f"Error stopping application: {str(e)}")
    
    def _run_cleanup(self):
        """Run the cleanup operation."""
        try:
            from cleanup_manager import CleanupManager
            
            self.logger.info("Starting scheduled cleanup operation")
            cleanup_manager = CleanupManager()
            
            # Get cleanup configuration from config
            cleanup_config = self.config_manager.get_config("cleanup", {})
            folder_configs = cleanup_config.get("folders", {})
            
            # Run cleanup
            results = cleanup_manager.cleanup_all(folder_configs)
            
            self.logger.info(f"Cleanup completed: {results}")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup operation: {str(e)}")


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Telegram Channel Aggregator and LLM Analysis Tool")
    parser.add_argument("--config", default="config.json", help="Path to configuration file")
    parser.add_argument("--setup", action="store_true", help="Run setup mode")
    parser.add_argument("--collect", action="store_true", help="Run a single collection and analysis")
    args = parser.parse_args()
    
    app = Application(config_file=args.config)
    
    if args.setup:
        # Set up the application interactively
        print("Setting up the application...")
        
        # Telegram configuration
        api_id = input("Enter Telegram API ID: ")
        api_hash = input("Enter Telegram API Hash: ")
        bot_token = input("Enter Telegram Bot Token: ")
        
        app.config_manager.set_config("telegram", "api_id", api_id)
        app.config_manager.set_config("telegram", "api_hash", api_hash)
        app.config_manager.set_config("telegram", "bot_token", bot_token)
        
        # LLM configuration
        api_key = input("Enter LLM API Key: ")
        base_url = input("Enter LLM API Base URL [https://api.openai.com/v1]: ")
        if not base_url:
            base_url = "https://api.openai.com/v1"
        
        app.config_manager.set_config("llm", "api_key", api_key)
        app.config_manager.set_config("llm", "base_url", base_url)
        
        # Add channels
        while True:
            channel = input("Enter channel username (or leave empty to stop): ")
            if not channel:
                break
                
            description = input("Enter channel description (optional): ")
            app.config_manager.add_channel(channel, description)
        
        print("Setup completed successfully!")
        
    elif args.collect:
        # Run a single collection and analysis
        print("Running collection and analysis...")
        await app.collect_and_analyze()
        print("Collection and analysis completed!")
        
    else:
        # Start the application normally
        print("Starting application...")
        await app.start()
        
        try:
            # Keep the application running
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("Stopping application...")
            await app.stop()
            print("Application stopped.")


if __name__ == "__main__":
    asyncio.run(main())