import discord
from discord.ext import commands
from discord.ext import tasks
import os
import asyncio
import yt_dlp as youtube_dl
from dotenv import load_dotenv
import random
import functools
import sys
import subprocess
import datetime
import re
import shutil

# Load environment variables
load_dotenv()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Find system FFmpeg
def find_ffmpeg():
    """Find the system FFmpeg executable"""
    # Try common system paths
    possible_paths = [
        '/usr/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        '/opt/homebrew/bin/ffmpeg',  # macOS with Homebrew
        'ffmpeg'  # Use system PATH
    ]
    
    for path in possible_paths:
        if path == 'ffmpeg':
            # Check if ffmpeg is in system PATH
            if shutil.which('ffmpeg'):
                print(f"Found FFmpeg in system PATH: {shutil.which('ffmpeg')}")
                return 'ffmpeg'
        else:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                print(f"Found FFmpeg at: {path}")
                return path
    
    # If not found, return None
    print("WARNING: FFmpeg not found in common locations!")
    print("Please ensure FFmpeg is installed on your Raspberry Pi:")
    print("sudo apt update && sudo apt install ffmpeg")
    return None

# Set FFmpeg executable
FFMPEG_EXECUTABLE = find_ffmpeg()

# Updated YouTube DL options - Fixed format selection
ytdl_format_options = {
    'format': 'bestaudio/best',  # Simplified format selection
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extractaudio': True,
    'audioformat': 'mp3',
    'audioquality': '192K',
}

# Updated FFmpeg options with better error handling
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -filter:a "volume=0.5"'
}

# Set FFmpeg executable for discord.py if found
if FFMPEG_EXECUTABLE:
    discord.FFmpegPCMAudio.FFMPEG_EXECUTABLE = FFMPEG_EXECUTABLE
    discord.FFmpegOpusAudio.FFMPEG_EXECUTABLE = FFMPEG_EXECUTABLE
    print(f"Discord.py configured to use FFmpeg at: {FFMPEG_EXECUTABLE}")
else:
    print("ERROR: FFmpeg not found! Music playback will not work.")
    print("Install FFmpeg on your Raspberry Pi with:")
    print("sudo apt update && sudo apt install ffmpeg")

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url')
        self.thumbnail = data.get('thumbnail', 'https://i.imgur.com/8QZQZ.png')
        self.duration = data.get('duration', 0)

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        
        # Enhanced error handling for format extraction
        to_run = functools.partial(ytdl.extract_info, url, download=not stream)
        try:
            data = await loop.run_in_executor(None, to_run)
        except youtube_dl.DownloadError as e:
            # Try with alternative format if first attempt fails
            print(f"Primary format failed, trying alternative: {e}")
            
            # Create alternative ytdl instance with more permissive format
            alt_ytdl_opts = ytdl_format_options.copy()
            alt_ytdl_opts['format'] = 'worst'  # Use worst quality as fallback
            alt_ytdl = youtube_dl.YoutubeDL(alt_ytdl_opts)
            
            alt_to_run = functools.partial(alt_ytdl.extract_info, url, download=not stream)
            try:
                data = await loop.run_in_executor(None, alt_to_run)
                print("Alternative format extraction successful")
            except Exception as alt_e:
                print(f"Alternative format also failed: {alt_e}")
                raise alt_e
        except Exception as e:
            print(f"Error extracting info: {e}")
            raise e
        
        if 'entries' in data:
            # Take first item from a playlist
            data = data['entries'][0]
        
        if stream:
            filename = data['url']
        else:
            filename = ytdl.prepare_filename(data)
        
        print(f"Playing: {data.get('title')} - URL: {filename}")
        
        # Check if FFmpeg is available before creating audio source
        if not FFMPEG_EXECUTABLE:
            raise Exception("FFmpeg not found! Please install FFmpeg on your system.")
        
        # Create the audio source with system FFmpeg
        try:
            audio_source = discord.FFmpegPCMAudio(filename, **ffmpeg_options)
            return cls(audio_source, data=data)
        except Exception as e:
            print(f"Error creating FFmpeg audio source: {e}")
            # Try without additional options as fallback
            try:
                audio_source = discord.FFmpegPCMAudio(filename)
                return cls(audio_source, data=data)
            except Exception as e2:
                print(f"Fallback audio creation also failed: {e2}")
                raise e2

# Music queue for each guild
music_queues = {}

# Maintenance mode variables
maintenance_mode = False
maintenance_end_time = None
maintenance_message = "Bot is currently under maintenance. Please try again later."

class MusicQueue:
    def __init__(self):
        self.queue = []
        self.current = None
        self.volume = 0.5
        self.loop_current = False
        self.loop_queue = False

    def add(self, song):
        self.queue.append(song)

    def get_next(self):
        if self.queue:
            return self.queue.pop(0)
        return None

    def clear(self):
        self.queue.clear()
        self.current = None

    def shuffle(self):
        random.shuffle(self.queue)

