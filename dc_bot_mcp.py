import os
import sys
import threading
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from discord.ext import commands
import discord
from discord.ext.commands import Context

import yt_dlp
from yt_dlp import YoutubeDL
import asyncio

from gtts import gTTS
import io
from io import BytesIO
import time

from fastmcp import FastMCP
import argparse
from uvicorn import Config, Server

# MCP Server
mcp = FastMCP("Discord Bot MCP Server")

# Queue and state
queue = []
my_queue = []
play_stopped = False
current_song = None  # Track currently playing song

# Command queue for MCP -> Discord communication
command_queue = asyncio.Queue()
response_queue = asyncio.Queue()  # For getting responses back from Discord
bot_ready = False

# Current selected server and channels
current_guild_id = None
current_text_channel_id = None
current_voice_channel_id = None

# Options
YDL_OPTIONS = {
    'format': 'ba[ext=m4a]/ba[ext=webm]/ba/b',  
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'geo_bypass': True,  
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'source_address': '0.0.0.0',
    'socket_timeout': 30,
    'http_chunk_size': 10485760,
    'prefer_ffmpeg': True,
    'keepvideo': False,
    'extract_flat': False,
    # Other YouTube clients (tv/web/android_vr) give stream URLs that return 403 to ffmpeg
    'extractor_args': {'youtube': {'player_client': ['visionos']}},
}
FFMPEG_OPTIONS = {
    'before_options': '-thread_queue_size 20480 -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -b:a 128k -bufsize 2048k'
}
FFMPEG_SPEAK_OPTIONS = {
    'before_options': '-f mp3',
    'options': '-vn -ar 48000 -ac 2 -b:a 96k -filter:a "atempo=1.25"'
}

# API Keys (loaded from .env file)
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', '0'))
VOICE_ID = int(os.getenv('VOICE_ID', '0'))
OWNER_ID = int(os.getenv('OWNER_ID', '0')) 
# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True 
intents.voice_states = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ==================== MCP TOOLS ====================

@mcp.tool
def get_queue() -> list:
    """Get the current music queue"""
    return my_queue.copy()

@mcp.tool
def add_to_queue(song: str) -> str:
    """Add a song to the queue
    
    Args:
        song: The name of the song to add
    """
    my_queue.append(song)
    return f"'{song}' added to the queue"

@mcp.tool
def remove_from_queue(song: str) -> str:
    """Remove a song from the queue
    
    Args:
        song: The name of the song to remove
    """
    for i in my_queue:
        if song.lower() in i.lower():
            my_queue.remove(i)
            return f"Removed from queue: {i}"
    return f"Song '{song}' not found in the queue."

@mcp.tool
def clear_queue() -> str:
    """Clear the entire music queue"""
    my_queue.clear()
    return "Queue is now empty"

@mcp.tool
def auto_join() -> dict:
    """MANDATORY FIRST STEP! Call this before any music operation.
    - If bot is already in a voice channel → returns current location, ready to play
    - If not, finds owner's voice channel → auto-joins there
    - If owner not found → returns available channels to ask user"""
    global current_guild_id, current_text_channel_id, current_voice_channel_id, play_stopped
    
    if not bot_ready:
        return {"error": "Discord bot is not ready yet."}
    
    # Check if bot is already connected to a voice channel
    for guild in bot.guilds:
        if guild.voice_client and guild.voice_client.is_connected():
            vc = guild.voice_client.channel
            current_guild_id = guild.id
            current_voice_channel_id = vc.id
            if guild.text_channels:
                current_text_channel_id = guild.text_channels[0].id
            return {
                "status": "already_connected",
                "message": f"Already in '{vc.name}' on '{guild.name}'. Ready to play!",
                "channel": vc.name,
                "server": guild.name
            }
    
    # Bot not connected - find owner in voice channels
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if member.id == OWNER_ID:
                    # Found owner! Auto-select this channel
                    current_guild_id = guild.id
                    current_voice_channel_id = vc.id
                    if guild.text_channels:
                        current_text_channel_id = guild.text_channels[0].id
                    
                    return {
                        "status": "success",
                        "message": f"Found you in '{vc.name}' on '{guild.name}'. Ready to play!",
                        "channel": vc.name,
                        "server": guild.name
                    }
    
    # Owner not in any voice channel - return available channels
    servers = []
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            servers.append({
                "server": guild.name,
                "channel": vc.name,
                "id": str(vc.id)
            })
    
    return {
        "status": "not_found",
        "message": "You're not in any voice channel. Please ask which channel to join.",
        "available_channels": servers
    }

