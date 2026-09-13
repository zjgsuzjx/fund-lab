from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .db import get_engine, get_session
from .models import Fund, FundNav

BACKEND = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    get_engine().dispose()


app = FastAPI(title='Fund Lab API', version='0.1.0', lifespan=lifespan)


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    # Do not send driver errors or connection information to the browser.
    return JSONResponse(status_code=503, content={'detail': '数据库暂不可用，请检查服务和迁移状态。'})


@app.get('/api/health/live')
def live():
    return {'status': 'ok', 'service': 'fund-lab', 'version': app.version}


@app.get('/api/health/ready')
def ready(session: Annotated[Session, Depends(get_session)]):
    config = Config(str(BACKEND / 'alembic.ini'))
    expected = set(ScriptDirectory.from_config(config).get_heads())
    connection = session.connection()
    current = set(MigrationContext.configure(connection).get_current_heads())
    if current != expected:
        return JSONResponse(status_code=503, content={'status': 'not_ready', 'database': 'connected', 'schema': 'migration_required'})
    count = session.scalar(select(func.count()).select_from(Fund))
    return {'status': 'ready', 'database': 'connected', 'schema': 'current', 'fund_count': count}


class FundItem(BaseModel):
    code: str
    name: str
    category: str
    nav_date: date | None
    unit_nav: Decimal | None
    source_observed_at: datetime
    is_sample: bool
    trade_enabled: bool


class FundPage(BaseModel):
    items: list[FundItem]
    total: int
    page: int
    page_size: int


@app.get('/api/funds', response_model=FundPage)
def list_funds(session: Annotated[Session, Depends(get_session)],
               q: Annotated[str, Query(max_length=100)] = '',
               page: Annotated[int, Query(ge=1)] = 1,
               page_size: Annotated[int, Query(ge=1, le=100)] = 20):
    query = select(Fund)
    term = q.strip()
    if term:
        query = query.where(or_(Fund.code.contains(term, autoescape=True), Fund.name.contains(term, autoescape=True)))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    funds = session.scalars(query.order_by(Fund.code).offset((page - 1) * page_size).limit(page_size)).all()
    # One grouped query for the latest NAV of all funds on this page.
    latest = select(FundNav.fund_code, func.max(FundNav.nav_date).label('day')).where(
        FundNav.fund_code.in_([f.code for f in funds])).group_by(FundNav.fund_code).subquery()
    navs = {n.fund_code: n for n in session.scalars(select(FundNav).join(latest,
        (FundNav.fund_code == latest.c.fund_code) & (FundNav.nav_date == latest.c.day)))}
    items = []
    for fund in funds:
        nav = navs.get(fund.code)
        items.append(FundItem(code=fund.code, name=fund.name, category=fund.category,
            nav_date=nav.nav_date if nav else None, unit_nav=nav.unit_nav if nav else None,
            source_observed_at=fund.source_observed_at, is_sample=fund.is_sample, trade_enabled=fund.trade_enabled))
    return FundPage(items=items, total=total, page=page, page_size=page_size)
