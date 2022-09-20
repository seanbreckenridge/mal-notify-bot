import os
import sys
import re
import json
import traceback
import pathlib

from typing import Dict, Optional, List, Any, Tuple
from asyncio import sleep
from dataclasses import dataclass

import yaml
import requests
import aiofiles
from git.cmd import Git  # type: ignore[import]
from logzero import logger  # type: ignore[import]

from discord import errors, File, Message, Embed, TextChannel, Member
from discord.ext import commands
from discord.utils import get

from .utils import (
    truncate,
    extract_mal_id_from_url,
    log,
    remove_discord_link_supression,
)
from .utils.embeds import (
    create_embed,
    refresh_embed,
    add_source,
    remove_source,
    get_source,
)
from .utils.user import download_users_list
from .utils.forum import get_forum_links
from .utils.external import get_official_link

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
mal_id_cache_dir = os.path.join(root_dir, "mal-id-cache")
mal_id_cache_json_file = os.path.join(mal_id_cache_dir, "cache", "anime_cache.json")
token_file = os.path.join(root_dir, "token.yaml")

old_db_file = os.path.join(root_dir, "old")
assert os.path.exists(old_db_file)
# arbitrary check to make sure the olddb isnt empty
assert len(pathlib.Path(old_db_file).read_text()) > 10000

# file to export sources as a backup
export_file = os.path.join(root_dir, "export.json")

# bot object
client = commands.Bot(command_prefix=commands.when_mentioned, case_insensitive=False)
client.remove_command("help")  # remove default help


ADMIN_ROLE = "admin"
TRUSTED_ROLE = "trusted"


@dataclass
class GlobalsType:
    period: int = 60 * 5
    export_period = 60 * 60 * 6  # once every 6 hours
    feed_channel: Any = None
    nsfw_feed_channel: Any = None
    old_db: Any = None


Globals = GlobalsType()


class FileState:
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
        async with aiofiles.open(self.filepath, mode="r") as old_f:
            contents = await old_f.read()
            return set(contents.splitlines())

    @log
    async def dump(self, contents):
        contents = sorted(list(contents), key=int)
        async with aiofiles.open(self.filepath, mode="w") as old_f:
            await old_f.write("\n".join(contents))
            await old_f.flush()


@log
async def update_git_repo():
    """Updates from the remote mal-id-cache"""
    g = Git(mal_id_cache_dir)
    g.pull()
    commit_id = g.log().splitlines()[0].split()[-1]
    logger.debug(f"{g.working_dir} is at commit hash {commit_id}")


@log
async def read_json_cache():
    """Reads the cache from mal-id-cache/cache.json and combines sfw ids with nsfw"""
    async with aiofiles.open(mal_id_cache_json_file, mode="r") as cache_f:
        plain_text_contents = await cache_f.read()
    contents = json.loads(plain_text_contents)
    return list(map(str, contents["sfw"] + contents["nsfw"]))


def roles_from_context(ctx: commands.Context) -> List[str]:
    assert isinstance(ctx.author, Member)
    return [role.name.lower() for role in ctx.author.roles]


@client.event
@log
async def on_ready():  # include so that on_ready event shows up in logs
    pass


# override on_message so we can remove double spaces after the bot name,
# which would ordinarily not trigger commands
@client.event
async def on_message(message):
    # remove weird spaces
    message.content = re.sub(r"\s{2,}", " ", message.content)
    await client.process_commands(message)


@log
async def search_feed_for_mal_id(
    mal_id: int, channel: TextChannel, limit: int = 99999
) -> Optional[Message]:
    """
    checks a feed channel (which is filled with embeds) for a message
    returns the discord.Message object if it finds it within limit, else return None
    """
    async for message in channel.history(limit=limit, oldest_first=False):
        try:
            embed = message.embeds[0]
            if embed.url is not None:
                embed_id = extract_mal_id_from_url(embed.url)
                if embed_id is not None and int(embed_id) == int(mal_id):
                    logger.debug("Found message: {}".format(message))
                    return message
        except Exception as e:
            logger.warning("Error while searching history: {}".format(str(e)))
            continue
    return None  # if we've exited the loop


