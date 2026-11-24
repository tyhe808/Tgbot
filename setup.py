"""Один раз после запуска сервера: python setup.py  (читает .env)"""
import os, httpx
for l in open(".env", encoding="utf-8"):
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1); os.environ[k.strip()] = v.split("#")[0].strip()
T, URL, SEC = os.environ["BOT_TOKEN"], os.environ["APP_URL"].rstrip("/"), os.environ["WEBHOOK_SECRET"]
api = lambda m, **j: httpx.post(f"https://api.telegram.org/bot{T}/{m}", json=j).json()
print("webhook:", api("setWebhook", url=f"{URL}/webhook/{SEC}", allowed_updates=["message", "pre_checkout_query"]))
print("menu:", api("setChatMenuButton", menu_button={"type": "web_app", "text": "Открыть", "web_app": {"url": URL}}))
print("description:", api("setMyDescription", description=(
    "Фото-стили и ИИ-помощник в одном приложении.\n\n"
    "🎨 Загрузи селфи и получи аниме, 3D-мультик, киберпанк, портрет маслом или «себя в 80 лет».\n"
    "💬 Спрашивай что угодно, проси написать текст или придумать идею.\n\n"
    "🎁 30 кредитов в подарок. Нажми «Старт» и открой приложение.")))
print("about:", api("setMyShortDescription", short_description="ИИ-фото в разных стилях и умный помощник. 30 кредитов в подарок 🎁"))
u = api("getMe")["result"]["username"]
print(f"\nГотово. Открой бота: https://t.me/{u}  и нажми /start")
