"""
Dossier — Личное дело и статистика личного состава
"""
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import dossier_embed, roster_embed, top_embed


class DossierCog(commands.Cog, name="Личные дела"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="досье", description="📁 Личное дело сотрудника")
    @app_commands.describe(участник="Чьё дело показать (по умолчанию ваше)")
    async def dossier(self, interaction: discord.Interaction,
                       участник: discord.Member = None):
        await interaction.response.defer(ephemeral=True)

        target = участник or interaction.user
        member_data = await self.bot.db.get_member(str(target.id))
        if not member_data:
            await interaction.followup.send(
                "❌ Пользователь не найден в базе данных Росгвардии!", ephemeral=True
            )
            return

        # Параллельные запросы — в 4 раза быстрее чем последовательные
        promotions, bonuses, reprimands, report_count = await asyncio.gather(
            self.bot.db.get_member_promotions(str(target.id)),
            self.bot.db.get_member_bonuses(str(target.id)),
            self.bot.db.get_member_reprimands(str(target.id)),
            self.bot.db.count_work_reports(str(target.id)),
        )

        embed = dossier_embed(
            member_data, target, promotions, bonuses, reprimands, report_count,
            roles_cfg=self.bot.config.get("roles")
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="состав", description="⚔️ Полный список личного состава")
    async def roster(self, interaction: discord.Interaction):
        await interaction.response.defer()
        members = await self.bot.db.get_all_members()
        if not members:
            await interaction.followup.send("📭 Личный состав пуст.")
            return
        embed = roster_embed(members, interaction.guild)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="топ", description="🏆 Топ сотрудников")
    @app_commands.describe(
        категория="Категория рейтинга"
    )
    @app_commands.choices(категория=[
        app_commands.Choice(name="⭐ По премиям", value="bonuses"),
        app_commands.Choice(name="📝 По отчётам о работе", value="reports"),
    ])
    async def top(self, interaction: discord.Interaction,
                   категория: app_commands.Choice[str] = None):
        await interaction.response.defer()

        cat = категория.value if категория else "bonuses"
        guild = interaction.guild

        if cat == "bonuses":
            rows = await self.bot.db.get_top_bonuses(10)
            embed = top_embed("⭐ Топ по премиям", rows, "bonus_count", "премий", guild)
        else:
            rows = await self.bot.db.get_top_reports(10)
            embed = top_embed("📝 Топ по отчётам о работе", rows, "report_count", "отчётов", guild)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="мои-отчёты", description="📋 Мои отчёты о работе")
    async def my_reports(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        reports = await self.bot.db.get_work_reports(str(interaction.user.id), 5)
        if not reports:
            await interaction.followup.send("📭 У вас нет отчётов о работе.", ephemeral=True)
            return

        e = discord.Embed(
            title="📋 Ваши последние отчёты о работе",
            color=0x3498DB,
        )
        from datetime import datetime
        for r in reports:
            try:
                dt = datetime.fromisoformat(r["created_at"]).strftime("%d.%m.%Y %H:%M")
            except Exception:
                dt = "—"
            e.add_field(
                name=f"#{r['id']} | {dt}",
                value=r["content"][:200] + ("..." if len(r["content"]) > 200 else ""),
                inline=False,
            )
        count = await self.bot.db.count_work_reports(str(interaction.user.id))
        e.set_footer(text=f"Всего отчётов: {count}")
        await interaction.followup.send(embed=e, ephemeral=True)

    # ──────────────── АРХИВ ЛИЧНЫХ ДЕЛ (ФОРУМ) ────────────────

    archive_group = app_commands.Group(name="архив", description="📁 Управление Архивом Личных Дел")

    @archive_group.command(name="создать", description="📁 Завести личное дело сотрудника в форуме-архиве")
    @app_commands.describe(
        участник="Сотрудник для заведения дела",
        статик="Игровой статик (ID) (опционально)",
        военный_билет="Военный билет (да/нет) (опционально)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def archive_create(
        self,
        interaction: discord.Interaction,
        участник: discord.Member,
        статик: str = None,
        военный_билет: str = None,
    ):
        await interaction.response.defer(ephemeral=True)
        from utils.dossier_service import DossierService

        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data:
            # Создаём запись в БД если её не было
            await self.bot.db.add_member(str(участник.id), участник.display_name, str(interaction.user.id))
            member_data = await self.bot.db.get_member(str(участник.id))

        thread = await DossierService.get_or_create_dossier_thread(
            self.bot,
            interaction.guild,
            str(участник.id),
            game_name=member_data.get("game_name") or участник.display_name,
            static_id=статик,
            military_id=военный_билет,
        )

        if thread:
            await interaction.followup.send(
                f"✅ Личное дело для {участник.mention} открыто в ветке: {thread.mention}!",
                ephemeral=True,
            )
        else:
            forum_ch_id = self.bot.config["channels"].get("dossier_forum", 0)
            await interaction.followup.send(
                f"❌ Не удалось создать ветку. Проверьте настройку `dossier_forum` в config.json (текущий ID: `{forum_ch_id}`).",
                ephemeral=True,
            )

    @archive_group.command(name="обновить", description="🔄 Принудительно обновить карточку личного дела")
    @app_commands.describe(участник="Сотрудник")
    async def archive_update(self, interaction: discord.Interaction, участник: discord.Member):
        await interaction.response.defer(ephemeral=True)
        from utils.dossier_service import DossierService

        await DossierService.update_dossier_card(self.bot, interaction.guild, str(участник.id))
        await interaction.followup.send(f"✅ Карточка личного дела {участник.mention} обновлена!", ephemeral=True)

    @archive_group.command(name="заметка", description="📌 Добавить служебную характеристику / заметку в дело")
    @app_commands.describe(участник="Сотрудник", текст="Текст характеристики или заметки")
    async def archive_note(self, interaction: discord.Interaction, участник: discord.Member, текст: str):
        await interaction.response.defer(ephemeral=True)
        from utils.dossier_service import DossierService
        from utils.checks import is_officer

        if not is_officer(interaction):
            await interaction.followup.send("❌ Только офицеры и командиры могут оставлять служебные заметки!", ephemeral=True)
            return

        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data:
            await interaction.followup.send("❌ Сотрудник не найден в базе данных!", ephemeral=True)
            return

        from datetime import datetime
        dt_str = datetime.utcnow().strftime("%d.%m.%Y")
        existing_notes = member_data.get("notes") or ""
        new_note_entry = f"[{dt_str} • {interaction.user.display_name}]: {текст}"
        combined_notes = f"{existing_notes}\n{new_note_entry}".strip()

        await self.bot.db.update_member(str(участник.id), notes=combined_notes)

        # Логируем заметку в тред форума
        await DossierService.log_event(
            self.bot,
            interaction.guild,
            str(участник.id),
            title="📌 Служебная характеристика / Заметка",
            description=текст,
            color=0x3498DB,
            author=interaction.user,
        )

        await interaction.followup.send(f"✅ Служебная характеристика внесена в дело {участник.mention}!", ephemeral=True)

    @archive_group.command(name="поиск", description="🔍 Найти личное дело в архиве")
    @app_commands.describe(запрос="Номер дела (напр. 1), статик (123-123), Discord или ник")
    async def archive_search(self, interaction: discord.Interaction, запрос: str):
        await interaction.response.defer(ephemeral=True)
        query = запрос.strip().replace("#", "").replace("ЛД-", "").replace("лд-", "")

        member_data = None
        # Пробуем по номеру дела
        if query.isdigit():
            member_data = await self.bot.db.get_member_by_case_number(int(query))

        # Пробуем по статику
        if not member_data:
            member_data = await self.bot.db.get_member_by_static_id(query)

        # Пробуем по Discord ID или имени
        if not member_data:
            all_m = await self.bot.db.get_all_members()
            for m in all_m:
                if query.lower() in m.get("game_name", "").lower() or query in m.get("discord_id", ""):
                    member_data = m
                    break

        if not member_data:
            await interaction.followup.send(f"❌ Личное дело по запросу «{запрос}» не найдено.", ephemeral=True)
            return

        thread_id = member_data.get("dossier_thread_id")
        thread_mention = f"<#{thread_id}>" if thread_id else "_Ветка ещё не создана_"
        case_num = member_data.get("case_number") or "—"
        case_str = f"№{case_num:04d}" if isinstance(case_num, int) else f"№{case_num}"

        e = discord.Embed(
            title=f"📁 Найдено личное дело {case_str}",
            color=0x1A237E,
        )
        e.add_field(name="👤 ФИО", value=member_data.get("game_name", "—"), inline=True)
        e.add_field(name="🎮 Статик ID", value=member_data.get("static_id") or "—", inline=True)
        e.add_field(name="🏷️ Discord", value=f"<@{member_data['discord_id']}>", inline=True)
        e.add_field(name="📁 Ветка в форуме", value=thread_mention, inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    @archive_group.command(name="синхронизировать", description="⚡ Создать дела в форуме для всех членов фракции")
    @app_commands.checks.has_permissions(administrator=True)
    async def archive_sync_all(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        from utils.dossier_service import DossierService

        members = await self.bot.db.get_all_members()
        if not members:
            await interaction.followup.send("📭 В базе данных нет участников.", ephemeral=True)
            return

        created = 0
        updated = 0
        for m in members:
            did = m["discord_id"]
            if not m.get("dossier_thread_id"):
                t = await DossierService.get_or_create_dossier_thread(
                    self.bot, interaction.guild, did, game_name=m.get("game_name")
                )
                if t:
                    created += 1
            else:
                await DossierService.update_dossier_card(self.bot, interaction.guild, did)
                updated += 1
            await asyncio.sleep(0.5)  # Защита от Discord rate-limit

        await interaction.followup.send(
            f"✅ **Синхронизация архива завершена!**\n"
            f"• Создано новых дел: **{created}**\n"
            f"• Обновлено существующих: **{updated}**",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(DossierCog(bot))
