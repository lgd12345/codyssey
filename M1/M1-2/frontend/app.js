'use strict';
const DATA_PAGE_SIZE = 10;
const OUTFIT_PAGE_SIZE = 6;
const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const HISTORY_COUNTDOWN_WINDOW_DAYS = 2;
const $ = id => document.getElementById(id);
const state = {garments: [], selected: [], profile: null, avatar: null, conversation: null, messages: [], category: '전체', offset: 0, total: 0, editData: null, editGarment: null, summary: null, conversionReady:false, uploadReady:false};
let outfitPreview = null;
let savedOutfit = null;
let openedOutfit = null;
let outfitRows = [];
let outfitPage = 0;
let conversationRetentionDays = 0;
let historyCountdownTimer;
const wearImages = new Map();
async function wearUrl(row, asset = 'wear') {
  const key = row.id + ':' + (row.image_version || row.conversion_version) + ':' + asset;
  if (wearImages.has(key)) return wearImages.get(key).promise;
  const entry = {url:null,promise:null,id:row.id};
  entry.promise = fetch('/api/wardrobe/'+encodeURIComponent(row.id)+'/'+asset,{credentials:'same-origin',signal:AbortSignal.timeout(15000)}).then(async response => {
    if (!response.ok) throw new Error('착용 이미지를 불러오지 못했습니다.');
    entry.url = URL.createObjectURL(await response.blob()); return entry.url;
  }).catch(error => {wearImages.delete(key); throw error;});
  wearImages.set(key,entry);
  for (const [oldKey,old] of wearImages) {
    if (wearImages.size<=8) break;
    if (oldKey!==key && old.url && !state.selected.includes(old.id)) {URL.revokeObjectURL(old.url); wearImages.delete(oldKey);}
  }
  return entry.promise;
}
let toastTimer;
function toast(message) {$('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => {$('toast').hidden = true;}, 6500);}
function node(tag, text, className) {const item = document.createElement(tag); if (text !== undefined) item.textContent = text; if (className) item.className = className; return item;}
function button(text, action, className = 'text-button') {const item = node('button', text, className); item.type = 'button'; item.addEventListener('click', () => Promise.resolve(action()).catch(error => toast(error.message))); return item;}

function confirmAction(message, labels = {}) {
  return new Promise(resolve => {
    const dialog = $('confirm-dialog');
    const description = $('confirm-message');
    const extra = $('confirm-extra');
    const structured = typeof message !== 'string';
    description.hidden = structured;
    description.textContent = structured ? '' : message;
    extra.hidden = !structured;
    extra.replaceChildren(...(structured ? [message] : []));
    dialog.setAttribute('aria-describedby', structured ? extra.id : description.id);
    $('confirm-title').textContent = labels.title || '삭제 확인';
    $('confirm-yes').textContent = labels.confirm || '삭제하기';
    $('confirm-no').textContent = labels.cancel || '취소';
    const finish = value => {dialog.onclose = null; dialog.close(); resolve(value);};
    $('confirm-yes').onclick = () => finish(true);
    $('confirm-no').onclick = () => finish(false);
    dialog.oncancel = event => {event.preventDefault(); finish(false);};
    dialog.onclose = () => finish(false);
    dialog.showModal();
  });
}

async function api(path, options = {}) {
  const {timeoutMs = 65000, responseType = 'json', missingAsNull = false,...requestOptions} = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = {...options.headers};
    if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    const response = await fetch('/api/' + path, {...requestOptions, headers, credentials: 'same-origin', signal: controller.signal});
    if (missingAsNull && response.status === 404) return null;
    if (!response.ok) {
      let message = '요청을 처리하지 못했습니다. 다시 시도해 주세요.';
      let detail;
      try {
        detail = (await response.json()).detail;
        if (typeof detail === 'string') message = detail;
        else if (typeof detail?.message === 'string') message = detail.message;
        else if (response.status === 422) message = '입력한 날짜·숫자·필수 항목을 확인해 주세요.';
      } catch {}
      const error = new Error(message);
      error.detail = detail;
      throw error;
    }
    if (response.status === 204) return null;
    return responseType === 'blob' ? response.blob() : response.json();
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.');
    if (error instanceof TypeError) throw new Error('서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해 주세요.');
    throw error;
  } finally {clearTimeout(timer);}
}
function applyTheme(theme) {
  document.body.classList.toggle('noir', theme === 'noir');
  const icon = document.createElementNS('http://www.w3.org/2000/svg','svg'); icon.classList.add('ui-icon'); icon.setAttribute('aria-hidden','true');
  const use = document.createElementNS('http://www.w3.org/2000/svg','use'); use.setAttribute('href',theme === 'noir' ? '#icon-sun' : '#icon-moon'); icon.append(use); $('mode-toggle').replaceChildren(icon);
  $('mode-toggle').setAttribute('aria-label',theme === 'noir' ? '밝은 모드로 전환' : '어두운 모드로 전환');
  $('mode-toggle').title = $('mode-toggle').getAttribute('aria-label');
  try {localStorage.setItem('closet-theme', theme);} catch {}
}
try {applyTheme(localStorage.getItem('closet-theme') || 'ivory');} catch {}
const musicToggle = $('music-toggle');
const backgroundMusic = $('background-music');
function updateMusicToggle() {
  const playing = !backgroundMusic.paused;
  musicToggle.setAttribute('aria-pressed', String(playing));
  musicToggle.title = playing ? '배경 음악 끄기' : '배경 음악 켜기';
}
backgroundMusic.addEventListener('play', updateMusicToggle);
backgroundMusic.addEventListener('pause', updateMusicToggle);
backgroundMusic.addEventListener('error', updateMusicToggle);
musicToggle.addEventListener('click', async () => {
  if (!backgroundMusic.paused) {
    backgroundMusic.pause();
    return;
  }
  if (!backgroundMusic.getAttribute('src') || backgroundMusic.error) {
    backgroundMusic.src = backgroundMusic.dataset.src;
  }
  backgroundMusic.volume = 0.25;
  try {
    await backgroundMusic.play();
  } catch (error) {
    updateMusicToggle();
    if (error.name !== 'AbortError') toast('배경 음악을 재생하지 못했습니다.');
  }
});
function applyProfile() {
  applyTheme(state.profile.theme);
  document.body.dataset.closetTheme = state.profile.closet_theme || 'walnut';
  const name = state.profile.name.trim();
  $('wardrobe-title').textContent = (name || '나의') + ' 옷장';
  document.querySelector('.profile-monogram').textContent = Array.from(
    (name || 'My').normalize('NFC').replace(/\s+/g, ''),
  ).slice(0,2).join('');
}
$('mode-toggle').addEventListener('click',async () => {
  if (!state.profile) return;
  const control = $('mode-toggle'); control.disabled = true;
  try {state.profile = await api('profile',{method:'PUT',body:JSON.stringify({...state.profile,theme:state.profile.theme === 'noir' ? 'ivory' : 'noir'})}); applyProfile();}
  catch(error) {toast(error.message);} finally {control.disabled = false;}
});
function renderView(view) {
  if (!['studio','insights','data','history','outfits'].includes(view)) view = 'studio';
  document.querySelectorAll('.view').forEach(element => {element.hidden = element.id !== 'view-' + view;});
  document.querySelectorAll('.nav').forEach(element => element.classList.toggle('active', element.dataset.view === view));
  if (view === 'insights') refreshSummary().catch(error => toast(error.message));
  if (view === 'data') loadData().catch(error => toast(error.message));
  if (view === 'history') loadHistory().catch(error => toast(error.message));
  else clearTimeout(historyCountdownTimer);
  if (view === 'outfits') loadOutfits().catch(error => toast(error.message));
}
function showView(view) {
  if (location.hash.slice(1) !== view) location.hash = view;
  else renderView(view);
}
window.addEventListener('hashchange', () => renderView(location.hash.slice(1) || 'studio'));
document.querySelectorAll('[data-view]').forEach(element => element.addEventListener('click', () => showView(element.dataset.view)));
document.querySelector('.brand').addEventListener('click', event => {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  markWardrobeCategory(defaultWardrobeTab);
  resetStudioDraft();
  showView('studio');
  requestAnimationFrame(() => {
    $('wardrobe-grid').scrollTop = 0;
    document.querySelector('#view-studio .recommend-panel').scrollTop = 0;
    window.scrollTo({top:0, behavior:'instant'});
  });
});
document.querySelectorAll('[data-close]').forEach(element => element.addEventListener('click', () => $(element.dataset.close).close()));
document.querySelectorAll('dialog:not(#login-dialog)').forEach(dialog => {
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
});

function renderWardrobe() {
  const grid = $('wardrobe-grid'); grid.replaceChildren();
  $('garment-count').textContent = state.garments.length;
  $('collection-caption').textContent = state.garments.length ? '직접 등록한 ' + state.garments.length + '벌 · 옷을 눌러 조합해 보세요' : '아직 비어 있는 옷장 · 첫 번째 옷을 담아 보세요';
  const headline = $('intro-headline'); headline.replaceChildren();
  headline.append(document.createTextNode(state.garments.length ? state.garments.length + '벌에서 시작하는,' : '첫 번째 옷부터,'),node('br'),document.createTextNode('나만의 새로운 조합.'));
  const rows = state.garments.filter(row => state.category === '전체' || row.category === state.category);
  $('category-title').textContent = state.category === '전체' ? '전체 의류' : state.category;
  $('category-count').textContent = rows.length + '벌';
  if (!rows.length) {const empty = node('div', undefined, 'empty-state'); empty.append(node('span', 'MY COLLECTION', 'empty-icon'), node('p', state.garments.length ? '이 카테고리에는 아직 옷이 없어요.' : '나만의 옷장을 채워볼까요?'), node('span', '사진 한 장으로 첫 번째 옷을 등록해 보세요.')); grid.append(empty); return;}
  rows.forEach(row => {
    const card = node('article', undefined, 'garment-card' + (state.selected.includes(row.id) ? ' chosen' : ''));
    const choose = button('', () => selectGarment(row), 'garment-photo-button');
    choose.setAttribute('aria-label', row.name + ' 미리보기'); choose.setAttribute('aria-pressed', state.selected.includes(row.id));
    const image = node('img'); image.src = '/api/wardrobe/' + encodeURIComponent(row.id) + '/image'; image.alt = row.name; image.loading = 'lazy'; choose.append(image);
    const edit = button('⋯', () => editGarment(row), 'garment-edit'); edit.setAttribute('aria-label', row.name + ' 정보 수정');
    card.append(choose, edit, node('p', row.name), node('small', row.category + ' · ' + row.season)); grid.append(card);
    if (!row.image_ready) {
      const generate = button('AI 착용 이미지 만들기',async () => {
        if (!await confirmAction('이 옷의 착용 이미지를 생성할까요? API 사용량이 발생하며, 생성한 결과는 저장해 재사용합니다.',{title:'착용 이미지 생성',confirm:'한 장 생성하기'})) return;
        generate.disabled = true; generate.textContent = '착용 이미지 생성 중…';
        try {await api('wardrobe/'+encodeURIComponent(row.id)+'/convert',{method:'POST',timeoutMs:180000}); await refreshWardrobe();}
        finally {generate.disabled = !state.conversionReady; generate.textContent = 'AI 착용 이미지 만들기';}
      },'text-button');
      generate.disabled = !state.conversionReady; card.append(generate);
    }
  });
}
async function selectGarment(row) {
  if (!row.image_ready) {
    toast('먼저 이 옷의 AI 착용 이미지를 만들어 주세요. 옷 선택만으로는 생성 요금이 발생하지 않습니다.'); return;
  }
  clearOutfitPreview();
  if (state.selected.includes(row.id)) state.selected = state.selected.filter(id => id !== row.id);
  else {
    state.selected = state.selected.filter(id => {const item = state.garments.find(g => g.id === id); return item && item.category !== row.category && !(row.category === '원피스' && ['상의','하의'].includes(item.category)) && !(['상의','하의'].includes(row.category) && item.category === '원피스');});
    state.selected.push(row.id);
  }
  renderWardrobe(); renderOutfit();
}
function applyAvatar(avatar) {
  const [width, height] = avatar.canvas;
  const image = {href: '/assets/assets/' + encodeURIComponent(avatar.image), width, height};
  $('avatar-doll').setAttribute('viewBox', `0 0 ${width} ${height}`);
  $('avatar-base').replaceChildren(svgNode('image', image));
  state.avatar = avatar;
}
function loadAvatarImage(src) {
  const image = new Image();
  image.src = src;
  return image.decode().then(() => image);
}
async function renderAvatarComposite(wear, rows) {
  const {canvas: [width, height], image, crop_boxes: boxes} = state.avatar;
  const result = svgNode('image', {width, height});
  wear.append(result);
  const [base, layers, masks] = await Promise.all([
    loadAvatarImage('/assets/assets/' + encodeURIComponent(image)),
    Promise.all(rows.map(row => wearUrl(row).then(loadAvatarImage))),
    Promise.all(rows.filter(row => row.has_base_mask)
      .map(row => wearUrl(row, 'base-mask').then(loadAvatarImage)))
  ]);
  if (!result.isConnected) return;
  const canvas = node('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  context.drawImage(base, 0, 0, width, height);
  if (boxes) {
    rows.forEach((row, index) => {
      const [x, y, right, bottom] = boxes[row.category];
      const w = right - x, h = bottom - y;
      context.clearRect(x, y, w, h);
      context.drawImage(layers[index], x, y, w, h, x, y, w, h);
    });
  } else {
    context.globalCompositeOperation = 'destination-out';
    masks.forEach(mask => context.drawImage(mask, 0, 0, width, height));
    context.globalCompositeOperation = 'source-over';
    layers.forEach(layer => context.drawImage(layer, 0, 0, width, height));
  }
  result.setAttribute('href', canvas.toDataURL());
  $('avatar-base').setAttribute('visibility', 'hidden');
}
function clearOutfitPreview() {
  if (outfitPreview?.url) URL.revokeObjectURL(outfitPreview.url);
  outfitPreview = null;
}

function rememberOpenedOutfit() {
  openedOutfit = {
    itemIds: [...state.selected],
    preview: outfitPreview ? {...outfitPreview} : null,
  };
}

function openedOutfitItems() {
  return openedOutfit.itemIds.filter(id => state.garments.some(row => row.id === id));
}

async function loadOutfitPreview(preview, method = 'POST') {
  const path = preview.savedId
    ? 'outfits/' + encodeURIComponent(preview.savedId) + '/image'
    : 'conversations/' + encodeURIComponent(preview.conversation) + '/previews/' + preview.index;
  const checking = method === 'GET';
  let url;
  try {
    const image = await api(path, {method, timeoutMs:checking ? 15000 : 160000, responseType:'blob', missingAsNull:checking});
    if (preview !== outfitPreview) return;
    if (image === null) {
      preview.status = 'available';
      return;
    }
    url = URL.createObjectURL(image);
    const rendered = new Image();
    rendered.src = url;
    await rendered.decode();
    if (preview !== outfitPreview) return;
    preview.url = url;
    url = null;
    preview.status = 'ready';
  } catch (error) {
    if (preview === outfitPreview) {
      if (!checking && error.detail?.code === 'season_confirmation_required') {
        preview.status = 'available';
        renderOutfit();
        const confirmed = await confirmSeason(error);
        if (preview !== outfitPreview) return;
        if (confirmed) {
          await requestOutfitChange('입기로 선택한 의류는 유지하고, 상의·하의·신발을 모두 갖추도록 나머지 코디를 조정해 주세요.', error.detail.item_ids);
        }
      } else {
        preview.status = checking ? 'lookup-failed' : error.detail?.code === 'required_items_missing' ? 'blocked' : 'failed';
        preview.error = error.message;
      }
    }
  } finally {
    if (url) URL.revokeObjectURL(url);
    if (preview === outfitPreview) renderOutfit();
  }
}

function renderOutfit() {
  const area = $('recommendation'); area.replaceChildren();
  const pieces = node('div', undefined, 'outfit-pieces');
  state.selected = state.selected.filter(id => state.garments.some(row => row.id === id));
  const recommendationIndex = state.messages.findLastIndex(message => message.role === 'assistant' && message.outfit_ids?.length);
  const lastIndex = recommendationIndex >= 0 ? recommendationIndex : state.messages.findLastIndex(message => message.role === 'assistant');
  const last = state.messages[lastIndex];
  const isRecommendation = Boolean(state.conversation && last?.outfit_ids?.length && last.outfit_ids.length === state.selected.length && last.outfit_ids.every(id => state.selected.includes(id)));
  const matchesRecommendation = isRecommendation && outfitPreview?.conversation === state.conversation && outfitPreview.index === lastIndex;
  const preview = outfitPreview?.savedId || matchesRecommendation ? outfitPreview : null;
  const preparing = preview?.status === 'loading';
  const dressed = preview?.status === 'ready';
  state.selected.forEach(id => {
    const row = state.garments.find(item => item.id === id);
    const piece = node('div', undefined, 'outfit-piece'); const image = node('img'); image.src = '/api/wardrobe/' + encodeURIComponent(id) + '/image'; image.alt = row.name; piece.append(image, node('span', row.name)); pieces.append(piece);
  });
  const wear = $('avatar-garments'); wear.replaceChildren();
  const order = {'하의':10,'상의':20,'원피스':20,'아우터':30,'신발':35,'가방':40,'액세서리':45};
  const ready = dressed ? [] : state.selected.map(id => state.garments.find(row => row.id === id)).filter(row => row.image_ready).sort((a,b) => order[a.category]-order[b.category]);
  $('avatar-base').removeAttribute('visibility');
  $('avatar-outfit-image').replaceChildren();
  $('avatar-preparing').hidden = !preparing;
  $('avatar-doll').setAttribute('aria-label', dressed ? '추천 의류를 함께 입은 AI 전신 착용 이미지' : '기본 아바타에 등록한 의류를 합성한 미리보기');
  if (dressed) {
    const [width, height] = state.avatar.canvas;
    $('avatar-base').setAttribute('visibility', 'hidden');
    $('avatar-outfit-image').append(svgNode('image', {href:preview.url, width, height}));
  }
  if (ready.length && (state.avatar?.crop_boxes || ready.some(row => row.has_base_mask))) {
    renderAvatarComposite(wear, ready).catch(error => toast(error.message));
  } else ready.forEach(row => {
    const [width, height] = state.avatar.canvas;
    const image = svgNode('image',{width,height}); wear.append(image);
    wearUrl(row).then(url => {if (image.isConnected) image.setAttribute('href',url);}).catch(error => toast(error.message));
  });
  const originalItems = openedOutfit ? openedOutfitItems() : [];
  const hasSelectionChanges = originalItems.length !== state.selected.length ||
    originalItems.some(id => !state.selected.includes(id));
  $('reset-outfit').disabled = openedOutfit
    ? !hasSelectionChanges && !(openedOutfit.preview && !outfitPreview)
    : state.selected.length === 0 && !dressed;
  const readyCount = state.selected.filter(id => state.garments.find(row => row.id===id)?.image_ready).length;
  $('avatar-status').textContent = state.selected.length ? readyCount===state.selected.length ? '내 옷 ' + readyCount + '벌 · 저장된 착용 이미지' : '착용 이미지 미생성 · 원본 의류 카드로 확인하세요' : '기본 모델 · 흰색 민소매와 반바지';
  if (preparing) $('avatar-status').textContent = '';
  if (dressed) $('avatar-status').textContent = 'AI 전신 착용 미리보기';
  if (preview?.error) $('avatar-status').textContent = preview.error + ' 기본 미리보기로 표시합니다.';
  if (savedOutfit || state.selected.length || (last && !last.outfit_ids?.length)) {
    const heading = node('div',undefined,'result-heading');
    const title = savedOutfit?.title || (isRecommendation ? '오늘의 추천 코디' : state.selected.length ? '직접 고른 코디' : '나의 스타일 노트');
    heading.append(node('h3',title));
    if (savedOutfit) {
      heading.append(button('코디 정보 수정', () => openEditOutfit(savedOutfit), 'outline-button edit-outfit-trigger'));
    } else {
      heading.append(node('span', state.selected.length ? '한 가지 조합' : 'AI 코디 제안'));
    }
    area.append(heading);
    const note = savedOutfit ? savedOutfit.note : (isRecommendation || !state.selected.length) ? last?.content : null;
    const details = (savedOutfit
      ? [savedOutfit.outfit_season, savedOutfit.date]
      : [last?.outfit_season, last?.outfit_date]).filter(Boolean).join(' · ');
    if (details) area.append(node('p',details,'small-note saved-outfit-context'));
    if (note) area.append(node('p',note,'result-note'));
    if (state.selected.length) {
      area.append(pieces);
      const payload = isRecommendation ? {conversation_id:state.conversation,message_index:lastIndex} : {item_ids:[...state.selected],date:$('outfit-date').value};
      const canGenerate = isRecommendation || (preview?.savedId && savedOutfit?.outfit_ids.length === state.selected.length);
      if (canGenerate && preview && ['available','failed'].includes(preview.status)) {
        const label = preview.error ? '전신 착용 이미지 다시 만들기' : '전신 착용 이미지 만들기';
        area.append(button(label, () => {
          preview.status = 'loading';
          delete preview.error;
          renderOutfit();
          return loadOutfitPreview(preview);
        }, 'outline-button outfit-preview-button'));
      }
      if (preview?.status === 'lookup-failed') {
        area.append(button('저장된 이미지 다시 확인', () => {
          preview.status = 'checking';
          delete preview.error;
          renderOutfit();
          return loadOutfitPreview(preview, 'GET');
        }, 'outline-button outfit-preview-button'));
      }
      if (!savedOutfit) area.append(button('이 코디 저장하기',() => openSaveOutfit(payload),'outline-button'));
    }
  }
}
async function refreshWardrobe() {state.garments = await api('wardrobe'); renderWardrobe(); renderOutfit(); state.garments.filter(row => row.image_ready).slice(0,8).forEach(row => wearUrl(row).catch(() => {}));}
const wardrobeTabs = document.querySelectorAll('[data-category]');
const defaultWardrobeTab = [...wardrobeTabs].find(tab => tab.dataset.category === state.category);
function markWardrobeCategory(current) {
  state.category = current.dataset.category;
  for (const tab of wardrobeTabs) {
    tab.classList.toggle('selected', tab === current);
    tab.setAttribute('aria-pressed', String(tab === current));
  }
}
wardrobeTabs.forEach(tab => tab.addEventListener('click', () => {
  markWardrobeCategory(tab);
  renderWardrobe();
}));
$('reset-outfit').addEventListener('click', () => {
  clearOutfitPreview();
  state.selected = openedOutfit ? openedOutfitItems() : [];
  if (openedOutfit?.preview && (state.selected.length || openedOutfit.preview.savedId)) {
    outfitPreview = {...openedOutfit.preview, status:'checking'};
  }
  renderWardrobe();
  renderOutfit();
  if (outfitPreview) void loadOutfitPreview(outfitPreview, 'GET');
});
function openUpload() {$('upload-feedback').textContent = state.uploadReady ? '' : '착용 이미지 기능을 준비 중입니다. 사진 선택과 미리보기는 가능하지만 아직 등록할 수 없습니다.'; $('upload-submit').disabled = !state.uploadReady; $('upload-dialog').showModal();}
$('upload-open').addEventListener('click', openUpload);
let previewUrl;
$('photo').addEventListener('change', () => {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  const file = $('photo').files[0];
  $('photo-preview').hidden = !file; $('upload-feedback').textContent = '';
  if (!file) return;
  if (file.size > 4 * 1024 * 1024) {$('upload-feedback').textContent = '4MB 이하의 사진으로 다시 선택해 주세요.'; $('photo').value = ''; $('photo-preview').hidden = true; return;}
  previewUrl = URL.createObjectURL(file); $('photo-preview').src = previewUrl;
});
$('upload-form').addEventListener('submit', async event => {
  event.preventDefault(); if (!state.uploadReady) return; const submit = $('upload-submit'); submit.disabled = true; submit.textContent = '사진에서 의류를 확인하고 있습니다…'; $('upload-feedback').textContent = '분석에 시간이 걸릴 수 있습니다. 완료될 때까지 기다려 주세요.';
  try {
    const form = new FormData();
    form.append('photo', $('photo').files[0]);
    const result = await api('wardrobe/review', {method:'POST', body:form,timeoutMs:300000});
    if (result.review_id) await openWearReview(result.review_id, result.has_auto_mask);
    else toast('이미 옷장에 등록된 사진입니다.');
    $('upload-dialog').close();
    $('upload-form').reset();
    $('photo-preview').hidden = true;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }
  catch (error) {$('upload-feedback').textContent = error.message + ' 사진을 바꾸어 다시 등록할 수 있습니다.';}
  finally {submit.disabled = !state.uploadReady; submit.textContent = '착용 결과 확인하기';}
});

let wearReview;
const reviewCanvas = $('wear-review-canvas');
const reviewViewport = $('wear-review-viewport');

async function openWearReview(id, hasAutoMask) {
  const url = '/api/wardrobe/review/' + encodeURIComponent(id);
  const [image, maskImage] = await Promise.all([
    loadAvatarImage(url),
    hasAutoMask ? loadAvatarImage(url + '/mask').catch(() => null) : null
  ]);
  const [width, height] = state.avatar.canvas;
  const matchesCanvas = picture => picture?.naturalWidth === width && picture.naturalHeight === height;
  if (!matchesCanvas(image)) throw new Error('착용 이미지 크기가 아바타와 맞지 않습니다.');
  const autoMask = matchesCanvas(maskImage) ? maskImage : null;
  reviewCanvas.width = width;
  reviewCanvas.height = height;
  const selection = document.createElement('canvas');
  selection.width = width;
  selection.height = height;
  wearReview = {id, image, autoMask, selection, points: [], regions: [], zoom: 1};
  $('wear-review-auto').checked = Boolean(autoMask);
  $('wear-review-auto').disabled = !autoMask;
  $('wear-review-preview').checked = false;
  $('wear-review-status').textContent = autoMask ? '' : '자동 윤곽을 만들지 못했습니다. 옷 영역을 직접 선택할 수 있습니다.';
  reviewCanvas.style.setProperty('--review-zoom', 1);
  reviewViewport.scrollTo(0, 0);
  drawWearReview();
  $('wear-review-dialog').showModal();
}

function traceReviewPath(context, points) {
  context.beginPath();
  for (const [index, [x, y]] of points.entries()) {
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  }
}

function drawWearReview() {
  const {image, autoMask, selection, points, regions} = wearReview;
  const {width, height} = reviewCanvas;
  const context = reviewCanvas.getContext('2d');
  const mask = selection.getContext('2d');
  const useAuto = Boolean(autoMask && $('wear-review-auto').checked);
  const preview = $('wear-review-preview').checked;
  mask.globalCompositeOperation = 'source-over';
  mask.clearRect(0, 0, width, height);
  if (useAuto) mask.drawImage(autoMask, 0, 0);
  for (const kind of ['outlines', 'openings']) {
    mask.globalCompositeOperation = kind === 'outlines' ? 'source-over' : 'destination-out';
    for (const region of regions.filter(region => region.kind === kind)) {
      traceReviewPath(mask, region.points);
      mask.fill();
    }
  }
  mask.globalCompositeOperation = 'source-in';
  if (preview) mask.drawImage(image, 0, 0);
  else {
    mask.fillStyle = '#147965';
    mask.fillRect(0, 0, width, height);
  }
  context.clearRect(0, 0, width, height);
  if (!preview) context.drawImage(image, 0, 0);
  context.globalAlpha = preview ? 1 : .35;
  context.drawImage(selection, 0, 0);
  context.globalAlpha = 1;
  const colors = {outlines:'#147965', hide_base:'#785514'};
  const pending = {kind: 'outlines', points};
  for (const region of [...regions.filter(region => region.kind === 'hide_base'), pending]) {
    if (!region.points.length) continue;
    traceReviewPath(context, region.points);
    context.strokeStyle = colors[region.kind];
    context.lineWidth = 3;
    if (region !== pending) {
      context.closePath();
      context.fillStyle = colors[region.kind] + '40';
      context.fill();
    }
    context.stroke();
  }
  for (const [x, y] of points) {
    context.beginPath();
    context.arc(x, y, 4, 0, Math.PI * 2);
    context.fillStyle = colors[pending.kind];
    context.fill();
  }
  for (const id of ['wear-review-add', 'wear-review-remove', 'wear-review-hide']) $(id).disabled = points.length < 3;
  $('wear-review-clear').disabled = !points.length;
  $('wear-review-zoom-value').textContent = `${wearReview.zoom * 100}%`;
  $('wear-review-zoom-out').disabled = wearReview.zoom <= 1;
  $('wear-review-zoom-in').disabled = wearReview.zoom >= 3;
  $('wear-review-undo').disabled = !points.length && !regions.length;
  $('wear-review-save').disabled = Boolean(points.length) || !(useAuto || regions.some(region => region.kind === 'outlines'));
}

$('wear-review-auto').addEventListener('change', drawWearReview);
$('wear-review-preview').addEventListener('change', drawWearReview);
reviewCanvas.addEventListener('click', event => {
  const box = reviewCanvas.getBoundingClientRect();
  const x = Math.min(reviewCanvas.width - 1, Math.floor((event.clientX - box.left) * reviewCanvas.width / box.width));
  const y = Math.min(reviewCanvas.height - 1, Math.floor((event.clientY - box.top) * reviewCanvas.height / box.height));
  if (wearReview.points.length >= 200 || x < 0 || y < 0) return;
  wearReview.points.push([x, y]);
  drawWearReview();
});
function applyReviewRegion(kind) {
  if (wearReview.points.length < 3) return;
  if (wearReview.regions.filter(region => region.kind === kind).length >= 8) {
    $('wear-review-status').textContent = '영역은 종류별로 8개까지 추가할 수 있습니다.';
    return;
  }
  wearReview.regions.push({kind, points: wearReview.points});
  wearReview.points = [];
  $('wear-review-status').textContent = '';
  drawWearReview();
}
$('wear-review-add').addEventListener('click', () => applyReviewRegion('outlines'));
$('wear-review-remove').addEventListener('click', () => applyReviewRegion('openings'));
$('wear-review-hide').addEventListener('click', () => applyReviewRegion('hide_base'));
$('wear-review-clear').addEventListener('click', () => {
  wearReview.points = [];
  drawWearReview();
});
function zoomWearReview(step) {
  const oldZoom = wearReview.zoom;
  const zoom = Math.min(3, Math.max(1, oldZoom + step));
  const centerX = reviewViewport.clientWidth / 2;
  const centerY = reviewViewport.clientHeight / 2;
  const left = (reviewViewport.scrollLeft + centerX) * zoom / oldZoom - centerX;
  const top = (reviewViewport.scrollTop + centerY) * zoom / oldZoom - centerY;
  wearReview.zoom = zoom;
  reviewCanvas.style.setProperty('--review-zoom', zoom);
  reviewViewport.scrollTo(left, top);
  drawWearReview();
}
$('wear-review-zoom-in').addEventListener('click', () => zoomWearReview(.5));
$('wear-review-zoom-out').addEventListener('click', () => zoomWearReview(-.5));
$('wear-review-undo').addEventListener('click', () => {
  if (wearReview.points.length) wearReview.points.pop();
  else wearReview.regions.pop();
  $('wear-review-status').textContent = '';
  drawWearReview();
});
$('wear-review-save').addEventListener('click', async () => {
  const body = {outlines: [], openings: [], hide_base: [], use_auto_mask: $('wear-review-auto').checked};
  for (const region of wearReview.regions) body[region.kind].push(region.points);
  const save = $('wear-review-save');
  save.disabled = true;
  try {
    const row = await api('wardrobe/review/' + encodeURIComponent(wearReview.id), {method:'POST', body:JSON.stringify(body)});
    await refreshWardrobe();
    await selectGarment(row);
    $('wear-review-dialog').close();
    toast('검수한 착용 레이어를 저장했습니다.');
  } catch (error) {
    $('wear-review-status').textContent = error.message;
    drawWearReview();
  }
});
const garmentSeasons = $('garment-seasons');
const garmentSeasonFeedback = $('garment-season-feedback');
function showGarmentSeasonFeedback(message = '') {
  garmentSeasonFeedback.textContent = message;
  garmentSeasonFeedback.hidden = !message;
}
function setGarmentSeasonOptions({individual, all}) {
  garmentSeasons.replaceChildren(...[...individual, all].map(season => {
    const label = node('label', undefined, 'occasion-option');
    const option = node('input');
    option.type = 'checkbox';
    option.value = season;
    option.addEventListener('change', () => {
      if (option.checked) {
        for (const other of garmentSeasons.querySelectorAll('input')) {
          if (other !== option && (season === all || other.value === all)) other.checked = false;
        }
      }
      showGarmentSeasonFeedback();
    });
    label.append(option, node('span', season));
    return label;
  }));
}
function editGarment(row) {
  state.editGarment = row.id;
  for (const key of ['name', 'category', 'color', 'memo']) $('garment-' + key).value = row[key];
  const selections = row.season_choices ?? [];
  for (const option of garmentSeasons.querySelectorAll('input')) option.checked = selections.includes(option.value);
  showGarmentSeasonFeedback(selections.length ? '' : '기존 계절 정보를 확인할 수 없어요. 착용 계절을 다시 골라 주세요.');
  $('garment-preview').src = '/api/wardrobe/' + encodeURIComponent(row.id) + '/image';
  $('garment-dialog').showModal();
}
$('garment-form').addEventListener('submit', async event => {
  event.preventDefault();
  const seasons = Array.from(garmentSeasons.querySelectorAll('input:checked'), option => option.value);
  if (!seasons.length) {
    showGarmentSeasonFeedback('착용 계절을 하나 이상 골라 주세요.');
    garmentSeasons.querySelector('input')?.focus();
    return;
  }
  const submit = event.submitter;
  submit.disabled = true;
  try {
    const body = {season: seasons.join(' · ')};
    for (const key of ['name', 'category', 'color', 'memo']) body[key] = $('garment-' + key).value;
    await api('wardrobe/' + state.editGarment, {method: 'PUT', body: JSON.stringify(body)});
    await refreshWardrobe();
    $('garment-dialog').close();
    toast('의류 정보를 저장했습니다.');
  } catch (error) {
    toast(error.message);
  } finally {
    submit.disabled = false;
  }
});
$('garment-delete').addEventListener('click', async () => {if (!await confirmAction('이 의류를 옷장에서 삭제할까요?')) return; const submit = $('garment-delete'); submit.disabled = true; try {await api('wardrobe/' + state.editGarment, {method:'DELETE'}); state.selected = state.selected.filter(id => id !== state.editGarment); await refreshWardrobe(); $('garment-dialog').close(); toast('옷장에서 삭제했습니다. 추천 후보에서도 제외됩니다.');} catch(error) {toast(error.message);} finally {submit.disabled = false;}});

$('profile-open').addEventListener('click', () => {if (!state.profile) return toast('서버 연결을 먼저 확인해 주세요.'); ['name','heat','cold','theme','closet_theme'].forEach(key => {$('profile-' + key).value = state.profile[key];}); document.querySelectorAll('#style-options input').forEach(input => {input.checked = state.profile.styles.includes(input.value);}); $('profile-dialog').showModal();});
$('profile-form').addEventListener('submit', async event => {event.preventDefault(); const submit = event.submitter; submit.disabled = true; try {const body = {}; ['name','heat','cold','theme','closet_theme'].forEach(key => {body[key] = $('profile-' + key).value;}); body.styles = [...document.querySelectorAll('#style-options input:checked')].map(input => input.value); state.profile = await api('profile', {method:'PUT',body:JSON.stringify(body)}); applyProfile(); $('profile-dialog').close(); toast('내 취향을 저장했습니다. 다음 코디 추천부터 반영됩니다.');} catch(error) {toast(error.message);} finally {submit.disabled = false;}});
function isRefiningOutfit() {
  return state.messages.some(message => message.role === 'assistant' && message.outfit_ids?.length);
}
function renderMessages() {
  const area = $('chat-messages'); area.replaceChildren();
  const refining = isRefiningOutfit();
  const lastUser = state.messages.findLast(message => message.role === 'user');
  if (lastUser && !refining) area.append(node('p',lastUser.content,'message user'));
  area.hidden = refining;
  const panel = $('conditions-panel');
  panel.classList.toggle('is-refinement',refining);
  const title = panel.querySelector('summary');
  title.firstChild.textContent = refining ? '코디 수정하기' : '오늘의 스타일 노트';
  title.querySelector('span').textContent = refining ? '지금 코디에서 바꾸고 싶은 부분을 알려주세요.' : '어떤 하루를 보내실 건가요?';
  panel.open = !refining;
  document.querySelector('label[for="message"]').textContent = refining ? '어떤 부분을 바꾸고 싶으세요?' : '오늘은 어떤 스타일이 좋으세요?';
  $('message').placeholder = refining ? '예: 구두 대신 운동화로 바꿔 주세요.' : '편안하지만 조금 특별하게 입고 싶어요.';
  $('chat-submit').textContent = refining ? '수정 요청하기' : '나에게 맞는 코디 찾기';
  renderOutfit();
  area.scrollTop = area.scrollHeight;
}
$('conditions-panel').addEventListener('toggle', event => {
  const panel = event.currentTarget;
  if (!panel.open || !panel.classList.contains('is-refinement')) return;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  $('chat-submit').scrollIntoView({block:'nearest', inline:'nearest', behavior:reduceMotion ? 'instant' : 'smooth'});
});
function resetStudioDraft() {
  clearOutfitPreview(); openedOutfit = null; savedOutfit = null; state.conversation = null; state.messages = []; state.selected = [];
  $('chat-form').reset();
  $('outfit-date').value = $('outfit-date').min;
  $('chat-feedback').textContent = '';
  renderWardrobe(); renderMessages();
}
$('new-chat').addEventListener('click', () => {
  resetStudioDraft();
  $('message').focus();
});
function confirmSeason(error) {
  const labels = {title:'착용 계절 확인', cancel:'다시 고르기', confirm:'입기'};
  const {season, items} = error.detail;
  if (!season || !Array.isArray(items) || !items.length) return confirmAction(error.message, labels);
  const content = node('div',undefined,'season-confirmation');
  const overview = node('p',undefined,'season-confirmation-date');
  overview.append(node('span','착용 예정 계절'),node('strong',season));
  const list = node('ul',undefined,'season-confirmation-items');
  for (const item of items) {
    const row = node('li');
    row.append(node('span',item.name),node('span',item.season,'season-confirmation-tag'));
    list.append(row);
  }
  content.append(overview,node('h3','등록 계절이 다른 의류'),list,
                 node('p','그래도 입으시겠어요?','season-confirmation-question'),
                 node('p','입기를 선택하면 이 옷을 유지한 채 코디를 다시 추천해요.','small-note'));
  return confirmAction(content, labels);
}

async function requestOutfitChange(message, confirmedItems = []) {
  const submit = $('chat-submit');
  if (!message || submit.disabled) return;
  const activeMessages = state.messages;
  const refining = isRefiningOutfit();
  submit.disabled = true;
  submit.textContent = refining ? '코디를 다시 살펴보고 있어요…' : '나의 옷장을 살펴보고 있어요…';
  $('chat-feedback').textContent = refining ? '' : '옷장과 취향, 코디 통계를 함께 확인하고 있습니다.';
  const body = {message, date:$('outfit-date').value, time:$('outfit-time').value || null, occasion:document.querySelector('input[name="occasion"]:checked').value, conversation_id:state.conversation, season_override_ids:confirmedItems};
  if (!body.conversation_id && savedOutfit) body.saved_outfit_id = savedOutfit.id;
  try {
    let result;
    try {
      result = await api('chat', {method:'POST',body:JSON.stringify(body)});
    } catch (error) {
      if (error.detail?.code !== 'season_confirmation_required') throw error;
      if (state.messages !== activeMessages) return;
      const confirmed = await confirmSeason(error);
      if (state.messages !== activeMessages) return;
      if (!confirmed) {
        $('chat-feedback').textContent = '';
        return;
      }
      body.season_override_ids = [...new Set([...confirmedItems, ...error.detail.item_ids])];
      result = await api('chat', {method:'POST',body:JSON.stringify(body)});
    }
    if (state.messages !== activeMessages) return;
    state.conversation = result.conversation_id;
    state.messages.push({role:'user',content:message},{
      role:'assistant', content:result.answer, outfit_ids:result.outfit_ids,
      outfit_date:result.outfit_date, outfit_season:result.outfit_season,
    });
    if (refining && !result.outfit_ids.length) {
      $('chat-feedback').textContent = result.answer;
      return;
    }
    clearOutfitPreview();
    openedOutfit = null;
    savedOutfit = null;
    state.selected = result.outfit_ids;
    if (state.selected.length) {
      outfitPreview = {conversation:state.conversation, index:state.messages.length - 1, status:'checking'};
    }
    const preview = outfitPreview;
    await refreshWardrobe();
    renderMessages();
    if (preview && preview === outfitPreview) void loadOutfitPreview(preview, 'GET');
    $('message').value = '';
    $('chat-feedback').textContent = isRefiningOutfit() ? '' : result.notice || '';
  }
  catch(error) {if (state.messages === activeMessages) $('chat-feedback').textContent = error.message;}
  finally {submit.disabled = false; submit.textContent = isRefiningOutfit() ? '수정 요청하기' : '나에게 맞는 코디 찾기';}
}
$('chat-form').addEventListener('submit', event => {
  event.preventDefault();
  void requestOutfitChange($('message').value.trim());
});

async function refreshSummary() {
  const summary = await api('data/summary'); state.summary = summary;
  $('context-summary').textContent = '참고 코디 ' + summary.count.toLocaleString() + '건 · 평균 ' + (summary.metrics.average ?? '—') + '개 / 코디\n게시일 ' + summary.period;
  const stats = $('stats'); stats.replaceChildren();
  [['코디 기록', summary.count.toLocaleString(), '건의 데이터'], ['평균 아이템 수', summary.metrics.average ?? '—', '개 / 코디'], ['아이템 수 범위', summary.count ? summary.metrics.min + '–' + summary.metrics.max : '—', '개 / 코디'], ['구성 아이템 추세', summary.trend, '관측 기간 내 비교']].forEach(([title,value,note]) => {const card = node('article',undefined,'stat'); card.append(node('span',title),node('strong',value),node('small',note)); stats.append(card);});
  $('trend-note').textContent = summary.period + ' · ' + summary.trend_definition;
  renderChart(summary.daily);
  const categories = $('category-stats'); categories.replaceChildren();
  const values = Object.entries(summary.category_breakdown).sort((a,b) => b[1]-a[1]);
  const seasonal = $('seasonal-category-rows');
  seasonal.replaceChildren();
  const seasons = ['봄','여름','가을','겨울'];
  for (const [name] of values) {
    const row = node('tr');
    const label = node('th',name);
    label.scope = 'row';
    row.append(label);
    for (const season of seasons) {
      row.append(node('td',(summary.seasonal_category_breakdown[season][name] ?? 0).toLocaleString()));
    }
    seasonal.append(row);
  }
  $('seasonal-category-table').hidden = !values.length;
  $('seasonal-category-empty').hidden = Boolean(values.length);
  renderSeasonalCategoryChart(values, seasons, summary.seasonal_category_breakdown);
  const max = values[0]?.[1] || 1;
  values.forEach(([name,count]) => {const row = node('div',undefined,'bar-row'); const track = node('div',undefined,'bar-track'); const fill = node('div',undefined,'bar-fill'); fill.style.width = count/max*100 + '%'; track.append(fill); row.append(node('span',name),track,node('span',count.toLocaleString())); categories.append(row);});
}
function renderSeasonalCategoryChart(categories, seasons, breakdown) {
  const chart = $('seasonal-category-chart');
  const filters = $('seasonal-category-legend');
  const content = $('seasonal-category-groups');
  const colors = ['#906846','#70816a','#547d84','#aa755e','#796987','#b29859','#858177'];
  chart.hidden = !categories.length;
  filters.replaceChildren();
  content.replaceChildren();
  if (!categories.length) return;

  function showComposition(season) {
    const counts = categories.map(([name,count],index) => ({
      name, count: season ? breakdown[season][name] ?? 0 : count,
      color: colors[index % colors.length],
    })).sort((a,b) => b.count-a.count);
    const total = counts.reduce((sum,item) => sum + item.count, 0);
    const donut = node('div',undefined,'seasonal-donut');
    donut.setAttribute('aria-hidden','true');
    const center = node('div',undefined,'seasonal-donut-center');
    center.append(node('span',season || '전체'),node('strong',total.toLocaleString()),node('span','아이템'));
    donut.append(center);

    const legend = node('ul',undefined,'seasonal-donut-details');
    let offset = 0;
    const segments = [];
    for (const {name,count,color} of counts) {
      const share = total ? count / total : 0;
      if (count) {
        const end = offset + share * 100;
        segments.push(color + ' ' + offset + '% ' + end + '%');
        offset = end;
      }
      const row = node('li');
      const dot = node('span',undefined,'seasonal-donut-dot');
      dot.style.backgroundColor = color;
      dot.setAttribute('aria-hidden','true');
      row.append(dot, node('span',name), node('strong',count.toLocaleString()), node('span',(share * 100).toFixed(1) + '%'));
      legend.append(row);
    }
    if (segments.length) donut.style.backgroundImage = 'conic-gradient(' + segments.join(', ') + ')';
    content.replaceChildren(donut,legend);
  }

  ['', ...seasons].forEach((season,index) => {
    const filter = button(season || '전체', () => {
      for (const option of filters.children) option.setAttribute('aria-pressed', String(option === filter));
      showComposition(season);
    }, 'seasonal-category-filter');
    filter.setAttribute('aria-pressed', String(index === 0));
    if (index > 0) filter.dataset.season = index - 1;
    filters.append(filter);
  });
  showComposition('');
}
function svgNode(tag, attrs, text) {const item = document.createElementNS('http://www.w3.org/2000/svg',tag); Object.entries(attrs).forEach(([key,value]) => item.setAttribute(key,value)); if (text !== undefined) item.textContent = text; return item;}
function renderChart(daily) {
  const area = $('chart'); area.replaceChildren(); if (!daily.length) {area.append(node('p','아직 표시할 데이터가 없습니다.','empty-state')); return;}
  const svg = svgNode('svg',{viewBox:'0 0 1000 280',role:'img','aria-label':'게시일별 평균 구성 아이템 수 그래프'});
  const max = Math.max(1,...daily.map(row => row.average)) * 1.15; const x = i => 55 + i * 915 / Math.max(1,daily.length-1); const y = value => 225 - value/max * 195;
  for (let i=0;i<=4;i++) {const value = max*i/4; const yy = y(value); svg.append(svgNode('line',{x1:55,x2:970,y1:yy,y2:yy,stroke:'var(--line)'}),svgNode('text',{x:40,y:yy+4,'text-anchor':'end',fill:'var(--muted)','font-size':12},value.toFixed(1)));}
  const path = daily.map((row,i) => (i ? 'L' : 'M') + x(i) + ',' + y(row.average)).join(' ');
  svg.append(svgNode('path',{d:path + ' L' + x(daily.length-1) + ',225 L55,225 Z',fill:'var(--accent)',opacity:'.08'}),svgNode('path',{d:path,stroke:'var(--accent)','stroke-width':2.5,fill:'none','stroke-linejoin':'round'}));
  const stride = Math.max(1,Math.ceil(daily.length/9));
  daily.forEach((row,i) => {const dot = svgNode('circle',{cx:x(i),cy:y(row.average),r:4,fill:'var(--surface)',stroke:'var(--accent)','stroke-width':2}); dot.append(svgNode('title',{},row.date + ' · 평균 ' + row.average + '개 · ' + row.count + '건')); svg.append(dot); if (i%stride===0 || i===daily.length-1) svg.append(svgNode('text',{x:x(i),y:255,'text-anchor':'middle',fill:'var(--muted)','font-size':12},row.date.slice(5)));}); area.append(svg);
}
async function loadData() {
  const result = await api('data?offset=' + state.offset + '&limit=' + DATA_PAGE_SIZE); state.total = result.total; $('data-count').textContent = result.total.toLocaleString() + '건';
  const area = $('data-rows'); area.replaceChildren();
  result.items.forEach(row => {const tr = node('tr'); const memo = node('td',row.memo); if (row.source_modified) memo.append(node('small',' · 직접 입력/수정','small-note')); const actions = node('td'); actions.append(button('수정',() => {state.editData = row.id; $('data-date').value = row.date; $('data-value').value = row.value; $('data-memo').value = row.memo; $('data-form-title').textContent = '기록 수정'; $('data-form').scrollIntoView({behavior:'smooth',block:'center'});}),button('삭제',async () => {if (!await confirmAction('이 기록을 내 데이터에서 삭제할까요?')) return; await api('data/' + encodeURIComponent(row.id),{method:'DELETE'}); if (state.editData === row.id) resetData(); if (state.offset >= state.total-1) state.offset = Math.max(0,state.offset-DATA_PAGE_SIZE); await Promise.all([loadData(),refreshSummary()]); toast('기록과 통계를 갱신했습니다.');})); tr.append(node('td',row.date),node('td',String(row.value)),memo,actions); area.append(tr);});
  if (!result.items.length) {const tr = node('tr'); const td = node('td','데이터가 없습니다. 새 기록을 추가해 주세요.'); td.colSpan = 4; tr.append(td); area.append(tr);}
  $('data-page').textContent = result.total ? Math.floor(state.offset/DATA_PAGE_SIZE)+1 + ' / ' + Math.ceil(result.total/DATA_PAGE_SIZE) : '0 / 0'; $('data-prev').disabled = state.offset === 0; $('data-next').disabled = state.offset+DATA_PAGE_SIZE >= result.total;
}
function resetData() {state.editData = null; $('data-form').reset(); $('data-form-title').textContent = '새 기록 추가';}
$('data-reset').addEventListener('click',resetData);
$('data-form').addEventListener('submit',async event => {event.preventDefault(); const submit = event.submitter; submit.disabled = true; try {const body = {date:$('data-date').value,value:Number($('data-value').value),memo:$('data-memo').value}; await api('data' + (state.editData ? '/' + encodeURIComponent(state.editData) : ''),{method:state.editData ? 'PUT':'POST',body:JSON.stringify(body)}); resetData(); state.offset = 0; await Promise.all([loadData(),refreshSummary()]); toast('기록을 저장하고 통계를 갱신했습니다.');} catch(error) {toast(error.message);} finally {submit.disabled = false;}});
$('data-prev').addEventListener('click',() => {state.offset = Math.max(0,state.offset-DATA_PAGE_SIZE); loadData().catch(error => toast(error.message));});
$('data-next').addEventListener('click',() => {state.offset += DATA_PAGE_SIZE; loadData().catch(error => toast(error.message));});

function historyTimeLeft(remaining) {
  if (remaining > HISTORY_COUNTDOWN_WINDOW_DAYS * DAY_MS) return '';
  if (remaining < MINUTE_MS) return '만료';
  if (remaining >= DAY_MS) return Math.ceil(remaining / DAY_MS) + 'd';
  if (remaining >= HOUR_MS) return Math.floor(remaining / HOUR_MS) + 'h';
  return Math.floor(remaining / MINUTE_MS) + 'm';
}

function updateHistoryCountdowns() {
  if ($('view-history').hidden) return;
  const now = Date.now();
  let delay = MINUTE_MS;
  const badges = $('history-list').querySelectorAll('[data-expires-at]');
  for (const badge of badges) {
    const remaining = Number(badge.dataset.expiresAt) - now;
    badge.textContent = historyTimeLeft(remaining);
    badge.hidden = !badge.textContent;
    badge.classList.toggle('is-expiring', remaining <= DAY_MS);
    if (remaining >= MINUTE_MS) delay = Math.min(delay, remaining - MINUTE_MS + 1);
  }
  if (badges.length) historyCountdownTimer = setTimeout(updateHistoryCountdowns, delay);
}

document.querySelectorAll('.info-toggle').forEach(toggle => {
  const detail = $(toggle.getAttribute('aria-controls'));
  toggle.addEventListener('click', () => {
    detail.hidden = !detail.hidden;
    toggle.setAttribute('aria-expanded', String(!detail.hidden));
  });
});

async function loadHistory() {
  const rows = await api('conversations'); const area = $('history-list'); area.replaceChildren();
  clearTimeout(historyCountdownTimer);
  if (!rows.length) {area.append(node('div','아직 저장된 대화가 없습니다. 코디 스튜디오에서 첫 이야기를 시작해 보세요.','panel empty-state')); return;}
  rows.forEach(row => {const card = node('article',undefined,'panel history-card'); const actions = node('div',undefined,'button-row'); actions.append(button('이야기 이어가기',async () => {
    const detail = await api('conversations/' + row.id);
    clearOutfitPreview();
    savedOutfit = null;
    state.conversation = detail.id;
    state.messages = detail.messages;
    const index = state.messages.findLastIndex(item => item.role === 'assistant' && item.outfit_ids?.length);
    const last = state.messages.findLast(item => item.role === 'assistant');
    $('chat-form').reset();
    const date = $('outfit-date');
    date.value = last?.outfit_date >= date.min ? last.outfit_date : date.min;
    $('outfit-time').value = last?.outfit_time || '';
    for (const occasion of document.querySelectorAll('input[name="occasion"]')) {
      occasion.checked = occasion.value === (last?.outfit_occasion || '일상');
    }
    state.selected = [...(state.messages[index]?.outfit_ids || [])];
    if (state.selected.length) {
      outfitPreview = {conversation:detail.id, index, status:'checking'};
    }
    rememberOpenedOutfit();
    const preview = outfitPreview;
    await refreshWardrobe(); renderMessages(); showView('studio');
    if (preview && preview === outfitPreview) void loadOutfitPreview(preview, 'GET');
    $('chat-feedback').textContent = '';
  },'outline-button'),button('삭제',async () => {if (!await confirmAction('저장된 대화를 삭제할까요?')) return; await api('conversations/' + row.id,{method:'DELETE'}); if (state.conversation === row.id) {clearOutfitPreview(); openedOutfit = null; state.conversation = null; state.messages = []; renderMessages();} await loadHistory();}));
    const updated = new Date(row.updated_at);
    const date = node('time',updated.toLocaleString('ko-KR'));
    date.dateTime = row.updated_at;
    const metadata = node('p',undefined,'history-card-meta');
    metadata.append(date);
    if (conversationRetentionDays && Number.isFinite(updated.getTime())) {
      const expiresAt = updated.getTime() + conversationRetentionDays * DAY_MS;
      const countdown = node('span',undefined,'history-countdown');
      countdown.hidden = true;
      countdown.dataset.expiresAt = String(expiresAt);
      countdown.title = '자동 삭제 예정 · ' + new Date(expiresAt).toLocaleString('ko-KR');
      metadata.append(countdown);
    }
    card.append(metadata,node('h2',row.title),actions);
    area.append(card);
  });
  updateHistoryCountdowns();
}
let pendingOutfit = null;
function openSaveOutfit(payload) {
  pendingOutfit = payload;
  $('save-outfit-title').value = '나의 코디';
  $('save-outfit-feedback').textContent = '';
  $('save-outfit-dialog').showModal();
}
$('save-outfit-form').addEventListener('submit',async event => {
  event.preventDefault(); const submit = event.submitter; submit.disabled = true;
  try {
    await api('outfits',{method:'POST',body:JSON.stringify({...pendingOutfit,title:$('save-outfit-title').value})});
    $('save-outfit-dialog').close(); toast('코디북에 저장했습니다.');
  } catch(error) {$('save-outfit-feedback').textContent = error.message;}
  finally {submit.disabled = false;}
});
const editOutfitDialog = $('edit-outfit-dialog');
const editOutfitForm = $('edit-outfit-form');
const editOutfitFeedback = $('edit-outfit-feedback');
function openEditOutfit(row) {
  if (editOutfitForm.querySelector('button[type=submit]').disabled) return;
  editOutfitForm.dataset.outfitId = row.id;
  for (const field of ['title', 'date', 'note']) editOutfitForm.elements.namedItem(field).value = row[field] ?? '';
  editOutfitFeedback.textContent = '';
  editOutfitDialog.showModal();
}
editOutfitForm.addEventListener('submit', async event => {
  event.preventDefault();
  const id = editOutfitForm.dataset.outfitId;
  const body = Object.fromEntries(new FormData(editOutfitForm));
  const submit = event.submitter;
  submit.disabled = true;
  editOutfitFeedback.textContent = '';
  try {
    const fields = await api('outfits/' + encodeURIComponent(id), {method: 'PATCH', body: JSON.stringify(body)});
    outfitRows = outfitRows.map(row => row.id === id ? {...row, ...fields} : row);
    editOutfitDialog.close();
    if (savedOutfit?.id === id) {
      const date = $('outfit-date');
      const previousDate = savedOutfit.date;
      if (date.value === (previousDate >= date.min ? previousDate : date.min)) {
        date.value = fields.date >= date.min ? fields.date : date.min;
      }
      savedOutfit = {...savedOutfit, ...fields};
      state.messages[0].content = fields.note || '저장한 코디입니다.';
      renderOutfit();
    }
    toast('코디 정보를 저장했습니다.');
  } catch (error) {
    editOutfitFeedback.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});
async function loadOutfits() {
  outfitRows = await api('outfits');
  renderOutfits();
}
function renderOutfits() {
  const pageCount = Math.max(1, Math.ceil(outfitRows.length / OUTFIT_PAGE_SIZE));
  outfitPage = Math.min(Math.max(0, outfitPage), pageCount - 1);
  $('outfit-pagination').hidden = pageCount === 1;
  $('outfit-prev').disabled = outfitPage === 0;
  $('outfit-next').disabled = outfitPage === pageCount - 1;
  $('outfit-page').textContent = `${outfitPage + 1} / ${pageCount}`;
  const area = $('outfit-list');
  area.replaceChildren();
  if (!outfitRows.length) {area.append(node('div','아직 저장한 코디가 없습니다. 옷장에서 고른 조합이나 마음에 드는 추천을 저장해 보세요.','panel empty-state')); return;}
  const offset = outfitPage * OUTFIT_PAGE_SIZE;
  const pageRows = outfitRows.slice(offset, offset + OUTFIT_PAGE_SIZE);
  pageRows.forEach(row => {
    const card = node('article',undefined,'panel history-card saved-outfit-card');
    const title = node('h2',row.title);
    title.title = row.title;
    const metadata = node('p',[row.date,row.outfit_season].filter(Boolean).join(' · '),'small-note');
    if (row.source === 'ai') {
      const icon = svgNode('svg', {class:'ui-icon saved-outfit-ai', role:'img', 'aria-label':'AI 추천 코디'});
      icon.append(svgNode('title', {}, 'AI 추천 코디'), svgNode('use', {href:'#icon-spark'}));
      metadata.append(icon);
    }
    card.append(metadata,title);
    const pieces = node('div',undefined,'outfit-pieces');
    row.items.forEach(item => {
      const piece = node('div',undefined,'outfit-piece');
      if (row.available_ids.includes(item.id)) {
        const image = node('img'); image.src = '/api/wardrobe/' + encodeURIComponent(item.id) + '/image'; image.alt = item.name; image.loading = 'lazy'; piece.append(image);
      }
      piece.append(node('span',item.name + (row.available_ids.includes(item.id) ? '' : ' (삭제됨)'))); pieces.append(piece);
    });
    const fullImage = node('img',undefined,'saved-outfit-photo');
    fullImage.alt = row.title + ' 전신 착용샷';
    fullImage.width = 384;
    fullImage.height = 1152;
    fullImage.hidden = true;
    fullImage.addEventListener('load', () => {
      fullImage.hidden = false;
      pieces.hidden = true;
    }, {once:true});
    fullImage.src = '/api/outfits/' + encodeURIComponent(row.id) + '/image';
    const media = node('div',undefined,'saved-outfit-media');
    media.append(fullImage,pieces);
    card.append(media);
    const details = node('div',undefined,'saved-outfit-details');
    if (row.note) {
      const note = node('p',row.note,'small-note saved-outfit-note');
      note.title = row.note;
      details.append(note);
    }
    if (row.missing_count) details.append(node('p','삭제된 의류 ' + row.missing_count + '개 제외','small-note saved-outfit-missing'));
    card.append(details);
    const actions = node('div',undefined,'button-row');
    const preview = button('이야기 이어가기',async () => {
      clearOutfitPreview();
      savedOutfit = row;
      state.conversation = null;
      state.messages = [{role:'assistant',content:row.note || '저장한 코디입니다.',outfit_ids:row.available_ids}];
      state.selected = [...row.available_ids];
      const savedPreview = {savedId:row.id, status:'checking'};
      outfitPreview = savedPreview;
      rememberOpenedOutfit();
      await refreshWardrobe();
      renderMessages();
      $('chat-feedback').textContent = '';
      $('chat-form').reset();
      const date = $('outfit-date');
      date.value = row.date >= date.min ? row.date : date.min;
      $('outfit-time').value = row.outfit_time || '';
      for (const occasion of document.querySelectorAll('input[name="occasion"]')) {
        occasion.checked = occasion.value === (row.outfit_occasion || '일상');
      }
      showView('studio'); toast('저장한 코디를 불러왔습니다.');
      if (savedPreview === outfitPreview) void loadOutfitPreview(savedPreview, 'GET');
    },'outline-button');
    preview.disabled = !row.available_ids.length && fullImage.hidden;
    fullImage.addEventListener('load', () => {preview.disabled = false;}, {once:true});
    actions.append(preview,button('삭제',async () => {
      if (!await confirmAction('이 코디를 코디북에서 삭제할까요? 옷장 속 의류는 유지됩니다.')) return;
      await api('outfits/' + row.id,{method:'DELETE'}); await loadOutfits();
    }));
    card.append(actions); area.append(card);
  });
  if (pageCount > 1) {
    for (let slot = pageRows.length; slot < OUTFIT_PAGE_SIZE; slot += 1) {
      const spacer = node('div',undefined,'saved-outfit-spacer');
      spacer.setAttribute('aria-hidden','true');
      area.append(spacer);
    }
  }
}
$('outfit-prev').addEventListener('click', () => {outfitPage -= 1; renderOutfits();});
$('outfit-next').addEventListener('click', () => {outfitPage += 1; renderOutfits();});
const loginDialog = $('login-dialog');
loginDialog.addEventListener('cancel', event => event.preventDefault());
$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const submit = $('login-submit');
  submit.disabled = true;
  $('login-feedback').textContent = '';
  try {
    await api('login', {method: 'POST', body: JSON.stringify({
      username: $('login-username').value.trim(), password: $('login-password').value
    })});
    $('login-form').reset();
    loginDialog.close();
    await initialize();
  } catch (error) {
    $('login-feedback').textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});
$('logout').addEventListener('click', async () => {
  try {
    await api('logout', {method: 'POST'});
    location.reload();
  } catch (error) {toast(error.message);}
});

async function initialize() {
  try {
    const status = await api('status');
    conversationRetentionDays = status.conversation_retention_days;
    const retentionNotice = $('history-retention-text');
    retentionNotice.textContent = `대화 기록은 AI와 마지막으로 대화를 나눈 시점부터 ${status.conversation_retention_days}일 뒤 자동으로 삭제됩니다. 코디북에 저장한 코디는 계속 볼 수 있어요.`;
    $('history-retention').hidden = !status.conversation_retention_days;
    $('logout').hidden = !status.authenticated;
    musicToggle.hidden = !status.authenticated || !status.background_music_available;
    if (status.login_required && !status.authenticated) {
      $('connection').textContent = '로그인이 필요합니다.';
      if (!loginDialog.open) loginDialog.showModal();
      return;
    }
    applyAvatar(status.avatar);
    setGarmentSeasonOptions(status.garment_seasons);
    state.conversionReady = status.garment_conversion_ready;
    state.uploadReady = Boolean(status.image_analysis_enabled && status.garment_review_ready);
    $('upload-submit').disabled = !state.uploadReady;
    $('connection').textContent = '나만의 아틀리에에 연결되었습니다';
    $('connection').classList.add('is-connected');
    if (!status.ai_configured) {$('connection').classList.remove('is-connected'); $('connection').textContent = 'AI 설정이 필요합니다';}
    if (!state.uploadReady) {
      $('connection').textContent += ' · 의류 이미지 생성 연동 준비 중';
      $('conversion-feedback').textContent = '착용 미리보기를 준비하고 있습니다.';
    }
    const outfitDate = $('outfit-date');
    outfitDate.min = status.date;
    outfitDate.value = status.date;
    $('today-label').textContent = status.date.replaceAll('-','.');
    state.profile = await api('profile'); applyProfile();
    await Promise.all([refreshWardrobe(),refreshSummary()]);
    const view = location.hash.slice(1); if (['studio','insights','data','history','outfits'].includes(view)) showView(view);
  } catch(error) {$('connection').textContent = error.message; renderWardrobe(); toast(error.message);}
}
initialize();
