#!/usr/bin/env python3

import sys
import os
import re
import time
import random
import argparse
import logging
import pickle

import requests
import jikanpy
import discord
from bs4 import BeautifulSoup

# basic rules
# 1) Check the first 50 pages every 2 days
# 2) Check the entirety of MAL once a week
# 3) Check the first 5 pages of the Just Added every 30(ish) minutes
# 3a) If you don't find an entry after the first 5 pages, don't continue
# 3b) If you find an entry, check the next 5 pages
# 3b.1) Continue checking pages till you don't find a new entry for 5 pages

# the last time the 50 pages and the entirety of MAL should be saved in a file called 'state'.
# since the discord bot and scraper are going to run on different PIDs, this script will output
# any new MAL IDs to 'new', and the discord bot script will read from there periodically,
# posting them in the feeds channel in the server in the process

# logs are good, use them
# Note logging levels go:
# DEBUG
# INFO
# WARNING
# ERROR (only in catch blocks, and with exc_info)
# CRITICAL

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler("{}.log".format(os.getpid()))
# format
formatter = logging.Formatter("%(asctime)s %(levelno)s %(process)d %(message)s")
fh.setFormatter(formatter)
# log to stderr
# logger.addHandler(logging.StreamHandler())
# and to the log file
logger.addHandler(fh)


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
            count += 1
            time.sleep(self.wait * count)  # sleep for successively longer times
            try:
                self.wait_till()
                response = requests.get(url)
                self.last_scrape = time.time() + random.randint(1, 3)
                if response.status_code == requests.codes.ok:
                    return response
                elif response.status_code == requests.codes.not_found:
                    logger.warning("(crawler[try={}]) request to {} returned 404".format(count, url))
                    raise RuntimeError("404")
                elif response.status_code == requests.codes.too_many_requests:
                    logger.warning("(crawler[try={}]) request to {} returned 429 (too many requests)".format(count, url))
                    raise requests.exceptions.RequestException()  # will wait for longer before requesting
            except requests.exceptions.RequestException as e:
                if count == self.retry_max:
                    logger.error("(crawler) Hit the maximum number of retries for {}".format(url), exc_info=True)
                    raise e

    def get_html(self, url):
        return self.get(url).text

    def get_json(self, url):
        return self.get(url).json()

    def get_just_added_page(self, page_number):
        return BeautifulSoup(self.get_html(just_added_page(page_number)), 'html.parser')


def just_added_page(page_number):
    """returns the URL for the newly added page of entries. Assumes the first page is page 0"""
    return "https://myanimelist.net/anime.php?o=9&c%5B0%5D=a&c%5B1%5D=d&cv=2&w=1&show={}".format(page_number * 50)


