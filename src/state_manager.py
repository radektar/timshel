"""State management for Timshel."""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from src.config import config
from src.logger import logger


def reset_state(target_date: Optional[datetime] = None) -> bool:
    """Reset transcription state to a specific date.
    
    Creates or updates the state file with a new last_sync timestamp.
    If target_date is None, defaults to 7 days ago.
    
    Args:
        target_date: Date to set as last_sync (defaults to 7 days ago)
        
    Returns:
        True if reset succeeded, False otherwise
    """
    try:
        # Default to 7 days ago if no date provided
        if target_date is None:
            target_date = datetime.now() - timedelta(days=7)
        
        # Ensure target_date is timezone-naive datetime
        if target_date.tzinfo is not None:
            target_date = target_date.replace(tzinfo=None)
        
        # Create backup if state file exists
        if config.STATE_FILE.exists():
            backup_file = Path(str(config.STATE_FILE) + ".backup")
            try:
                import shutil
                shutil.copy2(config.STATE_FILE, backup_file)
                logger.info(f"✓ Backup created: {backup_file}")
            except Exception as e:
                logger.warning(f"Could not create backup: {e}")
        
        # Write new state
        state_data = {
            "last_sync": target_date.isoformat()
        }
        
        # Ensure directory exists
        config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config.STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state_data, f, indent=2)
        
        logger.info(
            f"✓ State reset successful: last_sync = {target_date.isoformat()}"
        )
        return True
        
    except Exception as e:
        logger.error(f"Failed to reset state: {e}", exc_info=True)
        return False


def get_last_sync_time() -> datetime:
    """Get timestamp of last synchronization.
    
    Returns:
        Datetime of last sync, or 7 days ago if no state file exists
    """
    if config.STATE_FILE.exists():
        try:
            with open(config.STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                last_sync_str = data.get("last_sync")
                if last_sync_str:
                    last_sync = datetime.fromisoformat(last_sync_str)
                    logger.debug(f"Last sync: {last_sync}")
                    return last_sync
        except Exception as e:
            logger.error(f"Error reading state file: {e}")
    
    # Default: 7 days ago
    default_time = datetime.now() - timedelta(days=7)
    logger.info(f"No previous sync found, using default: {default_time}")
    return default_time


def save_sync_time() -> None:
    """Save current time as last sync timestamp."""
    try:
        current_time = datetime.now()
        # Ensure directory exists
        config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config.STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({"last_sync": current_time.isoformat()}, f, indent=2)
        logger.debug(f"Saved sync time: {current_time}")
    except Exception as e:
        logger.error(f"Error saving state file: {e}")

