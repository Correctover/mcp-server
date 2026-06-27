# Correctover BD 手动操作清单

> 需浏览器/人工操作，这些环节无法通过 CLI 自动化

## 🔴 P0 — 直接影响获客

### 1. 注册 Medium 账号并关联 Correctover 品牌
- 访问 medium.com → 用 wangguigui@correctover.com 注册
- 创建 Medium 个人主页：correctover.medium.com
- 获取 Integration Token：Settings → Security → Integration tokens
- 将已发布的 7 篇 Dev.to 文章同步到 Medium（带 canonical_url）
- 参考 `bd_send_all.py` 中的 Python 调用方式

### 2. LinkedIn 企业主页
- 用 wangguigui@correctover.com 注册 LinkedIn
- 创建公司主页：Correctover 可瑞沃
- 发布英文技术白皮书（可用已发布文章内容）
- 添加王归归为页面管理员

### 3. GitHub Organization
- 创建 github.com/Correctover 组织
- 上传 correctover SDK demo 仓库
- 设置组织 README

## 🟡 P1 — SEO 和发现

### 4. AI 工具目录提交
| 平台 | URL | 费用 | 操作 |
|------|-----|------|------|
| SaaSHub | saashub.com/submit | 免费 | 注册 → 提交正确网址 |
| AlternativeTo | alternativeto.net | 免费 | 注册 → 等7天新人期 → 提交 |
| There's An AI For That | theresanaiforthat.com | $347 | 付费提交 |
| OpenAlternative | openalternative.co | 免费 | 提交 |
| G2 | g2.com | 免费 | 注册 → 提交产品 |
| Capterra | capterra.com | 免费 | 注册 → 提交产品 |

### 5. 技术平台注册
| 平台 | 注册链接 | 策略 |
|------|---------|------|
| 知乎 | zhihu.com | 账号：Correctover可瑞沃AI可靠性 |
| CSDN | csdn.net | 同步 Dev.to 文章 |
| 掘金 | juejin.cn | 使用之前配好的 Cookie 管道 |
| InfoQ | infoq.cn | 技术深度文章 |

## 🟢 P2 — 权威背书

### 6. Google Search Console
- 验证 correctover.com 所有权（CNAME 或 HTML 文件）
- 提交 sitemap.xml 索引

### 7. 百度搜索资源平台
- 验证 correctover.cn 所有权
- 提交 sitemap.xml

### 8. AI 工具导航评论区铺设
- 在 「AI 网关」「LLM 可靠性」相关工具页面评论区
- 不硬推，以「我们在做类似方向」角度参与讨论

## 📅 第一周跟进（7月2日）

BD 邮件发出满一周后，对未回复的决策者发 follow-up：

```python
# follow-up 模板
Hi [Name],

Just following up on my previous email about Correctover.

We've had some interesting conversations since — developers consistently tell us that verified failover is the missing piece in their multi-provider stack.

I'd love to share our benchmark data and a quick demo. Are you open to a 15-minute call this week?

Best,
王归归
```

发送方式：修改 `bd_send_all.py` 中的 body 字段，加 `--send --target <key>`

## 策略要点
- **不重复发信**：每个目标一封 + 一周后一封 follow-up = 最多2封
- **先用免费渠道**：SaaSHub/AlternativeTo 免费，先上
- **内容复用**：Dev.to 文章 → Medium → LinkedIn → (截取片段) → Twitter
- **优先级判断依据**：直接获客能力 > SEO 长尾 > 品牌背书