async def _export_channel(channel: TextChannel) -> Dict[str, str]:
    results = {}
    async for message in channel.history(limit=99999, oldest_first=False):
        try:
            embed = message.embeds[0]
        except:
            continue
        else:
            if embed.url is None:
                continue
            embed_id: Optional[str] = extract_mal_id_from_url(embed.url)
            if embed_id is not None:
                source: Optional[str] = get_source(embed)
                if source is None:
                    continue
                results[embed_id] = source
    return results


@log
async def run_export() -> None:
    """
    Iterates through all the messages in the feeds
    saving any sources to a JSON file
    """

    feed_results: Dict[str, str] = await _export_channel(Globals.feed_channel)
    nsfw_feed_results: Dict[str, str] = await _export_channel(Globals.nsfw_feed_channel)
    feed_results.update(nsfw_feed_results)
    with open(export_file, "w") as f:
        f.write(json.dumps(feed_results, indent=4))


@client.command()
@log
async def export(ctx):
    if TRUSTED_ROLE not in roles_from_context(ctx):
        await ctx.channel.send("Insufficient permissions")
        return
    await run_export()
    await ctx.channel.send(file=File(export_file))


async def export_loop():
    await client.wait_until_ready()
    assert Globals.feed_channel is not None
    assert Globals.nsfw_feed_channel is not None
    while not client.is_closed():
        # save to JSON file
        await run_export()
        await sleep(Globals.export_period)


# run in event loop
@log
async def print_loop() -> None:
    """main loop - checks if entries exist periodically and prints them"""
    await client.wait_until_ready()
    # setup global variables
    guilds = list(iter(client.guilds))
    if len(guilds) != 1:
        logger.critical("This bot should only be used on one server")
        sys.exit(1)
    channels = guilds[0].channels
    Globals.feed_channel = get(channels, name="feed")
    Globals.nsfw_feed_channel = get(channels, name="nsfw-feed")
    if Globals.feed_channel is None:
        logger.critical("Couldn't find the 'feed' channel")
    if Globals.nsfw_feed_channel is None:
        logger.critical("Couldn't find the 'nsfw-feed' channel")
    Globals.old_db = OldDatabase(filepath=old_db_file)
    client.loop.create_task(export_loop())
    while not client.is_closed():
        # if there are new entries, print them
        await print_new_embeds()
        logger.debug(f"Sleeping for {Globals.period}")
        await sleep(Globals.period)


@client.command()
@log
async def add_new(ctx):
    if TRUSTED_ROLE not in roles_from_context(ctx):
        await ctx.channel.send("Insufficient permissions")
        return
    await print_new_embeds()
    await ctx.channel.send("Done!")
    return


@client.command()
@log
async def restart(ctx):
    if ADMIN_ROLE not in roles_from_context(ctx):
        await ctx.channel.send("Insufficient permissions")
        return
    await ctx.channel.send("Restarting...")
    sys.exit(0)


@log
async def create_new_embeds(ctx=None) -> List[Tuple[Embed, bool]]:
    """
    git pulls, reads the json cache, and returns new embeds if they exist
    this *is* blocking, but temporarily blocking seems better than managing multple processes
    """
    await update_git_repo()
    ids = await read_json_cache()
    new_ids = []
    if not Globals.old_db.file_exists():
        logger.info(f"{Globals.old_db.filepath} didn't exist, creating...")
        with open(Globals.old_db.filepath):
            await Globals.old_db.dump(ids)
    else:
        old_ids = await Globals.old_db.read()
        new_ids = sorted(list(set(ids) - set(old_ids)))
        logger.debug(f"new ids: {truncate(new_ids, 200)}")
        logger.debug(f"({len(new_ids)} new ids)")

    # couldnt have possibly be 10000 entries approved since we last checked
    # this means there was an error writing to old_db
    if len(new_ids) > 10000:
        error_message = f"There were {len(new_ids)} new entries, there must have been an error writing to the old_db file at '{Globals.old_db.filepath}'"
        logger.warning(error_message)
        if ctx:
            await ctx.channel.send(error_message)
        return []

    new_embeds = []
    for new_id in new_ids:
        await sleep(0)  # allow other items in the asyncio loop to run
        new_embed = await create_embed(int(new_id), logger)
        new_embeds.append(new_embed)
    return new_embeds


