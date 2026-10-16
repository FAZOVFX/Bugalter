# FAZO CREATIVE GROUP BOT

Administrator uchun Telegram hisob-kitob boti. Buyurtma, to'lov, xarajat va jamoa haqi PostgreSQL da saqlanadi.

## Ishga tushirish

PowerShell:

```powershell
cd E:\FAZO-CREATIVE-GROUP-BOT
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.migrate
.\.venv\Scripts\python.exe -m app.main
```

`.env` faylida `BOT_TOKEN`, `ADMIN_ID` va `DATABASE_URL` bo'lishi kerak. Namuna qiymatlar `.env.example` da. Haqiqiy token va parolni nusxalamang va ulashmang.

## Imkoniyatlar

- Yangi buyurtma, buyurtmalar ro'yxati va qarzdorlar
- To'lov tarixi. Qarz = kelishilgan narx − jami to'lovlar
- Xarajatlar va jamoa haqi alohida. Hisobotda jamoa haqi ikki marta ayirilmaydi
- Kunlik va oylik hisobot. Buyurtma qiymati kassaga tushgan pul emas
- Excel: umumiy hisobot, buyurtmalar, to'lovlar, qarzdorlar, xarajatlar, jamoa to'lovlari
- Faqat `ADMIN_ID` moliyaviy ma'lumotni ko'radi

Har bir forma oxirida Saqlash tugmasi bor. Qayta bosilsa yozuv takrorlanmaydi. Bekor qilish har bosqichda bor.

## Tekshiruv

```powershell
.\.venv\Scripts\python.exe -m compileall app
.\.venv\Scripts\python.exe -m app.migrate
.\.venv\Scripts\python.exe tests\verify_accounting.py
```

`verify_accounting.py` sinov yozuvlarini commit qilmaydi.

Migratsiya mavjud jadvallarni o'chirmaydi. `DROP`, `TRUNCATE` va `drop_all` ishlatilmaydi.
