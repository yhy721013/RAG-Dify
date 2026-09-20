# 历史版本与底层接口

本页用于维护原A～D阶段试点，**不是新开发者的启动流程**。Windows开发者预览版从[README](../README.md)进入门户；所有新实例使用自己的资料、专用知识库、Workflow和密钥。

## 两个入口的区别

| 项目 | 当前门户（推荐） | 原阶段D单快照试点（历史） |
|---|---|---|
| 页面与服务 | 本机8001页面、独立8002证据服务、worker | 无门户；证据服务8000 |
| 配置与数据 | `.env.portal`、`data/portal` | `.env`、原`data`试点目录 |
| 工作流输入 | portal-v1，七个输入；后端固定snapshot_id | stage-d-v3，六个用户输入；管理员绑定SNAPSHOT_ID |
| 知识版本 | rag_snapshot_id元数据隔离、不可变累积版本 | 一个激活的试点快照 |
| 导入方式 | 从门户向导生成当前环境DSL | 管理员另行绑定并重新验收历史模板 |

[旧运行手册](runbook.md)和[阶段D工作流规格](../workflows/workflow-spec.md)保留实现/联调记录。其 `sample_*`、`pilot_*`、本机应用ID和 `data/` 路径是历史记录，资料与凭据没有随源码交付。既有成功结果不能代替新开发者的真实验证。

## 旧DSL的交付状态

`workflows/safety-assessment.yml`保留已验证的stage-d-v3节点代码与六输入结构，交付文件中的HTTPS、知识库和快照均已改为占位值，Secret为空。它**不能直接运行，也不兼容门户的七输入契约**。原已配置Dify应用未因源码文件变更而自动改变。

维护旧试点时须同时绑定：

- `EVIDENCE_API_BASE_URL`：自己的可达服务地址；Cloud不能访问本机127.0.0.1。
- `EVIDENCE_API_TOKEN`：自己的证据服务Secret；不要写入交付DSL。
- `SNAPSHOT_ID`：已在旧证据库激活且有映射的实际快照。
- `DATASET_ID` **和原生检索节点的dataset_ids**：同一个专用知识库。
- 两个模型节点、MODEL_ID、图片绑定与经人工确认的CHECKLIST_JSON：按实际环境核对。

原实测文件哈希保留在验收记录中；它不再是去实例绑定后的交付文件哈希。不能将替换占位值后的新环境声称为已验收。

## 四个证据接口

`GET /health`、`POST /evidence/prepare`、`POST /reports/finalize`、`GET /reports/{report_id}`保持原指南契约。除健康检查外需Bearer鉴权；报告保存包含确定性引用校验，GET回读来自数据库。

仅在明确维护旧入口时，才在项目根目录准备自己的 `.env` 并按旧手册初始化、导入人工批准条款、索引、自检和激活快照。单独服务的启动命令为：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m app.cli init-db
.\.venv\Scripts\python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

这些命令不启动门户，不应加入门户首次安装步骤。旧入口需要的自有PDF、人工批准条款、激活快照与映射不会由上述命令自动生成。
