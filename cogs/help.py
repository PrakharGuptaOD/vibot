import discord
from discord import app_commands
from discord.ext import commands

# ==========================================
# DROPDOWN MENU UI
# ==========================================
class HelpDropdown(discord.ui.Select):
    def __init__(self):
        # Define the options for the dropdown menu
        options = [
            discord.SelectOption(
                label="General & Moderation", 
                description="Server management and moderation tools", 
                emoji="🔨"
            ),
            discord.SelectOption(
                label="Ticket System", 
                description="Commands for managing support tickets", 
                emoji="🎫"
            ),
            discord.SelectOption(
                label="Admin Utilities", 
                description="Database and data processing tools", 
                emoji="⚙️"
            ),
            discord.SelectOption(
                label="Breakout Rooms", 
                description="Info on automated voice channels", 
                emoji="🔊"
            )
        ]
        super().__init__(placeholder="Choose a category to view commands...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        # This function runs whenever an admin selects an option
        selected_category = self.values[0]
        
        embed = discord.Embed(color=discord.Color.dark_theme())
        embed.set_footer(text="Vinternship Server Administration")

        if selected_category == "General & Moderation":
            embed.title = "🔨 General & Moderation Commands"
            embed.description = (
                "`/clear [amount]` - Bulk delete messages in a channel.\n"
                "`/warn`, `/history`, `/delwarn` - Manage user strikes via SQLite.\n"
                "`/timeout`, `/kick`, `/ban` - Restrict or remove disruptive users.\n"
                "`/lock`, `/unlock`, `/slowmode` - Manage channel traffic and access.\n"
                "`/serverinfo`, `/userinfo`, `/ping`, `/uptime` - View core metrics."
            )
            
        elif selected_category == "Ticket System":
            embed.title = "🎫 Ticket System Commands"
            embed.description = (
                "`/setup` - Deploy the interactive Ticket Support Center panel.\n"
                "`/open_tickets` - View a list of all currently unresolved tickets.\n"
                "`/search_tickets` - Query the ticket database by user, handler, or subject.\n"
                "`/force_close [id]` - Manually archive and close a stuck ticket.\n"
                "`/escalate`, `/add_member`, `/remove_member` - Manage access within ticket threads.\n"
                "`/view_ratings` - Check feedback scores for staff members."
            )
            
        elif selected_category == "Admin Utilities":
            embed.title = "⚙️ Admin Utilities"
            embed.description = (
                "`/backup_db` - Generate a downloadable backup of the SQLite tickets database.\n"
                "`!process_tickets` - Scan and parse HTML transcripts into JSON format *(Note: This is a prefix command)*."
            )
            
        elif selected_category == "Breakout Rooms":
            embed.title = "🔊 Breakout Rooms"
            embed.description = (
                "Breakout Rooms are fully automated. When a user joins the designated VC, Vibot generates a private room and provides them with a UI panel to:\n\n"
                "🔒 **Lock / Unlock**\n"
                "✏️ **Rename Room**\n"
                "🗑️ **Delete Room**\n"
                "➕ **Add / Kick Users**\n"
                "👥 **Set Limits**\n"
                "👑 **Transfer Ownership**"
            )

        # Edit the original message with the new embed based on the selection
        await interaction.response.edit_message(embed=embed)

class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(HelpDropdown())

# ==========================================
# MAIN COG
# ==========================================
class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help_admin", description="Interactive admin command overview for Vibot")
    @app_commands.default_permissions(administrator=True)
    async def help_admin(self, interaction: discord.Interaction):
        # The initial "Home" embed shown before they click the dropdown
        embed = discord.Embed(
            title="🛡️ Vibot Admin & Staff Dashboard",
            description="Welcome to the control center. Use the dropdown menu below to navigate through the different command categories for managing the Vinternship server.",
            color=discord.Color.dark_theme()
        )
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.set_footer(text="Vinternship Server Administration")
        
        # Send the message ephemerally with the dropdown view attached
        await interaction.response.send_message(embed=embed, view=HelpView(), ephemeral=True)

async def setup(bot):
    await bot.add_cog(Help(bot))