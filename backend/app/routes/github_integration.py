import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.github_integration import GitHubProjectSelection, GitHubStatusMappingUpdate
from app.services.github_integration_service import GitHubIntegrationService


router = APIRouter()


def get_service(db: Session = Depends(get_db)) -> GitHubIntegrationService:
    return GitHubIntegrationService(db)


def local_user_id() -> str:
    """Current identity boundary until SmartDesk gains authentication."""
    return settings.DEFAULT_USER_ID


def translate_error(exc: Exception):
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=503, detail=str(exc))


@router.get("/status")
def connection_status(service: GitHubIntegrationService = Depends(get_service)):
    return service.connection_status(local_user_id())


@router.get("/connect")
def connect(service: GitHubIntegrationService = Depends(get_service)):
    try:
        return {"installation_url": service.begin_installation(local_user_id())}
    except Exception as exc:
        translate_error(exc)


@router.get("/callback")
def callback(installation_id: int = Query(...), state: str = Query(...),
             service: GitHubIntegrationService = Depends(get_service)):
    try:
        result = service.complete_installation(installation_id, state)
        if result.get("user_authorization_url"):
            return RedirectResponse(url=result["user_authorization_url"], status_code=303)
        return _frontend_github_redirect("connected")
    except Exception as exc:
        translate_error(exc)


@router.get("/user-callback")
def user_callback(code: str = Query(...), state: str = Query(...),
                  service: GitHubIntegrationService = Depends(get_service)):
    try:
        service.complete_user_authorization(code, state)
        return _frontend_github_redirect("connected")
    except Exception as exc:
        translate_error(exc)


def _frontend_github_redirect(result: str):
    if settings.SMARTDESK_FRONTEND_URL:
        frontend = settings.SMARTDESK_FRONTEND_URL.rstrip("/")
        return RedirectResponse(url=f"{frontend}/#/settings?github={result}", status_code=303)
    return RedirectResponse(url=f"/api/v1/integrations/github/setup?{result}=1", status_code=303)


@router.get("/projects")
def projects(service: GitHubIntegrationService = Depends(get_service)):
    try:
        return {"projects": service.projects(local_user_id())}
    except Exception as exc:
        translate_error(exc)


@router.put("/project")
def select_project(payload: GitHubProjectSelection,
                   service: GitHubIntegrationService = Depends(get_service)):
    try:
        return service.select_project(local_user_id(), payload)
    except Exception as exc:
        translate_error(exc)


@router.get("/status-options")
def status_options(service: GitHubIntegrationService = Depends(get_service)):
    try:
        return {"options": service.status_options(local_user_id())}
    except Exception as exc:
        translate_error(exc)


@router.put("/status-mapping")
def save_status_mapping(payload: GitHubStatusMappingUpdate,
                        service: GitHubIntegrationService = Depends(get_service)):
    try:
        project_id = service.save_mapping(local_user_id(), payload.mapping)
        return {"saved": True, "initial_sync_project_id": project_id}
    except Exception as exc:
        translate_error(exc)


@router.get("/status-mapping")
def current_status_mapping(service: GitHubIntegrationService = Depends(get_service)):
    return {"mapping": service.current_mapping(local_user_id())}


@router.post("/initial-sync")
def initial_synchronization(service: GitHubIntegrationService = Depends(get_service)):
    try:
        return {"project_id": service.synchronize(local_user_id())}
    except Exception as exc:
        translate_error(exc)


@router.get("/active-tasks")
def active_tasks(service: GitHubIntegrationService = Depends(get_service)):
    return {"tasks": service.active_tasks(local_user_id())}


@router.post("/webhook")
async def webhook(request: Request, service: GitHubIntegrationService = Depends(get_service)):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not service.verify_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    try:
        service.process_webhook(payload, dict(request.headers))
        return {"accepted": True}
    except Exception as exc:
        translate_error(exc)


@router.delete("/connection")
def disconnect(service: GitHubIntegrationService = Depends(get_service)):
    service.disconnect(local_user_id())
    return {"disconnected": True}


