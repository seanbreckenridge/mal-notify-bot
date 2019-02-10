import os
import yaml

from time import time
from json import loads

from discord import Client
from discord.ext import commands
from asyncio import sleep

with open('token.yaml', 'r') as t:
    token = yaml.load(t)["token"]

#  start client
client = commands.Bot(command_prefix=commands.when_mentioned)
client.remove_command('help') # remove default help

@client.event
async def on_ready():
    print("ready!")

@client.command(pass_context=True)
async def help(ctx):
    await client.send_message(ctx.message.channel, "This should have been a help message, but I haven't written one yet")

@client.command(pass_context=True)
@client.event
async def on_command_error(error, ctx):
    message = ctx.message.content.split(">", maxsplit=1)[1].lower().strip()
    message = message.replace("@", "") # make sure bot doesn't ping people
    await client.send_message(ctx.message.channel, "Not sure what '{}' means".format(message))

client.run(token)

