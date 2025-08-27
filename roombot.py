#!/usr/bin/env python3
"""
Cupid Bot V2 - The Love Network
A Telegram bot that creates a snowflake invite system with activity tracking,
XP/leveling, and point wagering. Spreads love through the network!
"""

import logging
import json
import os
import random
import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from telegram import Update, ChatInviteLink, ChatMemberUpdated, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

##############################################################################
#                          CONFIG & CONSTANTS
##############################################################################
API_TOKEN = "haha"
STORAGE_FILE = "cupid_bot_v2_data.json"

# Timing constants (seconds)
INVITE_COOLDOWN = 600  # 10 minutes between invites
VERIFICATION_TIMEOUT = 300  # 5 minutes to verify
WAGER_EXPIRY = 60  # 1 minute to accept wagers
BLACKLIST_DURATION = 86400  # 24 hours
DAILY_BONUS_COOLDOWN = 86400  # 24 hours for daily bonus

# Points and XP
INVITE_BASE_POINTS = 1  # Points for successful invite (simplified!)
ACTIVITY_XP_MESSAGE = 1  # XP per message
ACTIVITY_XP_DAILY = 50  # XP for daily bonus
LEVEL_XP_REQUIRED = 100  # Base XP required per level (scales)
WAGER_XP_MULTIPLIER = 0.1  # XP = wager_points * loveliness * this

# Activity tracking
MESSAGE_COOLDOWN = 30  # Seconds between XP-earning messages
ACTIVITY_DECAY_DAYS = 7  # Days before activity score starts decaying

# Viral mechanics
STREAK_BONUS_MULTIPLIER = 0.1  # 10% bonus per day of streak
HEAT_DECAY_HOURS = 24  # Hours before heat score decays
MILESTONE_ANNOUNCES = [10, 25, 50, 100, 250, 500, 1000]  # Announce these milestones

##############################################################################
#                          LOGGING SETUP
##############################################################################
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