@router.get("/setup", response_class=HTMLResponse)
def setup_page() -> str:
    return """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SmartDesk GitHub Development Setup</title>
<style>
body{font:15px system-ui;max-width:900px;margin:40px auto;padding:0 20px;color:#18202a}button,select{padding:8px;margin:4px}section{border:1px solid #ccd5df;border-radius:8px;padding:18px;margin:14px 0}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.error{color:#a00}.ok{color:#076b35}pre{white-space:pre-wrap;background:#f5f7f9;padding:12px}</style>
</head><body><h1>GitHub Projects development setup</h1><p>This utility is for local setup and diagnostics. Use SmartDesk Settings for the normal interface.</p><div id="message"></div>
<section><h2>Connection</h2><pre id="status">Loading...</pre><button onclick="connectGitHub()">Connect GitHub</button><button onclick="disconnectGitHub()">Disconnect</button></section>
<section><h2>Project</h2><button onclick="loadProjects()">Load projects</button><select id="projects"></select><button onclick="selectProject()">Select project</button></section>
<section><h2>Status mapping</h2><button onclick="loadOptions()">Load Status options</button><div id="mappings"></div><button onclick="saveMapping()">Save mapping and initial sync</button></section>
<section><h2>Active task and initial duration estimate</h2><button onclick="loadActive()">Refresh</button><pre id="active">No data loaded.</pre></section>
<script>
const base='/api/v1/integrations/github'; const msg=document.getElementById('message');
const projectSelect=document.getElementById('projects'); const loadedProjects=new Map();
async function api(path,options={}){const r=await fetch(base+path,{headers:{'Content-Type':'application/json'},...options});const data=await r.json();if(!r.ok)throw new Error(data.detail||r.statusText);return data}
function show(text,ok=true){msg.className=ok?'ok':'error';msg.textContent=text}
async function loadStatus(){try{status.textContent=JSON.stringify(await api('/status'),null,2)}catch(e){show(e.message,false)}}
async function connectGitHub(){try{location.href=(await api('/connect')).installation_url}catch(e){show(e.message,false)}}
async function disconnectGitHub(){try{await api('/connection',{method:'DELETE'});show('Disconnected');loadStatus()}catch(e){show(e.message,false)}}
async function loadProjects(){try{const data=await api('/projects');projectSelect.innerHTML='';loadedProjects.clear();for(const p of data.projects){const id=p.project_id??p.id;if(!id)continue;loadedProjects.set(id,p);const o=document.createElement('option');o.value=id;o.textContent=p.title;projectSelect.appendChild(o)}}catch(e){show(e.message,false)}}
async function selectProject(){try{const p=loadedProjects.get(projectSelect.value);if(!p)throw new Error('Load and choose a project');const payload={owner:p.owner,project_number:p.number,project_id:p.project_id??p.id,title:p.title};await api('/project',{method:'PUT',body:JSON.stringify(payload)});show('Project selected');loadStatus()}catch(e){show(e.message,false)}}
async function loadOptions(){try{const data=await api('/status-options');mappings.innerHTML='';for(const option of data.options){const row=document.createElement('div');row.className='row';row.dataset.name=option.name;row.innerHTML=`<span>${option.name}</span><select><option>OTHER</option><option>NOT_STARTED</option><option>ACTIVE</option><option>DONE</option></select>`;mappings.appendChild(row)}}catch(e){show(e.message,false)}}
async function saveMapping(){try{const mapping={};for(const row of mappings.children)mapping[row.dataset.name]=row.querySelector('select').value;const data=await api('/status-mapping',{method:'PUT',body:JSON.stringify({mapping})});show(`Mapping saved; initial sync ${data.initial_sync_project_id}`);loadActive()}catch(e){show(e.message,false)}}
async function loadActive(){try{active.textContent=JSON.stringify((await api('/active-tasks')).tasks,null,2)}catch(e){show(e.message,false)}}
loadStatus();loadActive();
</script></body></html>"""
