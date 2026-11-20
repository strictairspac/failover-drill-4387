from fastapi import APIRouter, Depends, Header, HTTPException
from src.config.database import get_db
from src.middlewares.auth import current_user, writable, admin
from src.schemas.quote import PriceInput, SwapInput, CursorInput, FailoverInput
from src.services import quote_service as svc
from src.controllers.actions import audit
router = APIRouter()


@router.get('/quote/columns')
def columns(db=Depends(get_db), user=Depends(current_user)): return svc.list_columns(db)


@router.get('/quote/rows')
def rows(db=Depends(get_db), user=Depends(current_user)): return svc.list_rows(db)


@router.put('/quote/rows/{symbol}/price')
def set_price(symbol: str, data: PriceInput, db=Depends(get_db), user=Depends(admin)):
    out = svc.set_price(db, symbol, data.value)
    audit(db, user, f'quote:price:{symbol}:{out["version"]}'); db.commit(); return out


@router.post('/quote/swap')
def swap(data: SwapInput, db=Depends(get_db), user=Depends(admin)):
    out = svc.swap_column(db, data.request_id, data.label)
    audit(db, user, f'quote:swap:{out["swap"]["to_generation"]}' +
          (':replayed' if out['swap']['replayed'] else ''))
    db.commit(); return out


@router.post('/quote/pages')
def page(data: CursorInput, token: str | None = Header(default=None, alias='X-Quote-Cursor'),
         db=Depends(get_db), user=Depends(current_user)):
    out = svc.fetch_page(db, token, data.page_size)
    db.commit(); return out


@router.get('/quote/cursors')
def cursors(db=Depends(get_db), user=Depends(current_user)): return svc.list_cursors(db)


@router.delete('/quote/cursors/{token}')
def close_cursor(token: str, db=Depends(get_db), user=Depends(current_user)):
    out = svc.close_cursor(db, token); db.commit(); return out


@router.post('/quote/reclaim')
def reclaim(db=Depends(get_db), user=Depends(writable)):
    out = svc.reclaim(db); audit(db, user, 'quote:reclaim'); db.commit(); return out


@router.post('/quote/failover')
def failover(data: FailoverInput, db=Depends(get_db), user=Depends(writable)):
    out = svc.failover(db, data.scenario_id); audit(db, user, f'quote:failover:{out["decision"]}')
    db.commit(); return out
