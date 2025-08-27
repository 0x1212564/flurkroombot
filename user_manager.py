#!/usr/bin/env python3
"""
User management logic for Roombot.
"""

import logging
import time
import hashlib
import random
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

from database import DatabaseManager
from config import Config

logger = logging.getLogger(__name__)


class UserManager:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.user_cache = {}  # Simple in-memory cache for session data
        self.verification_cache = {}  # Temporary verification data
        self.activity_cache = {}  # Activity tracking cache

    def get_or_create_user(self, telegram_id: int, username: str,
                           invited_by: str = None, invite_id: int = None) -> Dict[str, Any]:
        """Get existing user or create new one."""
        user = self.db.get_user(telegram_id)

        if not user:
            # Create new user
            success = self.db.create_user(
                telegram_id=telegram_id,
                username=username,
                invited_by=invited_by,
                invite_id=invite_id
            )

            if success:
                user = self.db.get_user(telegram_id)
                logger.info(f"Created new user: {username} ({telegram_id})")
            else:
                logger.error(f"Failed to create user: {username} ({telegram_id})")
                return None

        # Initialize session data if not in cache
        if telegram_id not in self.user_cache:
            self.user_cache[telegram_id] = {
                'level': 1,
                'xp': 0,
                'last_invite_time': 0,
                'last_message_xp': 0,
                'last_daily_bonus': 0,
                'blacklisted_until': 0,
                'verification_attempts': 0,
                'messages_sent': 0,
                'days_active': 0,
                'last_active': time.time(),
                'loveliness_score': 0.0,
                'heat_score': 0.0,
                'invite_streak': 0,
                'invites_sent': 0,
                'invites_successful': 0,
                'wagers_won': 0,
                'wagers_lost': 0,
                'total_points_earned': 0.0,
                'total_points_spent': 0.0,
                'milestones_reached': []
            }

        return {**user, **self.user_cache[telegram_id]}

    def update_user_points(self, telegram_id: int, points: int) -> bool:
        """Update user points in database."""
        success = self.db.update_user_points(telegram_id, points)
        if success:
            logger.info(f"Updated points for user {telegram_id}: {points}")
        return success

    def award_points(self, telegram_id: int, points: float, reason: str = "") -> bool:
        """Award points to user."""
        user = self.get_user_session_data(telegram_id)
        if not user:
            return False

        current_points = self.db.get_user(telegram_id)['points']
        new_points = current_points + points

        success = self.db.update_user_points(telegram_id, int(new_points))
        if success:
            user['total_points_earned'] += points
            logger.info(f"Awarded {points} points to {telegram_id} - {reason}")

        return success

    def update_activity_score(self, telegram_id: int, activity_score: int) -> bool:
        """Update user activity score."""
        success = self.db.update_user_activity(telegram_id, activity_score)
        if success:
            user_session = self.get_user_session_data(telegram_id)
            if user_session:
                user_session['last_active'] = time.time()
        return success

    def get_user_session_data(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user session data from cache."""
        return self.user_cache.get(telegram_id)

    def is_blacklisted(self, telegram_id: int) -> bool:
        """Check if user is blacklisted."""
        user_session = self.get_user_session_data(telegram_id)
        if user_session:
            return time.time() < user_session['blacklisted_until']
        return False

    def blacklist_user(self, telegram_id: int) -> None:
        """Blacklist user temporarily."""
        user_session = self.get_user_session_data(telegram_id)
        if user_session:
            user_session['blacklisted_until'] = time.time() + Config.BLACKLIST_DURATION

    def generate_invite_code(self, telegram_id: int) -> str:
        """Generate a unique invite code."""
        raw = f"{telegram_id}_{time.time()}_{random.randint(1000, 9999)}"
        code = hashlib.md5(raw.encode()).hexdigest()[:8].upper()
        return f"LOVE{code}"

    def calculate_level_xp(self, level: int) -> int:
        """Calculate XP required for a level."""
        return Config.LEVEL_XP_REQUIRED * level * (1 + level // 10)

    def calculate_loveliness_score(self, telegram_id: int) -> float:
        """Calculate user's loveliness score with gentle decay."""
        user_session = self.get_user_session_data(telegram_id)
        if not user_session:
            return 0.0

        last_active = user_session['last_active']
        days_inactive = (time.time() - last_active) / 86400

        # Base loveliness from engagement and presence
        base_score = user_session['messages_sent'] * 0.1 + user_session['days_active'] * 5

        # Gentle decay after ACTIVITY_DECAY_DAYS
        if days_inactive > Config.ACTIVITY_DECAY_DAYS:
            decay_factor = 0.95 ** (days_inactive - Config.ACTIVITY_DECAY_DAYS)
            base_score *= decay_factor

        return round(base_score, 2)

    def check_level_up(self, telegram_id: int) -> bool:
        """Check if user should level up."""
        user_session = self.get_user_session_data(telegram_id)
        if not user_session:
            return False

        current_level = user_session['level']
        current_xp = user_session['xp']
        required_xp = self.calculate_level_xp(current_level)

        if current_xp >= required_xp:
            user_session['level'] += 1
            user_session['xp'] -= required_xp
            return True
        return False

    def calculate_heat_score(self, telegram_id: int) -> float:
        """Calculate user's heat score (recent invite success rate)."""
        user_session = self.get_user_session_data(telegram_id)
        if not user_session:
            return 0.0

        # Heat based on recent successful invites
        last_success = user_session.get('last_invite_success', 0)
        hours_since = (time.time() - last_success) / 3600

        if hours_since > Config.HEAT_DECAY_HOURS:
            return 0.0

        # Base heat from successful invites in last 24h
        base_heat = user_session['invites_successful']

        # Decay factor
        decay = (Config.HEAT_DECAY_HOURS - hours_since) / Config.HEAT_DECAY_HOURS

        return round(base_heat * decay, 2)

    def track_activity(self, telegram_id: int) -> bool:
        """Track user activity for XP."""
        user_session = self.get_user_session_data(telegram_id)
        if not user_session:
            return False

        now = time.time()

        # Check if enough time passed for XP
        if now - user_session['last_message_xp'] >= Config.MESSAGE_COOLDOWN:
            user_session['xp'] += Config.ACTIVITY_XP_MESSAGE
            user_session['last_message_xp'] = now
            user_session['messages_sent'] += 1

            # Update daily active status
            today = datetime.now().date().isoformat()
            if telegram_id not in self.activity_cache:
                self.activity_cache[telegram_id] = {}

            if today not in self.activity_cache[telegram_id]:
                user_session['days_active'] += 1
                self.activity_cache[telegram_id][today] = True

            user_session['last_active'] = now
            user_session['loveliness_score'] = self.calculate_loveliness_score(telegram_id)

            # Update activity score in database
            current_user = self.db.get_user(telegram_id)
            new_activity_score = current_user['activity_score'] + 1
            self.update_activity_score(telegram_id, new_activity_score)

            # Check for level up
            if self.check_level_up(telegram_id):
                return True

        return False

    def create_verification(self, telegram_id: int, invite_code: str) -> Optional[str]:
        """Create a verification challenge."""
        if self.is_blacklisted(telegram_id):
            return None

        # Emoji sequence verification
        emojis = ["❤️", "💕", "💖", "💗", "💝", "💘", "💜", "💙"]
        selected = random.sample(emojis, 4)
        question = f"Type these emojis in order: {' '.join(selected)}"
        answer = ''.join(selected)

        self.verification_cache[telegram_id] = {
            "type": "emoji",
            "answer": answer,
            "invite_code": invite_code,
            "expires_at": time.time() + Config.VERIFICATION_TIMEOUT,
            "attempts": 0
        }

        return question

    def verify_answer(self, telegram_id: int, answer: str) -> Tuple[bool, Optional[str]]:
        """Verify user's answer."""
        if telegram_id not in self.verification_cache:
            return False, None

        verif = self.verification_cache[telegram_id]

        if time.time() > verif["expires_at"]:
            del self.verification_cache[telegram_id]
            return False, None

        verif["attempts"] += 1

        # Clean answer for comparison
        answer_clean = answer.strip().replace(' ', '')
        expected_clean = verif["answer"].replace(' ', '')

        if answer_clean == expected_clean:
            invite_code = verif["invite_code"]
            del self.verification_cache[telegram_id]
            return True, invite_code

        # Too many attempts
        if verif["attempts"] >= 3:
            self.blacklist_user(telegram_id)
            del self.verification_cache[telegram_id]

        return False, None

    def get_leaderboard(self, limit: int = 10) -> Dict[str, Any]:
        """Get comprehensive leaderboard data."""
        # Points leaderboard from database
        points_leaders = self.db.get_leaderboard(limit)

        # Session-based leaderboards
        level_leaders = []
        loveliness_leaders = []
        heat_leaders = []

        for telegram_id, session_data in self.user_cache.items():
            user_db = self.db.get_user(telegram_id)
            if user_db:
                level_leaders.append({
                    'username': user_db['username'],
                    'telegram_id': telegram_id,
                    'level': session_data['level'],
                    'xp': session_data['xp']
                })

                loveliness_leaders.append({
                    'username': user_db['username'],
                    'telegram_id': telegram_id,
                    'loveliness': self.calculate_loveliness_score(telegram_id)
                })

                heat_score = self.calculate_heat_score(telegram_id)
                if heat_score > 0:
                    heat_leaders.append({
                        'username': user_db['username'],
                        'telegram_id': telegram_id,
                        'heat': heat_score
                    })

        # Sort session-based leaderboards
        level_leaders.sort(key=lambda x: (x['level'], x['xp']), reverse=True)
        loveliness_leaders.sort(key=lambda x: x['loveliness'], reverse=True)
        heat_leaders.sort(key=lambda x: x['heat'], reverse=True)

        return {
            'points': points_leaders[:limit],
            'levels': level_leaders[:limit],
            'loveliness': loveliness_leaders[:limit],
            'heat': heat_leaders[:5]  # Show top 5 hot users
        }

    def cleanup_expired_data(self):
        """Clean up expired verifications and other temporary data."""
        now = time.time()
        expired_verifications = []

        for telegram_id, verif in self.verification_cache.items():
            if now > verif["expires_at"]:
                expired_verifications.append(telegram_id)

        for telegram_id in expired_verifications:
            del self.verification_cache[telegram_id]

        if expired_verifications:
            logger.info(f"Cleaned up {len(expired_verifications)} expired verifications")