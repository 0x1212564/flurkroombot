#!/usr/bin/env python3
"""
Configuration settings for Roombot.
"""

import os
from typing import Dict, Any


class Config:
    """Configuration class for bot settings."""

    # Bot configuration
    BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token_here")

    # Database configuration
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
    DB_NAME = os.getenv("DB_NAME", "Roombot")

    # Timing constants (seconds)
    INVITE_COOLDOWN = 600  # 10 minutes between invites
    VERIFICATION_TIMEOUT = 300  # 5 minutes to verify
    WAGER_EXPIRY = 60  # 1 minute to accept wagers
    BLACKLIST_DURATION = 86400  # 24 hours
    DAILY_BONUS_COOLDOWN = 86400  # 24 hours for daily bonus
    MESSAGE_COOLDOWN = 30  # Seconds between XP-earning messages

    # Points and XP system
    INVITE_BASE_POINTS = 10  # Points for successful invite
    ACTIVITY_XP_MESSAGE = 1  # XP per message
    ACTIVITY_XP_DAILY = 50  # XP for daily bonus
    LEVEL_XP_REQUIRED = 100  # Base XP required per level
    WAGER_XP_MULTIPLIER = 0.1  # XP = wager_points * loveliness * this

    # Activity tracking
    ACTIVITY_DECAY_DAYS = 7  # Days before activity score starts decaying
    HEAT_DECAY_HOURS = 24  # Hours before heat score decays

    # Viral mechanics
    STREAK_BONUS_MULTIPLIER = 0.1  # 10% bonus per day of streak
    MILESTONE_ANNOUNCES = [10, 25, 50, 100, 250, 500, 1000]  # Announce these milestones

    # Logging configuration
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    @classmethod
    def get_db_config(cls) -> Dict[str, Any]:
        """Get database configuration as dictionary."""
        return {
            "host": cls.DB_HOST,
            "port": cls.DB_PORT,
            "user": cls.DB_USER,
            "password": cls.DB_PASSWORD,
            "database": cls.DB_NAME
        }

    @classmethod
    def validate_config(cls) -> bool:
        """Validate that required configuration is present."""
        required_vars = ["BOT_TOKEN", "DB_HOST", "DB_USER", "DB_PASSWORD"]
        missing = []

        for var in required_vars:
            if not getattr(cls, var) or getattr(cls, var) == f"your_{var.lower()}_here":
                missing.append(var)

        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")

        return True