import discord
from discord.ext import commands

# ==========================================
# UI MODALS FOR RENAME & LIMIT
# ==========================================
class VCRenameModal(discord.ui.Modal, title='Rename Breakout Room'):
    name_input = discord.ui.TextInput(
        label='New Room Name',
        placeholder='e.g., Project Discussion...',
        max_length=100,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.channel.edit(name=self.name_input.value)
        await interaction.response.send_message(f"✅ Room renamed to **{self.name_input.value}**", ephemeral=True)

class VCLimitModal(discord.ui.Modal, title='Set User Limit'):
    limit_input = discord.ui.TextInput(
        label='Max Users (0 for unlimited)',
        placeholder='e.g., 5',
        max_length=2,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(self.limit_input.value)
            if limit < 0 or limit > 99:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ Please enter a valid number between 0 and 99.", ephemeral=True)
            return

        await interaction.channel.edit(user_limit=limit)
        await interaction.response.send_message(f"✅ Room limit set to **{limit if limit > 0 else 'Unlimited'}** users.", ephemeral=True)


# ==========================================
# MAIN CONTROL PANEL VIEW (4x2 GRID, UNCOLORED)
# ==========================================
class VCControlPanel(discord.ui.View):
    def __init__(self, owner_id: int, active_vcs: dict):
        super().__init__(timeout=None) 
        self.owner_id = owner_id
        self.active_vcs = active_vcs

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        current_owner = self.active_vcs.get(interaction.channel.id)
        if interaction.user.id != current_owner:
            await interaction.response.send_message("❌ Only the current owner of this breakout room can use the control panel.", ephemeral=True)
            return False
        return True

    # --- ROW 0: ROOM CONTROLS (4 Buttons) ---
    @discord.ui.button(emoji="🔒", style=discord.ButtonStyle.secondary, row=0)
    async def btn_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        perms = interaction.channel.overwrites_for(interaction.guild.default_role)
        perms.connect = False
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=perms)
        await interaction.response.send_message("🔒 Room is now **Locked**. Nobody else can join unless you add them.", ephemeral=True)

    @discord.ui.button(emoji="🔓", style=discord.ButtonStyle.secondary, row=0)
    async def btn_unlock(self, interaction: discord.Interaction, button: discord.ui.Button):
        perms = interaction.channel.overwrites_for(interaction.guild.default_role)
        perms.connect = None 
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=perms)
        await interaction.response.send_message("🔓 Room is now **Unlocked**. Anyone can join.", ephemeral=True)

    @discord.ui.button(emoji="✏️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VCRenameModal())

    @discord.ui.button(emoji="🗑️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if interaction.channel.id in self.active_vcs:
            del self.active_vcs[interaction.channel.id]
        await interaction.channel.delete(reason="Owner manually deleted the breakout room")

    # --- ROW 1: USER MANAGEMENT (4 Buttons) ---
    @discord.ui.button(emoji="➕", style=discord.ButtonStyle.secondary, row=1)
    async def btn_add_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=60)
        select = discord.ui.UserSelect(placeholder="➕ Select a user to grant access")
        
        async def select_callback(inter: discord.Interaction):
            user = select.values[0]
            await inter.channel.set_permissions(user, connect=True)
            await inter.response.send_message(f"✅ **{user.display_name}** has been granted permission to join.", ephemeral=True)
            
        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("Choose a user to add to your locked room:", view=view, ephemeral=True)

    @discord.ui.button(emoji="👢", style=discord.ButtonStyle.secondary, row=1)
    async def btn_kick_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=60)
        select = discord.ui.UserSelect(placeholder="👢 Select a user to kick")
        
        async def select_callback(inter: discord.Interaction):
            user = select.values[0]
            if user in inter.channel.members:
                await user.move_to(None)
                await inter.response.send_message(f"👢 **{user.display_name}** has been removed from the room.", ephemeral=True)
            else:
                await inter.response.send_message(f"❌ **{user.display_name}** is not in this voice channel.", ephemeral=True)
                
        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("Choose a user to kick out:", view=view, ephemeral=True)

    @discord.ui.button(emoji="👥", style=discord.ButtonStyle.secondary, row=1)
    async def btn_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VCLimitModal())

    @discord.ui.button(emoji="👑", style=discord.ButtonStyle.secondary, row=1)
    async def btn_transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = discord.ui.View(timeout=60)
        select = discord.ui.UserSelect(placeholder="👑 Select the new owner")
        
        async def select_callback(inter: discord.Interaction):
            new_owner = select.values[0]
            if new_owner.bot:
                await inter.response.send_message("❌ You cannot transfer ownership to a bot.", ephemeral=True)
                return
                
            self.active_vcs[inter.channel.id] = new_owner.id
            await inter.response.send_message(f"👑 Ownership of this breakout room has been transferred to {new_owner.mention}.")
            
        select.callback = select_callback
        view.add_item(select)
        await interaction.response.send_message("Who should take control of this room?", view=view, ephemeral=True)


