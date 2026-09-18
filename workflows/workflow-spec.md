# Workflow 交接规格（阶段 D，未实施）

当前阶段 A～C 只交付接口和入库工具。尚无可导入、已实测的 DSL，因此不创建 `safety-assessment.yml`。

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

所有 HTTP 节点绑定管理员配置的 `http://evidence-api:8000` 与秘密 Bearer 变量。密钥不写入导出文件。
接入官方 Docker 网络后，必须从 Dify HTTP 节点执行 `/health`；宿主机测试不能替代此验收。
Knowledge API 的 records[].segment 不适用于 Workflow 节点。阶段 D 必须保存真实节点输出 fixture、绑定视觉文件与模型／知识库，导入和运行通过后再导出 DSL。
