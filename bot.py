import os
import sys
import re
import time
import pdb
import json
import logging
import inspect
import traceback
from functools import wraps

import yaml
import requests
import aiofiles
import git

from discord import errors, Message, Embed
from discord.ext import commands
from discord.utils import get
from asyncio import sleep

from utils import *
from utils.embeds import create_embed, refresh_embed, add_source, remove_source
from utils.user import download_users_list  # currently not used

# setup project and discord.py logs
logger = setup_logger(__name__, "bot", supress_stream_output=True)
logging.basicConfig()
discord_logs = logging.getLogger("discord")
discord_logs.setLevel(logging.INFO)
root_dir = os.path.abspath(os.path.dirname(__file__))
mal_id_cache_dir = os.path.join(root_dir, "mal-id-cache")
mal_id_cache_json_file = os.path.join(mal_id_cache_dir, "cache.json")
token_file = os.path.join(root_dir, "token.yaml")

# bot object
client = commands.Bot(
    command_prefix=commands.when_mentioned, case_insensitive=False)
client.remove_command('help')  # remove default help
# amount of time to wait between checking for new entries
client.period = 60 * 15


def truncate(obj, limit: int):
    """Truncates the length of args/kwargs for the @log decorator so that we can read logs easier"""
    if len(repr(obj)) < limit:
        return repr(obj)
    else:
        return repr(obj)[:limit] + "... (truncated)"


