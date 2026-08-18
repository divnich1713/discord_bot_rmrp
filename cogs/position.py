"""
Position — Назначение должности и управление никнеймами
Формат ника: «Нач.АВНГ | Алексей Накамура» или «Алексей Накамура»
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import commander_only
from utils.constants import build_nickname


class PositionCog(commands.Cog, name="Должности"):
    def __init__(self, bot):
        self.bot = bot

    def _build_choices(self) -> list[app_commands.Choice]:
        """Генерирует список должностей из config['position_prefixes']"""
        choices = []
        prefixes = self.bot.config.get("position_prefixes", {})
        for key, value in prefixes.items():
            if key.startswith("_"):
                continue  # Пропускаем комментарии
            label = f"{value} [{key}]" if value else f"[без префикса] [{key}]"
            choices.append(app_commands.Choice(name=label[:100], value=key))
        return choices[:25]  # Discord ограничивает 25 вариантами

    @app_commands.command(name="должность", description="🏷️ Назначить/изменить должность и обновить ник")
    @app_commands.describe(
        участник="Кому назначить должность",
        должность="Ключ должности из конфига (например: nach_avng)",
        сброс="Сбросить должность (оставить только ФИО)",
    )
    @commander_only()
    async def set_position(self, interaction: discord.Interaction,
                            участник: discord.Member,
                            должность: str = "",
                            сброс: bool = False):
        await interaction.response.defer(ephemeral=True)

        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data:
            await interaction.followup.send("❌ Участник не найден в базе данных!", ephemeral=True)
            return

        config = self.bot.config
        prefixes = config.get("position_prefixes", {})

        if сброс:
            prefix = ""
        elif должность:
            # Поиск по ключу
            if должность in prefixes and not должность.startswith("_"):
                prefix = prefixes[должность]
            else:
                # Попытка найти по аббревиатуре (если пользователь ввёл «Нач.АВНГ»)
                match = next((v for k, v in prefixes.items()
                              if not k.startswith("_") and v == должность), None)
                if match is not None:
                    prefix = match
                else:
                    prefix = должность  # Свободный текст
        else:
            await interaction.followup.send(
                "❌ Укажите `должность` или `сброс=True`.", ephemeral=True
            )
            return

        # Сохраняем в БД
        await self.bot.db.update_member(str(участник.id), position_prefix=prefix)

        # Обновляем никнейм
        game_name = member_data["game_name"]
        new_nick = build_nickname(game_name, prefix)
        try:
            await участник.edit(nick=new_nick)
        except discord.Forbidden:
            await interaction.followup.send(
                f"⚠️ Должность сохранена, но не могу изменить ник (нет прав).\n"
                f"Установи вручную: `{new_nick}`",
                ephemeral=True,
            )
            return

        if prefix:
            await interaction.followup.send(
                f"✅ Должность назначена!\n"
                f"**Ник:** `{new_nick}`\n"
                f"**Должность:** `{prefix}`",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"✅ Должность сброшена.\n**Ник:** `{game_name}`",
                ephemeral=True,
            )

    @app_commands.command(name="ник", description="✏️ Изменить ФИО персонажа (ник обновится автоматически)")
    @app_commands.describe(
        участник="Кому изменить ФИО",
        фио="Новое ФИО персонажа (например: Алексей Накамура)",
    )
    @commander_only()
    async def change_name(self, interaction: discord.Interaction,
                           участник: discord.Member,
                           фио: str):
        await interaction.response.defer(ephemeral=True)

        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data:
            await interaction.followup.send("❌ Участник не найден в базе данных!", ephemeral=True)
            return

        await self.bot.db.update_member(str(участник.id), game_name=фио)

        prefix = member_data.get("position_prefix", "")
        new_nick = build_nickname(фио, prefix)

        try:
            await участник.edit(nick=new_nick)
        except discord.Forbidden:
            pass

        await interaction.followup.send(
            f"✅ ФИО изменено!\n**Новый ник:** `{new_nick}`",
            ephemeral=True,
        )

    @app_commands.command(name="список-должностей", description="📋 Все доступные аббревиатуры должностей")
    async def list_positions(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        prefixes = self.bot.config.get("position_prefixes", {})
        lines = []
        for key, value in prefixes.items():
            if key.startswith("_"):
                cat = value.replace("──", "").strip()
                lines.append(f"\n**{cat}**")
            else:
                display = f"`{value}`" if value else "_без префикса_"
                lines.append(f"  `{key}` → {display}")

        e = discord.Embed(
            title="📋 Должности и аббревиатуры",
            description=(
                "Используй `/должность @user должность:<ключ>` для назначения.\n"
                "Например: `/должность @user должность:nach_avng`\n\n"
                + "\n".join(lines)
            ),
            color=0x1A237E,
        )
        e.set_footer(text="Формат ника: Должность | Имя Фамилия")
        await interaction.followup.send(embed=e, ephemeral=True)


async def setup(bot):
    await bot.add_cog(PositionCog(bot))
