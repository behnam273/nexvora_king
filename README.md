# NEXVORA — سیستم جامع سیگنال‌دهی Trading Hub 3.0، پیگیری پوزیشن، هوش خبری فارسی و PWA

**NEXVORA** یک پلتفرم کامل معاملاتی و پایش سیگنال فارکس و طلا است که بر پایه منطق اصلی **Trading Hub 3.0 (`hub3.txt`)** به همراه لایه فیلتر سخت‌گیرانه **High Accuracy** ساخته شده است.

---

## ویژگی‌های کلیدی

1. **محدوده انحصاری ۶ نماد مجاز (Strict Instrument Guard)**:
   - `EURUSD`، `GBPUSD`، `USDJPY`، `AUDUSD`، `EURGBP`، `XAUUSD`
   - هر نماد خارج از این فهرست در لایه بک‌اند، اسکنر و API رد می‌شود.
2. **دسته‌بندی ۳ تایم‌فریم بر اساس سطح ریسک**:
   - **`4H`** — حالت امن (`SAFE`)
   - **`15m`** — ریسک متوسط (`MEDIUM_RISK`)
   - **`5m`** — ریسک بالا (`HIGH_RISK`)
3. **هسته Trading Hub 3.0 + فیلترهای سخت‌گیرانه برای حداکثر Win Rate**:
   - ساختار بازار (`CHoCH` / `BOS`)، سوئیپ نقدینگی (`Liquidity Sweep`)، ایندیوسمنت (`IDM`)، زون‌های `POI` (Order Block + FVG) و `Premium / Discount`
   - هم‌جهتی دوگانه با روند تایم‌فریم بالاتر (`HTF Dual-Bias` + `EMA200`)، فیلتر قدرت روند (`ADX >= 25`)، بدنه قوی `CHoCH`، گارد اسپایک و نوسان مرده، فیلتر سشن لندن/نیویورک و گارد همبستگی ارزی
   - مدیریت سود ۳مرحله‌ای: **`TP1 = 2R`** (خروج ۵۰٪ + انتقال SL به سر‌به‌سر `BE`)، **`TP2 = 3R`** (خروج ۳۰٪ + انتقال SL به `TP1`)، **`TP3 = 5R`** (خروج ۲۰٪ نهایی) — قابل تنظیم در پنل ادمین
4. **دروازه بک‌تست صلاحیت کانال تلگرام (۱۸ ترکیب = ۶ نماد × ۳ تایم‌فریم)**:
   - موتور به‌صورت Rolling روی هر ۱۸ ترکیب بک‌تست می‌گیرد و تنها نمادها/تایم‌فریم‌هایی که از آستانه **Win Rate** و **Profit Factor** عبور کنند مجوز ارسال به کانال تلگرام می‌گیرند.
5. **پیگیری کامل چرخه عمر پوزیشن (Position Tracking)**:
   - ردیابی لحظه‌ای از وضعیت `PENDING_LIMIT` تا `ACTIVE`، محاسبه پیوسته `Floating R/Pips/USD`، ثبت رویدادهای `TP1_HIT + MOVE_SL_BE`، `TP2_HIT + MOVE_SL_TP1`، `TP3_HIT`، `SL_HIT`، `BE_EXIT` و `EXPIRED`
   - انتشار خودکار به‌صورت **Reply روی پیام سیگنال اصلی** در کانال تلگرام و نمایش لحظه‌ای در تایم‌لاین PWA (از طریق WebSocket)
6. **هوش خبری بازارهای مالی به فارسی با درصد تاثیر روی بازار**:
   - دریافت RSS منابع معتبر (FXStreet، ForexLive، Investing.com، Federal Reserve، ECB، BoE)، حذف اخبار تکراری با کلید یکتا (SHA-256)
   - محاسبه ۵ امتیاز مستقل (اهمیت، نوسان، ارتباط ارزی، جهت اثر و ریسک روی معاملات باز) و درصد تاثیر کل (`0–100%`)
   - پشتیبانی از ترجمه/خلاصه‌سازی هوشمند با کلید اختیاری LLM (`LLM_API_KEY`) و موتور NLP بومی فارسی
7. **NEXVORA PWA (فارسی RTL، تیره + طلایی، امن و نصب‌پذیر)**:
   - احراز هویت با کوکی `HttpOnly` + `SameSite=Lax`، حفاظت `CSRF`، رمزنگاری پسورد با `Argon2id`، محدودسازی نرخ درخواست، کنترل نقش‌ها (`RBAC`)، احراز هویت دومرحله‌ای (`TOTP MFA`)، مدیریت نشست‌های فعال، لاگ ممیزی (`Audit Log`)، و Service Worker امن که هرگز داده‌های `/api/*` را کش نمی‌کند.

---

## ساختار پروژه