# ==========================================
# MAIN COG
# ==========================================
class VCGenerator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.JOIN_TO_CREATE_VC_ID = 1468815961275498547 
        
        # --- NEW: Target Category ID ---
        # Add the ID of the category where you want the new rooms to be created
        self.TARGET_CATEGORY_ID = 1468815959916675295  # <--- REPLACE THIS WITH YOUR CATEGORY ID
        
        self.active_temp_vcs = {}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        
        # 1. USER JOINS "JOIN TO CREATE"
        if after.channel and after.channel.id == self.JOIN_TO_CREATE_VC_ID:
            
            # Fetch the specific target category using the ID
            target_category = member.guild.get_channel(self.TARGET_CATEGORY_ID)
            
            # Fallback to the original category just in case the target ID is wrong or missing
            if not target_category:
                target_category = after.channel.category
            
            new_vc = await member.guild.create_voice_channel(
                name=f"{member.display_name}'s breakout",
                category=target_category,
                reason=f"{member.display_name} created a breakout room"
            )
            
            self.active_temp_vcs[new_vc.id] = member.id
            await member.move_to(new_vc)
            
            embed = discord.Embed(
                title="Breakout Room Controls", 
                description=(
                    "You are the owner of this temporary voice channel. "
                    "Use the buttons below to manage your room.\n\n"
                    "**Legend:**\n"
                    "🔒 **Lock:** Prevent new users from joining.\n"
                    "🔓 **Unlock:** Allow anyone to join freely.\n"
                    "✏️ **Rename:** Change the name of your room.\n"
                    "🗑️ **Delete:** Instantly close and delete this room.\n"
                    "➕ **Add User:** Grant a specific user bypass access.\n"
                    "👢 **Kick User:** Disconnect someone from the room.\n"
                    "👥 **Set Limit:** Change the max number of users.\n"
                    "👑 **Transfer:** Give ownership to someone else."
                ),
                color=discord.Color.blue()
            )
            
            await new_vc.send(
                content=f"Hey {member.mention}, here is your control panel!", 
                embed=embed, 
                view=VCControlPanel(owner_id=member.id, active_vcs=self.active_temp_vcs)
            )

        # 2. CLEANUP & AUTO-TRANSFER ON LEAVE
        # FIX: Ensure user actually changed channels or disconnected, ignoring mute/deafen events.
        if before.channel and before.channel != after.channel:
            
            is_tracked = before.channel.id in self.active_temp_vcs
            is_breakout_category = before.channel.category and before.channel.category.id == self.TARGET_CATEGORY_ID

            # FIX: Clean up zombie channels even if bot forgot about them, as long as they are empty and in the right category.
            if is_tracked or is_breakout_category:
                
                # Agar channel poora khaali ho gaya hai
                if len(before.channel.members) == 0:
                    if is_tracked:
                        del self.active_temp_vcs[before.channel.id]
                    await before.channel.delete(reason="Breakout room empty")
                
                # Agar sirf owner ne leave kiya hai (aur log abhi bhi hain)
                elif is_tracked and member.id == self.active_temp_vcs[before.channel.id]:
                    new_owner = None
                    
                    for m in before.channel.members:
                        if not m.bot:
                            new_owner = m
                            break
                    
                    if new_owner:
                        self.active_temp_vcs[before.channel.id] = new_owner.id
                        await before.channel.send(f"👑 **{member.display_name}** left. Ownership has automatically been transferred to {new_owner.mention}.")
                    else:
                        del self.active_temp_vcs[before.channel.id]
                        await before.channel.delete(reason="Only bots remained in breakout room")

async def setup(bot):
    await bot.add_cog(VCGenerator(bot))
