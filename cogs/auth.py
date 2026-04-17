import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import os

# ==========================================
# ⚙️ CONFIGURATION
# Replace this with the ID of the role you want to give users!
# (Right-click the role in Server Settings > Roles and click "Copy Role ID")
VERIFIED_ROLE_ID = 1468579283722305697 
# ==========================================

# --- Database Setup ---
def setup_database():
    conn = sqlite3.connect('meminfo.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS map_discord_email (
            discord_id INTEGER PRIMARY KEY,
            discord_username TEXT,
            name TEXT,
            vibe_email TEXT,
            alt_email TEXT
        )
    ''')
    conn.commit()
    conn.close()

# --- Security Embed Generator ---
def get_security_embed():
    embed = discord.Embed(
        title="🛡️ Vibe Account Security & Compromise Guide",
        description="Thank you for verifying your account. Please review these critical guidelines to protect your Discord account from takeovers.",
        color=discord.Color.brand_red()
    )
    embed.add_field(
        name="🔐 1. Enable Strong Authentication",
        value="• **Passkeys:** Phishing-resistant. Go to `User Settings > Account > Security Keys`.\n• **Authenticator Apps:** Use Aegis or Google Authenticator. Avoid SMS-based 2FA.\n• **Backup Codes:** Store them offline! Without them, a lost 2FA device means permanent account loss.\n🎥 *Watch [How to Setup Mobile 2FA](https://youtu.be/232a1QRj8ME) [00:00:27].*",
        inline=False
    )
    embed.add_field(
        name="🔑 2. Protect Your Account Token",
        value="• **The 'Verify' Scam:** **Never** paste code into your browser's Developer Console (F12) or Terminal.\n• **Suspicious Downloads:** Beware of 'beta testing' games or `.exe`/`.zip` files sent by friends.",
        inline=False
    )
    embed.add_field(
        name="🎣 3. Recognize Social Engineering",
        value="• **Staff Impersonation:** Discord staff will **never** DM you about account issues.\n• **Fake Nitro & QR Codes:** Never scan a Discord login QR code sent by someone else.",
        inline=False
    )
    embed.add_field(
        name="🚨 4. IF Your Account Got Compromised",
        value="**If you still have access:**\nChange your password instantly, remove unknown devices, and deauthorize apps.\n\n**If you are locked out:**\nCheck your email for *'Discord Email Changed'*. Click **'Start Account Recovery'** (valid for 48h). If expired, submit a ticket at [dis.gd/hackedaccount](https://dis.gd/hackedaccount).",
        inline=False
    )
    return embed

# --- The Form (Modal) ---
class AuthModal(discord.ui.Modal, title='Vibe Account Security'):
    user_name = discord.ui.TextInput(label='Your Name', style=discord.TextStyle.short, required=True)
    vibe_email = discord.ui.TextInput(label='Registered Email on Vibe', style=discord.TextStyle.short, required=True)
    alt_email = discord.ui.TextInput(label='Alternate Contact Email', style=discord.TextStyle.short, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        # 1. Save data to Database
        conn = sqlite3.connect('meminfo.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO map_discord_email (discord_id, discord_username, name, vibe_email, alt_email)
            VALUES (?, ?, ?, ?, ?)
        ''', (interaction.user.id, str(interaction.user), self.user_name.value, self.vibe_email.value, self.alt_email.value))
        conn.commit()
        conn.close()

        # 2. Assign the Role
        role_assigned = False
        if interaction.guild: # Ensure this is happening in a server, not a DM
            role = interaction.guild.get_role(VERIFIED_ROLE_ID)
            if role:
                try:
                    await interaction.user.add_roles(role)
                    role_assigned = True
                except discord.Forbidden:
                    print(f"Error: Bot lacks permissions to assign the role {role.name}. Check role hierarchy!")
                except discord.HTTPException as e:
                    print(f"Error assigning role: {e}")

        # 3. Handle User Responses
        sec_embed = get_security_embed()
        success_msg = '✅ Thank you! Your details are secure'
        if role_assigned:
            success_msg += ' and you have been given the verified role!'
        else:
            success_msg += '.'

        # Try to DM the user
        try:
            await interaction.user.send(embed=sec_embed)
            await interaction.response.send_message(
                f'{success_msg} **Please check your DMs** for an important security guide.', 
                ephemeral=True
            )
        except discord.Forbidden:
            # Fallback if DMs are closed
            await interaction.response.send_message(
                f"{success_msg}\n\n"
                "⚠️ *We tried to DM you a security guide, but your DMs are closed or you haven't added the bot. Please read the critical information below:*", 
                embed=sec_embed,
                ephemeral=True
            )

# --- The Button Panel (View) ---
class AuthView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify Account", style=discord.ButtonStyle.blurple, custom_id="persistent_auth_button", emoji="🛡️")
    async def auth_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AuthModal())

# --- The Cog ---
class AuthenticationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        setup_database()

    @app_commands.command(name="setupauth", description="Spawns the authentication verification panel.")
    @app_commands.default_permissions(administrator=True)
    async def setup_auth_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🛡️ Server Security Update",
            description=(
                "Recently, Discord has seen a spike in accounts getting compromised and used to promote scams.\n\n"
                "To ensure the safety of our community, please verify your account. If your account is ever compromised "
                "and we have to remove it to protect the server, we will use this information to contact you so you can safely rejoin."
            ),
            color=discord.Color.red()
        )
        embed.set_footer(text="Click the button below to fill out your details. Your data is kept private.")
        
        await interaction.response.send_message(embed=embed, view=AuthView())

    @app_commands.command(name="checkauth", description="View a list of all users who have filled out the auth form.")
    @app_commands.default_permissions(administrator=True)
    async def check_auth(self, interaction: discord.Interaction):
        conn = sqlite3.connect('meminfo.db')
        cursor = conn.cursor()
        cursor.execute('SELECT discord_id, name, vibe_email, alt_email FROM map_discord_email')
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message("No users have verified their accounts yet.", ephemeral=True)
            return

        lines = []
        for row in rows:
            user_id, name, v_email, a_email = row
            lines.append(f"👤 **{name}** | <@{user_id}> (`{user_id}`)\n📧 **Vibe**: {v_email} | **Alt**: {a_email}\n")
        
        content = "\n".join(lines)
        
        if len(content) <= 2000:
            await interaction.response.send_message(content, ephemeral=True)
        else:
            with open("auth_dump.txt", "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(f"Name: {row[1]} | UserID: {row[0]} | Vibe: {row[2]} | Alt: {row[3]}\n")
            
            await interaction.response.send_message(
                "The verified user list is too long for a single message. Here is the complete file:", 
                file=discord.File("auth_dump.txt"), 
                ephemeral=True
            )
            os.remove("auth_dump.txt")

async def setup(bot):
    await bot.add_cog(AuthenticationCog(bot))
