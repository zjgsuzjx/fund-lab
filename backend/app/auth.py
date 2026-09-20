"""Local username accounts. All account ownership comes from the session cookie."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_session
from .trade_rules import utcnow
from .throttle import throttle
from .models import AuthSession, CashLedger, SimulationAccount, User

router = APIRouter(prefix='/api')
DB = Annotated[Session, Depends(get_session)]
COOKIE = 'fund_lab_session'
INITIAL_CASH = Decimal('100000.00')
ITERATIONS = 600_000


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), ITERATIONS).hex()
    return f'pbkdf2_sha256${ITERATIONS}${salt}${digest}'


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, digest = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or int(iterations) != ITERATIONS:
            return False
        candidate = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), ITERATIONS).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


DUMMY_HASH = password_hash('dummy-password-for-timing')


def write_guard(request: Request):
    # Cross-origin forms cannot send this header; no CORS permission is granted.
    if request.headers.get('x-fund-lab') != '1' or request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, '请求来源验证失败，请从本站页面重试。')


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=4, max_length=20)
    password: str = Field(min_length=1, max_length=128)
    remember: bool = False

    @field_validator('username', mode='before')
    @classmethod
    def normalize_username(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_]{4,20}', value.strip()):
            raise ValueError('用户名须为 4–20 位字母、数字或下划线')
        return value.strip().lower()


def validate_password(password: str):
    if len(password) < 8 or not re.search(r'[A-Za-z]', password) or not re.search(r'[0-9]', password):
        raise HTTPException(422, '密码须为 8–128 位，并包含字母和数字。')


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request, db: DB) -> User:
    token = request.cookies.get(COOKIE, '')
    row = db.get(AuthSession, token_digest(token)) if token else None
    if not row or row.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(401, '请先登录，或重新登录已过期的账户。')
    user = db.get(User, row.user_id)
    if not user:
        raise HTTPException(401, '请重新登录。')
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def issue_session(db: Session, user: User, request: Request, response: Response, remember: bool):
    old_token = request.cookies.get(COOKIE)
    if old_token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_digest(old_token)))
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= datetime.now(timezone.utc)))
    token = secrets.token_urlsafe(32)
    lifetime = 30 * 86400 if remember else 12 * 3600
    db.add(AuthSession(token_hash=token_digest(token), user_id=user.id,
                       expires_at=datetime.now(timezone.utc) + timedelta(seconds=lifetime)))
    db.commit()
    response.set_cookie(COOKIE, token, httponly=True, samesite='strict',
                        secure=request.url.scheme == 'https', path='/api',
                        max_age=lifetime if remember else None)


def user_info(user: User):
    return {'id': str(user.id), 'username': user.username, 'created_at': user.created_at}


@router.post('/auth/register', status_code=201, dependencies=[Depends(write_guard), Depends(throttle)])
def register(body: Credentials, request: Request, response: Response, db: DB):
    validate_password(body.password)
    user = User(username=body.username, password_hash=password_hash(body.password))
    try:
        db.add(user)
        db.flush()
        account = SimulationAccount(user_id=user.id, available_cash=INITIAL_CASH)
        db.add(account)
        db.flush()
        db.add(CashLedger(account_id=account.id, event_key=f'initial:{account.id}',
                          kind='initial_capital', amount=INITIAL_CASH, balance_after=INITIAL_CASH, available_delta=INITIAL_CASH))
        # Commit all three records together with the first session.
        issue_session(db, user, request, response, body.remember)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '用户名已存在，请换一个用户名或直接登录。') from None
    return user_info(user)


@router.post('/auth/login', dependencies=[Depends(write_guard), Depends(throttle)])
def login(body: Credentials, request: Request, response: Response, db: DB):
    user = db.scalar(select(User).where(User.username == body.username))
    valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, '用户名或密码错误，请重试。')
    issue_session(db, user, request, response, body.remember)
    return user_info(user)


@router.get('/auth/me')
def me(user: CurrentUser):
    return user_info(user)


@router.post('/auth/logout', status_code=204, dependencies=[Depends(write_guard)])
def logout(request: Request, response: Response, db: DB):
    db.execute(delete(AuthSession).where(AuthSession.token_hash == token_digest(request.cookies.get(COOKIE, ''))))
    db.commit()
    response.delete_cookie(COOKIE, path='/api', httponly=True, samesite='strict')


def owned_account(db: Session, user: User):
    account = db.scalar(select(SimulationAccount).where(SimulationAccount.user_id == user.id))
    if not account:
        raise HTTPException(404, '未找到模拟账户。')
    return account


@router.get('/account')
def account(user: CurrentUser, db: DB, now: Annotated[datetime, Depends(utcnow)]):
    row = owned_account(db, user)
    from .trades import lock_account, portfolio
    row = lock_account(db, row.id)
    return {'id': str(row.id), 'created_at': row.created_at, **portfolio(db, row, now)}


@router.get('/account/ledger')
def ledger(user: CurrentUser, db: DB):
    row = owned_account(db, user)
    entries = db.scalars(select(CashLedger).where(CashLedger.account_id == row.id).order_by(CashLedger.created_at, CashLedger.id)).all()
    return {'items': [{'id': str(e.id), 'kind': e.kind, 'amount': str(e.amount),
                       'balance_after': str(e.balance_after), 'available_delta': str(e.available_delta),
                       'reserved_delta': str(e.reserved_delta), 'reserved_after': str(e.reserved_after),
                       'redemption_delta': str(e.redemption_delta), 'redemption_after': str(e.redemption_after), 'created_at': e.created_at} for e in entries]}


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AccountReset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=128)


@router.post('/account/reset', status_code=204, dependencies=[Depends(write_guard), Depends(throttle)])
def reset_account(body: AccountReset, user: CurrentUser, db: DB, request: Request, response: Response):
    from .models import BuyOrder, DividendPayment, PositionLot, SellAllocation, SellOrder, Watchlist
    from .trades import lock_account

    row = lock_account(db, owned_account(db, user).id)
    # Recheck after taking the account lock: another reset may have revoked this session.
    active_session = db.scalar(select(AuthSession).where(
        AuthSession.token_hash == token_digest(request.cookies.get(COOKIE, '')),
        AuthSession.user_id == user.id,
        AuthSession.expires_at > datetime.now(timezone.utc)))
    if not active_session:
        raise HTTPException(401, '会话已失效，请重新登录。')
    user = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, '当前密码错误，未重置任何数据。')
    db.execute(delete(SellAllocation).where(SellAllocation.order_id.in_(
        select(SellOrder.id).where(SellOrder.account_id == row.id))))
    for model in (DividendPayment, PositionLot, SellOrder, BuyOrder, CashLedger):
        db.execute(delete(model).where(model.account_id == row.id))
    db.execute(delete(Watchlist).where(Watchlist.user_id == user.id))
    row.available_cash = INITIAL_CASH
    row.reserved_cash = Decimal('0.00')
    row.redemption_cash = Decimal('0.00')
    db.add(CashLedger(account_id=row.id, event_key=f'initial:{row.id}', kind='initial_capital',
                      amount=INITIAL_CASH, balance_after=INITIAL_CASH, available_delta=INITIAL_CASH))
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.commit()
    response.delete_cookie(COOKIE, path='/api', httponly=True, samesite='strict')


@router.post('/account/password', status_code=204, dependencies=[Depends(write_guard), Depends(throttle)])
def change_password(body: PasswordChange, user: CurrentUser, db: DB, response: Response):
    validate_password(body.new_password)
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, '当前密码错误。')
    user.password_hash = password_hash(body.new_password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.commit()
    response.delete_cookie(COOKIE, path='/api', httponly=True, samesite='strict')
