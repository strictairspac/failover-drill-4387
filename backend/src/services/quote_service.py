"""报价簿：版本化报价列 + 快照游标分页 + 幂等换列 + 游标感知回收。

模型要点：
- 逻辑列名恒为 `price`，物理上按 generation 分代。换列 = 新建一代列并复制当前价。
- 每次改价写入一条新的 QuotePrice.version，不原地覆盖。
- 游标 pin 住打开时的 generation 与 snapshot_version，旧游标永远读打开时的旧价。
- 分页用 seq 键集推进（seq > last_seq），改价/换列不会漏行，也不会串版本。
- 回收只删除没有打开的游标所需的数据；与打开游标并发时用列行锁串行化。
- 换列以 request_id 唯一幂等，落盘后重试原请求不会重复换列。
"""
import secrets

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.models.entities import (Node, QuoteColumn, QuoteCursor, QuotePrice,
                                 QuoteRow, QuoteSwap, Scenario, now)
from src.services.election import elect
from src.utils.serialize import record


# ---------- 内部工具 ----------

def _active_column(db, lock=False):
    stmt = select(QuoteColumn).where(QuoteColumn.status == 'active')
    if lock:
        stmt = stmt.with_for_update()
    column = db.scalar(stmt.order_by(QuoteColumn.generation.desc()))
    if column is None:
        raise HTTPException(409, '报价列尚未初始化')
    return column


def _max_version(db, column_id):
    return db.scalar(select(func.max(QuotePrice.version)).where(QuotePrice.column_id == column_id)) or 0


def _price_map(db, column_id, row_ids, snapshot_version):
    """返回 {row_id: (value, version)}，只取不晚于 snapshot 的最新版本。"""
    if not row_ids:
        return {}
    rows = db.scalars(select(QuotePrice).where(
        QuotePrice.column_id == column_id,
        QuotePrice.row_id.in_(row_ids),
        QuotePrice.version <= snapshot_version,
    ).order_by(QuotePrice.version)).all()
    out = {}
    for p in rows:
        out[p.row_id] = (p.value, p.version)
    return out


def _serialize_column(column):
    return {'id': column.id, 'generation': column.generation, 'label': column.label,
            'status': column.status, 'created_at': column.created_at.isoformat(),
            'retired_at': column.retired_at.isoformat() if column.retired_at else None}


# ---------- 列与行 ----------

def list_columns(db):
    columns = db.scalars(select(QuoteColumn).order_by(QuoteColumn.generation)).all()
    active = next((c for c in columns if c.status == 'active'), None)
    return {'active_generation': active.generation if active else None,
            'columns': [_serialize_column(c) for c in columns]}


def list_rows(db):
    rows = db.scalars(select(QuoteRow).order_by(QuoteRow.seq)).all()
    column = _active_column(db)
    snapshot = _max_version(db, column.id)
    prices = _price_map(db, column.id, [r.id for r in rows], snapshot)
    return {'generation': column.generation, 'snapshot_version': snapshot,
            'rows': [{'id': r.id, 'seq': r.seq, 'symbol': r.symbol,
                      'price': prices.get(r.id, (None, None))[0],
                      'version': prices.get(r.id, (None, None))[1]} for r in rows]}


def set_price(db, symbol, value):
    """改价只写当前活跃列的新版本；旧游标不受影响。"""
    column = _active_column(db, lock=True)
    row = db.scalar(select(QuoteRow).where(QuoteRow.symbol == symbol))
    if row is None:
        raise HTTPException(404, '报价标的物不存在')
    version = _max_version(db, column.id) + 1
    db.add(QuotePrice(row_id=row.id, column_id=column.id, value=value, version=version))
    db.flush()
    return {'symbol': symbol, 'generation': column.generation, 'price': value, 'version': version}


# ---------- 快照游标与翻页 ----------

def _serialize_cursor(cursor, column):
    return {'token': cursor.token, 'generation': cursor.generation,
            'snapshot_version': cursor.snapshot_version, 'last_seq': cursor.last_seq,
            'max_seq': cursor.max_seq, 'page_size': cursor.page_size, 'status': cursor.status}


def open_cursor(db, page_size):
    column = _active_column(db, lock=True)
    max_seq = db.scalar(select(func.max(QuoteRow.seq))) or 0
    snapshot = _max_version(db, column.id)
    cursor = QuoteCursor(token=secrets.token_hex(16), column_id=column.id,
                         generation=column.generation, last_seq=0, max_seq=max_seq,
                         snapshot_version=snapshot, page_size=page_size, status='open')
    db.add(cursor)
    db.flush()
    return cursor, column


