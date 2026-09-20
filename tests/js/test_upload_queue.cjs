// 浏览器上传队列的纯状态/拖放事件测试，不启动浏览器或访问网络。
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname,"../../app/static/portal-upload.js"),"utf8"),context);
const create = context.createPdfUploadQueue;
const file = (name,size=8,content=name) => ({name,size,content});
const job = (id,status,time="2026-09-20T00:00:00.123450+00:00") => ({id,status,stage:"parsing",updated_at:time,error:status==="failed"?{code:"parse_error",message:"合成解析失败"}:{}});
const receipt = (id,reused=false,status="queued") => ({document_id:id,reused,parse_job:job("job_"+id,status)});
const deferred = () => {let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};

(async()=>{
  let active=0,maxActive=0,fail=true;const sent=[];
  const q=create({upload:async f=>{active++;maxActive=Math.max(maxActive,active);sent.push(f.name);await Promise.resolve();active--;if(f.name==="bad.pdf"&&fail){fail=false;throw new Error("synthetic HTTP failure");}return receipt(f.content,f.name==="renamed.pdf");},retry:async()=>{} });
  q.addFiles([file("one.pdf"),file("bad.pdf"),file("two.pdf")]);
  const first=q.start();assert.equal(q.rows[0].phase,"uploading");await q.start();await first;
  assert.deepEqual(Array.from(q.rows,r=>r.phase),["received","upload_failed","received"]);
  assert.equal(maxActive,1);assert.equal(q.rows[0].file,null);assert.equal(q.hasLocalFiles(),true);
  await q.retryUpload(q.rows[1].id);assert.deepEqual(sent,["one.pdf","bad.pdf","two.pdf","bad.pdf"]);
  assert.equal(q.hasLocalFiles(),false);
  q.addFiles([file("renamed.pdf",8,"one.pdf"),file("one.pdf",8,"different bytes")]);await q.start();
  assert.equal(q.rows[3].document_id,q.rows[0].document_id);assert.equal(q.rows[3].reused,true);
  assert.notEqual(q.rows[4].document_id,q.rows[0].document_id); // 不按文件名/大小去重。
  q.updateDocuments([{id:"one.pdf",revision:1,approved_count:7,candidate_count:9,parse_job:job("job_one.pdf","succeeded")}]);
  assert.equal(q.rows[3].document.approved_count,7);q.clearCompleted();assert.equal(q.rows.length,3);

  let calls=0;
  const limits=create({upload:async()=>{calls++;return receipt("valid");}},()=>{},()=>({max_pdf_bytes:10}));
  limits.addFiles([file("a.txt"),file("empty.pdf",0),file("huge.pdf",11),file("ok.PDF",10)]);await limits.start();
  assert.equal(calls,1);assert.deepEqual(Array.from(limits.rows,r=>r.phase),["upload_failed","upload_failed","upload_failed","received"]);
  limits.remove(limits.rows[0].id);assert.equal(limits.rows.length,3);

  const wait=deferred();let retries=0;
  const parsing=create({upload:async()=>receipt("shared",true,"failed"),retry:async id=>{retries++;await wait.promise;return job(id,"queued","2026-09-20T00:00:00.123456+00:00");}});
  parsing.addFiles([file("a.pdf"),file("b.pdf")]);await parsing.start();
  const recovery=parsing.retryParse(parsing.rows[0].id);await parsing.retryParse(parsing.rows[1].id);
  assert.equal(retries,1);assert.equal(parsing.retryingJobs.size,1);wait.resolve();await recovery;
  assert.deepEqual(Array.from(parsing.rows,r=>r.parse_job.status),["queued","queued"]);
  parsing.updateDocuments([{id:"shared",revision:0,parse_job:job("job_shared","failed","2026-09-20T00:00:00.123451+00:00")}]);
  assert.equal(parsing.rows[0].parse_job.status,"queued"); // 较早轮询不能覆盖成功重试，包含同毫秒竞争。
  parsing.pollFailed({info:{code:"network_error",message:"synthetic offline"}});assert.ok(parsing.rows[0].sync_error);
  parsing.updateDocuments([{id:"shared",revision:1,parse_job:job("job_shared","succeeded","2026-09-20T00:00:01+00:00")}]);
  assert.equal(parsing.rows[0].sync_error,null);assert.equal(parsing.rows[1].parse_job.status,"succeeded");

  let lost=true;const ambiguous=create({upload:async()=>{if(lost){lost=false;throw Object.assign(new Error("response lost"),{info:{code:"network_error",message:"结果不明"}});}return receipt("existing",true);}});
  ambiguous.addFiles([file("unknown.pdf")]);await ambiguous.start();assert.equal(ambiguous.rows[0].phase,"upload_failed");
  await ambiguous.retryUpload(ambiguous.rows[0].id);assert.equal(ambiguous.rows[0].reused,true);

  const listeners={}, classes=new Set();let dropped=[];
  const zone={addEventListener:(name,fn)=>listeners[name]=fn,classList:{add:name=>classes.add(name),remove:name=>classes.delete(name)},contains:()=>false};
  context.bindPdfDropZone(zone,files=>dropped.push(...files));
  const event={dataTransfer:{types:["Files"],files:[file("drop1.pdf"),file("drop2.pdf")]},preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}};
  listeners.dragover(event);assert.ok(classes.has("dragging"));assert.equal(event.dataTransfer.dropEffect,"copy");
  listeners.drop(event);assert.equal(dropped.length,2);assert.equal(event.prevented,true);assert.equal(event.stopped,true);assert.equal(classes.size,0);
  listeners.drop({dataTransfer:{types:["text/plain"]},preventDefault(){throw new Error("text drag must not upload");}});assert.equal(dropped.length,2);
  console.log("PASS: sequential/partial failure/retry/deduplication/limits/stale polling/drag-drop");
})().catch(error=>{console.error(error);process.exitCode=1;});