@log
async def print_new_embeds():
    old_ids = await Globals.old_db.read()
    # prevent broken old files from printing a bunch of messages
    assert len(old_ids) > 10000
    for embed, sfw in await create_new_embeds():
        print_to_channel = Globals.feed_channel if sfw else Globals.nsfw_feed_channel
        assert embed.url is not None, f"{embed.to_dict()}"
        new_mal_id = extract_mal_id_from_url(embed.url)
        assert new_mal_id is not None
        # check if that message already exists in the channel
        previous_message = await search_feed_for_mal_id(
            mal_id=int(new_mal_id), channel=print_to_channel, limit=1000
        )
        if previous_message is not None:
            logger.debug(
                f"While attempting to print new id {new_mal_id}, found previously printed message: {previous_message}"
            )
        else:
            logger.debug(
                f"Couldnt find any message with id {new_mal_id}, printing new message"
            )
        if (
            new_mal_id not in old_ids and previous_message is None
        ):  # make sure we're not printing entries twice
            logger.debug(
                "Printing {} to {}".format(new_mal_id, "#feed" if sfw else "#nsfw-feed")
            )
            await print_to_channel.send(embed=embed)
        await sleep(2)
        # check that we actually printed the embed
        printed_message = await search_feed_for_mal_id(
            mal_id=int(new_mal_id), channel=print_to_channel, limit=1000
        )
        if printed_message:
            logger.debug(
                f"Found printed message in channel, adding {new_mal_id} to old ids"
            )
            old_ids.add(new_mal_id)
            logger.debug("Attempting to publish message...")
            try:
                await printed_message.publish()
            except Exception as publish_err:
                logger.warning(f"Couldn't publish message {publish_err}")
        else:
            logger.warning(
                f"Couldnt find printed message for id {new_mal_id} in channel"
            )
            sys.exit(1)
    await Globals.old_db.dump(old_ids)


@client.command()
@log
async def test_log(ctx):
    if ADMIN_ROLE not in roles_from_context(ctx):
        await ctx.channel.send("Insufficient permissions")
        return
    message = "test message. beep boop"
    await Globals.feed_channel.send(message)
    await Globals.nsfw_feed_channel.send(message)


@client.command()
@log
async def index(ctx: commands.Context, pages: int) -> None:
    if ADMIN_ROLE not in roles_from_context(ctx):
        await ctx.channel.send("Insufficient permissions")
        return
    # communicates with the https://github.com/Hiyori-API/checker_mal
    # instance to tell it to index more pages
    resp = requests.get(f"http://localhost:4001/api/pages?type=anime&pages={pages}")
    resp.raise_for_status()
    await ctx.channel.send(
        f"Successfully submitted request to index {pages} anime pages"
    )