def _page(db, cursor, column):
    rows = db.scalars(select(QuoteRow).where(
        QuoteRow.seq > cursor.last_seq, QuoteRow.seq <= cursor.max_seq,
    ).order_by(QuoteRow.seq).limit(cursor.page_size)).all()
    prices = _price_map(db, column.id, [r.id for r in rows], cursor.snapshot_version)
    page = [{'seq': r.seq, 'symbol': r.symbol,
             'price': prices.get(r.id, (None, None))[0],
             'version': prices.get(r.id, (None, None))[1],
             'generation': cursor.generation} for r in rows]
    return page


def fetch_page(db, token=None, page_size=5):
    """无 token → 开新游标读当前列；有 token → 沿旧游标读打开时的旧价。

    锁顺序统一为「列 → 游标」，与 reclaim 一致，避免两者并发时死锁。
    """
    if token:
        existing = db.scalar(select(QuoteCursor).where(QuoteCursor.token == token))
        if existing is None:
            raise HTTPException(404, '游标不存在')
        if existing.status != 'open':
            raise HTTPException(409, f'游标已{existing.status}，请开启新查询')
        column = db.scalar(select(QuoteColumn).where(QuoteColumn.id == existing.column_id).with_for_update())
        cursor = db.scalar(select(QuoteCursor).where(QuoteCursor.token == token).with_for_update())
        if cursor.status != 'open':
            raise HTTPException(409, f'游标已{cursor.status}，请开启新查询')
    else:
        cursor, column = open_cursor(db, page_size)

    page = _page(db, cursor, column)
    if page:
        cursor.last_seq = page[-1]['seq']
    done = cursor.last_seq >= cursor.max_seq

    next_token = None if done else cursor.token
    if done:
        cursor.status = 'closed'
        cursor.closed_at = now()
    db.flush()
    return {'cursor': _serialize_cursor(cursor, column), 'column_label': column.label,
            'rows': page, 'next_cursor': next_token, 'done': done,
            'note': '旧游标固定打开时的列与价格版本；改价/换列不影响本次分页。'}


def close_cursor(db, token):
    cursor = db.scalar(select(QuoteCursor).where(QuoteCursor.token == token).with_for_update())
    if cursor is None:
        raise HTTPException(404, '游标不存在')
    if cursor.status == 'open':
        cursor.status = 'closed'
        cursor.closed_at = now()
        db.flush()
    return _serialize_cursor(cursor, db.get(QuoteColumn, cursor.column_id))


def list_cursors(db):
    cursors = db.scalars(select(QuoteCursor).order_by(QuoteCursor.id.desc()).limit(50)).all()
    return [{'token': c.token, 'generation': c.generation, 'snapshot_version': c.snapshot_version,
             'last_seq': c.last_seq, 'max_seq': c.max_seq, 'status': c.status,
             'remaining': max(c.max_seq - c.last_seq, 0)} for c in cursors]


# ---------- 换列（幂等） ----------

def _apply_swap(db, request_id, label):
    current = _active_column(db, lock=True)
    generation = (db.scalar(select(func.max(QuoteColumn.generation))) or 0) + 1
    new_column = QuoteColumn(generation=generation, label=label or f'报价口径 g{generation}', status='active')
    db.add(new_column)
    db.flush()

    # 复制当前列每个标的最新价到新列，作为新列 version=1 的起点。
    current_latest = _price_map(db, current.id, [r.id for r in db.scalars(select(QuoteRow)).all()],
                                _max_version(db, current.id))
    for row_id, (value, _version) in current_latest.items():
        db.add(QuotePrice(row_id=row_id, column_id=new_column.id, value=value, version=1))

    current.status = 'retired'
    current.retired_at = now()
    swap = QuoteSwap(request_id=request_id, from_generation=current.generation,
                     to_generation=generation, label=new_column.label, status='applied')
    db.add(swap)
    db.flush()
    return {'swap': {'request_id': request_id, 'from_generation': current.generation,
                     'to_generation': generation, 'status': 'applied', 'replayed': False},
            'column': _serialize_column(new_column)}


def swap_column(db, request_id, label=None):
    """换列落盘后中断，恢复重试同 request_id 返回既有结果，不重复换列。"""
    existing = db.scalar(select(QuoteSwap).where(QuoteSwap.request_id == request_id))
    if existing:
        column = db.scalar(select(QuoteColumn).where(QuoteColumn.generation == existing.to_generation))
        return {'swap': {'request_id': existing.request_id, 'from_generation': existing.from_generation,
                         'to_generation': existing.to_generation, 'status': 'applied', 'replayed': True},
                'column': _serialize_column(column)}
    try:
        return _apply_swap(db, request_id, label)
    except IntegrityError:
        # 并发同 request_id：回滚后读取已落盘的那次结果。
        db.rollback()
        existing = db.scalar(select(QuoteSwap).where(QuoteSwap.request_id == request_id))
        if existing is None:
            raise
        column = db.scalar(select(QuoteColumn).where(QuoteColumn.generation == existing.to_generation))
        return {'swap': {'request_id': existing.request_id, 'from_generation': existing.from_generation,
                         'to_generation': existing.to_generation, 'status': 'applied', 'replayed': True},
                'column': _serialize_column(column)}


