import os
import sys
import re
import time
import glob
import pickle

import yaml
import requests

from discord import Client, Embed, Color
from discord.ext import commands
from discord.utils import get
from asyncio import sleep

# Token is stored in token.yaml, with the key 'token'

with open('token.yaml', 'r') as t:
    token = yaml.load(t)["token"]

#  start client
client = commands.Bot(command_prefix=commands.when_mentioned, case_insensitive=False)
client.remove_command('help') # remove default help

period = 3 * 60  # how often (in seconds) to check if there are new entries

feed_channel = None
nsfw_feed_channel = None


# https://stackoverflow.com/a/568285
def check_pid(pid):
    """ Check For the existence of a unix pid. """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True

@client.event
async def on_ready():
    global feed_channel
    global nsfw_feed_channel
    channels = list(iter(client.servers))[0].channels
    feed_channel = get(channels, name="feed")
    nsfw_feed_channel = get(channels, name="nsfw-feed")
    print("ready!")

# override on_message so we can remove double spaces after the bot name, which would ordinarily not trigger commands
@client.event
async def on_message(message):
    message.content = " ".join(message.content.strip().split()) # remove weird spaces
    await client.process_commands(message)

# this is run in event loop, see bottom of file
async def loop():
    while not client.is_closed:
        # check if scraper is running
        with open('pid', 'r') as pid_f:
            pid = int(pid_f.read())
        if not check_pid(pid):
            # call scrape_mal.py as a background process
            os.system("python3 scrape_mal.py &")
        if client.is_logged_in and os.path.exists("new"):
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
async def print_logs(ctx, num_lines: int):
    if not ctx.message.author.server_permissions.administrator:
        await client.say("This command can only be run my administrators")
        return

    # get the number of lines specificed by user
    log_str = ""
    for file in sorted(glob.glob("*.log"), key=os.path.getmtime):
        if num_lines <= 0:
            break
        with open(file, 'r') as f:
            lines = f.readlines()
            if len(lines) < num_lines:
                log_str += "".join(lines)
                num_lines -= len(lines)
            else:
                log_str += "".join(lines[-num_lines:])
                num_lines = 0

    # tokenize messages and send them
    log_allowed_message = "" # A message with less than 2000 characters
    for l in log_str.splitlines():
        if len(log_allowed_message) + len(l) >= 1990:
            await client.say("```\n{}\n```".format(log_allowed_message.strip()))
            log_allowed_message = ""
        else:
            log_allowed_message += l + "\n"
    if len(log_allowed_message) > 0:
        await client.say("```\n{}\n```".format(log_allowed_message.strip()))


@client.command(pass_context=True)
async def add_new(ctx):
    if not (ctx.message.author.server_permissions.administrator or "trusted" in [role.name.lower() for role in ctx.message.author.roles]):
        await client.say("You must have the `trusted` role or be an administrator to use this command.")
        return
    if os.path.exists("new"):
        await add_new_entries()
    else:
        await client.say("No new entries found.")


@client.command(pass_context=True)
async def test_log(ctx):
    if not ctx.message.author.server_permissions.administrator:
        await client.say("This command can only be run by administrators.")
        return
    await client.send_message(feed_channel, "test message. beep boop")
    await client.send_message(nsfw_feed_channel, "test message. beep boop")