@mcp.tool
def list_servers() -> list:
    """IF you cant find the owner on anywhere or bot isnt playing music on anywhere You MUST call this and ask the user which voice channel to use.
    NEVER skip this step - ALWAYS ask the user to choose a voice channel before any music operation.
    Lists all Discord servers and their voice channels with IDs.
    After showing this to user, call select_voice_channel() with their chosen ID.
    
    This can also be called anytime to switch to a different voice channel."""
    if not bot_ready:
        return [{"error": "Discord bot is not ready yet."}]
    
    servers = []
    for guild in bot.guilds:
        voice_channels = []
        for vc in guild.voice_channels:
            voice_channels.append({
                "name": vc.name,
                "id": str(vc.id),
                "currently_selected": vc.id == current_voice_channel_id
            })
        
        servers.append({
            "server_name": guild.name,
            "voice_channels": voice_channels
        })
    
    return servers

@mcp.tool
def select_voice_channel(voice_channel_id: str) -> str:
    """Select a voice channel for music playback. Can be called anytime to switch channels.
    If music is playing, it will stop and you'll need to play again in the new channel.
    
    Args:
        voice_channel_id: The ID of the voice channel (copy from list_servers output)
    """
    global current_guild_id, current_text_channel_id, current_voice_channel_id, play_stopped
    if not bot_ready:
        return "Discord bot is not ready yet."
    
    # Convert string to int
    try:
        vc_id = int(voice_channel_id)
    except ValueError:
        return f"Invalid voice channel ID: {voice_channel_id}"
    
    # Try to find channel in all guilds
    channel = None
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            if vc.id == vc_id:
                channel = vc
                break
        if channel:
            break
    
    if not channel:
        # Debug: list all available channel IDs
        all_channels = []
        for guild in bot.guilds:
            for vc in guild.voice_channels:
                all_channels.append(f"{guild.name}/{vc.name}: {vc.id}")
        return f"Voice channel not found. Available: {', '.join(all_channels)}"
    
    # If switching servers while connected, disconnect first
    old_guild_id = current_guild_id
    if old_guild_id and old_guild_id != channel.guild.id:
        # Stop music and leave old channel
        global current_song
        play_stopped = True
        current_song = None
        my_queue.clear()
        try:
            asyncio.run_coroutine_threadsafe(
                command_queue.put({"action": "leave"}),
                bot.loop
            ).result(timeout=5)
        except:
            pass
    
    # Set the new voice channel and its server
    current_voice_channel_id = vc_id
    current_guild_id = channel.guild.id
    
    # Auto-select first text channel from the same server
    if channel.guild.text_channels:
        current_text_channel_id = channel.guild.text_channels[0].id
    
    return f"✓ Selected: '{channel.name}' on '{channel.guild.name}'. Ready to play music!"

@mcp.tool
def get_playback_status() -> dict:
    """Check if the bot is currently playing audio and get current status."""
    if not bot_ready:
        return {"error": "Discord bot is not ready yet."}
    
    if not current_voice_channel_id:
        return {"status": "not_connected", "message": "No voice channel selected."}
    
    voice_ch = bot.get_channel(current_voice_channel_id)
    if not voice_ch:
        return {"status": "error", "message": "Voice channel not found."}
    
    guild = voice_ch.guild
    voice_client = guild.voice_client
    
    if voice_client is None:
        return {
            "status": "not_connected",
            "message": "Bot is not connected to a voice channel.",
            "queue_length": len(my_queue)
        }
    
    if voice_client.is_playing():
        return {
            "status": "playing",
            "message": "Bot is currently playing audio.",
            "current_song": current_song,
            "channel": voice_ch.name,
            "server": guild.name,
            "queue_length": len(my_queue),
            "is_paused": False
        }
    elif voice_client.is_paused():
        return {
            "status": "paused",
            "message": "Playback is paused.",
            "current_song": current_song,
            "channel": voice_ch.name,
            "server": guild.name,
            "queue_length": len(my_queue),
            "is_paused": True
        }
    else:
        return {
            "status": "idle",
            "message": "Bot is connected but not playing anything.",
            "channel": voice_ch.name,
            "server": guild.name,
            "queue_length": len(my_queue),
            "is_paused": False
        }

