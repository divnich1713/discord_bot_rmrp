"""
Scheduler — Фоновые задачи (проверка истечения срока в академии)
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from utils.constants import COLORS
from utils.embeds import academy_deadline_reminder_embed, academy_failed_embed


class TaskScheduler:
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    async def start(self):
        self.scheduler.add_job(
            self._check_academy_deadlines,
            "interval",
            hours=1,
            id="academy_check",
            replace_existing=True,
        )
        # Каждое воскресенье в 21:00 МСК (18:00 UTC)
        self.scheduler.add_job(
            self.send_weekly_report,
            "cron",
            day_of_week="sun",
            hour=18,
            minute=0,
            id="weekly_report",
            replace_existing=True,
        )
        self.scheduler.start()
        print("✅ Планировщик запущен (проверка академии каждый час, еженедельный отчёт по воскресеньям в 21:00 МСК)")

    async def _check_academy_deadlines(self):
        """Проверяет сроки обучения курсантов"""
        try:
            cadets = await self.bot.db.get_cadets()
            config = self.bot.config
            duration_days = config["academy"].get("duration_days", 7)
            reminder_hours = config["academy"].get("reminder_hours_before", 24)
            guild_id = config.get("guild_id", 0)
            guild = self.bot.get_guild(guild_id)

            if not guild:
                return

            log_channel_id = config["channels"].get("bot_log", 0)
            log_channel = guild.get_channel(log_channel_id) if log_channel_id else None

            now = datetime.utcnow()

            for cadet in cadets:
                joined_str = cadet.get("joined_academy")
                if not joined_str:
                    continue

                try:
                    joined = datetime.fromisoformat(joined_str)
                except ValueError:
                    continue

                deadline = joined + timedelta(days=duration_days)
                time_left = deadline - now
                discord_id = int(cadet["discord_id"])
                member = guild.get_member(discord_id)

                # ── Срок истёк ──
                if time_left.total_seconds() <= 0:
                    await self._fail_cadet(cadet, member, guild, log_channel)

                # ── Напоминание за reminder_hours часов ──
                elif time_left.total_seconds() <= reminder_hours * 3600:
                    if not cadet.get("reminder_sent"):
                        await self._send_reminder(cadet, member, time_left)
                        await self.bot.db.update_member(cadet["discord_id"], reminder_sent=1)

        except Exception as e:
            print(f"❌ Ошибка планировщика: {e}")

    async def _fail_cadet(self, cadet: dict, member: discord.Member,
                           guild: discord.Guild, log_channel):
        """Проваливает курсанта по истечении срока"""
        config = self.bot.config

        # Меняем статус в БД
        await self.bot.db.update_member(
            cadet["discord_id"],
            status="failed",
            rank_id=0,
        )

        # Меняем роли
        if member:
            roles_to_remove_keys = ["cadet"]
            failed_role_id = config["roles"].get("failed_cadet", 0)
            candidate_role_id = config["roles"].get("candidate", 0)

            for key in roles_to_remove_keys:
                role_id = config["roles"].get(key, 0)
                if role_id:
                    role = guild.get_role(role_id)
                    if role and role in member.roles:
                        try:
                            await member.remove_roles(role, reason="Не прошёл академию (срок истёк)")
                        except Exception:
                            pass

            if failed_role_id:
                failed_role = guild.get_role(failed_role_id)
                if failed_role:
                    try:
                        await member.add_roles(failed_role, reason="Не прошёл академию")
                    except Exception:
                        pass

            # Меняем никнейм
            game_name = cadet.get("game_name", "")
            try:
                await member.edit(nick=game_name)
            except Exception:
                pass

            # Отправляем DM
            try:
                embed = academy_failed_embed(game_name)
                await member.send(embed=embed)
            except Exception:
                pass

        # Логируем
        if log_channel:
            e = discord.Embed(
                title="🔴 Курсант не прошёл академию (таймер)",
                description=(
                    f"**{cadet['game_name']}** (<@{cadet['discord_id']}>) "
                    "не прошёл академию АВНГ — срок истёк."
                ),
                color=COLORS["error"],
                timestamp=datetime.utcnow(),
            )
            await log_channel.send(embed=e)

    async def _send_reminder(self, cadet: dict, member: discord.Member, time_left: timedelta):
        """Отправляет напоминание о дедлайне"""
        if not member:
            return
        hours_left = int(time_left.total_seconds() // 3600)
        days_left = max(1, hours_left // 24)
        try:
            embed = academy_deadline_reminder_embed(days_left)
            await member.send(embed=embed)
        except Exception:
            pass

    async def send_weekly_report(self, target_channel: Optional[discord.TextChannel] = None) -> Optional[discord.Embed]:
        """Генерирует и публикует еженедельный отчёт командованию"""
        try:
            from utils.embeds import weekly_report_embed
            config = self.bot.config
            guild_id = config.get("guild_id", 0)
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return None

            # 1. Собираем статистику
            stats_data = await self.bot.db.get_weekly_statistics()
            embed = weekly_report_embed(stats_data, guild)

            # 2. Определяем канал отправки
            if target_channel:
                ch = target_channel
            else:
                ch_id = config["channels"].get("weekly_reports", 1539378119788732416)
                ch = guild.get_channel(ch_id)

            if ch:
                if isinstance(ch, discord.ForumChannel):
                    today_str = datetime.utcnow().strftime("%d.%m.%Y")
                    await ch.create_thread(
                        name=f"📊 Еженедельный отчёт | {today_str}",
                        content="📊 **Официальная еженедельная сводка командованию УФСВНГ**",
                        embed=embed,
                    )
                else:
                    await ch.send(
                        content="📊 **Официальная еженедельная сводка командованию УФСВНГ**",
                        embed=embed,
                    )

            return embed
        except Exception as e:
            print(f"❌ Ошибка отправки еженедельного отчёта: {e}")
            return None
