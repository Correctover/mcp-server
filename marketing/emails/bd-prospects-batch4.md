# BD 获客目标 — Batch 4

## 新发现的 AI 基础设施/企业 AI 决策者

| # | 公司 | 决策者 | 邮箱猜测 | 理由 |
|---|------|--------|---------|------|
| 1 | nexos.ai | Tomas Okmanas | tomas@nexos.ai or first@nexos.ai | 企业AI编排平台,$8M融资,智能路由+负载均衡 |
| 2 | Requesty | Thibault Jaigu | thibault@requesty.ai or first@requesty.ai | AI API网关("Cloudflare for AI"),$3M seed,25K开发者 |
| 3 | Gradient Labs | (待查) | first@gradientlabs.ai | 金融服务AI Agent基础设施,多provider failover |
| 4 | Writer.com | May Habib | may@writer.com | 企业GenAI平台,$1.5B估值,250+企业客户 |
| 5 | Dust | Gabriel Hubert | gabriel@dust.tt | 企业知识Agent,模型无关,ex-Stripe/OpenAI |
| 6 | E2B | Vasek Mlejnsky | vasek@e2b.dev | 安全沙箱 for AI Agents,Wing VC 2026 |
| 7 | Arcade | Alex Salazar | alex@arcade.dev | MCP认证/授权,ex-Okta,Wing VC 2026 |
| 8 | ComplyAdvantage | Vatsa Narasimha | vatsa@complyadvantage.com | AI驱动的AML/金融犯罪合规,1000+客户 |
| 9 | Artisan | Jaspar Carmichael-Jack | jaspar@artisan.co | AI BDR(销售Agent),SaaStr 2026 |
| 10 | Modal | Erik Bernhardsson | erik@modal.com | AI原生云,Wing VC 2026 |

## 邮件主题策略（建议）

- **nexos.ai/Requesty**: "Gateway + verified failover — a complementary layer"（类似Portkey策略）
- **Gradient Labs/Writer.com/Artisan**: "Production AI needs verified failover — 6-dimension response validation"
- **Dust/E2B/Arcade**: "Embedded SDK for verified failover — one pip install, zero proxy"
- **ComplyAdvantage**: "Zero tolerance for silent errors — verified failover for regulated AI"

## 执行

逐个SMTP RCPT验证邮箱存在性后，通过bd_send_all.py发送（Batch 4）。