@mcp.tool
def get_current_selection() -> dict:
    """Get the currently selected voice channel."""
    if not bot_ready:
        return {"error": "Discord bot is not ready yet."}
    
    voice_ch = bot.get_channel(current_voice_channel_id) if current_voice_channel_id else None
    
    if voice_ch:
        return {
            "server": voice_ch.guild.name,
            "voice_channel": voice_ch.name,
            "voice_channel_id": current_voice_channel_id
        }
    else:
        return {"error": "No voice channel selected. Call list_servers() to see available channels."}

@mcp.tool
def play_music(song: str = None) -> str:
    """Play music on Discord. STOP! Before calling this:
    1. FIRST call list_servers() to show available voice channels to the user
    2. ASK the user which voice channel they want
    3. Call select_voice_channel() with their choice
    4. THEN call this function
    
    If no channel is selected, this will fail and remind you to ask the user first.
    
    Args:
        song: The name of the song to play
    """
    if not bot_ready:
        return "Discord bot is not ready yet. Please wait."
    
    if not current_voice_channel_id:
        return "STOP! No voice channel selected. You MUST first: 1) Call auto_join() or 2) Call list_servers() and select_voice_channel(id)"
    
    # Check if already playing (like original !play command)
    voice_ch = bot.get_channel(current_voice_channel_id)
    if voice_ch:
        guild = voice_ch.guild
        voice_client = guild.voice_client
        if voice_client and voice_client.is_playing():
            return "The bot is currently playing audio, please wait."
    
    # Check if queue is empty and no song provided
    if len(my_queue) == 0 and song is None:
        return "Queue is empty. Add songs with add_to_queue() first."
    
    try:
        # Clear response queue first
        while not response_queue.empty():
            try:
                response_queue.get_nowait()
            except:
                break
        
        # Send command
        asyncio.run_coroutine_threadsafe(
            command_queue.put({"action": "play", "song": song}),
            bot.loop
        ).result(timeout=5)
        
        # Wait for response
        try:
            response = asyncio.run_coroutine_threadsafe(
                asyncio.wait_for(response_queue.get(), timeout=3.0),
                bot.loop
            ).result(timeout=5)
            
            if response.get("status") == "error":
                return response.get("message", "An error occurred")
        except:
            pass
        
        guild = bot.get_guild(current_guild_id)
        voice_ch = bot.get_channel(current_voice_channel_id)
        if song:
            return f"Playing '{song}' on server '{guild.name}' in voice channel '{voice_ch.name}'..."
        return f"Playing from queue on server '{guild.name}' in voice channel '{voice_ch.name}'..."
    except Exception as e:
        return f"Error: {e}"

@mcp.tool
def stop_music() -> str:
    """Stop the currently playing music and clear the queue.
    PREREQUISITE: A voice channel must be selected first."""
    if not bot_ready:
        return "Discord bot is not ready yet."
    
    if not current_voice_channel_id:
        return "ERROR: No voice channel selected! Call auto_join() first."
    
    # Check if actually playing
    voice_ch = bot.get_channel(current_voice_channel_id)
    if voice_ch:
        guild = voice_ch.guild
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_playing():
            return "Nothing is playing right now."
    
    try:
        asyncio.run_coroutine_threadsafe(
            command_queue.put({"action": "stop"}),
            bot.loop
        ).result(timeout=5)
        return "Music stopped and queue cleared."
    except Exception as e:
        return f"Error: {e}"

