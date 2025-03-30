import asyncio
import logging
import os
import json
from datetime import datetime, timedelta
import schedule
import time
import threading
from typing import Dict, Any, List, Callable, Optional

class TaskScheduler:
    def __init__(self):
        """Initialize the task scheduler."""
        self.logger = logging.getLogger(__name__)
        self.tasks = {}
        self.running = False
        self.thread = None
        
        # Create schedules directory if it doesn't exist
        self.schedules_dir = os.path.join(os.getcwd(), "schedules")
        os.makedirs(self.schedules_dir, exist_ok=True)
    
    def add_task(self, task_id: str, task_func: Callable, interval: str, **kwargs):
        """
        Add a task to the scheduler.
        
        Args:
            task_id: Unique identifier for the task
            task_func: Function to execute
            interval: Schedule interval (e.g., "1h", "30m", "daily")
            **kwargs: Arguments to pass to the task function
        """
        self.tasks[task_id] = {
            "function": task_func,
            "interval": interval,
            "kwargs": kwargs,
            "last_run": None,
            "next_run": None
        }
        
        self.logger.info(f"Added task {task_id} with interval {interval}")
        
        # Schedule the task
        self._schedule_task(task_id)
        
        # Save task configuration
        self._save_task_config(task_id)
    
    def remove_task(self, task_id: str):
        """
        Remove a task from the scheduler.
        
        Args:
            task_id: Task identifier
        """
        if task_id in self.tasks:
            schedule.clear(task_id)
            del self.tasks[task_id]
            self.logger.info(f"Removed task {task_id}")
            
            # Remove task configuration file
            config_path = os.path.join(self.schedules_dir, f"{task_id}.json")
            if os.path.exists(config_path):
                os.remove(config_path)
    
    def _schedule_task(self, task_id: str):
        """
        Schedule a task based on its interval.
        
        Args:
            task_id: Task identifier
        """
        if task_id not in self.tasks:
            return
            
        task = self.tasks[task_id]
        interval = task["interval"]
        
        # Create a wrapper function to update task execution times
        def task_wrapper():
            try:
                # Update last run time
                self.tasks[task_id]["last_run"] = datetime.now().isoformat()
                
                # Execute the task function with kwargs
                task["function"](**task["kwargs"])
                
                # Update next run time based on current schedule
                self._update_next_run_time(task_id)
                
                # Save updated task configuration
                self._save_task_config(task_id)
                
                self.logger.info(f"Task {task_id} executed successfully")
                
            except Exception as e:
                self.logger.error(f"Error executing task {task_id}: {str(e)}")
        
        # Schedule based on interval format
        if interval.endswith('m'):
            minutes = int(interval[:-1])
            schedule.every(minutes).minutes.do(task_wrapper).tag(task_id)
            next_run = datetime.now() + timedelta(minutes=minutes)
        elif interval.endswith('h'):
            hours = int(interval[:-1])
            schedule.every(hours).hours.do(task_wrapper).tag(task_id)
            next_run = datetime.now() + timedelta(hours=hours)
        elif interval == 'daily':
            schedule.every().day.at("00:00").do(task_wrapper).tag(task_id)
            next_run = datetime.now().replace(hour=0, minute=0, second=0) + timedelta(days=1)
        elif interval == 'hourly':
            schedule.every().hour.do(task_wrapper).tag(task_id)
            next_run = datetime.now().replace(minute=0, second=0) + timedelta(hours=1)
        else:
            self.logger.error(f"Invalid interval format for task {task_id}: {interval}")
            return
            
        # Set next run time
        self.tasks[task_id]["next_run"] = next_run.isoformat()
        
    def _update_next_run_time(self, task_id: str):
        """
        Update the next run time for a task.
        
        Args:
            task_id: Task identifier
        """
        if task_id not in self.tasks:
            return
            
        for job in schedule.get_jobs():
            if task_id in job.tags:
                next_run = job.next_run
                if next_run:
                    self.tasks[task_id]["next_run"] = next_run.isoformat()
                break
    
    def _save_task_config(self, task_id: str):
        """
        Save task configuration to file.
        
        Args:
            task_id: Task identifier
        """
        if task_id not in self.tasks:
            return
            
        task = self.tasks[task_id]
        
        # Create a serializable configuration
        config = {
            "interval": task["interval"],
            "kwargs": task["kwargs"],
            "last_run": task["last_run"],
            "next_run": task["next_run"]
        }
        
        # Save to file
        config_path = os.path.join(self.schedules_dir, f"{task_id}.json")
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    
    def _load_task_configs(self):
        """Load task configurations from files."""
        try:
            config_files = [f for f in os.listdir(self.schedules_dir) if f.endswith('.json')]
            
            for config_file in config_files:
                task_id = config_file.replace('.json', '')
                
                # Skip if task already exists
                if task_id in self.tasks:
                    continue
                    
                config_path = os.path.join(self.schedules_dir, config_file)
                
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                self.logger.info(f"Loaded task configuration for {task_id}")
                
        except Exception as e:
            self.logger.error(f"Error loading task configurations: {str(e)}")
    
    def start(self):
        """Start the scheduler in a separate thread."""
        if self.running:
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._run_scheduler)
        self.thread.daemon = True
        self.thread.start()
        
        self.logger.info("Scheduler started")
    
    def stop(self):
        """Stop the scheduler."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None
            
        self.logger.info("Scheduler stopped")
    
    def _run_scheduler(self):
        """Run the scheduler loop."""
        while self.running:
            schedule.run_pending()
            time.sleep(1)
    
    def get_task_status(self, task_id: str = None) -> Dict[str, Any]:
        """
        Get the status of tasks.
        
        Args:
            task_id: Optional task identifier, if None returns all tasks
            
        Returns:
            Dictionary with task status information
        """
        if task_id and task_id in self.tasks:
            task = self.tasks[task_id]
            return {
                "task_id": task_id,
                "interval": task["interval"],
                "last_run": task["last_run"],
                "next_run": task["next_run"]
            }
        elif task_id:
            return {"error": f"Task {task_id} not found"}
        else:
            result = {}
            for tid, task in self.tasks.items():
                result[tid] = {
                    "interval": task["interval"],
                    "last_run": task["last_run"],
                    "next_run": task["next_run"]
                }
            return result


def sample_task(name: str = "Task"):
    """Sample task function for testing."""
    print(f"{name} executed at {datetime.now().isoformat()}")


def main():
    """Example usage of the TaskScheduler."""
    # Initialize scheduler
    scheduler = TaskScheduler()
    
    # Add tasks
    scheduler.add_task("task1", sample_task, "5m", name="Five Minute Task")
    scheduler.add_task("task2", sample_task, "1h", name="Hourly Task")
    
    # Start scheduler
    scheduler.start()
    
    try:
        # Check task status after a minute
        time.sleep(60)
        status = scheduler.get_task_status()
        print("Task status:")
        print(json.dumps(status, indent=2))
        
        # Keep running for demo
        print("Scheduler running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        # Stop scheduler
        scheduler.stop()
        print("Scheduler stopped.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()