@client.command()
@log
async def source(ctx: commands.Context, mal_id: int, *, links: str) -> None:
    if TRUSTED_ROLE not in roles_from_context(ctx):
        await ctx.channel.send("Insufficient permissions")
        return
    adding_source = True
    parse_from_forum = False
    parse_external = False
    possible_command: str = links.strip().lower()
    if possible_command == "remove":
        adding_source = False
    elif possible_command.startswith("forum"):
        parse_from_forum = True
    elif possible_command.startswith("external"):
        parse_external = True
    logger.debug("{} source".format("Adding" if adding_source else "Removing"))

    valid_links = []
    if adding_source:
        if parse_from_forum:
            match_string = possible_command.split(" ", 1)[-1].strip()
            if len(match_string) == 0:
                await ctx.channel.send(
                    "Provide a link to match. e.g. 'forum youtube' or 'forum vimeo'"
                )
                return
            try:
                matched_link: str = await get_forum_links(mal_id, match_string, ctx=ctx)
                await ctx.channel.send("Matched <{}>".format(matched_link))
                valid_links.append(matched_link)
            except RuntimeError as re:
                await ctx.channel.send(str(re))
                return
        elif parse_external:
            external_link: Optional[str] = await get_official_link(mal_id)
            if external_link is None:
                await ctx.channel.send(
                    "Could not find an official link on MAL for that ID"
                )
                return
            await ctx.channel.send(f"Adding {external_link}...")
            valid_links.append(external_link)
        else:
            # if there are multiple links, check each
            for link in links.split():
                # remove supression from link, if it exists
                link = remove_discord_link_supression(link)
                valid_links.append(link)

    # get logs from feed
    message = await search_feed_for_mal_id(int(mal_id), Globals.feed_channel)
    if not message:
        await ctx.channel.send(
            "Could not find a message that contains the MAL id {} in {}".format(
                mal_id, Globals.feed_channel.mention
            )
        )
        return
    else:
        embed = message.embeds[0]
        if adding_source:
            logger.debug(f"Editing {message} to include {valid_links}")
            new_embed, is_new_source = await add_source(embed, valid_links)
            await message.edit(embed=new_embed)
            await ctx.channel.send(
                "{} source for '{}' successfully.".format(
                    "Added" if is_new_source else "Replaced", embed.title
                )
            )
            return
        else:
            new_embed = await remove_source(embed)
            await message.edit(embed=new_embed)
            await ctx.channel.send(
                "Removed source for '{}' successfully.".format(embed.title)
            )
            return


@client.command()
@log
async def refresh(ctx: commands.Context, mal_id: int) -> None:
    remove_image = "remove image" in ctx.message.content.lower()
    message = await search_feed_for_mal_id(
        int(mal_id), Globals.feed_channel, limit=999999
    )
    if not message:  # search nsfw channel
        message = await search_feed_for_mal_id(
            int(mal_id), Globals.nsfw_feed_channel, limit=999999
        )
    if message:
        embed = message.embeds[0]
        new_embed = await refresh_embed(embed, mal_id, remove_image, logger)
        await message.edit(embed=new_embed)
        await ctx.channel.send(
            "{} for '{}' successfully.".format(
                "Removed image" if remove_image else "Updated fields", embed.title
            )
        )
        return
    else:
        await ctx.channel.send(
            "Could not find a message that contains the MAL id {}".format(mal_id)
        )
        return


CHECK_DISABLED = False


