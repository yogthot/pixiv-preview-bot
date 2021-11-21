
import os
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
    
    async def on_message(self, message):
        if message.author.bot:
            return
        
        ids = self.pixiv.find_urls(message.content)
        if len(ids) > 0:
            async with message.channel.typing():
                with self.pixiv.download_preview(ids[0]) as details:
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

