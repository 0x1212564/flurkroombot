#!/usr/bin/env python3
"""
Message handlers for Roombot.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from config import Config
from user_manager import UserManager
from invite_manager import InviteManager

logger = logging.getLogger(__name__)


class MessageHandlers:
    def __init__(self, user_manager: UserManager, invite_manager: InviteManager):
        self.user_manager = user_manager
        self.invite_manager = invite_manager

    async def handle_private_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle private messages for verification."""
        user_id = update.effective_user.id
        username = update.effective_user.username or f"user_{user_id}"
        text = update.message.text.strip()

        # Initialize user
        user = self.user_manager.get_or_create_user(user_id, username)
        if not user:
            await update.message.reply_text("❌ Failed to initialize user.")
            return

        # Check for verification
        verified, invite_code = self.user_manager.verify_answer(user_id, text)

        if verified and invite_code:
            await self._handle_successful_verification(update, context, invite_code, user_id)
        elif not verified and user_id in self.user_manager.verification_cache:
            await self._handle_failed_verification(update, user_id)
        else:
            # Track activity for regular private messages
            leveled = self.user_manager.track_activity(user_id)
            if leveled:
                user_session = self.user_manager.get_user_session_data(user_id)
                level = user_session['level'] if user_session else 1
                await update.message.reply_text(
                    f"🎉 **LEVEL UP!** You reached level {level}! 🎉"
                )

    async def _handle_successful_verification(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                              invite_code: str, user_id: int):
        """Handle successful verification."""
        invite_data = self.invite_manager.get_invite(invite_code)
        if not invite_data:
            await update.message.reply_text("💔 Invite no longer exists.")
            return

        # Check if user already has a relationship
        existing_inviter = self.invite_manager.get_inviter(user_id)
        if existing_inviter:
            await update.message.reply_text(
                "💕 You're already part of the Love Network!\n"
                "Spread your own love with /invite!"
            )
            return

        try:
            # Create one-time invite link
            group_id = invite_data["group_id"]
            inviter_id = invite_data["inviter_id"]

            link = await context.bot.create_chat_invite_link(
                chat_id=group_id,
                name=f"Love Invite - {str(user_id)[:8]}",
                member_limit=1,
                creates_join_request=False
            )

            # Mark invite as used
            self.invite_manager.use_invite(invite_code, user_id)

            await update.message.reply_text(
                f"💘 **Verification Successful!** 💘\n\n"
                f"Welcome to the Love Network!\n"
                f"Here's your exclusive one-time entry:\n\n"
                f"{link.invite_link}\n\n"
                f"Join quickly, this link expires after one use! 💕",
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"Failed to create invite link: {e}")
            await update.message.reply_text(
                "💔 Verification successful but couldn't create invite link.\n"
                "Make sure the bot is admin in the group!"
            )

    async def _handle_failed_verification(self, update: Update, user_id: int):
        """Handle failed verification attempt."""
        verif = self.user_manager.verification_cache.get(user_id)
        if not verif:
            return

        attempts = verif["attempts"]
        remaining = 3 - attempts

        if remaining > 0:
            await update.message.reply_text(
                f"💔 That's not right! You have {remaining} attempts left.\n"
                f"Check the emoji sequence carefully! 💕"
            )
        else:
            await update.message.reply_text(
                "💔 Too many wrong attempts! You've been temporarily blocked.\n"
                "Try again in 24 hours!"
            )

    async def handle_group_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Track activity in groups."""
        if not update.effective_user:
            return

        user_id = update.effective_user.id
        username = update.effective_user.username or f"user_{user_id}"

        # Initialize user if needed
        user = self.user_manager.get_or_create_user(user_id, username)
        if not user:
            return

        # Track activity
        leveled = self.user_manager.track_activity(user_id)

        # Notify level up (occasionally, to avoid spam)
        if leveled:
            user_session = self.user_manager.get_user_session_data(user_id)
            level = user_session['level'] if user_session else 1

            # Only announce significant levels or occasionally
            if level % 5 == 0 or level <= 3:
                await update.message.reply_text(
                    f"🎉 {update.effective_user.first_name} reached **Level {level}** in the Love Network! 🎉",
                    parse_mode="Markdown"
                )

    async def handle_new_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle new members joining."""
        if not update.message.new_chat_members:
            return

        group_id = update.effective_chat.id

        for member in update.message.new_chat_members:
            user_id = member.id
            username = member.username or f"user_{user_id}"

            # Initialize user
            user = self.user_manager.get_or_create_user(user_id, username)
            if not user:
                continue

            # Check if they joined through an invite
            inviter_id = self.invite_manager.get_inviter(user_id)

            if inviter_id:
                await self._process_successful_invite(inviter_id, user_id, member.first_name, group_id, context)

    async def _process_successful_invite(self, inviter_id: int, invited_user_id: int,
                                         invited_name: str, group_id: int, context: ContextTypes.DEFAULT_TYPE):
        """Process a successful invite."""
        # Update inviter stats
        inviter_session = self.user_manager.get_user_session_data(inviter_id)
        if inviter_session:
            inviter_session['invites_successful'] += 1
            inviter_session['invite_streak'] = inviter_session.get('invite_streak', 0) + 1
            inviter_session['last_invite_success'] = time.time()

        # Award points with cascade effect
        await self._award_cascade_points(inviter_id, Config.INVITE_BASE_POINTS)

        # Check for milestones
        await self._check_milestones(inviter_id, group_id, context)

        # Calculate heat score
        heat = self.user_manager.calculate_heat_score(inviter_id)
        heat_emoji = "🔥" * min(int(heat / 10), 5) if heat > 0 else ""

        # Welcome message
        try:
            await context.bot.send_message(
                chat_id=group_id,
                text=(
                    f"💕 Welcome {invited_name} to the Love Network! 💕\n"
                    f"You were invited by a special Cupid! {heat_emoji}\n"
                    f"Use /help to learn how to spread the love!"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to send welcome message: {e}")

    async def _award_cascade_points(self, user_id: int, base_points: float):
        """Award points with cascade up the invite tree."""
        current_id = user_id
        current_points = base_points
        depth = 0
        max_depth = 10

        # Apply streak bonus to direct inviter
        user_session = self.user_manager.get_user_session_data(user_id)
        streak_bonus = 1.0
        if user_session:
            streak = user_session.get('invite_streak', 0)
            streak_bonus = 1 + (streak * Config.STREAK_BONUS_MULTIPLIER)
            current_points *= streak_bonus

        while current_id and current_points >= 0.01 and depth < max_depth:
            # Award points
            self.user_manager.award_points(
                current_id,
                current_points,
                f"cascade depth {depth} (streak x{streak_bonus:.1f})"
            )

            # Find parent
            parent_id = self.invite_manager.get_inviter(current_id)
            if parent_id:
                current_id = parent_id
                current_points /= 2  # Halve points at each level
                depth += 1
                streak_bonus = 1.0  # Only apply streak to direct inviter
            else:
                break

    async def _check_milestones(self, inviter_id: int, group_id: int, context: ContextTypes.DEFAULT_TYPE):
        """Check if user reached any milestones."""
        inviter_session = self.user_manager.get_user_session_data(inviter_id)
        if not inviter_session:
            return

        successful = inviter_session['invites_successful']
        milestones_reached = inviter_session.get('milestones_reached', [])

        for milestone in Config.MILESTONE_ANNOUNCES:
            if successful >= milestone and milestone not in milestones_reached:
                milestones_reached.append(milestone)
                inviter_session['milestones_reached'] = milestones_reached

                # Announce milestone
                try:
                    inviter = self.user_manager.db.get_user(inviter_id)
                    if inviter:
                        heat_score = self.user_manager.calculate_heat_score(inviter_id)
                        await context.bot.send_message(
                            chat_id=group_id,
                            text=(
                                f"🎉 **MILESTONE ALERT!** 🎉\n\n"
                                f"{inviter['username']} just hit {milestone} successful invites!\n"
                                f"They're on fire! 🔥🔥🔥\n\n"
                                f"Heat Score: {heat_score:.1f} 🌡️"
                            ),
                            parse_mode="Markdown"
                        )
                except Exception as e:
                    logger.error(f"Failed to announce milestone: {e}")

    async def handle_member_left(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle members leaving."""
        if not update.chat_member or not update.chat_member.new_chat_member:
            return

        member = update.chat_member.new_chat_member.user
        user_id = member.id

        # Check if they were invited
        inviter_id = self.invite_manager.get_inviter(user_id)
        if inviter_id:
            # Deduct penalty points from inviter
            penalty = Config.INVITE_BASE_POINTS * 0.5  # Half penalty

            inviter = self.user_manager.db.get_user(inviter_id)
            if inviter:
                new_points = max(0, inviter['points'] - penalty)
                self.user_manager.update_user_points(inviter_id, int(new_points))

                # Update heat score
                inviter_session = self.user_manager.get_user_session_data(inviter_id)
                if inviter_session:
                    inviter_session['heat_score'] = self.user_manager.calculate_heat_score(inviter_id)

                logger.info(f"Applied penalty of {penalty} points to user {inviter_id} for member leaving")