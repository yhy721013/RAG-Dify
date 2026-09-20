"""全部使用合成标准；批量批准是软件测试，不是业务人工复核记录。"""
import hashlib
from copy import deepcopy
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.errors import DomainError
from app.portal import assistance, review
from app.portal.main import create_app
from app.repository import digest
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
    ("asset","asset_missing"),("numeric","numeric_ocr"),("figure","figure_reference"),("fragment","sentence_fragment")])
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
