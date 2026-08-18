"""
Bonuses — Система премирования
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import officer_only
from utils.embeds import bonus_embed


class BonusesCog(commands.Cog, name="Премии"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="премия", description="⭐ Выдать премию сотруднику")
    @app_commands.describe(участник="Кому выдать", причина="За что премия")
    @officer_only()
    async def give_bonus(self, interaction: discord.Interaction,
                          участник: discord.Member, причина: str):
        await interaction.response.defer(ephemeral=True)

        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data or member_data["status"] not in ("active", "cadet"):
            await interaction.followup.send("❌ Пользователь не найден во фракции!", ephemeral=True)
            return

        bonus_id = await self.bot.db.add_bonus(str(участник.id), причина, str(interaction.user.id))
        embed = bonus_embed(участник, причина, interaction.user, bonus_id)

        # Публикуем в канал
        config = self.bot.config
        bonuses_ch_id = config["channels"].get("bonuses", 0)
        bonuses_ch = interaction.guild.get_channel(bonuses_ch_id)
        if bonuses_ch:
            await bonuses_ch.send(embed=embed)

        # Лог в личное дело (Форум)
        try:
            from utils.dossier_service import DossierService
            from utils.constants import COLORS
            await DossierService.log_event(
                self.bot, interaction.guild, str(участник.id),
                title="⭐ Поощрение / Выдача премии",
                description=f"Сотрудник поощрён премией #{bonus_id}.",
                color=COLORS["gold"],
                fields=[
                    ("Причина / Заслуги", причина, False),
                    ("Выдал", interaction.user.mention, True),
                ],
                author=interaction.user,
            )
        except Exception:
            pass

        # DM участнику
        try:
            await участник.send(embed=embed)
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ Премия выдана {участник.mention}!", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(BonusesCog(bot))
