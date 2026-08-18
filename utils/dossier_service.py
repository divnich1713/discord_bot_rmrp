"""
Dossier Service — Управление личными делами в канале-форуме (Discord Forum Channel)
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

import discord

from utils.constants import COLORS, RANK_BY_ID, RANKS, STATUSES, REPRIMAND_TYPES

logger = logging.getLogger("rosguard.dossier")


def _rank_name(rank_id: int) -> str:
    r = RANK_BY_ID.get(rank_id)
    return r["name"] if r else "Неизвестно"


def forum_dossier_embed(
    member_data: Dict,
    discord_member: Optional[discord.Member],
    promotions: List[Dict],
    bonuses: List[Dict],
    reprimands: List[Dict],
    report_count: int,
) -> discord.Embed:
    """Генерирует главную карточку личного дела для первого сообщения ветки форума."""
    case_num = member_data.get("case_number") or 1
    case_str = f"№{case_num:04d}"
    game_name = member_data.get("game_name", "Сотрудник")
    static_id = member_data.get("static_id") or "—"
    military_id = member_data.get("military_id") or "—"

    rank_id = member_data.get("rank_id", 0)
    rank = RANK_BY_ID.get(rank_id, RANKS[0])
    status_key = member_data.get("status", "cadet")
    status_label = STATUSES.get(status_key, status_key)
    pos_prefix = member_data.get("position_prefix") or ""

    # Цвет по статусу
    if status_key == "fired":
        embed_color = 0x2C3E50  # Тёмный
    elif status_key == "cadet":
        embed_color = 0xF1C40F  # Золотой / Жёлтый
    elif status_key == "vacation":
        embed_color = 0xE67E22  # Оранжевый
    elif status_key == "failed":
        embed_color = 0xE74C3C  # Красный
    else:
        embed_color = COLORS.get("rosguard", 0x1A237E)

    embed = discord.Embed(
        title=f"📁 ЛИЧНОЕ ДЕЛО {case_str} | {game_name}",
        color=embed_color,
        timestamp=datetime.utcnow(),
    )

    if discord_member:
        embed.set_thumbnail(url=discord_member.display_avatar.url)

    # 1. Персональные данные
    discord_mention = discord_member.mention if discord_member else f"<@{member_data['discord_id']}>"
    pos_display = f"{pos_prefix} " if pos_prefix else ""
    embed.add_field(name="👤 Сотрудник", value=f"{discord_mention}\n**{pos_display}{game_name}**", inline=True)
    embed.add_field(name="🎮 Статик (ID)", value=f"`{static_id}`", inline=True)
    embed.add_field(name="🪖 Военный билет", value=f"`{military_id}`", inline=True)

    # 2. Служебный статус
    embed.add_field(
        name="🎖️ Звание",
        value=f"**{rank['prefix']} {rank['name']}**",
        inline=True,
    )
    embed.add_field(
        name="📊 Статус",
        value=f"**{status_label}**",
        inline=True,
    )

    # Даты
    joined_faction = member_data.get("joined_faction")
    joined_academy = member_data.get("joined_academy")
    dates_lines = []
    if joined_academy:
        try:
            dt_a = datetime.fromisoformat(joined_academy).strftime("%d.%m.%Y")
            dates_lines.append(f"Академия: `{dt_a}`")
        except Exception:
            pass
    if joined_faction:
        try:
            dt_f = datetime.fromisoformat(joined_faction).strftime("%d.%m.%Y")
            dates_lines.append(f"Фракция: `{dt_f}`")
        except Exception:
            pass
    embed.add_field(
        name="📅 Даты службы",
        value="\n".join(dates_lines) if dates_lines else "—",
        inline=True,
    )

    # 3. Служебная статистика
    active_reps = sum(1 for r in reprimands if r.get("active", 1))
    embed.add_field(
        name="📊 Служебные показатели",
        value=(
            f"📈 Повышений: **{len(promotions)}**\n"
            f"⭐ Премий: **{len(bonuses)}**\n"
            f"⚠️ Взысканий: **{active_reps}** (всего {len(reprimands)})\n"
            f"📝 Отчётов о работе: **{report_count}**"
        ),
        inline=False,
    )

    # 4. Заметки руководства (если есть)
    notes = member_data.get("notes")
    if notes:
        embed.add_field(name="📌 Характеристика / Заметки", value=notes[:1024], inline=False)

    embed.set_footer(
        text=f"ID личного дела: {case_str} • Discord ID: {member_data['discord_id']} • Обновлено"
    )
    return embed


def dossier_event_embed(
    title: str,
    description: str,
    color: int,
    fields: Optional[List[tuple]] = None,
    author: Optional[discord.Member] = None,
) -> discord.Embed:
    """Создаёт embed-сообщение события для публикации в ветку личного дела."""
    e = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.utcnow(),
    )
    if author:
        e.set_footer(
            text=f"Приказ / запись оформил: {author.display_name}",
            icon_url=author.display_avatar.url,
        )
    if fields:
        for name, value, inline in fields:
            e.add_field(name=name, value=value, inline=inline)
    return e


class DossierService:
    """Сервис взаимодействия с каналом-форумом архива личных дел."""

    @staticmethod
    def _find_matching_tag(forum: discord.ForumChannel, status_key: str) -> Optional[discord.ForumTag]:
        """Ищет подходящий тег в форуме по статусу."""
        if not hasattr(forum, "available_tags") or not forum.available_tags:
            return None

        status_tag_map = {
            "cadet": ["курсант", "академия", "авнг", "ученик"],
            "active": ["сотрудник", "действующий", "в строю", "офицер", "личный состав"],
            "vacation": ["отпуск", "в отпуске"],
            "fired": ["уволен", "архив", "бывший"],
            "failed": ["не сдал", "отчислен", "архив"],
        }
        keywords = status_tag_map.get(status_key, [])
        for tag in forum.available_tags:
            tname = tag.name.lower()
            if any(kw in tname for kw in keywords):
                return tag
        return None

    @classmethod
    async def get_or_create_dossier_thread(
        cls,
        bot,
        guild: discord.Guild,
        discord_id: str,
        game_name: Optional[str] = None,
        static_id: Optional[str] = None,
        military_id: Optional[str] = None,
    ) -> Optional[discord.Thread]:
        """Получает или создаёт ветку (тред) в канале-форуме для сотрудника."""
        forum_ch_id = bot.config["channels"].get("dossier_forum", 0)
        if not forum_ch_id:
            return None

        forum = guild.get_channel(forum_ch_id)
        if not isinstance(forum, discord.ForumChannel):
            try:
                forum = await bot.fetch_channel(forum_ch_id)
            except Exception:
                forum = None

        if not isinstance(forum, discord.ForumChannel):
            logger.warning(f"Канал dossier_forum (ID {forum_ch_id}) не является ForumChannel!")
            return None

        member_data = await bot.db.get_member(discord_id)
        if not member_data:
            return None

        # Проверяем, есть ли уже ветка
        thread_id = member_data.get("dossier_thread_id")
        thread: Optional[discord.Thread] = None

        if thread_id:
            try:
                thread = guild.get_thread(int(thread_id))
                if not thread:
                    thread = await bot.fetch_channel(int(thread_id))
            except Exception:
                thread = None

        if thread:
            return thread

        # Присваиваем номер дела, если ещё не присвоен
        case_num = member_data.get("case_number")
        if not case_num:
            case_num = await bot.db.get_next_case_number()
            await bot.db.update_member(discord_id, case_number=case_num)
            member_data["case_number"] = case_num

        # Обновляем статик и военный билет если переданы
        updates = {}
        if static_id and static_id != "—" and not member_data.get("static_id"):
            updates["static_id"] = static_id
            member_data["static_id"] = static_id
        if military_id and military_id != "—" and not member_data.get("military_id"):
            updates["military_id"] = military_id
            member_data["military_id"] = military_id
        if updates:
            await bot.db.update_member(discord_id, **updates)

        # Собираем данные для карточки
        discord_member = guild.get_member(int(discord_id))
        promotions = await bot.db.get_member_promotions(discord_id)
        bonuses = await bot.db.get_member_bonuses(discord_id)
        reprimands = await bot.db.get_member_reprimands(discord_id)
        report_count = await bot.db.count_work_reports(discord_id)

        card_embed = forum_dossier_embed(
            member_data=member_data,
            discord_member=discord_member,
            promotions=promotions,
            bonuses=bonuses,
            reprimands=reprimands,
            report_count=report_count,
        )

        display_name = game_name or member_data.get("game_name") or (discord_member.display_name if discord_member else "Сотрудник")
        cur_static = member_data.get("static_id") or static_id or "—"
        thread_title = f"[ЛД-{case_num:04d}] {display_name} | {cur_static}"[:100]

        applied_tags = []
        tag = cls._find_matching_tag(forum, member_data.get("status", "cadet"))
        if tag:
            applied_tags.append(tag)

        try:
            thread_with_msg = await forum.create_thread(
                name=thread_title,
                embed=card_embed,
                applied_tags=applied_tags,
                reason=f"Создание личного дела для {display_name}",
            )
            created_thread = thread_with_msg.thread
            created_msg = thread_with_msg.message

            await bot.db.update_member(
                discord_id,
                dossier_thread_id=str(created_thread.id),
                dossier_message_id=str(created_msg.id) if created_msg else str(created_thread.id),
            )
            logger.info(f"Создано личное дело [ЛД-{case_num:04d}] для {discord_id} в ветке {created_thread.id}")
            return created_thread
        except Exception as e:
            logger.error(f"Ошибка при создании ветки форума для {discord_id}: {e}", exc_info=True)
            return None

    @classmethod
    async def update_dossier_card(cls, bot, guild: discord.Guild, discord_id: str) -> None:
        """Обновляет главную карточку личного дела и заголовок/теги ветки форума."""
        member_data = await bot.db.get_member(discord_id)
        if not member_data:
            return

        thread_id = member_data.get("dossier_thread_id")
        if not thread_id:
            # Если ветки ещё нет, пробуем создать
            await cls.get_or_create_dossier_thread(bot, guild, discord_id)
            return

        try:
            thread = guild.get_thread(int(thread_id))
            if not thread:
                thread = await bot.fetch_channel(int(thread_id))
        except Exception:
            thread = None

        if not thread or not isinstance(thread, discord.Thread):
            return

        discord_member = guild.get_member(int(discord_id))
        promotions = await bot.db.get_member_promotions(discord_id)
        bonuses = await bot.db.get_member_bonuses(discord_id)
        reprimands = await bot.db.get_member_reprimands(discord_id)
        report_count = await bot.db.count_work_reports(discord_id)

        card_embed = forum_dossier_embed(
            member_data=member_data,
            discord_member=discord_member,
            promotions=promotions,
            bonuses=bonuses,
            reprimands=reprimands,
            report_count=report_count,
        )

        # Редактируем стартовое сообщение
        msg_id = member_data.get("dossier_message_id")
        if msg_id:
            try:
                starter_msg = await thread.fetch_message(int(msg_id))
                if starter_msg:
                    await starter_msg.edit(embed=card_embed)
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение {msg_id} в треде {thread_id}: {e}")

        # Обновляем тег и заголовок ветки при необходимости
        case_num = member_data.get("case_number") or 1
        status_key = member_data.get("status", "cadet")
        display_name = member_data.get("game_name") or (discord_member.display_name if discord_member else "Сотрудник")
        static_id = member_data.get("static_id") or "—"

        status_prefix = ""
        if status_key == "fired":
            status_prefix = "[АРХИВ] "
        elif status_key == "vacation":
            status_prefix = "[ОТПУСК] "

        new_title = f"{status_prefix}[ЛД-{case_num:04d}] {display_name} | {static_id}"[:100]

        thread_edits = {}
        if thread.name != new_title:
            thread_edits["name"] = new_title

        parent = thread.parent
        if isinstance(parent, discord.ForumChannel) and parent.available_tags:
            tag = cls._find_matching_tag(parent, status_key)
            if tag and tag not in thread.applied_tags:
                thread_edits["applied_tags"] = [tag]

        if status_key == "fired" and not thread.archived:
            thread_edits["archived"] = True
            thread_edits["locked"] = True

        if thread_edits:
            try:
                await thread.edit(**thread_edits)
            except Exception as e:
                logger.warning(f"Не удалось обновить параметры треда {thread.id}: {e}")

    @classmethod
    async def log_event(
        cls,
        bot,
        guild: discord.Guild,
        discord_id: str,
        title: str,
        description: str,
        color: int = COLORS["info"],
        fields: Optional[List[tuple]] = None,
        author: Optional[discord.Member] = None,
    ) -> None:
        """Публикует запись о событии в ветку личного дела сотрудника и обновляет карточку."""
        thread = await cls.get_or_create_dossier_thread(bot, guild, discord_id)
        if thread:
            try:
                if thread.archived:
                    await thread.edit(archived=False)

                embed = dossier_event_embed(
                    title=title,
                    description=description,
                    color=color,
                    fields=fields,
                    author=author,
                )
                await thread.send(embed=embed)
            except Exception as e:
                logger.warning(f"Не удалось отправить лог-событие в личное дело {discord_id}: {e}")

        # Обновляем главную карточку
        await cls.update_dossier_card(bot, guild, discord_id)
