# AI Studio: бесплатный запуск

Всё работает на бесплатных сервисах: Render (сервер), Neon (база с балансами), Google Gemini (чат), Cloudflare Workers AI (фото).

Пошаговая инструкция была в чате. Коротко, что вставить в переменные окружения на Render (см. `.env.example`):
BOT_TOKEN, WEBHOOK_SECRET, APP_URL, GEMINI_API_KEY, CF_ACCOUNT_ID, CF_API_TOKEN, DATABASE_URL.

После деплоя поставь вебхук (ссылка setWebhook из инструкции или `python setup.py`).

Лучшее качество за деньги: добавь REPLICATE_API_TOKEN (фото) и/или ANTHROPIC_API_KEY (чат), они подхватятся автоматически.
Цены и бонусы: COST, PACKS, START_CREDITS в `server.py`. Если ошибки, смотри Logs на Render.
