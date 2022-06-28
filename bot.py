
import os
import re
import asyncio
import discord

from pixiv import Pixiv

async def _safe_await(coro):
    try:
        await coro
    except:
        pass

class PixivBot:
    def __init__(self, token, cookie):
        self.token = token
        self.pixiv = Pixiv(cookie)
        
        self.client = discord.Client(guild_subscriptions=False)
        self.client.event(self.on_message)
    
    async def start(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self.client.start(self.token))
    
    async def close(self):
        await _safe_await(self.client.close())
    
    
    POST_REGEXP = re.compile('(<?)https?:\/\/(?:www\.)?pixiv\.net\/(?:[a-zA-Z]{2}\/)?artworks\/(?P<post_id>\d+)>?', flags=re.IGNORECASE)
    def find_url(self, text):
        urls = self.POST_REGEXP.findall(text)
        if len(urls) > 0 and urls[0][0] != '<':
            return urls[0][1]
            
        else:
            return None
    
    async def on_message(self, message):
        if message.author.bot:
            return
        
        # testing server :(
        #if message.guild.id != 880079930929582091:
        #    return
        
        id = self.find_url(message.content)
        if id is not None:
            gif = bool(re.search(r'\bgif\b', message.content))
            async with message.channel.typing():
                isnsfw = message.channel.is_nsfw()
                with self.pixiv.download_preview(id, gif=gif, allow_nsfw=isnsfw) as details:
                    if not details.nsfw or message.channel.is_nsfw():
                        msg = ''
                        if details.files > 1:
                            msg = f'1/{details.files}'
                        
                        await message.channel.send(msg, file=discord.File(details.path, details.filename))
                        
                        try: await message.edit(suppress=True)
                        except: pass


bot = PixivBot(os.environ['DISCORD_TOKEN'], os.environ['PIXIV_COOKIE'])

loop = asyncio.get_event_loop()
loop.run_until_complete(bot.start())

print('bot started')

try:
    loop.run_forever()
    
except KeyboardInterrupt:
    print('\n\nbye')
    
finally:
    loop.run_until_complete(bot.close())

