"""全部使用合成标准；批量批准是软件测试，不是业务人工复核记录。"""
import hashlib
from copy import deepcopy
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.errors import DomainError
from app.portal import assistance, review
from app.portal.main import create_app
from app.repository import digest, Repository
from ingestion.build_clauses import candidates
from test_portal_review import parsed, metadata

ACK = ["text", "boundary", "context", "assets", "scope"]


def prepared(parsed):
    config, store, doc = parsed
    return config, store, {**doc, "payload": review.update_metadata(doc["payload"], metadata())}


def test_cover_prefill_is_traceable_and_never_invents_status_or_approval(parsed):
    config, _, doc = parsed
    payload = deepcopy(doc["payload"])
    page = payload["normalized"]["pages"][0]
    page["blocks"] += [
        {"block_id":"cover-id","block_type":"text","text":"GB/T 12345—2026","asset_refs":[],"review_issues":[]},
        {"block_id":"cover-title","block_type":"doc_title","text":"合成测试标准 防护要求","asset_refs":[],"review_issues":[]}]
    payload["candidates"][0]["record"]["text_verbatim"] = "1 范围\n仅为合成测试。"
    before = digest(payload)
    data = assistance.analyze({**doc,"payload":payload}, config.data_root)
    values = data["metadata_draft"]["values"]
    assert values == {"standard_code":"GB/T 12345-2026", "edition":"2026", "standard_name":"合成测试标准 防护要求", "scope":"仅为合成测试。"}
    assert data["metadata_draft"]["provenance"]["standard_code"]["page"] == 1
    assert not {"standard_status","status_verified_at","status_source"} & values.keys()
    assert digest(payload) == before
    assert all(i["record"]["content_review_status"] == "pending" for i in payload["candidates"])


def test_bare_heading_recovers_hierarchy_without_splitting_table_numbers(parsed):
    config, _, doc = parsed
    norm = deepcopy(doc["payload"]["normalized"])
    source = deepcopy(norm["pages"][0]["blocks"][0])
    source.update(block_id="heading", block_type="paragraph_title", text="5.3")
    body = {**source,"block_id":"body","block_type":"text","text":"【合成测试】防护要求。"}
    table = {**source,"block_id":"table","block_type":"table","text":"1 表内序号不应变成条款"}
    norm["pages"][0]["blocks"] = [source,body,table]
    norm["pages"] = norm["pages"][:1]
    items = candidates(norm,config.data_root)
    assert len(items)==1 and items[0]["clause_path"]==["5","5.3"]
    assert "表内序号" in items[0]["text_verbatim"]


@pytest.mark.parametrize("fault,code", [("missing","missing_pages"),("duplicate","number_duplicate"),
    ("gap","number_sequence"),("parent","parent_missing"),("crosspage","cross_page_join"),
    ("asset","asset_missing"),("numeric","numeric_ocr"),("figure","figure_reference"),("fragment","sentence_fragment"),("number_ocr","number_ocr")])
def test_rule_issues_are_visible_and_not_bulk_eligible(parsed, fault, code):
    config, _, doc = prepared(parsed)
    payload = doc["payload"]
    first, second = payload["candidates"]
    if fault=="missing": payload["normalized"].update(full_document_covered=False, missing_pages=[1])
    elif fault=="duplicate": second["record"].update(clause_no="1",clause_path=["1"])
    elif fault=="gap": second["record"].update(clause_no="4",clause_path=["4"])
    elif fault=="parent": second["record"].update(clause_no="5.2",clause_path=["5","5.2"])
    elif fault=="crosspage": second["record"]["source_spans"] += first["record"]["source_spans"]
    elif fault=="asset": payload["normalized"]["pages"][1]["blocks"][0]["review_issues"]=["missing_asset:lost.png"]
    elif fault=="numeric": second["record"]["text_verbatim"] += "间距不大于1O mm。"
    elif fault=="figure": second["record"]["text_verbatim"] += "参见图8。"
    elif fault=="number_ocr": payload["normalized"]["pages"][1]["blocks"][0].update(block_type="paragraph_title",text="2,1")
    else: second["record"]["text_verbatim"] += "条件（不得遗漏。"
    data = assistance.analyze(doc,config.data_root)
    row = data["rows"][1]
    assert any(x["code"]==code for x in row["issues"]+data["document_checks"])
    assert row["group"]=="exception"
    with pytest.raises(DomainError):
        review.batch_review(payload,[second["id"]],"synthetic-reviewer",ACK,config.data_root,data,"approve_batch")


