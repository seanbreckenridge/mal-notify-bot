#!/usr/bin/env python3

import sys
import os
import re
import time
import random
import argparse
import pickle

import requests
import jikanpy
import discord
from bs4 import BeautifulSoup

# basic rules
# 1) Check the first 50 pages every 2 days
# 2) Check the entirety of MAL once a week
# 3) Check the first 6 pages of the Just Added every 30(ish) minutes
# 3a) If you don't find an entry after the first 6 pages, don't continue
# 3b) If you find an entry, check the next 5 pages
# 3b.1) Continue checking pages till you don't find a new entry for 5 pages

# the last time the 50 pages and the entirety of MAL should be saved in a file called 'state'.
# since the discord bot and scraper are going to run on different PIDs, this script will output
# any new MAL IDs to 'new', and the discord bot script will read from there periodically,
# logging them in the server in the process

# 

class request_type:
    six_pages = 1
    fifty_pages = 2
    all_pages = 3

base_url="https://myanimelist.net/anime.php?o=9&c%5B0%5D=a&c%5B1%5D=d&cv=2&w=1&show={}"

def just_added_page(page_number):
    """returns the URL for the newly added page of entries. Assumes the first page is page 0"""
    return base_url.format(page_number * 50)

def read_old_db(): 
    with open("old", 'r') as old_f:
        return set(old_f.read().splitlines())   

class crawl:
    """Keep track of time between scrape requests.
        args:
            wait: time between requests
            retry_max: number of times to retry
    """
    def __init__(self, wait, retry_max):
        self.wait = wait
        self.retry_max = retry_max
        self.last_scrape = time.time() - (self.wait * 0.5)
        # can let user scrape faster the first time.

    def since_scrape(self):
        return (time.time() - self.last_scrape) > self.wait

    def wait_till(self):
        while (not self.since_scrape()):
            time.sleep(1)

    def get(self, url):
        count = 0
        while (count < self.retry_max):
            time.sleep(self.wait * count) # sleep for successively longer times
            try:
                self.wait_till()
                response = requests.get(url)
                self.last_scrape = time.time() + random.randint(1, 3)
                if response.status_code == requests.codes.ok:
                    return response
                elif response.status_code == requests.codes.not_found:
                    raise RuntimeError("404")
                elif response.status_code == requests.codes.too_many_requests:
                    raise requests.exceptions.RequestException() # will wait for longer before requesting
                else:
                    raise RuntimeError("Non-standard issue connecting to {}: {}".format(url, response.status_code))
            except requests.exceptions.RequestException as e:
            	pass
            count += 1

    def get_html(self, url):
        return self.get(url).text

    def get_json(self, url):
        return self.get(url).json()

    def get_just_added_page(self, page_number):
        return BeautifulSoup(self.get_html(just_added_page(page_number)), 'html.parser')

def make_jikan_animelist_request(j, username, page, retry, jikan_exception):
    # if we've failed to get this page 5 times or more
    if retry >= 5:
        raise jikan_exception
    try:
        resp = j.user(username=username, request='animelist', argument='all', page=page)
        time.sleep(1)
        return resp
    except (jikanpy.exceptions.JikanException, jikanpy.exceptions.APIException) as jex:
        # if we fail, increment retry and call again
        print("... Failed with {}, retrying... ({} of 5)".format(type(jex).__name__, retry))
        return make_jikan_animelist_request(j, username, page, retry + 1, jex)

