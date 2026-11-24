# راهنمای استقرار (Deploy) روی Railway — آنلاین ۲۴/۷

پروژه **NEXVORA** به‌صورت کامل برای استقرار **تک‌سرویسه** روی **Railway** آماده شده است (`Dockerfile` دو‌مرحله‌ای + `railway.toml`). در این حالت، Railway هم اپلیکیشن **PWA**، هم **API/WebSocket**، هم **موتور Trading Hub 3.0 + پیگیری پوزیشن** و هم **ربات تلگرام** را روی یک آدرس HTTPS دائمی اجرا می‌کند.

---

## گام ۱: ساخت پروژه و دیتابیس در Railway

1. وارد [railway.app](https://railway.app) شوید و **New Project → Deploy from GitHub Repo** را انتخاب کنید.
2. مخزن `behnam273/Nexvora-Hub3-WE` را انتخاب کنید. Railway به‌صورت خودکار فایل‌های `railway.toml` و `Dockerfile` را شناسایی می‌کند.
3. برای ذخیره دائمی کاربران، تاریخچه معاملات، بک‌تست‌ها و اخبار، یکی از دو روش زیر را انتخاب کنید:
   - **روش پیشنهادی A (ساده‌ترین)**: داخل همین پروژه Railway روی **+ New → Database → Add PostgreSQL** کلیک کنید. سپس در بخش Variables سرویس NEXVORA مقدار زیر را ست کنید:
     ```env
     DATABASE_URL=${{Postgres.DATABASE_URL}}
     ```
   - **روش B (اتصال به Supabase)**: رشته اتصال `Transaction Pooler` یا `Direct Connection` دیتابیس Supabase را در متغیر `DATABASE_URL` قرار دهید (فرمت `postgres://` و `postgresql://` هر دو به‌صورت خودکار پشتیبانی می‌شوند).

---

## گام ۲: تنظیم متغیرهای محیطی (Variables) در سرویس NEXVORA

در تب **Variables** سرویس NEXVORA در Railway این مقادیر را وارد کنید:

### ضروری برای امنیت و اجرای پروداکشن
```env
NEXVORA_ENV=production
DATABASE_URL=${{Postgres.DATABASE_URL}}
SECRET_KEY=یک-رشته-تصادفی-حداقل-۶۴-کاراکتری-قوی-وارد-کنید
INITIAL_ADMIN_EMAIL=admin@yourdomain.com
INITIAL_ADMIN_PASSWORD=یک-رمز-عبور-قوی-حداقل-۱۲-کاراکتری
COOKIE_SECURE=true
COOKIE_SAMESITE=lax
```

### اتصال به بازار واقعی فارکس و طلا (با Failover خودکار چندتأمین‌کننده)
```env
# auto = استفاده از زنجیره APIهای زنده و بازگشت شفاف به دمو در صورت قطع کامل اینترنت
# live = فقط داده زنده واقعی
NEXVORA_DATA_MODE=auto

# ترتیب سوییچ خودکار هنگام محدود شدن هر API (در صورت 429 فوری به بعدی سوییچ می‌کند):
MARKET_DATA_PROVIDERS=oanda,biquote,twelvedata,yahoo,alphavantage

# بدون نیاز به هیچ کلید API: biquote.io (۱۵٬۰۰۰ درخواست/دقیقه برای فارکس و طلا) و Yahoo Finance خودکار فعال‌اند!

# اختیاری (بهترین کیفیت بروکری رایگان — مشابه فید TradingView):
OANDA_API_TOKEN=
OANDA_ENV=practice

# اختیاری (در صورت استفاده از Twelve Data می‌توانید چند کلید را با کاما بدهید تا خودکار بچرخند):
TWELVE_DATA_API_KEY=
TWELVE_DATA_API_KEYS=
```

### اتصال به کانال تلگرام (سیگنال + پیگیری پوزیشن + اخبار High Impact)
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNO...
TELEGRAM_CHANNEL_ID=@your_channel_username_or_numeric_id
TELEGRAM_DRY_RUN=false
```
> **نکته**: ربات ساخته‌شده از طریق `@BotFather` را حتماً به‌عنوان **Admin** با دسترسی **Post Messages** به کانال تلگرام اضافه کنید.

### اختیاری: ترجمه و تحلیل هوشمندتر اخبار فارسی با LLM
```env
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

---

## گام ۳: فعال‌سازی دامنه عمومی (Networking)

1. در سرویس NEXVORA به تب **Settings → Networking → Public Networking** بروید و روی **Generate Domain** کلیک کنید (مثلاً `nexvora-hub3.up.railway.app`).
2. Railway به‌صورت خودکار متغیر `RAILWAY_PUBLIC_DOMAIN` را به کانتینر می‌دهد و NEXVORA به‌طور خودکار:
   - CORS را برای دامنه HTTPS شما تنظیم می‌کند؛
   - لینک‌های مستقیم داخل پیام‌های کانال تلگرام را به آدرس واقعی PWA شما متصل می‌کند؛
   - Healthcheck را روی `/api/v1/health` بررسی می‌کند.

---

## نکات مهم عملیاتی در Railway

- **تعداد Replica / Worker**: در `railway.toml` مقدار `numReplicas = 1` و در `Dockerfile` مقدار `--workers 1` تنظیم شده است تا موتور اسکن Trading Hub 3.0 و ربات تلگرام فقط یک نمونه فعال داشته باشند و سیگنال تکراری ارسال نشود.
- **نصب PWA روی موبایل**: پس از بالا آمدن دامنه HTTPS، صفحه را در Chrome (اندروید) یا Safari (iOS) باز کنید و گزینه **Add to Home Screen** را بزنید تا اپلیکیشن NEXVORA مثل اپ بومی نصب شود.
- **تست فوری پس از دیپلوی**:
  1. آدرس `https://<your-domain>/api/v1/health` را باز کنید (باید `status: "ok"` با ۶ نماد مجاز برگرداند).
  2. با ایمیل و رمز ادمین وارد PWA شوید، به بخش **پنل ادمین** بروید و دکمه‌های **تست تلگرام**، **به‌روزرسانی ماتریس Win Rate** و **دریافت اخبار** را اجرا کنید.
