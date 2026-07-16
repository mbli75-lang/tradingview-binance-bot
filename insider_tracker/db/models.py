"""SQLAlchemy-modeller (DB-agnostiska: fungerar på SQLite och Postgres/Supabase).

Schemat följer kravspec Modul 2. `transactions` har en unik dedupe-nyckel på
(person, ISIN, transaktionsdatum, volym, pris) så att ingest är idempotent.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    isin: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    lei: Mapped[str | None] = mapped_column(String(20), nullable=True)
    marketplace: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Steg 2: berikning från Börsdata.
    segment: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Small Cap m.m.
    borsdata_ins_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="company")


class Insider(Base):
    __tablename__ = "insiders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256))
    # Normaliserat namn för dedupe (lower, trimmad, kollapsade mellanslag).
    name_normalized: Mapped[str] = mapped_column(String(256), unique=True, index=True)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="insider")
    roles: Mapped[list["InsiderRole"]] = relationship(back_populates="insider")


class InsiderRole(Base):
    __tablename__ = "insider_roles"
    __table_args__ = (
        UniqueConstraint("insider_id", "company_isin", "role", name="uq_insider_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    insider_id: Mapped[int] = mapped_column(ForeignKey("insiders.id"), index=True)
    company_isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), index=True)
    role: Mapped[str | None] = mapped_column(String(256), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)

    insider: Mapped["Insider"] = relationship(back_populates="roles")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("dedupe_hash", name="uq_transaction_dedupe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    insider_id: Mapped[int] = mapped_column(ForeignKey("insiders.id"), index=True)
    company_isin: Mapped[str] = mapped_column(ForeignKey("companies.isin"), index=True)

    type: Mapped[str] = mapped_column(String(8))  # 'buy' | 'sell'
    volume: Mapped[float] = mapped_column(Numeric(20, 4))
    price: Mapped[float] = mapped_column(Numeric(20, 6))
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    amount_sek: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)

    trade_date: Mapped[date] = mapped_column(Date, index=True)
    publish_date: Mapped[date] = mapped_column(Date, index=True)
    publish_datetime: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    is_related_party: Mapped[bool] = mapped_column(Boolean, default=False)

    # Extra kontext från FI (används av senare moduler / spårbarhet).
    instrument_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    instrument_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    marketplace: Mapped[str | None] = mapped_column(String(64), nullable=True)
    marketplace_raw: Mapped[str | None] = mapped_column(String(128), nullable=True)
    character_raw: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_first_report: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    linked_to_share_program: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    dedupe_hash: Mapped[str] = mapped_column(String(64), index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    insider: Mapped["Insider"] = relationship(back_populates="transactions")
    company: Mapped["Company"] = relationship(back_populates="transactions")


class Price(Base):
    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint("isin", "date", name="uq_price_isin_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    isin: Mapped[str] = mapped_column(String(12), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # borsdata|eodhd


class InsiderScore(Base):
    __tablename__ = "insider_scores"
    __table_args__ = (
        UniqueConstraint("insider_id", "company_isin", name="uq_score_insider_company"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    insider_id: Mapped[int] = mapped_column(ForeignKey("insiders.id"), index=True)
    company_isin: Mapped[str | None] = mapped_column(
        ForeignKey("companies.isin"), nullable=True, index=True
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_return_1m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_return_3m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_return_6m: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TradeReturn(Base):
    """Steg 3: avkastning per historiskt köp, +21/+63/+126 handelsdagar efter
    publiceringsdatum, benchmark-justerat (OMXSPI) och slippage-justerat."""

    __tablename__ = "trade_returns"

    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id"), primary_key=True
    )
    insider_id: Mapped[int | None] = mapped_column(Integer, index=True)
    company_isin: Mapped[str | None] = mapped_column(String(12), index=True)
    publish_date: Mapped[date | None] = mapped_column(Date)
    entry_date: Mapped[date | None] = mapped_column(Date)
    entry_price: Mapped[float | None] = mapped_column(Float)
    marketplace: Mapped[str | None] = mapped_column(String(64))
    segment: Mapped[str | None] = mapped_column(String(64))
    slippage: Mapped[float | None] = mapped_column(Float)
    amount_sek: Mapped[float | None] = mapped_column(Numeric(20, 2))
    is_related_party: Mapped[bool | None] = mapped_column(Boolean)
    # Brutto aktieavkastning, benchmark, samt netto överavkastning (efter slippage).
    ret_1m: Mapped[float | None] = mapped_column(Float)
    bench_1m: Mapped[float | None] = mapped_column(Float)
    exc_1m: Mapped[float | None] = mapped_column(Float)
    ret_3m: Mapped[float | None] = mapped_column(Float)
    bench_3m: Mapped[float | None] = mapped_column(Float)
    exc_3m: Mapped[float | None] = mapped_column(Float)
    ret_6m: Mapped[float | None] = mapped_column(Float)
    bench_6m: Mapped[float | None] = mapped_column(Float)
    exc_6m: Mapped[float | None] = mapped_column(Float)
    exit_status: Mapped[str | None] = mapped_column(String(32))  # ok|delisted|bankrupt|pending
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Cluster(Base):
    """Steg 3: klustersignal – ≥N unika insiders köper i samma bolag inom rullande
    fönster. Egen avkastningsstatistik."""

    __tablename__ = "clusters"
    __table_args__ = (
        UniqueConstraint("company_isin", "trigger_date", name="uq_cluster"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_isin: Mapped[str] = mapped_column(String(12), index=True)
    trigger_date: Mapped[date] = mapped_column(Date, index=True)
    window_start: Mapped[date | None] = mapped_column(Date)
    n_insiders: Mapped[int | None] = mapped_column(Integer)
    n_buys: Mapped[int | None] = mapped_column(Integer)
    entry_date: Mapped[date | None] = mapped_column(Date)
    entry_price: Mapped[float | None] = mapped_column(Float)
    exc_1m: Mapped[float | None] = mapped_column(Float)
    exc_3m: Mapped[float | None] = mapped_column(Float)
    exc_6m: Mapped[float | None] = mapped_column(Float)
    exit_status: Mapped[str | None] = mapped_column(String(32))


class SignalExit(Base):
    """Steg 5: hypotetiskt utfall per exit-regel för varje köpflagg.

    Tre parallella regler loggas och jämförs: insider_sell | hold_3m | trailing_15.
    """

    __tablename__ = "signal_exits"
    __table_args__ = (
        UniqueConstraint("signal_id", "rule", name="uq_signal_exit"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    isin: Mapped[str | None] = mapped_column(String(12), index=True)
    insider_id: Mapped[int | None] = mapped_column(Integer)
    signal_date: Mapped[date | None] = mapped_column(Date)
    rule: Mapped[str] = mapped_column(String(24))
    entry_date: Mapped[date | None] = mapped_column(Date)
    entry_price: Mapped[float | None] = mapped_column(Float)
    exit_date: Mapped[date | None] = mapped_column(Date)
    exit_price: Mapped[float | None] = mapped_column(Float)
    gross_return: Mapped[float | None] = mapped_column(Float)
    net_return: Mapped[float | None] = mapped_column(Float)
    slippage: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(String(16))  # closed | open | no_price
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Signal(Base):
    """Modul 5: spårning av flaggade köp (skapas i steg 4/5, definieras redan nu)."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_date: Mapped[date] = mapped_column(Date, index=True)
    isin: Mapped[str] = mapped_column(String(12), index=True)
    insider_id: Mapped[int | None] = mapped_column(
        ForeignKey("insiders.id"), nullable=True
    )
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Steg 4: typ av flagg (insider_buy | cluster | insider_sell).
    signal_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
