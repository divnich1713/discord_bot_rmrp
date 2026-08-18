"""
Embeds — Красивые embed'ы для всех сообщений бота
"""
from datetime import datetime
from typing import Dict, List, Optional

import discord

from utils.constants import (COLORS, RANK_BY_ID, RANKS, REPRIMAND_TYPES,
                              REPORT_TYPES, STATUSES)


def _now_str() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")


def _rank_name(rank_id: int) -> str:
    r = RANK_BY_ID.get(rank_id)
    return r["name"] if r else "Неизвестно"


# ─────────────────────────── ЗАЯВКИ ───────────────────────────

def application_embed(member: discord.Member, app_id: int, game_name: str,
                       age: str, reason: str, experience: str) -> discord.Embed:
    e = discord.Embed(
        title="📋 Заявка на вступление в Росгвардию",
        color=COLORS["rosguard"],
        timestamp=datetime.utcnow(),
    )
    e.set_author(name=str(member), icon_url=member.display_avatar.url)
    e.add_field(name="🎮 Никнейм в игре", value=game_name, inline=True)
    e.add_field(name="🎂 Возраст персонажа", value=age, inline=True)
    e.add_field(name="📌 Discord", value=member.mention, inline=True)
    e.add_field(name="💬 Причина вступления", value=reason, inline=False)
    e.add_field(name="🏅 Предыдущий опыт", value=experience or "Нет", inline=False)
    e.set_footer(text=f"ID заявки: #{app_id} • {_now_str()}")
    return e


def application_approved_embed(game_name: str, reviewer: discord.Member) -> discord.Embed:
    e = discord.Embed(
        title="✅ Вы приняты в Росгвардию!",
        description=(
            f"Поздравляем, **{game_name}**!\n\n"
            "Вы зачислены в **Академию АВНГ** в звании **Курсант**.\n"
            "У вас есть **7 дней** на прохождение обучения.\n\n"
            "📚 Пройдите все назначенные тесты и практические задания.\n"
            "❓ По вопросам обращайтесь к вашему инструктору."
        ),
        color=COLORS["success"],
        timestamp=datetime.utcnow(),
    )
    e.add_field(name="Одобрил", value=reviewer.mention)
    e.set_thumbnail(url="https://i.imgur.com/RKOwrPQ.png")
    return e


def application_rejected_embed(game_name: str, reviewer: discord.Member,
                                 reason: str = None) -> discord.Embed:
    e = discord.Embed(
        title="❌ Заявка отклонена",
        description=(
            f"К сожалению, **{game_name}**, ваша заявка была отклонена.\n"
            + (f"\n📝 **Причина:** {reason}" if reason else "")
        ),
        color=COLORS["error"],
        timestamp=datetime.utcnow(),
    )
    e.add_field(name="Отклонил", value=reviewer.mention)
    return e


# ─────────────────────────── АКАДЕМИЯ ───────────────────────────

def cadet_list_embed(cadets: List[Dict], guild: discord.Guild) -> discord.Embed:
    e = discord.Embed(
        title="🎓 Список курсантов Академии АВНГ",
        color=COLORS["rosguard"],
        timestamp=datetime.utcnow(),
    )
    if not cadets:
        e.description = "_Нет активных курсантов_"
        return e

    lines = []
    for i, c in enumerate(cadets, 1):
        member = guild.get_member(int(c["discord_id"]))
        mention = member.mention if member else f"<@{c['discord_id']}>"
        joined = c.get("joined_academy", "—")
        if joined and joined != "—":
            try:
                dt = datetime.fromisoformat(joined)
                days = (datetime.utcnow() - dt).days
                joined = f"{dt.strftime('%d.%m.%Y')} ({days} д.)"
            except Exception:
                pass
        lines.append(f"`{i}.` {mention} — **{c['game_name']}** | Зачислен: {joined}")

    e.description = "\n".join(lines)
    e.set_footer(text=f"Всего курсантов: {len(cadets)}")
    return e


def academy_deadline_reminder_embed(days_left: int) -> discord.Embed:
    e = discord.Embed(
        title="⏰ Напоминание об окончании срока в академии",
        description=(
            f"Вам осталось **{days_left} {'день' if days_left == 1 else 'дней'}** "
            "до окончания срока обучения в Академии АВНГ.\n\n"
            "⚠️ Убедитесь, что вы прошли все тесты и практические задания!\n"
            "Обратитесь к вашему инструктору за помощью."
        ),
        color=COLORS["warning"],
    )
    return e


