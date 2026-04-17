import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import csv
import os
import json
from datetime import datetime, timedelta
import pytz

# --- CONFIGURATION ---
EVALUATOR_ROLE = "viva_evaluator" 
IST = pytz.timezone('Asia/Kolkata')
DB_FILE = 'evaluations.db'
CONFIG_FILE = 'viva_config.json'

def load_config():
    """Loads the dates and times from a JSON file. Creates a default one if it doesn't exist."""
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "dates": [
                {"label": "March 25, 2026", "value": "2026-03-25", "desc": "Wednesday"},
                {"label": "March 26, 2026", "value": "2026-03-26", "desc": "Thursday"},
                {"label": "March 27, 2026", "value": "2026-03-27", "desc": "Friday"}
            ],
            "time_slots": [
                "13:00", "13:30", "14:00", "14:30", "15:00", "15:30",
                "16:00", "16:30", "17:00", "17:30", "18:00", "18:30"
            ]
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(default_config, f, indent=4)
        return default_config
        
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def setup_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS evaluations (
            time_slot TEXT PRIMARY KEY, 
            discord_user_id INTEGER,
            discord_username TEXT,
            student_name TEXT,
            cohort_name TEXT,
            registered_email TEXT,
            conceptual_understanding INTEGER DEFAULT 0,
            interpretation_of_code INTEGER DEFAULT 0,
            reasoning INTEGER DEFAULT 0,
            error_handling INTEGER DEFAULT 0,
            flow_understanding INTEGER DEFAULT 0,
            total_score INTEGER DEFAULT 0,
            status TEXT DEFAULT 'booked'
        )
    ''')
    
    # Safely try to add the attendance column for existing databases
    try:
        cursor.execute("ALTER TABLE evaluations ADD COLUMN attendance TEXT DEFAULT 'Pending'")
    except sqlite3.OperationalError:
        pass # Column already exists
        
    conn.commit()
    conn.close()

def get_available_slots(date_str):
    config = load_config()
    all_slots = [f"{date_str} {t}" for t in config["time_slots"]]
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT time_slot FROM evaluations WHERE time_slot LIKE ?', (f"{date_str}%",))
    booked_slots = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    return [slot for slot in all_slots if slot not in booked_slots]

# --- UI COMPONENTS ---

class BookingModal(discord.ui.Modal, title='Evaluation Registration'):
    student_name = discord.ui.TextInput(label='Full Name', placeholder='e.g., John Doe', required=True)
    registered_email = discord.ui.TextInput(label='Registered Email', placeholder='name@example.com', required=True)
    cohort_name = discord.ui.TextInput(label='Cohort Name', placeholder='e.g., Kruskalians', required=True)

    def __init__(self, selected_slot: str):
        super().__init__()
        self.selected_slot = selected_slot

    async def on_submit(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('SELECT time_slot FROM evaluations WHERE discord_user_id=? AND status="booked"', (interaction.user.id,))
        if cursor.fetchone():
            await interaction.response.send_message("❌ You already have an active booking. You must complete it before booking again.", ephemeral=True)
            conn.close()
            return

        try:
            cursor.execute('''
                INSERT INTO evaluations 
                (time_slot, discord_user_id, discord_username, student_name, cohort_name, registered_email) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (self.selected_slot, interaction.user.id, interaction.user.name, 
                  self.student_name.value, self.cohort_name.value, self.registered_email.value))
            conn.commit()
            
            display_time = datetime.strptime(self.selected_slot, "%Y-%m-%d %H:%M").strftime("%B %d, %Y at %I:%M %p")
            
            confirm_embed = discord.Embed(
                title="✅ Viva Evaluation Confirmed", 
                description="Your slot has been successfully reserved. Please find your details below.",
                color=discord.Color.green()
            )
            confirm_embed.add_field(name="Name", value=self.student_name.value, inline=True)
            confirm_embed.add_field(name="Cohort", value=self.cohort_name.value, inline=True)
            confirm_embed.add_field(name="Time Slot (IST)", value=display_time, inline=False)
            confirm_embed.set_footer(text="A reminder will be sent to you 5 minutes before your slot.")

            dm_status = ""
            try:
                await interaction.user.send(embed=confirm_embed)
                dm_status = "I have also sent a confirmation receipt to your DMs."
            except discord.Forbidden:
                dm_status = "⚠️ *I couldn't send a DM receipt because your DMs are closed, but your booking is confirmed!*"

            await interaction.response.send_message(f"✅ Successfully booked for **{display_time} IST**!\n{dm_status}", ephemeral=True)
            
        except sqlite3.IntegrityError:
            await interaction.response.send_message("❌ Someone just grabbed this exact slot! Please select another time.", ephemeral=True)
        finally:
            conn.close()