@mcp.tool
def skip_song() -> str:
    """Skip to the next song in the queue.
    PREREQUISITE: A voice channel must be selected first."""
    if not bot_ready:
        return "Discord bot is not ready yet."
    
    if not current_voice_channel_id:
        return "ERROR: No voice channel selected! Call auto_join() first."
    
    # Check if bot is in voice channel
    voice_ch = bot.get_channel(current_voice_channel_id)
    if voice_ch:
        guild = voice_ch.guild
        voice_client = guild.voice_client
        if voice_client is None:
            return "I am not in a voice channel!"
        # Check if queue has songs (like original)
        if len(my_queue) > 0:
            if voice_client.is_playing():
                pass  # Will skip below
            else:
                return "Nothing is playing right now."
        elif len(my_queue) == 0:
            if not voice_client.is_playing():
                return "Queue is empty. Add songs first."
    
    try:
        asyncio.run_coroutine_threadsafe(
            command_queue.put({"action": "skip"}),
            bot.loop
        ).result(timeout=5)
        return "Skipped to next song."
    except Exception as e:
        return f"Error: {e}"

@mcp.tool
def pause_music() -> str:
    """Pause the currently playing music.
    PREREQUISITE: A voice channel must be selected first."""
    if not bot_ready:
        return "Discord bot is not ready yet."
    
    if not current_voice_channel_id:
        return "ERROR: No voice channel selected! Call auto_join() first."
    
    # Check if actually playing
    voice_ch = bot.get_channel(current_voice_channel_id)
    if voice_ch:
        guild = voice_ch.guild
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_playing():
            return "Nothing is playing right now."
        if voice_client.is_paused():
            return "Music is already paused."
    
    try:
        asyncio.run_coroutine_threadsafe(
            command_queue.put({"action": "pause"}),
            bot.loop
        ).result(timeout=5)
        return "Music paused."
    except Exception as e:
        return f"Error: {e}"

@mcp.tool
def resume_music() -> str:
    """Resume the paused music.
    PREREQUISITE: A voice channel must be selected first."""
    if not bot_ready:
        return "Discord bot is not ready yet."
    
    if not current_voice_channel_id:
        return "ERROR: No voice channel selected! Call auto_join() first."
    
    # Check if actually paused
    voice_ch = bot.get_channel(current_voice_channel_id)
    if voice_ch:
        guild = voice_ch.guild
        voice_client = guild.voice_client
        if not voice_client:
            return "Bot is not connected to voice."
        if not voice_client.is_paused():
            return "Music is not paused."
    
    try:
        asyncio.run_coroutine_threadsafe(
            command_queue.put({"action": "resume"}),
            bot.loop
        ).result(timeout=5)
        return "Music resumed."
    except Exception as e:
        return f"Error: {e}"

@mcp.tool
def leave_voice_channel() -> str:
    """Make the bot leave the voice channel.
    PREREQUISITE: A voice channel must be selected first."""
    if not bot_ready:
        return "Discord bot is not ready yet."
    
    if not current_voice_channel_id:
        return "ERROR: No voice channel selected!"
    
    # Check if bot is actually in a voice channel (like original)
    voice_ch = bot.get_channel(current_voice_channel_id)
    if voice_ch:
        guild = voice_ch.guild
        voice_client = guild.voice_client
        if voice_client is None:
            return "I am not in a voice channel!"
    
    try:
        asyncio.run_coroutine_threadsafe(
            command_queue.put({"action": "leave"}),
            bot.loop
        ).result(timeout=5)
        return "Left the voice channel."
    except Exception as e:
        return f"Error: {e}"

