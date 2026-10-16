import os
from datetime import date, datetime
from decimal import Decimal

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not DATABASE_URL:
    raise RuntimeError(".env faylida DATABASE_URL ko'rsatilmagan.")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={"timeout": 10},
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


class Order(Base):
    """Mavjud orders jadvaliga mos model. Eski ustunlar saqlanadi."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(40), default="", server_default="")
    service: Mapped[str] = mapped_column(String(500), default="", server_default="")
    total_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        default=Decimal("0"),
        server_default=text("0"),
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="Yangi",
        server_default="Yangi",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    payment_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reminder_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_checked_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    order_number: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        nullable=True,
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    method: Mapped[str] = mapped_column(String(40), default="Naqd", server_default="Naqd")
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        nullable=True,
    )


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    spent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        nullable=True,
    )


class TeamMember(Base):
    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    phone: Mapped[str] = mapped_column(String(40), default="", server_default="")
    role: Mapped[str] = mapped_column(String(120), default="Xodim", server_default="Xodim")
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
    )


class TeamPayment(Base):
    __tablename__ = "team_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("team_members.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"),
        nullable=True,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    work_for: Mapped[str] = mapped_column(String(200), default="", server_default="")
    debt_id: Mapped[int | None] = mapped_column(
        ForeignKey("team_debts.id"),
        nullable=True,
        index=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        nullable=True,
    )


class TeamDebt(Base):
    """Hodimga berilishi kerak bo'lgan, hali to'liq yopilmagan qarz."""

    __tablename__ = "team_debts"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("team_members.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"),
        nullable=True,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        default=Decimal("0"),
        server_default=text("0"),
    )
    opened_on: Mapped[date] = mapped_column(Date)
    work_for: Mapped[str] = mapped_column(String(200), default="", server_default="")
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        nullable=True,
    )


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()
