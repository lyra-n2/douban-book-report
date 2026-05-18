---
name: douban-reading
description: 当用户需要分析自己的豆瓣读书数据、生成阅读报告、可视化读书品味画像、统计读过/在读/想读、生成评分分布、分类雷达、作者偏好、想读列表分析等时使用。通过 Playwright 引导用户登录豆瓣，采集本人账号下的全部数据（含非公开），生成单文件 HTML 报告，并由 AI 基于数据生成个性化品味洞察。不用于通用图书推荐，也不用于他人豆瓣页面爬取。
---

# 豆瓣读书 Skill

通过用户本人登录态采集豆瓣读书数据，生成中文 HTML 阅读品味报告 + AI 个性化洞察。

适配 Claude Code、Cursor、Cline、通义灵码、Trae 等任何支持本地 Python 执行 + 文件读写的 AI agent。

## 输入

三种模式，互斥：

- **登录模式**（推荐）：`--login` 启动 Playwright 弹出豆瓣登录页，用户自行扫码/输密码完成登录，脚本接管采集本人「读过/在读/想读」全部内容（含仅自己可见）
- **CSV 模式**：`--csv <path>` 解析豆瓣官方导出的 CSV 文件
- **示例模式**：`--sample` 用内置模拟数据生成示例报告（不联网）

可选参数：
- `--output <dir>`：报告输出目录，默认当前目录下 `reports/`
- `--from-raw <path>`：从已采集的 `douban-raw-books.json` 重建报告（不重新采集，用于调整图表样式）
- `--include-comments`：采集每本书的短评（更耗时）
- `--proxy <url>`：HTTP 代理，例如 `http://127.0.0.1:7897`

## 输出

均写入 `--output` 目录：

- `douban-report.html`：单文件交互式 HTML 报告（双击即可在浏览器打开）
- `douban-report-data.json`：聚合后的图表数据
- `douban-raw-books.json`：原始采集的完整书籍列表（含个人评分/短评，请视为隐私）
- `douban-raw-summary.json`：采集覆盖范围摘要（不含敏感内容）
- `douban-insights.md`：由 AI agent 生成的个性化洞察（见下方工作流第 7 步）

## 安全约定

- **绝不存储登录态**：cookie 仅在内存中流转，脚本结束即丢弃
- **绝不读取/写入密码**：登录窗口由用户本人操作
- 报告产物视为私有，除非用户明确要求否则不要分享 `douban-raw-books.json` 或 `douban-insights.md`

## 工作流

AI agent 收到「分析我的豆瓣读书数据 / 生成豆瓣读书报告」类需求时，按以下顺序执行：

1. 读 `references/data-contract.md` 确认豆瓣页面字段映射
2. 检查依赖：`pip3 list | grep -iE "playwright|beautifulsoup"`，若缺失提示用户运行 `install.sh` 或手动装（脚本启动时也会自检并给出带国内镜像的命令）
3. 询问用户输出目录（不要假设具体路径）
4. 运行 `scripts/generate_douban_report.py --login --output <用户指定目录>`
5. 提示用户在弹出窗口中完成登录，**不要替用户输密码**；脚本会自动检测 `dbcl2` cookie 出现，无需用户回车
6. 检查生成的 HTML 含 9+ 图表，没有占位文本或残留 cookie
7. **生成 AI 洞察**（核心增值步骤）：
   - 读 `<output_dir>/douban-raw-books.json` 获取完整书籍列表
   - 基于以下维度分析，写入 `<output_dir>/douban-insights.md`：
     - **品味画像**：从高分书（4-5 星）+ 高频标签 + 偏好作者反推用户的核心兴趣领域和阅读偏好（不要只是统计，要给出判断和定性描述）
     - **想读优先级**：从想读列表挑 5-8 本「最该立刻读」的书，每本说一句为什么——结合用户已读过的相关书（说明承接关系）、想读时间长度（说明拖延）、或当下相关性
     - **建议放弃**：从想读列表挑 1-2 本「想读 N 年但实际不会读」的书，建议卸下心理负担
     - **阅读盲区**：用户的标签集中在哪几个领域，明显缺什么类型；这些盲区是有意选择还是无意忽略
     - **同款推荐**：基于用户已读高分书的作者/主题，推荐 5-10 本用户**没标过**的相关书（用 `douban-raw-books.json` 里的 title 字段验证「没标过」），每本说明推荐理由
     - **节奏观察**：年度/月度阅读量的变化趋势可能暗示了什么生活状态变化（如某年阅读量骤降可能对应生育/换工作/搬家等，但不要妄下结论，只提出可能性请用户确认）
   - HTML 报告在下次重新生成时会自动嵌入这个 markdown 到「AI 品味洞察」区块
   - 写完后运行 `python3 scripts/generate_douban_report.py --from-raw <output_dir>/douban-raw-books.json --output <output_dir>` 重新生成 HTML 嵌入洞察
   - 提示用户刷新报告页面查看

## 命令参考

```bash
# 完整流程：登录采集 + 生成报告
python3 scripts/generate_douban_report.py --login --output ./reports/

# 调整图表样式（基于已采集数据，无需重爬）
python3 scripts/generate_douban_report.py --from-raw ./reports/douban-raw-books.json --output ./reports/

# CSV 模式
python3 scripts/generate_douban_report.py --csv ~/Downloads/douban_books.csv --output ./reports/

# 示例数据（不联网）
python3 scripts/generate_douban_report.py --sample --output ./reports/sample/
```

## 边界

- 仅采集用户**自己**账号下的页面，不爬他人
- 不绕过豆瓣登录或验证码，反爬触发时脚本会暂停重试
- 报告中不嵌入任何 cookie、token 或可识别会话信息
- 豆瓣均分在书单页 HTML 中不提供，本脚本默认不抓取每本书的详情页（成本高、风险高）
