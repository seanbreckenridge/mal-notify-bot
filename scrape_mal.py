#!/usr/bin/env python3

import os
import requests
import time
import argparse
import sys
from bs4 import BeautifulSoup

# basic rules
# 1) Check the first 50 pages every 2 days
# 2) Check the entirety of MAL every week
# 3) Check the first 3 pages of the Just Added every 30(ish) minutes
# 3a) If you don't find an entry, don't continue
# 3b) If you find an entry, check the next 5 pages
# 3b.1) Continue checking pages till you don't find a new entry for 5 pages

# the last time the 50 pages and the entirety of MAL should be saved in a file called 'state'.
# since the discord bot and scraper are going to run on different PIDs, while we are scraping
# a file called 'lock' should be in the root directory, which forbids the discord bot from
# trying to read/log new entries, from a file called 'new'.
# the discord bot process will then read all entries from 'new' to 'old',
# logging them in the server in the process

base_url="https://myanimelist.net/anime.php?o=9&c%5B0%5D=a&c%5B1%5D=d&cv=2&w=1&show={}"

def just_added_page(page_number):
    """returns the URL for the newly added page of entries. Assumes the first page is page 0"""
    return base_url.format(page_number * 50)

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
                self.last_scrape = time.time()
                if response.status_code == requests.codes.ok:
                    return response
                else:
                    raise Exception("Non-standard issue connecting to {}: {}".format(url, response.status_code))
            except requests.exceptions.RequestException as e:
            	pass
            count += 1

    def get_html(self, url):
        return self.get(url).text

    def get_soup(self, url):
        return BeautifulSoup(self.get(url).text, 'html.parser')

    def get_json(self, url):
        return self.get(url).json()

    def get_just_added_page(self, page_number):
        return self.get_html(just_added_page(page_number))

class entry:
    def __init__(self, id, name, in_database):
        self.id = id
        self.name = name
        self.in_database = in_database if type(in_database) == bool else False

    def __repr__(self):
        return "{}: {}{}".format(id, name, ", in database" if self.in_database else ", not in database")

    def __str__(self):
        return self.__repr__()

def make_jikan_animelist_request(j, username, page, retry, jikan_exception):
    # if we've failed to get this page 5 times or more
    if retry >= 5:
        raise jikan_exception
    try:
        resp = j.user(username=username, request='animelist', argument='all', page=page)
        time.sleep(1)
        return resp
    except jikanpy.exceptions.JikanException as jex:
        # if we fail, increment retry and call again
        print("... Failed with {}, retrying... ({} of 5)".format(type(jex).__name__, retry))
        return make_jikan_animelist_request(username, page, j, retry + 1, jex)

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

def main(init):
    if init:
        print("Initializing database with {}'s anime list".format(init))
        import jikanpy
        j = jikanpy.Jikan()
        entries = download_anime_list(init, j)
        with open("old", "w") as old_f:
            for entry in entries:
                old_f.write("{}\n".format(entry["mal_id"]))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--initialize", default=False, help="Initialize the 'old' database by using a users animelist")
    main(parser.parse_args().initialize)
