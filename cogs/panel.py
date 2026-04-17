import discord
from discord.ext import commands
from discord import app_commands
import json
import os

# --- CONFIGURATION ---
COHORTS_FILE = 'cohorts.json'
# ---------------------

class DynamicCohortDropdown(discord.ui.Select):
    def __init__(self, options):
        # We pass the options in dynamically when this is created
        super().__init__(
            placeholder="Choose your cohort to join/leave...", 
            min_values=1, 
            max_values=1, 
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        role_id = int(self.values[0])
        role = interaction.guild.get_role(role_id)
        
        if not role:
            await interaction.response.send_message("❌ Error: That cohort role no longer exists on the server.", ephemeral=True)
            return

        # Toggle Logic
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"👋 You have left the **{role.name}** cohort and lost access to its channels.", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"🎉 You have joined the **{role.name}** cohort! Check the channel list for your new threads.", ephemeral=True)


class DropdownView(discord.ui.View):
    def __init__(self, options):
        # This view doesn't need a timeout because it's attached to an ephemeral message
        super().__init__(timeout=None)
        self.add_item(DynamicCohortDropdown(options))


class PanelButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Required for the button to survive bot restarts

    @discord.ui.button(label="Select Your Cohort", style=discord.ButtonStyle.blurple, custom_id="persistent_cohort_button", emoji="🎓")
    async def spawn_dropdown(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. Check if the JSON file exists
        if not os.path.exists(COHORTS_FILE):
            await interaction.response.send_message("❌ No cohorts are currently set up.", ephemeral=True)
            return
            
        # 2. Read the LATEST data from the JSON file EXACTLY when they click the button
        with open(COHORTS_FILE, 'r') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}

        if not data:
            await interaction.response.send_message("❌ No cohorts are currently available.", ephemeral=True)
            return

        # 3. Build the options list dynamically
        options = []
        # Discord limits dropdowns to 25 options max
        for name, role_id in list(data.items())[:25]:
            options.append(
                discord.SelectOption(
                    label=name, 
                    value=str(role_id), 
                    description=f"Join or leave the {name} cohort"
                )
            )

        # 4. Send the dropdown to the user privately (ephemeral)
        await interaction.response.send_message(
            "Here is the most up-to-date list of cohorts. Make your selection below:", 
            view=DropdownView(options), 
            ephemeral=True
        )


class PanelManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # This ensures the button still works if the bot goes offline and comes back online
        self.bot.add_view(PanelButton())

    @app_commands.command(name="spawn_panel", description="Spawns the persistent cohort selection button.")
    @app_commands.default_permissions(manage_roles=True, manage_channels=True)
    async def spawn_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎓 Cohort Selection Panel",
            description=(
                "Click the button below to view the active cohorts.\n\n"
                "A private menu will appear with the most up-to-date list of cohorts. "
                "**Note:** Selecting a cohort you are already in will *remove* your access."
            ),
            color=discord.Color.blurple()
        )
        
        # Acknowledge the command privately
        await interaction.response.send_message("✅ Button panel successfully spawned below.", ephemeral=True)
        
        # Send the actual button to the channel publicly
        await interaction.channel.send(embed=embed, view=PanelButton())


async def setup(bot):
    await bot.add_cog(PanelManager(bot))
