"""
Reports — Система рапортов (повышение, увольнение, взыскания, самоотвод)
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import commander_only, faction_member_only, officer_only
from utils.constants import COLORS, RANK_BY_ID, RANKS
from utils.embeds import report_embed, report_decision_embed


def build_rank_choices():
    return [
        app_commands.Choice(name=r["name"], value=r["id"])
        for r in RANKS[2:]  # Начиная с Рядового
    ]


class ReportDecisionView(discord.ui.View):
    """Кнопки одобрить/отклонить рапорт"""

    def __init__(self, cog, report_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.report_id = report_id

    @discord.ui.button(label="✅ Одобрить", style=discord.ButtonStyle.success,
                        custom_id="report_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.checks import is_commander
        if not is_commander(interaction):
            await interaction.response.send_message(
                "❌ Только командиры могут одобрять рапорты!", ephemeral=True
            )
            return
        await self._process(interaction, approved=True)

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger,
                        custom_id="report_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.checks import is_commander
        if not is_commander(interaction):
            await interaction.response.send_message(
                "❌ Только командиры могут отклонять рапорты!", ephemeral=True
            )
            return
        await self._process(interaction, approved=False)

    async def _process(self, interaction: discord.Interaction, approved: bool):
        report = await self.cog.bot.db.get_report(self.report_id)
        if not report:
            await interaction.response.send_message("❌ Рапорт не найден!", ephemeral=True)
            return
        if report["status"] != "pending":
            await interaction.response.send_message(
                "⚠️ Рапорт уже рассмотрен!", ephemeral=True
            )
            return

        status = "approved" if approved else "rejected"
        await self.cog.bot.db.update_report(
            self.report_id, status, str(interaction.user.id)
        )

        if approved:
            await self.cog._execute_report(report, interaction.user, interaction.guild)

        # Обновляем сообщение
        embed = report_decision_embed(self.report_id, report["type"], approved, interaction.user)
        await interaction.response.edit_message(embed=embed, view=None)

        # Уведомляем автора и цель рапорта
        guild = interaction.guild
        for uid in set([report["author_id"], report["target_id"]]):
            try:
                target_m = guild.get_member(int(uid))
                if target_m:
                    action = "одобрен ✅" if approved else "отклонён ❌"
                    e = discord.Embed(
                        title=f"Рапорт #{self.report_id} {action}",
                        description=f"Рапорт рассмотрен: **{interaction.user}**",
                        color=COLORS["success"] if approved else COLORS["error"],
                    )
                    await target_m.send(embed=e)
            except Exception:
                pass


class ReportsCog(commands.Cog, name="Рапорты"):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(ReportDecisionView(self, 0))

    report_group = app_commands.Group(name="рапорт", description="📋 Система рапортов")

    async def _send_report(self, interaction: discord.Interaction, report_id: int,
                            type_: str, author: discord.Member, target: discord.Member,
                            reason: str, new_rank_id: int = None):
        """Отправляет рапорт в нужный канал в зависимости от типа"""
        config = self.bot.config
        channels = config["channels"]
        guild = interaction.guild

        # Умная маршрутизация по типу рапорта
        if type_ == "promotion" and new_rank_id is not None:
            # Определяем куда слать рапорт на повышение
            member_data = await self.bot.db.get_member(str(target.id))
            current_rank = member_data["rank_id"] if member_data else 0

            if current_rank <= 1:  # Курсант АВНГ
                ch_id = channels.get("cadet_promotions", channels.get("reports", 0))
            elif current_rank <= 8:  # Сержанты / прапорщики (инструкторский состав)
                ch_id = channels.get("promotions_instr", channels.get("reports", 0))
            else:  # Офицеры и выше — АВНГ списки
                ch_id = channels.get("promotions_avng", channels.get("reports", 0))

        elif type_ in ("fire", "self_fire"):
            ch_id = channels.get("fire_reports", channels.get("reports", 0))

        else:
            ch_id = channels.get("reports", 0)

        reports_ch = guild.get_channel(ch_id) if ch_id else None

        embed = report_embed(report_id, type_, author, target, reason, new_rank_id)
        view = ReportDecisionView(self, report_id)

        # Пингуем командиров через список ролей
        commander_ids = config["roles"].get("commander_roles", [])
        if isinstance(commander_ids, int):
            commander_ids = [commander_ids]
        ping = " ".join(f"<@&{r}>" for r in commander_ids if r) or ""

        if reports_ch:
            msg = await reports_ch.send(
                f"{ping} 📋 Новый рапорт!" if ping else "📋 Новый рапорт!",
                embed=embed,
                view=view,
            )
            await self.bot.db.set_report_message(report_id, str(msg.id))
        else:
            await interaction.followup.send(embed=embed, view=view)

    async def _execute_report(self, report: dict, approved_by: discord.Member,
                               guild: discord.Guild):
        """Исполняет одобренный рапорт"""
        type_ = report["type"]
        target_id = report["target_id"]
        target = guild.get_member(int(target_id))
        member_data = await self.bot.db.get_member(target_id)
        if not member_data:
            return

        if type_ == "promotion":
            new_rank_id = report.get("new_rank_id")
            if new_rank_id is None:
                return
            old_rank = member_data["rank_id"]
            await self.bot.db.update_member(target_id, rank_id=new_rank_id)
            await self.bot.db.add_promotion(target_id, old_rank, new_rank_id,
                                             str(approved_by.id), report["id"])
            if target:
                await self._apply_rank_to_member(target, new_rank_id, guild)

            # Анонс
            promotions_ch_id = self.bot.config["channels"].get("promotions", 0)
            promotions_ch = guild.get_channel(promotions_ch_id)
            if promotions_ch:
                from utils.embeds import promotion_embed
                e = promotion_embed(target or approved_by,
                                    old_rank, new_rank_id, approved_by)
                await promotions_ch.send(embed=e)

            # Лог в личное дело (Форум)
            try:
                from utils.dossier_service import DossierService
                from utils.constants import RANK_BY_ID
                await DossierService.log_event(
                    self.bot, guild, target_id,
                    title="📈 Повышение по рапорту",
                    description=f"Рапорт #{report['id']} одобрен. Присвоено звание **{RANK_BY_ID[new_rank_id]['name']}**.",
                    color=COLORS["gold"],
                    fields=[
                        ("Прежнее звание", RANK_BY_ID[old_rank]["name"], True),
                        ("Новое звание", RANK_BY_ID[new_rank_id]["name"], True),
                        ("Одобрил рапорт", approved_by.mention, True),
                    ],
                    author=approved_by,
                )
            except Exception:
                pass

        elif type_ in ("fire", "self_fire"):
            await self.bot.db.update_member(target_id, status="fired", rank_id=0)

            # Лог в личное дело (Форум)
            try:
                from utils.dossier_service import DossierService
                fire_reason = report.get("reason", "Рапорт на увольнение / самоотвод")
                await DossierService.log_event(
                    self.bot, guild, target_id,
                    title="⚫ Приказ об увольнении / Архивирование дела",
                    description=f"Сотрудник уволен из рядов Росгвардии по рапорту #{report['id']}.",
                    color=COLORS["dark"],
                    fields=[
                        ("Причина", fire_reason, False),
                        ("Приказ утвердил", approved_by.mention, True),
                    ],
                    author=approved_by,
                )
            except Exception:
                pass

            if target:
                fired_role_id = self.bot.config["roles"].get("fired", 0)
                # Убираем все роли фракции
                from utils.constants import RANKS as ALL_RANKS
                for r in ALL_RANKS:
                    rid = self.bot.config["roles"].get(r["role_key"], 0)
                    if rid:
                        role = guild.get_role(rid)
                        if role and role in target.roles:
                            try:
                                await target.remove_roles(role)
                            except Exception:
                                pass
                if fired_role_id:
                    fired_role = guild.get_role(fired_role_id)
                    if fired_role:
                        try:
                            await target.add_roles(fired_role)
                        except Exception:
                            pass
                try:
                    await target.edit(nick=member_data['game_name'])
                except discord.Forbidden:
                    pass
                try:
                    e = discord.Embed(
                        title="📋 Вы уволены из Росгвардии",
                        description="Ваш рапорт на увольнение одобрен. "
                                    "Спасибо за службу!",
                        color=COLORS["dark"],
                    )
                    await target.send(embed=e)
                except Exception:
                    pass

        elif type_ == "reprimand":
            reason = report.get("reason", "")
            await self.bot.db.add_reprimand(target_id, reason, str(approved_by.id))

            # Лог в личное дело (Форум)
            try:
                from utils.dossier_service import DossierService
                await DossierService.log_event(
                    self.bot, guild, target_id,
                    title="⚠️ Приказ о дисциплинарном взыскании",
                    description=f"Сотруднику назначено дисциплинарное взыскание по рапорту #{report['id']}.",
                    color=COLORS["warning"],
                    fields=[
                        ("Причина", reason or "Нарушение устава", False),
                        ("Взыскание наложил", approved_by.mention, True),
                    ],
                    author=approved_by,
                )
            except Exception:
                pass

    async def _apply_rank_to_member(self, member: discord.Member, rank_id: int,
                                     guild: discord.Guild):
        """Применяет роль звания участнику"""
        config = self.bot.config
        from utils.constants import RANKS as ALL_RANKS
        # Убираем все старые роли
        for r in ALL_RANKS:
            rid = config["roles"].get(r["role_key"], 0)
            if rid:
                role = guild.get_role(rid)
                if role and role in member.roles:
                    try:
                        await member.remove_roles(role)
                    except Exception:
                        pass
        # Даём новую
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
                member_data = await self.bot.db.get_member(str(member.id))
                game_name = member_data["game_name"] if member_data else member.display_name
                await member.edit(nick=game_name)  # Только ФИО
            except discord.Forbidden:
                pass

    # ─────────────── РАПОРТ НА ПОВЫШЕНИЕ ───────────────

    @report_group.command(name="повышение", description="📈 Рапорт на повышение в звании")
    @app_commands.describe(
        участник="Кого повысить",
        звание="Новое звание",
        обоснование="Причина и заслуги",
    )
    @app_commands.choices(звание=build_rank_choices())
    @officer_only()
    async def report_promotion(self, interaction: discord.Interaction,
                                участник: discord.Member,
                                звание: app_commands.Choice[int],
                                обоснование: str):
        await interaction.response.defer(ephemeral=True)

        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data or member_data["status"] not in ("active", "cadet"):
            await interaction.followup.send("❌ Пользователь не найден во фракции!", ephemeral=True)
            return
        if звание.value <= member_data["rank_id"]:
            await interaction.followup.send(
                "❌ Новое звание должно быть выше текущего!", ephemeral=True
            )
            return

        report_id = await self.bot.db.add_report(
            "promotion", str(interaction.user.id), str(участник.id),
            обоснование, new_rank_id=звание.value,
        )
        await self._send_report(interaction, report_id, "promotion",
                                  interaction.user, участник, обоснование, звание.value)
        await interaction.followup.send(
            f"✅ Рапорт на повышение **#{report_id}** подан и ожидает решения командования.",
            ephemeral=True,
        )

    # ─────────────── РАПОРТ НА УВОЛЬНЕНИЕ ───────────────

    @report_group.command(name="увольнение", description="📋 Рапорт на увольнение сотрудника")
    @app_commands.describe(участник="Кого уволить", причина="Причина увольнения")
    @officer_only()
    async def report_fire(self, interaction: discord.Interaction,
                           участник: discord.Member, причина: str):
        await interaction.response.defer(ephemeral=True)

        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data or member_data["status"] == "fired":
            await interaction.followup.send("❌ Пользователь не найден или уже уволен!", ephemeral=True)
            return

        report_id = await self.bot.db.add_report(
            "fire", str(interaction.user.id), str(участник.id), причина
        )
        await self._send_report(interaction, report_id, "fire",
                                  interaction.user, участник, причина)
        await interaction.followup.send(
            f"✅ Рапорт на увольнение **#{report_id}** подан.", ephemeral=True
        )

    # ─────────────── РАПОРТ-САМООТВОД ───────────────

    @report_group.command(name="самоотвод", description="🚪 Подать рапорт на собственное увольнение")
    @app_commands.describe(причина="Причина увольнения")
    @faction_member_only()
    async def report_self_fire(self, interaction: discord.Interaction, причина: str):
        await interaction.response.defer(ephemeral=True)

        member_data = await self.bot.db.get_member(str(interaction.user.id))
        if not member_data:
            await interaction.followup.send("❌ Вы не являетесь членом фракции!", ephemeral=True)
            return

        report_id = await self.bot.db.add_report(
            "self_fire", str(interaction.user.id), str(interaction.user.id), причина
        )
        await self._send_report(interaction, report_id, "self_fire",
                                  interaction.user, interaction.user, причина)
        await interaction.followup.send(
            f"✅ Рапорт на самоотвод **#{report_id}** подан и ожидает решения.", ephemeral=True
        )

    # ─────────────── РАПОРТ — ВЗЫСКАНИЕ ───────────────

    @report_group.command(name="взыскание", description="⚠️ Рапорт о взыскании на сотрудника")
    @app_commands.describe(участник="На кого", причина="Причина взыскания")
    @officer_only()
    async def report_reprimand(self, interaction: discord.Interaction,
                                участник: discord.Member, причина: str):
        await interaction.response.defer(ephemeral=True)

        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data:
            await interaction.followup.send("❌ Пользователь не найден во фракции!", ephemeral=True)
            return

        report_id = await self.bot.db.add_report(
            "reprimand", str(interaction.user.id), str(участник.id), причина
        )
        await self._send_report(interaction, report_id, "reprimand",
                                  interaction.user, участник, причина)
        await interaction.followup.send(
            f"✅ Рапорт о взыскании **#{report_id}** подан.", ephemeral=True
        )

    # ─────────────── ОТЧЁТ О РАБОТЕ ───────────────

    @report_group.command(name="работа", description="📝 Подать отчёт о проделанной работе")
    @app_commands.describe(текст="Опишите проделанную работу")
    @faction_member_only()
    async def report_work(self, interaction: discord.Interaction, текст: str):
        await interaction.response.defer(ephemeral=True)

        member_data = await self.bot.db.get_member(str(interaction.user.id))
        if not member_data:
            await interaction.followup.send("❌ Вы не являетесь членом фракции!", ephemeral=True)
            return

        report_id = await self.bot.db.add_work_report(str(interaction.user.id), текст)

        config = self.bot.config
        wr_ch_id = config["channels"].get("work_reports", 0)
        wr_ch = interaction.guild.get_channel(wr_ch_id)

        from utils.embeds import work_report_embed
        embed = work_report_embed(interaction.user, текст, report_id)
        if wr_ch:
            await wr_ch.send(embed=embed)

        await interaction.followup.send(
            f"✅ Отчёт о работе **#{report_id}** подан!", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(ReportsCog(bot))
