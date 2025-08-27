#!/usr/bin/env python3
"""
Database manager for Roombot with MySQL support.
"""

import logging
from typing import Optional, Dict, Any, List

import mysql.connector
from mysql.connector import Error

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, host: str, database: str, user: str, password: str, port: int = 3306):
        self.host = host
        self.database = database
        self.user = user
        self.password = password
        self.port = port
        self.connection = None
        self.connect()

    def connect(self):
        """Establish database connection."""
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                database=self.database,
                user=self.user,
                password=self.password,
                port=self.port,
                autocommit=True
            )
            if self.connection.is_connected():
                logger.info("Successfully connected to MySQL database")
        except Error as e:
            logger.error(f"Error connecting to MySQL: {e}")
            raise

    def disconnect(self):
        """Close database connection."""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            logger.info("MySQL connection is closed")

    def execute_query(self, query: str, params: tuple = None) -> Optional[List[tuple]]:
        """Execute a SELECT query and return results."""
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params or ())
            result = cursor.fetchall()
            cursor.close()
            return result
        except Error as e:
            logger.error(f"Error executing query: {e}")
            return None

    def execute_update(self, query: str, params: tuple = None) -> bool:
        """Execute an INSERT, UPDATE, or DELETE query."""
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params or ())
            cursor.close()
            return True
        except Error as e:
            logger.error(f"Error executing update: {e}")
            return False

    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user by Telegram ID."""
        query = """
        SELECT id, Username, TelegramID, InvitedBy, InviteID, Points, 
               TwitterAccount, ActivityScore, created_at, updated_at
        FROM users WHERE TelegramID = %s
        """
        result = self.execute_query(query, (telegram_id,))

        if result:
            user_data = result[0]
            return {
                'id': user_data[0],
                'username': user_data[1],
                'telegram_id': user_data[2],
                'invited_by': user_data[3],
                'invite_id': user_data[4],
                'points': user_data[5],
                'twitter_account': user_data[6],
                'activity_score': user_data[7],
                'created_at': user_data[8],
                'updated_at': user_data[9]
            }
        return None

    def create_user(self, telegram_id: int, username: str, invited_by: str = None,
                    invite_id: int = None, twitter_account: str = None) -> bool:
        """Create a new user."""
        query = """
        INSERT INTO users (TelegramID, Username, InvitedBy, InviteID, TwitterAccount)
        VALUES (%s, %s, %s, %s, %s)
        """
        return self.execute_update(query, (telegram_id, username, invited_by, invite_id, twitter_account))

    def update_user_points(self, telegram_id: int, points: int) -> bool:
        """Update user points."""
        query = "UPDATE users SET Points = %s WHERE TelegramID = %s"
        return self.execute_update(query, (points, telegram_id))

    def update_user_activity(self, telegram_id: int, activity_score: int) -> bool:
        """Update user activity score."""
        query = "UPDATE users SET ActivityScore = %s WHERE TelegramID = %s"
        return self.execute_update(query, (activity_score, telegram_id))

    def update_user(self, telegram_id: int, **kwargs) -> bool:
        """Update user with dynamic fields."""
        if not kwargs:
            return False

        set_clause = ", ".join(f"{key} = %s" for key in kwargs.keys())
        query = f"UPDATE users SET {set_clause} WHERE TelegramID = %s"
        params = tuple(kwargs.values()) + (telegram_id,)

        return self.execute_update(query, params)

    def get_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top users by points."""
        query = """
        SELECT Username, TelegramID, Points, ActivityScore
        FROM users 
        ORDER BY Points DESC, ActivityScore DESC 
        LIMIT %s
        """
        result = self.execute_query(query, (limit,))

        if result:
            return [
                {
                    'username': row[0],
                    'telegram_id': row[1],
                    'points': row[2],
                    'activity_score': row[3]
                }
                for row in result
            ]
        return []

    def get_user_count(self) -> int:
        """Get total number of users."""
        query = "SELECT COUNT(*) FROM users"
        result = self.execute_query(query)
        return result[0][0] if result else 0

    def get_users_by_inviter(self, inviter_username: str) -> List[Dict[str, Any]]:
        """Get all users invited by a specific inviter."""
        query = """
        SELECT Username, TelegramID, Points, ActivityScore, created_at
        FROM users 
        WHERE InvitedBy = %s
        ORDER BY created_at DESC
        """
        result = self.execute_query(query, (inviter_username,))

        if result:
            return [
                {
                    'username': row[0],
                    'telegram_id': row[1],
                    'points': row[2],
                    'activity_score': row[3],
                    'created_at': row[4]
                }
                for row in result
            ]
        return []

    def delete_user(self, telegram_id: int) -> bool:
        """Delete a user by Telegram ID."""
        query = "DELETE FROM users WHERE TelegramID = %s"
        return self.execute_update(query, (telegram_id,))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()