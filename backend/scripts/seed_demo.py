import os
from sqlalchemy import select
from src.config.database import Base, engine, Session
from src.models.entities import User, Node, Scenario, QuoteColumn, QuoteRow, QuotePrice
from src.utils.security import hash_password

QUOTE_ROWS = [('hs-cu-2601', 1001), ('hs-cu-2602', 1002), ('hs-al-2601', 1003),
              ('hs-al-2602', 1004), ('hs-zn-2601', 1005), ('hs-zn-2602', 1006),
              ('hs-ni-2601', 1007), ('hs-au-2601', 1008)]

def seed_quotes(db):
    column = db.scalar(select(QuoteColumn).where(QuoteColumn.status == 'active'))
    if column is None:
        column = QuoteColumn(generation=1, label='基准报价口径 g1', status='active')
        db.add(column); db.flush()
    for seq, (symbol, price) in enumerate(QUOTE_ROWS, start=1):
        row = db.scalar(select(QuoteRow).where(QuoteRow.symbol == symbol))
        if row is None:
            row = QuoteRow(symbol=symbol, seq=seq); db.add(row); db.flush()
        exists = db.scalar(select(QuotePrice).where(QuotePrice.row_id == row.id,
                                                    QuotePrice.column_id == column.id))
        if exists is None:
            db.add(QuotePrice(row_id=row.id, column_id=column.id, value=price, version=1))

def seed():
    Base.metadata.create_all(engine)
    if os.getenv('SEED_DEMO','true').lower() != 'true': return
    with Session() as db:
        for role in ('admin','operator','viewer'):
            email = role + '@hengshi.local'
            if not db.scalar(select(User).where(User.email == email)):
                db.add(User(email=email, role=role, password_hash=hash_password('Drill2026!')))
        for name, role, pos in [('hs-primary','leader',8100),('hs-east','follower',8100),('hs-west','follower',8098)]:
            if not db.scalar(select(Node).where(Node.name == name)):
                db.add(Node(name=name, role=role, term=6, log_position=pos, available=True, fenced=False, vote_enabled=True, has_legacy=True))
        for name, fence in [('晚班隔离演练',True),('缺少隔离证明',False)]:
            if not db.scalar(select(Scenario).where(Scenario.name == name)):
                db.add(Scenario(name=name, fail_primary=True, fence_primary=fence, max_data_loss=0, required_term=7))
        seed_quotes(db)
        db.commit()
if __name__ == '__main__': seed()
