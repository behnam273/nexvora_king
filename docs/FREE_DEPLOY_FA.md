# استقرار کاملاً رایگان NEXVORA (هزینه اولیه: ۰)

پاسخ کوتاه به سؤال «پروژه رایگان باشد؟»:

- **بله، می‌شود.** با ترکیب **Railway Free** + **Supabase Free** هزینه ماهانه ۰ است.
- **بله، Postgres اضافه می‌شود.** کد از قبل پشتیبانی می‌کند؛ فقط یک `DATABASE_URL` لازم است.
- اما یک محدودیت واقعی وجود دارد که باید بدانید (بخش ۴).

---

## ۱) چرا Railway به‌تنهایی کافی نیست

از صفحه رسمی قیمت‌گذاری Railway (نوامبر ۲۰۲۶):

| پلن | هزینه | اعتبار | Managed Database |
|---|---|---|---|
| **Free** | $۰ | $۱ در ماه | **ندارد («Managed databases: No»)** |
| Hobby | $۵ در ماه | $۵ | دارد |
| Pro | $۲۰ در ماه | $۲۰ | دارد |

یعنی روی پلن رایگان Railway **هیچ دیتابیسی** نمی‌دهد — فقط سرویس اپ.
پس دیتابیس را از جای دیگری می‌گیریم: **Supabase Free**.

نکته مثبت: پلن Free کارت اعتباری نمی‌خواهد و سرویس «در صورت بی‌کاری می‌خوابد و با درخواست بیدار می‌شود».

---

## ۲) دیتابیس Postgres رایگان (Supabase) — انجام شد

پروژه Postgres ۱۷ روی پلن رایگان ساخته شد:

```
Project: nexvora-db
Region : eu-central-1 (فرانکفورت)
Ref    : luuiyyxlucutvvgwtmyd
Host   : db.luuiyyxlucutvvgwtmyd.supabase.co
Plan   : free
```

### رشته اتصال برای Railway

از پنل Supabase → **Connect** یکی از این دو را بردارید:

**الف) Pooler / Transaction (پیشنهادی برای Railway)**

```
postgresql://postgres.luuiyyxlucutvvgwtmyd:<PASSWORD>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres
```

**ب) Direct connection**

```
postgresql://postgres:<PASSWORD>@db.luuiyyxlucutvvgwtmyd.supabase.co:5432/postgres
```

> رمز دیتابیس در زمان ساخت تنظیم شد. اگر گم شد: Supabase → Settings → Database → Reset password.

`s slmode=require` را لازم نیست دستی اضافه کنید؛ کد خودش برای میزبان‌های Supabase اضافه می‌کند
(تست `test_supabase_urls_get_ssl_enforced`).

---

## ۳) متغیرهای محیطی روی Railway (پلن Free)

```
NEXVORA_ENV=production
NEXVORA_DATA_MODE=auto
SECRET_KEY=<۶۴ کاراکتر تصادفی>
COOKIE_SECURE=true

DATABASE_URL=postgresql://postgres.luuiyyxlucutvvgwtmyd:<PASSWORD>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres

TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_CHANNEL_ID=@your_channel
TELEGRAM_DRY_RUN=false

# داده بازار رایگان (OANDA حساب Practice رایگان است)
OANDA_API_TOKEN=<token>
OANDA_ENV=practice
```

**نکات مخصوص پلن رایگان Railway:**

- CPU هر سرویس حداکثر **۱ vCPU** و RAM حداکثر **۰.۵ گیگ** — برای این پروژه کافی است،
  ولی `numReplicas` را ۱ نگه دارید (هم به‌خاطر سقف پلن، هم برای جلوگیری از سیگنال تکراری).
- **هیچ Volume لازم نیست** چون دیتابیس روی Supabase است. این یعنی ۰.۵ گیگ محدودیت دیسک هم مشکلی نمی‌سازد.
- سرویس در بی‌کاری می‌خوابد و با اولین درخواست بیدار می‌شود.
  ⚠️ **پیامد مهم:** وقتی سرویس خواب است، اسکنر موتور و ارسال تلگرام هم اجرا نمی‌شوند.
  اگر می‌خواهید ۲۴ ساعته سیگنال بگیرید، باید پلن Hobby ($۵ در ماه) را بگیرید.
  برای راه‌اندازی و تست اولیه، پلن رایگان کاملاً کافی است.

---

## ۴) محدودیت‌هایی که باید بدانید (صادقانه)

| محدودیت | تأثیر |
|---|---|
| Supabase Free بعد از **۷ روز بی‌استفاده بودن** پروژه را pause می‌کند | دیتابیس از دست نمی‌رود، ولی باید از پنل Restore کنید |
| Supabase Free سقف فضای دیسک دارد (~۵۰۰ مگ) | این پروژه چند ده مگ بیشتر مصرف نمی‌کند (بدون تصاویر کارت) |
| Railway Free سرویس را می‌خواباند | ارسال ۲۴ ساعته سیگنال قطع می‌شود |
| حداقل تاخیر (cold start) | اولین درخواست بعد از خواب چند ثانیه طول می‌کشد |
| ۰.۵ گیگ RAM | بک‌تست ۱۸ ترکیب سنگین است؛ اولین بوت کمی کندتر می‌شود |

هیچ‌کدام از این‌ها برای «راه‌اندازی و گرفتن خروجی اولیه» مانع نیست. برای تولید جدی، $۵ در ماه
(Railway Hobby) تنها هزینه واقعی لازم است.

---

## ۵) بعد از دیپلوی — چک‌لیست

۱. `GET /api/v1/health` باید بدهد:

```json
{
  "status": "ok",
  "env": "production",
  "database": "ok",
  "persian_card_fonts": true,
  "telegram_configured": true,
  "policy_version": "nexvora-strict-2026.11.1"
}
```

اگر `database` چیزی جز `ok` بود، مشکل `DATABASE_URL` یا SSL است.
اگر `persian_card_fonts: false` بود، ایمیج فونت‌ها را ندارد.

۲. لاگ بوت باید این خط را داشته باشد:

```
[NEXVORA] schema upgraded: ...
```
یا اگر دیتابیس تازه است، هیچ خطی برای migration لازم نیست.

۳. `GET /api/v1/admin/telegram-health` → `mode` باید `LIVE` باشد.

۴. `GET /api/v1/analytics/qualifications` → `channel_rank` بین ۱ تا ۴ روی ترکیب‌های مجاز.

---

## ۶) اگر خواستید بعداً به Railway Postgres مهاجرت کنید

کد کاملاً مستقل از میزبان است؛ فقط دو گام:

```bash
# ۱. دامپ از Supabase
pg_dump "postgresql://postgres:<PASSWORD>@db.luuiyyxlucutvvgwtmyd.supabase.co:5432/postgres" \
  --no-owner --no-acl -f nexvora_backup.sql

# ۲. ریستور روی دیتابیس جدید Railway
psql "$RAILWAY_DATABASE_URL" -f nexvora_backup.sql
```

سپس فقط `DATABASE_URL` را عوض کنید و Redeploy بزنید. هیچ تغییر کدی لازم نیست.
