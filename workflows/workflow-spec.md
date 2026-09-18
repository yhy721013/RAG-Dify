# Workflow 实施规格（阶段 D，真实闭环待验收）

阶段 D 已获用户明确授权。固定观察17节点已在 Dify Cloud 跑通检索、证据准备、定稿和报告输出的完整HTTP闭环；完整视觉19节点已恢复为未发布草稿。真实图片与多模态模型闭环仍未验收，因此不创建最终 `safety-assessment.yml`，视觉候选继续标记 untested。

工作台草稿名称为“机械设备安全评估（阶段D）”，未发布；应用标识和本地候选哈希保存在 data/workflows/，不作为公共访问凭据。

| 节点 | 输入 | 输出／约束 |
|---|---|---|
| User Input | 1～4 张 JPEG/PNG、设备类型、说明、工况、同设备确认 | 未确认同一设备即终止；每张建议 5 MiB 上限 |
| 输入整理 | 文件列表 | request_id、image_manifest、equipment_id |
| 视觉模型 | 有序原图、工况、prompts/vision_observation.md | observations；无法辨认／范围异常即停止 |
| 检查项整理 | observations、config/checklist.json | 最多 6 项 checks；清单未复核不运行 |
| 串行 Iteration | 每项 query | 固定当前 dataset 的检索结果；失败终止 |
| 检索适配 | result[].metadata | dataset_id、document_id、segment_id、score；参见 app/dify_client.py 的 workflow_hits |
| HTTP prepare | config/prepare.schema.json | POST /evidence/prepare，保存完整证据副本 |
| 响应解包 | HTTP 状态码与 body | 非 2xx 终止，解析 JSON 后取 context_id 和 evidence |
| 评估模型 | 同一有序原图、观察、允许证据、prompts/risk_assessment.md | 仅输出 config/finalize.schema.json 的字段 |
| HTTP finalize | context_id、findings | POST /reports/finalize，失败终止 |
| Output | 服务端结果 | report_id、markdown、validation；不能返回未经校验的模型文本 |

## 实际节点及变量映射

节点实现为 workflows/nodes.py 的纯标准库函数；候选生成器嵌入源码及显式 main 包装，不依赖工作区模块在 Dify 沙箱中可导入。

| 节点ID | 主要输入选择器 | 输出 |
|---|---|---|
| start | 用户表单 | images、equipment_type、equipment_description、operating_state、work_context、same_equipment_confirmed |
| health / health_gate | env.EVIDENCE_API_BASE_URL | /health必须200且status=ok；否则终止 |
| validate_input | start各字段、sys.workflow_run_id、env配置 | request_json、image_manifest_json、equipment_context_json、checklist_json |
| vision | 同一份 start.images；输入清单、工况与固定检查方向 | structured_output，遵循 config/vision.schema.json |
| checks | vision.structured_output、validate_input.request_json、env.CHECKLIST_JSON | request_json、observations_json、checks（array[string]）、checks_json |
| iteration | checks.checks | 串行；error_handle_mode=terminated；不移除失败结果 |
| query | iteration.item | query，不超过250字符 |
| retrieval | query.query；当前试点dataset | result；Hybrid Search，0.5/0.5，Top-5 |
| adapt_hits | iteration.item、retrieval.result、env.DATASET_ID | check_result_json，仅保留真实ID和score |
| prepare_body | checks.request_json、iteration.output | body；检查项必须完整且一一对应 |
| prepare_http | prepare_body.body、管理员URL／Bearer变量 | /evidence/prepare 的 status_code / body |
| unpack_evidence | prepare_http状态和body、原始请求 | context_id、context_json、evidence_json；身份和检查项不一致即终止 |
| assessment | 同一份 start.images、观察、检查项和完整证据 | structured_output，遵循 config/assessment-draft.schema.json |
| finalize_body | unpack_evidence.context_json、assessment.structured_output | 由代码绑定context_id，模型只提交findings |
| finalize_http | finalize_body.body、管理员URL／Bearer变量 | /reports/finalize 的 status_code / body |
| unpack_report / end | finalize_http状态和body、可信context_id | 仅输出保存后的report_id、Markdown和validation_json |

