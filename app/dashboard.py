import base64
import json
import logging
from typing import Any

from aiohttp import web

from aiogram import Bot

from .db import DB
from .template import ApprovalMessageSettings, render_template_html, sanitize_telegram_html, settings_from_json, settings_to_json
from .validation import allowed_template_vars, validate_template_vars


log = logging.getLogger("dashboard")


def _is_authorized(request: web.Request, password: str) -> bool:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    raw = auth[len("Basic ") :].strip()
    try:
        decoded = base64.b64decode(raw).decode("utf-8")
    except Exception:
        return False
    if ":" not in decoded:
        return False
    username, pwd = decoded.split(":", 1)
    return username == "admin" and pwd == password


def _unauthorized() -> web.Response:
    return web.Response(
        status=401,
        headers={"WWW-Authenticate": 'Basic realm="tgbot"'},
        text="Unauthorized",
    )


def _html_page(title: str, body: str) -> str:
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'/>"
        f"<title>{title}</title>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        "<style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;background:#fafafa;color:#111}header{background:#111;color:#fff;padding:12px 16px;display:flex;align-items:center;gap:12px;position:sticky;top:0}header a{color:#fff;text-decoration:none;opacity:.9}header a:hover{opacity:1}main{padding:16px;max-width:1200px;margin:0 auto}.card{background:#fff;border:1px solid #e6e6e6;border-radius:10px;padding:12px}.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}.toolbar input{padding:8px 10px;border:1px solid #ddd;border-radius:8px;min-width:220px;flex:1}.btn{border:1px solid #ddd;background:#fff;border-radius:8px;padding:8px 10px;cursor:pointer}.btn.primary{background:#111;color:#fff;border-color:#111}.btn.danger{background:#b00020;color:#fff;border-color:#b00020}.btn:disabled{opacity:.6;cursor:not-allowed}.table-wrap{overflow:auto;border:1px solid #e6e6e6;border-radius:10px;background:#fff}table{border-collapse:collapse;width:100%;min-width:860px}th,td{border-bottom:1px solid #eee;padding:10px;text-align:left;vertical-align:top}th{background:#f7f7f7;position:sticky;top:0}th.sort{cursor:pointer;user-select:none}code{background:#f6f8fa;padding:2px 4px;border-radius:4px}.pill{display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;font-size:12px;border:1px solid #ddd;background:#fff}.pill.ok{border-color:#0a7a2f;color:#0a7a2f}.pill.bad{border-color:#b00020;color:#b00020}.muted{color:#666;font-size:13px}.pager{display:flex;gap:8px;align-items:center;justify-content:space-between;margin-top:12px;flex-wrap:wrap}.toast-wrap{position:fixed;right:12px;bottom:12px;display:flex;flex-direction:column;gap:8px;z-index:1000}.toast{background:#111;color:#fff;border-radius:10px;padding:10px 12px;max-width:360px;box-shadow:0 8px 24px rgba(0,0,0,.2)}.toast.err{background:#b00020}.spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.35);border-top-color:#fff;border-radius:50%;animation:spin 1s linear infinite;vertical-align:middle}@keyframes spin{to{transform:rotate(360deg)}}@media (max-width:720px){main{padding:12px}.toolbar input{min-width:140px}table{min-width:720px}}</style>"
        "</head><body>"
        "<header>"
        "<strong>tgbot admin</strong>"
        "<nav style='display:flex;gap:12px'>"
        "<a href='/admin'>Пользователи</a>"
        "<a href='/admin/requests'>Запросы</a>"
        "<a href='/admin/settings'>Настройки</a>"
        "</nav>"
        "</header>"
        "<main>"
        f"{body}"
        "</main>"
        "<div class='toast-wrap' id='toastWrap'></div>"
        "</body></html>"
    )