@client.command()
@log
async def check(ctx: commands.Context, mal_username: str, num: int) -> None:
    if CHECK_DISABLED:
        await ctx.channel.send("check is currently disabled")
        return
    leftover_args = " ".join(ctx.message.content.strip().split()[4:])
    print_all = "all" in leftover_args.lower()
    print_not_completed = "not completed" in leftover_args.lower()
    message = await ctx.channel.send(
        "Downloading {}'s list (downloaded 0 anime entries...)".format(mal_username)
    )
    parsed: Dict[int, str] = {}
    for resp in download_users_list(mal_username):
        if "my_list_status" not in resp:
            continue
        parsed[int(resp["id"])] = str(resp["my_list_status"]["status"])
        if len(parsed) > 0 and len(parsed) % 100 == 0:
            await message.edit(
                content=f"Downloading {mal_username}'s list (downloaded {len(parsed)} anime entries...)"
            )
    await message.edit(
        content=f"Downloaded {mal_username}'s list (downloaded {len(parsed)} anime entries...)"
    )
    found_entry = False  # mark True if we find an entry the user hasnt watched
    async for message in Globals.feed_channel.history(limit=num, oldest_first=False):
        try:
            embed = message.embeds[0]
        except Exception:
            continue
        source_exists = "Source" in [f.name for f in embed.fields]
        if source_exists or print_all:
            mal_id_str = extract_mal_id_from_url(embed.url)
            assert mal_id_str, f"Could not extract url from {embed.url}"
            mal_id = int(mal_id_str)
            on_your_list = mal_id in parsed
            on_your_ptw = mal_id in parsed and parsed[mal_id] == "plan_to_watch"
            on_your_completed = mal_id in parsed and parsed[mal_id] == "completed"
            if (not on_your_list) or (
                on_your_ptw or (print_not_completed and not on_your_completed)
            ):
                found_entry = True
                if source_exists:
                    fixed_urls = " ".join(
                        [
                            "<{}>".format(url)
                            for url in [
                                f.value for f in embed.fields if f.name == "Source"
                            ][0].split()
                        ]
                    )
                    if on_your_ptw:
                        await ctx.channel.send(
                            "{} is on your PTW, but it has a source: {}".format(
                                embed.url, fixed_urls
                            )
                        )
                    elif print_not_completed:
                        await ctx.channel.send(
                            "{} is not on your Completed, but it has a source: {}".format(
                                embed.url, fixed_urls
                            )
                        )
                    else:
                        await ctx.channel.send(
                            "{} isn't on your list, but it has a source: {}".format(
                                embed.url, fixed_urls
                            )
                        )
                else:
                    if print_all and not on_your_list:
                        await ctx.channel.send(
                            "{} isn't on your list.".format(embed.url)
                        )

    if not found_entry:
        await ctx.channel.send(
            "I couldn't find any MAL entries in the last {} entries that aren't on your list.".format(
                num
            )
        )

    await ctx.channel.send("Done!")


@client.command()
@log
async def help(ctx):
    mentionbot = f"@{ctx.guild.me.display_name}"
    embed = Embed(title="mal-notify help", color=0x4EB1FF)
    embed.add_field(name="basic commands", value="\u200b", inline=False)
    embed.add_field(name=f"{mentionbot} help", value="Show this message", inline=False)
    embed.add_field(
        name=f"{mentionbot} check <mal_username> <n> [all]",
        value=f"Check the last 'n' in #feed entries for any items not on your MAL. Can add 'all' after the number of entries to check to list all items. By default only lists items which have sources. e.g. `{mentionbot} check Xinil 10 all`. `{mentionbot} check <mal_username> <n> not completed` will print any items that are not completed on your list which have a source in the last 'n' entries in #feed.",
        inline=False,
    )
    embed.add_field(name="'trusted' commands", value="\u200b", inline=False)
    embed.add_field(
        name=f"{mentionbot} add_new",
        value="Checks if any new items have been added in the last 10 minutes. Runs automatically at 10 minute intervals.",
        inline=False,
    )
    embed.add_field(
        name=f"{mentionbot} source <mal_id> <links...|external|remove|forum match_link_regex>",
        value=f"Adds a source to an embed in #feed. Requires either the link, the `remove` keyword. e.g. `{mentionbot} source 1 https://....`, `{mentionbot} source 1 remove`, `{mentionbot}` source 1 external to grab the link from the external links, or `{mentionbot} source 1 forum youtube|vimeo` to search the forum for a source link matching 'youtube' or 'vimeo'",
        inline=False,
    )
    embed.add_field(
        name=f"{mentionbot} export",
        value="Create a backup of all of the sources",
        inline=False,
    )
    embed.add_field(
        name=f"{mentionbot} refresh",
        value=f"Refreshes an embed - checks if the metadata (i.e. description, air date, image) has changed and updates accordingly. e.g. `{mentionbot} refresh 40020`",
        inline=False,
    )
    embed.add_field(name="'admin' commands", value="\u200b", inline=False)
    embed.add_field(name=f"{mentionbot} restart", value="Restart the bot", inline=False)
    embed.add_field(
        name=f"{mentionbot} index <pages>",
        value="Communicate with the process that indexes MAL, asking it to search <pages> of recently approved MAL entries for newly approved items",
        inline=False,
    )
    await ctx.channel.send(embed=embed)


