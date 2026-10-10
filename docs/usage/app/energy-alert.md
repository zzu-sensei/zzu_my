# 电量预警与邮件提醒

寝室电量低于阈值（默认 **2 度**）时，本项目可以发送本地通知与提醒邮件。
本文说明阈值与去重规则、命令行与桌面端用法、服务端发信通道，以及域名邮箱
需要配置的 DNS 记录。

!!! tip "先理解一件事：发信密钥不放在手机上"
    邮件服务商的 API Key 一旦放进手机就既难轮换也不安全，因此安卓端**不直接
    发信**：它只在本地判断电量，然后把读数上报给服务端，由服务端完成发信。
    手机端只需要知道接口地址和一个共享密钥。

## 阈值与去重规则

| 行为 | 说明 |
| --- | --- |
| 触发条件 | 任意一个电表的剩余电量 **小于等于** 阈值 |
| 默认阈值 | 2 度，可用 `ZZU_ENERGY_THRESHOLD` 或界面上的滑杆修改 |
| 重复提醒 | 进入低电量后只提醒一次 |
| 重新武装 | 电量回升到阈值以上后自动复位，下次再低会重新提醒 |
| 补发 | 低电量持续超过冷却时间（默认 12 小时）会补发一次，避免长期断电却彻底静默 |
| 发信失败 | 不写入去重状态，下次巡检会重试 |

冷却时间可用 `ZZU_ENERGY_COOLDOWN_SECONDS` 调整，设为 `0` 表示不补发。

## 环境变量

发信凭据只从环境变量读取，不会写入配置文件。

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `ZZU_MAIL_PROVIDER` | 是 | `resend` 或 `brevo` |
| `ZZU_MAIL_API_KEY` | 是 | 服务商控制台生成的 API Key |
| `ZZU_MAIL_FROM` | 是 | 发信地址，必须属于已验证的域名 |
| `ZZU_MAIL_TO` | 是 | 收件人，多个用逗号分隔 |
| `ZZU_MAIL_FROM_NAME` | 否 | 发信人显示名，默认「郑大生活助手」 |
| `ZZU_MAIL_FALLBACK_PROVIDER` | 否 | 备用服务商 |
| `ZZU_MAIL_FALLBACK_API_KEY` | 否 | 备用服务商的 API Key |
| `ZZU_ENERGY_THRESHOLD` | 否 | 预警阈值，默认 `2` |
| `ZZU_ENERGY_COOLDOWN_SECONDS` | 否 | 补发冷却时间，默认 `43200` |
| `ZZU_ENERGY_STATE` | 否 | 去重状态文件路径 |
| `ZZU_ENERGY_HISTORY` | 否 | 耗电历史文件路径 |
| `ZZU_ALERT_DRY_RUN` | 否 | 设为 `1` 时只判断不发信 |

## 耗电速度估算

每次查到电量都会记一次采样（时间 + 电表 + 剩余电量），之后用最小二乘拟合出
日均耗电量，进而估算「还能用几天」。比单看两次读数的差值稳得多：抄表噪声和
四舍五入会被摊平。

```bash
# 查询电量并显示耗电速度
zzu --account 你的学号 energy --rate
```

输出形如：

```
耗电速度估算：
  照明：12.5 度，日均 0.42 度，约还能用 29 天
  空调：8.75 度，日均 2.10 度，约还能用 4.2 天
```

`energy-check` 与 `energy-watch` 每次采样后也会打印这行。

估算规则：

- 需要**至少 2 个采样点**且时间跨度**不少于 6 小时**，否则会明确说明数据不足；
- 默认只回看**最近 7 天**，历史文件默认保留 **30 天**；
- 中途充值会让电量上升，此时不会给出负的耗电速度，而是提示「期间电量没有下降」；
- 拟合结果几乎为零（小于 0.01 度/天）时提示「几乎没有耗电」，不给天数估计。

要让估算准，最好让 `energy-watch` 常驻，或用 cron 每天定时跑 `energy-check`。

### 安卓端

「寝室电量」页新增「耗电速度」面板。手机上不写 Python 历史文件，而是：

- 原生层在**每次查询电量成功后**（前台查询与后台巡检都算）往
  `SharedPreferences` 追加一条采样，保留 30 天、最多 4000 条；
- Flutter 侧用与 Python 完全相同的算法（最小二乘、6 小时跨度下限、7 天窗口）
  在本机算出日均耗电与可用天数。

所以手机上只要查过几次电量，不需要额外操作就能看到估算。

## 命令行

```bash
# 查询一次电量
zzu --account 你的学号 energy

# 查一次并按需发提醒邮件，适合交给 cron / systemd timer
zzu --account 你的学号 energy-check --threshold 2

# 常驻巡检，每 30 分钟一次
zzu --account 你的学号 energy-watch --interval 30

# 只巡检一次就退出
zzu --account 你的学号 energy-watch --once
```

统一认证密码通过隐藏输入读取，也可以通过 `ZZU_PASSWORD` 环境变量提供，不会
保存到磁盘。

`energy-check` 会把结果以 JSON 打印到标准输出，便于脚本判断：

```json
{"low": true, "threshold": 2.0, "lowest": 1.25, "notified": true, "provider": "resend"}
```

## 桌面端

`zzu-gui` 的「寝室电量」页新增了「电量预警与邮件提醒」面板：