def test_batch_context_and_approval_reuse_all_original_guards(parsed):
    config, _, doc = prepared(parsed)
    before=digest(doc["payload"]); ids=[i["id"] for i in doc["payload"]["candidates"]]
    data=assistance.analyze(doc,config.data_root)
    assert data["rows"][1]["context_needs_confirmation"]
    with pytest.raises(DomainError,match="上下文建议"):
        review.batch_review(doc["payload"],ids,"synthetic-reviewer",ACK,config.data_root,data,"approve_batch")
    assert digest(doc["payload"])==before
    payload=review.batch_review(doc["payload"],ids,"synthetic-reviewer",[],config.data_root,data,"apply_context")
    assert all(i["record"]["content_review_status"]=="pending" for i in payload["candidates"])
    data=assistance.analyze({**doc,"payload":payload},config.data_root)
    with pytest.raises(DomainError): review.batch_review(payload,ids,"synthetic-reviewer",[],config.data_root,data,"approve_batch")
    approved=review.batch_review(payload,ids,"synthetic-reviewer",ACK,config.data_root,data,"approve_batch")
    assert all(i["record"]["content_review_status"]=="approved" for i in approved["candidates"])
    assert approved["candidates"][1]["record"]["context_clause_uids"]==[approved["candidates"][0]["record"]["clause_uid"]]


def test_new_file_diff_tracks_transitive_dependents_and_does_not_inherit_approval(parsed):
    config, _, doc = prepared(parsed)
    old=deepcopy(doc["payload"])
    third=deepcopy(old["candidates"][1]); third["id"]="candidate_3";third["record"].update(clause_no="3",clause_path=["3"])
    review.identify(third["record"]);old["candidates"].append(third)
    old["candidates"][1]["record"]["context_clause_uids"]=[old["candidates"][0]["record"]["clause_uid"]]
    for i in old["candidates"]: i["record"]["content_review_status"]="approved"
    new=deepcopy(old)
    for i in new["candidates"]: review.pending(i["record"])
    new["candidates"][0]["record"]["text_verbatim"] += "【合成变更】"
    baseline={**doc,"id":"old-file","payload":old}
    changed={**doc,"id":"new-file","payload":new,"sha256":"b"*64}
    result=assistance.analyze(changed,config.data_root,[baseline])
    assert [r["diff"]["status"] for r in result["rows"]]==["modified","dependency_affected","unchanged"]
    assert all(i["record"]["content_review_status"]=="pending" for i in new["candidates"])
    assert result["rows"][2]["diff"]["previous_approved"]
    new["candidates"].pop(0)
    diffs,removed=assistance.comparison(new,old)
    assert removed[0]["clause_no"]=="1" and diffs[new["candidates"][0]["id"]]["status"]=="dependency_affected"


