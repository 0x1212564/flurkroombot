#!/usr/bin/env python3
"""
Callback query handlers for Roombot.
"""

import logging
import time
import random
from telegram import Update
from telegram.ext import ContextTypes

from config import Config
from user_manager import UserManager
from invite_manager import InviteManager

logger = logging.getLogger(__name__)


class CallbackHandlers:
    def __init__(self, user_manager: UserManager, invite_manager: InviteManager):
        self.user_manager = user_manager
        self.invite_manager = invite_manager

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks."""
        query = update.callback_query
        user_id = query.from_user.id
        username = query.from_user.username or f"user_{user_id}"

        # Parse callback data
        try:
            action, wager_id = query.data.split('_', 1)
        except ValueError:
            await query.answer("❌ Invalid button data!", show_alert=True)
            return

        # Check if wager exists
        wager = self.invite_manager.get_wager(wager_id)
        if not wager:
            await query.answer("💔 This duel has expired!", show_alert=True)
            await query.edit_message_text("💔 This love duel has expired!")
            return

        # Check if expired
        if time.time() > wager["expires_at"]:
            await self._handle_expired_wager(query, wager_id, wager)
            return

        if action == "accept":
            await self._handle_accept_wager(query, wager_id, wager, user_id, username)
        elif action == "cancel":
            await self._handle_cancel_wager(query, wager_id, wager, user_id)

    async def _handle_expired_wager(self, query, wager_id: str, wager: dict):
        """Handle expired wager."""
        # Refund challenger if not accepted
        if not wager.get("accepted", False):
            challenger_id = wager["challenger_id"]
            self.user_manager.award_points(challenger_id, wager["points"], "wager refund")

        self.invite_manager.remove_wager(wager_id)
        await query.answer("💔 This duel has expired!", show_alert=True)
        await query.edit_message_text("💔 This love duel expired!")

    async def _handle_accept_wager(self, query, wager_id: str, wager: dict, user_id: int, username: str):
        """Handle wager acceptance."""
        # Check if it's the challenger trying to accept their own wager
        if user_id == wager["challenger_id"]:
            await query.answer("💝 You can't accept your own duel!", show_alert=True)
            return

        # Check if already accepted
        if wager["accepted"]:
            await query.answer("💔 Someone already accepted this duel!", show_alert=True)
            return

        # Get or create acceptor user
        acceptor = self.user_manager.get_or_create_user(user_id, username)
        if not acceptor:
            await query.answer("❌ Failed to load your data!", show_alert=True)
            return

        # Check if acceptor has enough points
        if acceptor["points"] < wager["points"]:
            await query.answer(
                f"💔 You need {wager['points']:.2f} points to accept this duel!",
                show_alert=True
            )
            return

        # Mark as accepted
        self.invite_manager.accept_wager(wager_id)

        # Execute the duel
        await self._execute_wager_duel(query, wager, user_id, username)

    async def _execute_wager_duel(self, query, wager: dict, acceptor_id: int, acceptor_username: str):
        """Execute the wager duel."""
        challenger_id = wager["challenger_id"]
        challenger_name = wager["challenger_name"]
        points = wager["points"]

        # Get users
        challenger = self.user_manager.get_or_create_user(challenger_id, challenger_name)
        acceptor = self.user_manager.get_or_create_user(acceptor_id, acceptor_username)

        if not challenger or not acceptor:
            await query.answer("❌ Failed to execute duel!", show_alert=True)
            return

        # Calculate XP for both parties
        challenger_loveliness = self.user_manager.calculate_loveliness_score(challenger_id)
        acceptor_loveliness = self.user_manager.calculate_loveliness_score(acceptor_id)

        challenger_xp = int(points * Config.WAGER_XP_MULTIPLIER * (1 + challenger_loveliness / 100))
        acceptor_xp = int(points * Config.WAGER_XP_MULTIPLIER * (1 + acceptor_loveliness / 100))

        # Award XP to both parties
        challenger_session = self.user_manager.get_user_session_data(challenger_id)
        acceptor_session = self.user_manager.get_user_session_data(acceptor_id)

        if challenger_session:
            challenger_session['xp'] += challenger_xp
        if acceptor_session:
            acceptor_session['xp'] += acceptor_xp

        # 50/50 chance to determine winner
        winner_id = random.choice([challenger_id, acceptor_id])
        loser_id = acceptor_id if winner_id == challenger_id else challenger_id

        # Award/deduct points
        if winner_id == challenger_id:
            # Challenger wins - gets their bet back + winnings
            challenger_new_points = challenger["points"] + points * 2
            acceptor_new_points = acceptor["points"] - points
            winner_name = challenger_name
            loser_name = acceptor_username

            if challenger_session:
                challenger_session['wagers_won'] += 1
            if acceptor_session:
                acceptor_session['wagers_lost'] += 1
        else:
            # Acceptor wins - challenger already lost their points, acceptor gets double
            challenger_new_points = challenger["points"]  # Already deducted
            acceptor_new_points = acceptor["points"] + points
            winner_name = acceptor_username
            loser_name = challenger_name

            if acceptor_session:
                acceptor_session['wagers_won'] += 1
            if challenger_session:
                challenger_session['wagers_lost'] += 1

        # Update points in database
        self.user_manager.update_user_points(challenger_id, int(challenger_new_points))
        self.user_manager.update_user_points(acceptor_id, int(acceptor_new_points))

        # Update session totals
        if winner_id == challenger_id and challenger_session:
            challenger_session['total_points_earned'] += points
        elif winner_id == acceptor_id and acceptor_session:
            acceptor_session['total_points_earned'] += points

        if loser_id == challenger_id and challenger_session:
            challenger_session['total_points_spent'] += points
        elif loser_id == acceptor_id and acceptor_session:
            acceptor_session['total_points_spent'] += points

        # Check for level ups
        challenger_leveled = self.user_manager.check_level_up(challenger_id)
        acceptor_leveled = self.user_manager.check_level_up(acceptor_id)

        # Remove wager
        self.invite_manager.remove_wager(wager["wager_id"] if "wager_id" in wager else "")

        # Prepare result message
        result_text = (
            f"💘 **Love Duel Results!** 💘\n\n"
            f"The arrows of love favor **{winner_name}**!\n"
            f"They win {points:.2f} points from {loser_name}!\n\n"
            f"**XP Gained:**\n"
            f"├ {challenger_name}: +{challenger_xp} XP\n"
            f"└ {acceptor_username}: +{acceptor_xp} XP\n\n"
            f"💕 Love is a game of chance! 💕"
        )

        if challenger_leveled or acceptor_leveled:
            result_text += "\n\n🎉 **LEVEL UP!** 🎉"
            if challenger_leveled and challenger_session:
                result_text += f"\n{challenger_name} → Level {challenger_session['level']}"
            if acceptor_leveled and acceptor_session:
                result_text += f"\n{acceptor_username} → Level {acceptor_session['level']}"

        await query.answer("💘 Duel complete!", show_alert=False)
        await query.edit_message_text(result_text, parse_mode="Markdown")

    async def _handle_cancel_wager(self, query, wager_id: str, wager: dict, user_id: int):
        """Handle wager cancellation."""
        # Only challenger can cancel
        if user_id != wager["challenger_id"]:
            await query.answer("💔 Only the challenger can cancel!", show_alert=True)
            return

        # Refund points
        self.user_manager.award_points(wager["challenger_id"], wager["points"], "wager cancellation")
        self.invite_manager.remove_wager(wager_id)

        await query.answer("💔 Duel cancelled!", show_alert=False)
        await query.edit_message_text("💔 Love duel was cancelled by the challenger.")