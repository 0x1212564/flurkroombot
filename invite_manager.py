#!/usr/bin/env python3
"""
Invitation system manager for Roombot.
"""

import logging
import time
import json
import os
from typing import Dict, Any, List, Optional
from config import Config

logger = logging.getLogger(__name__)


class InviteManager:
    def __init__(self, storage_file: str = "invites_data.json"):
        self.storage_file = storage_file
        self.invites = {}
        self.relationships = {}
        self.pending_wagers = {}
        self.load_data()

    def load_data(self):
        """Load invite data from file."""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.invites = data.get('invites', {})
                    self.relationships = data.get('relationships', {})
                    self.pending_wagers = data.get('pending_wagers', {})
            except json.JSONDecodeError:
                logger.error("Corrupted invite data file, initializing fresh")
                self.initialize_data()
        else:
            self.initialize_data()

    def initialize_data(self):
        """Initialize fresh data structures."""
        self.invites = {}
        self.relationships = {}
        self.pending_wagers = {}

    def save_data(self):
        """Save invite data to file."""
        try:
            data = {
                'invites': self.invites,
                'relationships': self.relationships,
                'pending_wagers': self.pending_wagers
            }
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save invite data: {e}")

    def create_invite(self, invite_code: str, inviter_id: int, group_id: int) -> bool:
        """Create a new invite."""
        self.invites[invite_code] = {
            "inviter_id": inviter_id,
            "group_id": group_id,
            "created_at": time.time(),
            "active": True,
            "total_uses": 0,
            "used_by_list": []
        }
        self.save_data()
        return True

    def get_invite(self, invite_code: str) -> Optional[Dict[str, Any]]:
        """Get invite by code."""
        return self.invites.get(invite_code)

    def is_invite_active(self, invite_code: str) -> bool:
        """Check if invite is active."""
        invite = self.get_invite(invite_code)
        return invite and invite.get('active', False)

    def deactivate_invite(self, invite_code: str) -> bool:
        """Deactivate an invite."""
        if invite_code in self.invites:
            self.invites[invite_code]['active'] = False
            self.save_data()
            return True
        return False

    def use_invite(self, invite_code: str, user_id: int) -> bool:
        """Mark invite as used by a user."""
        if invite_code not in self.invites:
            return False

        invite = self.invites[invite_code]

        # Add user to used_by_list if not already there
        if user_id not in invite.get('used_by_list', []):
            if 'used_by_list' not in invite:
                invite['used_by_list'] = []
            invite['used_by_list'].append(user_id)
            invite['total_uses'] = invite.get('total_uses', 0) + 1

            # Create relationship
            self.relationships[str(user_id)] = invite['inviter_id']

            self.save_data()
            return True

        return False

    def get_user_invites(self, inviter_id: int, group_id: int = None) -> List[Dict[str, Any]]:
        """Get all invites created by a user."""
        user_invites = []
        for code, invite in self.invites.items():
            if invite['inviter_id'] == inviter_id:
                if group_id is None or invite['group_id'] == group_id:
                    user_invites.append({**invite, 'code': code})
        return user_invites

    def get_active_invite_for_user(self, inviter_id: int, group_id: int) -> Optional[str]:
        """Get active invite code for user in specific group."""
        for code, invite in self.invites.items():
            if (invite['inviter_id'] == inviter_id and
                    invite['group_id'] == group_id and
                    invite.get('active', False)):
                return code
        return None

    def deactivate_user_invites(self, inviter_id: int, group_id: int) -> int:
        """Deactivate all invites for user in specific group."""
        deactivated = 0
        for code, invite in self.invites.items():
            if (invite['inviter_id'] == inviter_id and
                    invite['group_id'] == group_id and
                    invite.get('active', False)):
                invite['active'] = False
                deactivated += 1

        if deactivated > 0:
            self.save_data()

        return deactivated

    def get_inviter(self, user_id: int) -> Optional[int]:
        """Get who invited this user."""
        return self.relationships.get(str(user_id))

    def get_invited_users(self, inviter_id: int) -> List[int]:
        """Get all users invited by this inviter."""
        invited = []
        for user_id, inviter in self.relationships.items():
            if inviter == inviter_id:
                invited.append(int(user_id))
        return invited

    def create_wager(self, wager_id: str, challenger_id: int, challenger_name: str, points: float) -> bool:
        """Create a new wager."""
        self.pending_wagers[wager_id] = {
            "challenger_id": challenger_id,
            "challenger_name": challenger_name,
            "points": points,
            "expires_at": time.time() + Config.WAGER_EXPIRY,
            "accepted": False
        }
        self.save_data()
        return True

    def get_wager(self, wager_id: str) -> Optional[Dict[str, Any]]:
        """Get wager by ID."""
        return self.pending_wagers.get(wager_id)

    def accept_wager(self, wager_id: str) -> bool:
        """Mark wager as accepted."""
        if wager_id in self.pending_wagers:
            self.pending_wagers[wager_id]['accepted'] = True
            self.save_data()
            return True
        return False

    def remove_wager(self, wager_id: str) -> bool:
        """Remove a wager."""
        if wager_id in self.pending_wagers:
            del self.pending_wagers[wager_id]
            self.save_data()
            return True
        return False

    def cleanup_expired_wagers(self) -> List[Dict[str, Any]]:
        """Clean up expired wagers and return list of expired ones."""
        now = time.time()
        expired = []
        expired_ids = []

        for wager_id, wager in self.pending_wagers.items():
            if now > wager["expires_at"]:
                expired.append({**wager, 'wager_id': wager_id})
                expired_ids.append(wager_id)

        for wager_id in expired_ids:
            del self.pending_wagers[wager_id]

        if expired_ids:
            self.save_data()
            logger.info(f"Cleaned up {len(expired_ids)} expired wagers")

        return expired

    def get_invite_stats(self) -> Dict[str, Any]:
        """Get overall invite statistics."""
        total_invites = len(self.invites)
        active_invites = sum(1 for inv in self.invites.values() if inv.get('active', False))
        total_uses = sum(inv.get('total_uses', 0) for inv in self.invites.values())
        total_relationships = len(self.relationships)
        active_wagers = len(self.pending_wagers)

        return {
            'total_invites': total_invites,
            'active_invites': active_invites,
            'total_uses': total_uses,
            'total_relationships': total_relationships,
            'active_wagers': active_wagers
        }