"""
Модуль обжалований и ходатайств о снятии дисциплинарных взысканий (УСБ)
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import faction_member_only, is_senior_staff
from utils.constants import COLORS, RANK_BY_ID
from utils.dossier_service import DossierService, resolve_member_rank
from utils.embeds import appeal_decision_embed, appeal_embed


class AppealRejectModal(discord.ui.Modal, title="❌ Отклонение ходатайства"):
    def __init__(self, cog, appeal_id: int, member_id: str, message: discord.Message):
        super().__init__()
        self.cog = cog
        self.appeal_id = appeal_id
        self.member_id = member_id
        self.original_message = message

    reason = discord.ui.TextInput(
        label="Причина отклонения",
        placeholder="Укажите причину отказа (недостаточно доказательств и т.д.)",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not is_senior_staff(interaction):
            await interaction.followup.send(
                "❌ Только старший состав, руководство и командиры УСБ могут выносить решения!",
                ephemeral=True,
            )
            return

        reason_text = self.reason.value.strip()
        await self.cog.bot.db.update_appeal(
            self.appeal_id, "rejected", str(interaction.user.id), reason_text
        )

        # Обновляем embed сообщения
        try:
            old_embed = self.original_message.embeds[0]
            new_embed = appeal_decision_embed(
                self.appeal_id, old_embed, approved=False, reviewer=interaction.user, comment=reason_text
            )
            await self.original_message.edit(embed=new_embed, view=None)
        except Exception:
            pass

        # Отправляем ЛС заявителю
        guild = interaction.guild
        member = guild.get_member(int(self.member_id))
        if member:
            try:
                e_dm = discord.Embed(
                    title=f"❌ Ходатайство #{self.appeal_id} отклонено",
                    description=(
                        f"Ваше ходатайство о снятии дисциплинарного взыскания было рассмотрено "
                        f"и **отклонено**.\n\n"
                        f"**Причина отказа:**\n{reason_text}"
                    ),
                    color=COLORS["error"],
                )
                e_dm.add_field(name="Рассмотрел", value=interaction.user.mention, inline=True)
                await member.send(embed=e_dm)
            except Exception:
                pass

        await interaction.followup.send(
            f"❌ Ходатайство **#{self.appeal_id}** отклонено.", ephemeral=True
        )


class AppealApproveModal(discord.ui.Modal, title="✅ Удовлетворение ходатайства"):
    def __init__(self, cog, appeal_id: int, member_id: str, message: discord.Message):
        super().__init__()
        self.cog = cog
        self.appeal_id = appeal_id
        self.member_id = member_id
        self.original_message = message

    resolution = discord.ui.TextInput(
        label="Резолюция / Комментарий УСБ",
        placeholder="Например: Доводы заявителя подтверждены, взыскание аннулировано",
        default="Доводы заявителя подтверждены, взыскание аннулировано.",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not is_senior_staff(interaction):
            await interaction.followup.send(
                "❌ Только старший состав, руководство и командиры УСБ могут выносить решения!",
                ephemeral=True,
            )
            return

        resolution_text = self.resolution.value.strip() or "Ходатайство удовлетворено."
        guild = interaction.guild
        target = guild.get_member(int(self.member_id))

        # 1. Обновляем статус в БД
        await self.cog.bot.db.update_appeal(
            self.appeal_id, "approved", str(interaction.user.id), resolution_text
        )

        # 2. Снимаем последнее взыскание из базы
        await self.cog.bot.db.remove_latest_reprimand(self.member_id)

        # 3. Снимаем роли взысканий
        config = self.cog.bot.config
        if target:
            for k in ["warn_1", "warn_2", "reprimand_1", "reprimand_2"]:
                rid = config["roles"].get(k, 0)
                if rid:
                    r = guild.get_role(rid)
                    if r and r in target.roles:
                        try:
                            await target.remove_roles(r, reason="Снятие взыскания по ходатайству УСБ")
                        except Exception:
                            pass

        # 4. Обновляем сообщение в канале
        try:
            old_embed = self.original_message.embeds[0]
            new_embed = appeal_decision_embed(
                self.appeal_id, old_embed, approved=True, reviewer=interaction.user, comment=resolution_text
            )
            await self.original_message.edit(embed=new_embed, view=None)
        except Exception:
            pass

        # 5. Лог в личное дело на форуме
        try:
            await DossierService.log_event(
                self.cog.bot, guild, self.member_id,
                title=f"✅ Снятие дисциплинарного взыскания | Ходатайство #{self.appeal_id}",
                description="Дисциплинарное взыскание аннулировано по решению УСБ / Руководства.",
                color=COLORS["success"],
                fields=[
                    ("Резолюция", resolution_text, False),
                    ("Решение вынес", interaction.user.mention, True),
                ],
                author=interaction.user,
            )
        except Exception:
            pass

        # 6. Уведомление в ЛС заявителю
        if target:
            try:
                e_dm = discord.Embed(
                    title=f"✅ Ходатайство #{self.appeal_id} удовлетворено!",
                    description=(
                        f"Поздравляем! Ваше ходатайство о снятии дисциплинарного взыскания **удовлетворено**.\n"
                        f"Дисциплинарное взыскание успешно аннулировано."
                    ),
                    color=COLORS["success"],
                )
                e_dm.add_field(name="Резолюция", value=resolution_text, inline=False)
                e_dm.add_field(name="Рассмотрел", value=interaction.user.mention, inline=True)
                await target.send(embed=e_dm)
            except Exception:
                pass

        await interaction.followup.send(
            f"✅ Ходатайство **#{self.appeal_id}** удовлетворено! Взыскание с {target.mention if target else self.member_id} снято.",
            ephemeral=True,
        )


class AppealDecisionView(discord.ui.View):
    """Кнопки рассмотрения ходатайства (Удовлетворить / Отклонить)"""

    def __init__(self, cog, appeal_id: int, member_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.appeal_id = appeal_id
        self.member_id = member_id

        # Динамический custom_id для персистентности
        self.approve_btn.custom_id = f"appeal_approve:{appeal_id}:{member_id}"
        self.reject_btn.custom_id = f"appeal_reject:{appeal_id}:{member_id}"

    @discord.ui.button(
        label="✅ Удовлетворить (Снять выговор)",
        style=discord.ButtonStyle.success,
        custom_id="appeal_approve_btn",
    )
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_senior_staff(interaction):
            await interaction.response.send_message(
                "❌ Только старший состав, руководство и командиры УСБ могут выносить решения!",
                ephemeral=True,
            )
            return

        modal = AppealApproveModal(self.cog, self.appeal_id, self.member_id, interaction.message)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="❌ Отклонить",
        style=discord.ButtonStyle.danger,
        custom_id="appeal_reject_btn",
    )
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_senior_staff(interaction):
            await interaction.response.send_message(
                "❌ Только старший состав, руководство и командиры УСБ могут выносить решения!",
                ephemeral=True,
            )
            return

        modal = AppealRejectModal(self.cog, self.appeal_id, self.member_id, interaction.message)
        await interaction.response.send_modal(modal)


class AppealModal(discord.ui.Modal, title="⚖️ Ходатайство о снятии взыскания"):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    reprimand_url = discord.ui.TextInput(
        label="1. Ссылка на приказ / выговор",
        placeholder="https://discord.com/channels/... или номер рапорта",
        max_length=300,
        required=True,
    )
    article = discord.ui.TextInput(
        label="2. Статья / Пункт устава",
        placeholder="Например: 3.8 В.У.",
        default="3.8 В.У.",
        max_length=100,
        required=True,
    )
    reason = discord.ui.TextInput(
        label="3. Суть ходатайства / Обоснование",
        placeholder="Прошу рассмотреть данное ходатайство для снятия выговора так как проводил лекцию...",
        style=discord.TextStyle.paragraph,
        max_length=600,
        required=True,
    )
    proof = discord.ui.TextInput(
        label="4. Доказательства (фото/видео)",
        placeholder="Ссылка на Яндекс.Диск, Imgur, видеофиксацию...",
        max_length=300,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user_id = str(interaction.user.id)
        member_data = await self.cog.bot.db.get_member(user_id)
        if not member_data:
            await interaction.followup.send("❌ Вы не найдены в базе данных сотрудников!", ephemeral=True)
            return

        reprimand_url_val = self.reprimand_url.value.strip()
        article_val = self.article.value.strip()
        reason_val = self.reason.value.strip()
        proof_val = self.proof.value.strip()

        # 1. Сохраняем в БД
        appeal_id = await self.cog.bot.db.add_appeal(
            user_id, reprimand_url_val, article_val, reason_val, proof_val
        )

        # 2. Определяем звание и должность
        roles_cfg = self.cog.bot.config.get("roles", {})
        rank_info = resolve_member_rank(roles_cfg, interaction.user, member_data)
        rank_name = rank_info.get("name", "Сотрудник")
        position_name = member_data.get("position_prefix", "")

        # 3. Генерируем Embed
        embed = appeal_embed(
            appeal_id=appeal_id,
            member=interaction.user,
            member_data=member_data,
            reprimand_url=reprimand_url_val,
            article=article_val,
            reason=reason_val,
            proof=proof_val,
            rank_name=rank_name,
            position_name=position_name,
        )

        view = AppealDecisionView(self.cog, appeal_id, user_id)

        # 4. Отправляем в канал ходатайств (1539365222001807430)
        config = self.cog.bot.config
        ch_id = config["channels"].get("appeals", 1539365222001807430)
        guild = interaction.guild
        ch = guild.get_channel(ch_id) if ch_id else None

        # Уведомление адресатов
        ping = (
            "<@&1527952234422210681> <@&1527953170490462290> "
            "<@&1245655611627143168> <@&1471213803445293150> <@&1245655611568427054>"
        )

        if ch:
            msg = await ch.send(f"⚖️ **Новое ходатайство о снятии дисциплинарного взыскания!**\n{ping}", embed=embed, view=view)
            await self.cog.bot.db.set_appeal_message(appeal_id, str(msg.id))
        else:
            await interaction.followup.send(embed=embed, view=view)

        await interaction.followup.send(
            f"✅ Ваше ходатайство **#{appeal_id}** о снятии дисциплинарного взыскания успешно подано и передано на рассмотрение УСБ и Руководству!",
            ephemeral=True,
        )


class AppealsCog(commands.Cog, name="Ходатайства и Обжалования"):
    def __init__(self, bot):
        self.bot = bot
        # Персистентный view для кнопок
        bot.add_view(AppealDecisionView(self, 0, "0"))

    @app_commands.command(
        name="ходатайство",
        description="⚖️ Подать ходатайство / обжалование о снятии дисциплинарного взыскания",
    )
    @faction_member_only()
    async def cmd_appeal(self, interaction: discord.Interaction):
        """Открывает модальное окно подачи ходатайства"""
        member_data = await self.bot.db.get_member(str(interaction.user.id))
        if not member_data:
            await interaction.response.send_message(
                "❌ Вы не являетесь действующим сотрудником Росгвардии!", ephemeral=True
            )
            return

        modal = AppealModal(self)
        await interaction.response.send_modal(modal)

    @app_commands.command(
        name="обжалование",
        description="⚖️ Подать обжалование дисциплинарного взыскания (синоним /ходатайство)",
    )
    @faction_member_only()
    async def cmd_appeal_alias(self, interaction: discord.Interaction):
        """Синоним команды /ходатайство"""
        member_data = await self.bot.db.get_member(str(interaction.user.id))
        if not member_data:
            await interaction.response.send_message(
                "❌ Вы не являетесь действующим сотрудником Росгвардии!", ephemeral=True
            )
            return

        modal = AppealModal(self)
        await interaction.response.send_modal(modal)


async def setup(bot):
    await bot.add_cog(AppealsCog(bot))
