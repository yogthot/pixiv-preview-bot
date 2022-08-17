#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
import tempfile
import asyncio
import json
import zipfile
import subprocess
import pathlib

import requests
import discord
from bs4 import BeautifulSoup

OWNER_ID = int(os.environ['OWNER_ID']) if 'OWNER_ID' in os.environ else None
DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
PIXIV_COOKIE = os.environ['PIXIV_COOKIE']


http = requests.Session()
http.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:80.0) Gecko/20100101 Firefox/82.0',
    'Referer': 'https://www.pixiv.net/'
})
cookie = requests.cookies.create_cookie(name='PHPSESSID', value=PIXIV_COOKIE)
http.cookies.set_cookie(cookie)

def download_url(url):
    with http.get(url, stream=True) as resp:
        fd, path = tempfile.mkstemp()
        
        with os.fdopen(fd, 'w+b') as file:
            for chunk in resp.iter_content(chunk_size=8192):
                file.write(chunk)
        
        return path

def ellipsis(str, length, suffix='...'):
    return str[:(length - len(suffix))] + suffix if len(str) > length else str


class PixivFile(os.PathLike):
    def __init__(self, path, filename):
        self.path = path
        self.filename = filename
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        if self.path is not None:
            os.remove(self.path)
    
    def __fspath__(self):
        return self.path
    
    def __str__(self):
        return self.filename

class PixivPost:
    @classmethod
    def init(cls, post_id):
        response = http.get('https://www.pixiv.net/ajax/illust/{post_id}'.format(post_id=post_id))
        response.raise_for_status()
        
        return cls(post_id, json.loads(response.text)['body'])
    
    def __init__(self, post_id, post):
        self.id = post_id
        self.post = post
        self.title = self.post['title']
        self.author = self.post['userName']
        self.author_url = 'https://www.pixiv.net/users/{user_id}'.format(user_id=self.post['userId'])
        self.pages = self.post['pageCount']
        self.is_nsfw = self.post['xRestrict'] >= 1
        self.is_ugoira = self.post['illustType'] == 2
        
        comment_html = BeautifulSoup(self.post['description'], 'html.parser')
        for br in comment_html.find_all('br'): br.replace_with('\n')
        self.comment = comment_html.text
    
    def convert_webm(self, ugoira_zip):
        fd, dst_path = tempfile.mkstemp()
        
        with tempfile.TemporaryDirectory() as tmp_dir, \
             zipfile.ZipFile(ugoira_zip, 'r') as zip:
            
            zip.extractall(tmp_dir)
            
            inputs_path = f'{tmp_dir}/inputs.txt'
            with open(inputs_path, 'w+') as inputs:
                for frame in self.ugoira_frames:
                    inputs.write('file ' + str(frame['file']) + '\n')
                    inputs.write('duration ' + str(frame['delay'] / 1000) + '\n')
            
            arguments = [
                'ffmpeg',
                # input
                '-f', 'concat',
                '-i', str(inputs_path),
                
                # output
                '-f', 'webm',
                '-c:v', 'libvpx',
                '-b:v', '10M',
                '-an',
                '-vsync', '2',
                '-r', '1000',
                '-y',
                '-'
            ]
            
            FNULL = open(os.devnull, 'w')
            ffmpeg = subprocess.Popen(arguments, shell=False, stdin=FNULL, stdout=fd, stderr=subprocess.PIPE)
            out, err = ffmpeg.communicate()
            if ffmpeg.returncode:
                if err: print(err.decode('utf-8'), file=sys.stderr)
        
        return PixivFile(dst_path, f'{self.id}.webm')

    def convert_gif(self, ugoira_zip):
        fd, dst_path = tempfile.mkstemp()
        
        with tempfile.TemporaryDirectory() as tmp_dir, \
             zipfile.ZipFile(ugoira_zip, 'r') as zip:
            
            zip.extractall(tmp_dir)
            
            delays = []
            for frame in self.ugoira_frames:
                delay = str(frame['delay'] / 1000)
                file = str(frame['file'])
                delays.extend([
                    '-delay', delay,
                    f'{tmp_dir}/{file}' 
                ])
            
            arguments = ['convert', *delays, 'gif:-']
            
            FNULL = open(os.devnull, 'w')
            ffmpeg = subprocess.Popen(arguments, shell=False, stdin=FNULL, stdout=fd, stderr=subprocess.PIPE)
            out, err = ffmpeg.communicate()
            if ffmpeg.returncode:
                if err: print(err.decode('utf-8'), file=sys.stderr)
        
        return PixivFile(dst_path, f'{self.id}.gif')
    
    def preview(self, page=0, gif=False):
        if self.is_ugoira:
            # ugoira
            response = http.get('https://www.pixiv.net/ajax/illust/{post_id}/ugoira_meta'.format(post_id=self.id))
            response.raise_for_status()
            self.ugoira_meta = json.loads(response.text)['body']
            self.ugoira_frames = self.ugoira_meta['frames']
            
            with PixivFile(download_url(self.ugoira_meta['src']), None) as ugoira_zip:
                if gif:
                    return self.convert_gif(ugoira_zip)
                    
                else:
                    return self.convert_webm(ugoira_zip)
            
        else:
            if page >= 0 and page < self.pages:
                response = http.get('https://www.pixiv.net/ajax/illust/{post_id}/pages'.format(post_id=self.id))
                response.raise_for_status()
                pages = json.loads(response.text)['body']
                url = pages[page]['urls']['regular']
                
            else:
                url = post['urls']['regular']
            
            return PixivFile(download_url(url), url.split('/')[-1])