def academy_failed_embed(game_name: str) -> discord.Embed:
    e = discord.Embed(
        title="❌ Срок обучения истёк",
        description=(
            f"**{game_name}**, к сожалению, срок вашего обучения в Академии АВНГ истёк.\n\n"
            "Статус изменён на **Не прошёл академию АВНГ**.\n"
            "Для повторного поступления обратитесь к командованию."
        ),
        color=COLORS["error"],
    )
    return e


def task_list_embed(tasks: List[Dict], tests: List[Dict],
                    test_attempts: Dict, member_name: str) -> discord.Embed:
    e = discord.Embed(
        title=f"📋 Задания курсанта: {member_name}",
        color=COLORS["info"],
        timestamp=datetime.utcnow(),
    )

    # Практические задания
    if tasks:
        prac_lines = []
        for t in tasks:
            status = "✅" if t["completed"] else "⏳"
            prac_lines.append(f"{status} `#{t['id']}` **{t['title']}**")
            if t["description"]:
                prac_lines.append(f"    _{t['description']}_")
        e.add_field(name="🛠️ Практические задания", value="\n".join(prac_lines), inline=False)
    else:
        e.add_field(name="🛠️ Практические задания", value="_Не назначено_", inline=False)

    # Тесты
    if tests:
        test_lines = []
        for t in tests:
            attempts = test_attempts.get(t["test_id"], [])
            passed = any(a["passed"] for a in attempts)
            count = len(attempts)
            if passed:
                status = "✅"
            elif count >= 3:
                status = "🚫"
            else:
                status = f"⏳ ({count}/3)"
            test_lines.append(f"{status} `#{t['test_id']}` **{t['name']}** (порог: {t['pass_score']}%)")
        e.add_field(name="📝 Тесты", value="\n".join(test_lines), inline=False)
    else:
        e.add_field(name="📝 Тесты", value="_Не назначено_", inline=False)

    return e


# ─────────────────────────── ТЕСТЫ ───────────────────────────

def test_question_embed(test_name: str, q_num: int, total: int,
                         question: Dict) -> discord.Embed:
    e = discord.Embed(
        title=f"📝 {test_name}",
        description=f"**Вопрос {q_num}/{total}**\n\n{question['question']}",
        color=COLORS["info"],
    )
    e.add_field(name="🅐", value=question["option_a"], inline=True)
    e.add_field(name="🅑", value=question["option_b"], inline=True)
    e.add_field(name="\u200b", value="\u200b", inline=True)
    e.add_field(name="🅒", value=question["option_c"], inline=True)
    e.add_field(name="🅓", value=question["option_d"], inline=True)
    e.set_footer(text="Выберите правильный вариант ответа")
    return e


def test_result_embed(test_name: str, correct: int, total: int,
                       score: int, passed: bool, attempt_num: int,
                       remaining: int) -> discord.Embed:
    color = COLORS["success"] if passed else COLORS["error"]
    status_text = "✅ **Сдан!**" if passed else "❌ **Не сдан**"
    e = discord.Embed(
        title=f"📊 Результат теста: {test_name}",
        color=color,
        timestamp=datetime.utcnow(),
    )
    e.add_field(name="Статус", value=status_text, inline=True)
    e.add_field(name="Результат", value=f"**{score}%** ({correct}/{total})", inline=True)
    e.add_field(name="Попытка", value=f"{attempt_num}/3", inline=True)
    if not passed:
        if remaining > 0:
            e.add_field(
                name="ℹ️ Осталось попыток",
                value=f"**{remaining}** — используйте `/тест пройти` снова",
                inline=False,
            )
        else:
            e.add_field(
                name="🚫 Попытки исчерпаны",
                value="Обратитесь к инструктору для сброса попыток",
                inline=False,
            )
    return e


# ─────────────────────────── РАПОРТЫ ───────────────────────────

def report_embed(report_id: int, type_: str, author: discord.Member,
                  target: discord.Member, reason: str,
                  new_rank_id: int = None) -> discord.Embed:
    type_label = REPORT_TYPES.get(type_, type_)
    e = discord.Embed(
        title=f"{type_label} — Рапорт #{report_id}",
        color=COLORS["info"],
        timestamp=datetime.utcnow(),
    )
    e.add_field(name="📌 Заявитель", value=author.mention, inline=True)
    e.add_field(name="👤 На кого", value=target.mention, inline=True)
    if new_rank_id is not None:
        e.add_field(name="🎖️ Новое звание", value=_rank_name(new_rank_id), inline=True)
    e.add_field(name="📝 Причина / Обоснование", value=reason or "—", inline=False)
    e.set_footer(text=f"ID рапорта: #{report_id} • Ожидает решения командования")
