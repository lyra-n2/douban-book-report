# 豆瓣读书数据契约

## 页面 URL 模板

| 用途 | URL |
|------|-----|
| 读过 | `https://book.douban.com/people/<UID>/collect?start=<N>&sort=time&mode=grid` |
| 在读 | `https://book.douban.com/people/<UID>/do?start=<N>&sort=time&mode=grid` |
| 想读 | `https://book.douban.com/people/<UID>/wish?start=<N>&sort=time&mode=grid` |
| 单本书页 | `https://book.douban.com/subject/<BOOK_ID>/` |

每页 15 条，分页参数 `start=0, 15, 30, ...`

## DOM 选择器（书单页）

每本书是 `li.subject-item`：

| 字段 | CSS 选择器 | 备注 |
|------|----------|------|
| 书名 | `.info h2 a` | text + href |
| 书 ID | `.info h2 a` 的 href 提取 `/subject/(\d+)/` | |
| 出版信息 | `.pub` | 形如「作者 / 译者 / 出版社 / 年份 / 价格」，用 ` / ` 分割 |
| 豆瓣均分 | `.rating-info .rating_nums` | 浮点数，可能为空 |
| 我的评分 | `.info span[class^="rating"]` | class 形如 `rating5-t`，取数字部分 1-5 |
| 标记日期 | `.date` | 形如「2024-01-15 读过」 |
| 标签 | `.tags` | 形如「标签: 心理学 哲学」，去前缀后空格分割 |
| 短评 | `.comment` | 用户自己的短评 |

## 状态字段

每个书单页对应一个状态：
- `collect` → 读过
- `do` → 在读
- `wish` → 想读

## CSV 模式字段映射

豆瓣官方导出 CSV 表头（按版本可能略有差异）：

| CSV 列 | 内部字段 |
|--------|---------|
| 标题 | `title` |
| 评分 | `my_rating` |
| 备注 / 短评 | `comment` |
| 标签 | `tags` |
| 创建时间 | `mark_date` |
| URL | `book_url` |

## 输出 JSON 结构

```json
{
  "meta": {
    "uid": "anonymized",
    "generated_at": "2026-05-18T10:00:00",
    "total_collect": 234,
    "total_doing": 5,
    "total_wish": 89
  },
  "books": [
    {
      "title": "思考，快与慢",
      "book_id": "10785583",
      "status": "collect",
      "author": "丹尼尔·卡尼曼",
      "publisher": "中信出版社",
      "pub_year": 2012,
      "douban_rating": 8.2,
      "my_rating": 5,
      "mark_date": "2024-01-15",
      "tags": ["心理学", "认知科学"],
      "comment": "..."
    }
  ]
}
```

## 反爬注意

- 每页之间 sleep 1.5 秒
- User-Agent 用真实浏览器（Playwright 默认即可）
- 检测到「检测到异常请求」「请输入验证码」时立即暂停，让用户在浏览器窗口手动处理后回车继续
- 不并发，串行请求
