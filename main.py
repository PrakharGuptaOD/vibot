import discord
import asyncio
from discord.ext import commands
import config
from cogs.auth import AuthView 

# Setup the Bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True # Needed for tickets
intents.voice_states = True # Needed for voice logs

bot = commands.Bot(command_prefix=";", intents=intents)

async def load_extensions():
    # Load all modules
    await bot.load_extension("cogs.auth")
    await bot.load_extension("cogs.cohort_manager")
    await bot.load_extension("cogs.general")
    await bot.load_extension("cogs.tickets")
    await bot.load_extension("cogs.ticket_processor")
    await bot.load_extension("cogs.vc_generator")
    await bot.load_extension("cogs.help")
    await bot.load_extension("cogs.evaluation")
    await bot.load_extension("cogs.panel")

# --- LAYER 1: GLOBAL SERVER CHECK ---
@bot.tree.interaction_check
async def strict_server_check(interaction: discord.Interaction):
    if interaction.guild_id != config.GUILD_ID:
        await interaction.response.send_message("❌ My commands are exclusively restricted to the Vinternship server!", ephemeral=True)
        return False
    return True

# --- LAYER 2: AUTO-LEAVE UNAUTHORIZED SERVERS ---
@bot.event
async def on_guild_join(guild: discord.Guild):
    if guild.id != config.GUILD_ID:
        print(f"🚨 Unauthorized invite detected! Automatically leaving {guild.name}...")
        await guild.leave()

@bot.event
async def on_ready():
    # Create an object for your specific server
    MY_GUILD = discord.Object(id=config.GUILD_ID)

    try:
        # 1. Copy all commands directly to your server
        bot.tree.copy_global_to(guild=MY_GUILD)
        
        # 2. Sync the commands ONLY to your server
        synced = await bot.tree.sync(guild=MY_GUILD)
        
        # 3. Wipe any leftover global commands so they disappear from DMs and other servers!
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync(guild=None)

        print(f"✅ Synced {len(synced)} command(s) EXCLUSIVELY to server {config.GUILD_ID}")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

    print(f'✅ Logged in as {bot.user}')

async def main():
    discord.utils.setup_logging()
    async with bot:
        await load_extensions()
        await bot.start(config.DISCORD_TOKEN)
async def setup_hook(self):
    self.add_view(AuthView())
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
