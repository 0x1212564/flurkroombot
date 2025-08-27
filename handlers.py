#!/usr/bin/env python3
"""
Command handlers for Roombot.
"""

import logging
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import Config
from invite_manager import InviteManager
from user_manager import UserManager

logger = logging.getLogger(__name__)


class CommandHandlers:
    def __init__(self, user_manager: UserManager, invite_manager: InviteManager):
        self.user_manager = user_manager
        self.invite_manager = invite_manager

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        user_id = update.effective_user.id
        username = update.effective_user.username or f"user_{user_id}"

        user = self.user_manager.get_or_create_user(user_id, username)
        if not user:
            await update.message.reply_text("❌ Failed to initialize user. Please try again.")
            return

        if context.args:
            invite_code = context.args[0]
            await self._handle_invite_code(update, context, invite_code)
        else:
            await self._send_welcome_message(update)

    async def _handle_invite_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE, invite_code: str):
        """Handle invite code from /start command."""
        user_id = update.effective_user.id

        if not self.invite_manager.is_invite_active(invite_code):
            await update.message.reply_text(
                "💔 That love invitation doesn't exist or has been deactivated.\n"
                "Ask your Cupid for a fresh one!"
            )
            return

        invite_data = self.invite_manager.get_invite(invite_code)

        # Check if user is trying to use their own invite
        if invite_data["inviter_id"] == user_id:
            await update.message.reply_text(
                "💝 You can't invite yourself, silly!\n"
                "Share the love with others!"
            )
            return

        # Check if already has a relationship
        existing_inviter = self.invite_manager.get_inviter(user_id)
        if existing_inviter:
            await update.message.reply_text(
                "💕 You're already part of the Love Network!\n"
                "Spread your own love with /invite in a group!"
            )
            return

        # Start verification
        question = self.user_manager.create_verification(user_id, invite_code)
        if question:
            await update.message.reply_text(
                f"💘 **Welcome to the Love Network!** 💘\n\n"
                f"Before you can join, prove you're a real person:\n\n"
                f"{question}\n\n"
                f"Send your answer as a message below! 💕",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "💔 You're temporarily blocked from the Love Network.\n"
                "Try again later!"
            )

    async def _send_welcome_message(self, update: Update):
        """Send welcome message for new users."""
        welcome_text = (
            "💕 **Welcome to Roombot's Love Network!** 💕\n\n"
            "Spread love, earn points, and build your network!\n\n"
            "📍 **Commands:**\n"
            "/invite - Generate a love invitation\n"
            "/profile - View your love stats\n"
            "/leaderboard - Top love spreaders\n"
            "/daily - Claim daily bonus\n"
            "/wager - Challenge someone\n"
            "/help - Full command list\n\n"
            "Start by joining a group and using /invite! 💘"
        )
        await update.message.reply_text(welcome_text, parse_mode="Markdown")

    async def cmd_invite(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate invite link."""
        if update.effective_chat.type in ["private", "channel"]:
            await update.message.reply_text(
                "💝 Please use /invite in a GROUP chat!\n"
                "That's where the love spreads best!"
            )
            return

        user_id = update.effective_user.id
        username = update.effective_user.username or f"user_{user_id}"
        group_id = update.effective_chat.id

        user = self.user_manager.get_or_create_user(user_id, username)

        if self.user_manager.is_blacklisted(user_id):
            await update.message.reply_text("💔 You're temporarily blocked from creating invitations.")
            return

        # Check for existing active invite
        existing_code = self.invite_manager.get_active_invite_for_user(user_id, group_id)

        if existing_code:
            await self._send_existing_invite(update, context, existing_code, user_id)
        else:
            await self._create_new_invite(update, context, user_id, group_id)

    async def _send_existing_invite(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                    invite_code: str, user_id: int):
        """Send existing invite link."""
        bot_username = context.bot.username
        invite_url = f"https://t.me/{bot_username}?start={invite_code}"

        invite_data = self.invite_manager.get_invite(invite_code)
        heat = self.user_manager.calculate_heat_score(user_id)
        heat_emoji = "🔥" * min(int(heat / 10), 5) if heat > 0 else "❄️"

        user_session = self.user_manager.get_user_session_data(user_id)
        streak = user_session.get('invite_streak', 0) if user_session else 0

        await update.message.reply_text(
            f"💘 **Your Active Love Link** 💘\n\n"
            f"Share everywhere:\n`{invite_url}`\n\n"
            f"📍 Code: `{invite_code}`\n"
            f"👥 Used by: {invite_data.get('total_uses', 0)} people\n"
            f"🔥 Heat: {heat:.1f} {heat_emoji}\n"
            f"📈 Streak: {streak} days\n\n"
            f"Want a fresh link? Use /newinvite\n"
            f"_Tap to copy and share everywhere!_",
            parse_mode="Markdown"
        )

    async def _create_new_invite(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                 user_id: int, group_id: int):
        """Create new invite link."""
        code = self.user_manager.generate_invite_code(user_id)

        success = self.invite_manager.create_invite(code, user_id, group_id)
        if not success:
            await update.message.reply_text("❌ Failed to create invite. Please try again.")
            return

        # Update user session data
        user_session = self.user_manager.get_user_session_data(user_id)
        if user_session:
            user_session['invites_sent'] += 1

        bot_username = context.bot.username
        invite_url = f"https://t.me/{bot_username}?start={code}"

        heat = self.user_manager.calculate_heat_score(user_id)
        heat_emoji = "🔥" * min(int(heat / 10), 5) if heat > 0 else "❄️"

        await update.message.reply_text(
            f"💘 **Love Link Created!** 💘\n\n"
            f"Share EVERYWHERE:\n`{invite_url}`\n\n"
            f"📍 Code: `{code}`\n"
            f"🔥 Heat: {heat:.1f} {heat_emoji}\n"
            f"♾️ Unlimited uses!\n"
            f"⚡ No cooldowns!\n\n"
            f"💡 Pro tip: Share on socials for viral growth!\n"
            f"_Tap to copy and start spreading love!_",
            parse_mode="Markdown"
        )

    async def cmd_newinvite(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate a fresh invite link."""
        if update.effective_chat.type in ["private", "channel"]:
            await update.message.reply_text("💝 Please use /newinvite in a GROUP chat!")
            return

        user_id = update.effective_user.id
        username = update.effective_user.username or f"user_{user_id}"
        group_id = update.effective_chat.id

        user = self.user_manager.get_or_create_user(user_id, username)

        if self.user_manager.is_blacklisted(user_id):
            await update.message.reply_text("💔 You're temporarily blocked from creating invitations.")
            return

        # Deactivate old invites
        deactivated = self.invite_manager.deactivate_user_invites(user_id, group_id)

        # Create new invite
        await self._create_new_invite(update, context, user_id, group_id)

    async def cmd_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user profile."""
        user_id = update.effective_user.id
        username = update.effective_user.username or f"user_{user_id}"

        user = self.user_manager.get_or_create_user(user_id, username)
        if not user:
            await update.message.reply_text("❌ Failed to load profile.")
            return

        user_session = self.user_manager.get_user_session_data(user_id)
        if not user_session:
            await update.message.reply_text("❌ Failed to load session data.")
            return

        # Calculate level progress
        current_xp = user_session['xp']
        needed_xp = self.user_manager.calculate_level_xp(user_session['level'])
        progress = int((current_xp / needed_xp) * 10)
        progress_bar = "❤️" * progress + "🤍" * (10 - progress)

        # Scores
        loveliness = self.user_manager.calculate_loveliness_score(user_id)
        heat = self.user_manager.calculate_heat_score(user_id)
        heat_emoji = "🔥" * min(int(heat / 10), 5) if heat > 0 else "❄️"

        profile_text = (
            f"💕 **Your Love Profile** 💕\n\n"
            f"**Level {user_session['level']} Cupid**\n"
            f"{progress_bar}\n"
            f"XP: {current_xp}/{needed_xp}\n\n"
            f"💝 **Points:** {user['points']}\n"
            f"✨ **Loveliness:** {loveliness:.1f}\n"
            f"🔥 **Heat Score:** {heat:.1f} {heat_emoji}\n"
            f"📈 **Streak:** {user_session.get('invite_streak', 0)} days\n\n"
            f"📊 **Stats:**\n"
            f"├ Invites Sent: {user_session['invites_sent']}\n"
            f"├ Successful: {user_session['invites_successful']}\n"
            f"├ Wagers Won: {user_session['wagers_won']}\n"
            f"├ Wagers Lost: {user_session['wagers_lost']}\n"
            f"└ Activity Score: {user['activity_score']}\n\n"
            f"💰 **Economy:**\n"
            f"├ Total Earned: {user_session['total_points_earned']:.1f}\n"
            f"└ Total Spent: {user_session['total_points_spent']:.1f}"
        )

        await update.message.reply_text(profile_text, parse_mode="Markdown")

    async def cmd_leaderboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show leaderboards."""
        leaderboards = self.user_manager.get_leaderboard()

        text = "💘 **Love Network Leaderboards** 💘\n\n"

        # Hot inviters
        if leaderboards['heat']:
            text += "**🔥 HOTTEST INVITERS RIGHT NOW:**\n"
            for i, user_data in enumerate(leaderboards['heat'], 1):
                heat_bar = "🔥" * min(int(user_data['heat'] / 10), 10)
                text += f"{i}. {user_data['username']}: {heat_bar}\n"
            text += "\n"

        # Points leaderboard
        text += "**💝 Top Point Holders:**\n"
        for i, user_data in enumerate(leaderboards['points'], 1):
            text += f"{i}. {user_data['username']}: {user_data['points']} pts\n"

        # Level leaderboard
        text += "\n**⭐ Highest Levels:**\n"
        for i, user_data in enumerate(leaderboards['levels'], 1):
            text += f"{i}. {user_data['username']}: Lvl {user_data['level']}\n"

        # Loveliness leaderboard
        text += "\n**✨ Most Lovely:**\n"
        for i, user_data in enumerate(leaderboards['loveliness'], 1):
            text += f"{i}. {user_data['username']}: {user_data['loveliness']:.1f} loveliness\n"

        await update.message.reply_text(text, parse_mode="Markdown")

    async def cmd_daily(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Claim daily bonus."""
        user_id = update.effective_user.id
        username = update.effective_user.username or f"user_{user_id}"

        user = self.user_manager.get_or_create_user(user_id, username)
        user_session = self.user_manager.get_user_session_data(user_id)

        if not user or not user_session:
            await update.message.reply_text("❌ Failed to load user data.")
            return

        now = time.time()
        if now - user_session["last_daily_bonus"] < Config.DAILY_BONUS_COOLDOWN:
            remaining = Config.DAILY_BONUS_COOLDOWN - (now - user_session["last_daily_bonus"])
            hours = int(remaining / 3600)
            minutes = int((remaining % 3600) / 60)
            await update.message.reply_text(
                f"💕 Your daily love bonus refreshes in {hours}h {minutes}m!\n"
                f"Come back then for more rewards!"
            )
            return

        # Calculate bonus
        base_bonus = 10
        level_bonus = user_session["level"] * 2
        streak_bonus = min(user_session["days_active"], 30)
        total_bonus = base_bonus + level_bonus + streak_bonus

        # Award points and XP
        success = self.user_manager.award_points(user_id, total_bonus, "daily bonus")
        if not success:
            await update.message.reply_text("❌ Failed to award daily bonus.")
            return

        user_session["xp"] += Config.ACTIVITY_XP_DAILY
        user_session["last_daily_bonus"] = now

        # Check for level up
        leveled = self.user_manager.check_level_up(user_id)

        msg = (
            f"💝 **Daily Love Bonus Claimed!** 💝\n\n"
            f"Base: +{base_bonus} points\n"
            f"Level Bonus: +{level_bonus} points\n"
            f"Streak Bonus: +{streak_bonus} points\n"
            f"**Total: +{total_bonus} points**\n\n"
            f"Also gained +{Config.ACTIVITY_XP_DAILY} XP! 💕"
        )

        if leveled:
            msg += f"\n\n🎉 **LEVEL UP!** You're now level {user_session['level']}!"

        await update.message.reply_text(msg, parse_mode="Markdown")

    async def cmd_wager(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Create a wager challenge."""
        user_id = update.effective_user.id
        username = update.effective_user.username or f"user_{user_id}"

        user = self.user_manager.get_or_create_user(user_id, username)
        if not user:
            await update.message.reply_text("❌ Failed to load user data.")
            return

        # Clean up expired wagers
        expired_wagers = self.invite_manager.cleanup_expired_wagers()
        for expired in expired_wagers:
            # Refund points for expired wagers
            if not expired.get('accepted', False):
                self.user_manager.award_points(expired['challenger_id'], expired['points'], "wager refund")

        # Parse arguments
        if not context.args:
            await update.message.reply_text(
                "💕 **Create a Love Duel:**\n"
                "/wager <points>\n\n"
                "Anyone with enough points can accept!"
            )
            return

        try:
            points = float(context.args[0])
            if points <= 0 or points > 1000:
                raise ValueError
            points = round(points, 2)
        except ValueError:
            await update.message.reply_text("💔 Points must be between 0.01 and 1000!")
            return

        # Check if user has enough points
        if user["points"] < points:
            await update.message.reply_text("💔 You don't have enough points for this wager!")
            return

        # Deduct points temporarily
        new_points = user["points"] - points
        success = self.user_manager.update_user_points(user_id, int(new_points))
        if not success:
            await update.message.reply_text("❌ Failed to create wager.")
            return

        # Create wager
        wager_id = f"wager_{int(time.time())}_{user_id}"
        self.invite_manager.create_wager(wager_id, user_id, username, points)

        # Create inline keyboard
        keyboard = [[
            InlineKeyboardButton("💘 Accept Duel", callback_data=f"accept_{wager_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{wager_id}")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"💘 **Open Love Duel!** 💘\n\n"
            f"{username} wagered {points:.2f} points!\n\n"
            f"First person to accept wins or loses it all!\n"
            f"⏰ Expires in 1 minute!",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    async def cmd_gift(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gift points to another user."""
        if not update.message.reply_to_message:
            await update.message.reply_text(
                "💝 **Gift Love Points:**\n"
                "Reply to someone's message with:\n"
                "/gift <points>\n\n"
                "Spread the love! 💕"
            )
            return

        if not context.args:
            await update.message.reply_text("💔 Please specify how many points to gift!")
            return

        try:
            points = float(context.args[0])
            if points <= 0:
                await update.message.reply_text("💔 You can only gift positive amounts!")
                return
            if points > 10000:
                await update.message.reply_text("💔 That's too generous! Maximum gift is 10000 points.")
                return
            points = round(points, 2)
        except ValueError:
            await update.message.reply_text("💔 Invalid amount! Use a number like 10 or 5.5")
            return

        giver_id = update.effective_user.id
        giver_username = update.effective_user.username or f"user_{giver_id}"
        recipient = update.message.reply_to_message.from_user
        recipient_id = recipient.id
        recipient_username = recipient.username or f"user_{recipient_id}"

        if recipient_id == giver_id:
            await update.message.reply_text("💝 You can't gift points to yourself!")
            return

        # Get users
        giver = self.user_manager.get_or_create_user(giver_id, giver_username)
        recipient_user = self.user_manager.get_or_create_user(recipient_id, recipient_username)

        if not giver or not recipient_user:
            await update.message.reply_text("❌ Failed to process gift.")
            return

        # Check if giver has enough points
        if giver["points"] < points:
            await update.message.reply_text(
                f"💔 You only have {giver['points']:.2f} points!\n"
                f"You need {points:.2f} to make this gift."
            )
            return

        # Transfer points
        giver_new_points = giver["points"] - points
        recipient_new_points = recipient_user["points"] + points

        giver_success = self.user_manager.update_user_points(giver_id, int(giver_new_points))
        recipient_success = self.user_manager.update_user_points(recipient_id, int(recipient_new_points))

        if not (giver_success and recipient_success):
            await update.message.reply_text("❌ Failed to transfer points.")
            return

        # Update session data
        giver_session = self.user_manager.get_user_session_data(giver_id)
        recipient_session = self.user_manager.get_user_session_data(recipient_id)

        if giver_session:
            giver_session['total_points_spent'] += points
        if recipient_session:
            recipient_session['total_points_earned'] += points

        await update.message.reply_text(
            f"💝 **Love Gift Sent!** 💝\n\n"
            f"{giver_username} sent {points:.2f} points to {recipient_username}!\n\n"
            f"What a lovely gesture! 💕",
            parse_mode="Markdown"
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help message."""
        help_text = """
💕 **Roombot - Love Network** 💕

**Core Commands:**
/invite - Get your shareable love link
/newinvite - Generate fresh link (deactivates old)
/profile - View stats, level, heat score
/leaderboard - Top spreaders of love
/daily - Claim daily bonus

**Social Commands:**
/gift <points> - Gift points (reply to user)
/wager <points> - Create open duel (with XP!)

**Growth Features:**
🔥 **Heat Score** - Shows how hot your invites are
📈 **Streaks** - Daily invite success = bonus multiplier
🏆 **Milestones** - Hit 10, 25, 50+ invites for glory
♾️ **Unlimited Links** - Share everywhere, no cooldowns!

**Point System:**
- Invite success: 10 points (+ streak bonus!)
- Cascade: 5, 2.5, 1.25... up the tree
- Daily bonus: 10-50+ points
- Wagers: Win/lose points + gain XP!

**Pro Tips:**
💡 Share your link on socials for viral growth
💡 Build streaks for multiplied rewards
💡 Higher loveliness = more XP from wagers
💡 Gift points to build alliances

Let's make this chat EXPLODE! 🚀💘
"""
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot statistics."""
        user_count = self.user_manager.db.get_user_count()
        invite_stats = self.invite_manager.get_invite_stats()

        stats_text = (
            f"💘 **Roombot Statistics** 💘\n\n"
            f"👥 Total Users: {user_count}\n"
            f"💌 Total Invites: {invite_stats['total_invites']}\n"
            f"✅ Active Invites: {invite_stats['active_invites']}\n"
            f"🔗 Total Uses: {invite_stats['total_uses']}\n"
            f"👫 Relationships: {invite_stats['total_relationships']}\n"
            f"⚔️ Active Duels: {invite_stats['active_wagers']}\n"
        )

        await update.message.reply_text(stats_text, parse_mode="Markdown")