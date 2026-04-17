import discord
from discord import app_commands
from discord.ext import commands
import config
import time
import datetime
import sqlite3 

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        
        # ==========================================
        # DATABASE SETUP
        # ==========================================
        self.conn = sqlite3.connect('meminfo.db')
        self.cursor = self.conn.cursor()
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS warnings (
                warning_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                moderator_id INTEGER,
                reason TEXT,
                timestamp TEXT
            )
        ''')
        self.conn.commit()

    # ==========================================
    # ORIGINAL COMMANDS
    # ==========================================

    @app_commands.command(name="clear", description="Delete messages (Admin/Mod Only)")
    @app_commands.default_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        await interaction.response.defer(ephemeral=True)
        if isinstance(interaction.channel, discord.TextChannel):
            deleted = await interaction.channel.purge(limit=amount)
            await interaction.followup.send(f"🗑️ Deleted {len(deleted)} messages.", ephemeral=True)
        else:
             await interaction.followup.send("❌ Cannot purge messages in this channel type.", ephemeral=True)

    @app_commands.command(name="resource", description="Get a direct link to a specific resource")
    @app_commands.choices(topic=[
        app_commands.Choice(name="Git Guide", value="git_guide"),
        app_commands.Choice(name="Project Policies", value="policies"),
        app_commands.Choice(name="Blogs", value="blogs"),
        app_commands.Choice(name="Projects", value="projects")
    ])
    async def resource(self, interaction: discord.Interaction, topic: app_commands.Choice[str]):
        url = config.TOPIC_MAP.get(topic.value)
        if url:
            await interaction.response.send_message(f"Here is the link for **{topic.name}**:\n🔗 {url}")
        else:
            await interaction.response.send_message("❌ Resource not found in configuration.", ephemeral=True)

    # ==========================================
    # MODERATION COMMANDS (Including SQLite)
    # ==========================================

    @app_commands.command(name="warn", description="Warn a user and log it to the database")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Insert the warning into the database
        self.cursor.execute('''
            INSERT INTO warnings (user_id, moderator_id, reason, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (member.id, interaction.user.id, reason, timestamp))
        self.conn.commit()
        
        # Check total warnings for the user
        self.cursor.execute('SELECT COUNT(*) FROM warnings WHERE user_id = ?', (member.id,))
        warning_count = self.cursor.fetchone()[0]
        
        response_msg = f"⚠️ **{member.display_name}** has been warned by {interaction.user.mention}. Reason: {reason}\n*They now have {warning_count} warning(s).*"
        
        # Apply automatic timeout if warnings exceed 5
        if warning_count > 5:
            try:
                duration = datetime.timedelta(hours=12)
                await member.timeout(duration, reason="more than 5 warnings")
                response_msg += f"\n🚨 **Automatic Action:** User has exceeded 5 warnings and has been timed out for 12 hours."
            except discord.Forbidden:
                response_msg += f"\n❌ **Error:** User exceeded 5 warnings, but I lack permissions to time them out (they may have a higher role)."

        await interaction.response.send_message(response_msg)
        
        try:
            await member.send(f"You have received a warning in **{interaction.guild.name}**.\nReason: {reason}\nYou currently have {warning_count} warning(s).")
        except discord.Forbidden:
            pass

    @app_commands.command(name="history", description="Check a user's warning history")
    @app_commands.default_permissions(moderate_members=True)
    async def history(self, interaction: discord.Interaction, member: discord.Member):
        # Retrieve warnings, including the warning_id
        self.cursor.execute('''
            SELECT warning_id, moderator_id, reason, timestamp FROM warnings WHERE user_id = ?
        ''', (member.id,))
        records = self.cursor.fetchall()
        
        embed = discord.Embed(title=f"Warning History: {member.display_name}", color=discord.Color.orange())
        
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)

        if not records:
            embed.description = "✅ This user has a clean record."
        else:
            embed.description = f"Total Warnings: **{len(records)}**\n"
            for idx, record in enumerate(records[-10:], 1):
                warning_id, mod_id, reason, timestamp = record
                embed.add_field(
                    name=f"ID: {warning_id} | {timestamp}", 
                    value=f"**Mod ID:** {mod_id}\n**Reason:** {reason}", 
                    inline=False
                )
                
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="delwarn", description="Delete a specific warning by its ID")
    @app_commands.default_permissions(moderate_members=True)
    async def delwarn(self, interaction: discord.Interaction, warning_id: int):
        # Check if the warning exists first
        self.cursor.execute('SELECT user_id FROM warnings WHERE warning_id = ?', (warning_id,))
        result = self.cursor.fetchone()
        
        if result:
            self.cursor.execute('DELETE FROM warnings WHERE warning_id = ?', (warning_id,))
            self.conn.commit()
            await interaction.response.send_message(f"✅ Warning `#{warning_id}` has been successfully deleted.")
        else:
            await interaction.response.send_message(f"❌ Could not find a warning with ID `#{warning_id}`.", ephemeral=True)

    @app_commands.command(name="kick", description="Kick a user from the server")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        try:
            await member.kick(reason=reason)
            await interaction.response.send_message(f"👢 **{member.display_name}** has been kicked. Reason: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ I do not have permission to kick this user.", ephemeral=True)

    @app_commands.command(name="ban", description="Ban a user from the server")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        try:
            await member.ban(reason=reason, delete_message_days=1)
            await interaction.response.send_message(f"🔨 **{member.display_name}** has been banned. Reason: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ I do not have permission to ban this user.", ephemeral=True)

    @app_commands.command(name="timeout", description="Timeout a user for a specific duration (in minutes)")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason provided"):
        try:
            duration = datetime.timedelta(minutes=minutes)
            await member.timeout(duration, reason=reason)
            await interaction.response.send_message(f"⏱️ **{member.display_name}** has been timed out for {minutes} minutes. Reason: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ I do not have permission to timeout this user.", ephemeral=True)

    @app_commands.command(name="lock", description="Lock the current channel")
    @app_commands.default_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
        await interaction.response.send_message("🔒 This channel has been locked.")

    @app_commands.command(name="unlock", description="Unlock the current channel")
    @app_commands.default_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
        await interaction.response.send_message("🔓 This channel has been unlocked.")

    @app_commands.command(name="slowmode", description="Set the slowmode delay for the current channel")
    @app_commands.default_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: int):
        await interaction.channel.edit(slowmode_delay=seconds)
        await interaction.response.send_message(f"⏱️ Slowmode set to {seconds} seconds.")

    # ==========================================
    # HEALTH & INFO COMMANDS
    # ==========================================

    @app_commands.command(name="ping", description="Check Vibot's latency")
    async def ping(self, interaction: discord.Interaction):
        gateway_latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! Gateway Latency: `{gateway_latency}ms`")

    @app_commands.command(name="uptime", description="Check how long Vibot has been online")
    async def uptime(self, interaction: discord.Interaction):
        current_time = time.time()
        difference = int(round(current_time - self.start_time))
        uptime_string = str(datetime.timedelta(seconds=difference))
        await interaction.response.send_message(f"🟢 Vibot has been online for: `{uptime_string}`")

    @app_commands.command(name="serverinfo", description="Display statistics about the server")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(title=f"Server Info: {guild.name}", color=discord.Color.blue())
        
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
            
        embed.add_field(name="Owner", value=guild.owner.mention, inline=True)
        embed.add_field(name="Server ID", value=guild.id, inline=True)
        embed.add_field(name="Created On", value=guild.created_at.strftime("%B %d, %Y"), inline=True)
        embed.add_field(name="Members", value=guild.member_count, inline=True)
        embed.add_field(name="Text Channels", value=len(guild.text_channels), inline=True)
        embed.add_field(name="Voice Channels", value=len(guild.voice_channels), inline=True)
        embed.add_field(name="Roles", value=len(guild.roles), inline=True)
        embed.add_field(name="Boost Level", value=guild.premium_tier, inline=True)
        
        embed.set_footer(text="Server Management")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Get information about a specific user")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        roles = [role.mention for role in member.roles[1:]]
        roles_str = " ".join(roles) if roles else "No roles"
        
        embed = discord.Embed(title=f"User Info: {member.display_name}", color=member.color)
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
            
        embed.add_field(name="Account Created", value=member.created_at.strftime("%B %d, %Y"), inline=False)
        embed.add_field(name="Joined Server", value=member.joined_at.strftime("%B %d, %Y"), inline=False)
        embed.add_field(name="Roles", value=roles_str, inline=False)
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(General(bot))