def test_batch_api_is_atomic_and_draft_cases_require_confirmation(parsed):
    config, store, doc = prepared(parsed)
    config=replace(config, knowledge_api_key="synthetic-key",dataset_id="synthetic-dataset")
    store.save_document(doc["id"],doc["revision"],doc["payload"],"pending_review","metadata","synthetic-reviewer")
    with TestClient(create_app(config),base_url=config.origin) as client:
        token=client.get('/api/status').json()['csrf_token']
        client.headers.update({'Origin':config.origin,'X-CSRF-Token':token})
        doc=client.get('/api/documents/'+doc['id']).json()
        ids=[i['id'] for i in doc['payload']['candidates']]
        body={'revision':doc['revision'],'review_hash':doc['assistance']['review_hash'],'candidate_ids':ids,'actor':'synthetic-reviewer','acknowledgements':ACK}
        stale=client.post('/api/documents/'+doc['id']+'/review/approve_batch',json={**body,'review_hash':'outdated'})
        assert stale.status_code==409 and store.document(doc['id'])['revision']==doc['revision']
        applied=client.post('/api/documents/'+doc['id']+'/review/apply_context',json=body)
        assert applied.status_code==200,applied.text
        updated=applied.json();body.update(revision=updated['revision'],review_hash=updated['assistance']['review_hash'])
        approved=client.post('/api/documents/'+doc['id']+'/review/approve_batch',json=body)
        assert approved.status_code==200,approved.text
        preview=client.post('/api/releases/preview',json={'document_ids':[doc['id']]}).json()
        draft=preview['case_draft'];assert draft['requires_confirmation']
        assert all(len(r['query'])<=250 for r in draft['cases'])
        release={'document_ids':[doc['id']],'preview_hash':preview['preview_hash'],'actor':'synthetic-reviewer','cases':draft['cases'],'case_draft_id':draft['id']}
        rejected=client.post('/api/releases',json=release)
        assert rejected.status_code==422 and not any(j['kind']=='publish' for j in store.jobs())
        missing_source=client.post('/api/releases',json={**release,'case_draft_id':''})
        assert missing_source.status_code==422 and not any(j['kind']=='publish' for j in store.jobs())
        allowed=client.post('/api/releases',json={**release,'confirmed_case_ids':[r['case_id'] for r in draft['cases']]})
        assert allowed.status_code==200,allowed.text  # 只入本机队列，不运行远程worker。
        assert store.job(allowed.json()['id'])['payload']['case_review']['source']=='rule_draft_confirmed'
        before=store.document(doc['id'])
        # 合成fixture初始登记用的占位hash改为真实字节hash，以验证去重保留批准和审计。
        source=config.data_root/before['source_path'];checksum=hashlib.sha256(source.read_bytes()).hexdigest()
        with store.connect(write=True) as conn:conn.execute('UPDATE documents SET sha256=? WHERE id=?',(checksum,doc['id']))
        reused=client.post('/api/documents',files={'file':('renamed.pdf',source.read_bytes(),'application/pdf')}).json()
        assert reused['reused'] and reused['document_id']==doc['id']
        after=store.document(doc['id']);assert after['revision']==before['revision'] and after['payload']==before['payload']
        original=source.read_bytes();source.write_bytes(b'changed archive')
        response=client.post('/api/documents',files={'file':('same.pdf',original,'application/pdf')})
        assert response.status_code==409 and response.json()['error']['code']=='source_archive_changed'


def test_source_mutation_reading_order_and_cyclic_suggestions_are_not_normal(parsed):
    config, _, doc = prepared(parsed)
    payload=doc['payload']
    source=config.data_root/doc['source_path'];source.write_bytes(b'altered after parsing')
    blocked=assistance.analyze(doc,config.data_root)
    assert all(r['hard_blocked'] for r in blocked['rows'])
    assert blocked['document_checks'][0]['code']=='source_archive_changed'
    payload['normalized'].pop('source_file_sha256')  # 以下为独立合成阅读顺序用例。
    page=payload['normalized']['pages'][0]
    other={**page['blocks'][0],'block_id':'p0_b2'}
    page['blocks'].insert(0,other)
    payload['candidates'][0]['record']['source_spans'][0]['block_ids'].insert(0,'p0_b2')
    data=assistance.analyze(doc,config.data_root)
    assert any(v['code']=='reading_order' for v in data['rows'][0]['issues'])
    a,b=payload['candidates']
    a['record'].update(clause_no='5.1',clause_path=['5','5.1'],text_verbatim='5.1 合成要求\n参见5.2。')
    b['record'].update(clause_no='5.2',clause_path=['5','5.2'],text_verbatim='5.2 合成要求\n参见5.1。')
    data=assistance.analyze(doc,config.data_root)
    assert all(any(v['code']=='context_cycle_suggestion' for v in r['issues']) for r in data['rows'])
    assert all(r['group']=='exception' for r in data['rows'])


def test_prefill_uses_existing_standard_identity_spelling_without_copying_approval(parsed):
    config,_,doc=prepared(parsed)
    old=deepcopy(doc)
    old.update(id='previous-file')
    old['payload']['metadata'].update(standard_code='GB/T12345—2026',edition='2026')
    old['payload']['candidates'][0]['record']['content_review_status']='approved'
    current=deepcopy(doc);current['payload']['metadata']={}
    current['payload']['normalized']['pages'][0]['blocks'][0]['text']='GB/T 12345-2026'
    data=assistance.analyze(current,config.data_root,[old])
    assert data['metadata_draft']['values']['standard_code']=='GB/T12345—2026'
    assert not current['payload']['metadata']
    assert all(i['record']['content_review_status']=='pending' for i in current['payload']['candidates'])