def reprimand_report_embed(
    report_id: int,
    author: discord.Member,
    author_data: Optional[Dict],
    target: discord.Member,
    target_data: Optional[Dict],
    article: str,
    proof: str,
    punishment: str,
    task: str,
    punishment_role: Optional[discord.Role] = None,
) -> discord.Embed:
    """Генерирует embed для рапорта о дисциплинарном взыскании по образцу."""
    author_name = author_data.get("game_name", author.display_name) if author_data else author.display_name
    author_static = author_data.get("static_id", "—") if author_data else "—"

    target_name = target_data.get("game_name", target.display_name) if target_data else target.display_name
    target_static = target_data.get("static_id", "—") if target_data else "—"

    e = discord.Embed(
        title=f"📋 РАПОРТ О ДИСЦИПЛИНАРНОМ ВЗЫСКАНИИ #{report_id}",
        color=COLORS["warning"],
        timestamp=datetime.utcnow(),
    )
    e.add_field(
        name="1. Заявитель",
        value=f"{author_name} | `{author_static}` | {author.mention}",
        inline=False,
    )
    e.add_field(
        name="2. Нарушитель",
        value=f"{target_name} | `{target_static}` | {target.mention}",
        inline=False,
    )
    e.add_field(name="3. Нарушение / Пункт устава", value=f"**{article}**", inline=True)
    e.add_field(name="4. Доказательства", value=proof or "По запросу", inline=True)

    punish_str = punishment
    if punishment_role:
        punish_str += f" ({punishment_role.mention})"
    e.add_field(name="5. Мера наказания", value=punish_str, inline=True)
    e.add_field(name="6. Отработка для снятия", value=f"```\n{task}\n```", inline=False)
    e.set_footer(text=f"ID рапорта: #{report_id} • 🔴 Взыскание вступило в силу • Выдал: {author.display_name}")
    return e


def report_decision_embed(report_id: int, type_: str, approved: bool,
                           reviewer: discord.Member) -> discord.Embed:
    status = "✅ Одобрен" if approved else "❌ Отклонён"
    color = COLORS["success"] if approved else COLORS["error"]
    e = discord.Embed(
        title=f"Рапорт #{report_id} — {status}",
        color=color,
        timestamp=datetime.utcnow(),
    )
    e.add_field(name="Решение принял", value=reviewer.mention)
    return e


# ─────────────────────────── ПОВЫШЕНИЯ ───────────────────────────

def promotion_embed(member: discord.Member, from_rank: int,
                     to_rank: int, approved_by: discord.Member) -> discord.Embed:
    e = discord.Embed(
        title="🎖️ Повышение в звании!",
        description=(
            f"Поздравляем, {member.mention}!\n"
            f"Вы повышены с **{_rank_name(from_rank)}** до **{_rank_name(to_rank)}**!"
        ),
        color=COLORS["gold"],
        timestamp=datetime.utcnow(),
    )
    e.add_field(name="Подписал", value=approved_by.mention)
    e.set_thumbnail(url=member.display_avatar.url)
    return e


# ─────────────────────────── ЛИЧНОЕ ДЕЛО ───────────────────────────

