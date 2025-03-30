import asyncio
import logging
import json
from typing import Dict, Any, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import os
from datetime import datetime
import html
import re

class TelegramBot:
    def __init__(self, token: str):
        """Initialize the Telegram bot."""
        self.token = token
        self.application = Application.builder().token(token).build()
        self.logger = logging.getLogger(__name__)
        
        # Register handlers
        self.register_handlers()
        
        # Store for analysis results
        self.analysis_store = {}
        
        # Initialize user-specific pagination data storage
        self.pagination_data = {}
        
        # Set session expiry (in seconds)
        self.pagination_session_expiry = 86400  # 24 hour
        
    def register_handlers(self):
        """Register command and callback handlers."""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("latest", self.latest_command))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_handler(CommandHandler("subscribe", self.subscribe_command))
        # self.application.add_handler(CommandHandler("unsubscribe", self.unsubscribe_command))

    # Add these methods to the TelegramBot class
    async def subscribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /subscribe command."""
        user_id = str(update.effective_user.id)
        
        # Import ConfigManager
        from config_manager import ConfigManager
        config_manager = ConfigManager()
        
        # Add user to subscribers
        if config_manager.add_subscriber(user_id):
            await update.message.reply_text(
                "✅ 您已成功订阅更新！"
                "您将定期收到被监控频道的内容摘要。"
            )
        else:
            await update.message.reply_text(
                "您已经订阅了消息聚合。"
            )
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /start command."""
        await update.message.reply_text(
            "👋 欢迎使用消息聚合器！\n\n"
            "目前我可以提供各种 Telegram 频道的内容摘要。\n\n"
            "Commands:\n"
            "/latest - 获取最新摘要\n"
            "/help - 显示帮助信息"
        )
        
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /help command."""
        await update.message.reply_text(
            "📚 消息聚合器 - 帮助\n\n"
            "该机器人汇总来自不同 Telegram 频道的内容，并提供简明摘要。\n\n"
            "Commands:\n"
            "/start - 启动机器人\n"
            "/latest - 获取最新摘要\n"
            "/help - 显示帮助信息"
        )
        
    async def latest_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /latest command."""
        try:
            latest_analysis = self.get_latest_analysis()
            
            if not latest_analysis or "error" in latest_analysis:
                await update.message.reply_text("No recent analysis available. Please try again later.")
                return
                
            # Format and send the summary
            await self.send_analysis_summary(update, latest_analysis)
            
        except Exception as e:
            self.logger.error(f"Error in latest_command: {str(e)}")
            await update.message.reply_text("An error occurred while retrieving the latest analysis.")
            
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks."""
        query = update.callback_query
        await query.answer()
        
        try:
            data = query.data
            
            if data.startswith("prev_") or data.startswith("next_") or data.startswith("page_"):
                # Extract pagination key
                key_part = data.split("_", 1)[1]
                
                # Get user ID for multi-user support
                user_id = query.from_user.id
                
                # Try both user-specific format and legacy format (for backward compatibility)
                user_pagination_key = f"u{user_id}_{key_part}"
                
                # Check if this pagination session exists
                if user_pagination_key in self.pagination_data:
                    pagination_key = user_pagination_key
                elif key_part in self.pagination_data:
                    # Legacy key format support
                    pagination_key = key_part
                else:
                    await query.edit_message_text("Session expired. Please try again.")
                    return
                
                # Verify user ownership of this pagination session
                session_data = self.pagination_data[pagination_key]
                if 'user_id' in session_data and session_data['user_id'] != user_id:
                    await query.answer("This session belongs to another user.", show_alert=True)
                    return
                
                # Update session timestamp to extend expiry
                from datetime import datetime
                session_data['created_at'] = datetime.now().timestamp()
                
                # Update current page based on action
                if data.startswith("prev_"):
                    session_data['current_page'] -= 1
                elif data.startswith("next_"):
                    session_data['current_page'] += 1
                
                # Extract analysis_id from pagination_key
                if "_details_" in pagination_key:
                    analysis_id = pagination_key.split("_details_")[1]
                else:
                    # Fallback for other pagination types
                    analysis_id = pagination_key.split("_")[-1]
                
                # Display the updated page
                await self._display_content_page(query, pagination_key, analysis_id)

            elif data.startswith("back_"):
                # Handle "Back to Summary" button clicks
                analysis_id = data.replace("back_", "")
                self.logger.info(f"Returning to summary for analysis ID: {analysis_id}")
                
                # Remove overly strict validation and instead focus on finding the analysis
                analysis = self.get_analysis_by_id(analysis_id)
                
                if analysis:
                    # Format summary
                    summary = analysis.get("summary", "No summary available.")
                    formatted_summary = html.escape(summary)
                    
                    # Create keyboard with buttons for details and sources
                    keyboard = [
                        [
                            InlineKeyboardButton("View Details", callback_data=f"details_{analysis_id}"),
                            InlineKeyboardButton("View Sources", callback_data=f"sources_{analysis_id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # Edit message to show summary again, using HTML formatting
                    await query.edit_message_text(
                        f"📊 <b>Content Summary</b>\n\n{formatted_summary}",
                        reply_markup=reply_markup,
                        parse_mode="HTML"
                    )
                else:
                    # Improved error message with actionable instructions
                    self.logger.error(f"Analysis not found for ID: {analysis_id}")
                    await query.edit_message_text(
                        "Unable to retrieve the summary. Please use /latest to view the most recent analysis."
                    )

            elif data.startswith("details_"):
                analysis_id = data.replace("details_", "")
                analysis = self.get_analysis_by_id(analysis_id)
                
                if analysis:
                    await self.send_analysis_details(query, analysis)
                else:
                    await query.edit_message_text("Analysis details not found.")
                    
            elif data.startswith("sources_"):
                analysis_id = data.replace("sources_", "")
                analysis = self.get_analysis_by_id(analysis_id)
                
                if analysis and "sources" in analysis:
                    await self.send_analysis_sources(query, analysis)
                else:
                    await query.edit_message_text("Source information not available.")
            
            elif data.startswith("back_"):
                # Handle "Back to Summary" button clicks
                analysis_id = data.replace("back_", "")
                analysis = self.get_analysis_by_id(analysis_id)
                
                if analysis:
                    # Format summary
                    summary = analysis.get("summary", "No summary available.")
                    # Use HTML instead of Markdown for more reliable formatting
                    formatted_summary = html.escape(summary)

                    # Create keyboard with buttons for details and sources
                    keyboard = [
                        [
                            InlineKeyboardButton("View Details", callback_data=f"details_{analysis_id}"),
                            InlineKeyboardButton("View Sources", callback_data=f"sources_{analysis_id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # Edit message to show summary again, using HTML formatting
                    await query.edit_message_text(
                        f"📊 <b>Content Summary</b>\n\n{formatted_summary}",
                        reply_markup=reply_markup,
                        parse_mode="HTML"
                    )
                else:
                    await query.edit_message_text("Summary not found.")
                    
        except Exception as e:
            self.logger.error(f"Error in button_callback: {str(e)}")
            # Provide a simple fallback response without formatting
            await query.edit_message_text("An error occurred while processing your request. Please try again.")

    def _cleanup_expired_pagination_sessions(self):
        """Remove expired pagination sessions to prevent memory leaks."""
        try:
            from datetime import datetime
            current_time = datetime.now().timestamp()
            expired_keys = []
            
            # Find expired sessions
            for key, data in self.pagination_data.items():
                if 'created_at' in data:
                    if current_time - data['created_at'] > self.pagination_session_expiry:
                        expired_keys.append(key)
            
            # Remove expired sessions
            for key in expired_keys:
                del self.pagination_data[key]
                
            if expired_keys:
                self.logger.info(f"Cleaned up {len(expired_keys)} expired pagination sessions")
        except Exception as e:
            self.logger.error(f"Error cleaning up pagination sessions: {str(e)}")

    def sanitize_markdown(self, text: str) -> str:
        """
        Sanitize text for Markdown formatting by properly escaping special characters.
        
        Args:
            text: Text to sanitize
            
        Returns:
            Sanitized text safe for Markdown parsing
        """
        if not text:
            return ""
            
        # Escape Markdown special characters with backslashes
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        
        # Process the text to handle existing markdown-like syntax
        result = ""
        escape_next = False
        
        for char in text:
            if char in special_chars and not escape_next:
                result += "\\" + char
            else:
                result += char
            escape_next = char == "\\" and not escape_next
        
        return result

    def sanitize_markdown_v2(self, text: str) -> str:
        """
        Sanitize text for MarkdownV2 formatting by escaping special characters.
        
        Args:
            text: Text to sanitize
            
        Returns:
            Sanitized text safe for MarkdownV2 parsing
        """
        if not text:
            return ""
            
        # These characters must be escaped in MarkdownV2
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        
        for char in special_chars:
            text = text.replace(char, '\\' + char)
            
        return text
    
    def format_for_telegram(self, text, use_html=True):
        """Format text for Telegram with consistent rules."""
        if not text:
            return ""
        
        # Always use HTML as the preferred format
        if use_html:
            # Escape HTML special characters
            text = html.escape(text)
            
            # Apply simple formatting
            # Bold markdown to HTML
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
            
            # Italic markdown to HTML
            text = re.sub(r'_(.*?)_', r'<i>\1</i>', text)
            
            # Handle bullet points
            text = re.sub(r'^- ', '• ', text, flags=re.MULTILINE)
            
            return text
        else:
            # Plain text fallback - strip markdown
            text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
            text = re.sub(r'_(.*?)_', r'\1', text)
            return text

    async def send_analysis_summary(self, update: Update, analysis: Dict[str, Any]):
        """
        Send a formatted summary of the analysis.
        
        Args:
            update: Telegram update object
            analysis: Analysis data dictionary
        """
        summary = analysis.get("summary", "No summary available.")
        # Sanitize the summary text
        summary = str(summary)
        analysis_id = analysis.get("id", datetime.now().strftime("%Y%m%d%H%M%S"))
        
        # Create keyboard with buttons
        keyboard = [
            [
                InlineKeyboardButton("View Details", callback_data=f"details_{analysis_id}"),
                InlineKeyboardButton("View Sources", callback_data=f"sources_{analysis_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Format the message
        message = f"📊 *Latest Content Summary*\n\n{summary}"
        
        # Send the message
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"  # Use MarkdownV2 for better escaping
        )
    
    def sanitize_html(self, text: str) -> str:
        """Safely prepare text for HTML formatting in Telegram."""
        if not text:
            return ""
        
        # First escape all HTML special characters
        text = html.escape(text)
        
        # Remove or replace problematic sequences
        # Sometimes even escaped sequences can cause issues
        text = text.replace('\n', '<br>')
        
        return text

    async def send_formatted_message(self, query, text, reply_markup=None):
        """Send a message with progressive formatting fallbacks."""
        try:
            # Try with HTML formatting
            await query.edit_message_text(
                text=self.sanitize_html(text),
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception as e1:
            self.logger.warning(f"HTML formatting failed: {str(e1)}")
            try:
                # Fall back to plain text
                await query.edit_message_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=None
                )
            except Exception as e2:
                self.logger.error(f"Plain text fallback also failed: {str(e2)}")
                # Last resort: truncate the message
                await query.edit_message_text(
                    text=text[:3000] + "... (content truncated)",
                    reply_markup=reply_markup,
                    parse_mode=None
                )

    def chunk_text(self, text, max_length=3000):
        """Break text into chunks that won't exceed Telegram's limits."""
        if len(text) <= max_length:
            return [text]
        
        chunks = []
        current_chunk = ""
        
        # Split by paragraphs or sentences
        paragraphs = text.split("\n\n")
        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 > max_length:  # +2 for newlines
                chunks.append(current_chunk)
                current_chunk = para + "\n\n"
            else:
                current_chunk += para + "\n\n"
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks

    async def _display_content_page(self, query, pagination_key, analysis_id):
        """Display a single page of content with navigation controls using HTML formatting."""
        try:
            # Verify the pagination session exists
            if pagination_key not in self.pagination_data:
                await query.edit_message_text("Session expired. Please try again.")
                return
                
            data = self.pagination_data[pagination_key]
            current_page = data['current_page']
            pages = data['pages']
            
            # Store the original analysis_id value for debugging
            original_analysis_id = analysis_id
            
            # More robust extraction of analysis_id from pagination_key if needed
            if pagination_key.startswith("details_"):
                analysis_id = pagination_key[8:]  # Remove "details_" prefix
            elif "_details_" in pagination_key:
                # Handle user-specific pagination keys
                analysis_id = pagination_key.split("_details_")[1]
                
            self.logger.info(f"Navigation: page {current_page+1}/{len(pages)}, using analysis_id '{analysis_id}'")
            
            # Create navigation buttons
            keyboard = []
            nav_row = []
            
            if current_page > 0:
                nav_row.append(InlineKeyboardButton("◀️ Previous", callback_data=f"prev_{pagination_key}"))
            
            nav_row.append(InlineKeyboardButton(f"{current_page+1}/{len(pages)}", callback_data=f"page_{pagination_key}"))
            
            if current_page < len(pages)-1:
                nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"next_{pagination_key}"))
            
            keyboard.append(nav_row)
            keyboard.append([InlineKeyboardButton("Back to Summary", callback_data=f"back_{analysis_id}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Format content with size limits
            header = f"🔍 <b>Detailed Analysis (Page {current_page+1}/{len(pages)})</b>\n\n"
            max_content_length = 3800 - len(header)
            
            html_content = ""
            added_items = 0
            
            for item in pages[current_page]:
                # Remove leading Markdown bullet points before applying formatting
                # This fixes the "• * " duplication issue
                clean_item = item
                if clean_item.startswith('* '):
                    clean_item = clean_item[2:]  # Remove "* " prefix
                elif clean_item.startswith('*'):
                    clean_item = clean_item[1:]  # Remove "*" prefix
                elif clean_item.startswith('- '):
                    clean_item = clean_item[2:]  # Also handle "- " prefix
                    
                # Apply HTML formatting
                safe_item = self.sanitize_html(clean_item)
                item_html = f"• {safe_item}\n\n"
                
                if len(html_content) + len(item_html) > max_content_length:
                    if added_items == 0:
                        # If we can't fit even one item, truncate it
                        available_space = max_content_length - len("• ...(truncated)\n\n")
                        truncated_item = safe_item[:available_space] + "...(truncated)"
                        html_content += f"• {truncated_item}\n\n"
                        added_items += 1
                    break
                
                html_content += formatted_item
                added_items += 1
            
            # Add note if content was truncated
            if added_items < len(pages[current_page]):
                remaining = len(pages[current_page]) - added_items
                html_content += f"<i>...and {remaining} more item(s). Content truncated due to size limits.</i>"
            
            # Combine header and content
            full_message = header + html_content
            
            # Send with HTML parsing
            await query.edit_message_text(
                text=full_message,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            
        except Exception as e:
            self.logger.error(f"Error in _display_content_page: {str(e)}")
            
            try:
                # Plain text fallback
                plain_header = f"🔍 Detailed Analysis (Page {current_page+1}/{len(pages)})\n\n"
                max_content_length = 3800 - len(plain_header)
                
                plain_content = ""
                added_items = 0
                
                for item in pages[current_page]:
                    # Strip markdown and HTML tags for plain text
                    plain_item = re.sub(r'<.*?>', '', item)  # Remove HTML tags
                    plain_item = re.sub(r'[*_~`]', '', plain_item)  # Remove markdown symbols
                    formatted_item = f"• {plain_item}\n\n"
                    
                    if len(plain_content) + len(formatted_item) > max_content_length:
                        if added_items == 0:
                            available_space = max_content_length - len("• ...(truncated)\n\n")
                            truncated_item = plain_item[:available_space] + "...(truncated)"
                            plain_content += f"• {truncated_item}\n\n"
                            added_items += 1
                        break
                    
                    plain_content += formatted_item
                    added_items += 1
                
                full_message = plain_header + plain_content
                
                # Send without formatting
                await query.edit_message_text(
                    text=full_message,
                    reply_markup=reply_markup
                )
                
            except Exception as fallback_error:
                # Minimal fallback
                self.logger.error(f"Plain text fallback also failed: {str(fallback_error)}")
                await query.edit_message_text(
                    text="Content is too large to display properly. Please use navigation buttons or return to summary.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Summary", callback_data=f"back_{analysis_id}")]])
                )

    async def send_analysis_details(self, query, analysis: Dict[str, Any]):
        """Send detailed analysis information with proper formatting."""
        contents = analysis.get("contents", [])
        analysis_id = analysis.get("id", "unknown")
        
        if not contents:
            await query.edit_message_text("No detailed information available.")
            return
        
        # Set up pagination with original content (not pre-converted)
        pagination_key = f"details_{analysis_id}"
        
        # Split content into pages (5 items per page)
        items_per_page = 5
        pages = []
        current_page = []
        
        for i, point in enumerate(contents):
            current_page.append(point)  # Store the original point with markdown
            if (i + 1) % items_per_page == 0:
                pages.append(current_page)
                current_page = []
        
        # Add the last page if it has any items
        if current_page:
            pages.append(current_page)
        
        # If no pages were created (this shouldn't happen if contents has items)
        if not pages:
            await query.edit_message_text("No content available to display.")
            return
        
        # Store pagination data
        self.pagination_data[pagination_key] = {
            'pages': pages,
            'current_page': 0
        }
        
        # Display the first page
        await self._display_content_page(query, pagination_key, analysis_id)

    def _markdown_to_html(self, text: str) -> str:
        """
        Convert markdown formatting to HTML for Telegram.
        
        Args:
            text: Text with markdown formatting
            
        Returns:
            Text with HTML formatting
        """
        if not text:
            return ""
        
        # First escape any HTML special characters to prevent injection
        text = html.escape(text)
        
        # Convert markdown to HTML
        # Bold: **text** or __text__ to <b>text</b>
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'__(.*?)__', r'<b>\1</b>', text)
        
        # Italic: *text* or _text_ to <i>text</i>
        text = re.sub(r'\*((?!\*).+?)\*', r'<i>\1</i>', text)
        text = re.sub(r'_((?!_).+?)_', r'<i>\1</i>', text)
        
        # Strikethrough: ~~text~~ to <s>text</s>
        text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', text)
        
        # Underline: __text__ to <u>text</u> (if not already processed as bold)
        text = re.sub(r'__(.*?)__', r'<u>\1</u>', text)
        
        # Code: `text` to <code>text</code>
        text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
        
        return text
            
    async def send_analysis_sources(self, query, analysis: Dict[str, Any]):
        """
        Send information about the sources used in the analysis.
        
        Args:
            query: Callback query object
            analysis: Analysis data dictionary
        """
        sources = analysis.get("sources", [])
        analysis_id = analysis.get("id", "unknown")
        
        if not sources:
            await query.edit_message_text("No source information available.")
            return
            
        # Format sources
        sources_text = "📚 *Sources*\n\n"
        for i, source in enumerate(sources, 1):
            channel_name = source.get("channel_name", "Unknown")
            message_count = source.get("message_count", 0)
            sources_text += f"{i}. {channel_name}: {message_count} messages\n"
            
        # Create back button
        keyboard = [[InlineKeyboardButton("Back to Summary", callback_data=f"back_{analysis_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send the message
        await query.edit_message_text(
            sources_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
    def get_latest_analysis(self) -> Optional[Dict[str, Any]]:
        """
        Get the latest analysis result.
        
        Returns:
            Latest analysis dictionary or None
        """
        try:
            # Look for the latest analysis file
            analysis_dir = os.path.join(os.getcwd(), "analysis")
            if not os.path.exists(analysis_dir):
                return None
                
            analysis_files = [f for f in os.listdir(analysis_dir) if f.endswith('.json')]
            if not analysis_files:
                return None
                
            # Sort by filename (assuming timestamp-based naming)
            latest_file = sorted(analysis_files)[-1]
            
            with open(os.path.join(analysis_dir, latest_file), 'r', encoding='utf-8') as f:
                analysis = json.load(f)
                
            # Add ID based on filename
            analysis["id"] = latest_file.replace('.json', '')
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"Error getting latest analysis: {str(e)}")
            return None
            
    def get_analysis_by_id(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Get analysis by ID with improved error handling and fallback options."""
        try:
            analysis_path = os.path.join(os.getcwd(), "analysis", f"{analysis_id}.json")
            
            if not os.path.exists(analysis_path):
                self.logger.warning(f"Analysis file not found at path: {analysis_path}")
                
                # Try to find the most recent analysis if the specific one isn't found
                analysis_dir = os.path.join(os.getcwd(), "analysis")
                if os.path.exists(analysis_dir):
                    analysis_files = [f for f in os.listdir(analysis_dir) if f.endswith('.json')]
                    if analysis_files:
                        self.logger.info("Falling back to most recent analysis file")
                        latest_file = sorted(analysis_files)[-1]
                        analysis_path = os.path.join(analysis_dir, latest_file)
                        analysis_id = latest_file.replace('.json', '')
                
                # If still not found after fallback attempt
                if not os.path.exists(analysis_path):
                    return None
                
            with open(analysis_path, 'r', encoding='utf-8') as f:
                analysis = json.load(f)
                
            # Add ID
            analysis["id"] = analysis_id
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"Error getting analysis by ID {analysis_id}: {str(e)}")
            return None
            
    def store_analysis(self, analysis: Dict[str, Any]) -> str:
        """
        Store analysis result and return its ID.
        
        Args:
            analysis: Analysis data
            
        Returns:
            Analysis ID
        """
        try:
            # Create analysis directory if it doesn't exist
            analysis_dir = os.path.join(os.getcwd(), "analysis")
            os.makedirs(analysis_dir, exist_ok=True)
            
            # Generate ID based on timestamp
            analysis_id = datetime.now().strftime("%Y%m%d%H%M%S")
            
            # Add ID to analysis
            analysis["id"] = analysis_id
            
            # Save to file
            with open(os.path.join(analysis_dir, f"{analysis_id}.json"), 'w', encoding='utf-8') as f:
                json.dump(analysis, f, ensure_ascii=False, indent=2)
                
            return analysis_id
            
        except Exception as e:
            self.logger.error(f"Error storing analysis: {str(e)}")
            return None
    
    async def send_analysis_to_users(self, analysis: Dict[str, Any], user_ids: List[str]):
        """
        Send analysis to specified users.
        
        Args:
            analysis: Analysis data
            user_ids: List of user IDs to send to
        """
        for user_id in user_ids:
            try:
                # Store the analysis first
                analysis_id = self.store_analysis(analysis)
                if not analysis_id:
                    continue
                    
                # Format summary
                summary = analysis.get("summary", "No summary available.")
                
                # Option 1: Switch to HTML formatting (recommended)
                import html
                formatted_summary = html.escape(summary)
                
                # Create keyboard with buttons
                keyboard = [
                    [
                        InlineKeyboardButton("View Details", callback_data=f"details_{analysis_id}"),
                        InlineKeyboardButton("View Sources", callback_data=f"sources_{analysis_id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Format the message with HTML
                message = f"📊 <b>New Content Summary</b>\n\n{formatted_summary}"
                
                # Send the message with HTML parsing
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
                
                # Option 2 (alternative): If you prefer to keep using MarkdownV2
                # sanitized_summary = self.sanitize_markdown_v2(summary)
                # message = f"📊 *New Content Summary*\n\n{sanitized_summary}"
                # await self.application.bot.send_message(
                #     chat_id=user_id,
                #     text=message,
                #     reply_markup=reply_markup,
                #     parse_mode="MarkdownV2"
                # )
                    
            except Exception as e:
                self.logger.error(f"Error sending analysis to user {user_id}: {str(e)}")
                
                # Fallback: Send without formatting
                try:
                    await self.application.bot.send_message(
                        chat_id=user_id,
                        text="📊 New Content Summary\n\n" + analysis.get("summary", "No summary available."),
                        reply_markup=reply_markup,
                        parse_mode=None
                    )
                    self.logger.info(f"Sent unformatted fallback message to user {user_id}")
                except Exception as fallback_error:
                    self.logger.error(f"Fallback also failed for user {user_id}: {str(fallback_error)}")
    
    async def start_polling(self):
        """Start the bot in polling mode."""
        # Check if we're using PTB version 20+ or older
        if hasattr(self.application, "run_polling"):
            # For Python-Telegram-Bot v20+
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
        else:
            # For older versions
            await self.application.initialize()
            await self.application.updater.start_polling()
            
    async def stop(self):
        """Stop the bot."""
        if hasattr(self.application, "run_polling"):
            # For Python-Telegram-Bot v20+
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
        else:
            # For older versions
            await self.application.updater.stop()

async def main():
    """Example usage of the TelegramBot."""
    # Replace with your bot token
    bot_token = "YOUR_BOT_TOKEN"
    
    bot = TelegramBot(bot_token)
    
    # Example of creating and sending an analysis  TODO 修正
    sample_analysis = {
        "summary": "This is a sample summary of collected content from various channels.",
        "key_points": [
            "First key point with important information",
            "Second key point discussing trends",
            "Third key point with notable observations"
        ],
        "sources": [
            {"channel_name": "Technology News", "message_count": 15},
            {"channel_name": "Finance Updates", "message_count": 8},
            {"channel_name": "World Events", "message_count": 12}
        ]
    }
    
    # List of user IDs to send analysis to
    user_ids = ["USER_ID_1", "USER_ID_2"]
    
    # Store and send the analysis
    await bot.send_analysis_to_users(sample_analysis, user_ids)
    
    # Start bot polling
    print("Starting bot...")
    await bot.start_polling()
    
    try:
        # Keep the bot running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        # Stop the bot on keyboard interrupt
        await bot.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())