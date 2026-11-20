from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, JSON, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base

def now(): return datetime.now(timezone.utc).replace(tzinfo=None)
class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(250))
class Node(Base):
    __tablename__ = 'nodes'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    role: Mapped[str] = mapped_column(String(20))
    term: Mapped[int] = mapped_column(Integer)
    log_position: Mapped[int] = mapped_column(Integer)
    available: Mapped[bool] = mapped_column(Boolean)
    fenced: Mapped[bool] = mapped_column(Boolean)
    vote_enabled: Mapped[bool] = mapped_column(Boolean)
    # 备库是否仍保留换列前的旧价数据；缺旧数据的备库不能接住未读完的旧游标。
    has_legacy: Mapped[bool] = mapped_column(Boolean, default=True)
class Scenario(Base):
    __tablename__ = 'scenarios'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    fail_primary: Mapped[bool] = mapped_column(Boolean)
    fence_primary: Mapped[bool] = mapped_column(Boolean)
    max_data_loss: Mapped[int] = mapped_column(Integer)
    required_term: Mapped[int] = mapped_column(Integer)
class Drill(Base):
    __tablename__ = 'drills'
    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey('scenarios.id'))
    label: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default='queued')
    snapshot: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
class Audit(Base):
    __tablename__ = 'audits'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class QuoteColumn(Base):
    """报价列（换列的物理落点）。

    逻辑列名恒为 `price`，每当改价口径/换列时新增一个 generation，旧 generation
    冻结为只读，供打开时的旧游标继续读取。任何时刻只有一个 status='active' 的列
    对外提供新查询。
    """
    __tablename__ = 'quote_columns'
    id: Mapped[int] = mapped_column(primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, unique=True)
    label: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default='active')  # active | retired
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class QuoteRow(Base):
    """报价行。价格按列 generation 存放：同一行在每代列各有一条价。"""
    __tablename__ = 'quote_rows'
    id: Mapped[int] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, unique=True)
    symbol: Mapped[str] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint('symbol', name='uq_quote_symbol'),)


class QuotePrice(Base):
    __tablename__ = 'quote_prices'
    id: Mapped[int] = mapped_column(primary_key=True)
    row_id: Mapped[int] = mapped_column(ForeignKey('quote_rows.id'))
    column_id: Mapped[int] = mapped_column(ForeignKey('quote_columns.id'))
    value: Mapped[int] = mapped_column(Integer)
    # 改价追加新版本，不覆盖历史；游标据版本读到打开时的价。
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint('row_id', 'column_id', 'version', name='uq_price_row_column_version'),)


class QuoteCursor(Base):
    """快照游标：绑定打开时的列 generation、价格版本与行上界。"""
    __tablename__ = 'quote_cursors'
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    column_id: Mapped[int] = mapped_column(ForeignKey('quote_columns.id'))
    generation: Mapped[int] = mapped_column(Integer)
    snapshot_version: Mapped[int] = mapped_column(Integer, default=0)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    max_seq: Mapped[int] = mapped_column(Integer, default=0)
    page_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='open')  # open | closed | expired
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class QuoteSwap(Base):
    """换列操作日志。request_id 唯一，保证中断恢复后重试不重复换列。"""
    __tablename__ = 'quote_swaps'
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(120), unique=True)
    from_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_generation: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default='applied')  # applied
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index('ix_quote_swaps_request', 'request_id'),)