@mcp.tool
def speak_text(text: str) -> str:
    """Make the bot speak text in Turkish using TTS.
    PREREQUISITE: A voice channel must be selected first using auto_join() or select_voice_channel().
    
    Args:
        text: The text to speak in Turkish
    """
    if not bot_ready:
        return "Discord bot is not ready yet."
    
    if not current_voice_channel_id:
        return "ERROR: No voice channel selected! Call auto_join() first."
    
    # Check if already playing (like original !speak command)
    voice_ch = bot.get_channel(current_voice_channel_id)
    if voice_ch:
        guild = voice_ch.guild
        voice_client = guild.voice_client
        if voice_client and voice_client.is_playing():
            return "The bot is currently playing audio, please wait."
    
    try:
        # Clear response queue first
        while not response_queue.empty():
            try:
                response_queue.get_nowait()
            except:
                break
        
        # Send command
        asyncio.run_coroutine_threadsafe(
            command_queue.put({"action": "speak", "text": text}),
            bot.loop
        ).result(timeout=5)
        
        # Wait for response
        try:
            response = asyncio.run_coroutine_threadsafe(
                asyncio.wait_for(response_queue.get(), timeout=3.0),
                bot.loop
            ).result(timeout=5)
            
            if response.get("status") == "error":
                return response.get("message", "An error occurred")
        except:
            pass
        
        return f"Speaking: '{text}'"
    except Exception as e:
        return f"Error: {e}"

@mcp.tool
def get_bot_help() -> dict:
    """Get all available Discord bot commands"""
    return {
        "queue_commands": {
            "!add <song>": "Add a song to the queue",
            "!remove <name>": "Remove a song from the queue",
            "!clear": "Clear the queue",
            "!queue": "Show the current queue"
        },
        "playback_commands": {
            "!play <song>": "Bot joins the voice channel and plays the queue or your song",
            "!pause": "Pause playback",
            "!resume": "Resume playback",
            "!skip": "Skip to the next song",
            "!stop": "Stop playback and clear the queue"
        },
        "voice_commands": {
            "!speak <text>": "Bot speaks the given text in Turkish"
        },
        "channel_commands": {
            "!join": "Bot joins your voice channel",
            "!leave": "Bot leaves the voice channel"
        },
        "other": {
            "!help": "Show help message"
        }
    }

# ==================== DISCORD BOT EVENTS & COMMANDS ====================

@bot.event
async def on_ready():
    global bot_ready
    bot_ready = True
    print(f'{bot.user} is ready!')
    print(f'Connected to {len(bot.guilds)} server(s)')
    for guild in bot.guilds:
        print(f'  - {guild.name} (ID: {guild.id})')
    print('Waiting for server selection via MCP...')
    
    # Start command processor
    bot.loop.create_task(process_mcp_commands())

async def process_mcp_commands():
    """Process commands from MCP tools"""
    global play_stopped
    while True:
        try:
            cmd = await asyncio.wait_for(command_queue.get(), timeout=1.0)
            
            # Use selected channels or fall back to defaults
            channel = bot.get_channel(current_text_channel_id)
            voice_channel = bot.get_channel(current_voice_channel_id)
            
            if channel is None or voice_channel is None:
                print("Error: No channel selected. Use list_servers() and select_server() first.")
                continue
            
            if cmd["action"] == "play":
                song = cmd.get("song")
                
                # Get voice client or connect
                guild = channel.guild
                voice_client = guild.voice_client
                
                # Check if already playing
                if voice_client and voice_client.is_playing():
                    await response_queue.put({"status": "error", "message": "Bot is currently playing audio, please wait."})
                    continue
                
                if song:
                    my_queue.append(song)
                
                if voice_client is None:
                    voice_client = await voice_channel.connect()
                    # Say "merhaba" when first joining (like original)
                    mp3_fp = io.BytesIO()
                    tts = gTTS(text="merhaba", lang='tr')
                    tts.write_to_fp(mp3_fp)
                    mp3_fp.seek(0)
                    source = discord.FFmpegOpusAudio(mp3_fp, pipe=True, **FFMPEG_SPEAK_OPTIONS)
                    voice_client.play(source)
                    await asyncio.sleep(1.5)  # Wait for merhaba to finish
                
                if len(my_queue) > 0:
                    await play_from_queue(voice_client, channel)
                    await response_queue.put({"status": "ok"})
                else:
                    await response_queue.put({"status": "error", "message": "Queue is empty. Add songs first."})
                    
            elif cmd["action"] == "stop":
                global current_song
                guild = channel.guild
                voice_client = guild.voice_client
                play_stopped = True
                current_song = None
                my_queue.clear()
                if voice_client and voice_client.is_playing():
                    voice_client.stop()
                    
            elif cmd["action"] == "skip":
                guild = channel.guild
                voice_client = guild.voice_client
                if voice_client and voice_client.is_playing():
                    voice_client.stop()
                    
            elif cmd["action"] == "pause":
                guild = channel.guild
                voice_client = guild.voice_client
                if voice_client and voice_client.is_playing():
                    voice_client.pause()
                    
            elif cmd["action"] == "resume":
                guild = channel.guild
                voice_client = guild.voice_client
                if voice_client and voice_client.is_paused():
                    voice_client.resume()
                    
            elif cmd["action"] == "leave":
                guild = channel.guild
                voice_client = guild.voice_client
                if voice_client:
                    await voice_client.disconnect()
                    
            elif cmd["action"] == "speak":
                text = cmd.get("text", "merhaba")
                guild = channel.guild
                voice_client = guild.voice_client
                
                # Check if already playing
                if voice_client and voice_client.is_playing():
                    await response_queue.put({"status": "error", "message": "Bot is currently playing audio, please wait."})
                    continue
                
                if voice_client is None:
                    voice_client = await voice_channel.connect()
                    await asyncio.sleep(0.5)
                
                mp3_fp = io.BytesIO()
                tts = gTTS(text=text, lang='tr')
                tts.write_to_fp(mp3_fp)
                mp3_fp.seek(0)
                source = discord.FFmpegOpusAudio(mp3_fp, pipe=True, **FFMPEG_SPEAK_OPTIONS)
                voice_client.play(source)
                await response_queue.put({"status": "ok"})
                    
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            print(f"Command processor error: {e}")

