import os
import sys
import re
import time
import glob
import pickle
import logging

import yaml
import requests

from discord import Client, errors
from discord.ext import commands
from discord.utils import get
from asyncio import sleep

from embeds import refresh_embed, add_source, remove_source
from user import download_users_list

# Token is stored in token.yaml, with the key 'token'

with open('token.yaml', 'r') as t:
    token = yaml.load(t, Loader=yaml.FullLoader)["token"]

logging.basicConfig(level=logging.INFO, format='%(asctime)s: %(message)s')

#  start client
client = commands.Bot(command_prefix=commands.when_mentioned, case_insensitive=False)
client.remove_command('help') # remove default help

period = 60  # how often (in seconds) to check if there are new entries

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
    channels = list(iter(client.guilds))[0].channels
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
    while not client.is_ready():
        await sleep(1)
    # check if scraper is running
    if os.path.exists('pid'):
        with open('pid', 'r') as pid_f:
            pid = int(pid_f.read())
        if not check_pid(pid):
            pass
            # call mal.py as a background process
            os.system("python3 mal.py &")
    else:
        os.system("python3 mal.py &")
    if os.path.exists("new"):
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
                await feed_channel.send(embed=new)
            else:
                await nsfw_feed_channel.send(embed=new)
            m = re.search("https:\/\/myanimelist\.net\/anime\/(\d+)", new.url)
            # verify that it got printed
            check_channel = feed_channel if sfw else nsfw_feed_channel
            async for message in check_channel.history(limit=10, oldest_first=False):
                try:
                    embed = message.embeds[0]
                    embed_id = re.search("https:\/\/myanimelist\.net\/anime\/(\d+)", embed.url)
                    if m.group(1) == embed_id.group(1):
                        old_entries.add(m.group(1))
                        break
                except Exception as e: # i.e. test_log messages that don't have embeds
                    continue
    with open("old", 'w') as old_f:
        old_f.write("\n".join(old_entries))
    os.remove("new") # remove new entries file as we've logged them


@client.command()
async def add_new(ctx):
    if not (ctx.author.permissions_in(ctx.channel).administrator or "trusted" in [role.name.lower() for role in ctx.author.roles]):
        await ctx.channel.send("You must have the `trusted` role or be an administrator to use this command.")
        return
    if os.path.exists("new"):
        await add_new_entries()
    else:
        await ctx.channel.send("No new entries found.")


@client.command()
async def test_log(ctx):
    if not ctx.author.permissions_in(ctx.channel).administrator:
        await ctx.channel.send("This command can only be run by administrators.")
        return
    await client.send_message(feed_channel, "test message. beep boop")
    await client.send_message(nsfw_feed_channel, "test message. beep boop")


@client.command()
async def source(ctx, mal_id: int, *, links):
    author = ctx.author
    if not (ctx.author.permissions_in(ctx.channel).administrator or "trusted" in [role.name.lower() for role in author.roles]):
        await ctx.channel.send("You must have the `trusted` role or be an administrator to use this command.")
        return

    adding_source = True
    if links.strip().lower() == "remove":
        adding_source = False

    if adding_source:
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
                await ctx.channel.send("`{}` has no schema (e.g. https), its not a valid URL.".format(link))
                return
            if not resp.status_code == requests.codes.ok:
                await ctx.channel.send("Error connecting to <{}> with status code {}".format(link, resp.status_code))
                return
            valid_links.append(link)

    # get logs from feed
    async for message in feed_channel.history(limit=999999, oldest_first=False):
        try:
            embed = message.embeds[0]
        except Exception as e: # i.e. test_log messages that don't have embeds
            continue
        m = re.search("https:\/\/myanimelist\.net\/anime\/(\d+)", embed.url)
        # if this matches the MAL id
        if m.group(1) == str(mal_id):
            if adding_source:
                new_embed, is_new_source = add_source(embed, valid_links)
                await message.edit(embed=new_embed)
                await ctx.channel.send("{} source for '{}' successfully.".format("Added" if is_new_source else "Replaced", embed.title))
                return
            else:
                new_embed = remove_source(embed)
                await message.edit(embed=new_embed)
                await ctx.channel.send("Removed source for '{}' successfully.".format(embed.title))
                return
    await ctx.channel.send("Could not find a message that conatins the MAL id {} in {}".format(mal_id, feed_channel.mention))


@client.command()
async def refresh(ctx, mal_id: int):
    author = ctx.author
    if not (ctx.author.permissions_in(ctx.channel).administrator or "trusted" in [role.name.lower() for role in author.roles]):
        await ctx.channel.send("You must have the `trusted` role or be an administrator to use this command.")
        return
    # get logs from feed
    remove_image = "remove image" in ctx.message.content.lower()
    async for message in feed_channel.history(limit=999999, oldest_first=False):
        try:
            embed = message.embeds[0]
        except Exception as e: # i.e. test_log messages that don't have embeds
            continue
        m = re.search("https:\/\/myanimelist\.net\/anime\/(\d+)", embed.url)
        # if this matches the MAL id
        if m.group(1) == str(mal_id):
            new_embed = refresh_embed(embed, mal_id, remove_image)
            await message.edit(embed=new_embed)
            await ctx.channel.send("{} for '{}' successfully.".format("Removed image" if remove_image else "Updated fields", embed.title))
            return
    await ctx.channel.send("Could not find a message that conatins the MAL id {} in {}".format(mal_id, feed_channel.mention))


