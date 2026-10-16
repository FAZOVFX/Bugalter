import asyncio
from typing import NamedTuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.database import Base, engine
from app.logsafe import safe_db_message, scrub

# Mavjud jadvallar va yozuvlar saqlanadi. DROP, TRUNCATE va drop_all ishlatilmaydi.
#
# Eski bazada ba'zi ustunlar yo'q. ALTER COLUMN ... SET DEFAULT shunday ustunga
# tegsa, PostgreSQL "column does not exist" bilan to'xtaydi. Avval haqiqiy
# ustunlar tekshiriladi, yo'q bo'lsa modeldagi tur bilan qo'shiladi va shundan
# keyingina DEFAULT o'rnatiladi.


class ColumnDefault(NamedTuple):
    table: str
    column: str
    column_type: str
    default_sql: str
    alter_existing_type: bool = False


# Model bilan bir xil tur va dastur ishlatadigan bo'sh/standart qiymat.
COLUMN_DEFAULTS = (
    ColumnDefault("orders", "phone", "VARCHAR(40)", "''", alter_existing_type=True),
    ColumnDefault(
        "orders",
        "paid_amount",
        "NUMERIC(14, 2)",
        "0",
        alter_existing_type=True,
    ),
    ColumnDefault(
        "orders",
        "service",
        "VARCHAR(500)",
        "''",
        alter_existing_type=True,
    ),
    ColumnDefault("orders", "status", "VARCHAR(30)", "'Yangi'"),
    ColumnDefault("orders", "notes", "TEXT", "''"),
    ColumnDefault("payments", "method", "VARCHAR(40)", "'Naqd'"),
    ColumnDefault("payments", "note", "TEXT", "''"),
    ColumnDefault("expenses", "description", "TEXT", "''"),
    ColumnDefault("team_members", "role", "VARCHAR(120)", "'Xodim'"),
    ColumnDefault("team_members", "active", "BOOLEAN", "true"),
    ColumnDefault("team_payments", "note", "TEXT", "''"),
)

TYPE_IF_PRESENT = (
    ("orders", "total_price", "NUMERIC(14, 2)"),
)

_IDENTIFIERS = frozenset(
    name
    for spec in COLUMN_DEFAULTS
    for name in (spec.table, spec.column)
) | {"orders", "total_price"}
_TYPES = frozenset(spec.column_type for spec in COLUMN_DEFAULTS) | {
    "NUMERIC(14, 2)",
}
_DEFAULTS = frozenset(spec.default_sql for spec in COLUMN_DEFAULTS)

STATEMENTS = (
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
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS payments_idempotency_key_key ON payments (idempotency_key)",
    "CREATE INDEX IF NOT EXISTS ix_payments_order_id ON payments (order_id)",
    "CREATE INDEX IF NOT EXISTS ix_payments_paid_at ON payments (paid_at)",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS expenses_idempotency_key_key ON expenses (idempotency_key)",
    "CREATE INDEX IF NOT EXISTS ix_expenses_spent_at ON expenses (spent_at)",
    "ALTER TABLE team_members ADD COLUMN IF NOT EXISTS phone VARCHAR(40) NOT NULL DEFAULT ''",
    "ALTER TABLE team_payments ADD COLUMN IF NOT EXISTS work_for VARCHAR(200) NOT NULL DEFAULT ''",
    "ALTER TABLE team_payments ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
    "ALTER TABLE team_payments ADD COLUMN IF NOT EXISTS debt_id INTEGER REFERENCES team_debts(id)",
    "CREATE INDEX IF NOT EXISTS ix_team_payments_debt_id ON team_payments (debt_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS team_payments_idempotency_key_key ON team_payments (idempotency_key)",
    "CREATE INDEX IF NOT EXISTS ix_team_payments_paid_at ON team_payments (paid_at)",
    "CREATE INDEX IF NOT EXISTS ix_team_payments_member_id ON team_payments (member_id)",
    "CREATE INDEX IF NOT EXISTS ix_team_payments_order_id ON team_payments (order_id)",
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


def _checked_name(name: str) -> str:
    if name not in _IDENTIFIERS:
        raise ValueError(name)
    return name


async def table_columns(connection: AsyncConnection, table: str) -> set[str]:
    """Jadvalning hozirgi ustunlari. Qidiruv yo'lidagi haqiqiy jadval olinadi."""
    checked = _checked_name(table)
    result = await connection.execute(
        text(
            """
            SELECT attribute.attname
            FROM pg_catalog.pg_attribute AS attribute
            WHERE attribute.attrelid = to_regclass(CAST(:table_name AS text))
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            """
        ),
        {"table_name": checked},
    )
    return {str(row[0]) for row in result}


async def ensure_column_default(
    connection: AsyncConnection,
    spec: ColumnDefault,
) -> None:
    """Ustun yo'q bo'lsa qo'shadi, mavjud bo'lgach DEFAULT o'rnatadi.

    Eski yozuvlar o'chirilmaydi. Yangi ustundagi NULL qiymatlar modeldagi
    standartga to'ldiriladi, so'ng NOT NULL qo'yiladi.
    """
    table = _checked_name(spec.table)
    column = _checked_name(spec.column)
    if spec.column_type not in _TYPES or spec.default_sql not in _DEFAULTS:
        raise ValueError(spec.column)
    columns = await table_columns(connection, table)
    if column not in columns:
        await connection.execute(
            text(f"ALTER TABLE {table} ADD COLUMN {column} {spec.column_type}")
        )
    elif spec.alter_existing_type:
        await connection.execute(
            text(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {spec.column_type}"
            )
        )
    await connection.execute(
        text(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {spec.default_sql}")
    )
    await connection.execute(
        text(
            f"UPDATE {table} SET {column} = {spec.default_sql} "
            f"WHERE {column} IS NULL"
        )
    )
    await connection.execute(
        text(f"ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL")
    )


async def alter_type_if_present(
    connection: AsyncConnection,
    table: str,
    column: str,
    column_type: str,
) -> None:
    checked_table = _checked_name(table)
    checked_column = _checked_name(column)
    if column_type not in _TYPES:
        raise ValueError(column_type)
    columns = await table_columns(connection, checked_table)
    if checked_column not in columns:
        return
    await connection.execute(
        text(
            "ALTER TABLE "
            f"{checked_table} ALTER COLUMN {checked_column} TYPE {column_type}"
        )
    )


async def apply_column_repairs(connection: AsyncConnection) -> None:
    for table, column, column_type in TYPE_IF_PRESENT:
        await alter_type_if_present(connection, table, column, column_type)
    for spec in COLUMN_DEFAULTS:
        await ensure_column_default(connection, spec)


async def migrate_schema() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await apply_column_repairs(connection)
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