async def play_from_queue(voice_client, channel):
    """Play songs from the queue"""
    global play_stopped
    play_stopped = False
    
    if len(my_queue) == 0:
        return
    
    loop = asyncio.get_event_loop()
    
    def ytdlp_extract():
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            return ydl.extract_info(f"ytsearch:{my_queue[0]}", download=False)
    
    result = await loop.run_in_executor(None, ytdlp_extract)
    first_result = result['entries'][0]
    url = first_result['url']
    title = first_result['title']
    my_queue.pop(0)
    
    source = discord.FFmpegOpusAudio(url, **FFMPEG_OPTIONS)
    
    global current_song
    current_song = title  # Store currently playing song
    
    def after_playing(error):
        global current_song
        if error:
            print(f"Error: {error}")
            current_song = None
        if play_stopped:
            current_song = None
            return
        if len(my_queue) == 0:
            current_song = None  # No more songs, clear current
        if len(my_queue) > 0:
            fut = asyncio.run_coroutine_threadsafe(play_from_queue(voice_client, channel), bot.loop)
            try:
                fut.result()
            except Exception as e:
                print(f"After playing error: {e}")
    
    voice_client.play(source, after=after_playing)
    await channel.send(f"Now playing: {title}")
####### MY CORE COMMANDS FOR CONTROL OVER DISCORD INTERFACE #######
@bot.command()
async def clear(ctx: Context):
    async with ctx.channel.typing():
        my_queue.clear()
        await ctx.channel.send("queue is now empty")

@bot.command()
async def add(ctx: Context, *, song: str):
    async with ctx.channel.typing():
        await ctx.channel.send(f" '{song}' added to the queue")
    my_queue.append(song)

@bot.command()
async def remove(ctx: Context, *, song: str):
    async with ctx.channel.typing():
        for i in my_queue:
            if song.lower() in i.lower():
                my_queue.remove(i)
                await ctx.channel.send(f"Removed from queue: {i}")
                return
        await ctx.channel.send(f"Song '{song}' not found in the queue.")

@bot.command()
async def pause(ctx: Context):
    async with ctx.channel.typing():
        if ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("Playback paused.")
        else:
            await ctx.send("There is no audio playing.")

@bot.command()
async def resume(ctx: Context):
    async with ctx.channel.typing():
        if ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("Playback resumed.")
        else:
            await ctx.send("The audio is not paused.")