@client.command()
async def check(ctx, mal_username, num: int):
    leftover_args = " ".join(ctx.message.content.strip().split()[4:])
    print_all = "all" in leftover_args.lower()
    message = await ctx.channel.send("Downloading {}'s list (downloaded 0 anime entries...)".format(mal_username))
    parsed = {}
    for entries in download_users_list(mal_username):
        for e in entries:
            parsed[e['mal_id']] = e['watching_status']
        await message.edit(content=f"Downloading {mal_username}'s list (downloaded {len(parsed)} anime entries...)")
    found_entry = False # mark True if we find an entry the user hasnt watched
    async for message in feed_channel.history(limit=num, oldest_first=False):
        try:
            embed = message.embeds[0]
        except Exception as e:
            continue
        source_exists = "Source" in [f.name for f in embed.fields]
        if source_exists or print_all:
            m = re.search("https:\/\/myanimelist\.net\/anime\/(\d+)", embed.url)
            mal_id = int(m.group(1))
            on_your_list = mal_id in parsed
            on_your_ptw = mal_id in parsed and parsed[mal_id] == "6"
            if (not on_your_list) or (on_your_ptw and source_exists):
                found_entry = True
                if source_exists:
                    fixed_urls = " ".join(["<{}>".format(url) for url in [f.value for f in embed.fields if f.name == "Source"][0].split()])
                    if on_your_ptw:
                        await ctx.channel.send("{} is on your PTW, but it has a source: {}".format(embed.url, fixed_urls))
                    else:
                        await ctx.channel.send("{} isn't on your list, but it has a source: {}".format(embed.url, fixed_urls))
                else:
                    await ctx.channel.send("{} isn't on your list.".format(embed.url))

    if not found_entry:
        await ctx.channel.send("I couldn't find any MAL entries in the last {} entries that aren't on your list.".format(num))


@client.command()
async def help(ctx):
    help_str = "**User commands**:\n`help`: describe commands\n" + \
               "`check`: checks if you've watched the 'n' most recent entries in {}\n".format(feed_channel.mention) + \
               "\tSyntax: `@notify check <mal_username> <n>`" + \
               "\n\tExample `@notify check purplepinapples 10`\n" + \
               "\tBy default, this will only print entries that have sources, provide the `all` keyword to make it check all entries:\n" + \
               "\t\tExample: `@notify check purplepinapples 10 all`\n" + \
               "**Trusted commands**:\n" + \
               "`source`: Adds a link to a embed in {}\n\tSyntax: `@notify source <mal_id> <link>`".format(feed_channel.mention) + \
               "\n\tExample: `@notify source 32287 https://www.youtube.com/watch?v=1RzNDZFQllA`\n" + \
               "\t`@notify source <mal_id> remove` will remove a source from an embed\n" + \
               "`add_new`: Checks if there are new entries waiting to be printed. This happens once every 3 minutes automatically\n" + \
               "`refresh`: Refreshes the image and synopsis on an embed\n\tExample: `@notify refresh 39254`\n" + \
               "\tYou can do `@notify refresh <mal_id> remove image` to remove the image from an embed (if it happens to be the placeholder MAL image)\n" + \
               "**Administrator commands**:\n" + \
               "`test_log`: send a test message to {} to check permissions\n".format(feed_channel.mention)
    await ctx.channel.send(help_str)


@client.event
async def on_command_error(ctx, error):

    command_name = ctx.invoked_with.replace("`", "")
    args = ctx.message.content.split(">", maxsplit=1)[1].strip().replace("`", '').split()

    # prevent self-loops
    if hasattr(ctx.command, 'on_error'):
        print("on_command_error self loop occured")
        return

    if isinstance(error, commands.CommandNotFound):
        await ctx.channel.send("Could not find the command `{}`. Use `@notify help` to see a list of commands.".format(command_name))
    elif isinstance(error, commands.MissingRequiredArgument) and command_name == "source":
        await ctx.channel.send("You're missing one or more arguments for the `source` command.\nExample: `@notify source 31943 https://youtube/...`")
    elif isinstance(error, commands.MissingRequiredArgument) and command_name == "refresh":
        await ctx.channel.send("Provide the MAL id you wish to refresh the embed for.")
    elif isinstance(error, commands.BadArgument) and command_name in ["source", "refresh"]:
        try:
            int(args[1])
        except ValueError:
            await ctx.channel.send("Error converting `{}` to an integer.".format(args[1]))
    elif isinstance(error, commands.MissingRequiredArgument) and command_name == "check":
        await ctx.channel.send("Provide your MAL username and then the number of entries in {} you want to check".format(feed_channel.mention))
    elif isinstance(error, commands.BadArgument) and command_name == "check":
        try:
            int(args[2])
        except:
            await ctx.channel.send("Error converting `{}` to an integer.".format(args[2]))
    elif isinstance(error, commands.CommandInvokeError):
        original_error = error.original
        if isinstance(original_error, errors.HTTPException):
            await ctx.channel.send("There was an issue connecting to the Discord API. Wait a few moments and try again.")
        elif isinstance(original_error, RuntimeError):
            await ctx.channel.send(str(original_error))
    else:
        await ctx.channel.send("Uncaught error: {}: {}".format(type(error).__name__, error))
        raise error

client.loop.create_task(loop())
client.run(token, bot=True, reconnect=True)