def test_questions_do_not_assume_headings_are_answers_and_are_bounded(parsed):
    _,_,doc=prepared(parsed)
    row=doc['payload']['candidates'][0]['record']
    headings=[{**row,'clause_uid':f'heading_{i}','text_verbatim':f'{i+1} 合成章节标题'} for i in range(101)]
    assert assistance.retrieval_drafts({'preview_hash':'synthetic','records':headings})['cases']==[]
    records=[{**row,'clause_uid':f'clause_{i}'} for i in range(102)]
    draft=assistance.retrieval_drafts({'preview_hash':'synthetic','records':records})
    assert len(draft['cases'])==100 and draft['truncated']
    assert len({r['case_id'] for r in draft['cases']})==100


def test_verification_timestamp_is_not_a_text_change_but_scope_affects_every_clause(parsed):
    _,_,doc=prepared(parsed)
    original=deepcopy(doc['payload'])
    doc['payload']['metadata']['status_verified_at']='2026-09-21'
    changes,_=assistance.comparison(doc['payload'],original)
    assert all(r['status']=='unchanged' for r in changes.values())
    doc['payload']['metadata']['scope']='Changed synthetic scope'
    changes,_=assistance.comparison(doc['payload'],original)
    assert all(r['status']=='modified' and 'metadata' in r['fields'] for r in changes.values())


def test_missing_context_link_prefers_selected_new_file_over_old_approved_file(parsed):
    config,store,old=prepared(parsed)
    first,second=old['payload']['candidates']
    second['record']['context_clause_uids']=[first['record']['clause_uid']]
    old['payload']=review.approve(old['payload'],first['id'],'synthetic-reviewer',ACK,config.data_root)
    store.save_document(old['id'],old['revision'],old['payload'],'pending_review','approve','synthetic-reviewer')
    new,_=store.register_document('b'*64,'new-synthetic.pdf',old['source_path'],old['page_count'])
    payload=deepcopy(old['payload']);review.pending(payload['candidates'][0]['record'])
    payload=review.approve(payload,second['id'],'synthetic-reviewer',ACK,config.data_root)
    store.save_document(new['id'],new['revision'],payload,'pending_review','approve','synthetic-reviewer')
    evidence=Repository(config.evidence_settings().db_path);evidence.initialize()
    preview=review.release_preview(store,evidence,[new['id']])
    missing=next(r for r in preview['blockers'] if r['code']=='missing_context')
    assert missing['document_id']==new['id'] and missing['candidate_id']==first['id']


def structure_fixture(parsed):
    config,store,doc=prepared(parsed)
    payload=doc['payload'];parent,dependent=payload['candidates'];page=payload['normalized']['pages'][0]
    for bid,kind,text in [('p0_b1','paragraph_title','1.1'),('p0_b2','text','【合成测试】独立子条款要求。')]:
        page['blocks'].append(dict(block_id=bid,block_type=kind,text=text,bbox=None,asset_refs=[],review_issues=[]))
        parent['record']['source_spans'].append({**parent['record']['source_spans'][0],'block_ids':[bid]})
    parent['record']['text_verbatim']='\n'.join(b['text'] for b in page['blocks'])
    independent=deepcopy(dependent);independent['id']='independent'
    independent['record'].update(clause_no='3',clause_path=['3'],text_verbatim='3 【合成测试】独立条款。')
    independent['record']['source_spans'][0]['block_ids']=['p1_b1'];review.identify(independent['record'])
    payload['normalized']['pages'][1]['blocks'].append(dict(block_id='p1_b1',block_type='text',text=independent['record']['text_verbatim'],bbox=None,asset_refs=[],review_issues=[]))
    payload['candidates'].append(independent)
    for p,c in zip(payload['normalized']['pages'],payload['normalized']['coverage']):c['block_count']=len(p['blocks'])
    dependent['record']['context_clause_uids']=[parent['record']['clause_uid']]
    for item in payload['candidates']:item['record']['is_test_fixture']=True
    for item in (dependent,independent):payload=review.approve(payload,item['id'],'synthetic-reviewer',ACK,config.data_root)
    return config,store,{**doc,'payload':payload}