@bot.command()
async def skip(ctx: Context):
    async with ctx.channel.typing():
        if ctx.voice_client is None:
            await ctx.send("I am not in a voice channel!")
            return
        if len(my_queue) > 0:
            if ctx.voice_client.is_playing():
                ctx.voice_client.stop()
                await ctx.send("Next song is playing.")
                return
        elif len(my_queue) == 0:
            await ctx.send("Queue is empty. Add songs with !add.")
            return
        if not ctx.voice_client.is_playing():
            await ctx.send("There is no audio :D")
            return

@bot.command()
async def stop(ctx: Context):
    global play_stopped, current_song
    play_stopped = True
    current_song = None
    my_queue.clear()
    async with ctx.channel.typing():
        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("Playback stopped and queue cleaned.")
            return
        else:
            await ctx.send("There is no audio :D")

@bot.command()
async def leave(ctx: Context):
    async with ctx.channel.typing():
        if ctx.voice_client is None:
            await ctx.send("I am not in a voice channel!")
            return
        await ctx.voice_client.disconnect()
        await ctx.send("Disconnected from the voice channel.")

@bot.command(name='queue')
async def show_queue(ctx: Context):
    if len(my_queue) == 0:
        await ctx.send("Queue is empty.")
    else:
        await ctx.send('\n'.join(my_queue))

@bot.command()
async def join(ctx: Context):
    async with ctx.channel.typing():
        if ctx.author.voice is None:
            await ctx.send("You need to be in a voice channel!")
        voice_channel = ctx.author.voice.channel
        if ctx.voice_client is not None:
            await ctx.send("I am already in the voice channel!")
            return
        voice_client = await voice_channel.connect()
        mp3_fp = io.BytesIO()
        tts = gTTS(text="merhaba", lang='tr')
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        await asyncio.sleep(0.5)
        source = discord.FFmpegOpusAudio(mp3_fp, pipe=True, **FFMPEG_SPEAK_OPTIONS)
        ctx.voice_client.play(source)
        await ctx.send(f"Connected to {voice_channel.name}")

@bot.command()
async def speak(ctx: Context, *, text):
    if ctx.author.voice is None:
        await ctx.send("You need to be in a voice channel!")
        return
    async with ctx.channel.typing():
        await ctx.send("Wait a moment...")
    if ctx.voice_client is None:
        await ctx.author.voice.channel.connect()
    if ctx.voice_client and ctx.voice_client.is_playing():
        await ctx.send("The bot is currently playing audio, please wait.")
        return
    mp3_fp = io.BytesIO()
    tts = gTTS(text=text, lang='tr')
    tts.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    await asyncio.sleep(0.5)
    source = discord.FFmpegOpusAudio(mp3_fp, pipe=True, **FFMPEG_SPEAK_OPTIONS)
    ctx.voice_client.play(source)

@bot.command()
async def play(ctx: Context, *, song_name: str = None):
    global play_stopped
    play_stopped = False
    if ctx.voice_client and ctx.voice_client.is_playing():
        await ctx.send("The bot is currently playing audio, please wait.")
        return
    if ctx.author.voice is None:
        await ctx.send("You need to be in a voice channel!")
        return
    if song_name:
        await ctx.channel.send("It may take a while to load the song")
        my_queue.append(song_name)
    if len(my_queue) == 0 and song_name is None:
        await ctx.send("Queue is empty. Add songs with !add.")
        return
    if ctx.voice_client is None:
        await ctx.author.voice.channel.connect()
        mp3_fp = io.BytesIO()
        tts = gTTS(text="merhaba", lang='tr')
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        await asyncio.sleep(0.5)
        source = discord.FFmpegOpusAudio(mp3_fp, pipe=True, **FFMPEG_SPEAK_OPTIONS)
        ctx.voice_client.play(source)
    await asyncio.sleep(0.5)
    loop = asyncio.get_event_loop()
    
    def ytdlp_extract():
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            return ydl.extract_info(f"ytsearch:{my_queue[0]}", download=False)
    
    result = await loop.run_in_executor(None, ytdlp_extract)
    first_result = result['entries'][0]
    url = first_result['url']
    title = first_result['title']
    my_queue.pop(0)
    source = discord.FFmpegOpusAudio(url, **FFMPEG_OPTIONS)

    def after_playing(error):
        if error:
            print(f"Error: {error}")
        if play_stopped:
            return
        fut = asyncio.run_coroutine_threadsafe(play(ctx), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"After playing error: {e}")
    
    ctx.voice_client.play(source, after=after_playing)
    await ctx.send(f"Now playing: {title}")