def dossier_embed(member_data: Dict, discord_member: Optional[discord.Member],
                   promotions: List[Dict], bonuses: List[Dict],
                   reprimands: List[Dict], report_count: int,
                   roles_cfg: Optional[Dict] = None) -> discord.Embed:
    from utils.dossier_service import resolve_member_rank
    rank = resolve_member_rank(roles_cfg, discord_member, member_data)
    status_key = member_data.get("status", "cadet")
    status_label = STATUSES.get(status_key, status_key)

    e = discord.Embed(
        title=f"📁 Личное дело — {member_data['game_name']}",
        color=COLORS["rosguard"],
        timestamp=datetime.utcnow(),
    )

    if discord_member:
        e.set_thumbnail(url=discord_member.display_avatar.url)

    # Основная информация
    mention = discord_member.mention if discord_member else f"<@{member_data['discord_id']}>"
    e.add_field(name="👤 Discord", value=mention, inline=True)
    e.add_field(name="🎖️ Звание", value=rank['name'], inline=True)
    e.add_field(name="📊 Статус", value=status_label, inline=True)

    # Даты
    joined_academy = member_data.get("joined_academy")
    joined_faction = member_data.get("joined_faction")
    if joined_academy:
        try:
            dt = datetime.fromisoformat(joined_academy)
            e.add_field(name="📅 В академии с", value=dt.strftime("%d.%m.%Y"), inline=True)
        except Exception:
            pass
    if joined_faction:
        try:
            dt = datetime.fromisoformat(joined_faction)
            e.add_field(name="📅 Во фракции с", value=dt.strftime("%d.%m.%Y"), inline=True)
        except Exception:
            pass

    e.add_field(name="📝 Отчётов о работе", value=str(report_count), inline=True)

    # Повышения (последние 3)
    if promotions:
        promo_lines = []
        for p in promotions[-3:]:
            try:
                dt = datetime.fromisoformat(p["date"]).strftime("%d.%m")
            except Exception:
                dt = "—"
            promo_lines.append(
                f"`{dt}` {_rank_name(p['from_rank'])} → **{_rank_name(p['to_rank'])}**"
            )
        e.add_field(
            name=f"📈 История повышений ({len(promotions)} всего)",
            value="\n".join(promo_lines),
            inline=False,
        )

    # Премии (последние 5)
    if bonuses:
        bonus_lines = []
        for b in bonuses[:5]:
            try:
                dt = datetime.fromisoformat(b["date"]).strftime("%d.%m")
            except Exception:
                dt = "—"
            bonus_lines.append(f"`{dt}` — {b['reason']}")
        e.add_field(
            name=f"⭐ Премии ({len(bonuses)} всего)",
            value="\n".join(bonus_lines),
            inline=False,
        )

    # Взыскания
    if reprimands:
        rep_lines = []
        for r in reprimands[:3]:
            try:
                dt = datetime.fromisoformat(r["date"]).strftime("%d.%m")
            except Exception:
                dt = "—"
            type_label = REPRIMAND_TYPES.get(r["type"], r["type"])
            rep_lines.append(f"`{dt}` {type_label} — {r['reason']}")
        e.add_field(
            name=f"⚠️ Взыскания ({len(reprimands)} всего)",
            value="\n".join(rep_lines),
            inline=False,
        )

    e.set_footer(text=f"ID: {member_data['discord_id']}")
    return e


# ─────────────────────────── ПРЕМИИ ───────────────────────────

def bonus_embed(member: discord.Member, reason: str,
                given_by: discord.Member, bonus_id: int) -> discord.Embed:
    e = discord.Embed(
        title="⭐ Выдана премия!",
        description=f"{member.mention} получает премию!",
        color=COLORS["gold"],
        timestamp=datetime.utcnow(),
    )
    e.add_field(name="📝 За что", value=reason, inline=False)
    e.add_field(name="🏅 Выдал", value=given_by.mention, inline=True)
    e.set_footer(text=f"ID премии: #{bonus_id}")
    return e


# ─────────────────────────── ОТЧЁТЫ О РАБОТЕ ───────────────────────────

def work_report_embed(member: discord.Member, content: str, report_id: int) -> discord.Embed:
    e = discord.Embed(
        title="📝 Отчёт о проделанной работе",
        description=content,
        color=COLORS["info"],
        timestamp=datetime.utcnow(),
    )
    e.set_author(name=str(member), icon_url=member.display_avatar.url)
    e.set_footer(text=f"ID отчёта: #{report_id}")
    return e


# ─────────────────────────── ТОП ───────────────────────────

def top_embed(title: str, rows: List[Dict], value_key: str,
               value_label: str, guild: discord.Guild) -> discord.Embed:
    e = discord.Embed(title=title, color=COLORS["gold"], timestamp=datetime.utcnow())
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"`{i+1}.`"
        member = guild.get_member(int(row["discord_id"]))
        name = member.mention if member else row.get("game_name", "Неизвестно")
        rank = _rank_name(row.get("rank_id", 0))
        value = row.get(value_key, 0)
        lines.append(f"{medal} {name} — {rank} | **{value}** {value_label}")
    e.description = "\n".join(lines) if lines else "_Нет данных_"
    return e


# ─────────────────────────── СОСТАВ ───────────────────────────

def roster_embed(members: List[Dict], guild: discord.Guild) -> discord.Embed:
    e = discord.Embed(
        title="⚔️ Личный состав Росгвардии",
        color=COLORS["rosguard"],
        timestamp=datetime.utcnow(),
    )
    # Группировка по званиям
    by_rank: Dict[int, List] = {}
    for m in members:
        rid = m.get("rank_id", 0)
        by_rank.setdefault(rid, []).append(m)

    for rank_id in sorted(by_rank.keys(), reverse=True):
        rank = RANK_BY_ID.get(rank_id, RANKS[0])
        members_in_rank = by_rank[rank_id]
        lines = []
        for m in members_in_rank:
            gm = guild.get_member(int(m["discord_id"]))
            lines.append(gm.mention if gm else m["game_name"])
        e.add_field(
            name=f"{rank['name']} ({len(members_in_rank)})",
            value=", ".join(lines) or "—",
            inline=False,
        )

    e.set_footer(text=f"Всего в составе: {len(members)}")
    return e
