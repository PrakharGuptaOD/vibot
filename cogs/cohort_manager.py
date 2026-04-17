import discord
from discord.ext import commands
from discord import app_commands
import json
import os

# --- CONFIGURATION ---
COHORTS_FILE = 'cohorts.json'
# Replace this with the actual ID of the Category where you want these channels created
TARGET_CATEGORY_ID = 123456789012345678 
# ---------------------

class CohortManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._ensure_json_file()

    def _ensure_json_file(self):
        """Creates cohorts.json if it doesn't exist."""
        if not os.path.exists(COHORTS_FILE):
            with open(COHORTS_FILE, 'w') as f:
                json.dump({}, f)

    def save_cohort(self, name: str, role_id: int):
        """Saves the new cohort to the JSON file."""
        with open(COHORTS_FILE, 'r') as f:
            data = json.load(f)
        
        data[name] = role_id
        
        with open(COHORTS_FILE, 'w') as f:
            json.dump(data, f, indent=4)

    def remove_cohort_data(self, name: str):
        """Removes a cohort from the JSON file."""
        with open(COHORTS_FILE, 'r') as f:
            data = json.load(f)
            
        if name in data:
            del data[name]
            
            with open(COHORTS_FILE, 'w') as f:
                json.dump(data, f, indent=4)

    @app_commands.command(name="add_cohort", description="Creates a new cohort role, channel, and dedicated threads.")
    @app_commands.describe(cohort_name="The name of the new cohort")
    @app_commands.default_permissions(manage_roles=True, manage_channels=True)
    async def add_cohort(self, interaction: discord.Interaction, cohort_name: str):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        category = discord.utils.get(guild.categories, id=TARGET_CATEGORY_ID)

        if not category:
            await interaction.followup.send("❌ Error: Target category not found. Please check `TARGET_CATEGORY_ID` in the code.", ephemeral=True)
            return

        try:
            # 1. Create the Cohort Role
            role = await guild.create_role(
                name=cohort_name, 
                reason=f"Cohort created by {interaction.user.name}"
            )

            # 2. Configure Channel Permissions
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,           # Blocks typing in main channel
                    send_messages_in_threads=True, # Allows typing in threads
                    create_public_threads=False,   # Prevents cluttering with their own threads
                    manage_threads=False,          # STRICTLY prevents them from deleting or managing the threads
                    read_message_history=True
                ),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    create_public_threads=True,
                    manage_threads=True,
                    read_message_history=True
                )
            }

            # 3. Create the Text Channel
            formatted_channel_name = cohort_name.lower().replace(" ", "-")
            channel = await guild.create_text_channel(
                name=formatted_channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Cohort channel for {cohort_name}"
            )

            # 4. Create the 3 Threads
            chitchat_thread = await channel.create_thread(name="💬 chit-chat", type=discord.ChannelType.public_thread)
            announcements_thread = await channel.create_thread(name="📢 announcements", type=discord.ChannelType.public_thread)
            discussions_thread = await channel.create_thread(name="📚 discussions", type=discord.ChannelType.public_thread)

            # 5. Send Directory Message
            embed = discord.Embed(
                title=f"Welcome to the {cohort_name} Cohort!",
                description="This main channel is **read-only**. Please use the designated threads below for all communication:",
                color=discord.Color.brand_green()
            )
            embed.add_field(name="💬 Chit Chat", value=f"Head over to {chitchat_thread.mention} for casual conversations.", inline=False)
            embed.add_field(name="📢 Announcements", value=f"Keep an eye on {announcements_thread.mention} for important updates.", inline=False)
            embed.add_field(name="📚 Discussions", value=f"Use {discussions_thread.mention} for coursework and questions.", inline=False)
            
            await channel.send(content=f"Welcome {role.mention}!", embed=embed)

            # 6. Save to JSON
            self.save_cohort(cohort_name, role.id)

            await interaction.followup.send(f"✅ Successfully created cohort **{cohort_name}**!", ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send("❌ Error: Missing permissions ('Manage Roles', 'Manage Channels', or 'Manage Threads').", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ An unexpected error occurred: {str(e)}", ephemeral=True)

    @app_commands.command(name="delete_cohort", description="Deletes a cohort's role and channel, and removes it from the database.")
    @app_commands.describe(cohort_name="The exact name of the cohort to delete")
    @app_commands.default_permissions(manage_roles=True, manage_channels=True)
    async def delete_cohort(self, interaction: discord.Interaction, cohort_name: str):
        # Defer because deleting things can take a moment
        await interaction.response.defer(ephemeral=True)
        
        with open(COHORTS_FILE, 'r') as f:
            data = json.load(f)
            
        if cohort_name not in data:
            await interaction.followup.send(f"❌ Cohort '{cohort_name}' not found in the database.", ephemeral=True)
            return
            
        role_id = data[cohort_name]
        guild = interaction.guild
        
        # 1. Delete Role
        role = guild.get_role(role_id)
        if role:
            try:
                await role.delete(reason=f"Cohort deleted by {interaction.user.name}")
            except discord.Forbidden:
                await interaction.followup.send("❌ I don't have permission to delete that role. Is it higher than my bot role?", ephemeral=True)
                return
                
        # 2. Delete Channel
        formatted_channel_name = cohort_name.lower().replace(" ", "-")
        channel = discord.utils.get(guild.channels, name=formatted_channel_name)
        if channel:
            try:
                await channel.delete(reason=f"Cohort channel deleted by {interaction.user.name}")
            except discord.Forbidden:
                await interaction.followup.send("❌ I don't have permission to delete that channel.", ephemeral=True)
                return
                
        # 3. Remove from JSON
        self.remove_cohort_data(cohort_name)
        
        await interaction.followup.send(f"🗑️ Successfully deleted the **{cohort_name}** cohort (role & channel).", ephemeral=True)

    @app_commands.command(name="list_cohorts", description="Shows a list of all active cohorts registered in the bot.")
    async def list_cohorts(self, interaction: discord.Interaction):
        with open(COHORTS_FILE, 'r') as f:
            data = json.load(f)
            
        if not data:
            await interaction.response.send_message("📂 No active cohorts found.", ephemeral=True)
            return
            
        embed = discord.Embed(title="📚 Active Cohorts", color=discord.Color.blue())
        description = ""
        
        for name, role_id in data.items():
            description += f"• **{name}** (Role: <@&{role_id}>)\n"
            
        embed.description = description
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(CohortManager(bot))
