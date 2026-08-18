"""
Checks — Проверки прав пользователей
Поддерживает списки ролей в config: commander_roles, instructor_roles
"""
from typing import List

import discord
from discord import app_commands

from utils.constants import RANKS


def _get_role_ids(interaction: discord.Interaction, key: str) -> List[int]:
    """Возвращает список ID ролей из конфига (поддерживает и int и list)"""
    config = interaction.client.config
    value = config["roles"].get(key, 0)
    if isinstance(value, list):
        return [v for v in value if v]
    elif isinstance(value, int) and value:
        return [value]
    return []


def _has_any_role(interaction: discord.Interaction, role_ids: List[int]) -> bool:
    """Проверяет наличие хотя бы одной из ролей"""
    if not role_ids:
        return False
    user_role_ids = {r.id for r in interaction.user.roles}
    return bool(user_role_ids & set(role_ids))


def is_commander(interaction: discord.Interaction) -> bool:
    """
    Командир — может одобрять рапорты и заявки.
    Настраивается через config.roles.commander_roles (список ID).
    Администраторы сервера всегда имеют доступ.
    """
    if interaction.user.guild_permissions.administrator:
        return True
    role_ids = _get_role_ids(interaction, "commander_roles")
    return _has_any_role(interaction, role_ids)


def is_instructor(interaction: discord.Interaction) -> bool:
    """
    Инструктор АВНГ — управляет академией, тестами, практикой.
    Настраивается через config.roles.instructor_roles.
    Командиры также имеют права инструктора.
    """
    if is_commander(interaction):
        return True
    role_ids = _get_role_ids(interaction, "instructor_roles")
    return _has_any_role(interaction, role_ids)


def is_officer(interaction: discord.Interaction) -> bool:
    """
    Офицер — может писать рапорты на других, выдавать премии.
    Минимальный ранг задаётся в config.roles.officer_min_rank.
    """
    if is_commander(interaction):
        return True
    config = interaction.client.config
    min_rank = config["roles"].get("officer_min_rank", 9)
    # Проверяем по ролям всех рангов >= min_rank
    role_keys = [r["role_key"] for r in RANKS if r["id"] >= min_rank]
    for key in role_keys:
        ids = _get_role_ids(interaction, key)
        if _has_any_role(interaction, ids):
            return True
    return False


def is_member_of_faction(interaction: discord.Interaction) -> bool:
    """Любой сотрудник фракции"""
    if is_commander(interaction):
        return True
    faction_keys = [
        "cadet", "private", "jr_sergeant", "sergeant", "sr_sergeant",
        "sergeant_major", "warrant", "sr_warrant", "jr_lieutenant",
        "lieutenant", "sr_lieutenant", "captain", "major",
        "lt_colonel", "colonel", "general_major",
        "sotrudnik_fsvng",
    ]
    for key in faction_keys:
        ids = _get_role_ids(interaction, key)
        if _has_any_role(interaction, ids):
            return True
    return False


# ─── Декораторы для slash-команд ───

def commander_only():
    def predicate(interaction: discord.Interaction) -> bool:
        if not is_commander(interaction):
            raise app_commands.CheckFailure(
                "❌ Только командиры могут использовать эту команду!"
            )
        return True
    return app_commands.check(predicate)


def instructor_only():
    def predicate(interaction: discord.Interaction) -> bool:
        if not is_instructor(interaction):
            raise app_commands.CheckFailure(
                "❌ Только инструкторы АВНГ могут использовать эту команду!"
            )
        return True
    return app_commands.check(predicate)


def officer_only():
    def predicate(interaction: discord.Interaction) -> bool:
        if not is_officer(interaction):
            raise app_commands.CheckFailure(
                "❌ Только офицеры могут использовать эту команду!"
            )
        return True
    return app_commands.check(predicate)


def faction_member_only():
    def predicate(interaction: discord.Interaction) -> bool:
        if not is_member_of_faction(interaction):
            raise app_commands.CheckFailure(
                "❌ Только члены Росгвардии могут использовать эту команду!"
            )
        return True
    return app_commands.check(predicate)


def is_senior_staff(interaction: discord.Interaction) -> bool:
    """
    Старший состав и руководство (Нач., Зам. Нач., Старший состав).
    Администраторы и командиры всегда имеют доступ.
    """
    if is_commander(interaction):
        return True
    senior_keys = [
        "nach_ufsvng", "zam1_ufsvng", "zam_ufsvng", "pomoshnik_ufsvng",
        "starshiy_sostav_ufsvng",
        "komandír_sobr", "zam_komandira_sobr",
        "komandír_omon", "zam_komandira_omon",
        "nach_avng", "zam_nach_avng",
        "nach_uvo", "zam_nach_uvo",
        "nach_usb", "zam_nach_usb",
    ]
    for key in senior_keys:
        ids = _get_role_ids(interaction, key)
        if _has_any_role(interaction, ids):
            return True
    return False


def senior_staff_only():
    def predicate(interaction: discord.Interaction) -> bool:
        if not is_senior_staff(interaction):
            raise app_commands.CheckFailure(
                "❌ Только старший состав и руководство (Нач., Зам. Нач., Ст. Состав) могут подавать рапорты на выговоры!"
            )
        return True
    return app_commands.check(predicate)
