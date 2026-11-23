import asyncio
import base64
from contextlib import asynccontextmanager
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
import re
import secrets
import threading
import time
import uuid
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from . import auth, config, services, garment_images
from .schemas import Chat, DataPoint, Garment, Login, Profile, SaveOutfit, WearReview
from .storage import store

CONVERSATION_SWEEP_SECONDS = 60 * 60


def conversation_cutoff():
    return (datetime.fromisoformat(services.now()) - timedelta(days=config.CONVERSATION_RETENTION_DAYS)).isoformat(timespec='microseconds')


async def sweep_conversations(stop):
    while not stop.is_set():
        try:
            await asyncio.to_thread(store.prune_conversations, conversation_cutoff())
        except Exception:
            services.LOGGER.error('Expired conversation cleanup failed. It will be retried.')
        try:
            await asyncio.wait_for(stop.wait(), timeout=CONVERSATION_SWEEP_SECONDS)
        except asyncio.TimeoutError:
            continue


@asynccontextmanager
async def lifespan(_app):
    stop = asyncio.Event()
    cleanup = asyncio.create_task(sweep_conversations(stop))
    try:
        yield
    finally:
        stop.set()
        await cleanup


app = FastAPI(title='My Closet AI', version='0.1.0', debug=False, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[host.strip() for host in __import__('os').getenv('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')])
COOKIE = '__Host-closet' if config.PRODUCTION else 'closet_session'
RATE_LOCK = threading.Lock()
RATE = {}
REVIEW_LOCK = threading.Lock()
REVIEWS = {}


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in {'POST', 'PUT', 'PATCH'}:
            return await self.app(scope, receive, send)
        parts, total = [], 0
        while True:
            event = await receive()
            if event['type'] == 'http.disconnect':
                return
            body = event.get('body', b'')
            total += len(body)
            if total > 5 * 1024 * 1024:
                return await JSONResponse({'detail': '요청은 5MB를 넘을 수 없습니다.'}, status_code=413)(scope, receive, send)
            parts.append(body)
            if not event.get('more_body'):
                break
        sent = False
        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {'type': 'http.request', 'body': b''.join(parts), 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)


app.add_middleware(BodyLimit)