```text
├── backend/
│   ├── app/
│   │   ├── api/            # روترهای REST v1 (auth, dashboard, trades, analytics, news, market, notifications, admin)
│   │   ├── engine/         # هسته Trading Hub 3.0، بک‌تستر، پیگیری پوزیشن، تامین‌کننده داده بازار و زمان‌بند
│   │   ├── services/       # موتور اخبار فارسی، ربات تلگرام، آنالیتیکس KPI و WebSocket Hub
│   │   ├── config.py       # تنظیمات محیطی، ۶ نماد مجاز و ۳ سطح ریسک تایم‌فریم
│   │   ├── models.py       # مدل‌های SQLAlchemy (سازگار با SQLite و PostgreSQL/Supabase)
│   │   ├── security.py     # Argon2id، کوکی سشن، CSRF، RBAC، Rate Limit، ضد XSS و ضد SSRF
│   │   └── main.py         # نقطه ورود FastAPI و هدرهای امنیتی
│   ├── tests/              # تست‌های جامع هسته استراتژی، پیگیری پوزیشن، اخبار و امنیت
│   ├── .env.example        # نمونه متغیرهای محیطی (کلیدها را اینجا تنظیم کنید)
│   └── requirements.txt
├── frontend/               # اپلیکیشن React + TypeScript + Tailwind + Lightweight Charts (PWA)
└── docs/
    └── ARCHITECTURE_AND_SECURITY.md
```

---

## راه‌اندازی سریع (توسعه و دمو)

### ۱. بک‌اند (FastAPI)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> به‌صورت پیش‌فرض در محیط بدون اینترنت/کلید API، سیستم در حالت شفاف `LIVE_WITH_DEMO_FALLBACK` (با برچسب صریح **بازپخش آزمایشی / DEMO_REPLAY**) اجرا می‌شود و هیچ داده زنده جعلی تولید نمی‌کند.

### ۲. فرانت‌اند (PWA)

```bash
cd frontend
npm install
npm run dev
```

رابط کاربری روی پورت `5173` در دسترس است و درخواست‌های `/api` و `/ws` را خودکار به بک‌اند روی پورت `8000` پراکسی می‌کند.

### حساب‌های پیش‌فرض (محیط توسعه)

| نقش | ایمیل | رمز عبور پیش‌فرض |
|---|---|---|
| مدیر سیستم (`SUPER_ADMIN`) | `admin@nexvora.local` | `NexvoraAdmin!2026` |
| کاربر عادی (`USER`) | `trader@nexvora.local` | `NexvoraTrader!2026` |

*(در محیط پروداکشن حتماً مقدار `INITIAL_ADMIN_PASSWORD` و `SECRET_KEY` را در `.env` یا Variables سرویس Railway تغییر دهید.)*

---

## استقرار آنلاین ۲۴/۷ روی Railway (توصیه‌شده)

فایل‌های `Dockerfile` (دو‌مرحله‌ای Node + Python)، `.dockerignore` و `railway.toml` آماده هستند تا کل پروژه (PWA + API + WebSocket + موتور Trading Hub 3.0 + ربات تلگرام) به‌صورت **تک‌سرویسه** روی Railway اجرا شود.

راهنمای گام‌به‌گام کامل را در [`docs/RAILWAY_DEPLOY.md`](docs/RAILWAY_DEPLOY.md) بخوانید.

## اتصال به داده‌های زنده و کانال تلگرام (Production)

در فایل `backend/.env` یا تب **Variables** در Railway مقادیر زیر را وارد کنید:

```env
NEXVORA_ENV=production
COOKIE_SECURE=true
COOKIE_SAMESITE=lax
SECRET_KEY=your-64-char-random-secret
INITIAL_ADMIN_EMAIL=admin@yourdomain.com
INITIAL_ADMIN_PASSWORD=YourStrongAdminPassword!2026

# دیتابیس پروداکشن (Railway PostgreSQL یا Supabase)
DATABASE_URL=postgresql+psycopg2://USER:PASS@HOST:5432/nexvora

# حالت داده بازار: auto | live | demo
NEXVORA_DATA_MODE=live
TWELVE_DATA_API_KEY=your_free_twelvedata_key

# کانال تلگرام (سیگنال + پیگیری پوزیشن + اخبار High Impact)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHANNEL_ID=@your_channel_or_chat_id
TELEGRAM_DRY_RUN=false

# اختیاری: ترجمه و تحلیل هوشمندتر اخبار فارسی با OpenAI-compatible LLM
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

---

## اجرای تست‌ها

```bash
# تست‌های بک‌اند (استراتژی Trading Hub 3.0، بک‌تست، پیگیری پوزیشن، اخبار فارسی و امنیت)
cd backend && .venv/bin/pytest -v

# بررسی تایپ و بیلد تولیدی فرانت‌اند PWA
cd frontend && npm run typecheck && npm run build
```
