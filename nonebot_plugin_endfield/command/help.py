from nonebot import on_command


endfield_help = on_command("终末地帮助", aliases={"终末地"})


@endfield_help.handle()
async def handle_endfield_help():
    help_text = "\n".join(
        [
            "终末地插件指令帮助",
            "",
            "【基础功能】",
            "终末地绑定",
            "终末地切换账号 [序号/角色ID]",
            "终末地信息卡",
            "签到",
            "终末地公告",
            "",
            "【抽卡相关】",
            "抽卡记录 [页码]",
            "抽卡分析",
            "全服抽卡统计 [卡池关键词]",
            "同步全部抽卡（仅 superusers）",
            "",
            "提示：抽卡指令支持前缀，如 :抽卡记录、/zmd 抽卡分析、#终末地 全服抽卡统计",
        ]
    )
    await endfield_help.finish(help_text)