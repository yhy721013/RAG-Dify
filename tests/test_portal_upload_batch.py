"""批量UI复用原接口；合成解析输出不代表真实MinerU结果。"""
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.errors import DomainError
from app.portal.main import create_app
from app.portal import worker
from app.portal.settings import PortalSettings
from test_portal import pdf_bytes, portal

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="可选Node运行时用于JS队列回归；门户运行不依赖Node")
def test_browser_queue_state_machine_and_drop_events():
    result=subprocess.run([shutil.which("node"),str(ROOT/'tests/js/test_upload_queue.cjs')],capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


def test_mixed_uploads_continue_and_reuse_parse_task(portal):
    client,store,_=portal
    first=client.post('/api/documents',files={'file':('first.pdf',pdf_bytes(1),'application/pdf')}).json()
    failed=client.post('/api/documents',files={'file':('broken.pdf',b'not a PDF','application/pdf')})
    last=client.post('/api/documents',files={'file':('last.pdf',pdf_bytes(2),'application/pdf')}).json()
    duplicate=client.post('/api/documents',files={'file':('renamed.pdf',pdf_bytes(1),'application/pdf')}).json()
    assert failed.status_code==422
    assert first['parse_job']['status']==last['parse_job']['status']=='queued'
    assert duplicate['reused'] and duplicate['parse_job']['id']==first['parse_job']['id']
    assert len(store.jobs())==2 and len(client.get('/api/documents').json())==2


def test_parse_error_has_file_retry_and_other_files_finish(tmp_path,monkeypatch):
    executable=tmp_path/'mineru-kit.exe';executable.touch()
    config=PortalSettings(data_root=tmp_path/'data',mineru_executable=executable,app_env='test')
    app=create_app(config);attempts={};actual_parse=worker.parse_document
    def controlled_parse(job,store,cfg):
        doc=store.document(job['payload']['document_id']);name=doc['filename']
        attempts[name]=attempts.get(name,0)+1
        if name=='retry.pdf' and attempts[name]==1: raise DomainError('parse_error','合成解析故障，仅此文件失败')
        def parser(command,log_path,timeout,tick):
            raw={'schema':'docvortex.middle','schema_version':'2.0','metadata':{'producer':{'name':'mineru','version':'4.0.2'}},'is_full_document':True,
                 'pages':[{'page_idx':i,'blocks':[{'index':0,'type':'text','content':[{'type':'text','content':f'{i+1} 【合成批量测试】不得自动批准。'}]}]} for i in range(doc['page_count'])]}
            with zipfile.ZipFile(log_path.parent/'result.zip','w') as archive:
                archive.writestr('middle_json.json',json.dumps(raw,ensure_ascii=False));archive.writestr('structured_content.json','{}');archive.writestr('markdown.md','合成软件测试')
        return actual_parse(job,store,cfg,parser)
    monkeypatch.setattr(worker,'parse_document',controlled_parse)
    with TestClient(app,base_url=config.origin) as client:
        token=client.get('/api/status').json()['csrf_token'];client.headers.update({'Origin':config.origin,'X-CSRF-Token':token})
        receipts=[client.post('/api/documents',files={'file':(name,pdf_bytes(i+1),'application/pdf')}).json() for i,name in enumerate(('before.pdf','retry.pdf','after.pdf'))]
        store=app.state.store
        while job:=store.claim():worker.execute(job,store,config)
        rows={r['filename']:r for r in client.get('/api/documents').json()}
        assert [rows[n]['parse_job']['status'] for n in ('before.pdf','retry.pdf','after.pdf')]==['succeeded','failed','succeeded']
        assert rows['retry.pdf']['parse_job']['error']['code']=='parse_error'
        identity=rows['retry.pdf']['parse_job']['id']
        response=client.post(f'/api/jobs/{identity}/retry');assert response.status_code==200
        assert next(r for r in client.get('/api/documents').json() if r['filename']=='retry.pdf')['parse_job']['status']=='queued'
        worker.execute(store.claim(),store,config)
        assert store.job(identity)['status']=='succeeded' and len(store.jobs())==3
        assert attempts=={'before.pdf':1,'retry.pdf':2,'after.pdf':1}
        assert all(r['approved_count']==0 and r['candidate_count']>0 for r in client.get('/api/documents').json())
        assert any(e['error'].get('code')=='parse_error' for e in store.events(identity))


def test_document_status_not_limited_to_latest_hundred_jobs_or_documents(portal):
    client,store,_=portal
    first=client.post('/api/documents',files={'file':('first.pdf',pdf_bytes(1),'application/pdf')}).json()
    store.progress(first['parse_job']['id'],'parsing',status='failed',error={'code':'parse_error','message':'合成旧任务错误'})
    for i in range(105):store.register_document(f'{i:064x}',f'synthetic-{i}.pdf',f'raw_pdf/{i}.pdf',1)
    assert first['parse_job']['id'] not in {j['id'] for j in store.jobs()}
    rows=client.get('/api/documents').json();assert len(rows)==106
    row=next(r for r in rows if r['id']==first['document_id'])
    assert row['parse_job']['id']==first['parse_job']['id'] and row['parse_job']['error']['message']=='合成旧任务错误'
