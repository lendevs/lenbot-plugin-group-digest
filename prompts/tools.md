group_summary_card 按本群消息记录生成日报。过去 12h 用 hours=12，过去 24h 用 hours=24；昨天整日、今天下午使用本群时区的 ISO start_at/end_at，不要把自然日当成滚动 24h。范围终点不含，不能在未来，跨度最多 72h；hours 与范围互斥。省略全部为过去 24h。
status=started 表示开始后台生成；delivery=plugin 表示完成后插件自行发送到本群，你不用再转述报告。already_running 表示已有报告正在生成。增量开启时复用完整小时摘要，边缘时段仍从原文提取；统计与引用来自选定范围。
group_work 用请求人的真实 source_message_id 委派长工作。返回任务信息表示排队或实际状态，最终交付由宿主负责。
