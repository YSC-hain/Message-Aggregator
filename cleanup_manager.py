import os
import logging
import shutil
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

class CleanupManager:
    def __init__(self, base_dir: str = None):
        """
        Initialize the cleanup manager.
        
        Args:
            base_dir: Base directory for the application (optional)
        """
        self.base_dir = base_dir or os.getcwd()
        self.logger = logging.getLogger(__name__)
        
    def cleanup_folder(self, folder_name: str, max_age_days: int = 7, keep_latest: int = 10) -> Dict[str, Any]:
        """
        Clean up files in a folder based on age and count.
        
        Args:
            folder_name: Name of the folder to clean
            max_age_days: Maximum age of files to keep (in days)
            keep_latest: Minimum number of latest files to keep regardless of age
            
        Returns:
            Dictionary with cleanup statistics
        """
        folder_path = os.path.join(self.base_dir, folder_name)
        if not os.path.exists(folder_path):
            self.logger.warning(f"Folder {folder_path} does not exist, skipping cleanup")
            return {"status": "skipped", "reason": "folder_not_found"}
            
        self.logger.info(f"Starting cleanup of {folder_path}")
        
        # Get all files with their modification times
        files = []
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if os.path.isfile(file_path):
                mod_time = os.path.getmtime(file_path)
                files.append((file_path, mod_time))
        
        # Sort files by modification time (newest first)
        files.sort(key=lambda x: x[1], reverse=True)
        
        # Keep the latest N files
        protected_files = files[:keep_latest] if keep_latest > 0 else []
        protected_paths = [f[0] for f in protected_files]
        
        # Calculate the cutoff date
        cutoff_date = datetime.now() - timedelta(days=max_age_days)
        cutoff_timestamp = cutoff_date.timestamp()
        
        # Delete old files
        deleted_count = 0
        deleted_size = 0
        
        for file_path, mod_time in files:
            # Skip if file is in protected list
            if file_path in protected_paths:
                continue
                
            # Delete if older than cutoff date
            if mod_time < cutoff_timestamp:
                try:
                    file_size = os.path.getsize(file_path)
                    os.remove(file_path)
                    deleted_count += 1
                    deleted_size += file_size
                    self.logger.debug(f"Deleted old file: {file_path}")
                except Exception as e:
                    self.logger.error(f"Error deleting file {file_path}: {str(e)}")
        
        # Format the deleted size
        deleted_size_mb = deleted_size / (1024 * 1024)
        
        self.logger.info(f"Cleanup completed for {folder_path}: {deleted_count} files deleted ({deleted_size_mb:.2f} MB)")
        
        return {
            "status": "completed",
            "folder": folder_path,
            "deleted_count": deleted_count,
            "deleted_size_mb": deleted_size_mb,
            "timestamp": datetime.now().isoformat()
        }
    
    def cleanup_all(self, folder_configs: Dict[str, Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Clean up multiple folders based on configuration.
        
        Args:
            folder_configs: Dictionary mapping folder names to cleanup configurations
            
        Returns:
            Dictionary with cleanup results for all folders
        """
        if folder_configs is None:
            # Default configuration for common folders
            folder_configs = {
                "media": {"max_age_days": 7, "keep_latest": 100},
                "logs": {"max_age_days": 30, "keep_latest": 10},
                "data": {"max_age_days": 14, "keep_latest": 20},
                "analysis": {"max_age_days": 30, "keep_latest": 50}
            }
        
        results = {}
        for folder, config in folder_configs.items():
            results[folder] = self.cleanup_folder(
                folder_name=folder,
                max_age_days=config.get("max_age_days", 7),
                keep_latest=config.get("keep_latest", 10)
            )
        
        return results