@bot.command()
async def help(ctx: Context):
    async with ctx.channel.typing():
        embed = discord.Embed(
            title="Help — Commands",
            description="Here are the available commands:",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Queue", value="`!add <song>` — Add a song to the queue\n`!remove <name>` — Remove a song from the queue\n`!clear` — Clear the queue\n`!queue` — Show the current queue", inline=False)
        embed.add_field(name="Playback", value="`!play <song>` — Bot joins the voice channel and plays the queue or your song\n`!pause` — Pause playback\n`!resume` — Resume playback\n`!skip` — Skip to the next song\n`!stop` — Stop playback and clear the queue", inline=False)
        embed.add_field(name="Voice (TTS)", value="`!speak <text>` — Bot speaks the given text in Turkish", inline=False)
        embed.add_field(name="Voice Channel", value="`!join` — Bot joins your voice channel\n`!leave` — Bot leaves the voice channel", inline=False)
        embed.add_field(name="Help", value="`!help` — Show this help message", inline=False)
        embed.set_footer(text=f"Prefix: ! | Developed by mirage")
        await ctx.send(embed=embed)


# ==================== MAIN ====================

def run_discord_bot():
    """Run the Discord bot in its own event loop"""
    bot.run(BOT_TOKEN)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Discord Bot with MCP Server")
    parser.add_argument("--mode", choices=["discord", "mcp", "http"], default="discord",
                        help="Run mode: 'discord' for bot only, 'mcp' for stdio+http, 'http' for HTTP only")
    parser.add_argument("--port", type=int, default=9000, help="HTTP server port (default: 9000)")
    args = parser.parse_args()
    
    if args.mode == "discord":
        # Run only Discord bot
        print("Starting Discord Bot...")
        bot.run(BOT_TOKEN)
    
    elif args.mode == "mcp":
        # Run BOTH stdio (for Claude Desktop) AND http (for mobile/remote)
        discord_thread = threading.Thread(target=run_discord_bot, daemon=True)
        discord_thread.start()
        time.sleep(2)
        
        # Start HTTP server in background thread
        def run_http_server():
            http_app = mcp.http_app(path="/sse")
            config = Config(app=http_app, host="127.0.0.1", port=args.port, log_level="warning")
            server = Server(config)
            server.run()
        
        http_thread = threading.Thread(target=run_http_server, daemon=True)
        http_thread.start()
        print(f"HTTP server running on http://127.0.0.1:{args.port}/sse", file=sys.stderr)
        
        # Run stdio in main thread (for Claude Desktop)
        mcp.run()
    
    elif args.mode == "http":
        # Run HTTP/SSE MCP server only (for Cloudflare Tunnel)
        print(f"Starting Discord Bot + HTTP MCP Server on http://127.0.0.1:{args.port}")
        print(f"SSE endpoint: http://127.0.0.1:{args.port}/sse")
        
        discord_thread = threading.Thread(target=run_discord_bot, daemon=True)
        discord_thread.start()
        time.sleep(2)
        
        mcp.run(transport="sse", host="127.0.0.1", port=args.port)


"""
Usage:
    python dc_bot_mcp.py                    # Discord bot only
    python dc_bot_mcp.py --mode mcp         # MCP stdio (Claude Desktop local)
    python dc_bot_mcp.py --mode http        # HTTP/SSE on port 9000

For BOTH Desktop + Mobile access:
    1. Claude Desktop config (claude_desktop_config.json):
       {
         "mcpServers": {
           "discord-bot": {
             "command": "python",
             "args": ["c:\\Users\\mirac\\OneDrive\\Masaüstü\\Code\\dc_bot\\dc_bot_mcp.py", "--mode", "http"]
           }
         }
       }
    
    2. Cloudflare Tunnel: cloudflared tunnel --url http://localhost:9000
    
    3. Claude Mobile: Settings → MCP → Add: https://your-domain.com/sse

    Now both Desktop and Mobile connect to the same server!
"""