class TimeSelect(discord.ui.Select):
    def __init__(self, date_str: str = None):
        self.date_str = date_str
        
        # If no date is selected yet, show a locked "dummy" dropdown
        if not date_str:
            super().__init__(
                placeholder="⏰ Step 2: Please select a Date first...", 
                min_values=1, max_values=1, 
                options=[discord.SelectOption(label="...", value="none")],
                disabled=True # This locks the dropdown!
            )
            return

        # If a date IS selected, fetch the real available slots from the DB
        available_slots = get_available_slots(date_str)
        
        if not available_slots:
            options = [discord.SelectOption(label=f"All slots booked for this date", value="none")]
        else:
            options = [discord.SelectOption(
                label=datetime.strptime(slot, "%Y-%m-%d %H:%M").strftime("%I:%M %p"), 
                value=slot, 
                description="Click to book this time"
            ) for slot in available_slots]
            
        super().__init__(placeholder=f"⏰ Step 2: Select a Time...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_slot = self.values[0]
        if selected_slot == "none":
            await interaction.response.send_message("❌ There are no slots left, or this is an invalid selection.", ephemeral=True)
            return
            
        # Pop open the text form!
        await interaction.response.send_modal(BookingModal(selected_slot))

class DateSelect(discord.ui.Select):
    def __init__(self, default_date=None):
        config = load_config()
        options = [discord.SelectOption(label=d["label"], value=d["value"], description=d["desc"]) for d in config["dates"]]
        
        # If they already picked a date, make sure it stays selected visually
        if default_date:
            for opt in options:
                if opt.value == default_date:
                    opt.default = True

        super().__init__(placeholder="🗓️ Step 1: Select a Date...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_date = self.values[0]
        
        # 1. Save a safe reference to the view BEFORE we clear it!
        current_view = self.view 
        
        # 2. Clear the old view using our safe reference
        current_view.clear_items()
        
        # 3. Add the updated items back to it
        current_view.add_item(DateSelect(default_date=selected_date))
        current_view.add_item(TimeSelect(date_str=selected_date)) 
        
        # 4. Instantly update the SAME message (fixes the Discord UI bug!)
        await interaction.response.edit_message(content=f"**Date selected:** {selected_date}\nNow pick an available time slot below:", view=current_view)

class EphemeralBookingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300) 
        # Add BOTH dropdowns to the message immediately when they click the button
        self.add_item(DateSelect())
        self.add_item(TimeSelect(date_str=None)) # Passes 'None' so it starts out locked

class StartBookingButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="📅 Book Evaluation Slot", style=discord.ButtonStyle.primary, custom_id="persistent_booking_btn")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Welcome! Let's get you booked. \nFirst, select which day you'd like to do your evaluation:", 
            view=EphemeralBookingView(), 
            ephemeral=True
        )

class PersistentMainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(StartBookingButton())


# --- THE COG ---

