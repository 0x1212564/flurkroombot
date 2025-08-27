#!/usr/bin/env python3
"""
Roombot - Main Application
A refactored Telegram bot with MySQL database integration.
"""

import logging
import asyncio
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    CallbackQueryHandler,
    filters
)

# Import our modules
from config import Config
from database import DatabaseManager
from user_manager import UserManager
from invite_manager import InviteManager
from handlers import CommandHandlers
from callbacks import CallbackHandlers
from message_handlers import MessageHandlers

# Setup logging
logging.basicConfig(
    format=Config.LOG_FORMAT,
    level=getattr(logging, Config.LOG_LEVEL.upper())
)
logger = logging.getLogger(__name__)


class RoombotApplication:
    def __init__(self):
        self.db = None
        self.user_manager = None
        self.invite_manager = None
        self.command_handlers = None
        self.callback_handlers = None
        self.message_handlers = None
        self.application = None

    async def initialize(self):
        """Initialize all components."""
        try:
            # Validate configuration
            Config.validate_config()

            # Initialize database
            logger.info("Initializing database connection...")
            db_config = Config.get_db_config()
            self.db = DatabaseManager(**db_config)

            # Initialize managers
            logger.info("Initializing managers...")
            self.user_manager = UserManager(self.db)
            self.invite_manager = InviteManager()

            # Initialize handlers
            logger.info("Initializing handlers...")
            self.command_handlers = CommandHandlers(self.user_manager, self.invite_manager)
            self.callback_handlers = CallbackHandlers(self.user_manager, self.invite_manager)
            self.message_handlers = MessageHandlers(self.user_manager, self.invite_manager)

            # Initialize Telegram application
            logger.info("Initializing Telegram application...")
            self.application = ApplicationBuilder().token(Config.BOT_TOKEN).build()

            # Register handlers
            self._register_handlers()

            logger.info("✅ All components initialized successfully")

        except Exception as e:
            logger.error(f"❌ Failed to initialize application: {e}")
            raise

    def _register_handlers(self):
        """Register all bot handlers."""
        app = self.application

        # Command handlers
        app.add_handler(CommandHandler("start", self.command_handlers.cmd_start))
        app.add_handler(CommandHandler("invite", self.command_handlers.cmd_invite))
        app.add_handler(CommandHandler("newinvite", self.command_handlers.cmd_newinvite))
        app.add_handler(CommandHandler("profile", self.command_handlers.cmd_profile))
        app.add_handler(CommandHandler("leaderboard", self.command_handlers.cmd_leaderboard))
        app.add_handler(CommandHandler("daily", self.command_handlers.cmd_daily))
        app.add_handler(CommandHandler("wager", self.command_handlers.cmd_wager))
        app.add_handler(CommandHandler("gift", self.command_handlers.cmd_gift))
        app.add_handler(CommandHandler("help", self.command_handlers.cmd_help))
        app.add_handler(CommandHandler("stats", self.command_handlers.cmd_stats))

        # Callback query handler
        app.add_handler(CallbackQueryHandler(self.callback_handlers.handle_callback_query))

        # Message handlers
        app.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            self.message_handlers.handle_private_message
        ))

        app.add_handler(MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            self.message_handlers.handle_group_message
        ))

        app.add_handler(MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            self.message_handlers.handle_new_member
        ))

        app.add_handler(ChatMemberHandler(
            self.message_handlers.handle_member_left,
            ChatMemberHandler.CHAT_MEMBER
        ))

        logger.info("✅ All handlers registered")

    async def start_cleanup_task(self):
        """Start periodic cleanup task."""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                # Cleanup expired verifications
                self.user_manager.cleanup_expired_data()

                # Cleanup expired wagers and refund points
                expired_wagers = self.invite_manager.cleanup_expired_wagers()
                for expired in expired_wagers:
                    if not expired.get('accepted', False):
                        self.user_manager.award_points(
                            expired['challenger_id'],
                            expired['points'],
                            "wager refund"
                        )

                if expired_wagers:
                    logger.info(f"Cleaned up {len(expired_wagers)} expired wagers")

            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")

    async def run(self):
        """Run the bot."""
        try:
            await self.initialize()

            # Start cleanup task
            cleanup_task = asyncio.create_task(self.start_cleanup_task())

            logger.info("🚀 Starting Roombot - Love Network Edition!")
            logger.info(f"Bot username will be available after start")

            # Start the bot
            await self.application.run_polling(
                drop_pending_updates=True,
                close_loop=False
            )

        except KeyboardInterrupt:
            logger.info("👋 Shutting down gracefully...")
        except Exception as e:
            logger.error(f"❌ Critical error: {e}")
            raise
        finally:
            # Cleanup
            if hasattr(self, 'cleanup_task'):
                cleanup_task.cancel()
            if self.db:
                self.db.disconnect()
            logger.info("✅ Cleanup completed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.db:
            self.db.disconnect()


async def main():
    """Main function."""
    try:
        app = RoombotApplication()
        await app.run()
    except Exception as e:
        logger.error(f"❌ Application failed to start: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())