import {useEffect,useRef,useState} from 'react';

export type WorkspaceSecret = {id:string;name:string};
export type Operations = {worker_healthy:boolean;oldest_pending_seconds:number;schema:number;queue:Record<string,number>;storage:{n:number;size:number;response_bytes:number}};
type Props = {
  secrets:WorkspaceSecret[]; operations:Operations|null;
  request:<T>(path:string,options?:RequestInit)=>Promise<T>;
  changed:()=>Promise<void>; notify:(message:string)=>void; signedOut:()=>void;
};

export function SecuritySettings({secrets,operations,request,changed,notify,signedOut}:Props){
  const [name,setName]=useState(''), [value,setValue]=useState('');
  const [current,setCurrent]=useState(''), [password,setPassword]=useState('');
  const [busy,setBusy]=useState(false), [error,setError]=useState('');
  const [deleting,setDeleting]=useState<WorkspaceSecret|null>(null);
  const trigger=useRef<HTMLElement|null>(null), busyRef=useRef(false);busyRef.current=busy;
  useEffect(()=>{
    if(!deleting)return;
    const dialog=document.querySelector<HTMLElement>('[data-secret-confirm]');
    dialog?.querySelector<HTMLElement>('button')?.focus();
    const handler=(e:KeyboardEvent)=>{
      if(e.key==='Escape'&&!busyRef.current)setDeleting(null);
      const controls=dialog?.querySelectorAll<HTMLElement>('button:not(:disabled)');
      if(e.key==='Tab'&&controls?.length){const first=controls[0],last=controls[controls.length-1];
        if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
        else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}
    };
    document.addEventListener('keydown',handler);
    return()=>{document.removeEventListener('keydown',handler);trigger.current?.focus();};
  },[deleting]);
  async function act(action:()=>Promise<void>){setBusy(true);setError('');try{await action();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <>
    <section className="settings-card"><h2>Workspace secrets</h2><p>Add provider verification and delivery signing secrets. Values are encrypted on the server and cannot be displayed again. To rotate, create a replacement and update your endpoints.</p>
      <form onSubmit={e=>{e.preventDefault();void act(async()=>{await request('/secrets',{method:'POST',body:JSON.stringify({name,value})});setName('');setValue('');await changed();notify('Secret stored');});}}>
        <label>Secret name<input required maxLength={60} value={name} onChange={e=>setName(e.target.value)} autoComplete="off"/></label>
        <label>Secret value<input required type="password" minLength={32} maxLength={4096} value={value} onChange={e=>setValue(e.target.value)} autoComplete="new-password"/></label>
        <button className="primary" disabled={busy}>Store secret</button>
      </form>
      <ul>{secrets.map(secret=><li key={secret.id}>{secret.name} <code>{secret.id}</code><button className="secondary" disabled={busy} aria-label={'Delete secret '+secret.name} onClick={()=>{trigger.current=document.activeElement as HTMLElement;setError('');setDeleting(secret);}}>Delete</button></li>)}</ul>
      {!secrets.length&&<p>No secrets stored yet.</p>}
    </section>
    <section className="settings-card"><h2>Change password</h2><p>Changing your password signs out every session in your account.</p>
      <form onSubmit={e=>{e.preventDefault();void act(async()=>{await request('/password',{method:'POST',body:JSON.stringify({current_password:current,password})});setCurrent('');setPassword('');signedOut();});}}>
        <label>Current password<input required type="password" minLength={12} maxLength={128} value={current} onChange={e=>setCurrent(e.target.value)} autoComplete="current-password"/></label>
        <label>New password<input required type="password" minLength={12} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} autoComplete="new-password"/></label>
        <button className="primary" disabled={busy}>Change password and sign out</button>
      </form>
    </section>
    <section className="settings-card"><h2>Delivery health</h2>{operations?<dl>
      <div><dt>Worker</dt><dd>{operations.worker_healthy?'Healthy':'No recent heartbeat'}</dd></div>
      <div><dt>Queued / sending</dt><dd>{operations.queue.queued||0} / {operations.queue.sending||0}</dd></div>
      <div><dt>Oldest pending</dt><dd>{operations.oldest_pending_seconds} seconds</dd></div>
      <div><dt>Retained payloads</dt><dd>{(operations.storage.size/1024/1024).toFixed(2)} MiB</dd></div>
      <div><dt>Response previews</dt><dd>{(operations.storage.response_bytes/1024/1024).toFixed(2)} MiB</dd></div>
    </dl>:<p>Loading health…</p>}<p>Limits apply to your workspace. Server backup and recovery are managed by the operator.</p></section>
    {error&&<div className="form-error" role="alert">{error}</div>}
    {deleting&&<div className="modal-backdrop"><section className="modal" data-secret-confirm role="dialog" aria-modal="true" aria-labelledby="secret-confirm-title"><h2 id="secret-confirm-title">Delete stored secret?</h2><p>This permanently removes {deleting.name}. Endpoints and pending deliveries must stop referencing it first.</p>{error&&<p className="form-error" role="alert">{error}</p>}<div className="modal-actions"><button className="secondary" disabled={busy} onClick={()=>setDeleting(null)}>Cancel</button><button className="primary destructive" disabled={busy} onClick={()=>void act(async()=>{await request('/secrets/'+deleting.id,{method:'DELETE'});setDeleting(null);await changed();notify('Secret deleted');})}>Delete secret permanently</button></div></section></div>}
  </>;
}
