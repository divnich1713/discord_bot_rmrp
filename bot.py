"""
Бот Росгвардия — Главный модуль
"""
import asyncio
import json
import os
import sys
import logging

# Фикс кодировки на Windows — чтобы эмодзи в принтах не вызывали ошибку
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Логирование в файл + консоль
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('bot_errors.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger('rosguard')

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import Database

load_dotenv()

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

intents = discord.Intents.default()
intents.members = True
# intents.message_content не нужен — используем только slash-команды


class RosguardBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.config = config
        self.db = Database()
        self._scheduler_started = False  # защита от двойного старта

    async def setup_hook(self):
        await self.db.init()

        cogs = [
            "cogs.applications",
            "cogs.academy",
            "cogs.reports",
            "cogs.ranks",
            "cogs.bonuses",
            "cogs.dossier",
            "cogs.admin",
            "cogs.position",
            "cogs.appeals",
        ]
        # Параллельная загрузка cogs — быстрее при старте
        results = await asyncio.gather(
            *[self.load_extension(c) for c in cogs],
            return_exceptions=True
        )
        for cog, result in zip(cogs, results):
            if isinstance(result, Exception):
                print(f"  ❌ Ошибка загрузки {cog}: {result}")
            else:
                print(f"  ✅ Загружен модуль: {cog}")

        guild = discord.Object(id=self.config["guild_id"])
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        cmd_names = [f"/{c.name}" for c in synced]
        print(f"✅ Синхронизировано {len(synced)} slash-команд для сервера {self.config['guild_id']}: {', '.join(cmd_names)}")

        # Запускаем планировщик один раз в setup_hook (не в on_ready!)
        from utils.scheduler import TaskScheduler
        scheduler = TaskScheduler(self)
        await scheduler.start()
        self._scheduler_started = True

    async def on_ready(self):
        print(f"\n{'='*50}")
        print(f"  🤖 Бот запущен: {self.user}")
        print(f"  📡 Серверов: {len(self.guilds)}")
        print(f"{'='*50}\n")
        # Планировщик запускается один раз в setup_hook, не здесь

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ У вас недостаточно прав!", ephemeral=True)


bot = RosguardBot()

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ Токен не найден! Создайте файл .env с переменной DISCORD_TOKEN")
        exit(1)
    bot.run(token)
