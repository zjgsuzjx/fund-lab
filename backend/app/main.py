from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path
from typing import Annotated

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import router as auth_router
from .db import get_engine, get_session
from .models import Fund
from .funds import router as funds_router
from .trades import router as trades_router
from .settle_orders import settle_pending

BACKEND = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    async def worker():
        while not stop.is_set():
            try:
                await asyncio.to_thread(settle_pending)
            except Exception:
                logging.getLogger(__name__).warning('Settlement postponed; check database and migrations.')
            try:
                await asyncio.wait_for(stop.wait(), timeout=60)
            except TimeoutError:
                pass
    task = asyncio.create_task(worker())
    try:
        yield
    finally:
        stop.set()
        await task
        get_engine().dispose()


app = FastAPI(title='Fund Lab API', version='0.4.0', lifespan=lifespan)


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


app.include_router(auth_router)
app.include_router(funds_router)
app.include_router(trades_router)


@app.middleware('http')
async def private_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response
