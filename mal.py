#!/usr/bin/env python3

import sys
import os
import re
import time
import random
import logging
import pickle
import json

import git
import requests

from utils import setup_logger
from utils.embeds import create_embed



logger = setup_logger(__name__, "mal", supress_stream_output=True)

def loop():

    # create pid file
    with open('pid', 'w') as pid_f:
        pid_f.write(str(os.getpid()))

    # get new id's
    update_git_repo()
    # read all ids
    ids = read_json_cache()

    new_ids = []

    # if there is no old file
    if not os.path.exists('old'):
        with open('old', 'w') as old_f:
            old_f.write("\n".join(map(str, ids)))
    else:
        with open('old', 'r') as old_f:
            old_ids = list(map(int, old_f.read().strip().splitlines()))

        # check for new ids
        new_ids = list(set(ids) - set(old_ids))

    # download json for new elements and write to 'new' as pickles (serialized objects)
    if new_ids:
        # create list of pickled embeds
        pickles = []
        for new_id in new_ids:
            logger.info("Downloading page for MAL id: {}".format(new_id))
            pickles.append(create_embed(int(new_id), logger))
        if pickles:
            with open("new", "wb") as new_entries:
                pickle.dump(pickles, new_entries)
        # dump new cache file to 'old'
        with open('old', 'w') as old_f:
            old_f.write("\n".join(map(str, ids)))

    logger.info("Sleeping for 10m")
    time.sleep(600)


def main():
    update_git_repo()
    while True:
        try:
            loop()
        except Exception as e:
            logger.error(str(e), exc_info=True)

if __name__ == "__main__":
    main()