- 可以修改预警阈值；
- 点击「立即检查并提醒」会查询照明与空调电表并按需发信；
- 面板底部显示最近一次检查结果。

## 服务端发信通道

服务端有两个接口，都需要 `ZZU_ALERT_SECRET` 保护。**未配置该密钥时接口一律
返回 503**，避免被匿名调用刷爆邮件额度。

### `POST /api/energy-alert` —— 由设备上报读数

这是推荐用法：服务端不需要保存任何一卡通凭据。

```bash
curl -X POST 'https://你的域名/api/energy-alert' \
  -H 'Content-Type: application/json' \
  -H 'X-ZZU-Alert-Secret: 你的密钥' \
  -d '{
        "room": "7-2--186-8511",
        "meters": [
          {"label": "照明", "meter_id": "7-2--186-8511", "remaining": 12.5},
          {"label": "空调", "meter_id": "7-2--205-900",  "remaining": 1.25}
        ]
      }'
```

返回示例：

```json
{"ok": true, "low": true, "lowest": 1.25, "notified": true, "provider": "resend"}
```

密钥也可以放在查询参数里（`?secret=...`）以便外部定时器直接配置，但请求头
不会出现在访问日志中，更安全。

### `GET /api/energy-alert/cron` —— 服务端自行巡检

需要额外配置 `ZZU_ACCOUNT` 与 `ZZU_PASSWORD`。**配置后统一认证密码会保存在
服务端**；不想这样做请只用上面的上报接口。

`vercel.json` 里已经声明了每天一次的定时任务。注意 Vercel Hobby 计划
**最多只能每天运行一次 cron**，比这更频繁的表达式会导致部署失败。

> [!WARNING]
> Serverless 上只有 `/tmp` 可写，且实例随时可能被回收，因此服务端的去重状态
> 是尽力而为。建议把 `ZZU_ENERGY_STATE` 设为 `/tmp/zzu-energy-alert.json`，
> 并接受极端情况下可能重复发信。

## 域名邮箱配置

### 只用域名发信（推荐）

Resend 与 Brevo 都**只靠 DNS 验证域名，不需要真实邮箱，也不需要改 MX 记录**。
在你的域名服务商处添加：

```dns
; Resend：DKIM 放在 sending 子域上，不会和根域的 MX/SPF 冲突
resend._domainkey.example.com.  TXT   "p=MIGfMA0GCSq...（控制台给出）"
send.example.com.               TXT   "v=spf1 include:amazonses.com ~all"
send.example.com.               MX 10 feedback-smtp.us-east-1.amazonses.com
```

```dns
; Brevo
mail._domainkey.example.com.    TXT   "v=DKIM1; k=rsa; p=...（控制台给出）"
example.com.                    TXT   "v=spf1 include:spf.brevo.com ~all"
_dmarc.example.com.             TXT   "v=DMARC1; p=none; rua=mailto:dmarc@example.com"
```

规则：

- **同一个域名下只能有一条 SPF 记录**，多个发信方要合并成
  `v=spf1 include:a include:b ~all`。
- DMARC 建议从 `p=none` 起步观察，确认没有误判后再改成 `quarantine`、`reject`。
- 网站与邮件互不影响：A 记录指向 Vercel、MX 指向邮箱服务商即可。但**根域必须
  用 A 记录指向 Vercel，不能用 CNAME**，否则会顶掉 MX 记录。

### 顺带收信

如果还想在这个域名上收信，再补一条 MX 指向邮箱服务商（腾讯企业邮、阿里云邮箱、
Zoho、飞书邮箱等），并按服务商要求添加 SPF/DKIM。

### 上线前的验证顺序

1. 先在 Resend / Brevo 控制台添加域名，按提示添加 DNS 记录并等待验证通过。
2. 配置 `ZZU_MAIL_*` 环境变量，把 `ZZU_ALERT_DRY_RUN=1` 打开试跑一次。
3. 用上面的 `curl` 手工触发一次发信，确认能收到邮件。
4. 关掉 dry run，再在手机上开启邮件提醒。

!!! warning "Resend 域名验证前的限制"
    域名验证通过前，Resend 只允许用 `onboarding@resend.dev` 发到你自己注册的
    邮箱地址，发给其他地址会返回 403。

## 安卓端

「寝室电量」页的「低电量邮件提醒」卡片可以：

- 开关邮件提醒；
- 调整发信阈值（默认 2 度）；
- 填写发信接口地址与提醒密钥（密钥只保存是否已配置，不回显明文）。

后台巡检使用精确闹钟，并在每次巡检结束后重排下一次；应用每次启动也会重排，
避免应用更新后闹钟链断掉。若系统未授予精确闹钟权限，会自动退回允许空闲窗口
的非精确闹钟。

!!! note "为什么不能只靠手机提醒"
    国产 ROM 冻结后台后闹钟可能完全不触发，这是系统行为，改代码无法根治。
    因此建议以服务端巡检为准、手机端作补充。

## 相关模块

- [`zzupy.energy`][zzupy.energy]：阈值判断、去重状态与邮件文案
- [`zzupy.mail`][zzupy.mail]：Resend / Brevo 发信
- [`zzupy.alerting`][zzupy.alerting]：读配置、查电量、判断、发信的编排