@app.middleware('http')
async def security(request: Request, call_next):
    if request.method in {'POST', 'PUT', 'DELETE', 'PATCH'}:
        origin = request.headers.get('origin')
        if origin is not None and origin not in config.ORIGINS:
            return JSONResponse({'detail': '허용되지 않은 요청 출처입니다.'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': '다른 사이트에서 보낸 변경 요청을 차단했습니다.'}, status_code=403)
    token = request.cookies.get(COOKIE, '')
    owner = hashlib.sha256(token.encode()).hexdigest() if re.fullmatch('[a-f0-9]{64}', token) else ''
    fresh = False
    if request.url.path.startswith('/api/'):
        with RATE_LOCK:
            tick = int(time.monotonic() // 60)
            ip = request.client.host if request.client else 'unknown'
            is_login = request.method == 'POST' and request.url.path == '/api/login'
            bucket_key = (ip, is_login)
            for key in list(RATE):
                if RATE[key][0] != tick:
                    del RATE[key]
            if bucket_key not in RATE and len(RATE) >= 4096:
                return JSONResponse({'detail':'서버가 바쁩니다. 잠시 후 다시 시도해 주세요.'}, status_code=503)
            bucket = RATE.setdefault(bucket_key, [tick, 0])
            bucket[1] += 1
            if bucket[1] > (8 if is_login else 180):
                return JSONResponse({'detail':'요청이 많습니다. 잠시 후 다시 시도해 주세요.'}, status_code=429, headers={'Retry-After':'60'})
        session = store.get('sessions', 'server', owner) if owner else None
        if config.LOGIN_REQUIRED:
            request.state.session_id = owner
            user_id = session.get('user_id') if session and session.get('expires_at', 0) > time.time() else None
            request.state.authenticated = user_id is not None
            if user_id is None and request.url.path not in {'/api/status', '/api/login'}:
                return JSONResponse({'detail': '로그인이 필요합니다.'}, status_code=401,
                                    headers={'Cache-Control': 'no-store'})
            if user_id is not None:
                request.state.owner = f'member:{user_id}'
        elif not session:
            token = secrets.token_hex(32)
            owner = hashlib.sha256(token.encode()).hexdigest()
            store.put('sessions', 'server', owner, {'created_at': services.now()})
            fresh = True
        if not config.LOGIN_REQUIRED:
            request.state.owner = owner
    response = await call_next(request)
    if fresh:
        response.set_cookie(COOKIE, token, max_age=60*60*24*180, httponly=True, secure=config.PRODUCTION, samesite='lax', path='/')
    response.headers.update({
        'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
        'X-Frame-Options': 'DENY', 'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
        'Cache-Control': 'no-store' if request.url.path.startswith('/api/') else 'no-cache',
    })
    if not request.url.path.startswith('/docs'):
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    return response


@app.exception_handler(Exception)
async def safe_error(request, exception):
    return JSONResponse({'detail': '서버에서 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.'}, status_code=500)


def identifier(value):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', value):
        raise HTTPException(404, '항목을 찾을 수 없습니다.')
    return value


def owned(request, collection, key):
    row = store.get(collection, request.state.owner, identifier(key))
    if row is None:
        raise HTTPException(404, '항목을 찾을 수 없습니다.')
    return row


def active_conversation(request, key):
    row = owned(request, 'conversations', key)
    if row['updated_at'] <= conversation_cutoff():
        raise HTTPException(404, '이 대화의 보관 기간이 지났습니다. 새 대화를 시작해 주세요.')
    return row


def visible_garment(row):
    ready = row.get('conversion_version') == garment_images.VERSION
    private_fields = {'image_b64', 'original_b64', 'thumbnail_b64', 'wear_b64', 'base_mask_b64',
                      'source_sha256', 'conversion_key', 'has_base_mask', 'wear_fit'}
    return {**{key: value for key, value in row.items() if key not in private_fields},
            'image_ready': ready, 'has_base_mask': ready and bool(row.get('has_base_mask'))}


def image_record(row,owner):
    images=store.get('wardrobe_images',owner,row['id'])
    if images:
        return images
    if row.get('image_b64'):
        return {'original_b64':row['image_b64']}
    raise HTTPException(503,'저장된 의류 이미지를 찾을 수 없습니다.')


def garment_image_payload(original, converted):
    row={'original_b64':base64.b64encode(original).decode(),**converted}
    # Firestore native documents are capped at 1 MiB, including names/metadata.
    if len(json.dumps(row).encode())>900_000:
        raise HTTPException(413,'변환 이미지의 저장 용량을 초과했습니다.')
    return row


def save_images(owner, key, original, converted):
    return store.put('wardrobe_images', owner, key, garment_image_payload(original, converted))


@app.post('/api/login', status_code=204)
def login(body: Login, request: Request):
    if not config.LOGIN_REQUIRED:
        raise HTTPException(404, '로그인을 사용하지 않는 모드입니다.')
    account = store.get_user(body.username)
    digest = auth.hash_password(body.password, account[1] if account else '0' * 32)
    if not account or not secrets.compare_digest(digest, account[2]):
        raise HTTPException(401, '아이디 또는 비밀번호가 맞지 않습니다.')
    token = secrets.token_hex(32)
    session_id = hashlib.sha256(token.encode()).hexdigest()
    store.put('sessions', 'server', session_id,
              {'user_id': account[0], 'expires_at': time.time() + auth.SESSION_SECONDS})
    if request.state.authenticated:
        store.delete('sessions', 'server', request.state.session_id)
    response = Response(status_code=204)
    response.set_cookie(COOKIE, token, max_age=auth.SESSION_SECONDS, httponly=True,
                        secure=config.PRODUCTION, samesite='lax', path='/')
    return response


@app.post('/api/logout', status_code=204)
def logout(request: Request):
    if not config.LOGIN_REQUIRED:
        raise HTTPException(404, '로그인을 사용하지 않는 모드입니다.')
    store.delete('sessions', 'server', request.state.session_id)
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path='/', httponly=True, secure=config.PRODUCTION, samesite='lax')
    return response


@app.get('/api/status')
def status(request: Request):
    avatar = garment_images.AVATAR
    return {'storage': store.mode, 'ai_configured': bool(config.AI_KEY), 'image_analysis_enabled': config.IMAGE_ANALYSIS_ENABLED, 'garment_conversion_ready':garment_images.is_ready(), 'garment_review_ready':garment_images.review_is_ready(), 'login_required': config.LOGIN_REQUIRED, 'authenticated': getattr(request.state, 'authenticated', False), 'background_music_available': config.BACKGROUND_MUSIC_PATH.is_file(), 'date': services.today().isoformat(), 'conversation_retention_days': config.CONVERSATION_RETENTION_DAYS, 'source': 'SHIFT15M · CC BY-NC 4.0', 'source_period': services.SOURCE_PERIOD, 'avatar': {key: avatar[key] for key in ('image', 'canvas', 'foreground', 'hands_foreground', 'crop_boxes') if key in avatar}}


@app.get('/api/profile')
def get_profile(request: Request):
    settings = store.get('profiles', request.state.owner, 'settings') or {}
    if settings.get('closet_theme') in ('ivory', 'sage'):
        settings = {**settings, 'closet_theme': 'walnut'}
    return Profile.model_validate(settings).model_dump()


@app.put('/api/profile')
def put_profile(body: Profile, request: Request):
    if any(len(style) > 40 for style in body.styles):
        raise HTTPException(422, '스타일 이름이 너무 깁니다.')
    return store.put('profiles', request.state.owner, 'settings', body.model_dump())


@app.get('/api/data/summary')
def summary(request: Request):
    return services.summarize(services.dataset(store, request.state.owner))


@app.get('/api/data/export')
def export(request: Request, format: str = Query('json', pattern='^(json|csv)$')):
    rows = services.dataset(store, request.state.owner)
    if format == 'json':
        return Response(json.dumps(rows, ensure_ascii=False), media_type='application/json', headers={'Content-Disposition': 'attachment; filename="my-closet-data.json"'})
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['id', 'date', 'value', 'memo'])
    for row in rows:
        fields = [str(row[key]) for key in ['id', 'date', 'value', 'memo']]
        writer.writerow(["'" + field if field.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else field for field in fields])
    return Response('\ufeff' + output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="my-closet-data.csv"'})


@app.get('/api/data')
def get_data(request: Request, offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=100)):
    rows = services.dataset(store, request.state.owner)
    return {'items': rows[offset:offset+limit], 'total': len(rows), 'offset': offset}


@app.post('/api/data', status_code=201)
def add_data(body: DataPoint, request: Request):
    key = uuid.uuid4().hex
    row = {'id': key, **body.model_dump(mode='json'), 'source_modified': True}
    return store.put('data', request.state.owner, key, row)


@app.put('/api/data/{key}')
def edit_data(key: str, body: DataPoint, request: Request):
    key = identifier(key)
    existing = next((row for row in services.dataset(store, request.state.owner) if row['id'] == key), None)
    if existing is None:
        raise HTTPException(404, '데이터를 찾을 수 없습니다.')
    return store.put('data', request.state.owner, key, {'id': key, **body.model_dump(mode='json'), 'source_modified': True})


@app.delete('/api/data/{key}', status_code=204)
def delete_data(key: str, request: Request):
    key = identifier(key)
    if not any(row['id'] == key for row in services.dataset(store, request.state.owner)):
        raise HTTPException(404, '데이터를 찾을 수 없습니다.')
    store.put('data', request.state.owner, key, {'id': key, 'deleted': True})


@app.get('/api/wardrobe')
def wardrobe(request: Request):
    return [visible_garment(row) for row in sorted(store.list('wardrobe', request.state.owner), key=lambda row: row['created_at'], reverse=True)]


@app.post('/api/wardrobe/review', status_code=201)
def start_wear_review(request: Request, photo: UploadFile = File(...)):
    if not config.IMAGE_ANALYSIS_ENABLED or not garment_images.review_is_ready():
        raise HTTPException(503, '사진 분석 또는 전신 착용 이미지 기능이 준비되지 않았습니다.')
    owner = request.state.owner
    image = services.prepare_image(photo.file.read(4 * 1024 * 1024 + 1))
    source_hash = hashlib.sha256(image).hexdigest()
    rows = store.list('wardrobe', owner)
    for row in rows:
        if row.get('source_sha256') == source_hash and row.get('conversion_version') == garment_images.VERSION:
            return {'registered': visible_garment(row)}
    if len(rows) >= 100:
        raise HTTPException(409, '옷장에는 최대 100개까지 등록할 수 있습니다.')
    with REVIEW_LOCK:
        draft = REVIEWS.get(owner)
        if draft and draft['expires'] > time.monotonic() and draft['source_hash'] == source_hash:
            return {'review_id': draft['id'], 'has_auto_mask': bool(draft.get('auto_mask'))}
    result = services.inspect_garment(owner, image)
    if not result.is_clothing or result.confidence < .8:
        raise HTTPException(422, '의류가 선명하게 보이는 사진이 필요합니다.')
    frame = garment_images.prepare_wear_review(image, result.category, owner)
    try:
        auto_mask = garment_images.auto_review_mask(frame, result.category, owner)
    except Exception:
        # Preserve the try-on for manual review if the provider cannot return a mask.
        auto_mask = None
    key = uuid.uuid4().hex
    with REVIEW_LOCK:
        now = time.monotonic()
        for expired_owner in [owner for owner, draft in REVIEWS.items() if draft['expires'] <= now]:
            REVIEWS.pop(expired_owner)
        if len(REVIEWS) >= 64 and owner not in REVIEWS:
            raise HTTPException(429, '윤곽 편집 요청이 많습니다. 잠시 후 다시 시도해 주세요.')
        REVIEWS[owner] = {'id': key, 'expires': now + 3600, 'frame': frame, 'image': image,
                          'source_hash': source_hash, 'garment': result, 'auto_mask': auto_mask}
    return {'review_id': key, 'has_auto_mask': bool(auto_mask)}


def current_wear_review(owner, key):
    draft = REVIEWS.get(owner)
    if not draft or draft['id'] != key or draft['expires'] <= time.monotonic():
        raise HTTPException(404, '윤곽을 편집할 착용 이미지를 찾을 수 없습니다.')
    return draft


@app.get('/api/wardrobe/review/{key}')
def wear_review_image(key: str, request: Request):
    with REVIEW_LOCK:
        draft = current_wear_review(request.state.owner, key)
        return Response(base64.b64decode(draft['frame']), media_type='image/webp')


@app.get('/api/wardrobe/review/{key}/mask')
def wear_review_mask(key: str, request: Request):
    with REVIEW_LOCK:
        draft = current_wear_review(request.state.owner, key)
        if not draft.get('auto_mask'):
            raise HTTPException(404, '자동 생성된 의류 윤곽이 없습니다.')
        return Response(draft['auto_mask'], media_type='image/png')


@app.post('/api/wardrobe/review/{key}', status_code=201)
def finish_wear_review(key: str, review: WearReview, request: Request):
    owner = request.state.owner
    with REVIEW_LOCK:
        draft = current_wear_review(owner, key)
        rows = store.list('wardrobe', owner)
        if len(rows) >= 100:
            raise HTTPException(409, '옷장에는 최대 100개까지 등록할 수 있습니다.')
        converted = garment_images.save_reviewed_layer(draft['frame'], review, draft.get('auto_mask'))
        result = draft['garment']
        row = {'id': key, **result.model_dump(exclude={'is_clothing', 'confidence', 'wear_fit'}),
               'conversion_version': garment_images.VERSION, 'cutout_size': converted['cutout_size'],
               'has_base_mask': bool(converted.get('base_mask_b64')), 'source_sha256': draft['source_hash'],
               'image_version': services.now(), 'created_at': services.now()}
        store.save_garment(owner, row, garment_image_payload(draft['image'], converted))
        REVIEWS.pop(owner)
        return visible_garment(row)


@app.post('/api/wardrobe', status_code=201)
def add_garment(request: Request, photo: UploadFile = File(...)):
    if not config.IMAGE_ANALYSIS_ENABLED:
        raise HTTPException(503, '사진 분석 연동이 준비되지 않았습니다. 사진을 외부 AI에 전송하거나 저장하지 않았습니다.')
    garment_images.ensure_ready()
    owner = request.state.owner
    if len(store.list('wardrobe', owner)) >= 100:
        raise HTTPException(409, '옷장에는 최대 100개까지 등록할 수 있습니다.')
    image = services.prepare_image(photo.file.read(4 * 1024 * 1024 + 1))
    source_hash=hashlib.sha256(image).hexdigest()
    for existing in store.list('wardrobe',owner):
        if existing.get('source_sha256')==source_hash:
            return visible_garment(existing)
    result = services.inspect_garment(owner, image)
    if not result.is_clothing or result.confidence < .8:
        raise HTTPException(422, '의류가 선명하게 보이는 사진이 필요합니다. 다시 촬영해 올려 주세요.')
    fit = garment_images.fit_for_category(result.category, result.wear_fit)
    converted=garment_images.convert(image,result.category,result.name,owner,wear_fit=fit)
    key = uuid.uuid4().hex
    row = {'id': key, **result.model_dump(exclude={'is_clothing','confidence','wear_fit'}), **{field:converted[field] for field in ('conversion_version','conversion_ms','cutout_size')}, 'has_base_mask':bool(converted.get('base_mask_b64')), 'source_sha256':source_hash, 'conversion_key':converted['conversion_key'], 'image_version':services.now(), 'created_at': services.now()}
    if fit:
        row['wear_fit'] = fit
    store.save_garment(owner, row, garment_image_payload(image, converted))
    return visible_garment(row)


@app.get('/api/wardrobe/{key}/image')
def garment_image(key: str, request: Request):
    row = owned(request, 'wardrobe', key)
    images=image_record(row,request.state.owner)
    ready=row.get('conversion_version')==garment_images.VERSION and images.get('conversion_version')==garment_images.VERSION and bool(images.get('thumbnail_b64'))
    return Response(base64.b64decode(images['thumbnail_b64'] if ready else images['original_b64']), media_type='image/webp' if ready else 'image/jpeg')


@app.get('/api/wardrobe/{key}/wear')
def garment_wear(key: str, request: Request):
    row=owned(request,'wardrobe',key)
    images=image_record(row,request.state.owner)
    if row.get('conversion_version')!=garment_images.VERSION or images.get('conversion_version')!=garment_images.VERSION or not images.get('wear_b64'):
        raise HTTPException(409,'이 의류는 AI 착용 이미지 생성이 필요합니다. 이전 단순 합성 결과는 사용하지 않습니다.')
    return Response(base64.b64decode(images['wear_b64']),media_type='image/webp')


@app.get('/api/wardrobe/{key}/base-mask')
def garment_base_mask(key: str, request: Request):
    row = owned(request, 'wardrobe', key)
    if row.get('conversion_version') != garment_images.VERSION or not row.get('has_base_mask'):
        raise HTTPException(404, '저장된 아바타 가림 정보가 없습니다.')
    images = image_record(row, request.state.owner)
    if images.get('conversion_version') != garment_images.VERSION or not images.get('base_mask_b64'):
        raise HTTPException(404, '저장된 아바타 가림 정보가 없습니다.')
    return Response(base64.b64decode(images['base_mask_b64']), media_type='image/png')


@app.post('/api/wardrobe/{key}/convert')
def convert_garment(key: str, request: Request):
    row=owned(request,'wardrobe',key)
    images=image_record(row,request.state.owner)
    if row.get('conversion_version')==garment_images.VERSION and images.get('conversion_version')==garment_images.VERSION and images.get('wear_b64'):
        return visible_garment(row)
    raw=base64.b64decode(images['original_b64'])
    converted=garment_images.convert(raw,row['category'],row['name'],request.state.owner,wear_fit=row.get('wear_fit'))
    save_images(request.state.owner,key,raw,converted)
    row.pop('image_b64',None)
    row.update({field:converted[field] for field in ('conversion_version','conversion_ms','cutout_size')})
    row['has_base_mask']=bool(converted.get('base_mask_b64'))
    row.update(source_sha256=hashlib.sha256(raw).hexdigest(),conversion_key=converted['conversion_key'])
    row['image_version']=services.now()
    store.put('wardrobe',request.state.owner,key,row)
    return visible_garment(row)


@app.put('/api/wardrobe/{key}')
def update_garment(key: str, body: Garment, request: Request):
    row = owned(request, 'wardrobe', key)
    if row['category'] != body.category:
        row.pop('wear_fit', None)
        if row.get('conversion_version'):
            row['conversion_version']=0
            row['image_version']=services.now()
    row.update(body.model_dump())
    store.put('wardrobe', request.state.owner, key, row)
    return visible_garment(row)


@app.delete('/api/wardrobe/{key}', status_code=204)
def delete_garment(key: str, request: Request):
    owned(request, 'wardrobe', key)
    store.delete('wardrobe', request.state.owner, key)
    store.delete('wardrobe_images',request.state.owner,key)


def active_conversations(owner):
    cutoff = conversation_cutoff()
    return [row for row in store.list('conversations', owner) if row['updated_at'] > cutoff]


@app.get('/api/conversations')
def conversations(request: Request):
    rows = active_conversations(request.state.owner)
    return [{k: row[k] for k in ('id','title','updated_at')} for row in sorted(rows, key=lambda row: row['updated_at'], reverse=True)]


@app.get('/api/conversations/{key}')
def conversation(key: str, request: Request):
    row = active_conversation(request, key)
    messages = [
        {**message, 'outfit_season': outfit_season_for_date(message['outfit_date'])}
        if message.get('outfit_date') and not message.get('outfit_season') else message
        for message in row['messages']
    ]
    return {**row, 'messages': messages}


@app.delete('/api/conversations/{key}', status_code=204)
def delete_conversation(key: str, request: Request):
    owned(request, 'conversations', key)
    store.delete('conversations', request.state.owner, key)


@app.post('/api/conversations', status_code=201)
def save_conversation(body: Chat, request: Request):
    # Uses the same verified chat-and-save operation; arbitrary AI messages cannot be forged.
    return chat(body, request)


@app.post('/api/chat')
def chat(body: Chat, request: Request):
    today = services.today()
    date = body.date or today
    if date < today:
        raise HTTPException(422, '추천 날짜는 오늘부터 선택할 수 있습니다.')
    owner = request.state.owner
    profile = get_profile(request)
    garments = store.list('wardrobe', owner)
    previous = active_conversation(request, body.conversation_id) if body.conversation_id else None
    if previous and body.saved_outfit_id:
        raise HTTPException(422, '대화 또는 저장한 코디 중 하나를 선택해 주세요.')
    history = list(previous['messages']) if previous else []
    saved = owned(request, 'outfits', body.saved_outfit_id) if body.saved_outfit_id else None
    if saved:
        current_ids = {row['id'] for row in garments}
        history.append({'role':'assistant', 'content':saved.get('note') or '저장한 코디입니다.',
                        'outfit_ids':[key for key in saved['outfit_ids'] if key in current_ids],
                        'outfit_date':saved['date'], 'outfit_season':saved.get('outfit_season'),
                        'outfit_occasion':saved.get('outfit_occasion'),
                        'outfit_time':saved.get('outfit_time'), 'front_closures':saved.get('front_closures', []),
                        'season_override_ids':saved.get('season_override_ids', [])})
    if previous and len(previous['messages']) >= 100:
        raise HTTPException(409, '이 대화가 길어졌습니다. 새 대화를 시작해 주세요.')
    if not previous and len(active_conversations(owner)) >= 100:
        raise HTTPException(409, '대화 기록이 100개입니다. 오래된 대화를 삭제해 주세요.')
    season = services.season_for_month(date.month)
    selected_overrides = set(body.season_override_ids)
    owned_ids = {row['id'] for row in garments}
    if not selected_overrides.issubset(owned_ids):
        raise HTTPException(422, '옷장에 있는 의류만 입기로 선택할 수 있습니다.')
    previous_outfit = next((message for message in reversed(history)
                            if message['role'] == 'assistant' and message.get('outfit_ids')), {})
    previous_overrides = set(previous_outfit.get('season_override_ids', [])) if (
        previous_outfit.get('outfit_date') == date.isoformat()
    ) else set()
    mentions = services.mentioned_offseason_items(body.message, garments, season)
    check_outfit_seasons(mentions, season, selected_overrides | previous_overrides)
    conditions = {'date': date.isoformat(), 'season': season, 'occasion': body.occasion}
    if body.time:
        conditions['time'] = body.time
    notice = f'{season} 코디 기준' + (f' · 외출 시간 {body.time} 반영' if body.time else '')
    result = services.recommend(owner, body, profile, garments, summary(request), history, conditions)
    # Recheck latest ownership after the external call to block concurrent deletion.
    current = {row['id'] for row in store.list('wardrobe', owner)}
    if not set(result.outfit_ids).issubset(current):
        raise HTTPException(409, '추천 도중 옷장이 변경되었습니다. 다시 추천해 주세요.')
    if previous:
        active_conversation(request, previous['id'])
    key = previous['id'] if previous else uuid.uuid4().hex
    messages = history
    messages.extend([
        {'role':'user','content':body.message},
        {'role':'assistant','content':result.answer, 'outfit_ids':result.outfit_ids,
         'outfit_date':date.isoformat(), 'outfit_season':season,
         'outfit_occasion':body.occasion, 'outfit_time':body.time,
         'front_closures':[entry.model_dump() for entry in result.front_closures],
         'season_override_ids':[key for key in result.outfit_ids if key in selected_overrides | previous_overrides]},
    ])
    row = {'id':key, 'title': previous['title'] if previous else body.message[:40], 'messages':messages, 'updated_at':services.now()}
    store.put('conversations', owner, key, row)
    return {'conversation_id':key, **result.model_dump(), 'outfit_date':date.isoformat(),
            'outfit_season':season, 'weather':None, 'notice':notice}


def outfit_preview_inputs(request, item_ids, *, occasion, front_closures):
    owner = request.state.owner
    garments = []
    fingerprints = []
    closures = {entry['item_id']: entry['mode'] for entry in front_closures or ()}
    closure_by_image = {}
    styled_fingerprints = []
    for item_id in sorted(item_ids):
        row = owned(request, 'wardrobe', item_id)
        images = image_record(row, owner)
        raw = base64.b64decode(images['original_b64'], validate=True)
        category = row['category']
        garments.append((category, raw))
        fingerprint = (category, hashlib.sha256(raw).hexdigest())
        fingerprints.append(fingerprint)
        mode = closures.get(item_id, '') if category in ('상의', '아우터') else ''
        if mode:
            closure_by_image[len(garments) + 1] = mode
        styled_fingerprints.append((*fingerprint, mode))
    avatar = hashlib.sha256(garment_images.BASE_PATH.read_bytes()).hexdigest()
    model = garment_images.wear_model()
    versions = [((garment_images.OUTFIT_PREVIEW_VERSION, model, avatar, occasion), sorted(styled_fingerprints))]
    if front_closures is None:
        # Only old saved outfits may fall back to images made without the styling rules.
        for version in (('4', model, avatar), ('3', model, avatar, garment_images.AVATAR['identity_face_box'])):
            versions.append((version, sorted(fingerprints)))
    keys = [hashlib.sha256(json.dumps(value).encode()).hexdigest() for value in versions]
    return keys, garments, closure_by_image


def cached_outfit_preview_key(request, row):
    try:
        keys, _, _ = outfit_preview_inputs(request, row['outfit_ids'],
                                           occasion=row.get('outfit_occasion') or '일상',
                                           front_closures=row.get('front_closures'))
    except HTTPException as error:
        if error.status_code not in (404, 503):
            raise
        return None
    return next((key for key in keys if store.get('outfit_previews', request.state.owner, key)), None)


@app.get('/api/conversations/{key}/previews/{index}')
@app.post('/api/conversations/{key}/previews/{index}')
def outfit_preview(key: str, index: int, request: Request):
    conversation = active_conversation(request, key)
    messages = conversation['messages']
    if not 0 <= index < len(messages) or messages[index]['role'] != 'assistant' or not messages[index].get('outfit_ids'):
        raise HTTPException(404, '착용 이미지로 만들 추천 코디가 없습니다.')
    _, image = generate_outfit_preview(request, messages[index], lambda: active_conversation(request, key))
    return Response(base64.b64decode(image['image']), media_type='image/webp')


def generate_outfit_preview(request, row, recheck):
    owner = request.state.owner
    item_ids = row['outfit_ids']
    occasion = row.get('outfit_occasion') or '일상'
    keys, garments, closures = outfit_preview_inputs(request, item_ids, occasion=occasion,
                                                     front_closures=row.get('front_closures', []))
    cache_key = keys[0]
    cached = store.get('outfit_previews', owner, cache_key)
    if cached:
        return cache_key, cached
    if request.method == 'GET':
        raise HTTPException(404, '저장된 전신 착용 이미지가 없습니다.')
    items = [owned(request, 'wardrobe', item_id) for item_id in item_ids]
    missing = [category for category in ('상의', '하의', '신발')
               if not any(item['category'] == category for item in items)]
    if missing:
        raise HTTPException(422, {'code':'required_items_missing',
                                  'message':'상의·하의·신발을 모두 선택해야 전신 착용 이미지를 만들 수 있어요. 빠진 품목: ' + ', '.join(missing)})
    season = row.get('outfit_season') or outfit_season_for_date(row.get('outfit_date') or row.get('date'))
    check_outfit_seasons(items, season, set(row.get('season_override_ids', [])))
    if not garment_images.review_is_ready():
        raise HTTPException(503, 'AI 전신 착용 이미지 생성이 준비되지 않았습니다.')
    if not garment_images.GATE.acquire(blocking=False):
        raise HTTPException(429, '다른 착용 이미지를 만드는 중입니다. 잠시 후 다시 시도해 주세요.')
    try:
        cached = store.get('outfit_previews', owner, cache_key)
        if cached:
            return cache_key, cached
        day = 'garment-image:' + services.now()[:10]
        if not store.reserve_ai(day, owner, config.GARMENT_IMAGE_DAILY_LIMIT):
            raise HTTPException(429, '오늘의 착용 이미지 생성 한도에 도달했습니다.')
        image = garment_images.render_outfit_preview(garments, occasion=occasion, front_closures=closures)
        for item_id in item_ids:
            owned(request, 'wardrobe', item_id)
        recheck()
        preview = store.put('outfit_previews', owner, cache_key, {'image': base64.b64encode(image).decode('ascii')})
        return cache_key, preview
    finally:
        garment_images.GATE.release()


@app.get('/api/outfits')
def outfits(request: Request):
    owner = request.state.owner
    available = {item['id'] for item in store.list('wardrobe', owner)}
    rows = store.list('outfits', owner)
    return [{**row, 'source': row.get('source', 'unknown'),
             'outfit_season': row.get('outfit_season') or outfit_season_for_date(row.get('date')),
             'available_ids': [key for key in row['outfit_ids'] if key in available],
             'missing_count': sum(key not in available for key in row['outfit_ids'])}
            for row in sorted(rows, key=lambda row: row['created_at'], reverse=True)]


def outfit_season_for_date(value):
    if not value:
        return None
    try:
        return services.season_for_month(datetime.fromisoformat(value).month)
    except (TypeError, ValueError):
        return None


def check_outfit_seasons(items, season, confirmed_ids):
    mismatches = [item for item in items if season and item['id'] not in confirmed_ids
                  and services.season_fit(item['season'], season) == '다른 계절']
    if mismatches:
        names = ', '.join(f"{item['name']}({item['season']})" for item in mismatches)
        raise HTTPException(409, {'code': 'season_confirmation_required',
                                  'message': f'착용 예정 계절은 {season}이에요. 등록 계절이 다른 의류는 {names}입니다.',
                                  'season': season,
                                  'items': [{'name':item['name'], 'season':item['season']} for item in mismatches],
                                  'item_ids': [item['id'] for item in mismatches]})


@app.get('/api/outfits/{key}/image')
@app.post('/api/outfits/{key}/image')
def saved_outfit_image(key: str, request: Request):
    row = owned(request, 'outfits', key)
    owner = request.state.owner
    image_key = row.get('preview_key') or cached_outfit_preview_key(request, row)
    image = store.get('outfit_previews', owner, image_key) if image_key else None
    if not image:
        if request.method == 'GET':
            raise HTTPException(404, '저장된 전신 착용 이미지가 없습니다.')
        try:
            image_key, image = generate_outfit_preview(request, row, lambda: owned(request, 'outfits', key))
        except HTTPException as error:
            if error.status_code in (404, 503) and any(
                not store.get('wardrobe', owner, item_id) for item_id in row['outfit_ids']
            ):
                raise HTTPException(409, '삭제된 의류가 포함된 코디는 전신 착용 이미지를 만들 수 없습니다.') from None
            raise
    if request.method == 'POST' and image_key != row.get('preview_key'):
        if not store.attach_outfit_preview(owner, key, image_key):
            raise HTTPException(404, '저장한 코디를 찾을 수 없습니다.')
    return Response(base64.b64decode(image['image']), media_type='image/webp')


@app.post('/api/outfits', status_code=201)
def save_outfit(body: SaveOutfit, request: Request):
    owner = request.state.owner
    note = ''
    context = {}
    outfit_date = str(body.date or services.today())
    if body.conversation_id:
        if body.item_ids or body.message_index is None:
            raise HTTPException(422, '저장할 추천을 선택해 주세요.')
        conversation = active_conversation(request, body.conversation_id)
        if body.message_index >= len(conversation['messages']):
            raise HTTPException(404, '추천을 찾을 수 없습니다.')
        message = conversation['messages'][body.message_index]
        if message['role'] != 'assistant':
            raise HTTPException(422, '추천 코디만 저장할 수 있습니다.')
        item_ids = message.get('outfit_ids', [])
        note = message['content']
        outfit_date = message.get('outfit_date', outfit_date)
        context = {field: message[field] for field in
                   ('outfit_occasion','outfit_time','front_closures','season_override_ids') if field in message}
        key = hashlib.sha256(f'{body.conversation_id}:{body.message_index}'.encode()).hexdigest()[:32]
        existing = store.get('outfits', owner, key)
        if existing:
            if not existing.get('preview_key'):
                image_key = cached_outfit_preview_key(request, existing)
                if image_key:
                    return store.put('outfits', owner, key, {**existing, 'preview_key': image_key})
            return existing
    else:
        if body.message_index is not None:
            raise HTTPException(422, '잘못된 코디 선택입니다.')
        item_ids = body.item_ids
        key = uuid.uuid4().hex
    if not item_ids or len(item_ids) != len(set(item_ids)):
        raise HTTPException(422, '옷장에서 저장할 옷을 선택해 주세요.')
    wardrobe = {item['id']: item for item in store.list('wardrobe', owner)}
    if not set(item_ids).issubset(wardrobe):
        raise HTTPException(409, '옷장에 없는 의류가 포함되어 저장할 수 없습니다.')
    if len(store.list('outfits', owner)) >= 100:
        raise HTTPException(409, '코디북에는 최대 100개까지 저장할 수 있습니다.')
    snapshot = [{field: wardrobe[key][field] for field in ('id','name','category','color','season')} for key in item_ids]
    row = {'id': key, 'title': body.title, 'date': outfit_date,
           'source': 'ai' if body.conversation_id else 'manual',
           'outfit_season': outfit_season_for_date(outfit_date),
           'outfit_ids': item_ids, 'items': snapshot, 'note': note, 'created_at': services.now(), **context}
    image_key = cached_outfit_preview_key(request, row)
    if image_key:
        row['preview_key'] = image_key
    return store.put('outfits', owner, key, row)


@app.delete('/api/outfits/{key}', status_code=204)
def delete_outfit(key: str, request: Request):
    owned(request, 'outfits', key)
    store.delete('outfits', request.state.owner, key)


@app.api_route('/api/background-music', methods=['GET', 'HEAD'], include_in_schema=False)
def background_music(request: Request):
    if not getattr(request.state, 'authenticated', False):
        raise HTTPException(401, '로그인이 필요합니다.')
    if not config.BACKGROUND_MUSIC_PATH.is_file():
        raise HTTPException(404, '배경 음악을 찾을 수 없습니다.')
    return FileResponse(config.BACKGROUND_MUSIC_PATH, media_type='audio/mpeg')


@app.get('/health', include_in_schema=False)
def health():
    return {'status': 'ok'}


@app.get('/')
def index():
    return FileResponse(config.ROOT / 'frontend/index.html')


app.mount('/assets', StaticFiles(directory=config.ROOT / 'frontend'), name='assets')
