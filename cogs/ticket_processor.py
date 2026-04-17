import discord
from discord.ext import commands
import json
import aiohttp
import os
import re
import base64
from datetime import datetime, timezone

class TicketProcessor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_channel_id = 1468832805713875159  # Replace with your Channel ID
        self.json_file = "tickets.json"

    def load_database(self):
        if not os.path.exists(self.json_file):
            return {}
        try:
            with open(self.json_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}

    @commands.command(name="process_tickets")
    @commands.has_permissions(administrator=True)
    async def process_tickets(self, ctx):
        channel = self.bot.get_channel(self.target_channel_id)
        if not channel:
            return await ctx.send("❌ Target channel not found.")

        database = self.load_database()

        await ctx.send(f"🔍 Scanning channel... Found {len(database)} unique tickets in the database.\n⚡ Processing new tickets at native speed...")

        processed_count = 0
        skipped_count = 0
        
        async for message in channel.history(limit=None):
            for attachment in message.attachments:
                # Check for either HTML or JSON
                is_html = attachment.filename.endswith('.html')
                is_json = attachment.filename.endswith('.json')
                
                if not (is_html or is_json):
                    continue

                # Strip out extensions to get the clean ticket key
                ticket_key = attachment.filename.replace("transcript-", "").replace(".html", "").replace(".json", "")
                
                if ticket_key in database:
                    skipped_count += 1
                    continue 
                
                # Route to the correct processor based on file type
                if is_html:
                    success, extracted_data = await self.handle_html_file(ctx, attachment, ticket_key)
                elif is_json:
                    success, extracted_data = await self.handle_json_file(ctx, attachment, ticket_key)
                
                if success:
                    database[ticket_key] = extracted_data
                    self.save_to_json(ticket_key, extracted_data)
                    processed_count += 1
        
        await ctx.send(f"🎉 All done! Processed {processed_count} new tickets (Skipped {skipped_count} duplicates).")

    # ==========================================
    # HTML PROCESSOR (ORIGINAL)
    # ==========================================
    async def handle_html_file(self, ctx, attachment, exact_ticket_name):
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status != 200:
                    return False, None
                html_content = await resp.text()

        match = re.search(r'let messages = "(.*?)";', html_content)
        
        if not match:
            await ctx.send(f"❌ Failed to find Ticket Tool data in `{attachment.filename}`.")
            return False, None

        try:
            base64_data = match.group(1)
            decoded_text = base64.b64decode(base64_data).decode('utf-8')
            raw_ticket_data = json.loads(decoded_text)
        except Exception as e:
            print(f"Decode/JSON Error in {attachment.filename}: {e}")
            await ctx.send(f"❌ Failed to decode `{attachment.filename}`.")
            return False, None

        chat_log = []
        ticket_creator = "Unknown"
        ticket_resolver = "Unknown"

        for msg in raw_ticket_data:
            if not msg.get("bot", False):
                ticket_creator = msg.get("username", "Unknown")
                break

        for msg in raw_ticket_data:
            sender = "Ticket Tool" if msg.get("bot") else msg.get("username", "Unknown")
            
            ts_ms = msg.get("created", 0)
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            timestamp_iso = dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

            content = msg.get("content", "") or ""
            discord_data = msg.get("discordData", {})

            def replace_mention(m):
                user_id = m.group(1)
                if user_id in discord_data and "name" in discord_data[user_id]:
                    return f"@{discord_data[user_id]['name']}"
                return f"@{user_id}"
            
            content = re.sub(r'<@!?&?(\d+)>', replace_mention, content)

            for embed in msg.get("embeds", []):
                desc = embed.get("description", "") or ""
                desc = re.sub(r'<@!?&?(\d+)>', replace_mention, desc)
                
                if desc.startswith("Reason :") or desc.startswith("Reason:"):
                    chat_log.append({
                        "sender": ticket_creator,
                        "timestamp": timestamp_iso,
                        "message": desc
                    })
                elif "Ticket Closed by" in desc:
                    content += desc if not content else f"\n{desc}"
                    resolver_match = re.search(r'Ticket Closed by @(\S+)', desc)
                    if resolver_match:
                        ticket_resolver = resolver_match.group(1).rstrip('.')
                else:
                    if desc:
                        content += desc if not content else f"\n{desc}"
                        
                for field in embed.get("fields", []):
                    field_text = f"{field.get('name', '')}: {field.get('value', '')}"
                    content += field_text if not content else f"\n{field_text}"

            for att in msg.get("attachments", []):
                filename = att.get("name", "unknown_file")
                att_str = f"[Attachment: {filename}]"
                content += att_str if not content else f"\n{att_str}"

            if content.strip():
                chat_log.append({
                    "sender": sender,
                    "timestamp": timestamp_iso,
                    "message": content.strip()
                })

        if ticket_resolver == "Unknown":
            for msg in reversed(raw_ticket_data):
                if not msg.get("bot", False):
                    ticket_resolver = msg.get("username", "Unknown")
                    break

        extracted_data = {
            "ticket_creator": ticket_creator,
            "ticket_resolver": ticket_resolver,
            "chat_log": chat_log,
            "ticket_name": exact_ticket_name
        }

        await ctx.send(f"✅ Processed and saved: **{exact_ticket_name}** (HTML)")
        return True, extracted_data

    # ==========================================
    # JSON PROCESSOR (NEW)
    # ==========================================
    async def handle_json_file(self, ctx, attachment, exact_ticket_name):
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status != 200:
                    return False, None
                # Using content_type=None in case Discord serves the JSON as text/plain
                raw_json_data = await resp.json(content_type=None)

        chat_log = []
        ticket_creator = "Unknown"
        ticket_resolver = "Unknown"
        
        # 1. Build a dictionary to map user IDs to Usernames dynamically
        id_to_name = {}
        for msg in raw_json_data:
            uid = str(msg.get("author_id"))
            uname = msg.get("author", "Unknown")
            if uid and uname:
                id_to_name[uid] = uname

        # 2. Hunt for Creator and Resolver using bot messages
        for msg in raw_json_data:
            content = msg.get("content", "")
            
            # The bot usually pings the creator in the first message: "Hey <@ID>!"
            if "Hey <@" in content and ticket_creator == "Unknown":
                match = re.search(r'Hey <@!?(\d+)>', content)
                if match:
                    creator_id = match.group(1)
                    ticket_creator = id_to_name.get(creator_id, f"User_{creator_id}")
            
            # The bot usually announces who claimed it: "🙋 <@ID> has claimed this ticket!"
            if "claimed this ticket!" in content and ticket_resolver == "Unknown":
                match = re.search(r'<@!?(\d+)> has claimed', content)
                if match:
                    resolver_id = match.group(1)
                    ticket_resolver = id_to_name.get(resolver_id, f"Staff_{resolver_id}")

        # Fallback if the bot messages were deleted/altered:
        if ticket_creator == "Unknown":
            for msg in raw_json_data:
                author = msg.get("author", "")
                if "bot" not in author.lower() and "#9118" not in author:
                    ticket_creator = author
                    break

        if ticket_resolver == "Unknown":
            for msg in reversed(raw_json_data):
                author = msg.get("author", "")
                if "bot" not in author.lower() and "#9118" not in author and author != ticket_creator:
                    ticket_resolver = author
                    break

        # 3. Process the chat messages natively
        def replace_mention(m):
            user_id = m.group(1)
            if user_id in id_to_name:
                return f"@{id_to_name[user_id]}"
            return f"@{user_id}"

        for msg in raw_json_data:
            content = msg.get("content", "").strip()
            attachments = msg.get("attachments", [])
            
            # Skip empty messages (like the ones the bot generates with no content)
            if not content and not attachments:
                continue 
                
            sender = msg.get("author", "Unknown")
            
            # Format Timestamp: "2026-04-05 05:53:17" -> ISO 8601 string
            raw_ts = msg.get("timestamp", "")
            try:
                dt = datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S")
                # Appending .000Z to keep format identical to the HTML parser
                timestamp_iso = dt.strftime('%Y-%m-%dT%H:%M:%S.000Z') 
            except ValueError:
                timestamp_iso = raw_ts # Fallback if time format randomly changes

            # Resolve <@ID> pings to actual names using our mapped dictionary
            content = re.sub(r'<@!?&?(\d+)>', replace_mention, content)

            # Note attached files if any exist in the array
            for att in attachments:
                content += f"\n[Attachment]" if not content else f"\n[Attachment]"
                
            chat_log.append({
                "sender": sender,
                "timestamp": timestamp_iso,
                "message": content.strip()
            })

        extracted_data = {
            "ticket_creator": ticket_creator,
            "ticket_resolver": ticket_resolver,
            "chat_log": chat_log,
            "ticket_name": exact_ticket_name
        }

        await ctx.send(f"✅ Processed and saved: **{exact_ticket_name}** (JSON)")
        return True, extracted_data

    # ==========================================
    # FILE SAVING
    # ==========================================
    def save_to_json(self, key, data):
        try:
            with open(self.json_file, 'r', encoding='utf-8') as f:
                file_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            file_data = {}
            
        file_data[key] = data
        
        with open(self.json_file, 'w', encoding='utf-8') as f:
            json.dump(file_data, f, indent=4, ensure_ascii=False)

async def setup(bot):
    await bot.add_cog(TicketProcessor(bot))