@pytest.mark.parametrize('protected',['approval','text','notes','context'])
def test_structure_suggestions_never_overwrite_reviewed_or_edited_content(parsed,protected):
    config,_,doc=structure_fixture(parsed);item=doc['payload']['candidates'][0]
    if protected=='approval':item['record']['content_review_status']='approved'
    elif protected=='text':item['record']['text_verbatim']+='人工更正'
    elif protected=='notes':item['record']['review_notes']='人工待核对记录'
    else:item['context_reviewed']=True
    data=assistance.analyze(doc,config.data_root)
    proposal=data['rows'][0]['structure_proposal']
    assert proposal and not proposal['eligible']
    with pytest.raises(DomainError):review.reorganize_candidate(doc['payload'],item['id'],proposal)


def test_structure_application_preserves_sources_and_only_invalidates_dependents(parsed):
    config,store,doc=structure_fixture(parsed)
    original=deepcopy(doc['payload']);parent=original['candidates'][0]
    doc=store.save_document(doc['id'],doc['revision'],doc['payload'],'pending_review','synthetic_fixture','synthetic-reviewer')
    with TestClient(create_app(config),base_url=config.origin) as client:
        token=client.get('/api/status').json()['csrf_token'];client.headers.update({'Origin':config.origin,'X-CSRF-Token':token})
        data=client.get('/api/documents/'+doc['id']).json()
        proposal=data['assistance']['rows'][0]['structure_proposal'];assert proposal['eligible'] and len(proposal['parts'])==2
        body={'revision':data['revision'],'review_hash':data['assistance']['review_hash'],'actor':'synthetic-reviewer'}
        url=f"/api/documents/{doc['id']}/candidates/{parent['id']}/organize"
        result=client.post(url,json=body);assert result.status_code==200,result.text
        items=result.json()['payload']['candidates']
        assert [i['record']['clause_no'] for i in items]==['1','1.1','2','3']
        assert [i['record']['content_review_status'] for i in items]==['pending','pending','pending','approved']
        assert items[3]==original['candidates'][2]
        assert [bid for i in items[:2] for span in i['record']['source_spans'] for bid in span['block_ids']]==[bid for span in parent['record']['source_spans'] for bid in span['block_ids']]
        assert all(i['record']['is_test_fixture'] for i in items)
        assert client.post(url,json=body).status_code==409


def test_unassigned_prefix_can_be_organized_but_cannot_be_approved(parsed):
    config,store,doc=structure_fixture(parsed)
    payload=doc['payload'];parent=payload['candidates'][0];page=payload['normalized']['pages'][0]
    page['blocks'][0]['text']='【合成封面前缀】';page['blocks'][1]['text']='1'
    parent['record'].update(clause_no='unassigned_p0',clause_path=['unassigned_p0'],text_verbatim='\n'.join(b['text'] for b in page['blocks']),boundary_status='unknown')
    review.identify(parent['record'])
    payload['candidates'][1]['record']['context_clause_uids']=[parent['record']['clause_uid']]
    doc=store.save_document(doc['id'],doc['revision'],payload,'pending_review','synthetic_fixture','synthetic-reviewer')
    with TestClient(create_app(config),base_url=config.origin) as client:
        token=client.get('/api/status').json()['csrf_token'];client.headers.update({'Origin':config.origin,'X-CSRF-Token':token})
        data=client.get('/api/documents/'+doc['id']).json();row=data['assistance']['rows'][0]
        assert row['hard_blocked'] and not row['structure_blocked'] and row['structure_proposal']['eligible']
        base=f"/api/documents/{doc['id']}/candidates/{parent['id']}"
        body={'revision':doc['revision'],'actor':'synthetic-reviewer','acknowledgements':ACK,'review_hash':data['assistance']['review_hash']}
        assert client.post(base+'/approve',json=body).status_code==422
        response=client.post(base+'/organize',json=body);assert response.status_code==200,response.text
        assert response.json()['payload']['candidates'][0]['record']['boundary_status']!='confirmed'
        assert response.json()['payload']['candidates'][1]['record']['clause_no']=='1'
