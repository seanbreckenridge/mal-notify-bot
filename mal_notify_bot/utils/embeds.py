import re
import logging
import asyncio
from typing import List

import discord  # type: ignore[import]

from typing import Optional, Dict, Any, Tuple

from . import log

from .user import session

assert session is not None


BASE_ANIME_URL = "https://api.myanimelist.net/v2/anime/{}?nsfw=true"

ANIME_FIELDS = "fields=id,title,main_picture,alternative_titles,start_date,end_date,synopsis,mean,rank,popularity,num_list_users,num_scoring_users,nsfw,created_at,updated_at,media_type,status,genres,num_episodes,start_season,broadcast,source,average_episode_duration,rating,pictures,background,related_anime,related_manga,recommendations,studios,statistics"


def fetch_anime_details(anime_id: int) -> Dict[str, Any]:
    """Fetches anime details from MAL"""
    api_url = BASE_ANIME_URL.format(anime_id) + "&" + ANIME_FIELDS
    assert session is not None
    return session.safe_json_request(api_url)


def _get_mal_image(data: dict) -> Optional[str]:
    """Gets the image from MAL"""
    if pics := data.get("main_picture"):
        if medium := pics.get("medium"):
            return medium
        if large := pics.get("large"):
            return large
    return None


def unslugify(slug: str) -> str:
    return " ".join([w.capitalize() for w in slug.split("_")])


@log
async def get_data(
    mal_id: int, ignore_image: bool = False, **kwargs: logging.Logger
) -> Tuple[str, Optional[str], Optional[str], bool, Optional[str], str]:
    logger: Optional[logging.Logger] = kwargs.get("logger", None)

    if logger:
        logger.debug("Sleeping before MAL request...")
    await asyncio.sleep(1)

    # return values
    name: str
    image: Optional[str] = None
    synopsis: Optional[str] = None
    airdate: Optional[str] = None
    status: Optional[str] = None
    sfw: bool

    resp: Dict[str, Any] = fetch_anime_details(mal_id)
    name = str(resp["title"])
    if not ignore_image:
        image = _get_mal_image(resp)
    # no image, default 'MAL' icon
    if image is not None and image.startswith(
        "https://myanimelist.cdn-dena.com/img/sp/icon/"
    ):
        image = None
    # return something so that there form POST has value incase synopsis is empty
    synopsis = resp.get("synopsis", "No Synopsis")
    if synopsis is not None:
        synopsis.replace("\r", "")
        synopsis = re.sub(r"\n\s*\n", "\n", synopsis.strip()).strip()
        if len(synopsis) > 400:
            synopsis = synopsis[:400].strip() + "..."
        if synopsis.strip() == "":
            synopsis = "No Synopsis"
    status = str(unslugify(resp.get("status", "Unknown")))
    airdate = resp.get("start_date", "No Air Date")
    sfw = "Hentai" not in [g.get("name") for g in resp.get("genres", [])]
    return name, image, synopsis, sfw, airdate, status


def embed_value_helper(embed_dict: Any, name: str) -> Any:
    """Only call this when you know that the value is in the embed, returns the value for the name"""
    for f in embed_dict.fields:
        if f.name == name:
            return f.value
    raise RuntimeError("Could not find {} on embed object".format(name))


def add_to_embed(
    discord_embed_object: discord.Embed,
    embed_dict: Any,
    name: str,
    value: Any,
    inline: bool,
) -> discord.Embed:
    if embed_dict is not None:
        # this was already in the embed_dict
        if name in [f.name for f in embed_dict.fields]:
            if value is not None:
                # prefer the recent value from MAL, if it exists
                discord_embed_object.add_field(name=name, value=value, inline=inline)
            else:
                # get it from the previous embed message
                discord_embed_object.add_field(
                    name=name, value=embed_value_helper(embed_dict, name), inline=inline
                )
        # if this field wasnt in the fields previously, add it to the embed object
        else:
            if value is not None:
                discord_embed_object.add_field(name=name, value=value, inline=inline)
    # if there is no embed_dict, this is a new embed object
    else:
        discord_embed_object.add_field(name=name, value=value, inline=inline)
    return discord_embed_object


