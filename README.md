# Uzum Plus — shaxsiy analitika dashboard

4 ta Uzum do'kon uchun avtomatik sync qiluvchi shaxsiy analitika tizimi: veb-dashboard
(kompyuter/telefon brauzeridan) + Telegram bot.

To'liq bosqichma-bosqich joylashtirish yo'riqnomasi: **docs/Deployment_Qollanmasi.docx**

## Papka tuzilishi

```
uzum-dashboard/
  db/schema.sql          - Postgres/Supabase jadval sxemasi
  backend/
    uzum_client.py        - Uzum Seller API klienti (Authorization header, endpointlar)
    db.py                 - Supabase ulanishi
    queries.py             - dashboard va bot ishlatadigan umumiy SQL so'rovlar
    sync.py                - Uzum API -> Postgres sync jarayoni (har 4 do'kon uchun)
    main.py                - FastAPI server: login, /api/summary, /api/hourly,
                              /api/sales-stock, /api/expenses, /api/costs, /api/shops,
                              /api/sync/run, + frontend'ni serve qiladi
    requirements.txt, Procfile
  frontend/
    index.html             - bitta HTML+JS dashboard (Chart.js), backend orqali serve qilinadi
  telegram_bot/
    bot.py                 - /start /today /month /stock /expenses + kunlik avtomatik hisobot
    requirements.txt
  docs/
    Deployment_Qollanmasi.docx  - Supabase + Railway + BotFather bo'yicha to'liq qo'llanma
```

## Qisqacha oqim

1. Supabase'da baza yaratish, `db/schema.sql` ni ishga tushirish.
2. Railway'da `backend/` ni deploy qilish (env: `DATABASE_URL`, `DASHBOARD_PASSWORD`, `DASHBOARD_TOKEN`).
3. Dashboard ochilgach, "Do'konlar" bo'limidan 4 ta Uzum do'konining shop ID va API tokenini kiritish.
4. "Sync qilish" tugmasi bilan birinchi ma'lumotlarni tortish (keyin avtomatik, har 30 daqiqada).
5. "Tannarx" bo'limida har mahsulot uchun sebestoimostni kiritish (sof foyda shundan hisoblanadi).
6. Railway'da `telegram_bot/` uchun alohida service ochib deploy qilish (env: `DATABASE_URL`,
   `TELEGRAM_BOT_TOKEN`, `BOT_REGISTER_CODE`).
7. Telegramda botga `/start MAXFIY_SOZ` yozib ro'yxatdan o'tish.

Har bir bosqichning screenshot bilan batafsil ko'rsatmasi `docs/Deployment_Qollanmasi.docx` faylida.

## Muhim eslatma

Uzum Seller API'ning aniq javob maydonlari (masalan buyurtma/mahsulot ichidagi kalit nomlari)
rasmiy Swagger sxemasi asosida yozilgan, lekin real token bilan sinovdan o'tkazilmagan (bu
loyihani tuzish jarayonida real API tokeni mavjud emas edi). Birinchi real sync'dan keyin
agar ma'lumotlar noto'g'ri joylashsa, `backend/sync.py` dagi `.get("...")` kalitlarini haqiqiy
javob namunasiga qarab bir marta moslashtirish kifoya.