# Role Selection View
class RoleSelectionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view
    
    @discord.ui.button(label="Member", style=discord.ButtonStyle.primary, custom_id="role_member")
    async def member_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_role_toggle(interaction, "Member")
    
    @discord.ui.button(label="Gamer", style=discord.ButtonStyle.success, custom_id="role_gamer")
    async def gamer_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_role_toggle(interaction, "Gamer")
    
    @discord.ui.button(label="Valorant", style=discord.ButtonStyle.danger, custom_id="role_valorant")
    async def valorant_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_role_toggle(interaction, "Valorant")
    
    @discord.ui.button(label="CS2", style=discord.ButtonStyle.secondary, custom_id="role_cs2")
    async def cs2_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_role_toggle(interaction, "CS2")
    
    @discord.ui.button(label="Minecraft", style=discord.ButtonStyle.success, custom_id="role_minecraft", row=1)
    async def minecraft_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_role_toggle(interaction, "Minecraft")
    
    @discord.ui.button(label="GTA V", style=discord.ButtonStyle.blurple, custom_id="role_gtav", row=1)
    async def gtav_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_role_toggle(interaction, "GTA V")
    
    async def handle_role_toggle(self, interaction: discord.Interaction, role_name: str):
        """Handle adding/removing roles"""
        try:
            if interaction.response.is_done():
                return
            
            guild = interaction.guild
            user = interaction.user
            
            role = discord.utils.get(guild.roles, name=role_name)
            
            if not role:
                try:
                    role = await guild.create_role(
                        name=role_name,
                        mentionable=True,
                        reason=f"Auto-created role for role selection system"
                    )
                except discord.Forbidden:
                    embed = discord.Embed(
                        title="Permission Error",
                        description=f"The role **{role_name}** doesn't exist and I don't have permission to create it!",
                        color=0xed4245
                    )
                    embed.set_footer(text="Only you can see this")
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
            
            if role in user.roles:
                try:
                    await user.remove_roles(role, reason="Self-role removal via role selection")
                    embed = discord.Embed(
                        title="Role Removed",
                        description=f"Successfully removed the **{role_name}** role from you!",
                        color=0xfee75c
                    )
                    embed.set_footer(text="Only you can see this")
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                except discord.Forbidden:
                    embed = discord.Embed(
                        title="Permission Error",
                        description=f"I don't have permission to remove the **{role_name}** role!",
                        color=0xed4245
                    )
                    embed.set_footer(text="Only you can see this")
                    await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                try:
                    await user.add_roles(role, reason="Self-role assignment via role selection")
                    embed = discord.Embed(
                        title="Role Added",
                        description=f"Successfully added the **{role_name}** role to you!",
                        color=0x57f287
                    )
                    embed.set_footer(text="Only you can see this")
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                except discord.Forbidden:
                    embed = discord.Embed(
                        title="Permission Error",
                        description=f"I don't have permission to add the **{role_name}** role!",
                        color=0xed4245
                    )
                    embed.set_footer(text="Only you can see this")
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    
        except Exception as e:
            if not interaction.response.is_done():
                embed = discord.Embed(
                    title="Error",
                    description=f"An unexpected error occurred: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}",
                    color=0xed4245
                )
                embed.set_footer(text="Only you can see this")
                await interaction.response.send_message(embed=embed, ephemeral=True)