# ---------- 回收 ----------

def reclaim(db):
    """删除无人需要的旧数据；打开中的游标所 pin 的列/版本一律保留。

    与翻页并发安全的依据：打开游标、换列、回收都先锁对应列行；回收在同一事务中
    重新读取打开游标后再删。仍在推进的游标在其 snapshot_version 上读到所需版本。
    """
    columns = db.scalars(select(QuoteColumn).order_by(QuoteColumn.generation).with_for_update()).all()
    open_by_column = {}
    for cursor in db.scalars(select(QuoteCursor).where(QuoteCursor.status == 'open').with_for_update()).all():
        open_by_column.setdefault(cursor.column_id, []).append(cursor)

    removed_versions, dropped_generations, kept = 0, [], []
    for column in columns:
        open_cursors = open_by_column.get(column.id, [])
        prices = db.scalars(select(QuotePrice).where(QuotePrice.column_id == column.id)).all()
        if not prices:
            continue
        if not open_cursors:
            if column.status == 'retired':
                for p in prices:
                    db.delete(p)
                    removed_versions += 1
                dropped_generations.append(column.generation)
                continue
            # 活跃列无人读旧版本：仅保留每行最新版本。
            latest = {}
            for p in prices:
                latest[p.row_id] = max(latest.get(p.row_id, 0), p.version)
            for p in prices:
                if p.version != latest[p.row_id]:
                    db.delete(p)
                    removed_versions += 1
            continue
        # 有打开游标：对每一行保留「不晚于最小快照的最新版本」，以及所有不早于
        # 最小快照的版本。这样任一游标按其 snapshot 读到的正是它打开时的价。
        min_snapshot = min(c.snapshot_version for c in open_cursors)
        floor_by_row = {}
        for p in prices:
            if p.version <= min_snapshot:
                floor_by_row[p.row_id] = max(floor_by_row.get(p.row_id, 0), p.version)
        for p in prices:
            needed = p.version >= min_snapshot or p.version == floor_by_row.get(p.row_id)
            if not needed:
                db.delete(p)
                removed_versions += 1
        kept.append({'generation': column.generation, 'open_cursors': len(open_cursors),
                     'retain_from_version': min_snapshot})
    db.flush()
    return {'removed_versions': removed_versions, 'dropped_generations': dropped_generations,
            'retained_for_cursors': kept, 'open_cursors': sum(len(v) for v in open_by_column.values()),
            'note': '打开游标所 pin 的旧列与版本保留；游标关闭后下次回收可删除。'}


# ---------- 切主（游标感知） ----------

def failover(db, scenario_id=None):
    scenario = db.get(Scenario, scenario_id) if scenario_id else db.scalar(
        select(Scenario).order_by(Scenario.id).limit(1))
    if scenario is None:
        raise HTTPException(404, '故障剧本不存在')

    nodes = [{'id': n.id, 'name': n.name, 'role': n.role, 'term': n.term,
              'log_position': n.log_position, 'available': n.available,
              'fenced': n.fenced, 'vote_enabled': n.vote_enabled, 'has_legacy': n.has_legacy}
             for n in db.scalars(select(Node).order_by(Node.id)).all()]
    result = elect(nodes, record(scenario))

    active = _active_column(db)
    open_cursors = db.scalars(select(QuoteCursor).where(QuoteCursor.status == 'open')).all()
    # 只有仍读「换列前那一代」的游标才依赖备库保留旧数据；活跃列的历史版本随活跃列一起复制。
    needs_legacy = [c for c in open_cursors if c.generation != active.generation]
    legacy_open = [{'token': c.token, 'generation': c.generation, 'remaining': c.max_seq - c.last_seq}
                   for c in needs_legacy]

    winner = result.get('winner')
    successor = next((n for n in nodes if n['name'] == winner), None) if winner else None

    if result['decision'] == 'approved' and legacy_open and successor and not successor['has_legacy']:
        result['decision'] = 'deferred'
        result['defer_reason'] = (f"接任副本 {successor['name']} 缺少换列前旧数据，"
                                  f"无法接住 {len(legacy_open)} 个未读完的旧游标，暂缓切主。")
        result['checks'].append({'rule': '接住旧游标', 'pass': False,
                                 'evidence': f"游标 {len(legacy_open)} 个仍读旧价；{successor['name']} has_legacy=False"})
        result['winner'] = None
        result['successor_considered'] = winner
    else:
        result['checks'].append({'rule': '接住旧游标', 'pass': True,
                                 'evidence': ('无旧游标' if not legacy_open else
                                              (f"{successor['name']} 保留旧价，可接住 {len(legacy_open)} 个游标" if successor else '无候选'))})
    result['open_cursors'] = legacy_open
    result['simulation'] = True
    result['boundary'] = '受控演练模型；不连接真实复制集群，不执行生产切主。'
    return result
