import re

import bs4
import discord
import requests

# can't use Jikan here since API requests are cached for 6 hours, and
# the whole point of this is to be relevant as entries come out

# image, synopsis, whether this is SFW, air date, status
def get_data(mal_id: int, ignore_image: bool, **kwargs):
    name = image = synopsis = sfw = airdate = status = soup = None
    crawler = kwargs.get('crawler', None)
    logger = kwargs.get('logger', None)
    if crawler is None:
        soup = bs4.BeautifulSoup(requests.get("https://myanimelist.net/anime/{}".format(mal_id)).text, "html.parser")
    else:
        soup = bs4.BeautifulSoup(crawler.get_html("https://myanimelist.net/anime/{}".format(mal_id)), "html.parser")
    if logger is not None:
        logger.debug("Generating embed for MAL id: {}".format(mal_id))
    # name
    name, dash, homepage = soup.title.string.rpartition("-")
    name = name.strip()

    # image
    if not ignore_image:
        try:
            image = soup.select("tr > td.borderClass > div > div > a > img.ac")[0]["src"]
            # placeholder MAL logo image
            if image.startswith("https://myanimelist.cdn-dena.com/img/sp/icon/"):
                image = None
        except:
            pass

    # synopsis
    try:
        synopsis = soup.select('span[itemprop="description"]')[0].text.replace("\r", "")
        synopsis = re.sub("\n\s*\n", "\n", synopsis.strip()).strip()
        if len(synopsis) > 400:
            synopsis = synopsis[:400].strip() + "..."
    except: # no synopsis
        pass

    # sidebar
    # select this by selecting the "score" div, moving up one level and then getting all elements in the sidebar
    sidebar_titles = list(soup.select("div.js-statistics-info")[0].parent.select("div > span"))
    for title in sidebar_titles:
        title_str = title.text.strip()
        if title_str == "Aired:":
            parent_div = title.parent
            # remove inner span title
            title.decompose()
            airdate = parent_div.text.strip()
            if airdate == "Not available":
                airdate = None
        elif title_str == "Status:":
            parent_div = title.parent
            title.decompose()
            status = parent_div.text.strip()
        elif title_str == "Genres:":
            parent_div = title.parent
            title.decompose()
            sfw = "Hentai" not in parent_div.text.strip()
    return name, image, synopsis, sfw, airdate, status


def embed_value_helper(embed_dict, name):
    """Only call this when you know that the value is in the embed, returns the value for the name"""
    for f in embed_dict['fields']:
        if f['name'] == name:
            return f['value']


def add_to_embed(discord_embed_object, embed_dict, name, value, inline):
    if embed_dict is not None:
        # this was already in the embed_dict
        if name in [f['name'] for f in embed_dict['fields']]:
            if value is not None:
                # prefer the recent value from MAL, if it exists
                discord_embed_object.add_field(name=name, value=value, inline=inline)
            else:
                # get it from the previous embed message
                discord_embed_object.add_field(name=name, value=embed_value_helper(embed_dict, name), inline=inline)
        # if this field wasnt in the fields previously, add it to the embed object
        else:
            if value is not None:
                discord_embed_object.add_field(name=name, value=value, inline=inline)
    # if there is no embed_dict, this is a new embed object
    else:
        discord_embed_object.add_field(name=name, value=value, inline=inline)
    return discord_embed_object


def create_embed(mal_id:int, crawler, logger):
    title, image, synopsis, sfw, airdate, status = get_data(mal_id, False, crawler=crawler, logger=logger)
    embed = discord.Embed(title=title, url="https://myanimelist.net/anime/{}".format(mal_id), color=discord.Colour.dark_blue())
    if image is not None:
        embed.set_thumbnail(url=image)
    embed = add_to_embed(embed, None, "Status", status, True)
    embed = add_to_embed(embed, None, "Air Date", airdate, True)
    embed = add_to_embed(embed, None, "Synopsis", synopsis, False)
    return embed, sfw


def refresh_embed(embed, mal_id:int, remove_image: bool):
    title, image, synopsis, _, airdate, status = get_data(mal_id, remove_image)
    if synopsis is not None and len(synopsis) > 400:
        synopsis = synopsis[:400] + "..."
    new_embed=discord.Embed(title=title, url="https://myanimelist.net/anime/{}".format(mal_id), color=discord.Color.dark_blue())
    if not remove_image and image is not None:
        new_embed.set_thumbnail(url=image)
    new_embed = add_to_embed(new_embed, embed, "Status", status, True)
    new_embed = add_to_embed(new_embed, embed, "Air Date", airdate, True)
    new_embed = add_to_embed(new_embed, embed, "Synopsis", synopsis, False)
    new_embed = add_to_embed(new_embed, embed, "Source", None, False)
    return new_embed

def add_source(embed, valid_links):
    new_embed=discord.Embed(title=embed['title'], url=embed['url'], color=discord.Color.dark_blue())
    print(embed)
    print("thumbnail in embed:", 'thumbnail' in embed)        
    if 'thumbnail' in embed:
        new_embed.set_thumbnail(url=embed['thumbnail']['url'])
    is_new_source = "Source" not in [f['name'] for f in embed['fields']]
    new_embed = add_to_embed(new_embed, embed, "Status", None, True)
    new_embed = add_to_embed(new_embed, embed, "Air Date", None, True)
    new_embed = add_to_embed(new_embed, embed, "Synopsis", None, True)
    new_embed = add_to_embed(new_embed, embed, "Source", " ".join(valid_links), inline=False)
    return new_embed, is_new_source

def remove_source(embed):
    new_embed=discord.Embed(title=embed['title'], url=embed['url'], color=discord.Color.dark_blue())
    if 'thumbnail' in embed:
        new_embed.set_thumbnail(url=embed['thumbnail']['url'])
    new_embed = add_to_embed(new_embed, embed, "Status", None, True)
    new_embed = add_to_embed(new_embed, embed, "Air Date", None, True)
    new_embed = add_to_embed(new_embed, embed, "Synopsis", None, False)
    return new_embed

# basic test to see what data is returned from MAL
if __name__ == "__main__":
    import sys
    mid = int(sys.argv[1])
    print(get_data(mid, False))