def create_dashboard_app(db: DB, password: str, bot: Bot, admin_chat_id: int, bot_username: str, network_id: str) -> web.Application:
    app = web.Application()

    async def _json(request: web.Request, payload: dict[str, Any], status: int = 200) -> web.Response:
        return web.Response(text=json.dumps(payload, ensure_ascii=False), status=status, content_type="application/json")

    def _require_auth(request: web.Request) -> web.Response | None:
        if not _is_authorized(request, password):
            return _unauthorized()
        return None

    async def _notify_user(tg_id: int, text: str) -> None:
        try:
            await bot.send_message(chat_id=tg_id, text=text)
        except Exception:
            log.exception("dashboard_notify_failed tg_id=%s", tg_id)

    async def users_page(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        body = (
            "<div class='card'>"
            "<h1 style='margin:0 0 12px 0'>Пользователи</h1>"
            "<div class='toolbar'>"
            "<input id='q' placeholder='Поиск: tg_id, username, node_id…'/>"
            "<button class='btn' id='exportBtn'>Экспорт CSV</button>"
            "<button class='btn danger' id='bulkDeactivateBtn' disabled>Массовая деактивация</button>"
            "<span class='muted' id='statusLine'></span>"
            "</div>"
            "<div class='table-wrap'><table><thead><tr>"
            "<th style='width:40px'><input type='checkbox' id='selAll'/></th>"
            "<th class='sort' data-sort='tg_id'>ID</th>"
            "<th class='sort' data-sort='username'>username</th>"
            "<th>Имя</th>"
            "<th class='sort' data-sort='node_id'>node_id</th>"
            "<th class='sort' data-sort='is_active'>Статус</th>"
            "<th class='sort' data-sort='created_at'>Регистрация</th>"
            "<th class='sort' data-sort='updated_at'>Обновлено</th>"
            "<th style='width:220px'>Действия</th>"
            "</tr></thead><tbody id='tbody'></tbody></table></div>"
            "<div class='pager'>"
            "<div>"
            "<button class='btn' id='prevBtn'>Назад</button>"
            "<button class='btn' id='nextBtn'>Вперёд</button>"
            "</div>"
            "<div class='muted' id='pageLine'></div>"
            "</div>"
            "</div>"
            "<script>"
            "const state={page:1,pageSize:25,sort:'updated_at',order:'desc',q:'',items:[],total:0,selected:new Set()};"
            "const el={q:document.getElementById('q'),tbody:document.getElementById('tbody'),statusLine:document.getElementById('statusLine'),pageLine:document.getElementById('pageLine'),prevBtn:document.getElementById('prevBtn'),nextBtn:document.getElementById('nextBtn'),selAll:document.getElementById('selAll'),bulkDeactivateBtn:document.getElementById('bulkDeactivateBtn'),exportBtn:document.getElementById('exportBtn')};"
            "function toast(msg,isErr){const w=document.getElementById('toastWrap');const d=document.createElement('div');d.className='toast'+(isErr?' err':'');d.textContent=msg;w.appendChild(d);setTimeout(()=>{d.remove();},4000);}"
            "function setBusy(b,msg){el.statusLine.innerHTML=b?`<span class='pill'><span class='spinner' style='margin-right:6px'></span>${msg}</span>`:'';}"
            "function fullName(u){return [u.first_name,u.last_name].filter(Boolean).join(' ');}"
            "function statusPill(u){return u.is_active?`<span class='pill ok'>active</span>`:`<span class='pill bad'>inactive</span>`;}"
            "function esc(s){return (s??'').toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;').replace(/'/g,'&#39;');}"
            "function render(){el.tbody.innerHTML=state.items.map(u=>{const checked=state.selected.has(u.tg_id)?'checked':'';const node=u.node_id?('<code>'+esc(u.node_id)+'</code>'):'';const uname=u.username?('@'+esc(u.username)):'';return `<tr><td><input type='checkbox' data-id='${u.tg_id}' class='rowSel' ${checked}/></td><td><code>${u.tg_id}</code></td><td>${uname}</td><td>${esc(fullName(u))}</td><td>${node}</td><td>${statusPill(u)}</td><td>${esc(u.created_at)}</td><td>${esc(u.updated_at)}</td><td><a class='btn' href='/admin/users/${u.tg_id}'>Профиль</a> <button class='btn danger' data-act='deactivate' data-id='${u.tg_id}' ${u.is_active?'':'disabled'}>Деактивировать</button></td></tr>`;}).join('');"
            "el.pageLine.textContent=`Страница ${state.page} · Всего: ${state.total}`;"
            "el.prevBtn.disabled=state.page<=1;"
            "el.nextBtn.disabled=(state.page*state.pageSize)>=state.total;"
            "el.bulkDeactivateBtn.disabled=state.selected.size===0;"
            "const pageIds=new Set(state.items.map(i=>i.tg_id));let all=true;let any=false;for(const id of pageIds){if(state.selected.has(id)) any=true; else all=false;}el.selAll.checked=all && pageIds.size>0;el.selAll.indeterminate=!all && any;"
            "}"
            "async function api(path,opt){const r=await fetch(path,Object.assign({headers:{'Content-Type':'application/json'}},opt||{}));let j=null;const ct=r.headers.get('content-type')||'';if(ct.includes('application/json')) j=await r.json(); if(!r.ok){throw new Error((j&&j.error)||('HTTP '+r.status));} return j;}"
            "async function load(){setBusy(true,'Загрузка');try{const qp=new URLSearchParams({page:String(state.page),page_size:String(state.pageSize),sort:state.sort,order:state.order,q:state.q});const data=await api('/api/admin/users?'+qp.toString());state.items=data.items;state.total=data.total;render();}catch(e){toast(e.message,true);}finally{setBusy(false,'');}}"
            "function debounce(fn,ms){let t=null;return (...a)=>{clearTimeout(t);t=setTimeout(()=>fn(...a),ms);};}"
            "el.q.addEventListener('input',debounce(()=>{state.q=el.q.value.trim();state.page=1;load();},300));"
            "document.querySelectorAll('th.sort').forEach(th=>{th.addEventListener('click',()=>{const s=th.dataset.sort; if(state.sort===s){state.order=state.order==='asc'?'desc':'asc';} else {state.sort=s;state.order='asc';} state.page=1;load();});});"
            "el.prevBtn.addEventListener('click',()=>{state.page=Math.max(1,state.page-1);load();});"
            "el.nextBtn.addEventListener('click',()=>{state.page=state.page+1;load();});"
            "el.tbody.addEventListener('change',(e)=>{const t=e.target; if(t.classList.contains('rowSel')){const id=parseInt(t.dataset.id,10); if(t.checked) state.selected.add(id); else state.selected.delete(id); render();}});"
            "el.selAll.addEventListener('change',()=>{const ids=state.items.map(i=>i.tg_id); if(el.selAll.checked){ids.forEach(id=>state.selected.add(id));} else {ids.forEach(id=>state.selected.delete(id));} render();});"
            "el.tbody.addEventListener('click',async(e)=>{const b=e.target; if(!(b instanceof HTMLElement)) return; if(b.dataset.act==='deactivate'){const id=parseInt(b.dataset.id,10); if(!confirm('Деактивировать пользователя '+id+'?')) return; b.setAttribute('disabled','disabled'); try{await api('/api/admin/users/'+id+'/deactivate',{method:'POST',body:JSON.stringify({})}); toast('Пользователь деактивирован'); state.selected.delete(id); await load();}catch(err){toast(err.message,true); b.removeAttribute('disabled');}}});"
            "el.bulkDeactivateBtn.addEventListener('click',async()=>{if(state.selected.size===0) return; if(!confirm('Деактивировать выбранных пользователей ('+state.selected.size+')?')) return; el.bulkDeactivateBtn.setAttribute('disabled','disabled'); setBusy(true,'Выполнение'); try{const ids=[...state.selected]; const res=await api('/api/admin/users/bulk/deactivate',{method:'POST',body:JSON.stringify({tg_ids:ids})}); toast('Деактивировано: '+res.updated); state.selected.clear(); await load();}catch(e){toast(e.message,true);}finally{setBusy(false,'');}});"
            "el.exportBtn.addEventListener('click',()=>{const qp=new URLSearchParams({q:state.q,sort:state.sort,order:state.order}); window.location='/api/admin/users/export?'+qp.toString();});"
            "load();"
            "</script>"
        )
        return web.Response(text=_html_page("Пользователи", body), content_type="text/html")

    async def requests_page(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        body = (
            "<div class='card'>"
            "<h1 style='margin:0 0 12px 0'>Запросы</h1>"
            "<div class='toolbar'>"
            "<input id='q' placeholder='Поиск: request_id, tg_id, node_id…'/>"
            "<select id='statusSel' class='btn'><option value=''>Все</option><option value='pending'>pending</option><option value='approved'>approved</option><option value='denied'>denied</option></select>"
            "<span class='muted' id='statusLine'></span>"
            "</div>"
            "<div class='table-wrap'><table><thead><tr>"
            "<th class='sort' data-sort='id'>ID</th>"
            "<th class='sort' data-sort='tg_id'>tg_id</th>"
            "<th>node_id</th>"
            "<th class='sort' data-sort='status'>status</th>"
            "<th class='sort' data-sort='created_at'>created_at</th>"
            "<th>decided_at</th>"
            "<th>decided_by</th>"
            "<th style='width:220px'>Действия</th>"
            "</tr></thead><tbody id='tbody'></tbody></table></div>"
            "<div class='pager'>"
            "<div>"
            "<button class='btn' id='prevBtn'>Назад</button>"
            "<button class='btn' id='nextBtn'>Вперёд</button>"
            "</div>"
            "<div class='muted' id='pageLine'></div>"
            "</div>"
            "</div>"
            "<script>"
            "const state={page:1,pageSize:25,sort:'id',order:'desc',q:'',status:'',items:[],total:0};"
            "const el={q:document.getElementById('q'),tbody:document.getElementById('tbody'),statusLine:document.getElementById('statusLine'),pageLine:document.getElementById('pageLine'),prevBtn:document.getElementById('prevBtn'),nextBtn:document.getElementById('nextBtn'),statusSel:document.getElementById('statusSel')};"
            "function toast(msg,isErr){const w=document.getElementById('toastWrap');const d=document.createElement('div');d.className='toast'+(isErr?' err':'');d.textContent=msg;w.appendChild(d);setTimeout(()=>{d.remove();},4000);}"
            "function setBusy(b,msg){el.statusLine.innerHTML=b?`<span class='pill'><span class='spinner' style='margin-right:6px'></span>${msg}</span>`:'';}"
            "function esc(s){return (s??'').toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;').replace(/'/g,'&#39;');}"
            "function render(){el.tbody.innerHTML=state.items.map(r=>{const st=esc(r.status);const pill=st==='approved'?`<span class='pill ok'>approved</span>`:(st==='denied'?`<span class='pill bad'>denied</span>`:`<span class='pill'>pending</span>`);const btns=r.status==='pending'?(`<button class='btn primary' data-act='approve' data-id='${r.id}'>Approve</button> <button class='btn danger' data-act='cancel' data-id='${r.id}'>Cancel</button>`):'';return `<tr><td><code>${r.id}</code></td><td><code>${r.tg_id}</code></td><td><code>${esc(r.node_id)}</code></td><td>${pill}</td><td>${esc(r.created_at)}</td><td>${esc(r.decided_at||'')}</td><td>${esc(r.decided_by||'')}</td><td>${btns}</td></tr>`;}).join('');el.pageLine.textContent=`Страница ${state.page} · Всего: ${state.total}`;el.prevBtn.disabled=state.page<=1;el.nextBtn.disabled=(state.page*state.pageSize)>=state.total;}"
            "async function api(path,opt){const r=await fetch(path,Object.assign({headers:{'Content-Type':'application/json'}},opt||{}));let j=null;const ct=r.headers.get('content-type')||'';if(ct.includes('application/json')) j=await r.json(); if(!r.ok){throw new Error((j&&j.error)||('HTTP '+r.status));} return j;}"
            "async function load(){setBusy(true,'Загрузка');try{const qp=new URLSearchParams({page:String(state.page),page_size:String(state.pageSize),sort:state.sort,order:state.order,q:state.q,status:state.status});const data=await api('/api/admin/requests?'+qp.toString());state.items=data.items;state.total=data.total;render();}catch(e){toast(e.message,true);}finally{setBusy(false,'');}}"
            "function debounce(fn,ms){let t=null;return (...a)=>{clearTimeout(t);t=setTimeout(()=>fn(...a),ms);};}"
            "el.q.addEventListener('input',debounce(()=>{state.q=el.q.value.trim();state.page=1;load();},300));"
            "el.statusSel.addEventListener('change',()=>{state.status=el.statusSel.value;state.page=1;load();});"
            "document.querySelectorAll('th.sort').forEach(th=>{th.addEventListener('click',()=>{const s=th.dataset.sort; if(state.sort===s){state.order=state.order==='asc'?'desc':'asc';} else {state.sort=s;state.order='asc';} state.page=1;load();});});"
            "el.prevBtn.addEventListener('click',()=>{state.page=Math.max(1,state.page-1);load();});"
            "el.nextBtn.addEventListener('click',()=>{state.page=state.page+1;load();});"
            "el.tbody.addEventListener('click',async(e)=>{const b=e.target; if(!(b instanceof HTMLElement)) return; const act=b.dataset.act; const id=parseInt(b.dataset.id,10); if(!act||!id) return; b.setAttribute('disabled','disabled'); setBusy(true,'Выполнение'); try{await api('/api/admin/requests/'+id+'/'+(act==='approve'?'approve':'cancel'),{method:'POST',body:JSON.stringify({})}); toast('Готово'); await load();}catch(err){toast(err.message,true); b.removeAttribute('disabled');}finally{setBusy(false,'');}});"
            "load();"
            "</script>"
        )
        return web.Response(text=_html_page("Запросы", body), content_type="text/html")

    async def settings_page(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        body = """
<div class='card'>
  <h1 style='margin:0 0 12px 0'>Настройки</h1>
  <p class='muted' style='margin-top:0'>Шаблон сообщения, которое отправляется пользователю после одобрения заявки.</p>

  <div class='toolbar'>
    <button class='btn' data-act='b'><b>B</b></button>
    <button class='btn' data-act='i'><i>I</i></button>
    <button class='btn' data-act='code'><code>&lt;/&gt;</code></button>
    <button class='btn' data-act='link'>Ссылка</button>
    <button class='btn' data-act='list'>Список</button>
    <span class='muted' id='statusLine'></span>
  </div>

  <div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>
    <div class='card' style='padding:12px'>
      <div style='display:flex;justify-content:space-between;align-items:center;gap:8px'>
        <strong>Редактор</strong>
        <div style='display:flex;gap:8px'>
          <button class='btn primary' id='saveBtn' type='button'>Сохранить</button>
          <button class='btn' id='cancelBtn' type='button'>Отмена</button>
        </div>
      </div>
      <textarea id='tpl' style='width:100%;min-height:260px;margin-top:10px;padding:10px;border:1px solid #ddd;border-radius:10px;font-family:ui-monospace,Consolas,monospace;resize:vertical'></textarea>
      <div class='muted' style='margin-top:8px'>Поддерживаются HTML-теги Telegram: <code>&lt;b&gt;</code>, <code>&lt;i&gt;</code>, <code>&lt;u&gt;</code>, <code>&lt;s&gt;</code>, <code>&lt;code&gt;</code>, <code>&lt;pre&gt;</code>, <code>&lt;a href="..."&gt;</code>, <code>&lt;br&gt;</code>. Переменные: <span id='varsInline'></span></div>
    </div>

    <div class='card' style='padding:12px'>
      <strong>Предпросмотр</strong>
      <div class='muted' style='margin-top:6px'>Здесь показано, как сообщение будет выглядеть после подстановки переменных.</div>
      <div id='preview' style='margin-top:10px;border:1px solid #e6e6e6;border-radius:10px;padding:10px;min-height:260px;background:#fff'></div>
    </div>
  </div>

  <div style='display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px'>
    <div class='card' style='padding:12px'>
      <strong>Переменные</strong>
      <div class='muted' style='margin-top:6px'>Fallback применяется, если значение переменной отсутствует. Sample используется только для предпросмотра.</div>
      <div class='table-wrap' style='margin-top:10px'>
        <table style='min-width:0'>
          <thead><tr><th>Переменная</th><th>Fallback</th><th>Sample (preview)</th></tr></thead>
          <tbody id='varsBody'></tbody>
        </table>
      </div>
    </div>

    <div class='card' style='padding:12px'>
      <strong>История изменений</strong>
      <div class='muted' style='margin-top:6px'>Можно посмотреть предыдущие версии и восстановить.</div>
      <div class='table-wrap' style='margin-top:10px'>
        <table style='min-width:0'>
          <thead><tr><th>ID</th><th>Дата</th><th>Кем</th><th>Действие</th><th style='width:220px'>Операции</th></tr></thead>
          <tbody id='histBody'></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<dialog id='dlg' style='border:1px solid #e6e6e6;border-radius:12px;max-width:900px;width:calc(100% - 24px)'>
  <form method='dialog'>
    <div style='display:flex;justify-content:space-between;align-items:center;gap:8px'>
      <strong id='dlgTitle'>Версия</strong>
      <button class='btn'>Закрыть</button>
    </div>
    <textarea id='dlgText' style='width:100%;min-height:240px;margin-top:10px;padding:10px;border:1px solid #ddd;border-radius:10px;font-family:ui-monospace,Consolas,monospace;resize:vertical'></textarea>
    <div style='display:flex;justify-content:flex-end;gap:8px;margin-top:10px'>
      <button class='btn danger' id='restoreBtn' type='button'>Восстановить</button>
    </div>
  </form>
</dialog>

<script>
const el={
  tpl:document.getElementById('tpl'),
  preview:document.getElementById('preview'),
  statusLine:document.getElementById('statusLine'),
  varsInline:document.getElementById('varsInline'),
  varsBody:document.getElementById('varsBody'),
  histBody:document.getElementById('histBody'),
  saveBtn:document.getElementById('saveBtn'),
  cancelBtn:document.getElementById('cancelBtn'),
  dlg:document.getElementById('dlg'),
  dlgTitle:document.getElementById('dlgTitle'),
  dlgText:document.getElementById('dlgText'),
  restoreBtn:document.getElementById('restoreBtn'),
};

const state={
  loaded:null,
  allowedVars:[],
  fallbacks:{},
  samples:{},
  selectedHistoryId:null,
  dirty:false,
};

function toast(msg,isErr){const w=document.getElementById('toastWrap');const d=document.createElement('div');d.className='toast'+(isErr?' err':'');d.textContent=msg;w.appendChild(d);setTimeout(()=>{d.remove();},4500);}
function setBusy(b,msg){el.statusLine.innerHTML=b?`<span class='pill'><span class='spinner' style='margin-right:6px'></span>${msg}</span>`:'';}

async function api(path,opt){
  const r=await fetch(path,Object.assign({headers:{'Content-Type':'application/json'}},opt||{}));
  const ct=r.headers.get('content-type')||'';
  const j=ct.includes('application/json')?await r.json():null;
  if(!r.ok){throw new Error((j&&j.error)||('HTTP '+r.status));}
  return j;
}

function wrapSelection(start,end){
  const ta=el.tpl;
  const s=ta.selectionStart||0;
  const e=ta.selectionEnd||0;
  const val=ta.value;
  const mid=val.slice(s,e)||'';
  const next=val.slice(0,s)+start+mid+end+val.slice(e);
  ta.value=next;
  ta.focus();
  ta.selectionStart=s+start.length;
  ta.selectionEnd=s+start.length+mid.length;
  markDirty();
  schedulePreview();
}

function insertList(){
  const ta=el.tpl;
  const s=ta.selectionStart||0;
  const e=ta.selectionEnd||0;
  const val=ta.value;
  const block=val.slice(s,e)||'';
  const lines=(block||'').split(/\r?\n/).map(x=>x.trim().length?('• '+x):x).join('\n');
  const next=val.slice(0,s)+lines+val.slice(e);
  ta.value=next;
  ta.focus();
  ta.selectionStart=s;
  ta.selectionEnd=s+lines.length;
  markDirty();
  schedulePreview();
}

function insertLink(){
  const url=prompt('URL для ссылки');
  if(!url) return;
  wrapSelection(`<a href="${url}">`,`</a>`);
}

function markDirty(){
  state.dirty=true;
}

function resetDirty(){
  state.dirty=false;
}

function buildVarsUI(){
  el.varsInline.textContent=state.allowedVars.map(v=>`{${v}}`).join(', ');
  el.varsBody.innerHTML=state.allowedVars.map(v=>{
    const fb=state.fallbacks[v]||'';
    const sm=state.samples[v]||'';
    return `<tr>
      <td><code>{${v}}</code></td>
      <td><input data-kind='fb' data-var='${v}' value='${escapeHtml(fb)}' style='width:100%;padding:8px;border:1px solid #ddd;border-radius:8px'/></td>
      <td><input data-kind='sm' data-var='${v}' value='${escapeHtml(sm)}' style='width:100%;padding:8px;border:1px solid #ddd;border-radius:8px'/></td>
    </tr>`;
  }).join('');
}

function buildHistoryUI(history){
  el.histBody.innerHTML=(history||[]).map(h=>{
    const who=h.created_by==null?'':String(h.created_by);
    return `<tr>
      <td><code>${h.id}</code></td>
      <td>${escapeHtml(h.created_at)}</td>
      <td>${escapeHtml(who)}</td>
      <td>${escapeHtml(h.action)}</td>
      <td>
        <button class='btn' data-act='view' data-id='${h.id}' type='button'>Просмотр</button>
        <button class='btn danger' data-act='restore' data-id='${h.id}' type='button'>Восстановить</button>
      </td>
    </tr>`;
  }).join('');
}

function escapeHtml(s){
  return (s??'').toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

let previewTimer=null;
function schedulePreview(){
  clearTimeout(previewTimer);
  previewTimer=setTimeout(runPreview,250);
}

async function runPreview(){
  try{
    const payload={template_html:el.tpl.value,fallbacks:state.fallbacks,sample_vars:state.samples};
    const res=await api('/api/admin/settings/approval_message/preview',{method:'POST',body:JSON.stringify(payload)});
    el.preview.innerHTML=res.html;
  }catch(e){
    el.preview.textContent=e.message;
  }
}

async function load(){
  setBusy(true,'Загрузка');
  try{
    const data=await api('/api/admin/settings/approval_message');
    state.allowedVars=data.allowed_vars||[];
    state.fallbacks=data.fallbacks||{};
    state.samples={
      client_name:'Иван',
      request_id:'123',
      node_id:'a1b2c3d4e5',
      tg_id:'100000000',
      username:'example',
      bot_username:'',
      network_id:'',
    };
    el.tpl.value=data.template_html||'';
    state.loaded={template_html:el.tpl.value,fallbacks:JSON.parse(JSON.stringify(state.fallbacks))};
    buildVarsUI();
    buildHistoryUI(data.history||[]);
    resetDirty();
    schedulePreview();
  }catch(e){
    toast(e.message,true);
  }finally{
    setBusy(false,'');
  }
}

async function save(){
  if(!confirm('Сохранить изменения?')) return;
  el.saveBtn.setAttribute('disabled','disabled');
  el.cancelBtn.setAttribute('disabled','disabled');
  setBusy(true,'Сохранение');
  try{
    const payload={template_html:el.tpl.value,fallbacks:state.fallbacks};
    const data=await api('/api/admin/settings/approval_message/save',{method:'POST',body:JSON.stringify(payload)});
    toast('Сохранено');
    state.loaded={template_html:data.template_html,fallbacks:data.fallbacks};
    resetDirty();
    buildHistoryUI(data.history||[]);
    schedulePreview();
  }catch(e){
    toast((e&&e.message)?e.message:'Ошибка сохранения',true);
  }finally{
    setBusy(false,'');
    el.saveBtn.removeAttribute('disabled');
    el.cancelBtn.removeAttribute('disabled');
  }
}

function cancel(){
  if(state.dirty && !confirm('Отменить изменения? Несохранённые правки будут потеряны.')) return;
  if(!state.loaded) return;
  el.tpl.value=state.loaded.template_html||'';
  state.fallbacks=JSON.parse(JSON.stringify(state.loaded.fallbacks||{}));
  buildVarsUI();
  resetDirty();
  schedulePreview();
}

async function viewVersion(id){
  setBusy(true,'Загрузка');
  try{
    const data=await api('/api/admin/settings/approval_message/history/'+id);
    state.selectedHistoryId=id;
    el.dlgTitle.textContent='Версия #'+id;
    el.dlgText.value=data.template_html||'';
    el.dlg.showModal();
  }catch(e){
    toast(e.message,true);
  }finally{
    setBusy(false,'');
  }
}

async function restoreVersion(id){
  if(!confirm('Восстановить эту версию?')) return;
  setBusy(true,'Восстановление');
  try{
    const data=await api('/api/admin/settings/approval_message/restore',{method:'POST',body:JSON.stringify({history_id:id})});
    toast('Восстановлено');
    el.tpl.value=data.template_html||'';
    state.fallbacks=data.fallbacks||{};
    state.loaded={template_html:el.tpl.value,fallbacks:JSON.parse(JSON.stringify(state.fallbacks))};
    buildVarsUI();
    buildHistoryUI(data.history||[]);
    resetDirty();
    schedulePreview();
  }catch(e){
    toast(e.message,true);
  }finally{
    setBusy(false,'');
  }
}

document.querySelectorAll('button[data-act]').forEach(b=>{
  b.addEventListener('click',()=>{
    const a=b.getAttribute('data-act');
    if(a==='b') wrapSelection('<b>','</b>');
    if(a==='i') wrapSelection('<i>','</i>');
    if(a==='code') wrapSelection('<code>','</code>');
    if(a==='link') insertLink();
    if(a==='list') insertList();
  });
});

el.saveBtn.addEventListener('click',save);
el.cancelBtn.addEventListener('click',cancel);
el.tpl.addEventListener('input',()=>{markDirty();schedulePreview();});
el.varsBody.addEventListener('input',(e)=>{
  const t=e.target;
  if(!(t instanceof HTMLInputElement)) return;
  const kind=t.dataset.kind;
  const v=t.dataset.var;
  if(!kind||!v) return;
  if(kind==='fb') state.fallbacks[v]=t.value;
  if(kind==='sm') state.samples[v]=t.value;
  markDirty();
  schedulePreview();
});
el.histBody.addEventListener('click',(e)=>{
  const t=e.target;
  if(!(t instanceof HTMLElement)) return;
  const act=t.dataset.act;
  const id=parseInt(t.dataset.id||'0',10);
  if(!act||!id) return;
  if(act==='view') viewVersion(id);
  if(act==='restore') restoreVersion(id);
});
el.restoreBtn.addEventListener('click',()=>{ if(state.selectedHistoryId) restoreVersion(state.selectedHistoryId); });
window.addEventListener('beforeunload',(e)=>{ if(state.dirty){ e.preventDefault(); e.returnValue=''; } });

load();
</script>
"""
        return web.Response(text=_html_page("Настройки", body), content_type="text/html")

    async def api_get_approval_message(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        raw = await db.get_setting("approval_message")
        s = settings_from_json(raw or "")
        hist = await db.list_setting_history("approval_message", limit=50)
        history = [
            {"id": hid, "created_at": created_at, "created_by": created_by, "action": action}
            for hid, created_at, created_by, action, _ in hist
        ]
        return await _json(
            request,
            {
                "template_html": _denormalize_template_output(s.template_html),
                "fallbacks": s.fallbacks,
                "allowed_vars": allowed_template_vars(),
                "history": history,
            },
        )

    def _normalize_template_input(template_html: str) -> str:
        t = (template_html or "").replace("\r\n", "\n").replace("\r", "\n")
        t = t.replace("\n", "<br>")
        return t

    def _denormalize_template_output(template_html: str) -> str:
        t = template_html or ""
        t = t.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
        return t

    async def api_preview_approval_message(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        try:
            payload = await request.json()
        except Exception:
            return await _json(request, {"error": "Некорректный JSON"}, status=400)
        template_html = _normalize_template_input(str(payload.get("template_html") or ""))
        fallbacks = payload.get("fallbacks")
        sample_vars = payload.get("sample_vars")
        if not isinstance(fallbacks, dict):
            fallbacks = {}
        if not isinstance(sample_vars, dict):
            sample_vars = {}
        ok, unknown = validate_template_vars(template_html)
        if not ok:
            return await _json(request, {"error": "Неизвестные переменные: " + ", ".join(unknown)}, status=400)
        template_html = sanitize_telegram_html(template_html)
        html = render_template_html(template_html, variables=sample_vars, fallbacks=fallbacks)
        return await _json(request, {"html": html})

    async def api_save_approval_message(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        try:
            payload = await request.json()
        except Exception:
            return await _json(request, {"error": "Некорректный JSON"}, status=400)
        template_html_raw = str(payload.get("template_html") or "")
        fallbacks = payload.get("fallbacks")
        if not isinstance(fallbacks, dict):
            fallbacks = {}

        if len(template_html_raw.strip()) < 1:
            return await _json(request, {"error": "Сообщение не может быть пустым"}, status=400)
        if len(template_html_raw) > 4000:
            return await _json(request, {"error": "Сообщение слишком длинное"}, status=400)

        template_html = sanitize_telegram_html(_normalize_template_input(template_html_raw))
        ok, unknown = validate_template_vars(template_html)
        if not ok:
            return await _json(request, {"error": "Неизвестные переменные: " + ", ".join(unknown)}, status=400)

        fallbacks_clean: dict[str, str] = {}
        for k in allowed_template_vars():
            v = fallbacks.get(k)
            if v is None:
                continue
            s = str(v)
            if len(s) > 500:
                return await _json(request, {"error": f"Fallback для {k} слишком длинный"}, status=400)
            fallbacks_clean[k] = s

        raw_value = settings_to_json(ApprovalMessageSettings(template_html=template_html, fallbacks=fallbacks_clean))
        await db.set_setting("approval_message", raw_value, updated_by=admin_chat_id, action="update")

        s = settings_from_json(raw_value)
        hist = await db.list_setting_history("approval_message", limit=50)
        history = [
            {"id": hid, "created_at": created_at, "created_by": created_by, "action": action}
            for hid, created_at, created_by, action, _ in hist
        ]
        return await _json(request, {"template_html": _denormalize_template_output(s.template_html), "fallbacks": s.fallbacks, "history": history})

    async def api_get_history_item(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        hid = int(request.match_info.get("history_id", "0") or "0")
        item = await db.get_setting_history_value(hid)
        if not item:
            return await _json(request, {"error": "not found"}, status=404)
        key, value = item
        if key != "approval_message":
            return await _json(request, {"error": "not found"}, status=404)
        s = settings_from_json(value)
        return await _json(request, {"template_html": _denormalize_template_output(s.template_html), "fallbacks": s.fallbacks})

    async def api_restore_approval_message(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        try:
            payload = await request.json()
        except Exception:
            return await _json(request, {"error": "Некорректный JSON"}, status=400)
        hid = int(payload.get("history_id") or 0)
        item = await db.get_setting_history_value(hid)
        if not item:
            return await _json(request, {"error": "not found"}, status=404)
        key, value = item
        if key != "approval_message":
            return await _json(request, {"error": "not found"}, status=404)
        s = settings_from_json(value)
        ok, unknown = validate_template_vars(s.template_html)
        if not ok:
            return await _json(request, {"error": "Нельзя восстановить: неизвестные переменные: " + ", ".join(unknown)}, status=400)
        await db.set_setting("approval_message", value, updated_by=admin_chat_id, action="restore")
        hist = await db.list_setting_history("approval_message", limit=50)
        history = [
            {"id": hid2, "created_at": created_at, "created_by": created_by, "action": action}
            for hid2, created_at, created_by, action, _ in hist
        ]
        return await _json(request, {"template_html": _denormalize_template_output(s.template_html), "fallbacks": s.fallbacks, "history": history})

    async def user_profile_page(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        tg_id = int(request.match_info.get("tg_id", "0") or "0")
        body = (
            "<div class='card'>"
            f"<h1 style='margin:0 0 6px 0'>Профиль: <code>{tg_id}</code></h1>"
            "<div class='toolbar'>"
            "<button class='btn danger' id='deactivateBtn'>Деактивировать</button>"
            "<span class='muted' id='statusLine'></span>"
            "</div>"
            "<div id='profileBox' class='muted'>Загрузка…</div>"
            "<h2 style='margin:16px 0 10px 0'>Запросы пользователя</h2>"
            "<div class='table-wrap'><table><thead><tr><th>ID</th><th>node_id</th><th>status</th><th>created_at</th><th>decided_at</th></tr></thead><tbody id='tbody'></tbody></table></div>"
            "</div>"
            "<script>"
            f"const tgId={tg_id};"
            "const el={profileBox:document.getElementById('profileBox'),tbody:document.getElementById('tbody'),statusLine:document.getElementById('statusLine'),deactivateBtn:document.getElementById('deactivateBtn')};"
            "function toast(msg,isErr){const w=document.getElementById('toastWrap');const d=document.createElement('div');d.className='toast'+(isErr?' err':'');d.textContent=msg;w.appendChild(d);setTimeout(()=>{d.remove();},4000);}"
            "function setBusy(b,msg){el.statusLine.innerHTML=b?`<span class='pill'><span class='spinner' style='margin-right:6px'></span>${msg}</span>`:'';}"
            "function esc(s){return (s??'').toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;').replace(/'/g,'&#39;');}"
            "async function api(path,opt){const r=await fetch(path,Object.assign({headers:{'Content-Type':'application/json'}},opt||{}));let j=null;const ct=r.headers.get('content-type')||'';if(ct.includes('application/json')) j=await r.json(); if(!r.ok){throw new Error((j&&j.error)||('HTTP '+r.status));} return j;}"
            "async function load(){setBusy(true,'Загрузка'); try{const u=await api('/api/admin/users/'+tgId); el.profileBox.innerHTML=`<div><div><strong>${u.username?('@'+esc(u.username)):'(no username)'}</strong> <span class='muted'>${esc([u.first_name,u.last_name].filter(Boolean).join(' '))}</span></div><div class='muted'>Создан: ${esc(u.created_at)} · Обновлён: ${esc(u.updated_at)} · ${u.is_active?`<span class='pill ok'>active</span>`:`<span class='pill bad'>inactive</span>`}</div><div class='muted'>node_id: ${u.node_id?('<code>'+esc(u.node_id)+'</code>'):'(none)'}</div></div>`; el.deactivateBtn.disabled=!u.is_active; const qp=new URLSearchParams({page:'1',page_size:'100',sort:'id',order:'desc',tg_id:String(tgId)}); const rs=await api('/api/admin/requests?'+qp.toString()); el.tbody.innerHTML=rs.items.map(r=>`<tr><td><code>${r.id}</code></td><td><code>${esc(r.node_id)}</code></td><td>${esc(r.status)}</td><td>${esc(r.created_at)}</td><td>${esc(r.decided_at||'')}</td></tr>`).join(''); }catch(e){toast(e.message,true);} finally{setBusy(false,'');}}"
            "el.deactivateBtn.addEventListener('click',async()=>{if(!confirm('Деактивировать пользователя '+tgId+'?')) return; el.deactivateBtn.setAttribute('disabled','disabled'); setBusy(true,'Выполнение'); try{await api('/api/admin/users/'+tgId+'/deactivate',{method:'POST',body:JSON.stringify({})}); toast('Пользователь деактивирован'); await load();}catch(e){toast(e.message,true);} finally{setBusy(false,'');}});"
            "load();"
            "</script>"
        )
        return web.Response(text=_html_page("Профиль", body), content_type="text/html")

    async def api_users(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        q = (request.query.get("q") or "").strip() or None
        page = int(request.query.get("page", "1") or "1")
        page_size = int(request.query.get("page_size", "25") or "25")
        sort = (request.query.get("sort") or "updated_at").strip()
        order = (request.query.get("order") or "desc").strip()
        items, total = await db.list_users_paginated(q=q, page=page, page_size=page_size, sort=sort, order=order)
        return await _json(
            request,
            {
                "items": [
                    {
                        "tg_id": u.tg_id,
                        "username": u.username,
                        "first_name": u.first_name,
                        "last_name": u.last_name,
                        "email": u.email,
                        "created_at": u.created_at,
                        "updated_at": u.updated_at,
                        "is_active": u.is_active,
                        "deactivated_at": u.deactivated_at,
                        "node_id": u.node_id,
                    }
                    for u in items
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        )

    async def api_user_get(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        tg_id = int(request.match_info.get("tg_id", "0") or "0")
        u = await db.get_user(tg_id)
        if not u:
            return await _json(request, {"error": "not found"}, status=404)
        return await _json(
            request,
            {
                "tg_id": u.tg_id,
                "username": u.username,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "email": u.email,
                "created_at": u.created_at,
                "updated_at": u.updated_at,
                "is_active": u.is_active,
                "deactivated_at": u.deactivated_at,
                "node_id": u.node_id,
            },
        )

    async def api_user_deactivate(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        tg_id = int(request.match_info.get("tg_id", "0") or "0")
        ok = await db.deactivate_user(tg_id)
        log.info("user_deactivated tg_id=%s by=dashboard", tg_id)
        if ok:
            await _notify_user(tg_id, "Ваш аккаунт был деактивирован администратором.")
        return await _json(request, {"ok": ok})

    async def api_users_bulk_deactivate(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        tg_ids = payload.get("tg_ids") or []
        if not isinstance(tg_ids, list):
            return await _json(request, {"error": "tg_ids must be list"}, status=400)
        updated = await db.bulk_deactivate_users([int(x) for x in tg_ids])
        log.info("users_bulk_deactivated count=%s by=dashboard", updated)
        for x in tg_ids:
            try:
                await _notify_user(int(x), "Ваш аккаунт был деактивирован администратором.")
            except Exception:
                pass
        return await _json(request, {"ok": True, "updated": updated})

    async def api_users_export(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        q = (request.query.get("q") or "").strip() or None
        sort = (request.query.get("sort") or "updated_at").strip()
        order = (request.query.get("order") or "desc").strip()
        items, _ = await db.list_users_paginated(q=q, page=1, page_size=200, sort=sort, order=order)
        lines = ["tg_id,username,first_name,last_name,email,created_at,updated_at,is_active,node_id"]
        for u in items:
            def f(v: Any) -> str:
                if v is None:
                    return ""
                s = str(v)
                if "," in s or '"' in s:
                    s = '"' + s.replace('"', '""') + '"'
                return s

            lines.append(
                ",".join(
                    [
                        f(u.tg_id),
                        f(u.username),
                        f(u.first_name),
                        f(u.last_name),
                        f(u.email),
                        f(u.created_at),
                        f(u.updated_at),
                        f(1 if u.is_active else 0),
                        f(u.node_id),
                    ]
                )
            )
        return web.Response(text="\n".join(lines), content_type="text/csv")

    async def api_requests(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        q = (request.query.get("q") or "").strip() or None
        status = (request.query.get("status") or "").strip() or None
        page = int(request.query.get("page", "1") or "1")
        page_size = int(request.query.get("page_size", "25") or "25")
        sort = (request.query.get("sort") or "id").strip()
        order = (request.query.get("order") or "desc").strip()
        tg_id_raw = (request.query.get("tg_id") or "").strip()
        tg_id = int(tg_id_raw) if tg_id_raw else None
        items, total = await db.list_requests_paginated(q=q, status=status, page=page, page_size=page_size, sort=sort, order=order, tg_id=tg_id)
        return await _json(
            request,
            {
                "items": [
                    {
                        "id": r.id,
                        "tg_id": r.tg_id,
                        "node_id": r.node_id,
                        "status": r.status,
                        "created_at": r.created_at,
                        "decided_at": r.decided_at,
                        "decided_by": r.decided_by,
                        "decided_via": r.decided_via,
                    }
                    for r in items
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        )

    async def api_request_decide(request: web.Request) -> web.Response:
        auth_resp = _require_auth(request)
        if auth_resp:
            return auth_resp
        request_id = int(request.match_info.get("request_id", "0") or "0")
        action = request.match_info.get("action", "")
        status = "approved" if action == "approve" else "denied"
        req = await db.get_request(request_id)
        if not req:
            return await _json(request, {"error": "not found"}, status=404)
        ok = await db.decide_request(request_id, status=status, decided_by=admin_chat_id, decided_via="dashboard")
        if not ok:
            return await _json(request, {"error": "already decided"}, status=409)
        log.info("request_%s request_id=%s decided_by=%s via=dashboard tg_id=%s node_id=%s", status, request_id, admin_chat_id, req.tg_id, req.node_id)
        if status == "approved":
            raw = await db.get_setting("approval_message")
            st = settings_from_json(raw or "")
            u = await db.get_user(req.tg_id)
            client_name = ""
            username = ""
            if u:
                parts = [p for p in [u.first_name, u.last_name] if p]
                client_name = " ".join(parts)
                username = u.username or ""
            variables = {
                "client_name": client_name,
                "request_id": request_id,
                "node_id": req.node_id,
                "tg_id": req.tg_id,
                "username": username,
                "bot_username": bot_username,
                "network_id": network_id,
            }
            msg_html = render_template_html(st.template_html, variables=variables, fallbacks=st.fallbacks)
            await bot.send_message(chat_id=req.tg_id, text=msg_html, parse_mode="HTML")
        else:
            await _notify_user(req.tg_id, f"Ваша заявка {request_id} отклонена. node_id: {req.node_id}")
        return await _json(request, {"ok": True})

    app.router.add_get("/admin", users_page)
    app.router.add_get("/admin/requests", requests_page)
    app.router.add_get("/admin/users/{tg_id}", user_profile_page)
    app.router.add_get("/admin/settings", settings_page)

    app.router.add_get("/api/admin/users", api_users)
    app.router.add_get("/api/admin/users/{tg_id}", api_user_get)
    app.router.add_post("/api/admin/users/{tg_id}/deactivate", api_user_deactivate)
    app.router.add_post("/api/admin/users/bulk/deactivate", api_users_bulk_deactivate)
    app.router.add_get("/api/admin/users/export", api_users_export)

    app.router.add_get("/api/admin/requests", api_requests)
    app.router.add_post("/api/admin/requests/{request_id}/{action}", api_request_decide)

    app.router.add_get("/api/admin/settings/approval_message", api_get_approval_message)
    app.router.add_post("/api/admin/settings/approval_message/preview", api_preview_approval_message)
    app.router.add_post("/api/admin/settings/approval_message/save", api_save_approval_message)
    app.router.add_get("/api/admin/settings/approval_message/history/{history_id}", api_get_history_item)
    app.router.add_post("/api/admin/settings/approval_message/restore", api_restore_approval_message)
    return app