# The next two functions can print to stdout instead of logger as its assumed you're initializing 'old'
# by hand, which only needs to be done once


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
        print("... failed with {}, retrying... ({} of 5)".format(type(jex).__name__, retry))
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
    page_range = (user_total_entries//300) + (0 if user_total_entries % 300 == 0 else 1)

    # download paginations
    all_entries = []
    for page in range(1, page_range + 1):
        sys.stdout.write("\r[{}]Downloading animelist page {}/{}...".format(uname, page, page_range))
        req = make_jikan_animelist_request(j, uname, page, 1, None)
        all_entries.extend(req['anime'])
    print()  # newline
    return all_entries


def get_ids_from_search_page(page_number, crawler):
    if page_number < 0:
        logger.warning("Recieved page number {}, can't be negative".format(page_number))
        return
    soup = crawler.get_just_added_page(page_number)
    table = soup.select(".js-categories-seasonal.js-block-list")[0]
    for link in table.select('a[id^="sinfo"]'):
        m = re.search("https:\/\/myanimelist\.net\/anime\/(\d+)", link["href"])
        yield m.group(1)


def make_embed(anime_json_data):
    embed = discord.Embed(title=anime_json_data['title'], url=anime_json_data['url'], color=discord.Colour.dark_blue())
    embed.set_thumbnail(url=anime_json_data['image_url'])
    embed.add_field(name="Status", value=anime_json_data['status'], inline=True)
    if 'from' in anime_json_data['aired'] and anime_json_data['aired']['from'] is not None:
        embed.add_field(name="Air Date", value=anime_json_data['aired']['from'].split("T")[0], inline=True)
    if anime_json_data['synopsis'] is not None:
        # truncate the synopsis past 400 characters
        if len(anime_json_data['synopsis']) > 400:
            embed.add_field(name="Synopsis", value=anime_json_data['synopsis'][:400] + "...", inline=False)
        else:
            embed.add_field(name="Synopsis", value=anime_json_data['synopsis'], inline=False)
    genre_names = [g['name'] for g in anime_json_data['genres']]
    # the second index in return value specifies if this is SFW
    return (embed, "Hentai" not in genre_names)


def make_anime_jikan_request(jikan, mal_id, retry, jikan_exception):
    # if we've failed to get this page 5 times or more
    if retry >= 5:
        raise jikan_exception
    try:
        resp = jikan.anime(int(mal_id))
        time.sleep(3 * retry)
        return resp
    except (jikanpy.exceptions.JikanException, jikanpy.exceptions.APIException) as jex:
        # if we fail, increment retry and call again
        return make_anime_jikan_request(jikan, mal_id, retry + 1, jex)


class request_type:
    five = 1
    twenty_five = 2
    seventy_five = 3


def loop(crawler, j):
    # state has 2 lines in it, the first is last time we scraped the first 50 pages
    # the second is the last time we scraped the entirety of MAL
    # we should scrape the first 50 pages every 2 days and all the pages once a week

    # otherwise scrape the first 6 pages (and keep going if you find new entries) every 30 minutes

    # this script will be called by `python3 bot.py` as an os.system call
    # we should create a file named 'pid' that contains this process' pid
    # incase this file crashes for some reason, so we can restart it

    # create pid file
    with open('pid', 'w') as pid_f:
        pid_f.write(str(os.getpid()))

    while True:
        # Initialize 'state' values to 0, (i.e. its Jan 1. 1970, so if needed, 25/75 are chekced
        first_25_pages = 0
        first_75_pages = 0
        page_range = 5
        req_type = request_type.five

        # read times from 'state' file
        if os.path.exists("state"):
            with open("state", "r") as last_scraped:
                first_25_pages, first_75_pages = list(map(int, last_scraped.read().strip().splitlines()))

        # if its been 2 weeks since we checked 75 pages
        if int(time.time() - first_75_pages) > 3600 * 24 * 7 * 2:  # seconds in 2 weeks
            page_range = 75
            req_type = request_type.seventy_five

        # if its been 2 dats since we've checked 25 pages
        elif int(time.time()) - first_25_pages > 3600 * 24 * 2:  # seconds in 2 days
            page_range = 25
            req_type = request_type.twenty_five

        logger.debug("(loop) checking {} pages".format(page_range))

        # read old database
        with open("old", 'r') as old_f:
            old_db = set(old_f.read().splitlines())

        new_ids = []
        current_page = 0
        while current_page < page_range:
            page_ids = []
            logger.debug("Downloading 'Just Added' page {}".format(current_page))
            mal_ids = list(get_ids_from_search_page(current_page, crawler))
            for mal_id in mal_ids:
                # if this is a new entry
                if mal_id not in old_db:
                    # found a new entry, extend how many pages we should check
                    extend_by = 5 + int(current_page / 5)
                    page_range_before_extend = int(page_range)
                    page_range = current_page + extend_by
                    new_ids.append(mal_id)
                    logger.debug("Found new MAL Entry: {}".format(mal_id))
                    if page_range != page_range_before_extend:
                        logger.debug("Found new entry on page {}. Extending search by {} to {}".format(current_page, extend_by, current_page + extend_by))
            current_page += 1

        # if we extended past the thresholds because we found new entries
        if page_range >= 75:
            req_type = request_type.seventy_five
        elif page_range >= 25:
            req_type = request_type.twenty_five

        # if we looked at the first 25 or 75 pages, write time to 'state'
        if req_type == request_type.seventy_five:
            # write current time to 'state', 75 > 25 pages
            with open("state", "w") as last_scraped:
                last_scraped.write("{}\n{}".format(int(time.time()), int(time.time())))
        elif req_type == request_type.twenty_five:
            with open("state", "w") as last_scraped:
                last_scraped.write("{}\n{}".format(int(time.time()), first_75_pages))

        # download json for new elements and write to 'new' as pickles (serialized objects)
        if new_ids:
            # create list of pickled embeds
            pickles = []
            for new_id in new_ids:
                try:
                    logger.debug("Requesting {} from Jikan".format(new_id))
                    anime_json_resp = make_anime_jikan_request(j, new_id, 0, None)
                    pickles.append(make_embed(anime_json_resp))
                except jikanpy.exceptions.JikanException:
                    logger.warning("Failed to get {} from Jikan after 5 retries, skipping for now".format(new_id))
                    continue
            if pickles:
                with open("new", "wb") as new_entries:
                    pickle.dump(pickles, new_entries)
        sleep_for = int(60 * random.uniform(27, 35))
        logger.debug("Sleeping for {}m{}s".format(sleep_for // 60, sleep_for % 60))
        time.sleep(sleep_for)  # sleep for around 30 minutes


def main(init):
    j = jikanpy.Jikan()
    if init:
        print("Initializing database with {}'s anime list".format(init))
        entries = download_anime_list(init, j)
        with open("old", "w") as old_f:
            for entry in entries:
                old_f.write("{}\n".format(entry["mal_id"]))
    crawler = crawl(wait=8, retry_max=4)
    loop(crawler, j)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--initialize", default=False, help="Initialize the 'old' database by using a users animelist")
    main(parser.parse_args().initialize)
