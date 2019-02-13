import re

import bs4
import discord
import requests

# can't use Jikan here since API requests are cached for 6 hours, and
# the whole point of this is to be relevant as entries come out

def get_image_and_synopsis(mal_id: int, ignore_image: bool):
    image, synopsis = None, None
    soup = bs4.BeautifulSoup(requests.get("https://myanimelist.net/anime/{}".format(mal_id)).text, "html.parser")
    if not ignore_image:
        try:
            image = soup.select("tr > td.borderClass > div > div > a > img.ac")[0]["src"]
        except: # image is a placeholder image, ignore it
            pass
    try:
        synopsis = soup.select('span[itemprop="description"]')[0].text.replace("\r", "")
        synopsis = re.sub("\n\s*\n", "\n", synopsis.strip()).strip()
    except: # no synopsis
        pass
    return image, synopsis

def refresh_embed(embed, mal_id:int, remove_image: bool):
    image, synopsis = get_image_and_synopsis(mal_id, remove_image)
    if synopsis is not None and len(synopsis) > 400:
        synopsis = synopsis[:400] + "..."
    new_embed=discord.Embed(title=embed['title'], url=embed['url'], color=discord.Color.dark_blue())
    if not remove_image and image is not None:
        new_embed.set_thumbnail(url=image)

    for f in embed['fields']:
        if f['name'] == "Status":
            new_embed.add_field(name="Status", value=f['value'], inline=True)
        elif f['name'] == "Air Date":
            new_embed.add_field(name="Air Date", value=f['value'], inline=True)
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
    print(get_image_and_synopsis(mid, False))
