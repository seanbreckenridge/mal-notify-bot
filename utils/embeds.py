import re

import discord
import requests
import jikanpy
import backoff

j = jikanpy.Jikan("http://localhost:8000/v3/")


@backoff.on_exception(
    backoff.fibo,  # fibonacci sequence backoff
    (jikanpy.exceptions.JikanException,
     jikanpy.exceptions.APIException),
    max_tries=10,
)
def get_data(mal_id: int, ignore_image: bool, **kwargs):
    name = image = synopsis = sfw = airdate = status = None
    logger = kwargs.get('logger', None)
    resp = j.anime(mal_id)
    name = resp['title']
    if not ignore_image:
        image = resp['image_url']
    if image.startswith("https://myanimelist.cdn-dena.com/img/sp/icon/"):
        image = None
    synopsis = resp.get("synopsis", "No Synopsis")  # return something so that there form POST has value incase synposis is empty
    if synopsis is not None:
        synopsis.replace("\r", "")
        synopsis = re.sub("\n\s*\n", "\n", synopsis.strip()).strip()
        if len(synopsis) > 400:
            synopsis = synopsis[:400].strip() + "..."
        if synopsis.strip() == "":
            synopsis = "No Synopsis"
    status = resp["status"]
    airdate = resp["aired"].get("string", None)
    sfw = 12 not in [g['mal_id'] for g in resp['genres']]
    return name, image, synopsis, sfw, airdate, status


def embed_value_helper(embed_dict, name):
    """Only call this when you know that the value is in the embed, returns the value for the name"""
    for f in embed_dict.fields:
        if f.name == name:
            return f.value


def add_to_embed(discord_embed_object, embed_dict, name, value, inline):
    if embed_dict is not None:
        # this was already in the embed_dict
        if name in [f.name for f in embed_dict.fields]:
            if value is not None:
                # prefer the recent value from MAL, if it exists
                discord_embed_object.add_field(
                    name=name, value=value, inline=inline)
            else:
                # get it from the previous embed message
                discord_embed_object.add_field(
                    name=name, value=embed_value_helper(embed_dict, name), inline=inline)
        # if this field wasnt in the fields previously, add it to the embed object
        else:
            if value is not None:
                discord_embed_object.add_field(
                    name=name, value=value, inline=inline)
    # if there is no embed_dict, this is a new embed object
    else:
        discord_embed_object.add_field(name=name, value=value, inline=inline)
    return discord_embed_object


def create_embed(mal_id: int, logger):
    title, image, synopsis, sfw, airdate, status = get_data(
        mal_id, False, logger=logger)
    embed = discord.Embed(title=title, url="https://myanimelist.net/anime/{}".format(
        mal_id), color=discord.Colour.dark_blue())
    if image is not None:
        embed.set_thumbnail(url=image)
    embed = add_to_embed(embed, None, "Status", status, inline=True)
    embed = add_to_embed(embed, None, "Air Date", airdate, inline=True)
    embed = add_to_embed(embed, None, "Synopsis", synopsis, inline=False)
    return embed, sfw


def refresh_embed(embed, mal_id: int, remove_image: bool, logger):
    title, image, synopsis, _, airdate, status = get_data(
        mal_id, remove_image, logger=logger)
    if synopsis is not None and len(synopsis) > 400:
        synopsis = synopsis[:400] + "..."
    new_embed = discord.Embed(
        title=title, url="https://myanimelist.net/anime/{}".format(mal_id), color=discord.Color.dark_blue())
    if not remove_image and image is not None:
        new_embed.set_thumbnail(url=image)
    new_embed = add_to_embed(new_embed, embed, "Status", status, inline=True)
    new_embed = add_to_embed(
        new_embed, embed, "Air Date", airdate, inline=True)
    new_embed = add_to_embed(
        new_embed, embed, "Synopsis", synopsis, inline=False)
    new_embed = add_to_embed(new_embed, embed, "Source", None, inline=False)
    return new_embed


def add_source(embed, valid_links):
    new_embed = discord.Embed(
        title=embed.title, url=embed.url, color=discord.Color.dark_blue())
    if hasattr(embed, "thumbnail"):
        new_embed.set_thumbnail(url=embed.thumbnail.url)
    is_new_source = "Source" not in [f.name for f in embed.fields]
    new_embed = add_to_embed(new_embed, embed, "Status", None, inline=True)
    new_embed = add_to_embed(new_embed, embed, "Air Date", None, inline=True)
    new_embed = add_to_embed(new_embed, embed, "Synopsis", None, inline=True)
    new_embed = add_to_embed(new_embed, embed, "Source",
                             " ".join(valid_links), inline=False)
    return new_embed, is_new_source


def remove_source(embed):
    new_embed = discord.Embed(
        title=embed.title, url=embed.url, color=discord.Color.dark_blue())

    if hasattr(embed, "thumbnail"):
        new_embed.set_thumbnail(url=embed.thumbnail.url)
    new_embed = add_to_embed(new_embed, embed, "Status", None, inline=True)
    new_embed = add_to_embed(new_embed, embed, "Air Date", None, inline=True)
    new_embed = add_to_embed(new_embed, embed, "Synopsis", None, inline=False)
    return new_embed


# basic test to see what data is returned from MAL
if __name__ == "__main__":
    import sys
    mid = int(sys.argv[1])
    print(get_data(mid, False))
