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

        embed = dossier_embed(member_data, target, promotions, bonuses, reprimands, report_count)
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


async def setup(bot):
    await bot.add_cog(DossierCog(bot))
