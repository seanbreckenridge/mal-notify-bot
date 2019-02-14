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

def create_embed(mal_id:int, crawler, logger):
    title, image, synopsis, sfw, airdate, status = get_data(mal_id, False, crawler=crawler, logger=logger)
    embed = discord.Embed(title=title, url="https://myanimelist.net/anime/{}".format(mal_id), color=discord.Colour.dark_blue())
    # placeholder image on MAL
    if image is not None:
        embed.set_thumbnail(url=image)
    embed.add_field(name="Status", value=status, inline=True)
    if airdate is not None:
        embed.add_field(name="Air Date", value=airdate, inline=True)
    if synopsis is not None:
        # truncate the synopsis past 400 characters
        if len(synopsis) > 400:
            embed.add_field(name="Synopsis", value=synopsis[:400] + "...", inline=False)
        else:
            embed.add_field(name="Synopsis", value=synopsis, inline=False)
    return embed, sfw

def refresh_embed(embed, mal_id:int, remove_image: bool):
    title, image, synopsis, _, airdate, status = get_data(mal_id, remove_image)
    if synopsis is not None and len(synopsis) > 400:
        synopsis = synopsis[:400] + "..."
    new_embed=discord.Embed(title=title, url=embed['url'], color=discord.Color.dark_blue())
    if not remove_image and image is not None:
        new_embed.set_thumbnail(url=image)
    for f in embed['fields']:
        if f['name'] == "Status":
            new_embed.add_field(name="Status", value=status, inline=True)
        elif f['name'] == "Air Date":
            new_embed.add_field(name="Air Date", value=airdate, inline=True)
    if synopsis is not None:
        new_embed.add_field(name="Synopsis", value=synopsis, inline=False)
    for f in embed['fields']:
        if f['name'] == 'Source':
            new_embed.add_field(name=f['name'], value=f['value'], inline=False)
    return new_embed

def add_source(embed, valid_links):
    new_embed=discord.Embed(title=embed['title'], url=embed['url'], color=discord.Color.dark_blue())
    if 'thumbnail' in embed:
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
        return new_embed, is_new_source

def remove_source(embed):
    new_embed=discord.Embed(title=embed['title'], url=embed['url'], color=discord.Color.dark_blue())
    if 'thumbnail' in embed:
        new_embed.set_thumbnail(url=embed['thumbnail']['url'])
    for f in embed['fields']:
        if f['name'] == "Status":
            new_embed.add_field(name="Status", value=f['value'], inline=True)
        elif f['name'] == "Air Date":
            new_embed.add_field(name="Air Date", value=f['value'], inline=True)
        elif f['name'] == "Synopsis":
            new_embed.add_field(name="Synopsis", value=f['value'], inline=False)
    return new_embed

# basic test
if __name__ == "__main__":
    import sys
    mid = int(sys.argv[1])
    print(get_data(mid, False))
