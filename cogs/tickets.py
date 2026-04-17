import discord
import io
import json
import sqlite3
import datetime
import asyncio
import chat_exporter
from github import Github
from discord import app_commands
from discord.ext import commands, tasks
import config

# --- DATABASE LOGIC ---
def init_db():
    with sqlite3.connect("tickets.db") as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS counter (id INTEGER PRIMARY KEY, val INTEGER)")
        cursor.execute("INSERT OR IGNORE INTO counter (id, val) VALUES (1, 100000)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ticket_logs (
                ticket_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                user_name TEXT,
                category TEXT,
                subject TEXT,
                handler_id INTEGER,
                status TEXT,
                timestamp TEXT,
                transcript_url TEXT 
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                ticket_id INTEGER,
                user_id INTEGER,
                rating INTEGER,
                timestamp TEXT
            )
        """)
        conn.commit()

def get_next_id():
    with sqlite3.connect("tickets.db") as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE counter SET val = val + 1 WHERE id = 1")
        cursor.execute("SELECT val FROM counter WHERE id = 1")
        new_id = cursor.fetchone()[0]
        conn.commit()
    return new_id

init_db()

# --- HELPER FUNCTIONS ---
def upload_to_github_sync(thread_name, html_transcript, json_string):
    g = Github(config.GITHUB_TOKEN)
    repo = g.get_repo(config.GITHUB_TICKET_REPO)
    
    html_path = f"html/transcript-{thread_name}.html"
    json_path = f"json/transcript-{thread_name}.json"
    
    repo.create_file(path=html_path, message=f"HTML archive for {thread_name}", content=html_transcript)
    repo.create_file(path=json_path, message=f"JSON archive for {thread_name}", content=json_string)
    
    raw_html_link = f"https://raw.githubusercontent.com/{config.GITHUB_TICKET_REPO}/main/{html_path}"
    return f"https://htmlpreview.github.io/?{raw_html_link}"

async def archive_and_close_ticket(interaction: discord.Interaction, thread: discord.Thread, ticket_id: int):
    # 1. Update Database Status to Closed
    opener_id = None
    with sqlite3.connect("tickets.db") as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE ticket_logs SET status = 'Closed' WHERE ticket_id = ?", (ticket_id,))
        cursor.execute("SELECT user_id FROM ticket_logs WHERE ticket_id = ?", (ticket_id,))
        result = cursor.fetchone()
        if result:
            opener_id = result[0]
        conn.commit()

    # 2. Generate Transcripts
    # We still need the HTML for the GitHub upload so staff can view it visually
    html_transcript = await chat_exporter.export(thread)
    
    chat_log = []
    main_reason = "Unknown"
    additional_details = "Unknown"
    email = "Unknown"
    cohort = "Unknown"
    ticket_opener_mention = f"User ({thread.name})"
    
    async for msg in thread.history(limit=None, oldest_first=True):
        if msg.author == interaction.guild.me and msg.embeds and msg.embeds[0].title == "New Ticket Information":
            embed = msg.embeds[0]
            for field in embed.fields:
                if field.name == "Main Reason": main_reason = field.value
                elif field.name == "Additional Details": additional_details = field.value
                elif field.name == "Registered Email": email = field.value
                elif field.name == "Cohort Name": cohort = field.value
            if msg.mentions: ticket_opener_mention = msg.mentions[0].mention

        chat_log.append({
            "timestamp": msg.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "author": str(msg.author),
            "author_id": msg.author.id,
            "content": msg.content,
            "attachments": [a.url for a in msg.attachments]
        })
        
    json_string = json.dumps(chat_log, indent=4)
    json_bytes = json_string.encode('utf-8')
    
    # Create TWO file objects because discord.File can only be read and sent once.
    user_json_file = discord.File(io.BytesIO(json_bytes), filename=f"transcript-{thread.name}.json")
    staff_json_file = discord.File(io.BytesIO(json_bytes), filename=f"transcript-{thread.name}.json")
    
    # 3. Push to GitHub
    preview_url = None
    if config.GITHUB_TOKEN and config.GITHUB_TICKET_REPO:
        try:
            preview_url = await asyncio.to_thread(upload_to_github_sync, thread.name, html_transcript, json_string)
            with sqlite3.connect("tickets.db") as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE ticket_logs SET transcript_url = ? WHERE ticket_id = ?", (preview_url, ticket_id))
                conn.commit()
        except Exception as e:
            print(f"⚠️ GitHub Upload Error: {e}")

    # 4. DM Transcript File & Feedback to the User
    if opener_id:
        opener = interaction.guild.get_member(opener_id)
        if opener:
            try:
                dm_embed = discord.Embed(
                    title="Your Ticket has been Closed", 
                    description=f"Ticket **{thread.name}** was successfully resolved.\n\n**Reason:** {main_reason}\n\n**How was your support experience?** Please rate it below!\n\n*(A JSON data log of your ticket is attached to this message)*",
                    color=discord.Color.green()
                )
                await opener.send(embed=dm_embed, file=user_json_file, view=FeedbackView(ticket_id))
            except discord.Forbidden:
                pass # User has DMs closed

    # 5. Send Log Embed to Staff Channel
    log_channel = interaction.guild.get_channel(config.TRANSCRIPT_CHANNEL_ID)
    if log_channel:
        safe_reason = main_reason[:1020] + "..." if len(main_reason) > 1024 else main_reason
        safe_details = additional_details[:1020] + "..." if len(additional_details) > 1024 else additional_details

        preview_embed = discord.Embed(
            title=f"🔒 Ticket Closed: {thread.name}",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        preview_embed.add_field(name="Opened By", value=ticket_opener_mention, inline=True)
        preview_embed.add_field(name="Closed By", value=interaction.user.mention, inline=True)
        preview_embed.add_field(name="\u200b", value="\u200b", inline=True) # Blank field for alignment
        
        preview_embed.add_field(name="Registered Email", value=email, inline=True)
        preview_embed.add_field(name="Cohort Name", value=cohort, inline=True)
        preview_embed.add_field(name="\u200b", value="\u200b", inline=True) # Blank field for alignment
        
        preview_embed.add_field(name="Main Reason", value=safe_reason, inline=False)
        preview_embed.add_field(name="Additional Details", value=safe_details, inline=False)
        
        log_view = discord.ui.View()
        if preview_url:
            log_view.add_item(discord.ui.Button(label="View Visual Transcript", url=preview_url, style=discord.ButtonStyle.link, emoji="🌐"))
        
        await log_channel.send(embed=preview_embed, file=staff_json_file, view=log_view)
    
    # 6. Delete Thread
    await thread.delete()

# --- UI CLASSES ---
class FeedbackView(discord.ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=86400) # Valid for 24 hours
        self.ticket_id = ticket_id

    async def log_feedback(self, interaction: discord.Interaction, rating: int):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO feedback (ticket_id, user_id, rating, timestamp) VALUES (?, ?, ?, ?)",
                (self.ticket_id, interaction.user.id, rating, timestamp)
            )
            conn.commit()

        for child in self.children:
            child.disabled = True
            
        await interaction.response.edit_message(content=f"🌟 Thank you! You rated this support experience **{rating} Stars**.", view=self, embed=None)

    @discord.ui.button(label="1 ⭐", style=discord.ButtonStyle.secondary)
    async def star_1(self, interaction: discord.Interaction, button: discord.ui.Button): await self.log_feedback(interaction, 1)

    @discord.ui.button(label="2 ⭐", style=discord.ButtonStyle.secondary)
    async def star_2(self, interaction: discord.Interaction, button: discord.ui.Button): await self.log_feedback(interaction, 2)

    @discord.ui.button(label="3 ⭐", style=discord.ButtonStyle.secondary)
    async def star_3(self, interaction: discord.Interaction, button: discord.ui.Button): await self.log_feedback(interaction, 3)

    @discord.ui.button(label="4 ⭐", style=discord.ButtonStyle.secondary)
    async def star_4(self, interaction: discord.Interaction, button: discord.ui.Button): await self.log_feedback(interaction, 4)

    @discord.ui.button(label="5 ⭐", style=discord.ButtonStyle.success)
    async def star_5(self, interaction: discord.Interaction, button: discord.ui.Button): await self.log_feedback(interaction, 5)


class ConfirmCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Confirm Close & Save", style=discord.ButtonStyle.danger, custom_id="confirm_close_btn")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Archiving transcripts and closing... ⏳", ephemeral=True)
        ticket_id = int(interaction.channel.name.split('-')[-1])
        await archive_and_close_ticket(interaction, interaction.channel, ticket_id)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="cancel_close_btn")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()

class EscalateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        user_select = discord.ui.UserSelect(placeholder="Select a staff member to escalate to...", max_values=1, custom_id="escalate_select_menu")
        user_select.callback = self.escalate_callback
        self.add_item(user_select)

    async def escalate_callback(self, interaction: discord.Interaction):
        new_handler = self.children[0].values[0]
        ticket_id = int(interaction.channel.name.split('-')[-1])
        
        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE ticket_logs SET handler_id = ? WHERE ticket_id = ?", (new_handler.id, ticket_id))
            conn.commit()

        await interaction.channel.add_user(new_handler)
        await interaction.response.send_message(f"✅ Ticket has been escalated to {new_handler.mention} by {interaction.user.mention}.")

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.success, custom_id="claim_ticket_btn")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [config.SUPPORT_USER_1_ID, config.SUPPORT_USER_2_ID]:
            return await interaction.response.send_message("❌ Only designated support handlers can claim tickets.", ephemeral=True)

        try:
            ticket_id = int(interaction.channel.name.split('-')[-1])
            with sqlite3.connect("tickets.db") as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE ticket_logs SET handler_id = ?, status = 'In Progress' WHERE ticket_id = ?", (interaction.user.id, ticket_id))
                conn.commit()

            if interaction.user.id == config.SUPPORT_USER_1_ID:
                user2 = interaction.guild.get_member(config.SUPPORT_USER_2_ID)
                if user2: await interaction.channel.remove_user(user2)
            elif interaction.user.id == config.SUPPORT_USER_2_ID:
                user1 = interaction.guild.get_member(config.SUPPORT_USER_1_ID)
                if user1: await interaction.channel.remove_user(user1)

            button.disabled = True
            button.label = f"Claimed by {interaction.user.display_name}"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(f"🙋 {interaction.user.mention} has claimed this ticket!", ephemeral=False)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Error claiming ticket: {e}", ephemeral=True)

    @discord.ui.button(label="Escalate", style=discord.ButtonStyle.primary, custom_id="escalate_btn")
    async def escalate_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_id = int(interaction.channel.name.split('-')[-1])
        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT handler_id FROM ticket_logs WHERE ticket_id = ?", (ticket_id,))
            result = cursor.fetchone()

        if not result or result[0] != interaction.user.id:
            return await interaction.response.send_message("❌ Only the staff member who claimed this ticket can escalate it.", ephemeral=True)
            
        await interaction.response.send_message("Who would you like to escalate this ticket to?", view=EscalateView(), ephemeral=True)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red, custom_id="init_close_btn")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⚠️ Are you sure you want to close this ticket?", view=ConfirmCloseView())

class TicketForm(discord.ui.Modal):
    def __init__(self, category_name, role_id):
        self.category_name = category_name
        self.role_id = role_id
        super().__init__(title=f"Open {category_name} Ticket")

    email = discord.ui.TextInput(
        label="Registered Email", 
        style=discord.TextStyle.short, 
        placeholder="your.email@example.com",
        required=True
    )
    
    cohort = discord.ui.TextInput(
        label="Cohort Name", 
        style=discord.TextStyle.short, 
        placeholder="e.g., AKSian",
        required=True
    )

    reason = discord.ui.TextInput(label="What is the main reason for this ticket?", style=discord.TextStyle.short, required=True)
    details = discord.ui.TextInput(label="Please provide additional details:", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM ticket_logs WHERE user_id = ? AND status IN ('Open', 'In Progress')", (interaction.user.id,))
            open_tickets = cursor.fetchone()[0]

        if open_tickets >= 5:
            return await interaction.response.send_message("❌ You already have an active ticket. Please wait for it to be resolved before opening another one.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        ticket_id = get_next_id()
        
        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO ticket_logs (ticket_id, user_id, user_name, category, subject, status, timestamp, transcript_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ticket_id, interaction.user.id, interaction.user.name, self.category_name, self.reason.value, "Open", str(datetime.datetime.now()), None)
            )
            conn.commit()

        parent_channel = interaction.guild.get_channel(config.TICKET_CHANNEL_ID)
        thread_name = f"{self.category_name.lower().replace(' ', '-')}-{interaction.user.name.lower().replace(' ', '')[:15]}-{ticket_id}"
        
        ticket_thread = await parent_channel.create_thread(name=thread_name, type=discord.ChannelType.private_thread, invitable=False)
        
        await ticket_thread.add_user(interaction.user)
        user1 = interaction.guild.get_member(config.SUPPORT_USER_1_ID)
        user2 = interaction.guild.get_member(config.SUPPORT_USER_2_ID)
        if user1: await ticket_thread.add_user(user1)
        if user2: await ticket_thread.add_user(user2)

        embed = discord.Embed(title="New Ticket Information", color=discord.Color.green())
        embed.add_field(name="Ticket ID", value=f"#{ticket_id}", inline=False)
        embed.add_field(name="Registered Email", value=self.email.value, inline=False)
        embed.add_field(name="Cohort Name", value=self.cohort.value, inline=False)
        embed.add_field(name="Main Reason", value=self.reason.value, inline=False)
        embed.add_field(name="Additional Details", value=self.details.value, inline=False)
        
        staff_role = interaction.guild.get_role(self.role_id)
        mention_str = staff_role.mention if staff_role else ""
        
        await ticket_thread.send(content=f"Hey {interaction.user.mention}! {mention_str}\nA staff member will be with you shortly.", embed=embed, view=CloseTicketView())
        await interaction.followup.send(f"✅ Ticket created: {ticket_thread.mention}", ephemeral=True)

class CategorySelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=cat, value=cat) for cat in config.ROLE_MAPPING.keys()]
        super().__init__(placeholder="Select Category...", options=options, custom_id="category_select_menu")
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TicketForm(self.values[0], config.ROLE_MAPPING.get(self.values[0])))

class CategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CategorySelect())

class TicketLauncher(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Create Ticket", style=discord.ButtonStyle.blurple, custom_id="ticket_launch_btn")
    async def ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(view=CategoryView(), ephemeral=True)

# --- COG COMMANDS ---
class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @app_commands.command(name="force_claim", description="Force claim this ticket, bypassing handler restrictions (Admin Only)")
    @app_commands.describe(handler="The staff member to assign this ticket to (defaults to yourself)")
    @app_commands.default_permissions(administrator=True)
    async def force_claim(self, interaction: discord.Interaction, handler: discord.Member = None):
        if not isinstance(interaction.channel, discord.Thread):
            return await interaction.response.send_message("❌ This command can only be used inside a ticket thread.", ephemeral=True)
            
        try: 
            ticket_id = int(interaction.channel.name.split('-')[-1])
        except ValueError: 
            return await interaction.response.send_message("❌ Could not determine ticket ID from the channel name.", ephemeral=True)

        target_handler = handler or interaction.user

        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE ticket_logs SET handler_id = ?, status = 'In Progress' WHERE ticket_id = ?", (target_handler.id, ticket_id))
            conn.commit()

        await interaction.channel.add_user(target_handler)
        
        if target_handler == interaction.user:
            await interaction.response.send_message(f"🚨 **Admin Override:** {interaction.user.mention} has forcibly claimed this ticket.")
        else:
            await interaction.response.send_message(f"🚨 **Admin Override:** This ticket has been forcibly assigned to {target_handler.mention} by {interaction.user.mention}.")
            
    @app_commands.command(name="view_ratings", description="View staff support ratings and feedback (Admin Only)")
    @app_commands.describe(handler="Select a specific staff member to view their detailed ratings")
    @app_commands.default_permissions(administrator=True)
    async def view_ratings(self, interaction: discord.Interaction, handler: discord.Member = None):
        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            
            if handler:
                cursor.execute("""
                    SELECT AVG(f.rating), COUNT(f.rating)
                    FROM feedback f
                    JOIN ticket_logs t ON f.ticket_id = t.ticket_id
                    WHERE t.handler_id = ?
                """, (handler.id,))
                stats = cursor.fetchone()
                
                if not stats or stats[1] == 0:
                    return await interaction.response.send_message(f"📊 **{handler.display_name}** has not received any ratings yet.", ephemeral=True)
                
                avg_rating = round(stats[0], 2)
                total_ratings = stats[1]
                
                cursor.execute("""
                    SELECT f.ticket_id, f.rating, t.user_name, f.timestamp
                    FROM feedback f
                    JOIN ticket_logs t ON f.ticket_id = t.ticket_id
                    WHERE t.handler_id = ?
                    ORDER BY f.timestamp DESC LIMIT 10
                """, (handler.id,))
                recent_feedbacks = cursor.fetchall()
                
                embed = discord.Embed(title=f"📊 Rating Overview: {handler.display_name}", color=discord.Color.gold())
                embed.add_field(name="Average Rating", value=f"{avg_rating} ⭐", inline=True)
                embed.add_field(name="Total Reviews", value=str(total_ratings), inline=True)
                
                if recent_feedbacks:
                    feedback_str = ""
                    for fb in recent_feedbacks:
                        t_id, rating, u_name, timestamp = fb
                        stars = "⭐" * rating
                        date_short = timestamp[:10]
                        feedback_str += f"**#{t_id}** | {stars} | User: {u_name} ({date_short})\n"
                    embed.add_field(name="Recent Feedback (Last 10)", value=feedback_str, inline=False)
                    
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
            else:
                cursor.execute("""
                    SELECT t.handler_id, AVG(f.rating), COUNT(f.rating)
                    FROM feedback f
                    JOIN ticket_logs t ON f.ticket_id = t.ticket_id
                    WHERE t.handler_id IS NOT NULL
                    GROUP BY t.handler_id
                    ORDER BY AVG(f.rating) DESC, COUNT(f.rating) DESC
                """)
                leaderboard = cursor.fetchall()
                
                if not leaderboard:
                    return await interaction.response.send_message("📊 No feedback has been submitted across the server yet.", ephemeral=True)
                
                embed = discord.Embed(
                    title="🏆 Staff Rating Leaderboard", 
                    description="Average support ratings based on user feedback.", 
                    color=discord.Color.gold()
                )
                
                for rank, row in enumerate(leaderboard, 1):
                    h_id, avg_r, count_r = row
                    avg_r_rounded = round(avg_r, 2)
                    handler_mention = f"<@{h_id}>"
                    embed.add_field(
                        name=f"#{rank} - {avg_r_rounded} ⭐", 
                        value=f"{handler_mention} ({count_r} reviews)", 
                        inline=False
                    )
                
                await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setup", description="Deploy the Ticket Panel (Admin Only)")
    @app_commands.default_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Support Center", description="Click the button below to open a ticket.", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, view=TicketLauncher())

    @app_commands.command(name="open_tickets", description="View all currently active tickets (Staff Only)")
    @app_commands.default_permissions(manage_messages=True)
    async def open_tickets(self, interaction: discord.Interaction):
        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ticket_id, user_name, category, subject, status, handler_id FROM ticket_logs WHERE status != 'Closed'")
            active_tickets = cursor.fetchall()

        if not active_tickets:
            await interaction.response.send_message("🎉 There are no active tickets! Great job team.", ephemeral=True)
            return

        embed = discord.Embed(title="📋 Active Support Tickets", color=discord.Color.orange())
        for ticket in active_tickets:
            t_id, u_name, cat, subj, status, h_id = ticket
            handler = f"<@{h_id}>" if h_id else "Unclaimed"
            embed.add_field(name=f"Ticket #{t_id} | {cat}", value=f"**User:** {u_name}\n**Reason:** {subj}\n**Status:** {status}\n**Handler:** {handler}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="backup_db", description="Force a backup of the tickets database (Admin Only)")
    @app_commands.default_permissions(administrator=True)
    async def backup_db(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db_file = discord.File("tickets.db", filename=f"tickets_backup_{datetime.date.today()}.db")
        await interaction.followup.send("✅ Here is your database backup. Keep it safe!", file=db_file, ephemeral=True)

    @app_commands.command(name="search_tickets", description="Search the ticket database (Staff Only)")
    @app_commands.describe(ticket_id="Specific 6-digit Ticket ID", user="The user who opened the ticket", handler="The staff member who claimed it", category="Ticket Category", status="Current Status (Open, In Progress, Closed)", subject="Keywords in the subject", date="Date created (Format: YYYY-MM-DD)")
    @app_commands.default_permissions(manage_messages=True)
    async def search_tickets(self, interaction: discord.Interaction, ticket_id: int = None, user: discord.Member = None, handler: discord.Member = None, category: str = None, status: str = None, subject: str = None, date: str = None):
        query = "SELECT ticket_id, user_name, category, subject, status, handler_id, timestamp, transcript_url FROM ticket_logs WHERE 1=1"
        params = []

        if ticket_id:
            query += " AND ticket_id = ?"; params.append(ticket_id)
        if user:
            query += " AND user_id = ?"; params.append(user.id)
        if handler:
            query += " AND handler_id = ?"; params.append(handler.id)
        if category:
            query += " AND category = ?"; params.append(category)
        if status:
            query += " AND status = ?"; params.append(status)
        if subject:
            query += " AND subject LIKE ?"; params.append(f"%{subject}%")
        if date:
            query += " AND timestamp LIKE ?"; params.append(f"{date}%")

        query += " ORDER BY timestamp DESC"

        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            results = cursor.fetchall()

        if not results:
            await interaction.response.send_message("🔍 No tickets found matching those criteria.", ephemeral=True)
            return

        embed = discord.Embed(title=f"🔍 Search Results ({len(results)} found)", color=discord.Color.blue())
        for ticket in results[:20]:
            t_id, u_name, cat, subj, stat, h_id, t_stamp, t_url = ticket
            handler_str = f"<@{h_id}>" if h_id else "Unclaimed"
            link_str = f"\n**Transcript:** [Click here to view]({t_url})" if t_url else ""
            embed.add_field(name=f"Ticket #{t_id} | {cat}", value=f"**User:** {u_name}\n**Subject:** {subj}\n**Status:** {stat}\n**Handler:** {handler_str}\n**Date:** {t_stamp[:10]}{link_str}", inline=False)

        if len(results) > 20:
            embed.set_footer(text="Showing the top 20 results. Refine your search to see more.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="force_close", description="Force close and archive a specific ticket (Admin Only)")
    @app_commands.describe(ticket_id="The 6-digit ID of the ticket to close")
    @app_commands.default_permissions(administrator=True)
    async def force_close(self, interaction: discord.Interaction, ticket_id: int):
        await interaction.response.defer(ephemeral=True)
        
        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM ticket_logs WHERE ticket_id = ?", (ticket_id,))
            result = cursor.fetchone()

        if not result:
            return await interaction.followup.send(f"❌ Ticket `#{ticket_id}` does not exist in the database.", ephemeral=True)
            
        if result[0] == "Closed":
            return await interaction.followup.send(f"⚠️ Ticket `#{ticket_id}` is already closed.", ephemeral=True)

        try:
            with sqlite3.connect("tickets.db") as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE ticket_logs SET status = 'Closed' WHERE ticket_id = ?", (ticket_id,))
                conn.commit()
        except Exception as e:
            return await interaction.followup.send(f"⚠️ **Database error!** {e}", ephemeral=True)

        parent_channel = interaction.guild.get_channel(config.TICKET_CHANNEL_ID)
        target_thread = None
        
        if parent_channel:
            for thread in parent_channel.threads:
                if thread.name.endswith(f"-{ticket_id}"):
                    target_thread = thread
                    break
            if not target_thread:
                async for thread in parent_channel.archived_threads(limit=100):
                    if thread.name.endswith(f"-{ticket_id}"):
                        target_thread = thread
                        break

        if not target_thread:
            return await interaction.followup.send(f"✅ **Database Fixed:** Ticket `#{ticket_id}` is now marked as **Closed** in the database.\n*(Note: Could not find the Discord thread to generate a transcript.)*", ephemeral=True)

        await interaction.followup.send(f"Database updated! Archiving Ticket `#{ticket_id}` to GitHub... ⏳", ephemeral=True)
        await archive_and_close_ticket(interaction, target_thread, ticket_id)

    @app_commands.command(name="escalate", description="Transfer this ticket to another staff member")
    @app_commands.describe(new_handler="The staff member to transfer this ticket to")
    @app_commands.default_permissions(manage_messages=True)
    async def escalate_command(self, interaction: discord.Interaction, new_handler: discord.Member):
        if not isinstance(interaction.channel, discord.Thread):
            return await interaction.response.send_message("❌ This command can only be used inside a ticket thread.", ephemeral=True)

        try: ticket_id = int(interaction.channel.name.split('-')[-1])
        except ValueError: return await interaction.response.send_message("❌ Could not determine ticket ID.", ephemeral=True)

        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT handler_id FROM ticket_logs WHERE ticket_id = ?", (ticket_id,))
            result = cursor.fetchone()

        if not result or result[0] != interaction.user.id:
            return await interaction.response.send_message("❌ Only the staff member who claimed this ticket can escalate it.", ephemeral=True)

        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE ticket_logs SET handler_id = ? WHERE ticket_id = ?", (new_handler.id, ticket_id))
            conn.commit()

        await interaction.channel.add_user(new_handler)
        await interaction.response.send_message(f"✅ Ticket manually escalated to {new_handler.mention} by {interaction.user.mention}.")

    @app_commands.command(name="add_member", description="Add an extra user to this ticket thread")
    @app_commands.describe(member="The user to add to the thread")
    @app_commands.default_permissions(manage_messages=True)
    async def add_member(self, interaction: discord.Interaction, member: discord.Member):
        if not isinstance(interaction.channel, discord.Thread):
            return await interaction.response.send_message("❌ This command can only be used inside a ticket thread.", ephemeral=True)
            
        try: ticket_id = int(interaction.channel.name.split('-')[-1])
        except ValueError: return await interaction.response.send_message("❌ Could not determine ticket ID.", ephemeral=True)

        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT handler_id FROM ticket_logs WHERE ticket_id = ?", (ticket_id,))
            result = cursor.fetchone()

        if not result or result[0] != interaction.user.id:
            return await interaction.response.send_message("❌ Only the staff member who claimed this ticket can add members to it.", ephemeral=True)

        await interaction.channel.add_user(member)
        await interaction.response.send_message(f"👋 {member.mention} has been added to the ticket by {interaction.user.mention}.")

    @app_commands.command(name="remove_member", description="Remove a user from this ticket thread")
    @app_commands.describe(member="The user to remove from the thread")
    @app_commands.default_permissions(manage_messages=True)
    async def remove_member(self, interaction: discord.Interaction, member: discord.Member):
        if not isinstance(interaction.channel, discord.Thread):
            return await interaction.response.send_message("❌ This command can only be used inside a ticket thread.", ephemeral=True)
            
        try: ticket_id = int(interaction.channel.name.split('-')[-1])
        except ValueError: return await interaction.response.send_message("❌ Could not determine ticket ID.", ephemeral=True)

        with sqlite3.connect("tickets.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT handler_id FROM ticket_logs WHERE ticket_id = ?", (ticket_id,))
            result = cursor.fetchone()

        if not result or result[0] != interaction.user.id:
            return await interaction.response.send_message("❌ Only the staff member who claimed this ticket can remove members.", ephemeral=True)

        await interaction.channel.remove_user(member)
        await interaction.response.send_message(f"👢 {member.mention} has been removed from the ticket by {interaction.user.mention}.")

async def setup(bot):
    bot.add_view(TicketLauncher())
    bot.add_view(CategoryView())
    bot.add_view(CloseTicketView())
    bot.add_view(ConfirmCloseView())
    bot.add_view(EscalateView())
    await bot.add_cog(Tickets(bot))
