import os, hmac, hashlib, json, time, sqlite3, base64
from urllib.parse import parse_qsl
import httpx
from fastapi import FastAPI, Header, HTTPException, Request, UploadFile, File, Form
import asyncio, traceback
from fastapi.responses import FileResponse, HTMLResponse

BOT_TOKEN = os.environ["BOT_TOKEN"]
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
CF_ACCOUNT = os.environ.get("CF_ACCOUNT_ID", "")
CF_TOKEN = os.environ.get("CF_API_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me")
REPLICATE = os.environ.get("REPLICATE_API_TOKEN", "")
BOT_USER = ""
WELCOME = ("Привет! 👋 Это мини-приложение с двумя инструментами:\n\n"
           "🎨 Фото-стили: загрузи селфи и получи аниме, 3D-мультик, киберпанк, портрет маслом и другие образы.\n"
           "💬 ИИ-помощник: отвечает на вопросы, пишет тексты и придумывает идеи.\n\n"
           "🎁 30 кредитов в подарок, чтобы попробовать. Нажми кнопку ниже, чтобы открыть.")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

START_CREDITS, DAILY_BONUS, REF_BONUS = 30, 5, 10
COST = {"chat": 1, "photo": 10}
PACKS = {  # id: (credits, stars)
    "p100": (100, 100), "p350": (350, 300), "p1000": (1000, 750),
    "sub": (300, 400),  # Premium на 30 дней: безлимитный чат + 300 кредитов
}
STYLE_PROMPTS = {
    "Аниме": "Redraw this person as a polished anime character, keep the face recognizable",
    "3D-мультик": "Turn this person into a 3D animated movie character, keep the face recognizable",
    "Киберпанк": "Cyberpunk neon-lit portrait of this person, rainy futuristic city, keep the face recognizable",
    "Масло": "Classic oil painting portrait of this person, visible brush strokes, keep the face recognizable",
    "Обложка": "Glossy fashion magazine cover photo of this person, studio lighting, keep the face recognizable",
    "Я в 80": "Show this exact person at age 80, realistic aging, keep the identity",
}

app = FastAPI()
if DATABASE_URL:
    import psycopg2

    class PG:
        """Тонкая обёртка: те же запросы, что и для SQLite, но в Postgres."""
        def __init__(self): self._connect()

        def _connect(self):
            self.c = psycopg2.connect(DATABASE_URL); self.c.autocommit = True

        def execute(self, q, a=()):
            q = q.replace("?", "%s").replace("INTEGER", "BIGINT").replace("MAX(premium", "GREATEST(premium")
            if "INSERT OR IGNORE" in q:
                q = q.replace("INSERT OR IGNORE", "INSERT") + " ON CONFLICT DO NOTHING"
            for attempt in (1, 2):
                try:
                    cur = self.c.cursor(); cur.execute(q, a); return cur
                except (psycopg2.OperationalError, psycopg2.InterfaceError):
                    if attempt == 2: raise
                    self._connect()  # Neon закрывает соединение при простое

        def commit(self): pass

    db = PG()
else:
    db = sqlite3.connect(os.environ.get("DB_PATH", "data.db"), check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, credits INTEGER, last_daily TEXT, ref INTEGER, premium INTEGER DEFAULT 0)""")
db.execute("""CREATE TABLE IF NOT EXISTS pays(charge_id TEXT PRIMARY KEY)""")


def verify(init_data: str) -> dict:
    """Проверка подписи initData от Telegram. Без неё доверять user_id нельзя."""
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    got = data.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, got) or time.time() - int(data.get("auth_date", 0)) > 86400:
        raise HTTPException(401, "bad initData")
    user = json.loads(data["user"])
    user["start_param"] = data.get("start_param", "")
    return user


def get_user(init_data: str) -> dict:
    u = verify(init_data)
    row = db.execute("SELECT credits,last_daily FROM users WHERE id=?", (u["id"],)).fetchone()
    today = time.strftime("%Y-%m-%d")
    if not row:
        ref = int(u["start_param"][3:]) if u["start_param"].startswith("ref") and u["start_param"][3:].isdigit() else None
        db.execute("INSERT INTO users(id,credits,last_daily,ref) VALUES(?,?,?,?)", (u["id"], START_CREDITS, today, ref))
        if ref and ref != u["id"]:
            db.execute("UPDATE users SET credits=credits+? WHERE id=?", (REF_BONUS, ref))
    elif row[1] != today:
        db.execute("UPDATE users SET credits=credits+?, last_daily=? WHERE id=?", (DAILY_BONUS, today, u["id"]))
    db.commit()
    return u


def credits(uid): return db.execute("SELECT credits FROM users WHERE id=?", (uid,)).fetchone()[0]


def is_premium(uid):
    row = db.execute("SELECT premium FROM users WHERE id=?", (uid,)).fetchone()
    return bool(row and row[0] > time.time())


def charge(uid, kind):
    if kind == "chat" and is_premium(uid): return
    cur = db.execute("UPDATE users SET credits=credits-? WHERE id=? AND credits>=?", (COST[kind], uid, COST[kind]))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(402, "Недостаточно кредитов")


def refund(uid, kind):
    if kind == "chat" and is_premium(uid): return
    db.execute("UPDATE users SET credits=credits+? WHERE id=?", (COST[kind], uid)); db.commit()


@app.get("/")
def index(): return FileResponse("index.html")


@app.get("/privacy")
def privacy():
    return HTMLResponse("""<meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<body style="font:16px/1.5 system-ui;max-width:640px;margin:24px auto;padding:0 16px"><h2>Конфиденциальность</h2>
