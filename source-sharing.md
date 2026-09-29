# 源码分享与Dify工作流同步

## 交付内容

保留 app、config、deploy、docs、evals、fixtures、ingestion、prompts、templates、tests、workflows，及README、AGENTS、CONTRIBUTING、架构指南、pyproject.toml、uv.lock、.env.example与Git/Docker忽略规则。历史safety-assessment.yml仍有测试依赖，不作为新门户导入文件。

不分享.env.portal、其他个人环境文件、data、虚拟环境、缓存、模型权重、PDF、照片、报告或诊断包。.gitignore不会自动影响手工压缩；从明确源码清单生成ZIP。当前目录无.git，无提交/历史审计结论。

## 页面下载为什么不需要链接导出文件

下载端点 /api/setup/workflow.yml 调用 workflows/build_portal.py，以当前已应用配置生成DSL，供本实例导入。文件叫什么名字不影响这一机制。网页导出只用于核对；有效代码、提示词、Schema必须回写生成器相关源文件。网页端改动不会自动同步。

2026-09-28导出核对结果：两个LLM均为OpenAI-API-compatible的qwen3-vl-flash，temperature=0.1，视觉开启、读取start.images，结构化输出开启；checks读取vision.structured_output。提示词正文、Schema及Code节点与本地一致，提示词对象仅编辑器元数据不同；补充导出的0.0.68插件依赖。没有采用DeepSeek测试时的text回退模式。

导出含非空EVIDENCE_API_TOKEN，原导出不得直接分享。公共模板Secret为空，模型按接收者配置生成，知识库、HTTPS不复制个人值。导出中的retrieval.dataset_ids与本机生成结果不同；可能涉及Dify内部表示或实例差异，未盲目覆盖，仍以接收者自己的知识库绑定与真实检索验收为准。

## 接收者步骤

1. 按README安装、启动并打开本地门户。
2. 自建Dify专用知识库与应用，配置模型及密钥，启用本机证据HTTPS入口。
3. 如复现本轮千问配置，两个LLM使用百炼qwen3-vl-flash，通过OpenAI-API-compatible插件；本地提供方/模型同步后保存应用。嵌入模型填写自己的知识库实际配置。
4. 下载当前已应用配置的DSL，导入专用工作流，核对模型、知识库、版本过滤及环境变量，绑定本机证据Secret，发布API并关闭公开Web App。不要互相覆盖同一个应用的知识库或证据地址。
5. 人工复核路径见portal-runbook，自动批量路径见batch-runbook。完成发布后上传图片，并在单输入框说明设备与问题。
6. 真实运行检查节点输出、检索条款、最终报告；不能只看技术校验通过。本轮已知案例中4.3.1未入发布快照，且模型对4.5关键操作要求有遗漏；完整覆盖和业务准确性仍需验证。

本次代码同步不改变任何已发布Dify应用，不自动更新个人云端配置，也不重新调用付费模型。源码包不预置知识库。