class VivaEvaluations(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.add_view(PersistentMainView()) 
        setup_db()
        self.slot_reminder.start()

    def cog_unload(self):
        self.slot_reminder.cancel()

    @tasks.loop(minutes=1)
    async def slot_reminder(self):
        now_ist = datetime.now(IST)
        target_time = now_ist + timedelta(minutes=5)
        target_time_str = target_time.strftime("%Y-%m-%d %H:%M") 
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT discord_user_id FROM evaluations WHERE time_slot=? AND status="booked"', (target_time_str,))
        upcoming_students = cursor.fetchall()
        conn.close()

        for row in upcoming_students:
            user_id = row[0]
            user = self.bot.get_user(user_id)
            if user:
                try:
                    display_time = datetime.strptime(target_time_str, "%Y-%m-%d %H:%M").strftime("%I:%M %p")
                    await user.send(f"⏰ **Reminder:** Your Viva Evaluation starts in **5 minutes** ({display_time} IST). Please be ready!")
                except discord.Forbidden:
                    pass

    @slot_reminder.before_loop
    async def before_reminder(self):
        await self.bot.wait_until_ready()

    # --- ADMIN SLASH COMMANDS ---

    @app_commands.command(name="setup_panel", description="Deploy the booking panel for students")
    @app_commands.checks.has_role(EVALUATOR_ROLE)
    async def setup_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📅 Viva Evaluation Booking",
            description=(
                "Please click the button below to secure your time slot.\n\n"
                "**Timings:** 1:00 PM - 7:00 PM (IST)\n\n"
                "⚠️ *You may only have 1 active booking at a time. Choose carefully!*"
            ),
            color=discord.Color.brand_green()
        )
        await interaction.response.send_message(embed=embed, view=PersistentMainView())

    @app_commands.command(name="view_booking", description="View the active booking details for a specific student")
    @app_commands.checks.has_role(EVALUATOR_ROLE)
    async def view_booking(self, interaction: discord.Interaction, student: discord.Member):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT time_slot, student_name, discord_username, cohort_name, registered_email, attendance 
            FROM evaluations 
            WHERE discord_user_id=? AND status="booked"
        ''', (student.id,))
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            await interaction.response.send_message(f"❌ {student.mention} does not have an active booking.", ephemeral=True)
            return
            
        time_slot, student_name, discord_username, cohort_name, email, attendance = result
        display_time = datetime.strptime(time_slot, "%Y-%m-%d %H:%M").strftime("%B %d, %Y at %I:%M %p")
        
        embed = discord.Embed(title="📅 Booking Details", color=discord.Color.gold())
        embed.add_field(name="Student Name", value=student_name, inline=True)
        embed.add_field(name="Discord User", value=f"{student.mention} (`{discord_username}`)", inline=True)
        embed.add_field(name="Time Slot (IST)", value=display_time, inline=False)
        embed.add_field(name="Cohort", value=cohort_name, inline=True)
        embed.add_field(name="Email", value=email, inline=True)
        embed.add_field(name="Attendance", value=attendance, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="daily_schedule", description="View all booked evaluations for a specific date")
    @app_commands.checks.has_role(EVALUATOR_ROLE)
    @app_commands.describe(date="The date to view the schedule for (e.g. 2026-03-25)")
    async def daily_schedule(self, interaction: discord.Interaction, date: str = None):
        config = load_config()
        if not date:
            now_ist = datetime.now(IST)
            today_str = now_ist.strftime("%Y-%m-%d")
            valid_dates = [d["value"] for d in config["dates"]]
            date = today_str if today_str in valid_dates else valid_dates[0]

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT time_slot, student_name, discord_user_id 
            FROM evaluations 
            WHERE time_slot LIKE ? AND status="booked"
            ORDER BY time_slot ASC
        ''', (f"{date}%",))
        bookings = cursor.fetchall()
        conn.close()

        if not bookings:
            await interaction.response.send_message(f"📅 No active bookings found for **{date}**.", ephemeral=True)
            return

        embed = discord.Embed(title=f"📅 Daily Schedule: {date}", color=discord.Color.blurple())
        
        schedule_text = ""
        for slot, name, user_id in bookings:
            time_obj = datetime.strptime(slot, "%Y-%m-%d %H:%M")
            time_str = time_obj.strftime("%I:%M %p")
            schedule_text += f"**{time_str}** — {name} (<@{user_id}>)\n"

        embed.description = schedule_text
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @daily_schedule.autocomplete('date')
    async def date_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        config = load_config()
        choices = [
            app_commands.Choice(name=d['label'], value=d['value'])
            for d in config['dates'] if current.lower() in d['label'].lower() or current in d['value']
        ]
        return choices[:25]

    @app_commands.command(name="mark_attendance", description="Mark a student's attendance (Present/Absent)")
    @app_commands.checks.has_role(EVALUATOR_ROLE)
    @app_commands.choices(status=[
        app_commands.Choice(name="Present", value="Present"),
        app_commands.Choice(name="Absent", value="Absent")
    ])
    async def mark_attendance(self, interaction: discord.Interaction, student: discord.Member, status: app_commands.Choice[str]):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('SELECT time_slot FROM evaluations WHERE discord_user_id=? AND status="booked"', (student.id,))
        if not cursor.fetchone():
            await interaction.response.send_message("❌ This user does not have an active pending slot.", ephemeral=True)
            conn.close()
            return

        cursor.execute('UPDATE evaluations SET attendance=? WHERE discord_user_id=? AND status="booked"', (status.value, student.id))
        
        # If absent, we clear their active booking status so they can rebook right away
        if status.value == "Absent":
            cursor.execute('UPDATE evaluations SET status="absent" WHERE discord_user_id=? AND status="booked"', (student.id,))
            msg = f"✅ Marked {student.mention} as **Absent**. Their active slot has been cleared so they can re-book."
        else:
            msg = f"✅ Marked {student.mention} as **Present**."
            
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="cancel_booking", description="Cancel a student's active booking to free up the slot")
    @app_commands.checks.has_role(EVALUATOR_ROLE)
    async def cancel_booking(self, interaction: discord.Interaction, student: discord.Member):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT time_slot FROM evaluations WHERE discord_user_id=? AND status="booked"', (student.id,))
        if not cursor.fetchone():
            await interaction.response.send_message(f"❌ {student.mention} does not have an active booking to cancel.", ephemeral=True)
            conn.close()
            return
            
        cursor.execute('DELETE FROM evaluations WHERE discord_user_id=? AND status="booked"', (student.id,))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"✅ Successfully canceled the active booking for {student.mention}. That time slot is now open again.", ephemeral=True)

    @app_commands.command(name="grade", description="Grade a student's viva (Scores 0-4)")
    @app_commands.checks.has_role(EVALUATOR_ROLE)
    @app_commands.describe(
        student="The Discord user to grade",
        concept="Conceptual Understanding (0-4)",
        code="Interpretation of code (0-4)",
        reasoning="Reasoning (0-4)",
        error_handling="Error Handling (0-4)",
        flow="Flow Understanding (0-4)"
    )
    async def grade(self, interaction: discord.Interaction, student: discord.Member, concept: int, code: int, reasoning: int, error_handling: int, flow: int):
        total = concept + code + reasoning + error_handling + flow
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('SELECT time_slot FROM evaluations WHERE discord_user_id=? AND status="booked"', (student.id,))
        if not cursor.fetchone():
            await interaction.response.send_message("❌ This user does not have an active pending slot.", ephemeral=True)
            conn.close()
            return

        cursor.execute('''
            UPDATE evaluations 
            SET conceptual_understanding=?, interpretation_of_code=?, reasoning=?, error_handling=?, flow_understanding=?, total_score=?
            WHERE discord_user_id=? AND status='booked'
        ''', (concept, code, reasoning, error_handling, flow, total, student.id))
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(f"✅ Scores saved for {student.mention}. **Total: {total}/20**.\n*Use `/mark_done` to finalize.*", ephemeral=True)

    @app_commands.command(name="mark_done", description="Finalize the viva and send the result to the student via DM")
    @app_commands.checks.has_role(EVALUATOR_ROLE)
    async def mark_done(self, interaction: discord.Interaction, student: discord.Member):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT total_score, student_name, attendance FROM evaluations WHERE discord_user_id=? AND status="booked"', (student.id,))
        result = cursor.fetchone()
        
        if not result:
            await interaction.response.send_message("❌ No active booking found for this user, or they are already marked done.", ephemeral=True)
            conn.close()
            return
            
        total_score, student_name, attendance = result
        
        if attendance == 'Pending':
            await interaction.response.send_message("⚠️ Please use `/mark_attendance` for this student before finalizing their score.", ephemeral=True)
            conn.close()
            return
            
        cursor.execute('UPDATE evaluations SET status="done" WHERE discord_user_id=? AND status="booked"', (student.id,))
        conn.commit()
        conn.close()

        if total_score > 15:
            msg = f"🎉 **Congratulations {student_name}!** You have successfully passed your viva evaluation with a score of **{total_score}/20**."
        else:
            msg = f"Hello {student_name}, your evaluation score was **{total_score}/20**. Unfortunately, you did not pass this time. As your evaluation is complete, you may now book another slot or wait for the **'viva for endorsement'**."
        
        try:
            await student.send(msg)
            await interaction.response.send_message(f"✅ Evaluation finalized. **{student_name}** scored {total_score}/20 and has been notified.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"⚠️ Evaluation finalized. **{student_name}** scored {total_score}/20, but **I could not DM them**.", ephemeral=True)

    @app_commands.command(name="export_data", description="Export all evaluation data to a CSV file")
    @app_commands.checks.has_role(EVALUATOR_ROLE)
    async def export_data(self, interaction: discord.Interaction):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM evaluations")
        rows = cursor.fetchall()
        column_names = [description[0] for description in cursor.description]
        conn.close()
        
        filename = 'evaluation_results.csv'
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(column_names)
            writer.writerows(rows)
            
        await interaction.response.send_message("📁 Here is the complete database export:", file=discord.File(filename), ephemeral=True)

    @app_commands.command(name="help_viva", description="Shows instructions for the Viva Evaluation system")
    @app_commands.checks.has_role(EVALUATOR_ROLE)
    async def help_viva(self, interaction: discord.Interaction):
        help_text = (
            "**🛠️ Viva Evaluation System Help**\n\n"
            "All commands below are restricted to the **" + EVALUATOR_ROLE + "** role.\n\n"
            "**1️⃣ `/setup_panel`**\n"
            "Spawns the main booking button for students.\n\n"
            "**2️⃣ `/view_booking <student>`**\n"
            "View the exact time slot, email, and cohort details for a student's active booking.\n\n"
            "**3️⃣ `/daily_schedule [date]`**\n"
            "See a chronological list of all upcoming evaluation slots for a specific day.\n\n"
            "**4️⃣ `/cancel_booking <student>`**\n"
            "Deletes a student's active booking entirely, freeing up the time slot.\n\n"
            "**5️⃣ `/mark_attendance <student> <status>`**\n"
            "Mark them Present or Absent. If Absent, their active booking is cleared allowing them to rebook immediately.\n\n"
            "**6️⃣ `/grade <student> <scores...>`**\n"
            "Input rubric scores (0-4) for the selected user. It calculates the total out of 20 and stores it.\n\n"
            "**7️⃣ `/mark_done <student>`**\n"
            "Finalizes the evaluation (Requires attendance to be marked first). >15 gets a 'Pass' DM. <=15 gets a DM to rebook. This clears their active status.\n\n"
            "**8️⃣ `/export_data`**\n"
            "Generates and sends a CSV file containing all student data, choices, and scores.\n\n"
            "*To update dates/times, simply edit the `viva_config.json` file generated in your bot directory!*"
        )
        await interaction.response.send_message(help_text, ephemeral=True)

async def setup(bot):
    await bot.add_cog(VivaEvaluations(bot))