两个 LLM 的 vision.configs.variable_selector 均为 `[start, images]`。Code 仅从原生 File.to_dict 元数据读取 type、transfer_method、related_id、mime_type、size；不把图片转成字符串，不访问文件系统、SQLite或网络。原生文件格式参考 Dify 1.17.1 所用 graphon 0.7.0，仍需实拍运行确认云实例实际输入。

输入必须为1～4张本地上传的JPEG/PNG，每张≤5 MiB；用户未确认同设备、设备类型与清单不一致、图片未知／重复标识均拒绝。模型判定不同设备、无法辨认或范围不明也会终止。未能观察到的固定检查项用“需补图／现场检查”保留，不自动变成不存在或无风险。

阶段 D 向 prepare 契约新增可选追溯字段：equipment_type、equipment_description、operating_state、work_context、same_equipment_confirmed、workflow_version、model_id。原有必填字段和四个接口不变；空可选字段从哈希中排除，兼容旧请求的幂等记录。

## 候选生成与导入

```powershell
.\.venv\Scripts\uv.exe run python -m workflows.build_candidate --mode fixed --output data/workflows/fixed-observation.candidate.yml
.\.venv\Scripts\uv.exe run python -m workflows.build_candidate --mode vision --output data/workflows/safety-assessment.candidate.yml --model Qwen/Qwen2.5-VL-32B-Instruct
```

输出为JSON形式的合法YAML，结构来自固定版本的官方DSL/节点模型，不新增YAML依赖。当前参考DSL版本0.7.0；两种候选均已在本轮云实例成功导入。生成器拒绝直接写最终 safety-assessment.yml。
fixed 模式仅使用明确标记为软件联通测试的固定观察和固定结果，不能作为真实设备评估；vision 模式才包含真实视觉与评估节点。初始全链路未通过前不要发布应用。

管理员需绑定 EVIDENCE_API_BASE_URL、EVIDENCE_API_TOKEN（Secret）、SNAPSHOT_ID、DATASET_ID、CHECKLIST_JSON、WORKFLOW_VERSION、MODEL_ID。常规候选和最终交付文件中的密钥始终为空；环境变量值不写进用户输入或模型提示词。模型ID环境变量必须与两个LLM节点实际模型一致。
本轮已取得用户对该服务密钥及当前Dify工作流的明确授权，通过一次性本地配置载荷绑定Secret；两份载荷均在导入成功后删除，不纳入Git，也未把密钥输出到聊天或写入模型提示词。普通候选生成器仍不写密钥。重新导入无密钥候选时需保留或重新绑定Secret，不能以界面的星号显示判断鉴权是否有效。
目前设备类别和6项检查清单为 pending 草案，不能用于真实评估。候选暂绑定当前工作区已显示支持VISION的 Qwen/Qwen2.5-VL-32B-Instruct，尚未实测模型调用；可按用户选择调整。

当前候选 URL 默认 `http://evidence-api:8000` 只适用于接入同一网络的自建 Dify。当前使用 Dify Cloud，必须改为管理员提供且受控可达的 HTTPS 服务地址；不要假定云节点能访问本机或容器主机名。
无论采用哪种部署，都必须从 Dify HTTP 节点执行 `/health`；宿主机测试不能替代此验收。本轮通过用户配置的Quick Tunnel已完成该验证，TLS校验保持开启。临时地址与进程记录在data/quick_tunnel/runtime.json，重启分配新地址后需更新Dify环境变量并重新验证。
固定观察测试的 /evidence/prepare、/reports/finalize 均由Dify HTTP节点实际调用，最终Markdown哈希与SQLite保存版本一致。完整运行时，这两个接口及响应校验均不可绕过。该结果未使用真实照片或生成模型，不能替代视觉工作流验收。
真实 Workflow 检索 fixture 已保存为 fixtures/dify_workflow_retrieval.real.json，与 Knowledge API records[].segment 分开适配。实拍、多图片关联、模型结构化输出和最终服务端报告全部验证后，才交付正式 DSL。
