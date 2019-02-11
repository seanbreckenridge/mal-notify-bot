# mal-notify-bot

A discord bot that checks the [Just Added](https://myanimelist.net/anime.php?o=9&c%5B0%5D=a&c%5B1%5D=d&cv=2&w=1) page on [MAL](https://myanimelist.net/), reporting any newly approved entries.

<img src="https://i.imgur.com/pEVk0iw.png" alt="" width=400>

You can join the discord server this is run on [here](https://goo.gl/ciydwZ).

Depedencies:
```
pip3 install --user git+git://github.com/AWConant/jikanpy.git
pip3 install --user PyYaml requests discord.py bs4
```

This is run on `Python 3.5.3`

Run:

`cd` into the directory

put your bots token in a file named `token.yaml` with contents like:

`token: !!str EU*#3eiSzEr7i4L36FaTlrV0*RtuGOBVNrcteyrtt$GPAwNtkJKQg*dweSLy`

`python3 bot.py` to start, which calls `python3 scrape_mal.py` as a background process.

Note the names of the channels were `bot.py` posts new links are hard coded, as `feed` and `nsfw-feed`, you can change those [here](https://github.com/purplepinapples/mal-notify-bot/blob/master/bot.py#L45)