##############################################################################
#                       DATA MANAGEMENT
##############################################################################
def load_data():
    """Load bot data with all required structures."""
    if not os.path.exists(STORAGE_FILE):
        return initialize_data()

    try:
        with open(STORAGE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        logger.error("Corrupted data file, initializing fresh")
        return initialize_data()

    # Ensure all structures exist
    required_keys = [
        "users", "invites", "verifications", "relationships",
        "pending_wagers", "activity_tracking", "daily_stats"
    ]

    for key in required_keys:
        if key not in data:
            data[key] = {}

    return data


def initialize_data():
    """Initialize fresh data structure."""
    return {
        "users": {},  # user_id -> user data
        "invites": {},  # invite_code -> invite data
        "verifications": {},  # user_id -> verification data
        "relationships": {},  # user_id -> parent_id
        "pending_wagers": {},  # wager_id -> wager data
        "activity_tracking": {},  # user_id -> activity data
        "daily_stats": {}  # date -> stats
    }


def save_data(data):
    """Save data to file."""
    try:
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save data: {e}")


# Global data instance
bot_data = load_data()


##############################################################################
#                         USER MANAGEMENT
##############################################################################
def init_user(user_id: str):
    """Initialize user with all required fields."""
    if user_id not in bot_data["users"]:
        bot_data["users"][user_id] = {
            # Points and levels
            "lover_points": 0.0,
            "xp": 0,
            "level": 1,

            # Invite tracking
            "invite_code": None,
            "invites_sent": 0,
            "invites_successful": 0,

            # Cooldowns and restrictions
            "last_invite_time": 0,
            "last_message_xp": 0,
            "last_daily_bonus": 0,
            "blacklisted_until": 0,
            "verification_attempts": 0,

            # Loveliness tracking
            "messages_sent": 0,
            "days_active": 0,
            "last_active": time.time(),
            "loveliness_score": 0.0,

            # Stats
            "wagers_won": 0,
            "wagers_lost": 0,
            "total_points_earned": 0.0,
            "total_points_spent": 0.0
        }


def generate_invite_code(user_id: str) -> str:
    """Generate a unique invite code."""
    # Use timestamp and user_id for uniqueness
    raw = f"{user_id}_{time.time()}_{random.randint(1000, 9999)}"
    code = hashlib.md5(raw.encode()).hexdigest()[:8].upper()
    return f"LOVE{code}"


def calculate_level_xp(level: int) -> int:
    """Calculate XP required for a level."""
    return LEVEL_XP_REQUIRED * level * (1 + level // 10)


def calculate_loveliness_score(user_id: str) -> float:
    """Calculate user's loveliness score with gentle decay."""
    user = bot_data["users"][user_id]
    last_active = user["last_active"]
    days_inactive = (time.time() - last_active) / 86400

    # Base loveliness from engagement and presence
    base_score = user["messages_sent"] * 0.1 + user["days_active"] * 5

    # Gentle decay after ACTIVITY_DECAY_DAYS
    if days_inactive > ACTIVITY_DECAY_DAYS:
        decay_factor = 0.95 ** (days_inactive - ACTIVITY_DECAY_DAYS)
        base_score *= decay_factor

    return round(base_score, 2)


def check_level_up(user_id: str) -> bool:
    """Check if user should level up."""
    user = bot_data["users"][user_id]
    current_level = user["level"]
    current_xp = user["xp"]

    required_xp = calculate_level_xp(current_level)

    if current_xp >= required_xp:
        user["level"] += 1
        user["xp"] -= required_xp
        save_data(bot_data)
        return True
    return False


def calculate_heat_score(user_id: str) -> float:
    """Calculate user's heat score (recent invite success rate)."""
    user = bot_data["users"][user_id]

    # Heat based on recent successful invites
    last_success = user.get("last_invite_success", 0)
    hours_since = (time.time() - last_success) / 3600

    if hours_since > HEAT_DECAY_HOURS:
        return 0.0

    # Base heat from successful invites in last 24h
    base_heat = user["invites_successful"]

    # Decay factor
    decay = (HEAT_DECAY_HOURS - hours_since) / HEAT_DECAY_HOURS

    return round(base_heat * decay, 2)


def update_invite_streak(user_id: str):
    """Update user's invite streak."""
    user = bot_data["users"][user_id]
    last_success = user.get("last_invite_success", 0)
    now = time.time()

    # Check if within 24 hours for streak
    if now - last_success < 86400:  # 24 hours
        user["invite_streak"] += 1
    else:
        user["invite_streak"] = 1

    user["last_invite_success"] = now
    user["heat_score"] = calculate_heat_score(user_id)


def check_milestones(user_id: str, context: ContextTypes.DEFAULT_TYPE) -> list:
    """Check if user reached any milestones."""
    user = bot_data["users"][user_id]
    successful = user["invites_successful"]
    milestones_hit = []

    for milestone in MILESTONE_ANNOUNCES:
        if successful >= milestone and milestone not in user["milestones_reached"]:
            user["milestones_reached"].append(milestone)
            milestones_hit.append(milestone)

    return milestones_hit


##############################################################################
#                         VERIFICATION SYSTEM
##############################################################################
def create_verification(user_id: str, invite_code: str) -> Optional[str]:
    """Create a verification challenge."""
    if is_blacklisted(user_id):
        return None

    # More complex verification: emoji sequence
    emojis = ["❤️", "💕", "💖", "💗", "💝", "💘", "💜", "💙"]
    selected = random.sample(emojis, 4)
    question = f"Type these emojis in order: {' '.join(selected)}"
    answer = ''.join(selected)

    bot_data["verifications"][user_id] = {
        "type": "emoji",
        "answer": answer,
        "invite_code": invite_code,
        "expires_at": time.time() + VERIFICATION_TIMEOUT,
        "attempts": 0
    }
    save_data(bot_data)
    return question


def verify_answer(user_id: str, answer: str) -> Tuple[bool, Optional[str]]:
    """Verify user's answer."""
    if user_id not in bot_data["verifications"]:
        return False, None

    verif = bot_data["verifications"][user_id]

    if time.time() > verif["expires_at"]:
        del bot_data["verifications"][user_id]
        save_data(bot_data)
        return False, None

    verif["attempts"] += 1

    # Clean answer for comparison
    answer_clean = answer.strip().replace(' ', '')
    expected_clean = verif["answer"].replace(' ', '')

    if answer_clean == expected_clean:
        invite_code = verif["invite_code"]
        del bot_data["verifications"][user_id]
        save_data(bot_data)
        return True, invite_code

    # Too many attempts
    if verif["attempts"] >= 3:
        blacklist_user(user_id)
        del bot_data["verifications"][user_id]
        save_data(bot_data)

    return False, None


##############################################################################
#                         HELPER FUNCTIONS
##############################################################################
def is_blacklisted(user_id: str) -> bool:
    return time.time() < bot_data["users"][user_id]["blacklisted_until"]


def blacklist_user(user_id: str):
    bot_data["users"][user_id]["blacklisted_until"] = time.time() + BLACKLIST_DURATION


def calculate_heat_score(user_id: str) -> float:
    """Calculate user's heat score (recent invite success rate)."""
    user = bot_data["users"][user_id]

    # Heat based on recent successful invites
    last_success = user.get("last_invite_success", 0)
    hours_since = (time.time() - last_success) / 3600

    if hours_since > HEAT_DECAY_HOURS:
        return 0.0

    # Base heat from successful invites in last 24h
    base_heat = user["invites_successful"]

    # Decay factor
    decay = (HEAT_DECAY_HOURS - hours_since) / HEAT_DECAY_HOURS

    return round(base_heat * decay, 2)


def update_invite_streak(user_id: str):
    """Update user's invite streak."""
    user = bot_data["users"][user_id]
    last_success = user.get("last_invite_success", 0)
    now = time.time()

    # Check if within 24 hours for streak
    if now - last_success < 86400:  # 24 hours
        user["invite_streak"] += 1
    else:
        user["invite_streak"] = 1

    user["last_invite_success"] = now
    user["heat_score"] = calculate_heat_score(user_id)


async def check_milestones(user_id: str, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> list:
    """Check if user reached any milestones and announce them."""
    user = bot_data["users"][user_id]
    successful = user["invites_successful"]
    milestones_hit = []

    for milestone in MILESTONE_ANNOUNCES:
        if successful >= milestone and milestone not in user["milestones_reached"]:
            user["milestones_reached"].append(milestone)
            milestones_hit.append(milestone)

            # Announce in the group
            try:
                user_name = await get_user_display_name(context, user_id)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🎉 **MILESTONE ALERT!** 🎉\n\n"
                         f"{user_name} just hit {milestone} successful invites!\n"
                         f"They're on fire! 🔥🔥🔥\n\n"
                         f"Heat Score: {user['heat_score']:.1f} 🌡️",
                    parse_mode="Markdown"
                )
            except:
                pass

    return milestones_hit


def award_points(user_id: str, points: float, reason: str = ""):
    """Award points to user."""
    user = bot_data["users"][user_id]
    user["lover_points"] += points
    user["total_points_earned"] += points
    logger.info(f"Awarded {points} to {user_id} - {reason}")


def award_points_cascade(user_id: str, base_points: float = INVITE_BASE_POINTS):
    """Award points with cascade up the invite tree and apply streak bonus."""
    current_id = user_id
    current_points = base_points
    depth = 0

    # Apply streak bonus to direct inviter
    user = bot_data["users"][user_id]
    streak_bonus = 1 + (user.get("invite_streak", 0) * STREAK_BONUS_MULTIPLIER)
    current_points *= streak_bonus

    while current_id and current_points >= 0.01 and depth < 10:
        award_points(current_id, current_points, f"cascade depth {depth} (streak x{streak_bonus:.1f})")

        # Find parent
        if current_id in bot_data["relationships"]:
            current_id = bot_data["relationships"][current_id]
            current_points /= 2
            depth += 1
            streak_bonus = 1  # Only apply streak to direct inviter
        else:
            break


def track_activity(user_id: str):
    """Track user activity for XP."""
    user = bot_data["users"][user_id]
    now = time.time()

    # Check if enough time passed for XP
    if now - user["last_message_xp"] >= MESSAGE_COOLDOWN:
        user["xp"] += ACTIVITY_XP_MESSAGE
        user["total_xp_earned"] = user.get("total_xp_earned", 0) + ACTIVITY_XP_MESSAGE
        user["last_message_xp"] = now
        user["messages_sent"] += 1

        # Update daily active status
        today = datetime.now().date().isoformat()
        if today not in bot_data["activity_tracking"].get(user_id, {}):
            user["days_active"] += 1
            if user_id not in bot_data["activity_tracking"]:
                bot_data["activity_tracking"][user_id] = {}
            bot_data["activity_tracking"][user_id][today] = True

        user["last_active"] = now
        user["loveliness_score"] = calculate_loveliness_score(user_id)

        # Check for level up
        if check_level_up(user_id):
            return True

        save_data(bot_data)

    return False


def cleanup_expired_wagers():
    """Clean up expired wagers and refund points."""
    now = time.time()
    expired = []

    for wager_id, wager in bot_data["pending_wagers"].items():
        if now > wager["expires_at"]:
            expired.append(wager_id)
            # Refund challenger if not accepted
            if not wager.get("accepted", False):
                challenger_id = wager["challenger_id"]
                if challenger_id in bot_data["users"]:
                    bot_data["users"][challenger_id]["lover_points"] += wager["points"]

    for wager_id in expired:
        del bot_data["pending_wagers"][wager_id]

    if expired:
        save_data(bot_data)
        logger.info(f"Cleaned up {len(expired)} expired wagers")


async def get_user_display_name(context: ContextTypes.DEFAULT_TYPE, user_id: str) -> str:
    """Get user's display name with fallback."""
    try:
        user = await context.bot.get_chat(user_id)
        name = user.full_name or f"Cupid_{user_id[:6]}"
        return f"[{name}](tg://user?id={user_id})"
    except:
        return f"Cupid_{user_id[:6]}"


##############################################################################
#                         COMMAND HANDLERS
##############################################################################
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user_id = str(update.effective_user.id)
    init_user(user_id)

    if context.args:
        invite_code = context.args[0]

        if invite_code not in bot_data["invites"]:
            await update.message.reply_text(
                "💔 That love invitation doesn't exist.\n"
                "Ask your Cupid for a fresh one!"
            )
            return

        invite_data = bot_data["invites"][invite_code]

        # Check if invite is still active
        if not invite_data.get("active", True):
            await update.message.reply_text(
                "💔 This love invitation has been deactivated.\n"
                "Ask your Cupid for their current link!"
            )
            return

        # Check if this specific user already used this code
        if user_id in bot_data["relationships"] and bot_data["relationships"][user_id] == invite_data["inviter_id"]:
            await update.message.reply_text(
                "💕 You've already joined through this Cupid's love!\n"
                "Spread your own love with /invite in a group!"
            )
            return

        if invite_data["inviter_id"] == user_id:
            await update.message.reply_text(
                "💝 You can't invite yourself, silly!\n"
                "Share the love with others!"
            )
            return

        # Start verification
        question = create_verification(user_id, invite_code)
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
    else:
        await update.message.reply_text(
            "💕 **Welcome to Cupid's Love Network!** 💕\n\n"
            "Spread love, earn points, and build your network!\n\n"
            "📍 **Commands:**\n"
            "/invite - Generate a love invitation\n"
            "/myprofile - View your love stats\n"
            "/leaderboard - Top love spreaders\n"
            "/daily - Claim daily bonus\n"
            "/wager - Challenge someone\n"
            "/help - Full command list\n\n"
            "Start by joining a group and using /invite! 💘",
            parse_mode="Markdown"
        )


async def cmd_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate invite link - persistent and shareable everywhere!"""
    if update.effective_chat.type in ["private", "channel"]:
        await update.message.reply_text(
            "💝 Please use /invite in a GROUP chat!\n"
            "That's where the love spreads best!"
        )
        return

    user_id = str(update.effective_user.id)
    init_user(user_id)

    if is_blacklisted(user_id):
        await update.message.reply_text("💔 You're temporarily blocked from creating invitations.")
        return

    # Check if user already has a code for this group
    existing_code = None
    group_id = str(update.effective_chat.id)

    for code, invite_data in bot_data["invites"].items():
        if (invite_data["inviter_id"] == user_id and
                str(invite_data["group_id"]) == group_id and
                invite_data.get("active", True)):
            existing_code = code
            break

    if existing_code:
        # User already has an active code for this group
        bot_username = context.bot.username
        invite_url = f"https://t.me/{bot_username}?start={existing_code}"

        heat = calculate_heat_score(user_id)
        heat_emoji = "🔥" * min(int(heat / 10), 5) if heat > 0 else "❄️"

        total_uses = invite_data.get("total_uses", 0)

        await update.message.reply_text(
            f"💘 **Your Active Love Link** 💘\n\n"
            f"Share everywhere:\n`{invite_url}`\n\n"
            f"📍 Code: `{existing_code}`\n"
            f"👥 Used by: {total_uses} people\n"
            f"🔥 Heat: {heat:.1f} {heat_emoji}\n"
            f"📈 Streak: {bot_data['users'][user_id].get('invite_streak', 0)} days\n\n"
            f"Want a fresh link? Use /newinvite\n"
            f"_Tap to copy and share everywhere!_",
            parse_mode="Markdown"
        )
        return

    # Generate new invite code
    code = generate_invite_code(user_id)
    bot_data["users"][user_id]["invite_code"] = code
    bot_data["users"][user_id]["invites_sent"] += 1

    bot_data["invites"][code] = {
        "inviter_id": user_id,
        "group_id": update.effective_chat.id,
        "created_at": time.time(),
        "active": True,
        "total_uses": 0,
        "used_by_list": []
    }

    save_data(bot_data)

    bot_username = context.bot.username
    invite_url = f"https://t.me/{bot_username}?start={code}"

    heat = calculate_heat_score(user_id)
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


async def cmd_newinvite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a fresh invite link, deactivating the old one."""
    if update.effective_chat.type in ["private", "channel"]:
        await update.message.reply_text("💝 Please use /newinvite in a GROUP chat!")
        return

    user_id = str(update.effective_user.id)
    init_user(user_id)

    if is_blacklisted(user_id):
        await update.message.reply_text("💔 You're temporarily blocked from creating invitations.")
        return

    # Deactivate old codes for this group
    group_id = str(update.effective_chat.id)
    deactivated = 0

    for code, invite_data in bot_data["invites"].items():
        if (invite_data["inviter_id"] == user_id and
                str(invite_data["group_id"]) == group_id and
                invite_data.get("active", True)):
            invite_data["active"] = False  # Mark as inactive instead of used
            deactivated += 1

    # Generate new code
    code = generate_invite_code(user_id)
    bot_data["users"][user_id]["invite_code"] = code

    bot_data["invites"][code] = {
        "inviter_id": user_id,
        "group_id": update.effective_chat.id,
        "created_at": time.time(),
        "active": True,
        "total_uses": 0,
        "used_by_list": []
    }

    save_data(bot_data)

    bot_username = context.bot.username
    invite_url = f"https://t.me/{bot_username}?start={code}"

    await update.message.reply_text(
        f"💘 **Fresh Love Link!** 💘\n\n"
        f"Old links deactivated: {deactivated}\n"
        f"New link ready:\n`{invite_url}`\n\n"
        f"📍 Code: `{code}`\n"
        f"♾️ Share everywhere!\n\n"
        f"_Your new viral weapon is ready!_",
        parse_mode="Markdown"
    )


async def cmd_myprofile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user profile with stats."""
    user_id = str(update.effective_user.id)
    init_user(user_id)

    user = bot_data["users"][user_id]

    # Calculate level progress
    current_xp = user["xp"]
    needed_xp = calculate_level_xp(user["level"])
    progress = int((current_xp / needed_xp) * 10)
    progress_bar = "❤️" * progress + "🤍" * (10 - progress)

    # Loveliness score
    loveliness = calculate_loveliness_score(user_id)

    # Heat score
    heat = calculate_heat_score(user_id)
    heat_emoji = "🔥" * min(int(heat / 10), 5) if heat > 0 else "❄️"

    profile = (
        f"💕 **Your Love Profile** 💕\n\n"
        f"**Level {user['level']} Cupid**\n"
        f"{progress_bar}\n"
        f"XP: {current_xp}/{needed_xp}\n\n"
        f"💝 **Lover Points:** {user['lover_points']:.1f}\n"
        f"✨ **Loveliness:** {loveliness:.1f}\n"
        f"🔥 **Heat Score:** {heat:.1f} {heat_emoji}\n"
        f"📈 **Streak:** {user.get('invite_streak', 0)} days\n\n"
        f"📊 **Stats:**\n"
        f"├ Invites Sent: {user['invites_sent']}\n"
        f"├ Successful: {user['invites_successful']}\n"
        f"├ Wagers Won: {user['wagers_won']}\n"
        f"└ Wagers Lost: {user['wagers_lost']}\n\n"
        f"💰 **Economy:**\n"
        f"├ Total Earned: {user['total_points_earned']:.1f}\n"
        f"├ Total Spent: {user['total_points_spent']:.1f}\n"
        f"└ Total XP: {user.get('total_xp_earned', 0)}"
    )

    await update.message.reply_text(profile, parse_mode="Markdown")


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show leaderboards."""
    # Points leaderboard
    points_leaders = sorted(
        [(uid, data["lover_points"]) for uid, data in bot_data["users"].items()],
        key=lambda x: x[1],
        reverse=True
    )[:10]

    # Level leaderboard
    level_leaders = sorted(
        [(uid, data["level"], data["xp"]) for uid, data in bot_data["users"].items()],
        key=lambda x: (x[1], x[2]),
        reverse=True
    )[:10]

    # Loveliness leaderboard
    loveliness_leaders = sorted(
        [(uid, calculate_loveliness_score(uid)) for uid in bot_data["users"].keys()],
        key=lambda x: x[1],
        reverse=True
    )[:10]

    # Heat leaderboard
    heat_leaders = sorted(
        [(uid, calculate_heat_score(uid)) for uid in bot_data["users"].keys()],
        key=lambda x: x[1],
        reverse=True
    )[:5]

    text = "💘 **Love Network Leaderboards** 💘\n\n"

    if heat_leaders and any(score > 0 for _, score in heat_leaders):
        text += "**🔥 HOTTEST INVITERS RIGHT NOW:**\n"
        for i, (uid, heat) in enumerate(heat_leaders, 1):
            if heat > 0:
                name = await get_user_display_name(context, uid)
                heat_bar = "🔥" * min(int(heat / 10), 10)
                text += f"{i}. {name}: {heat_bar}\n"
        text += "\n"

    text += "**💝 Top Point Holders:**\n"
    for i, (uid, points) in enumerate(points_leaders, 1):
        name = await get_user_display_name(context, uid)
        text += f"{i}. {name}: {points:.1f} pts\n"

    text += "\n**⭐ Highest Levels:**\n"
    for i, (uid, level, xp) in enumerate(level_leaders, 1):
        name = await get_user_display_name(context, uid)
        text += f"{i}. {name}: Lvl {level}\n"

    text += "\n**✨ Most Lovely:**\n"
    for i, (uid, score) in enumerate(loveliness_leaders, 1):
        name = await get_user_display_name(context, uid)
        text += f"{i}. {name}: {score:.1f} loveliness\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Claim daily bonus."""
    user_id = str(update.effective_user.id)
    init_user(user_id)

    user = bot_data["users"][user_id]
    now = time.time()

    if now - user["last_daily_bonus"] < DAILY_BONUS_COOLDOWN:
        remaining = DAILY_BONUS_COOLDOWN - (now - user["last_daily_bonus"])
        hours = int(remaining / 3600)
        minutes = int((remaining % 3600) / 60)
        await update.message.reply_text(
            f"💕 Your daily love bonus refreshes in {hours}h {minutes}m!\n"
            f"Come back then for more rewards!"
        )
        return

    # Calculate bonus based on activity and level
    base_bonus = 10
    level_bonus = user["level"] * 2
    streak_bonus = min(user["days_active"], 30)  # Max 30 day streak bonus

    total_bonus = base_bonus + level_bonus + streak_bonus
    xp_bonus = ACTIVITY_XP_DAILY

    user["lover_points"] += total_bonus
    user["total_points_earned"] += total_bonus
    user["xp"] += xp_bonus
    user["total_xp_earned"] = user.get("total_xp_earned", 0) + xp_bonus
    user["last_daily_bonus"] = now

    # Check for level up
    leveled = check_level_up(user_id)

    save_data(bot_data)

    msg = (
        f"💝 **Daily Love Bonus Claimed!** 💝\n\n"
        f"Base: +{base_bonus} points\n"
        f"Level Bonus: +{level_bonus} points\n"
        f"Streak Bonus: +{streak_bonus} points\n"
        f"**Total: +{total_bonus} points**\n\n"
        f"Also gained +{xp_bonus} XP! 💕"
    )

    if leveled:
        msg += f"\n\n🎉 **LEVEL UP!** You're now level {user['level']}!"

    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_wager(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start an open wager that anyone can accept."""
    challenger_id = str(update.effective_user.id)
    init_user(challenger_id)

    # Clean up expired wagers first
    cleanup_expired_wagers()

    # Parse arguments
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "💕 **Create a Love Duel:**\n"
            "/wager <points>\n\n"
            "Anyone with enough points can accept!"
        )
        return

    # Validate points
    try:
        points = float(context.args[0])
        if points <= 0 or points > 1000:
            raise ValueError
        points = round(points, 2)  # Round to 2 decimals
    except ValueError:
        await update.message.reply_text("💔 Points must be between 0.01 and 1000!")
        return

    # Check points
    if bot_data["users"][challenger_id]["lover_points"] < points:
        await update.message.reply_text("💔 You don't have enough Lover Points for this wager!")
        return

    # Create wager
    wager_id = f"wager_{int(time.time())}_{challenger_id[:8]}"
    bot_data["pending_wagers"][wager_id] = {
        "challenger_id": challenger_id,
        "challenger_name": update.effective_user.first_name,
        "points": points,
        "expires_at": time.time() + WAGER_EXPIRY,
        "accepted": False
    }

    # Reserve the points
    bot_data["users"][challenger_id]["lover_points"] -= points
    save_data(bot_data)

    # Create inline keyboard
    keyboard = [[
        InlineKeyboardButton("💘 Accept Duel", callback_data=f"accept_{wager_id}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{wager_id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"💘 **Open Love Duel!** 💘\n\n"
        f"{update.effective_user.first_name} wagered {points:.2f} Lover Points!\n\n"
        f"First person to accept wins or loses it all!\n"
        f"⏰ Expires in 1 minute!",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def cmd_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gift points to another user."""
    giver_id = str(update.effective_user.id)
    init_user(giver_id)

    # Check if replying to a message
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "💝 **Gift Love Points:**\n"
            "Reply to someone's message with:\n"
            "/gift <points>\n\n"
            "Spread the love! 💕"
        )
        return

    # Parse points
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

    # Get recipient
    recipient = update.message.reply_to_message.from_user
    recipient_id = str(recipient.id)

    if recipient_id == giver_id:
        await update.message.reply_text("💝 You can't gift points to yourself!")
        return

    init_user(recipient_id)

    # Check if giver has enough points
    if bot_data["users"][giver_id]["lover_points"] < points:
        await update.message.reply_text(
            f"💔 You only have {bot_data['users'][giver_id]['lover_points']:.2f} points!\n"
            f"You need {points:.2f} to make this gift."
        )
        return

    # Transfer points
    bot_data["users"][giver_id]["lover_points"] -= points
    bot_data["users"][giver_id]["total_points_spent"] += points

    bot_data["users"][recipient_id]["lover_points"] += points
    bot_data["users"][recipient_id]["total_points_earned"] += points

    save_data(bot_data)

    await update.message.reply_text(
        f"💝 **Love Gift Sent!** 💝\n\n"
        f"{update.effective_user.first_name} sent {points:.2f} Lover Points to {recipient.first_name}!\n\n"
        f"What a lovely gesture! 💕",
        parse_mode="Markdown"
    )


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks."""
    query = update.callback_query
    user_id = str(query.from_user.id)

    # Parse callback data
    action, wager_id = query.data.split('_', 1)

    # Check if wager exists
    if wager_id not in bot_data["pending_wagers"]:
        await query.answer("💔 This duel has expired!", show_alert=True)
        await query.edit_message_text("💔 This love duel has expired!")
        return

    wager = bot_data["pending_wagers"][wager_id]

    # Check if expired
    if time.time() > wager["expires_at"]:
        # Refund challenger
        bot_data["users"][wager["challenger_id"]]["lover_points"] += wager["points"]
        del bot_data["pending_wagers"][wager_id]
        save_data(bot_data)
        await query.answer("💔 This duel has expired!", show_alert=True)
        await query.edit_message_text("💔 This love duel expired!")
        return

    if action == "accept":
        # Check if it's the challenger trying to accept their own wager
        if user_id == wager["challenger_id"]:
            await query.answer("💝 You can't accept your own duel!", show_alert=True)
            return

        # Check if already accepted
        if wager["accepted"]:
            await query.answer("💔 Someone already accepted this duel!", show_alert=True)
            return

        init_user(user_id)

        # Check if acceptor has enough points
        if bot_data["users"][user_id]["lover_points"] < wager["points"]:
            await query.answer(
                f"💔 You need {wager['points']:.2f} points to accept this duel!",
                show_alert=True
            )
            return

        # Mark as accepted
        wager["accepted"] = True

        # Execute the duel
        challenger_id = wager["challenger_id"]
        points = wager["points"]

        # Calculate XP for both parties based on wager size and loveliness
        challenger_loveliness = calculate_loveliness_score(challenger_id)
        acceptor_loveliness = calculate_loveliness_score(user_id)

        challenger_xp = int(points * WAGER_XP_MULTIPLIER * (1 + challenger_loveliness / 100))
        acceptor_xp = int(points * WAGER_XP_MULTIPLIER * (1 + acceptor_loveliness / 100))

        # Award XP to both parties
        bot_data["users"][challenger_id]["xp"] += challenger_xp
        bot_data["users"][challenger_id]["total_xp_earned"] += challenger_xp
        bot_data["users"][user_id]["xp"] += acceptor_xp
        bot_data["users"][user_id]["total_xp_earned"] += acceptor_xp

        # 50/50 chance
        winner_id = random.choice([challenger_id, user_id])
        loser_id = user_id if winner_id == challenger_id else challenger_id

        # Transfer points
        bot_data["users"][winner_id]["lover_points"] += points * 2  # Get their bet back + winnings
        bot_data["users"][winner_id]["wagers_won"] += 1
        bot_data["users"][winner_id]["total_points_earned"] += points

        bot_data["users"][loser_id]["lover_points"] -= points
        bot_data["users"][loser_id]["wagers_lost"] += 1
        bot_data["users"][loser_id]["total_points_spent"] += points

        # Check for level ups
        challenger_leveled = check_level_up(challenger_id)
        acceptor_leveled = check_level_up(user_id)

        # Remove wager
        del bot_data["pending_wagers"][wager_id]
        save_data(bot_data)

        winner_name = wager["challenger_name"] if winner_id == challenger_id else query.from_user.first_name
        loser_name = query.from_user.first_name if winner_id == challenger_id else wager["challenger_name"]

        result_text = (
            f"💘 **Love Duel Results!** 💘\n\n"
            f"The arrows of love favor **{winner_name}**!\n"
            f"They win {points:.2f} points from {loser_name}!\n\n"
            f"**XP Gained:**\n"
            f"├ {wager['challenger_name']}: +{challenger_xp} XP\n"
            f"└ {query.from_user.first_name}: +{acceptor_xp} XP\n\n"
            f"💕 Love is a game of chance! 💕"
        )

        if challenger_leveled or acceptor_leveled:
            result_text += "\n\n🎉 **LEVEL UP!** 🎉"
            if challenger_leveled:
                result_text += f"\n{wager['challenger_name']} → Level {bot_data['users'][challenger_id]['level']}"
            if acceptor_leveled:
                result_text += f"\n{query.from_user.first_name} → Level {bot_data['users'][user_id]['level']}"

        await query.answer("💘 Duel complete!", show_alert=False)
        await query.edit_message_text(result_text, parse_mode="Markdown")

    elif action == "cancel":
        # Only challenger can cancel
        if user_id != wager["challenger_id"]:
            await query.answer("💔 Only the challenger can cancel!", show_alert=True)
            return

        # Refund points
        bot_data["users"][wager["challenger_id"]]["lover_points"] += wager["points"]
        del bot_data["pending_wagers"][wager_id]
        save_data(bot_data)

        await query.answer("💔 Duel cancelled!", show_alert=False)
        await query.edit_message_text("💔 Love duel was cancelled by the challenger.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message."""
    help_text = """
💕 **Cupid Bot - Viral Growth Edition** 💕

**Core Commands:**
/invite - Get your shareable love link
/newinvite - Generate fresh link (deactivates old)
/myprofile - View stats, level, heat score
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
- Invite success: 1 point (+ streak bonus!)
- Cascade: 0.5, 0.25, 0.125... up the tree
- Daily bonus: 10-50+ points
- Wagers: Win/lose points + gain XP!

**XP & Levels:**
- Messages: 1 XP (30s cooldown)
- Wagers: XP based on bet × loveliness
- Daily: 50 XP
- Level up = prestige!

**Pro Tips:**
💡 Share your link on socials for viral growth
💡 Build streaks for multiplied rewards
💡 Higher loveliness = more XP from wagers
💡 Gift points to build alliances

Let's make this chat EXPLODE! 🚀💘
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics."""
    total_users = len(bot_data["users"])
    total_invites = len(bot_data["invites"])
    successful_invites = sum(1 for inv in bot_data["invites"].values() if inv["used"])
    total_points = sum(u["lover_points"] for u in bot_data["users"].values())
    total_messages = sum(u["messages_sent"] for u in bot_data["users"].values())
    active_wagers = len(bot_data["pending_wagers"])

    stats = (
        f"💘 **Cupid Bot Statistics** 💘\n\n"
        f"👥 Total Users: {total_users}\n"
        f"💌 Total Invites: {total_invites}\n"
        f"✅ Successful: {successful_invites}\n"
        f"💝 Total Points: {total_points:.1f}\n"
        f"💬 Total Messages: {total_messages}\n"
        f"⚔️ Active Duels: {active_wagers}\n"
    )

    await update.message.reply_text(stats, parse_mode="Markdown")


async def cmd_resetleaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset all points (admin only)."""
    # Add admin check here if needed
    for user_id in bot_data["users"]:
        bot_data["users"][user_id]["lover_points"] = 0
        bot_data["users"][user_id]["total_points_earned"] = 0
        bot_data["users"][user_id]["total_points_spent"] = 0
        bot_data["users"][user_id]["wagers_won"] = 0
        bot_data["users"][user_id]["wagers_lost"] = 0

    save_data(bot_data)
    await update.message.reply_text("💕 All Lover Points have been reset! Fresh start for everyone!")


##############################################################################
#                        MESSAGE HANDLERS
##############################################################################
async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle private messages for verification."""
    user_id = str(update.effective_user.id)
    init_user(user_id)

    text = update.message.text.strip()

    # Check for verification
    verified, invite_code = verify_answer(user_id, text)

    if verified and invite_code:
        invite_data = bot_data["invites"][invite_code]

        # Check if user already joined through an invite
        if user_id in bot_data["relationships"]:
            await update.message.reply_text(
                "💕 You're already part of the Love Network!\n"
                "Spread your own love with /invite!"
            )
            return

        try:
            # Create one-time invite link for this specific user
            group_id = invite_data["group_id"]
            inviter_id = invite_data["inviter_id"]

            link = await context.bot.create_chat_invite_link(
                chat_id=group_id,
                name=f"Love Invite - {user_id[:8]}",
                member_limit=1,
                creates_join_request=False
            )

            # Track this specific use
            invite_data["total_uses"] = invite_data.get("total_uses", 0) + 1

            # Add to used_by list instead of single user
            if "used_by_list" not in invite_data:
                invite_data["used_by_list"] = []
            invite_data["used_by_list"].append(user_id)

            # Create relationship
            bot_data["relationships"][user_id] = inviter_id

            save_data(bot_data)

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

    elif not verified and user_id in bot_data["verifications"]:
        attempts = bot_data["verifications"][user_id]["attempts"]
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
    else:
        # Track activity for private messages too
        leveled = track_activity(user_id)
        if leveled:
            await update.message.reply_text(
                f"🎉 **LEVEL UP!** You reached level {bot_data['users'][user_id]['level']}! 🎉"
            )


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track activity in groups."""
    if update.effective_user:
        user_id = str(update.effective_user.id)
        init_user(user_id)

        # Track activity
        leveled = track_activity(user_id)

        # Notify level up in group (rare enough to not spam)
        if leveled:
            user = bot_data["users"][user_id]
            await update.message.reply_text(
                f"🎉 {update.effective_user.first_name} reached **Level {user['level']}** in the Love Network! 🎉",
                parse_mode="Markdown"
            )


async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new members joining."""
    group_id = update.effective_chat.id

    for member in update.message.new_chat_members:
        user_id = str(member.id)
        init_user(user_id)

        # Check if they joined through an invite
        if user_id in bot_data["relationships"]:
            inviter_id = bot_data["relationships"][user_id]

            # Update invite streak
            update_invite_streak(inviter_id)

            # Award points with cascade
            award_points_cascade(inviter_id, INVITE_BASE_POINTS)

            # Update inviter stats
            bot_data["users"][inviter_id]["invites_successful"] += 1

            # Check for milestones
            await check_milestones(inviter_id, context, group_id)

            save_data(bot_data)

            # Welcome message with heat indicator
            heat = calculate_heat_score(inviter_id)
            heat_emoji = "🔥" * min(int(heat / 10), 5) if heat > 0 else ""

            await update.message.reply_text(
                f"💕 Welcome {member.first_name} to the Love Network! 💕\n"
                f"You were invited by a special Cupid! {heat_emoji}\n"
                f"Use /help to learn how to spread the love!",
                parse_mode="Markdown"
            )


async def handle_member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle members leaving."""
    member = update.chat_member.new_chat_member.user
    user_id = str(member.id)

    # If they were invited, deduct some points from inviter
    if user_id in bot_data["relationships"]:
        inviter_id = bot_data["relationships"][user_id]
        if inviter_id in bot_data["users"]:
            # Deduct half point (since base is now 1)
            penalty = 0.5
            bot_data["users"][inviter_id]["lover_points"] -= penalty
            bot_data["users"][inviter_id]["lover_points"] = max(0, bot_data["users"][inviter_id]["lover_points"])

            # Reduce their heat score
            bot_data["users"][inviter_id]["heat_score"] = calculate_heat_score(inviter_id)

            save_data(bot_data)


##############################################################################
#                           MAIN BOT
##############################################################################
def main():
    """Run the bot."""
    app = ApplicationBuilder().token(API_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("invite", cmd_invite))
    app.add_handler(CommandHandler("newinvite", cmd_newinvite))
    app.add_handler(CommandHandler("myprofile", cmd_myprofile))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("gift", cmd_gift))
    app.add_handler(CommandHandler("wager", cmd_wager))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("resetleaderboard", cmd_resetleaderboard))

    # Callback query handler for buttons
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Message handlers
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        handle_private_message
    ))

    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
        handle_group_message
    ))

    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        handle_new_member
    ))

    app.add_handler(ChatMemberHandler(
        handle_member_left,
        ChatMemberHandler.CHAT_MEMBER
    ))

    logger.info("💕 Cupid Bot V2 - Viral Growth Edition is spreading love! 💕")
    app.run_polling()


if __name__ == "__main__":
    main()