@client.command(pass_context=True)
async def source(ctx, mal_id: int, *, links):
    author = ctx.message.author
    if not (author.server_permissions.administrator or "trusted" in [role.name.lower() for role in author.roles]):
        await client.say("You must have the `trusted` role or be an administrator to use this command.")
        return

    valid_links = []

    # if there are multiple links, check each
    for link in links.split():
        # remove supression from link, if it exists
        if link[0] == "<":
            link = link[1:]
        if link[-1] == ">":
            link = link[0:-1]

        # test if link exists
        try:
            resp = requests.get(link)
        except requests.exceptions.MissingSchema:
            await client.say("`{}` has no schema (e.g. https), its not a valid URL.".format(link))
            return
        if not resp.status_code == requests.codes.ok:
            await client.say("Error connecting to <{}> with status code {}".format(link, resp.status_code))
            return

        valid_links.append(link)

    # get logs from feed
    async for message in client.logs_from(feed_channel, limit=999999, reverse=True):
        try:
            embed = message.embeds[0]
        except Exception as e: # i.e. test_log messages that don't have embeds
            continue
        m = re.search("https:\/\/myanimelist\.net\/anime\/(\d+)", embed['url'])
        # if this matches the MAL id
        if m.group(1) == str(mal_id):
            new_embed=Embed(title=embed['title'], url=embed['url'], color=Color.dark_blue())
            new_embed.set_thumbnail(url=embed['thumbnail']['url'])
            for f in embed['fields']:
                if f['name'] == "Status":
                    new_embed.add_field(name="Status", value=f['value'], inline=True)
                elif f['name'] == "Air Date":
                    new_embed.add_field(name="Air Date", value=f['value'], inline=True)
                elif f['name'] == "Synopsis":
                    new_embed.add_field(name="Synopsis", value=f['value'], inline=False)
                # if there was already a source field, replace it
                elif f['name'] == "Source":
                    new_embed.add_field(name=f['name'], value=" ".join(valid_links), inline=False)
            # if there wasn't a source field
            is_new_source = "Source" not in [f['name'] for f in embed['fields']]
            if is_new_source:
                new_embed.add_field(name="Source", value=" ".join(valid_links), inline=False)
            # edit message with new embed
            await client.edit_message(message, embed=new_embed)
            await client.say("{} source for '{}' successfully.".format("Added" if is_new_source else "Replaced", embed['title']))
            return
    await client.say("Could not find a message that conatins the MAL id {} in {}".format(mal_id, feed_channel.mention))


@client.command()
async def help():
    help_str = "**User commands**:\n`help`: describe commands\n" + \
               "**Trusted commands**:\n" + \
               "`source`: Adds a link to a embed in {}\n\tSyntax: `@notify source <mal_id> <link>`\n\tExample: `@notify source 32287 https://www.youtube.com/watch?v=1RzNDZFQllA`\n".format(feed_channel.mention) + \
               "`add_new`: Checks if there are new entries waiting to be printed. This happens once every 3 minutes automatically\n" + \
               "**Administrator commands**:\n" + \
               "`test_log`: send a test message to {} to check permissions\n".format(feed_channel.mention) + \
               "`print_logs <num>`: print recent logs from other process which checks the 'Just Added' page\n"
    await client.say(help_str)


# use get_channel() with the id to get the channel object
@client.command(pass_context=True)
@client.event
async def on_command_error(error, ctx):

    command_name = ctx.invoked_with.replace("`", "")
    args = ctx.message.content.split(">", maxsplit=1)[1].strip().replace("`", '').split()

    # prevent self-loops
    if hasattr(ctx.command, 'on_error'):
        print("on_command_error self loop occured")
        return

    if isinstance(error, commands.CommandNotFound):
        await client.send_message(ctx.message.channel, "Could not find the command `{}`. Use `@notify help` to see a list of commands.".format(command_name))
    elif isinstance(error, commands.MissingRequiredArgument) and command_name == "source":
        await client.send_message(ctx.message.channel, "You're missing one or more arguments for the `source` command.\nExample: `@notify source 31943 https://youtube/...`")
    elif isinstance(error, commands.BadArgument) and command_name == "source":
        try:
            int(args[1])
        except ValueError:
            await client.send_message(ctx.message.channel, "Error converting `{}` to an integer".format(args[1]))
    else:
        await client.send_message(ctx.message.channel, "Uncaught error [{}]: {}".format(type(error).__name__, error))
        raise error

client.loop.create_task(loop())
client.run(token)