def log(func):
    """Decorator for functions, to log start/end times"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        _id = uuid.get_and_increment()
        args_text = truncate(args, 2000)
        kwargs_text = truncate(kwargs, 2000)
        logger.debug(
            f"{func.__name__} ({_id}) called with {args_text} {kwargs_text}")
        if inspect.iscoroutinefunction(func):
            result = await func(*args, **kwargs)
        else:
            result = func(*args, **kwargs)
        logger.debug(f"{func.__name__} ({_id}) finished")
        return result
    return wrapper


class FileState():
    """Parent class for managing file states"""

    def __init__(self, filepath):
        self.filepath = filepath

    def file_exists(self):
        return os.path.exists(self.filepath)

    def __repr__(self):
        return f"{self.__class__.__name__}(filepath={self.filepath})"


class OldDatabase(FileState):
    """Models and interacts with the 'old' database file"""

    def __init__(self, *, filepath):
        super().__init__(filepath)

    @log
    async def read(self):
        async with aiofiles.open(self.filepath, mode='r') as old_f:
            contents = await old_f.read()
            return set(contents.splitlines())

    @log
    async def dump(self, contents):
        contents = sorted(list(contents), key=int)
        async with aiofiles.open(self.filepath, mode='w') as old_f:
            await old_f.write("\n".join(contents))
            await old_f.flush()


@log
async def update_git_repo():
    """Updates from the remote mal-id-cache"""
    g = git.cmd.Git(mal_id_cache_dir)
    g.pull()
    commit_id = g.log().splitlines()[0].split()[-1]
    logger.debug(f"{g.working_dir} is at commit hash {commit_id}")


@log
async def read_json_cache():
    """Reads the cache from mal-id-cache/cache.json and combines sfw ids with nsfw"""
    async with aiofiles.open(mal_id_cache_json_file, mode='r') as cache_f:
        plain_text_contents = await cache_f.read()
    contents = json.loads(plain_text_contents)
    return list(map(str, contents["sfw"] + contents["nsfw"]))


def is_admin_or_owner():
    """Check that returns True if the user is the owner/admin on the server"""
    async def predicate(ctx):
        is_owner = await ctx.bot.is_owner(ctx.author)
        is_admin = ctx.author.permissions_in(ctx.channel).administrator
        return is_owner or is_admin
    return commands.check(predicate)


def has_privilege():
    """Check that returns true if the user can use 'trusted' commands or is owner/admin"""
    async def predicate(ctx):
        is_owner = await ctx.bot.is_owner(ctx.author)
        is_admin = ctx.author.permissions_in(ctx.channel).administrator
        is_trusted = "trusted" in [role.name.lower()
                                   for role in ctx.author.roles]
        return is_owner or is_admin or is_trusted
    return commands.check(predicate)


@client.event
@log
async def on_ready():
    # setup global variables
    guilds = list(iter(client.guilds))
    if len(guilds) != 1:
        logger.critical("This bot should only be used on one server")
        await client.logout()
        sys.exit(1)
    channels = guilds[0].channels
    client.feed_channel = get(channels, name="feed")
    client.nsfw_feed_channel = get(channels, name="nsfw-feed")
    if client.feed_channel is None:
        logger.critical("Couldn't find the 'feed' channel")
    if client.nsfw_feed_channel is None:
        logger.critical("Couldn't find the 'nsfw-feed' channel")
    client.old_db = OldDatabase(filepath=os.path.join(root_dir, "old"))
    client.loop.create_task(print_loop())


# override on_message so we can remove double spaces after the bot name,
# which would ordinarily not trigger commands
@client.event
async def on_message(message):
    message.content = re.sub(
        "\s{2,}", " ", message.content)  # remove weird spaces
    await client.process_commands(message)


@log
async def search_feed_for_mal_id(mal_id, channel, limit) -> Message:
    """
    checks a feed channel (which is filled with embeds) for a message
    returns the discord.Message object if it finds it within limit, else return None
    """
    async for message in channel.history(limit=limit, oldest_first=False):
        try:
            embed = message.embeds[0]
            embed_id = extract_mal_id_from_url(embed.url)
            if embed_id is not None and embed_id == mal_id:
                logger.debug("Found message: {}".format(message))
                return message
        except Exception as e:
            logger.warning("Error while searching history: {}".format(str(e)))
            continue
    return None  # if we've exited the loop


# run in event loop
@log
async def print_loop():
    """main loop - checks if entries exist periodically and prints them"""
    await client.wait_until_ready()
    while not client.is_closed():
        # if there are new entries, print them
        await print_new_embeds()
        logger.debug(f"Sleeping for {client.period}")
        await sleep(client.period)


@client.command()
@has_privilege()
@log
async def add_new(ctx):
    async with ctx.channel.typing():
        new_embeds = await create_new_embeds(ctx)
        if not new_embeds:
            return await ctx.channel.send("No new entries found.")
        else:
            entry_count = len(new_embeds)
            await ctx.channel.send("Found {} new entr{}.".format(entry_count, "y" if entry_count == 1 else "ies"))
            return await print_new_embeds(new_embeds=new_embeds)


@log
async def create_new_embeds(ctx=None):
    """
    git pulls, reads the json cache, and returns new embeds if they exist
    this *is* blocking, but temporarily blocking seems better than managing multple processes
    """
    await update_git_repo()
    ids = await read_json_cache()
    new_ids = []
    new_embeds = []
    if not client.old_db.file_exists():
        logger.info(f"{client.old_db.filepath} didn't exist, creating...")
        with open(client.old_db.filepath):
            await client.old_db.dump(ids)
    else:
        old_ids = await client.old_db.read()
        new_ids = sorted(list(set(ids) - set(old_ids)))
        logger.debug(f"new ids: {truncate(new_ids, 200)}")

    # couldnt have possibly be 1000 entries approved since we last checked
    # this means there was an error writing to old_db
    if len(new_ids) > 1000:
        error_message = f"There were {len(new_ids)} new entries, there must have been an error writing to the old_db file at '{client.old_db.filepath}'"
        logger.warning(error_message)
        if ctx:
            await ctx.channel.send(error_message)
        return []

    for new_id in new_ids:
        sleep(0)  # allow other items in the asyncio loop to run
        new_embeds.append(create_embed(int(new_id), logger))
    return new_embeds


@log
async def print_new_embeds(new_embeds=None):
    if new_embeds is None:
        new_embeds = await create_new_embeds()
    if new_embeds:
        old_ids = await client.old_db.read()
        for embed, sfw in new_embeds:
            print_to_channel = client.feed_channel if sfw else client.nsfw_feed_channel
            new_mal_id = extract_mal_id_from_url(embed.url)
            if new_mal_id not in old_ids:  # make sure we're not printing entries twice
                logger.debug("Printing {} to {}".format(
                    new_mal_id, "#feed" if sfw else "#nsfw-feed"))
                await print_to_channel.send(embed=embed)
            # check that we actually printed the embed
            printed_message = await search_feed_for_mal_id(mal_id=new_mal_id, channel=print_to_channel, limit=50)
            if printed_message:
                logger.debug(
                    "Found printed message in channel, adding {} to old ids".format(new_mal_id))
                old_ids.add(new_mal_id)
            else:
                logger.warning(
                    "Couldnt find printed message for id {} in channel".format(new_mal_id))
        await client.old_db.dump(old_ids)


@client.command()
@is_admin_or_owner()
@log
async def test_log(ctx):
    message = "test message. beep boop"
    await client.feed_channel.send(message)
    await client.nsfw_feed_channel.send(message)


@client.command()
@has_privilege()
@log
async def source(ctx, mal_id: int, *, links):

    with ctx.channel.typing():
        adding_source = True
        if links.strip().lower() == "remove":
            adding_source = False
        logger.debug("{} source".format(
            "Adding" if adding_source else "Removing"))

        if adding_source:
            valid_links = []
            # if there are multiple links, check each
            for link in links.split():
                # remove supression from link, if it exists
                link = remove_discord_link_supression(link)

                # test if link exists; blocking
                try:
                    resp = requests.get(link)
                    sleep(0)
                except requests.exceptions.MissingSchema:
                    return await ctx.channel.send("`{}` has no schema (e.g. https), its not a valid URL.".format(link))
                if not resp.status_code == requests.codes.ok:
                    return await ctx.channel.send("Error connecting to <{}> with status code {}".format(link, resp.status_code))
                valid_links.append(link)

        # get logs from feed
        message = await search_feed_for_mal_id(str(mal_id), client.feed_channel, limit=999999)
        if not message:
            return await ctx.channel.send("Could not find a message that contains the MAL id {} in {}".format(mal_id, client.feed_channel.mention))
        else:
            embed = message.embeds[0]
            if adding_source:
                new_embed, is_new_source = add_source(embed, valid_links)
                await message.edit(embed=new_embed)
                return await ctx.channel.send("{} source for '{}' successfully.".format("Added" if is_new_source else "Replaced", embed.title))
            else:
                new_embed = remove_source(embed)
                await message.edit(embed=new_embed)
                return await ctx.channel.send("Removed source for '{}' successfully.".format(embed.title))


@client.command()
@has_privilege()
@log
async def refresh(ctx, mal_id: int):
    with ctx.channel.typing():
        remove_image = "remove image" in ctx.message.content.lower()
        message = await search_feed_for_mal_id(str(mal_id), client.feed_channel, limit=999999)
        if not message:
            return await ctx.channel.send("Could not find a message that contains the MAL id {} in {}".format(mal_id, client.feed_channel.mention))
        else:
            embed = message.embeds[0]
            new_embed = refresh_embed(embed, mal_id, remove_image, logger)
            await message.edit(embed=new_embed)
            return await ctx.channel.send("{} for '{}' successfully.".format("Removed image" if remove_image else "Updated fields", embed.title))


@client.command()
@log
async def check(self, ctx, mal_username, num: int):
    # the request.get calls are synchronous - blocking, figure out a better way to implement this
    return await ctx.channel.send("This command is currently disabled.")
    leftover_args = " ".join(ctx.message.content.strip().split()[4:])
    print_all = "all" in leftover_args.lower()
    message = await ctx.channel.send("Downloading {}'s list (downloaded 0 anime entries...)".format(mal_username))
    parsed = {}
    for entries in download_users_list(mal_username):
        for e in entries:
            parsed[e['mal_id']] = e['watching_status']
        await message.edit(content=f"Downloading {mal_username}'s list (downloaded {len(parsed)} anime entries...)")
    found_entry = False  # mark True if we find an entry the user hasnt watched
    async for message in client.feed_channel.history(limit=num, oldest_first=False):
        try:
            embed = message.embeds[0]
        except Exception as e:
            continue
        source_exists = "Source" in [f.name for f in embed.fields]
        if source_exists or print_all:
            m = re.search(
                "https:\/\/myanimelist\.net\/anime\/(\d+)", embed.url)
            mal_id = int(m.group(1))
            on_your_list = mal_id in parsed
            on_your_ptw = mal_id in parsed and parsed[mal_id] == "6"
            if (not on_your_list) or (on_your_ptw and source_exists):
                found_entry = True
                if source_exists:
                    fixed_urls = " ".join(["<{}>".format(url) for url in [
                                          f.value for f in embed.fields if f.name == "Source"][0].split()])
                    if on_your_ptw:
                        await ctx.channel.send("{} is on your PTW, but it has a source: {}".format(embed.url, fixed_urls))
                    else:
                        await ctx.channel.send("{} isn't on your list, but it has a source: {}".format(embed.url, fixed_urls))
                else:
                    await ctx.channel.send("{} isn't on your list.".format(embed.url))

    if not found_entry:
        await ctx.channel.send("I couldn't find any MAL entries in the last {} entries that aren't on your list.".format(num))


@client.command()
@log
async def help(ctx):
    mentionbot = f"@{ctx.guild.me.display_name}"
    embed=Embed(title="mal-notify help", color=0x4eb1ff)
    embed.add_field(name="basic commands", value='\u200b', inline=False)
    embed.add_field(name=f"{mentionbot} help", value="Show this message", inline=False)
    embed.add_field(name=f"{mentionbot} check <mal_username> <n> [all]", value=f"Check the last 'n' in #feed entries for any items not on your MAL. Can add 'all' after the number of entries to check to list all items. By default only lists items which have sources. e.g. `{mentionbot} check Xinil 10 all`. This command is currently disabled.", inline=False)
    embed.add_field(name="'trusted' commands", value='\u200b', inline=False)
    embed.add_field(name=f"{mentionbot} add_new", value="Checks if any new items have been added in the last 15 minutes. Runs automatically at 15 minute intervals.", inline=False)
    embed.add_field(name=f"{mentionbot} source <mal_id> <links...|remove>", value=f"Adds a source to an embed in #feed. Requires either the link or the `remove` keyword. e.g. `{mentionbot} source 1 https://....` or `{mentionbot} source 14939 remove`", inline=False)
    embed.add_field(name=f"{mentionbot} refresh", value=f"Refreshes an embed - checks if the metadata (i.e. description, air date, image) has changed and updates accordingly. e.g. `{mentionbot} refresh 40020`", inline=False)
    await ctx.channel.send(embed=embed)


@client.event
async def on_command_error(ctx, error):

    command_name = None
    if ctx.command:
        command_name = ctx.command.name
    clean_message_content = ctx.message.content.split(
        ">", maxsplit=1)[1].strip().replace("`", '')
    args = clean_message_content.split()

    # prevent self-loops; on_command_error calling on_command_error
    if hasattr(ctx.command, 'on_error'):
        logger.warning("on_command_error self loop occured")
        return

    if isinstance(error, commands.CommandNotFound):
        await ctx.channel.send("Could not find the command `{}`. Use `@notify help` to see a list of commands.".format(command_name))
    elif isinstance(error, commands.CheckFailure):
        await ctx.channel.send("You don't have sufficient permissions to run this command.")
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
        await ctx.channel.send("Provide your MAL username and then the number of entries in {} you want to check".format(client.feed_channel.mention))
    elif isinstance(error, commands.BadArgument) and command_name == "check":
        try:
            int(args[2])
        except ValueError:
            await ctx.channel.send("Error converting `{}` to an integer.".format(args[2]))
    elif isinstance(error, commands.CommandInvokeError):
        original_error = error.original
        if isinstance(original_error, errors.HTTPException):
            await ctx.channel.send("There was an issue connecting to the Discord API. Wait a few moments and try again.")
        elif isinstance(original_error, RuntimeError):
            # couldn't find a user with that username
            await ctx.channel.send(str(original_error))
        elif isinstance(original_error, requests.exceptions.InvalidURL):
            await ctx.channel.send(f"Error with that URL: {str(original_error)}")
        else:
            await ctx.channel.send("Uncaught error: {} - {}".format(type(error.original).__name__, error.original))
            logger.exception(error.original)
            logger.exception(
                "".join(traceback.format_tb(error.original.__traceback__)))
    else:
        await ctx.channel.send("Uncaught error: {} - {}".format(type(error).__name__, error))
        logger.exception(error, exc_info=True)


if __name__ == "__main__":
    # Token is stored in token.yaml, with the key 'token'
    with open(token_file, 'r') as t:
        token = yaml.load(t, Loader=yaml.FullLoader)["token"]

    client.run(token, bot=True, reconnect=True)
