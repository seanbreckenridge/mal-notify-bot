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

from embeds import create_embed

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
        logger.debug("Requesting page {}".format(page_number))
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



class request_type:
    two = 1
    twelve = 2
    twenty_five = 3
    fifty = 4


def loop(crawler):
    # Check:
    # 2 pages every 30 minutes
    # 12 pages once every 4 hours
    # 25 pages once every 2 days
    # 50 pages once every week

    # if you find something near the end of a range (e.g. on page 10 while checking 12 pages)
    # extend the range till you stop finding new entries

    # this script will be called by `python3 bot.py` as an os.system call
    # we should create a file named 'pid' that contains this process' pid
    # incase this file crashes for some reason, so we can restart it

    # create pid file
    with open('pid', 'w') as pid_f:
        pid_f.write(str(os.getpid()))

    while True:
        # Initialize 'state' values to 0, (i.e. its Jan 1. 1970, so if needed, 12/25/50 are chekced
        first_12_pages = first_25_pages = first_50_pages = 0
        page_range = 2
        req_type = request_type.two
        
        logger.debug("Checking state")
        # read times from 'state' file
        if os.path.exists("state"):
            with open("state", "r") as last_scraped:
                first_12_pages, first_25_pages, first_50_pages = list(map(int, last_scraped.read().strip().splitlines()))


        # if its been a week since we checked 50 pages
        if int(time.time() - first_50_pages) > 3600 * 24 * 7:  # seconds in a week
            page_range = 50
            req_type = request_type.fifty

        # if its been 2 days since we've checked 25 pages
        elif int(time.time()) - first_25_pages > 3600 * 24 * 2:  # seconds in 2 days
            page_range = 25
            req_type = request_type.twenty_five

	# if its been 4 hours since we've checked 12 pages
        elif int(time.time()) - first_12_pages > 3600 * 4:  # seconds in 4 hours
            page_range = 12
            req_type = request_type.twelve

        logger.debug("(loop) checking {} pages".format(page_range))

        # read old database
        with open("old", 'r') as old_f:
            old_db = set(old_f.read().splitlines())

        new_ids = []
        current_page = 0
        while current_page < page_range:
            page_ids = []
            logger.debug("Checking page {}".format(current_page))
            mal_ids = list(get_ids_from_search_page(current_page, crawler))
            for mal_id in mal_ids:
                # if this is a new entry
                if mal_id not in old_db:
                    # found a new entry, extend how many pages we should check
                    extend_by = 5 + int(current_page / 5)
                    page_range_before_extend = page_range
                    if current_page + extend_by > page_range:
                        page_range = current_page + extend_by
                    new_ids.append(mal_id)
                    logger.debug("Found new MAL entry ({}) on page: {}".format(mal_id, current_page))
                    if page_range != page_range_before_extend:
                        logger.debug("Found new MAL entry ({}) on page {}. Extending search from {} to {}".format(mal_id, current_page, page_range_before_extend, page_range))
            current_page += 1

        # if we extended past the thresholds because we found new entries
        if page_range >= 50:
            req_type = request_type.fifty
        elif page_range >= 25:
            req_type = request_type.twenty_five
        elif page_range >= 12:
            req_type = request_type.twelve

        # if we looked at the first 12/25/50, write time to 'state'
        if req_type == request_type.fifty:
            # write current time to 'state', 50 > 25 pages
            with open("state", "w") as last_scraped:
                last_scraped.write("{}\n{}\n{}".format(int(time.time()), int(time.time()), int(time.time())))
        elif req_type == request_type.twenty_five:
            with open("state", "w") as last_scraped:
                last_scraped.write("{}\n{}\n{}".format(int(time.time()), int(time.time()), first_50_pages))
        elif req_type == request_type.twelve:
            with open("state", "w") as last_scraped:
                last_scraped.write("{}\n{}\n{}".format(int(time.time()), first_25_pages, first_50_pages))


        # download json for new elements and write to 'new' as pickles (serialized objects)
        if new_ids:
            # create list of pickled embeds
            pickles = []
            for new_id in new_ids:
                logger.debug("Downloading page for MAL id: {}".format(new_id))
                pickles.append(create_embed(int(new_id), crawler, logger))
            if pickles:
                with open("new", "wb") as new_entries:
                    pickle.dump(pickles, new_entries)
        sleep_for = int(60 * random.uniform(27, 35))
        logger.debug("Sleeping for {}m{}s".format(sleep_for // 60, sleep_for % 60))
        time.sleep(sleep_for)  # sleep for around 30 minutes


def main(init):
    if init:
        j = jikanpy.Jikan()
        print("Initializing database with {}'s anime list".format(init))
        entries = download_anime_list(init, j)
        with open("old", "w") as old_f:
            for entry in entries:
                old_f.write("{}\n".format(entry["mal_id"]))
    crawler = crawl(wait=8, retry_max=4)
    loop(crawler)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--initialize", default=False, help="Initialize the 'old' database by using a users animelist")
    main(parser.parse_args().initialize)
