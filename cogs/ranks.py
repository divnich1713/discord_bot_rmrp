"""
Ranks — Прямое управление званиями (командиры)
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import commander_only
from utils.constants import RANK_BY_ID, RANKS
from utils.embeds import promotion_embed


def build_rank_choices():
    return [
        app_commands.Choice(name=r["name"], value=r["id"])
        for r in RANKS[2:]
    ]


class RanksCog(commands.Cog, name="Звания"):
    def __init__(self, bot):
        self.bot = bot

    async def _apply_rank(self, member: discord.Member, rank_id: int,
                           guild: discord.Guild):
        """Выдаёт нужную роль, убирает старые"""
        config = self.bot.config
        for r in RANKS:
            rid = config["roles"].get(r["role_key"], 0)
            if rid:
                role = guild.get_role(rid)
                if role and role in member.roles:
                    try:
                        await member.remove_roles(role)
                    except Exception:
                        pass
        rank = RANK_BY_ID.get(rank_id)
        if rank:
            new_role_id = config["roles"].get(rank["role_key"], 0)
            if new_role_id:
                new_role = guild.get_role(new_role_id)
                if new_role:
                    try:
                        await member.add_roles(new_role, reason=f"Звание: {rank['name']}")
                    except Exception:
                        pass
            try:
                m_data = await self.bot.db.get_member(str(member.id))
                game_name = m_data["game_name"] if m_data else member.display_name
                await member.edit(nick=game_name)  # Только ФИО, без рангового префикса
            except discord.Forbidden:
                pass

    @app_commands.command(name="повысить", description="⬆️ Повысить сотрудника в звании")
    @app_commands.describe(участник="Кого повысить", звание="Новое звание")
    @app_commands.choices(звание=build_rank_choices())
    @commander_only()
    async def promote(self, interaction: discord.Interaction,
                       участник: discord.Member,
                       звание: app_commands.Choice[int]):
        await interaction.response.defer(ephemeral=True)

        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data:
            await interaction.followup.send("❌ Пользователь не найден во фракции!", ephemeral=True)
            return

        old_rank = member_data["rank_id"]
        if звание.value <= old_rank:
            await interaction.followup.send(
                "❌ Новое звание должно быть выше текущего!", ephemeral=True
            )
            return

        await self.bot.db.update_member(str(участник.id), rank_id=звание.value, status="active")
        await self.bot.db.add_promotion(str(участник.id), old_rank, звание.value,
                                         str(interaction.user.id))
        await self._apply_rank(участник, звание.value, interaction.guild)

        # Анонс
        config = self.bot.config
        promotions_ch_id = config["channels"].get("promotions", 0)
        promotions_ch = interaction.guild.get_channel(promotions_ch_id)
        embed = promotion_embed(участник, old_rank, звание.value, interaction.user)
        if promotions_ch:
            await promotions_ch.send(embed=embed)

        # Лог в личное дело (Форум)
        try:
            from utils.dossier_service import DossierService
            from utils.constants import COLORS
            await DossierService.log_event(
                self.bot, interaction.guild, str(участник.id),
                title="📈 Присвоение очередного звания",
                description=f"Сотрудник повышен в звании до **{RANK_BY_ID[звание.value]['name']}**.",
                color=COLORS["gold"],
                fields=[
                    ("Прежнее звание", RANK_BY_ID[old_rank]["name"], True),
                    ("Новое звание", RANK_BY_ID[звание.value]["name"], True),
                    ("Приказ подписал", interaction.user.mention, True),
                ],
                author=interaction.user,
            )
        except Exception:
            pass

        # DM
        try:
            await участник.send(embed=embed)
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ {участник.mention} повышен до **{звание.name}**!", ephemeral=True
        )

    @app_commands.command(name="понизить", description="⬇️ Понизить сотрудника в звании")
    @app_commands.describe(участник="Кого понизить", звание="Новое звание", причина="Причина")
    @app_commands.choices(звание=build_rank_choices())
    @commander_only()
    async def demote(self, interaction: discord.Interaction,
                      участник: discord.Member,
                      звание: app_commands.Choice[int],
                      причина: str = ""):
        await interaction.response.defer(ephemeral=True)

        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data:
            await interaction.followup.send("❌ Пользователь не найден!", ephemeral=True)
            return

        old_rank = member_data["rank_id"]
        if звание.value >= old_rank:
            await interaction.followup.send(
                "❌ Новое звание должно быть ниже текущего!", ephemeral=True
            )
            return

        await self.bot.db.update_member(str(участник.id), rank_id=звание.value)
        await self._apply_rank(участник, звание.value, interaction.guild)

        # Лог в личное дело (Форум)
        try:
            from utils.dossier_service import DossierService
            from utils.constants import COLORS
            await DossierService.log_event(
                self.bot, interaction.guild, str(участник.id),
                title="⬇️ Приказ о понижении в звании",
                description=f"Сотрудник понижен в звании до **{RANK_BY_ID[звание.value]['name']}**.",
                color=COLORS["error"],
                fields=[
                    ("Прежнее звание", RANK_BY_ID[old_rank]["name"], True),
                    ("Новое звание", RANK_BY_ID[звание.value]["name"], True),
                    ("Причина", причина or "Решение командования", False),
                    ("Приказ подписал", interaction.user.mention, True),
                ],
                author=interaction.user,
            )
        except Exception:
            pass

        # DM
        try:
            e = discord.Embed(
                title="⬇️ Понижение в звании",
                description=(
                    f"Ваше звание изменено с **{RANK_BY_ID[old_rank]['name']}** "
                    f"до **{RANK_BY_ID[звание.value]['name']}**.\n"
                    + (f"**Причина:** {причина}" if причина else "")
                ),
                color=0xE74C3C,
            )
            e.add_field(name="Подписал", value=interaction.user.mention)
            await участник.send(embed=e)
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ {участник.mention} понижен до **{звание.name}**.", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(RanksCog(bot))
