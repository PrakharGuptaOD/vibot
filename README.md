# 🤖 Vibot

Vibot is a custom-built Discord bot designed to automate community management, streamline student evaluations, and provide advanced support tools for the server. It handles everything from dynamic voice channels to thread-based ticketing, all backed by a persistent database.

## ✨ What Does Vibot Do?

### 🎫 Advanced Support Ticketing
* **Private Threads:** Users can open support tickets categorized by their specific needs, creating private threads for 1-on-1 assistance.
* **Smart Archiving:** Once a ticket is resolved, the bot automatically archives the chat transcript (as both HTML and JSON) and uploads it securely to a GitHub repository.
* **Feedback System:** Users can rate their support experience (1-5 stars) after a ticket closes, helping admins track team performance.

### 📅 Viva Evaluation Booking
* **Interactive Booking Panel:** Students can view available time slots and book their Viva evaluations directly through Discord.
* **Evaluator Dashboard:** Staff members can mark attendance, grade students on a 20-point rubric, and automatically DM the results (Pass/Fail) to the student.
* **Conflict Prevention:** The bot automatically prevents double-booking and frees up time slots if a student is marked absent.

### 🔊 Dynamic Breakout Rooms (Join-to-Create)
* **Auto-Generation:** When a user joins the designated "Join-to-Create" channel, the bot instantly creates a private, temporary voice channel for them.
* **Owner Control Panel:** The creator gets a click-button dashboard to:
    * 🔒 Lock or 🔓 Unlock the room.
    * 👥 Set a maximum user limit.
    * ➕ Grant access to specific users or 👢 Kick unwanted members.
    * ✏️ Rename the channel or 👑 Transfer ownership.
* **Auto-Cleanup:** As soon as the room is empty, the bot deletes it to keep the server clean.

### 🛡️ Authentication & Security
* **Account Verification:** Members can verify their accounts by mapping their Discord ID to their registered email address.
* **Security Guidance:** Upon verification, users receive an automated DM with a comprehensive guide on protecting their Discord accounts from phishing and takeovers.

### 👥 Cohort & Server Management
* **Automated Setup:** Admins can quickly generate text/voice channels and specific roles for new cohorts.
* **Self-Assignment:** Provides interactive dropdown panels for users to select and join their designated cohorts easily.
* **Moderation:** Includes standard server moderation tools (Warn, Kick, Ban, Timeout) with persistent warning logs.