class ServerList:
    def __init__(self, filename):
        self.filename = filename
        
        if pathlib.Path(self.filename).exists():
            with open(self.filename) as f:
                self.servers = json.load(f)
        
        else:
            self.servers = dict()
    
    def contains(self, guild_id):
        return str(guild_id) in self.servers
    
    def __contains__(self, value):
        return self.contains(value)
    
    def add(self, guild_id, name):
        self.servers[str(guild_id)] = name
        with open(self.filename, 'w+') as f:
            json.dump(self.servers, f, indent=4, sort_keys=True)

class PixivBot:
    def __init__(self, token):
        self.token = token
        
        self.whitelist = ServerList('whitelist.json')
        self.client = discord.Client(guild_subscriptions=False)
        self.client.event(self.on_message)
    
    async def start(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self.client.start(self.token))
    
    async def close(self):
        await self.client.close()
    
    
    POST_REGEXP = re.compile(
        '((<?)https?:\/\/(?:www\.)?pixiv\.net\/(?:[a-zA-Z]{2}\/)?artworks\/(?P<post_id>\d+)>?)',
        flags=re.IGNORECASE
    )
    
    def find_url(self, text):
        urls = self.POST_REGEXP.findall(text)
        if len(urls) > 0 and urls[0][1] != '<':
            return urls[0][0], urls[0][2]
            
        else:
            return None, None
    
    def parse_page(self, msg):
        try: return int(re.search(r'\bp(\d+)\b', msg).group(1))
        except: return 0
    
    async def on_message(self, message):
        if message.author.bot:
            return
        
        if message.guild.id not in self.whitelist:
            if OWNER_ID is not None and message.author.id == OWNER_ID and message.content == '--whitelist':
                self.whitelist.add(message.guild.id, message.guild.name)
                await message.add_reaction('✅')
                return
            return
        
        url, id = self.find_url(message.content)
        if id is not None:
            isgif = bool(re.search(r'\bgif\b', message.content))
            page = self.parse_page(message.content) # /p(\d+)/
            
            post = PixivPost.init(id)
            if not message.channel.is_nsfw() and post.is_nsfw:
                # don't do anything if nsfw post and sfw channel
                return
            
            # clamp to [1, post.pages]
            page = max(1, min(page, post.pages))
            
            async with message.channel.typing():
                with post.preview(page=page - 1, gif=isgif) as details:
                    file = discord.File(details.path, details.filename)
                    
                    embed = discord.Embed(
                        title=post.title,
                        description=ellipsis(post.comment, 250),
                        color=discord.Color.from_rgb(0, 150, 250),
                        url=url,
                    )
                    embed.set_author(name=post.author, url=post.author_url)
                    
                    if post.pages > 1:
                        embed.add_field(name='Page', value='{}/{}'.format(page, post.pages), inline=False)
                    
                    await message.channel.send('', embed=embed, file=file)
                    
                    # attempt to delete the old embed
                    try: await message.edit(suppress=True)
                    except: pass


bot = PixivBot(DISCORD_TOKEN)

loop = asyncio.get_event_loop()
loop.run_until_complete(bot.start())

print('bot started')

try:
    loop.run_forever()
    
except KeyboardInterrupt:
    print('\n\nbye')
    
finally:
    loop.run_until_complete(bot.close())