@client.event
async def on_command_error(ctx, error):

    command_name = None
    if ctx.command:
        command_name = ctx.command.name
    clean_message_content = (
        ctx.message.content.split(">", maxsplit=1)[1].strip().replace("`", "")
    )
    args = clean_message_content.split()

    # prevent self-loops; on_command_error calling on_command_error
    if hasattr(ctx.command, "on_error"):
        logger.warning("on_command_error self loop occured")
        return

    if isinstance(error, commands.CommandNotFound):
        if command_name is None:
            await ctx.channel.send(
                "Didn't provide a known command. Use `@notify help` to see a list of commands"
            )
        else:
            await ctx.channel.send(
                "Could not find the command `{}`. Use `@notify help` to see a list of commands.".format(
                    command_name
                )
            )
    elif isinstance(error, commands.CheckFailure):
        await ctx.channel.send(
            "You don't have sufficient permissions to run this command."
        )
    elif (
        isinstance(error, commands.MissingRequiredArgument) and command_name == "source"
    ):
        await ctx.channel.send(
            "You're missing one or more arguments for the `source` command.\nExample: `@notify source 31943 https://youtube/...`"
        )
    elif (
        isinstance(error, commands.MissingRequiredArgument)
        and command_name == "refresh"
    ):
        await ctx.channel.send("Provide the MAL id you wish to refresh the embed for.")
    elif isinstance(error, commands.BadArgument) and command_name in [
        "source",
        "refresh",
        "index",
    ]:
        try:
            int(args[1])
        except ValueError:
            await ctx.channel.send(
                "Error converting `{}` to an integer.".format(args[1])
            )
    elif (
        isinstance(error, commands.MissingRequiredArgument) and command_name == "check"
    ):
        await ctx.channel.send(
            "Provide your MAL username and then the number of entries in {} you want to check".format(
                Globals.feed_channel.mention
            )
        )
    elif isinstance(error, commands.BadArgument) and command_name == "check":
        try:
            int(args[2])
        except ValueError:
            await ctx.channel.send(
                "Error converting `{}` to an integer.".format(args[2])
            )
    elif isinstance(error, commands.CommandInvokeError):
        original_error = error.original
        if isinstance(original_error, errors.HTTPException):
            await ctx.channel.send(
                "There was an issue connecting to the Discord API. Wait a few moments and try again."
            )
        elif isinstance(original_error, RuntimeError):
            # couldn't find a user with that username
            await ctx.channel.send(str(original_error))
        elif isinstance(original_error, requests.exceptions.InvalidURL):
            await ctx.channel.send(f"Error with that URL: {str(original_error)}")
        else:
            await ctx.channel.send(
                "Uncaught error: {} - {}".format(
                    type(error.original).__name__, error.original
                )
            )
            logger.exception(error.original)
            logger.exception("".join(traceback.format_tb(error.original.__traceback__)))
    else:
        await ctx.channel.send(
            "Uncaught error: {} - {}".format(type(error).__name__, error)
        )
        logger.exception(error, exc_info=True)


@client.event
async def setup_hook() -> None:
    client.loop.create_task(print_loop())  # waits until bot is ready


def main():
    # Token is stored in token.yaml, with the key 'token'
    with open(token_file, "r") as t:
        token = yaml.load(t, Loader=yaml.FullLoader)["token"]
    client.run(token, reconnect=True)
