"""
Constants — Звания, статусы и другие константы
"""

# Список всех званий по порядку
RANKS = [
    {"id": 0,  "name": "Кандидат",          "prefix": "[КАН]",    "role_key": "candidate"},
    {"id": 1,  "name": "Курсант АВНГ",       "prefix": "[КУР]",    "role_key": "cadet"},
    {"id": 2,  "name": "Рядовой",            "prefix": "[РД]",     "role_key": "private"},
    {"id": 3,  "name": "Младший сержант",    "prefix": "[МЛ.СРЖ]", "role_key": "jr_sergeant"},
    {"id": 4,  "name": "Сержант",            "prefix": "[СРЖ]",    "role_key": "sergeant"},
    {"id": 5,  "name": "Старший сержант",    "prefix": "[СТ.СРЖ]", "role_key": "sr_sergeant"},
    {"id": 6,  "name": "Старшина",           "prefix": "[СТШ]",    "role_key": "sergeant_major"},
    {"id": 7,  "name": "Прапорщик",          "prefix": "[ПРП]",    "role_key": "warrant"},
    {"id": 8,  "name": "Старший прапорщик",  "prefix": "[СТ.ПРП]", "role_key": "sr_warrant"},
    {"id": 9,  "name": "Младший лейтенант",  "prefix": "[МЛ.ЛНТ]", "role_key": "jr_lieutenant"},
    {"id": 10, "name": "Лейтенант",          "prefix": "[ЛНТ]",    "role_key": "lieutenant"},
    {"id": 11, "name": "Старший лейтенант",  "prefix": "[СТ.ЛНТ]", "role_key": "sr_lieutenant"},
    {"id": 12, "name": "Капитан",            "prefix": "[КПТ]",    "role_key": "captain"},
    {"id": 13, "name": "Майор",              "prefix": "[МЙР]",    "role_key": "major"},
    {"id": 14, "name": "Подполковник",       "prefix": "[ПДП]",    "role_key": "lt_colonel"},
    {"id": 15, "name": "Полковник",          "prefix": "[ПЛК]",    "role_key": "colonel"},
    {"id": 16, "name": "Генерал-Майор",      "prefix": "[ГН.МЙР]", "role_key": "general_major"},
]

# Словари для быстрого доступа
RANK_BY_ID   = {r["id"]: r for r in RANKS}
RANK_BY_NAME = {r["name"]: r for r in RANKS}

# Статусы
STATUSES = {
    "candidate": "🔵 Кандидат",
    "cadet":     "🟡 Обучение в Академии",
    "active":    "🟢 В строю",
    "failed":    "🔴 Отчислен из академии",
    "fired":     "⚫ В архиве (Уволен)",
    "vacation":  "🟠 В отпуске",
}

# Типы рапортов
REPORT_TYPES = {
    "promotion":  "📈 На повышение",
    "fire":       "📋 На увольнение",
    "self_fire":  "🚪 Самоотвод",
    "reprimand":  "⚠️ Взыскание",
    "work":       "📝 О работе",
}

# Типы взысканий
REPRIMAND_TYPES = {
    "warning":          "⚠️ Предупреждение",
    "reprimand":        "🔴 Выговор",
    "severe_reprimand": "🟥 Строгий выговор",
}

# Цвета для embed'ов
COLORS = {
    "success":  0x2ECC71,
    "error":    0xE74C3C,
    "info":     0x3498DB,
    "warning":  0xF39C12,
    "gold":     0xF1C40F,
    "dark":     0x2C3E50,
    "rosguard": 0x1A237E,  # Тёмно-синий — цвет Росгвардии
}

MAX_TEST_ATTEMPTS = 3


def build_nickname(game_name: str, position_prefix: str = "") -> str:
    """
    Формирует никнейм пользователя.
    Если есть должность — «Нач.АВНГ | Алексей Накамура»
    Если нет — просто «Алексей Накамура»
    Discord ограничивает ник до 32 символов.
    """
    if position_prefix:
        nick = f"{position_prefix} | {game_name}"
    else:
        nick = game_name
    return nick[:32]  # Лимит Discord
