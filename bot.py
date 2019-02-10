import os
import sys
import re
import time
import pickle

from discord import Client, Embed, Colour
from discord.ext import commands
from discord.utils import get
from asyncio import sleep

import yaml
import jikanpy

# Token is stored in token.yaml, with the key token

with open('token.yaml', 'r') as t:
    token = yaml.load(t)["token"]

#  start client
client = commands.Bot(command_prefix=commands.when_mentioned, case_insensitive=False)
client.remove_command('help') # remove default help

period = 30  # how often to check if there are new entries

feed_channel = None
nsfw_feed_channel = None
verbose_flag = True
jikan = jikanpy.Jikan()

@client.event
async def on_ready():
    global feed_channel
    global nsfw_feed_channel
    channels = list(iter(client.servers))[0].channels
    feed_channel = get(channels, name="feed")
    nsfw_feed_channel = get(channels, name="nsfw-feed")
    print("ready!")

# this is run in event loop, see bottom of file
async def loop():
    while not client.is_closed:
        print("Started outer loop")
        if client.is_logged_in and os.path.exists("new"):
            print("Started inner loop")
            await add_new_entries()
        await sleep(period) # check for 'new' file periodically

async def add_new_entries():
    with open("new", 'rb') as new_f:
        pickles = pickle.load(new_f)
    with open("old", 'r') as old_f:
        old_entries = set(old_f.read().splitlines())
    for new, sfw in pickles:
        if new not in old_entries: # makes sure we're not printing entries twice
            if sfw:
                await client.send_message(feed_channel, embed=new)
            else:
                await client.send_message(nsfw_feed_channel, embed=new)
            m = re.search("https:\/\/myanimelist\.net\/anime\/(\d+)", new.url)
            old_entries.add(m.group(1))
            sleep(0.5) # prevent lockups
    with open("old", 'w') as old_f:
        old_f.write("\n".join(old_entries))
    os.remove("new") # remove new entries file as we've logged them

@client.command(pass_context=True)
async def test_log(ctx):
    if not ctx.message.author.server_permissions.administrator:
        await client.say("This command can only be run by administrators.")
        return
    await client.send_message(feed_channel, "test message. beep boop")
    await client.send_message(nsfw_feed_channel, "test message. beep boop")


@client.command(pass_context=True)
async def verbose(ctx):
    global verbose_flag
    if not ctx.message.author.server_permissions.administrator:
        await client.say("This command can only be run by administrators.")
        return
    if not verbose_flag:
        verbose_flag = True
        await client.say("Verbose logs have been toggled on.")
    else:
        verbose_flag = False
        await client.say("Verbose logs have been toggled off.")

@client.command()
async def help():
    help_str = "User commands:\n`help`: describe commands\n" + \
               "Trusted commands:\n" + \
               "Administrator commands:\n" + \
               "`verbose`: toggle verbose logs for command errors\n" + \
               "`test_log`: send a test message to #feed to check permissions\n"
    await client.say(help_str)


# use get_channel() with the id to get the channel object
@client.command(pass_context=True)
@client.event
async def on_command_error(error, ctx):
    message = ctx.message.content.split(">", maxsplit=1)[1].lower().strip()
    message = message.replace("@", "") # make sure bot doesn't ping people
    command_name = message.split()[0]
    if verbose_flag:
        await client.send_message(ctx.message.channel, str(error))
    elif command_name in ['help', 'verbose']: # try to match against commands
        if command_name == 'help':
            await help(ctx)
        elif command_name == 'verbose':
            await verbose(ctx)
    else:
        await client.send_message(ctx.message.channel, "Unknown command. Use `@notify help` to see a list of commands".format(message.split()[0]))

client.loop.create_task(loop())
client.run(token)