@log
async def create_embed(
    mal_id: int, logger: logging.Logger
) -> Tuple[discord.Embed, bool]:
    title, image, synopsis, sfw, airdate, status = await get_data(
        mal_id, False, logger=logger
    )
    embed = discord.Embed(
        title=title,
        url="https://myanimelist.net/anime/{}".format(mal_id),
        color=discord.Colour.dark_blue(),
    )
    if image is not None:
        embed.set_thumbnail(url=image)
    embed = add_to_embed(embed, None, "Status", status, inline=True)
    embed = add_to_embed(embed, None, "Air Date", airdate, inline=True)
    embed = add_to_embed(embed, None, "MAL ID", mal_id, inline=True)
    embed = add_to_embed(embed, None, "Synopsis", synopsis, inline=False)
    return embed, sfw


@log
async def refresh_embed(
    embed: discord.Embed, mal_id: int, remove_image: bool, logger: logging.Logger
) -> discord.Embed:
    title, image, synopsis, _, airdate, status = await get_data(
        mal_id, remove_image, logger=logger
    )
    if synopsis is not None and len(synopsis) > 400:
        synopsis = synopsis[:400] + "..."
    new_embed = discord.Embed(
        title=title,
        url="https://myanimelist.net/anime/{}".format(mal_id),
        color=discord.Color.dark_blue(),
    )
    if not remove_image and image is not None:
        new_embed.set_thumbnail(url=image)
    new_embed = add_to_embed(new_embed, embed, "Status", status, inline=True)
    new_embed = add_to_embed(new_embed, embed, "Air Date", airdate, inline=True)
    new_embed = add_to_embed(new_embed, embed, "MAL ID", mal_id, inline=True)
    new_embed = add_to_embed(new_embed, embed, "Synopsis", synopsis, inline=False)
    new_embed = add_to_embed(new_embed, embed, "Source", None, inline=False)
    return new_embed


@log
async def add_source(
    embed: discord.Embed, valid_links: List[str]
) -> Tuple[discord.Embed, bool]:
    new_embed = discord.Embed(
        title=embed.title, url=embed.url, color=discord.Color.dark_blue()
    )
    if hasattr(embed, "thumbnail"):
        new_embed.set_thumbnail(url=embed.thumbnail.url)
    is_new_source = "Source" not in [f.name for f in embed.fields]
    new_embed = add_to_embed(new_embed, embed, "Status", None, inline=True)
    new_embed = add_to_embed(new_embed, embed, "Air Date", None, inline=True)
    new_embed = add_to_embed(new_embed, embed, "MAL ID", None, inline=True)
    new_embed = add_to_embed(new_embed, embed, "Synopsis", None, inline=True)
    new_embed = add_to_embed(
        new_embed, embed, "Source", " ".join(valid_links), inline=False
    )
    return new_embed, is_new_source


@log
async def remove_source(embed: discord.Embed) -> discord.Embed:
    new_embed = discord.Embed(
        title=embed.title, url=embed.url, color=discord.Color.dark_blue()
    )

    if hasattr(embed, "thumbnail"):
        new_embed.set_thumbnail(url=embed.thumbnail.url)
    new_embed = add_to_embed(new_embed, embed, "Status", None, inline=True)
    new_embed = add_to_embed(new_embed, embed, "Air Date", None, inline=True)
    new_embed = add_to_embed(new_embed, embed, "MAL ID", None, inline=True)
    new_embed = add_to_embed(new_embed, embed, "Synopsis", None, inline=False)
    return new_embed


def get_source(embed: discord.Embed) -> Optional[str]:
    for embed_proxy in embed.fields:
        if embed_proxy.name == "Source":
            return str(embed_proxy.value)
    return None