<p>Фото, которое ты загружаешь, отправляется сервису обработки изображений, возвращается тебе и не сохраняется на нашем сервере.</p>
<p>Сообщения чата передаются ИИ-сервису для ответа и не хранятся у нас. Мы храним только твой Telegram ID и баланс кредитов.</p>
<p>Загружай только свои фото или фото людей, которые согласны. Фото детей, откровенный и оскорбительный контент запрещены.</p>
<p>Платежи проходят через Telegram Stars. Вопросы и жалобы: напиши боту.</p>""")


@app.get("/api/me")
def me(x_init_data: str = Header()):
    global BOT_USER
    u = get_user(x_init_data)
    if not BOT_USER:
        BOT_USER = httpx.get(f"{API}/getMe").json()["result"]["username"]
    return {"credits": credits(u["id"]), "id": u["id"], "premium": is_premium(u["id"]),
            "app_link": f"https://t.me/{BOT_USER}?startapp="}


@app.post("/api/chat")
async def chat(req: Request, x_init_data: str = Header()):
    u = get_user(x_init_data)
    body = await req.json()
    msgs = body["messages"][-12:]
    while msgs and msgs[0]["role"] != "user": msgs = msgs[1:]
    charge(u["id"], "chat")
    try:
        sysmsg = ("Ты дружелюбный помощник в Telegram. Отвечай кратко, на языке пользователя. "
                  "Отказывайся от откровенного, жестокого и незаконного контента.")
        async with httpx.AsyncClient(timeout=60) as c:
            if GEMINI_KEY:
                r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                    headers={"x-goog-api-key": GEMINI_KEY},
                    json={"systemInstruction": {"parts": [{"text": sysmsg}]},
                          "contents": [{"role": "model" if m["role"] == "assistant" else "user",
                                        "parts": [{"text": m["content"]}]} for m in msgs]})
                r.raise_for_status()
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            else:
                r = await c.post("https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"},
                    json={"model": "claude-sonnet-5-5", "max_tokens": 800, "system": sysmsg, "messages": msgs})
                r.raise_for_status()
                text = r.json()["content"][0]["text"]
    except Exception:
        traceback.print_exc()
        refund(u["id"], "chat"); raise HTTPException(502, "ИИ не ответил, кредит возвращён")
    return {"text": text, "credits": credits(u["id"])}


async def photo_replicate(image: bytes, style: str) -> bytes:
    """Replicate: FLUX Kontext (платно, качество выше)."""
    hdr = {"Authorization": f"Bearer {REPLICATE}"}
    uri = "data:image/jpeg;base64," + base64.b64encode(image).decode()
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post("https://api.replicate.com/v1/models/black-forest-labs/flux-kontext-pro/predictions",
            headers={**hdr, "Prefer": "wait"},
            json={"input": {"prompt": STYLE_PROMPTS[style], "input_image": uri,
                            "output_format": "png", "safety_tolerance": 1}})
        r.raise_for_status(); p = r.json()
        for _ in range(40):
            if p["status"] == "succeeded": break
            if p["status"] in ("failed", "canceled"): raise RuntimeError(p.get("error"))
            await asyncio.sleep(2)
            p = (await c.get(p["urls"]["get"], headers=hdr)).json()
        out = p["output"]
        return (await c.get(out if isinstance(out, str) else out[0])).content


CF_STYLE = {  # (описание стиля, сила изменения 0..1)
    "Аниме": ("anime style portrait, vibrant colors, clean lineart, detailed", 0.65),
    "3D-мультик": ("3d pixar style animated character portrait, soft lighting", 0.65),
    "Киберпанк": ("cyberpunk portrait, neon lights, futuristic city at night, cinematic", 0.7),
    "Масло": ("classic oil painting portrait, visible brush strokes, museum quality", 0.7),
    "Обложка": ("glossy magazine cover photo, studio lighting, high detail", 0.55),
    "Я в 80": ("portrait of the same person at age 80, wrinkles, grey hair, realistic photo", 0.6),
}


async def photo_cloudflare(image: bytes, style: str) -> bytes:
    """Cloudflare Workers AI (есть бесплатная суточная квота)."""
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(image)).convert("RGB")
    im.thumbnail((512, 512))
    w, h = max(64, im.width // 8 * 8), max(64, im.height // 8 * 8)
    buf = io.BytesIO(); im.resize((w, h)).save(buf, "JPEG", quality=90)
    prompt, strength = CF_STYLE[style]
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/@cf/runwayml/stable-diffusion-v1-5-img2img",
            headers={"Authorization": f"Bearer {CF_TOKEN}"},
            json={"prompt": prompt, "negative_prompt": "deformed, blurry, nsfw, nude, extra fingers",
                  "image_b64": base64.b64encode(buf.getvalue()).decode(), "width": w, "height": h,
                  "strength": strength, "num_steps": 20, "guidance": 7.5})
        if "image" not in r.headers.get("content-type", ""):
            raise RuntimeError(r.text[:300])
        return r.content


async def run_photo_model(image: bytes, style: str) -> bytes:
    if REPLICATE: return await photo_replicate(image, style)
    if CF_ACCOUNT and CF_TOKEN: return await photo_cloudflare(image, style)
    raise RuntimeError("Не подключён провайдер фото (REPLICATE_API_TOKEN или CF_ACCOUNT_ID + CF_API_TOKEN)")


@app.post("/api/photo")
async def photo(style: str = Form(), file: UploadFile = File(...), x_init_data: str = Header()):
    u = get_user(x_init_data)
    if style not in STYLE_PROMPTS: raise HTTPException(400, "Неизвестный стиль")
    img = await file.read()
    if len(img) > 8_000_000: raise HTTPException(413, "Файл больше 8 МБ")
    charge(u["id"], "photo")
    try:
        out = await run_photo_model(img, style)
    except Exception:
        traceback.print_exc()
        refund(u["id"], "photo"); raise HTTPException(502, "Не получилось обработать фото, кредиты возвращены")
    return {"image": "data:image/png;base64," + base64.b64encode(out).decode(), "credits": credits(u["id"])}


@app.post("/api/invoice")
async def invoice(req: Request, x_init_data: str = Header()):
    u = get_user(x_init_data)
    pack = (await req.json())["pack"]
    if pack not in PACKS: raise HTTPException(400)
    cr, stars = PACKS[pack]
    body = {"title": "Premium на месяц" if pack == "sub" else f"{cr} кредитов",
            "description": "Безлимитный чат и 300 кредитов каждый месяц" if pack == "sub" else "Пополнение баланса AI Studio",
            "payload": f"{pack}:{u['id']}", "provider_token": "", "currency": "XTR",
            "prices": [{"label": "AI Studio", "amount": stars}]}
    if pack == "sub": body["subscription_period"] = 2592000
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{API}/createInvoiceLink", json=body)
    return {"link": r.json()["result"]}


@app.post("/webhook/{secret}")
async def webhook(secret: str, req: Request):
    if secret != WEBHOOK_SECRET: raise HTTPException(403)
    up = await req.json()
    async with httpx.AsyncClient() as c:
        if "pre_checkout_query" in up:
            await c.post(f"{API}/answerPreCheckoutQuery",
                         json={"pre_checkout_query_id": up["pre_checkout_query"]["id"], "ok": True})
        msg = up.get("message", {})
        if "successful_payment" in msg:
            p = msg["successful_payment"]
            pack, uid = p["invoice_payload"].split(":")
            if db.execute("INSERT OR IGNORE INTO pays VALUES(?)", (p["telegram_payment_charge_id"],)).rowcount:
                db.execute("UPDATE users SET credits=credits+? WHERE id=?", (PACKS[pack][0], int(uid)))
                if pack == "sub":
                    db.execute("UPDATE users SET premium=MAX(premium,?)+? WHERE id=?", (int(time.time()), 30 * 86400, int(uid)))
                db.commit()
                await c.post(f"{API}/sendMessage", json={"chat_id": int(uid), "text": f"Готово: +{PACKS[pack][0]} кредитов ✨"})
        elif msg.get("text", "").startswith("/start"):
            await c.post(f"{API}/sendMessage", json={"chat_id": msg["chat"]["id"],
                "text": WELCOME,
                "reply_markup": {"inline_keyboard": [[{"text": "Открыть приложение",
                    "web_app": {"url": os.environ["APP_URL"]}}]]}})
    return {"ok": True}
