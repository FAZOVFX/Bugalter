import asyncio

from sqlalchemy import text

from app.database import Base, engine
from app.logsafe import safe_db_message, scrub

# Mavjud jadvallar va yozuvlar saqlanadi. DROP, TRUNCATE va drop_all ishlatilmaydi.
STATEMENTS = (
    "ALTER TABLE orders ALTER COLUMN phone TYPE VARCHAR(40)",
    "ALTER TABLE orders ALTER COLUMN total_price TYPE NUMERIC(14, 2)",
    "ALTER TABLE orders ALTER COLUMN paid_amount TYPE NUMERIC(14, 2)",
    "ALTER TABLE orders ALTER COLUMN phone SET DEFAULT ''",
    "ALTER TABLE orders ALTER COLUMN service SET DEFAULT ''",
    "ALTER TABLE orders ALTER COLUMN service TYPE VARCHAR(500)",
    "ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'Yangi'",
    "ALTER TABLE orders ALTER COLUMN paid_amount SET DEFAULT 0",
    "ALTER TABLE orders ALTER COLUMN notes SET DEFAULT ''",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS event_checked_on DATE",
    """
    UPDATE orders
    SET event_checked_on = event_date
    WHERE event_date IS NOT NULL
      AND event_date < (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Tashkent')::date - INTERVAL '1 day'
      AND event_checked_on IS NULL
    """,
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_number VARCHAR(32)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS orders_order_number_key ON orders (order_number)",
    "CREATE UNIQUE INDEX IF NOT EXISTS orders_idempotency_key_key ON orders (idempotency_key)",
    """
    UPDATE orders
    SET order_number = 'FCG-' || LPAD(id::text, 5, '0')
    WHERE order_number IS NULL OR order_number = ''
    """,
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS order_id INTEGER REFERENCES orders(id)",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS amount NUMERIC(14, 2) DEFAULT 0",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS method VARCHAR(40) DEFAULT 'Naqd'",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS note TEXT DEFAULT ''",
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'payments'
          AND column_name = 'created_at'
      ) THEN
        UPDATE payments
        SET paid_at = created_at
        WHERE paid_at IS NULL AND created_at IS NOT NULL;
      END IF;
    END $$;
    """,
    "ALTER TABLE payments ALTER COLUMN method SET DEFAULT 'Naqd'",
    "ALTER TABLE payments ALTER COLUMN note SET DEFAULT ''",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS payments_idempotency_key_key ON payments (idempotency_key)",
    "CREATE INDEX IF NOT EXISTS ix_payments_order_id ON payments (order_id)",
    "CREATE INDEX IF NOT EXISTS ix_payments_paid_at ON payments (paid_at)",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS category VARCHAR(120) DEFAULT ''",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS amount NUMERIC(14, 2) DEFAULT 0",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS description TEXT DEFAULT ''",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS spent_at TIMESTAMPTZ",
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'expenses'
          AND column_name = 'created_at'
      ) THEN
        UPDATE expenses
        SET spent_at = created_at
        WHERE spent_at IS NULL AND created_at IS NOT NULL;
      END IF;
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'expenses'
          AND column_name = 'note'
      ) THEN
        UPDATE expenses
        SET description = note
        WHERE description IS NULL AND note IS NOT NULL;
      END IF;
    END $$;
    """,
    "ALTER TABLE expenses ALTER COLUMN description SET DEFAULT ''",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS expenses_idempotency_key_key ON expenses (idempotency_key)",
    "CREATE INDEX IF NOT EXISTS ix_expenses_spent_at ON expenses (spent_at)",
    "ALTER TABLE team_members ADD COLUMN IF NOT EXISTS name VARCHAR(200) DEFAULT ''",
    "ALTER TABLE team_members ADD COLUMN IF NOT EXISTS role VARCHAR(120) DEFAULT 'Xodim'",
    "ALTER TABLE team_members ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT true",
    "ALTER TABLE team_members ALTER COLUMN role SET DEFAULT 'Xodim'",
    "ALTER TABLE team_members ADD COLUMN IF NOT EXISTS phone VARCHAR(40) NOT NULL DEFAULT ''",
    "ALTER TABLE team_members ALTER COLUMN active SET DEFAULT true",
    "ALTER TABLE team_payments ADD COLUMN IF NOT EXISTS member_id INTEGER REFERENCES team_members(id)",
    "ALTER TABLE team_payments ADD COLUMN IF NOT EXISTS order_id INTEGER REFERENCES orders(id)",
    "ALTER TABLE team_payments ADD COLUMN IF NOT EXISTS amount NUMERIC(14, 2) DEFAULT 0",
    "ALTER TABLE team_payments ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ",
    "ALTER TABLE team_payments ADD COLUMN IF NOT EXISTS note TEXT DEFAULT ''",
    """
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'team_payments'
          AND column_name = 'created_at'
      ) THEN
        UPDATE team_payments
        SET paid_at = created_at
        WHERE paid_at IS NULL AND created_at IS NOT NULL;
      END IF;
    END $$;
    """,
    "ALTER TABLE team_payments ALTER COLUMN note SET DEFAULT ''",
    "ALTER TABLE team_payments ADD COLUMN IF NOT EXISTS work_for VARCHAR(200) NOT NULL DEFAULT ''",
    "ALTER TABLE team_payments ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
    "ALTER TABLE team_payments ADD COLUMN IF NOT EXISTS debt_id INTEGER REFERENCES team_debts(id)",
    "CREATE INDEX IF NOT EXISTS ix_team_payments_debt_id ON team_payments (debt_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS team_payments_idempotency_key_key ON team_payments (idempotency_key)",
    "CREATE INDEX IF NOT EXISTS ix_team_payments_paid_at ON team_payments (paid_at)",
    "CREATE INDEX IF NOT EXISTS ix_team_payments_member_id ON team_payments (member_id)",
    "CREATE INDEX IF NOT EXISTS ix_team_payments_order_id ON team_payments (order_id)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS client_name VARCHAR(200) DEFAULT ''",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
    "CREATE INDEX IF NOT EXISTS ix_orders_created_at ON orders (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_orders_client_name ON orders (client_name)",
    """
    UPDATE orders AS target
    SET paid_amount = COALESCE((
        SELECT SUM(payment.amount)
        FROM payments AS payment
        WHERE payment.order_id = target.id
    ), 0)
    WHERE target.paid_amount IS DISTINCT FROM COALESCE((
        SELECT SUM(payment.amount)
        FROM payments AS payment
        WHERE payment.order_id = target.id
    ), 0)
    """,
)


async def migrate_schema() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for statement in STATEMENTS:
            await connection.execute(text(statement))


async def migrate() -> None:
    try:
        await migrate_schema()
    except Exception as exc:
        print(safe_db_message(exc))
        print(scrub(f"{type(exc).__name__}: {exc}"))
        raise SystemExit(1) from None
    else:
        print("Migratsiya muvaffaqiyatli yakunlandi. Mavjud yozuvlar o'chirilmadi.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