# Error dismiss view for private error messages
class ErrorDismissView(discord.ui.View):
    def __init__(self, author_id, timeout=60):
        super().__init__(timeout=timeout)
        self.author_id = author_id
    
    @discord.ui.button(label="Got it", style=discord.ButtonStyle.secondary, emoji="✅")
    async def dismiss_error(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            try:
                await interaction.response.send_message("❌ Only the original command user can dismiss this.", ephemeral=True)
            except:
                pass
            return
        
        try:
            await interaction.response.edit_message(content="✅ **Error acknowledged**", embed=None, view=None)
            await asyncio.sleep(2)
            await interaction.delete_original_response()
        except Exception:
            pass
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            if hasattr(self, 'message') and self.message:
                await self.message.edit(view=self)
                await asyncio.sleep(3)
                await self.message.delete()
        except:
            pass

# Helper function to send private error messages
async def send_private_error(ctx, embed, use_button=False, timeout=30):
    """Send a private error message to user"""
    try:
        if use_button:
            view = ErrorDismissView(ctx.author.id, timeout=timeout)
            message = await ctx.author.send(embed=embed, view=view)
            view.message = message
        else:
            message = await ctx.author.send(embed=embed)
            # Auto-delete after timeout
            async def delete_after():
                try:
                    await asyncio.sleep(timeout)
                    await message.delete()
                except:
                    pass
            asyncio.create_task(delete_after())
            
    except (discord.Forbidden, discord.HTTPException):
        # DM failed, send in channel with mention
        try:
            if use_button:
                embed.add_field(name="Note", value=f"Only {ctx.author.mention} can interact with this", inline=False)
                view = ErrorDismissView(ctx.author.id, timeout=timeout)
                message = await ctx.send(embed=embed, view=view)
                view.message = message
            else:
                embed.set_footer(text=f"This message will auto-delete in {timeout//2} seconds")
                message = await ctx.send(f"{ctx.author.mention}", embed=embed)
                # Auto-delete after shorter timeout in channel
                async def delete_after():
                    try:
                        await asyncio.sleep(timeout//2)
                        await message.delete()
                    except:
                        pass
                asyncio.create_task(delete_after())
                
        except (discord.Forbidden, discord.HTTPException):
            print(f"Could not send error message to {ctx.author}: {embed.description}")

# Helper function to update bot status
async def update_bot_status():
    """Update bot status based on maintenance mode"""
    try:
        if maintenance_mode:
            activity = discord.Activity(type=discord.ActivityType.watching, name="Under Maintenance")
            status = discord.Status.do_not_disturb
        else:
            activity = discord.Game(name="Music Bot | !help for commands")
            status = discord.Status.online
        
        await bot.change_presence(activity=activity, status=status)
    except Exception as e:
        print(f"Error updating bot status: {e}")

# Helper function to update bot status
async def update_bot_status():
    """Update bot status based on maintenance mode"""
    try:
        if maintenance_mode:
            activity = discord.Activity(type=discord.ActivityType.watching, name="Under Maintenance")
            status = discord.Status.do_not_disturb
        else:
            activity = discord.Game(name="Music Bot | !help for commands")
            status = discord.Status.online
        
        await bot.change_presence(activity=activity, status=status)
    except Exception as e:
        print(f"Error updating bot status: {e}")

# Helper function to check maintenance mode
async def check_maintenance():
    """Check if maintenance mode should be disabled"""
    global maintenance_mode, maintenance_end_time
    if maintenance_mode and maintenance_end_time:
        current_time = datetime.datetime.now()
        if current_time >= maintenance_end_time:
            maintenance_mode = False
            maintenance_end_time = None
            print(f"Maintenance mode automatically disabled at {current_time.strftime('%H:%M:%S')}")
            await update_bot_status()
            return True  # Indicates maintenance was disabled
    return False  # No change in maintenance status

async def is_maintenance_active():
    """Check if bot is in maintenance mode"""
    await check_maintenance()
    return maintenance_mode

# Background task to check maintenance mode automatically
@tasks.loop(minutes=1)  # Check every minute
async def maintenance_checker():
    """Background task to check maintenance mode expiry"""
    try:
        if await check_maintenance():
            print("Background maintenance check: Maintenance mode disabled")
    except Exception as e:
        print(f"Error in maintenance checker: {e}")

@maintenance_checker.before_loop
async def before_maintenance_checker():
    """Wait until bot is ready before starting maintenance checker"""
    await bot.wait_until_ready()

# Maintenance mode decorator
def maintenance_check():
    async def predicate(ctx):
        if await is_maintenance_active():
            OWNER_ID = int(os.getenv('OWNER_ID', '0'))
            if ctx.author.id != OWNER_ID:
                time_left = ""
                if maintenance_end_time:
                    remaining = maintenance_end_time - datetime.datetime.now()
                    if remaining.total_seconds() > 0:
                        hours = int(remaining.total_seconds() // 3600)
                        minutes = int((remaining.total_seconds() % 3600) // 60)
                        if hours > 0:
                            time_left = f"\n**Time remaining:** {hours}h {minutes}m"
                        else:
                            time_left = f"\n**Time remaining:** {minutes}m"
                
                embed = discord.Embed(
                    title="Maintenance Mode",
                    description=f"{maintenance_message}{time_left}",
                    color=0xffa94d
                )
                await ctx.send(embed=embed)
                return False
        return True
    return commands.check(predicate)

# Helper function to automatically join user's voice channel
async def ensure_voice_connection(ctx):
    """Ensure bot is connected to the user's voice channel"""
    if not ctx.author.voice:
        embed = discord.Embed(
            title="Voice Channel Required",
            description="You need to be in a voice channel to use music commands!",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)
        return False
    
    user_channel = ctx.author.voice.channel
    
    if not ctx.voice_client:
        try:
            await user_channel.connect()
            if ctx.guild.id not in music_queues:
                music_queues[ctx.guild.id] = MusicQueue()
            
            embed = discord.Embed(
                title="Voice Channel Joined",
                description=f"Automatically connected to **{user_channel.name}**",
                color=0x51cf66
            )
            await ctx.send(embed=embed)
            return True
        except Exception as e:
            embed = discord.Embed(
                title="Connection Failed",
                description=f"Couldn't join voice channel: {str(e)}",
                color=0xff6b6b
            )
            await ctx.send(embed=embed)
            return False
    
    elif ctx.voice_client.channel != user_channel:
        try:
            await ctx.voice_client.move_to(user_channel)
            embed = discord.Embed(
                title="Voice Channel Moved",
                description=f"Moved to **{user_channel.name}**",
                color=0x51cf66
            )
            await ctx.send(embed=embed)
            return True
        except Exception as e:
            embed = discord.Embed(
                title="Move Failed",
                description=f"Couldn't move to voice channel: {str(e)}",
                color=0xff6b6b
            )
            await ctx.send(embed=embed)
            return False
    
    return True

# Bot events
@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is ready and connected to {len(bot.guilds)} servers')
    
    # Check FFmpeg availability
    if FFMPEG_EXECUTABLE:
        print(f"✅ FFmpeg is available at: {FFMPEG_EXECUTABLE}")
        try:
            # Test FFmpeg
            result = subprocess.run([FFMPEG_EXECUTABLE, '-version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version_line = result.stdout.split('\n')[0]
                print(f"✅ FFmpeg test successful: {version_line}")
            else:
                print("⚠️ FFmpeg test failed but executable found")
        except Exception as e:
            print(f"⚠️ FFmpeg test error: {e}")
    else:
        print("❌ FFmpeg not found! Music playback will not work.")
        print("Install with: sudo apt update && sudo apt install ffmpeg")
    
    # Add persistent views for role selection
    bot.add_view(RoleSelectionView())
    
    await update_bot_status()

# Add FFmpeg status command
@bot.command(name='ffmpeg')
async def ffmpeg_status(ctx):
    """Check FFmpeg installation status"""
    embed = discord.Embed(title="FFmpeg Status", color=0x339af0)
    
    if FFMPEG_EXECUTABLE:
        try:
            result = subprocess.run([FFMPEG_EXECUTABLE, '-version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version_info = result.stdout.split('\n')[0]
                embed.add_field(name="Status", value="✅ Available", inline=True)
                embed.add_field(name="Path", value=f"`{FFMPEG_EXECUTABLE}`", inline=True)
                embed.add_field(name="Version", value=f"`{version_info}`", inline=False)
                embed.color = 0x51cf66
            else:
                embed.add_field(name="Status", value="❌ Error running FFmpeg", inline=True)
                embed.add_field(name="Path", value=f"`{FFMPEG_EXECUTABLE}`", inline=True)
                embed.color = 0xff6b6b
        except Exception as e:
            embed.add_field(name="Status", value="❌ Test failed", inline=True)
            embed.add_field(name="Error", value=f"`{str(e)}`", inline=True)
            embed.color = 0xff6b6b
    else:
        embed.add_field(name="Status", value="❌ Not found", inline=True)
        embed.add_field(name="Solution", value="Install with: `sudo apt install ffmpeg`", inline=False)
        embed.color = 0xff6b6b
    
    await ctx.send(embed=embed)

@bot.event
async def on_member_join(member):
    """Handle new member joining - send role selection message"""
    print(f"New member joined: {member} ({member.id}) in {member.guild.name}")
    
    try:
        embed = discord.Embed(
            title="Welcome to the Server!",
            description="Choose your roles to customize your server experience!",
            color=0x5865f2
        )
        
        embed.add_field(
            name="Available Roles",
            value="**Member** - General server member\n"
                  "**Gamer** - Gaming enthusiast\n"
                  "**Valorant** - Valorant player\n"
                  "**CS2** - Counter-Strike 2 player\n"
                  "**Minecraft** - Minecraft player\n"
                  "**GTA V** - Grand Theft Auto V player",
            inline=False
        )
        
        embed.add_field(
            name="How it works",
            value="• Click a button to **add** a role\n"
                  "• Click again to **remove** it\n"
                  "• You can have multiple roles",
            inline=False
        )
        
        embed.set_footer(text="Use this panel anytime to manage your roles!")
        
        view = RoleSelectionView()
        
        # Try to send DM first
        try:
            await member.send(embed=embed, view=view)
            print(f"Welcome message sent via DM to {member}")
        except discord.Forbidden:
            # Find a welcome channel
            welcome_channels = ['welcome', 'general', 'lobby', 'main', 'chat']
            welcome_channel = None
            
            for channel_name in welcome_channels:
                welcome_channel = discord.utils.get(member.guild.text_channels, name=channel_name)
                if welcome_channel and welcome_channel.permissions_for(member.guild.me).send_messages:
                    break
            
            if welcome_channel:
                await welcome_channel.send(f"{member.mention}", embed=embed, view=view)
                print(f"Welcome message sent to #{welcome_channel.name}")
            else:
                print(f"Could not send welcome message to {member} - no suitable channel found")
                
    except Exception as e:
        print(f"Error sending welcome message to {member}: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    """Handle voice state updates to disconnect bot when alone"""
    if member == bot.user:
        return
    
    voice_client = discord.utils.get(bot.voice_clients, guild=member.guild)
    if voice_client and voice_client.channel:
        if len(voice_client.channel.members) == 1:
            await asyncio.sleep(30)
            if voice_client and voice_client.channel and len(voice_client.channel.members) == 1:
                await voice_client.disconnect()
                if member.guild.id in music_queues:
                    music_queues[member.guild.id].clear()

# Enhanced error handling
@bot.event
async def on_command_error(ctx, error):
    """Handle command errors with private messages"""
    if hasattr(ctx, '_error_handled') and ctx._error_handled:
        return
    
    ctx._error_handled = True
    
    # Helper to safely delete command message
    async def safe_delete():
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
    
    if isinstance(error, commands.CommandNotFound):
        await safe_delete()
        
        try:
            invalid_command = ctx.message.content.split()[0] if ctx.message.content else "unknown command"
        except:
            invalid_command = "unknown command"
        
        embed = discord.Embed(
            title="Unknown Command",
            description=f"The command `{invalid_command}` doesn't exist!\n\n"
                       "**Suggestions:**\n"
                       "• Use `!help` to see all available commands\n"
                       "• Check your spelling and try again\n"
                       "• Make sure you're using the `!` prefix",
            color=0xed4245
        )
        embed.add_field(
            name="Popular Commands",
            value="`!play <song>` - Play music\n"
                  "`!roles` - Select your roles\n"
                  "`!help` - Show all commands",
            inline=True
        )
        embed.set_footer(text="Only you can see this • Auto-deletes in 30 seconds")
        
        await send_private_error(ctx, embed, use_button=True, timeout=30)
        
    elif isinstance(error, commands.MissingRequiredArgument):
        await safe_delete()
        
        embed = discord.Embed(
            title="Missing Argument",
            description="You're missing a required argument for this command!\n\n"
                       "**Tip:** Use `!help` to see the correct usage for all commands.",
            color=0xfee75c
        )
        embed.set_footer(text="Only you can see this")
        
        await send_private_error(ctx, embed, use_button=False, timeout=20)
        
    elif isinstance(error, commands.MissingPermissions):
        await safe_delete()
        
        try:
            permissions = ", ".join(error.missing_permissions)
        except:
            permissions = "required permissions"
        
        embed = discord.Embed(
            title="Permission Denied",
            description=f"You don't have the required permissions to use this command!\n\n"
                       f"**Required permissions:** {permissions}",
            color=0xed4245
        )
        embed.set_footer(text="Only you can see this")
        
        await send_private_error(ctx, embed, use_button=False, timeout=25)
        
    elif isinstance(error, commands.BotMissingPermissions):
        await safe_delete()
        
        try:
            permissions = ", ".join(error.missing_permissions)
        except:
            permissions = "required permissions"
        
        embed = discord.Embed(
            title="Bot Permission Missing",
            description=f"I don't have the required permissions to execute this command!\n\n"
                       f"**Missing permissions:** {permissions}\n\n"
                       "Please ask an administrator to grant me these permissions.",
            color=0xed4245
        )
        embed.set_footer(text="Only you can see this")
        
        await send_private_error(ctx, embed, use_button=False, timeout=30)
        
    elif isinstance(error, commands.CommandOnCooldown):
        await safe_delete()
        
        try:
            retry_after = f"{error.retry_after:.1f}"
        except:
            retry_after = "a few"
        
        embed = discord.Embed(
            title="Command Cooldown",
            description=f"This command is on cooldown!\n\n"
                       f"**Try again in:** {retry_after} seconds",
            color=0xfee75c
        )
        embed.set_footer(text="Only you can see this")
        
        await send_private_error(ctx, embed, use_button=False, timeout=15)
        
    elif isinstance(error, commands.CheckFailure):
        # Don't send private messages for check failures (like maintenance mode)
        pass
        
    else:
        # Log unexpected errors
        try:
            error_text = str(error)[:100] + ('...' if len(str(error)) > 100 else '')
        except:
            error_text = "An unexpected error occurred"
        
        print(f"Unexpected error in {ctx.command if ctx.command else 'unknown command'}: {error}")
        
        embed = discord.Embed(
            title="Command Error",
            description=f"An unexpected error occurred while executing this command.\n\n"
                       f"**Error:** {error_text}",
            color=0xed4245
        )
        embed.set_footer(text="If this persists, please contact the bot administrator")
        
        await send_private_error(ctx, embed, use_button=False, timeout=30)

# Voice commands
@bot.command(name='join')
async def join(ctx):
    """Join the voice channel"""
    if not ctx.author.voice:
        embed = discord.Embed(
            title="Voice Channel Required",
            description="You need to be in a voice channel first!",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)
        return
    
    try:
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            if ctx.voice_client.channel == channel:
                embed = discord.Embed(
                    title="Already Connected",
                    description="I'm already in your voice channel!",
                    color=0x4ecdc4
                )
                await ctx.send(embed=embed)
                return
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        
        if ctx.guild.id not in music_queues:
            music_queues[ctx.guild.id] = MusicQueue()
        
        embed = discord.Embed(
            title="Voice Channel Joined",
            description=f"Successfully connected to **{channel.name}**",
            color=0x51cf66
        )
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="Connection Failed",
            description=f"Couldn't join voice channel: {str(e)}",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)

@bot.command(name='leave', aliases=['disconnect'])
async def leave(ctx):
    """Leave the voice channel"""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        if ctx.guild.id in music_queues:
            music_queues[ctx.guild.id].clear()
        
        embed = discord.Embed(
            title="Voice Channel Left",
            description="Successfully disconnected from voice channel",
            color=0xffa94d
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="Not Connected",
            description="I'm not currently in a voice channel!",
            color=0xff8787
        )
        await ctx.send(embed=embed)

# Music commands
@bot.command(name='play', aliases=['p'])
@maintenance_check()
async def play(ctx, *, search=None):
    """Play a song from YouTube"""
    if not search:
        embed = discord.Embed(
            title="Search Required",
            description="Please provide a song name or YouTube URL to play!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    if not await ensure_voice_connection(ctx):
        return
    
    if ctx.guild.id not in music_queues:
        music_queues[ctx.guild.id] = MusicQueue()
    
    queue = music_queues[ctx.guild.id]
    
    try:
        async with ctx.typing():
            if not search.startswith(('http://', 'https://')):
                search = f"ytsearch:{search}"
            
            player = await YTDLSource.from_url(search, loop=bot.loop, stream=True)
            
            song_info = {'player': player, 'ctx': ctx, 'requester': ctx.author}
            
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                queue.add(song_info)
                embed = discord.Embed(
                    title="Song Added to Queue",
                    description=f"**{player.title}**",
                    color=0x51cf66
                )
                embed.add_field(name="Position in Queue", value=f"#{len(queue.queue)}", inline=True)
                embed.add_field(name="Requested by", value=ctx.author.mention, inline=True)
                if player.thumbnail:
                    embed.set_thumbnail(url=player.thumbnail)
                await ctx.send(embed=embed)
            else:
                queue.current = song_info
                try:
                    def after_playing(error):
                        if error:
                            print(f'Player error: {error}')
                        else:
                            coro = play_next(ctx)
                            fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
                            try:
                                fut.result()
                            except Exception as e:
                                print(f"Error in after_playing: {e}")
                    
                    ctx.voice_client.play(player, after=after_playing)
                    await now_playing(ctx)
                except Exception as e:
                    print(f"Error starting playback: {e}")
                    embed = discord.Embed(
                        title="Playback Error",
                        description=f"Failed to start playing: {str(e)}",
                        color=0xff6b6b
                    )
                    await ctx.send(embed=embed)
                
    except Exception as e:
        embed = discord.Embed(
            title="Song Load Error",
            description=f"Failed to load song: {str(e)}",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)
        print(f"Error in play command: {e}")

async def play_next(ctx):
    """Play the next song in queue"""
    if ctx.guild.id not in music_queues:
        return
    
    queue = music_queues[ctx.guild.id]
    
    if ctx.voice_client and ctx.voice_client.is_connected():
        next_song = queue.get_next()
        
        if next_song:
            queue.current = next_song
            try:
                def after_playing(error):
                    if error:
                        print(f'Player error: {error}')
                    else:
                        coro = play_next(ctx)
                        fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
                        try:
                            fut.result()
                        except Exception as e:
                            print(f"Error in after_playing next: {e}")
                
                ctx.voice_client.play(next_song['player'], after=after_playing)
                await now_playing(ctx)
            except Exception as e:
                print(f"Error playing next song: {e}")
                await asyncio.sleep(1)
                asyncio.create_task(play_next(ctx))
        else:
            queue.current = None

@bot.command(name='skip', aliases=['s'])
@maintenance_check()
async def skip(ctx):
    """Skip the current song"""
    if not await ensure_voice_connection(ctx):
        return
    
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        ctx.voice_client.stop()
        embed = discord.Embed(
            title="Song Skipped",
            description="Successfully skipped to the next song",
            color=0x51cf66
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="Nothing Playing",
            description="There's nothing currently playing to skip!",
            color=0xff8787
        )
        await ctx.send(embed=embed)

@bot.command(name='pause')
@maintenance_check()
async def pause(ctx):
    """Pause the current song"""
    if not await ensure_voice_connection(ctx):
        return
    
    if ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        embed = discord.Embed(
            title="Music Paused",
            description="Playback has been paused",
            color=0xffd43b
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="Nothing Playing",
            description="There's nothing currently playing to pause!",
            color=0xff8787
        )
        await ctx.send(embed=embed)

@bot.command(name='stop')
@maintenance_check()
async def stop(ctx):
    """Stop playing and clear queue"""
    if not await ensure_voice_connection(ctx):
        return
    
    if ctx.guild.id in music_queues:
        music_queues[ctx.guild.id].clear()
    
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        ctx.voice_client.stop()
    
    embed = discord.Embed(
        title="Music Stopped",
        description="Playback stopped and queue cleared",
        color=0xff6b6b
    )
    await ctx.send(embed=embed)

# Queue management
@bot.command(name='queue', aliases=['q'])
@maintenance_check()
async def show_queue(ctx):
    """Show the current queue"""
    if ctx.guild.id not in music_queues:
        embed = discord.Embed(
            title="Queue Empty",
            description="The music queue is currently empty!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    queue = music_queues[ctx.guild.id]
    
    embed = discord.Embed(title="Music Queue", color=0x339af0)
    
    if queue.current:
        current_song = queue.current['player']
        embed.add_field(
            name="Now Playing", 
            value=f"**[{current_song.title}]({current_song.url})**\nRequested by: {queue.current['requester'].mention}",
            inline=False
        )
    
    if queue.queue:
        queue_text = ""
        total_duration = 0
        for i, song in enumerate(queue.queue[:10], 1):
            duration = song['player'].duration if song['player'].duration else 0
            total_duration += duration
            duration_str = f"{duration//60}:{duration%60:02d}" if duration > 0 else "Unknown"
            queue_text += f"`{i}.` **{song['player'].title[:40]}{'...' if len(song['player'].title) > 40 else ''}** `[{duration_str}]`\n"
        
        if len(queue.queue) > 10:
            queue_text += f"... and **{len(queue.queue) - 10}** more songs"
        
        embed.add_field(name="Up Next", value=queue_text, inline=False)
        
        total_duration_str = f"{total_duration//3600}:{(total_duration%3600)//60:02d}:{total_duration%60:02d}"
        embed.set_footer(text=f"Total songs in queue: {len(queue.queue)} | Total duration: {total_duration_str}")
    else:
        embed.add_field(name="Up Next", value="Queue is empty", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='nowplaying', aliases=['np'])
@maintenance_check()
async def now_playing(ctx):
    """Show the currently playing song"""
    if ctx.guild.id not in music_queues or not music_queues[ctx.guild.id].current:
        embed = discord.Embed(
            title="Nothing Playing",
            description="No music is currently playing!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    queue = music_queues[ctx.guild.id]
    current = queue.current['player']
    requester = queue.current['requester']
    
    embed = discord.Embed(title="Now Playing", color=0x339af0)
    embed.add_field(name="Title", value=f"**[{current.title}]({current.url})**", inline=False)
    embed.add_field(name="Requested by", value=requester.mention, inline=True)
    
    if current.duration:
        duration_str = f"{current.duration//60}:{current.duration%60:02d}"
        embed.add_field(name="Duration", value=duration_str, inline=True)
    
    queue_length = len(queue.queue)
    if queue_length > 0:
        embed.add_field(name="Songs in Queue", value=str(queue_length), inline=True)
    
    if current.thumbnail:
        embed.set_thumbnail(url=current.thumbnail)
    
    await ctx.send(embed=embed)

@bot.command(name='shuffle')
@maintenance_check()
async def shuffle_queue(ctx):
    """Shuffle the current queue"""
    if ctx.guild.id not in music_queues:
        embed = discord.Embed(
            title="Queue Empty",
            description="The music queue is currently empty!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    queue = music_queues[ctx.guild.id]
    if not queue.queue:
        embed = discord.Embed(
            title="Queue Empty",
            description="The music queue is currently empty!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    queue.shuffle()
    embed = discord.Embed(
        title="Queue Shuffled",
        description=f"Successfully shuffled **{len(queue.queue)}** songs in the queue",
        color=0x51cf66
    )
    await ctx.send(embed=embed)

# Message management
@bot.command(name='clear', aliases=['purge'])
@commands.has_permissions(manage_messages=True)
async def clear_messages(ctx, amount: int = 1):
    """Delete specified number of messages (default: 1)"""
    ctx._error_handled = True
    
    try:
        if amount < 1:
            embed = discord.Embed(
                title="Invalid Amount",
                description="Please provide a number greater than 0!",
                color=0xff6b6b
            )
            await ctx.send(embed=embed, delete_after=5)
            return
        
        if amount > 100:
            embed = discord.Embed(
                title="Amount Too Large",
                description="Discord limits bulk deletion to 100 messages at once!",
                color=0xff6b6b
            )
            await ctx.send(embed=embed, delete_after=5)
            return
        
        if not ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            embed = discord.Embed(
                title="Bot Permission Missing",
                description="I don't have the `Manage Messages` permission in this channel!",
                color=0xff6b6b
            )
            await ctx.send(embed=embed, delete_after=10)
            return
        
        try:
            await ctx.message.delete()
        except discord.NotFound:
            pass
        except discord.Forbidden:
            embed = discord.Embed(
                title="Permission Error",
                description="I can't delete your command message. Make sure I have proper permissions!",
                color=0xff6b6b
            )
            await ctx.send(embed=embed, delete_after=10)
            return
        
        deleted = await ctx.channel.purge(limit=amount, check=lambda m: True)
        
        embed = discord.Embed(
            title="Messages Cleared",
            description=f"Successfully deleted **{len(deleted)}** message{'s' if len(deleted) != 1 else ''}",
            color=0x51cf66
        )
        
        success_msg = await ctx.send(embed=embed)
        await asyncio.sleep(3)
        try:
            await success_msg.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
            
    except commands.MissingPermissions:
        ctx._error_handled = False
        raise
        
    except discord.Forbidden:
        embed = discord.Embed(
            title="Permission Denied",
            description="I don't have permission to delete messages in this channel!\n\n"
                       "**Required permissions:**\n• Manage Messages\n• Read Message History",
            color=0xff6b6b
        )
        await ctx.send(embed=embed, delete_after=15)
        
    except discord.HTTPException as e:
        if "Cannot delete messages older than 14 days" in str(e):
            embed = discord.Embed(
                title="Delete Failed",
                description="Cannot delete messages older than 14 days due to Discord limitations!",
                color=0xff6b6b
            )
        else:
            embed = discord.Embed(
                title="Delete Failed",
                description=f"Failed to delete messages: {str(e)[:200]}{'...' if len(str(e)) > 200 else ''}",
                color=0xff6b6b
            )
        await ctx.send(embed=embed, delete_after=15)
        
    except Exception as e:
        print(f"Unexpected error in clear command: {e}")
        embed = discord.Embed(
            title="Unexpected Error",
            description=f"An unexpected error occurred: {str(e)[:150]}{'...' if len(str(e)) > 150 else ''}",
            color=0xff6b6b
        )
        await ctx.send(embed=embed, delete_after=15)

# Role management commands
@bot.command(name='roles')
async def show_roles_panel(ctx):
    """Show the role selection panel"""
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass
    
    embed = discord.Embed(
        title="Role Selection Panel",
        description="Choose your roles to customize your server experience and connect with other members who share your interests!",
        color=0x5865f2
    )
    
    embed.add_field(
        name="Available Roles",
        value="**Member** - General server member\n"
              "**Gamer** - Gaming enthusiast\n"
              "**Valorant** - Valorant player\n"
              "**CS2** - Counter-Strike 2 player\n"
              "**Minecraft** - Minecraft player\n"
              "**GTA V** - Grand Theft Auto V player",
        inline=False
    )
    
    embed.add_field(
        name="How it works",
        value="• Click a button to **add** a role\n"
              "• Click again to **remove** it\n"
              "• You can have multiple roles\n"
              "• **All responses are private** - only you can see them!",
        inline=False
    )
    
    embed.set_footer(text="Use this panel anytime to manage your roles!")
    
    view = RoleSelectionView()
    await ctx.send(embed=embed, view=view)

@bot.command(name='myroles')
async def show_my_roles(ctx):
    """Show user's current roles"""
    user_roles = [role for role in ctx.author.roles if role.name != "@everyone"]
    
    if user_roles:
        role_list = "\n".join([f"• {role.mention}" for role in user_roles])
        embed = discord.Embed(
            title="Your Current Roles",
            description=f"Here are all your current roles:\n\n{role_list}",
            color=0x51cf66
        )
    else:
        embed = discord.Embed(
            title="Your Current Roles",
            description="You don't have any roles yet!\nUse `!roles` to select some roles.",
            color=0xff8787
        )
    
    embed.set_footer(text=f"Total roles: {len(user_roles)}")
    await ctx.send(embed=embed)

@bot.command(name='roleinfo')
async def role_info(ctx, *, role_name=None):
    """Get information about a specific role"""
    if not role_name:
        embed = discord.Embed(
            title="Role Information",
            description="Please specify a role name!\n**Usage:** `!roleinfo Member`",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    
    if not role:
        embed = discord.Embed(
            title="Role Not Found",
            description=f"The role **{role_name}** doesn't exist in this server!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    embed = discord.Embed(
        title=f"Role Information: {role.name}",
        color=role.color if role.color != discord.Color.default() else 0x339af0
    )
    
    embed.add_field(name="Role ID", value=role.id, inline=True)
    embed.add_field(name="Members", value=len(role.members), inline=True)
    embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
    embed.add_field(name="Created", value=role.created_at.strftime("%B %d, %Y"), inline=True)
    embed.add_field(name="Position", value=role.position, inline=True)
    embed.add_field(name="Color", value=str(role.color), inline=True)
    
    if role.members:
        member_list = ", ".join([member.display_name for member in role.members[:10]])
        if len(role.members) > 10:
            member_list += f" and {len(role.members) - 10} more..."
        embed.add_field(name="Some Members", value=member_list, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='help')
async def help_command(ctx):
    """Show all available commands"""
    embed = discord.Embed(
        title="Music Bot Commands",
        description="Complete command guide for the music bot",
        color=0x339af0
    )
    
    embed.add_field(
        name="Voice Commands",
        value="`!join` - Join your voice channel\n"
              "`!leave` or `!disconnect` - Leave voice channel",
        inline=False
    )
    
    embed.add_field(
        name="Music Commands (Auto-joins your channel)",
        value="`!play <query>` or `!p <query>` - Play a song from YouTube\n"
              "`!pause` - Pause current song\n"
              "`!resume` or `!unpause` - Resume paused song\n"
              "`!skip` or `!s` - Skip current song\n"
              "`!stop` - Stop playing and clear queue",
        inline=False
    )
    
    embed.add_field(
        name="Queue Management",
        value="`!queue` or `!q` - Show current music queue\n"
              "`!nowplaying` or `!np` - Show currently playing song\n"
              "`!shuffle` - Shuffle the current queue",
        inline=False
    )
    
    embed.add_field(
        name="Role Management",
        value="`!roles` - Show role selection panel\n"
              "`!myroles` - Show your current roles\n"
              "`!roleinfo <role>` - Get information about a role",
        inline=False
    )
    
    embed.add_field(
        name="Utility Commands",
        value="`!clear <amount>` or `!purge <amount>` - Delete messages (Admin Only)\n"
              "`!say <message>` - Send message in simple embed\n"
              "`!embed <content>` or `!e <content>` - Create custom embeds\n"
              "`!embedhelp` or `!ehelp` - Show embed formatting help",
        inline=False
    )
    
    embed.add_field(
        name="Admin Commands (Owner Only)",
        value="`!announce <message>` - Send announcement embed\n"
              "`!shutdown` - Shutdown the bot\n"
              "`!restart` - Restart the bot automatically\n"
              "`!m` or `!maintenance` - Toggle maintenance mode (Admin Only)",
        inline=False
    )
    
    embed.add_field(
        name="Additional Information",
        value="**Music Sources:** YouTube links or search terms\n"
              "**Auto-Features:** Auto-join voice channels, auto-leave when alone\n"
              "**Embed Colors:** red, green, blue, yellow, orange, purple, pink, cyan, gray, black\n"
              "**Privacy:** Error messages are sent privately to you!",
        inline=False
    )
    
    embed.set_footer(text="Use the ! prefix for all commands")
    embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)
    
    await ctx.send(embed=embed)

# Maintenance command
@bot.command(name='m', aliases=['maintenance'])
@commands.has_permissions(administrator=True)
async def maintenance(ctx, action=None, duration=None):
    """Toggle maintenance mode (Admin only)"""
    global maintenance_mode, maintenance_end_time, maintenance_message
    
    if not action:
        if maintenance_mode:
            time_info = ""
            if maintenance_end_time:
                remaining = maintenance_end_time - datetime.datetime.now()
                if remaining.total_seconds() > 0:
                    hours = int(remaining.total_seconds() // 3600)
                    minutes = int((remaining.total_seconds() % 3600) // 60)
                    if hours > 0:
                        time_info = f"Time remaining: {hours}h {minutes}m"
                    else:
                        time_info = f"Time remaining: {minutes}m"
                else:
                    time_info = "Maintenance should have ended (checking...)"
                    await check_maintenance()
            
            embed = discord.Embed(
                title="Maintenance Status",
                description=f"**Status:** ON\n**Message:** {maintenance_message}\n**{time_info}**",
                color=0xffa94d
            )
        else:
            embed = discord.Embed(
                title="Maintenance Status",
                description="**Status:** OFF\nBot is operating normally",
                color=0x51cf66
            )
        await ctx.send(embed=embed)
        return
    
    if action.lower() == 'on':
        maintenance_mode = True
        
        if duration:
            duration_match = re.findall(r'(\d+)([hm])', duration.lower())
            if duration_match:
                total_minutes = 0
                for value, unit in duration_match:
                    if unit == 'h':
                        total_minutes += int(value) * 60
                    elif unit == 'm':
                        total_minutes += int(value)
                
                if total_minutes > 0:
                    maintenance_end_time = datetime.datetime.now() + datetime.timedelta(minutes=total_minutes)
                    time_str = f"{total_minutes // 60}h {total_minutes % 60}m" if total_minutes >= 60 else f"{total_minutes}m"
                    
                    embed = discord.Embed(
                        title="Maintenance Mode Enabled",
                        description=f"Bot is now in maintenance mode for **{time_str}**\nMaintenance will end at: **{maintenance_end_time.strftime('%H:%M:%S')}**",
                        color=0xffa94d
                    )
                else:
                    embed = discord.Embed(
                        title="Invalid Duration",
                        description="Please provide a valid duration (e.g., 30m, 1h, 2h30m)",
                        color=0xff6b6b
                    )
                    await ctx.send(embed=embed)
                    return
            else:
                embed = discord.Embed(
                    title="Invalid Duration Format",
                    description="Please use format like: 30m, 1h, 2h30m\nExample: `!m on 40m`",
                    color=0xff6b6b
                )
                await ctx.send(embed=embed)
                return
        else:
            maintenance_end_time = None
            embed = discord.Embed(
                title="Maintenance Mode Enabled",
                description="Bot is now in maintenance mode indefinitely\nUse `!m off` to disable",
                color=0xffa94d
            )
        
        await update_bot_status()
        print(f"Maintenance mode enabled by {ctx.author} for {duration if duration else 'indefinite time'}")
        
    elif action.lower() == 'off':
        maintenance_mode = False
        maintenance_end_time = None
        embed = discord.Embed(
            title="Maintenance Mode Disabled",
            description="Bot is now operating normally",
            color=0x51cf66
        )
        await update_bot_status()
        print(f"Maintenance mode disabled by {ctx.author}")
        
    else:
        embed = discord.Embed(
            title="Invalid Action",
            description="**Usage:**\n"
                       "`!m` - Show maintenance status\n"
                       "`!m on` - Enable maintenance mode\n"
                       "`!m on 40m` - Enable for 40 minutes\n"
                       "`!m on 2h30m` - Enable for 2 hours 30 minutes\n"
                       "`!m off` - Disable maintenance mode",
            color=0xff8787
        )
    
    await ctx.send(embed=embed)

# Owner-only commands
def is_owner():
    def predicate(ctx):
        OWNER_ID = int(os.getenv('OWNER_ID', '0'))
        return ctx.author.id == OWNER_ID
    return commands.check(predicate)

@bot.command(name='shutdown')
@is_owner()
async def shutdown(ctx):
    """Shutdown the bot (Owner only)"""
    embed = discord.Embed(
        title="Bot Shutting Down",
        description="The bot is shutting down... Goodbye!",
        color=0xff6b6b
    )
    await ctx.send(embed=embed)
    
    for voice_client in bot.voice_clients:
        await voice_client.disconnect()
    
    for guild_id in music_queues:
        music_queues[guild_id].clear()
    
    print(f"Bot shutdown initiated by {ctx.author}")
    await bot.close()

@bot.command(name='restart')
@is_owner()
async def restart(ctx):
    """Restart the bot (Owner only)"""
    embed = discord.Embed(
        title="Bot Restarting",
        description="The bot is restarting now... Please wait a moment!",
        color=0xffa94d
    )
    await ctx.send(embed=embed)
    
    for voice_client in bot.voice_clients:
        await voice_client.disconnect()
    
    for guild_id in music_queues:
        music_queues[guild_id].clear()
    
    print(f"Bot restart initiated by {ctx.author}")
    
    await bot.close()
    
    try:
        python_executable = sys.executable
        script_path = os.path.abspath(__file__)
        
        print("Restarting bot...")
        
        subprocess.Popen([python_executable, script_path], 
                        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
        
        os._exit(0)
        
    except Exception as e:
        print(f"Failed to restart: {e}")
        print("Please manually restart the bot.")
        os._exit(1)

@bot.command(name='announce')
@is_owner()
async def announce(ctx, *, message=None):
    """Send a message in an embed (Owner only)"""
    if not message:
        embed = discord.Embed(
            title="Message Required",
            description="Please provide a message to announce!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    try:
        await ctx.message.delete()
        
        embed = discord.Embed(
            title="Announcement",
            description=message,
            color=0x339af0
        )
        embed.set_footer(text=f"Announced by {ctx.author.display_name}")
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        embed = discord.Embed(
            title="Announcement",
            description=message,
            color=0x339af0
        )
        embed.set_footer(text=f"Announced by {ctx.author.display_name}")
        await ctx.send(embed=embed)

@bot.command(name='say')
async def say(ctx, *, message=None):
    """Send a message in an embed"""
    if not message:
        embed = discord.Embed(
            title="Message Required",
            description="Please provide a message to send!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    try:
        await ctx.message.delete()
        
        embed = discord.Embed(
            description=message,
            color=0x51cf66
        )
        embed.set_footer(text=f"Message by {ctx.author.display_name}")
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        embed = discord.Embed(
            description=message,
            color=0x51cf66
        )
        embed.set_footer(text=f"Message by {ctx.author.display_name}")
        await ctx.send(embed=embed)

@bot.command(name='embed', aliases=['e'])
async def embed_message(ctx, *, content=None):
    """Create a custom embed with your message"""
    if not content:
        embed = discord.Embed(
            title="Content Required",
            description="Please provide content for the embed!\n\n**Usage Examples:**\n"
                       "`!embed Hello World` - Simple message\n"
                       "`!embed title:Welcome | description:This is a welcome message` - Custom title and description\n"
                       "`!embed title:Alert | description:Important news | color:red` - With custom color",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass
    
    title = None
    description = content
    color = 0x339af0
    
    if '|' in content:
        parts = [part.strip() for part in content.split('|')]
        for part in parts:
            if part.startswith('title:'):
                title = part[6:].strip()
            elif part.startswith('description:'):
                description = part[12:].strip()
            elif part.startswith('color:'):
                color_name = part[6:].strip().lower()
                color_map = {
                    'red': 0xff6b6b,
                    'green': 0x51cf66,
                    'blue': 0x339af0,
                    'yellow': 0xffd43b,
                    'orange': 0xffa94d,
                    'purple': 0x9775fa,
                    'pink': 0xff8cc8,
                    'cyan': 0x4ecdc4,
                    'gray': 0x868e96,
                    'black': 0x2d3436
                }
                color = color_map.get(color_name, 0x339af0)
    
    embed = discord.Embed(color=color)
    
    if title:
        embed.title = title
        if description and description != content:
            embed.description = description
    else:
        embed.description = description
    
    embed.set_footer(text=f"Embedded by {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.timestamp = ctx.message.created_at
    
    await ctx.send(embed=embed)

@bot.command(name='embedhelp', aliases=['ehelp'])
async def embed_help(ctx):
    """Show help for the embed command"""
    embed = discord.Embed(
        title="Embed Command Help",
        description="Create beautiful embedded messages with custom formatting!",
        color=0x339af0
    )
    
    embed.add_field(
        name="Basic Usage",
        value="`!embed Your message here`\n"
              "Creates a simple embed with your message",
        inline=False
    )
    
    embed.add_field(
        name="Advanced Usage",
        value="`!embed title:Your Title | description:Your description`\n"
              "`!embed title:Alert | description:Important message | color:red`",
        inline=False
    )
    
    embed.add_field(
        name="Available Colors",
        value="red, green, blue, yellow, orange, purple, pink, cyan, gray, black",
        inline=False
    )
    
    embed.add_field(
        name="Examples",
        value="`!embed Welcome to our server!`\n"
              "`!embed title:Announcement | description:Server maintenance tonight | color:yellow`\n"
              "`!embed title:Rules | description:Be respectful to everyone | color:green`",
        inline=False
    )
    
    embed.set_footer(text="Use !embed or !e for short")
    await ctx.send(embed=embed)

# Cleanup on shutdown
@bot.event
async def on_disconnect():
    for guild_id in music_queues:
        music_queues[guild_id].clear()

# Run the bot
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print("Error: DISCORD_BOT_TOKEN not found in environment variables!")
        print("Please create a .env file with your bot token:")
        print("DISCORD_BOT_TOKEN=your_bot_token_here")
        print("OWNER_ID=your_discord_user_id_here")
    else:
        try:
            bot.run(token)
        except Exception as e:
            print(f"Failed to start bot: {e}")
            print("Make sure your bot token is correct and the bot has proper permissions.")