# j: jikan object
def download_anime_list(uname, j):
    try:
        # get the number of entries on this users list
        user_profile = j.user(username=uname, request='profile')
    except jikanpy.exceptions.APIException as jex:
        if '404' in str(jex):
            print("Could not find the user '{}'.".format(uname))
            sys.exit(1)
        else:
            raise jex
    time.sleep(1)
    user_total_entries = user_profile["anime_stats"]['total_entries']
    page_range = (user_total_entries//300) + (0 if user_total_entries%300 == 0 else 1)

    # download paginations
    all_entries = []
    for page in range(1 , page_range + 1):
        sys.stdout.write("\r[{}]Downloading animelist page {}/{}...".format(uname, page, page_range))
        req = make_jikan_animelist_request(j, uname, page, 1, None)
        all_entries.extend(req['anime'])
    print() # newline
    return all_entries

def get_ids_from_search_page(page_number, crawler):
    if page_number < 0:
        raise ValueError("page number cant be negative.")
    soup = crawler.get_just_added_page(page_number)
    table = soup.select(".js-categories-seasonal.js-block-list")[0]
    for link in table.select('a[id^="sinfo"]'):
        m = re.search("https:\/\/myanimelist\.net\/anime\/(\d+)", link["href"])
        yield m.group(1)

def make_embed(anime_json_data):
    embed=discord.Embed(title=anime_json_data['title'], url=anime_json_data['url'], color=discord.Colour.dark_blue())
    embed.set_thumbnail(url=anime_json_data['image_url'])
    embed.add_field(name="Status", value=anime_json_data['status'], inline=True)
    if 'from' in anime_json_data['aired'] and anime_json_data['aired']['from'] is not None:
        embed.add_field(name="Air Date", value=anime_json_data['aired']['from'].split("T")[0], inline=True)
    embed.add_field(name="Synopsis", value=anime_json_data['synopsis'], inline=False)
    genre_names = [g['name'] for g in anime_json_data['genres']]
    # the second index in return value specifies if this is SFW
    return (embed, "Hentai" not in genre_names)

def make_anime_jikan_request(jikan, mal_id, retry, jikan_exception):
    # if we've failed to get this page 5 times or more
    if retry >= 5:
        print("Failed to get anime information for {} from jikan 5 times.".format(mal_id))
        raise jikan_exception
    try:
        print("Requesting {}".format(mal_id))
        resp = jikan.anime(int(mal_id))
        time.sleep(3 * retry) # actual sleep to ensure API compliance
        return resp
    except (jikanpy.exceptions.JikanException, jikanpy.exceptions.APIException) as jex:
        # if we fail, increment retry and call again
        return make_anime_jikan_request(jikan, mal_id, retry + 1, jex)

def loop(crawler, j):
    # state has 2 lines in it, the first is last time we scraped the first 50 pages
    # the second is the last time we scraped the entirety of MAL
    # we should scrape the first 50 pages every 2 days and all the pages once a week

    # otherwise scrape the first 6 pages (and keep going if you find new entries) every 30 minutes

    # this script will be called by `python3 bot.py` as an os.system call
    # we should create a file named 'pid' that contains this process' pid
    # incase this file crashes for some reason, so we can restart it

    first_50_pages = 0
    all_pages = 0
    page_range = 6
    req_type = request_type.six_pages
    if os.path.exists("state"):
        with open("state", "r") as last_scraped:
            first_50_pages, all_pages = map(lambda x: int(float(x)), last_scraped.read().strip().splitlines())
    while True:
        # create pid file
        with open('pid', 'w') as pid_f:
            pid_f.write(str(os.getpid()))
        # every 14 days
        if int(time.time()) - all_pages > 3600 * 24 * 7 * 2: # seconds in 2 weeks
            page_range = 99999
            req_type = request_type.all_pages
        # every 2 days
        elif int(time.time()) - first_50_pages > 3600 * 24 * 2: # seconds in 2 days
            page_range = 50
            req_type = request_type.fifty_pages
        # read old database
        old_db = read_old_db()
        new_ids = []
        # for each page
        current_page = 0
        while current_page < page_range:
            page_ids = []
            try:
                print("Downloading page {}".format(current_page))
                page_ids = list(get_ids_from_search_page(current_page, crawler))
            except RuntimeError as runerr:
                # if we past the last search page
                break
            for page_id in page_ids:
                # if this is a new entry
                if page_id not in old_db:
                    page_range = current_page + 5  # found a new entry, extend how many pages we should check
                    print("New entry: {}".format(page_id))
                    new_ids.append(page_id)
            current_page += 1

        # if we looked at the first 50 or all pages, write time to 'state'
        if req_type == request_type.all_pages:
            # write current time to 'state', all pages counts as 50 pages as well
            with open("state", "w") as last_scraped:
                last_scraped.write("{}\n{}".format(time.time(), time.time()))
        elif req_type == request_type.fifty_pages:
            with open("state", "w") as last_scraped:
                last_scraped.write("{}\n{}".format(time.time(), all_pages))
        
        # write new entries, if any
        if new_ids:
            # create list of pickled embeds
            pickles = []
            for new_id in new_ids:
                try:
                    anime_json_resp = make_anime_jikan_request(j, new_id, 0, None)
                    pickles.append(make_embed(anime_json_resp))
                except jikanpy.exceptions.JikanException:
                    print("Could not request {} from Jikan".format(new_id))
                    continue
            if pickles:
                with open("new", "wb") as new_entries:
                    pickle.dump(pickles, new_entries)
        print("Sleeping...")
        time.sleep(int(60*random.uniform(27, 35))) # sleep for around 30 minutes

def main(init):
    j = jikanpy.Jikan()
    if init:
        print("Initializing database with {}'s anime list".format(init))
        entries = download_anime_list(init, j)
        with open("old", "w") as old_f:
            for entry in entries:
                old_f.write("{}\n".format(entry["mal_id"]))
    crawler = crawl(wait=14, retry_max=4)
    loop(crawler, j)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--initialize", default=False, help="Initialize the 'old' database by using a users animelist")
    main(parser.parse_args().initialize)
