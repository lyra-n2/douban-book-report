# 豆瓣读书 Skill

> 用 AI agent 一键生成你的豆瓣读书可视化报告 + 个性化品味洞察

一个适配多种 AI agent（Claude Code / Cursor /Openclaw/ 通义灵码 / Trae 等）的本地 skill。通过 Playwright 引导你登录豆瓣，采集本人「读过/在读/想读」全部数据（含仅自己可见），生成一份单文件 HTML 报告，并由 AI agent 基于数据为你生成个性化阅读洞察。

## 报告包含什么

**9 个可视化图表**：
- 年度阅读量趋势 / 月度热力图
- 评分分布 / 分类雷达 / 标签词云
- Top 作者 / Top 出版社
- 出版年份分布
- 想读但久未读 Top 10
- 想读但一本都没读过的作者 Top 10

**AI 个性化洞察**（由你使用的 AI agent 生成）：
- 品味画像
- 想读优先级建议（最该立刻读的 5-8 本）
- 建议放弃的书（想读多年实际不会读）
- 阅读盲区
- 同款推荐（你没标过的 5-10 本相关书）
- 阅读节奏观察

## 安装

### 1. 下载 skill

把这个目录放到 AI agent 能识别的 skill 路径，例如：
- **Claude Code**：`~/.claude/skills/douban-reading/`
- **其他 agent**：参考各自 skill 加载约定

### 2. 安装依赖

**一键安装脚本（推荐国内用户）**：

```bash
bash install.sh
```

**或手动安装**：

```bash
# 用清华镜像装 Python 包
pip3 install -i https://pypi.tuna.tsinghua.edu.cn/simple playwright beautifulsoup4

# 用 npmmirror 装 Chromium 浏览器
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors python3 -m playwright install chromium
```

国外用户去掉镜像参数即可：

```bash
pip3 install playwright beautifulsoup4
python3 -m playwright install chromium
```

## 使用

### 方式一：让 AI agent 调用（推荐）

打开你的 AI agent，直接说：

> 帮我用 douban-reading skill 生成豆瓣读书报告，输出到 `~/Documents/豆瓣报告/`

agent 会：
1. 启动浏览器引导你登录豆瓣
2. 自动采集你的全部书单
3. 读原始数据生成个性化洞察
4. 重新生成 HTML 把洞察嵌进去

### 方式二：直接命令行运行

```bash
# 登录采集（首次使用）
python3 scripts/generate_douban_report.py --login --output ./reports/

# 看报告
open ./reports/douban-report.html
```

然后让 AI agent 读 `./reports/douban-raw-books.json` 并按 SKILL.md 第 7 步生成洞察，写入 `./reports/douban-insights.md`，再重跑：

```bash
python3 scripts/generate_douban_report.py --from-raw ./reports/douban-raw-books.json --output ./reports/
```

## 常见问题

### Q: 会不会被豆瓣封号？

实操中风险**很低**：脚本只访问你自己的页面、串行请求、每页 1.5 秒间隔、用真实 Chromium 浏览器（不是 requests）。豆瓣对这种行为非常宽容。

如果想更稳，把 `scripts/generate_douban_report.py` 里的 `PAGE_SLEEP_SEC = 1.5` 改成 3-5 秒。

### Q: 我的密码会被读取吗？

**不会**。登录窗口由你自己操作，脚本只在登录完成后（检测到 `dbcl2` cookie 出现）才接管，cookie 仅在内存中使用，脚本结束即丢弃。

### Q: 图表加载不出来？

国内访问 CDN 不稳定，脚本已配置 3 个 CDN 自动 fallback（npmmirror → unpkg → jsdelivr）。如果全部失败，页面会显示警告条，请检查网络或代理。

### Q: 想读列表能采集吗？

可以。豆瓣的「想读」即使设为私密，登录态下也能采到。报告里有专门的「想读分析」章节。

### Q: 数据会上传到任何地方吗？

**不会**。所有数据采集和报告生成全部在本地完成，AI agent 也只是读你本地的 JSON 文件生成洞察 md。没有任何数据发送到第三方服务器（除了你的 AI agent 服务本身处理 prompt 的过程）。

### Q: 我换了一个 AI agent，洞察怎么再生成一遍？

让新 agent 读 `douban-raw-books.json` 并按 `SKILL.md` 第 7 步执行即可。SKILL.md 第 7 步是 agent-agnostic 的明确指令。

## 隐私须知

⚠️ **`douban-raw-books.json` 和 `douban-insights.md` 含有你的全部阅读记录、评分、短评，请视为隐私文件**：

- 不要直接 push 到公开 git 仓库
- 不要分享给他人看（除非你愿意）
- 如果在云端 AI agent 用，agent 服务方会读到这些数据，请评估服务方隐私政策

如果只想分享报告，分享 `douban-report.html` 即可（聚合数据已脱敏到统计层面，但仍可能反推个人偏好）。

## 文件结构

```
douban-reading/
├── SKILL.md                            # AI agent 触发条件 + 工作流
├── README.md                           # 本文件
├── manifest.json                       # 元信息
├── requirements.txt                    # Python 依赖
├── install.sh                          # 一键安装脚本
├── LICENSE                             # MIT
├── scripts/
│   └── generate_douban_report.py       # 主脚本
└── references/
    ├── data-contract.md                # 豆瓣页面字段映射
    └── report-design.md                # 报告视觉规范
```

## License

MIT
