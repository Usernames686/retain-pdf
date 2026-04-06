# Rust API 接口文档

本文档描述当前后端服务的实际接口契约，面向三类使用者：

- 前端接入方
- 本地部署与运维人员
- 需要排查任务失败原因的开发者

相关文档：

- [前端请求示例](/home/wxyhgk/tmp/Code/backend/rust_api/frontend_request_example.md)
- [OCR-only 服务文档](/home/wxyhgk/tmp/Code/backend/rust_api/MinerU_OCR_Service_API.md)
- [拆分版文档目录](/home/wxyhgk/tmp/Code/doc/API.md)

## 1. 服务概览

当前后端分为两层：

- Rust：对外 HTTP API、鉴权、任务排队、任务状态落库、OCR provider transport
- Python：OCR 标准化、翻译、渲染、PDF 产物生成

当前 Rust API 的内部职责边界也已经按模块拆开：

- `routes/jobs/`：按用例拆分的 HTTP endpoint 编排，当前分为 `create` / `query` / `download` / `control`
- `routes/job_requests.rs`：`multipart/form-data` 与表单字段解析
- `routes/job_helpers.rs`：路由层共用的 response / loader / 下载辅助逻辑
- `services/jobs/`：按用例拆分的业务入口，当前分为 `creation` / `query` / `control`
- `services/job_factory.rs`：统一的 job 构建与启动逻辑
- `services/job_validation.rs`：请求参数、provider、MinerU 限制校验

如果后续文档和代码不一致，以这些模块边界为准，而不是旧版“所有逻辑都堆在 `routes/jobs.rs` / `services/jobs.rs`”的描述。

主任务链路：

1. 上传 PDF
2. 创建主任务 `POST /api/v1/jobs`
3. 主任务内部创建 OCR 子任务 `{job_id}-ocr`
4. OCR 子任务完成后产出标准化 `document.v1.json`
5. 主任务继续翻译和渲染
6. 下载 PDF / Markdown / ZIP

默认端口：

- `41000`：完整 API
- `42000`：简便同步接口

基础路径：

- 健康检查：`GET /health`
- 业务前缀：`/api/v1`

## 2. 鉴权与配置

除 `GET /health` 外，其余接口默认都要求：

```http
X-API-Key: your-rust-api-key
```

注意区分两类密钥：

- `X-API-Key`：访问 Rust API 自身
- 请求体里的 `api_key`：访问下游模型服务

本地推荐配置文件：

- `backend/rust_api/auth.local.json`

示例：

```json
{
  "api_keys": ["replace-with-your-backend-key"],
  "max_running_jobs": 4,
  "simple_port": 42000
}
```

常用环境变量：

- `RUST_API_BIND_HOST`：监听地址，默认 `0.0.0.0`
- `RUST_API_PORT`：完整 API 端口，默认 `41000`
- `RUST_API_SIMPLE_PORT`：简便同步接口端口，默认 `42000`
- `RUST_API_KEYS`：后端允许的 API key 列表，逗号分隔
- `RUST_API_MAX_RUNNING_JOBS`：同时运行任务数，默认 `4`
- `RUST_API_DATA_ROOT`：数据根目录
- `RUST_API_UPLOAD_MAX_BYTES`：上传文件大小限制，单位字节；`0` 表示不限制
- `RUST_API_UPLOAD_MAX_PAGES`：上传页数限制；`0` 表示不限制
- `PYTHON_BIN`：Python 可执行文件，默认 `python`

配置优先级：

1. 代码默认值
2. 本地配置文件
3. 环境变量
4. 启动参数
5. 请求体白名单业务参数

请求体不能覆盖路径、端口、数据根目录等基础设施配置。

## 3. 存储约定

当前运行时以 `DATA_ROOT` 作为唯一数据根目录。默认是仓库下的 `data/`。

主要目录：

- `DATA_ROOT/uploads/`：上传文件
- `DATA_ROOT/jobs/{job_id}/`：任务工作目录
- `DATA_ROOT/downloads/`：下载缓存
- `DATA_ROOT/db/jobs.db`：SQLite

任务目录标准结构：

- `source/`
- `ocr/`
- `translated/`
- `rendered/`
- `artifacts/`
- `logs/`

数据库内部已拆分为：

- `jobs`：任务元信息、状态、错误、日志尾部
- `artifacts`：产物索引
- `job_artifact_entries`：按 `artifact_key` 建模的稳定产物清单，是下载与外部清单接口的真源
- `events`：结构化事件流

数据库与接口返回以相对路径为主，运行时再解析到真实文件。

## 4. 统一响应格式

成功：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

失败：

```json
{
  "code": 400,
  "message": "具体错误信息"
}
```

约定：

- `code = 0` 表示成功
- `message` 适合直接展示给前端用户
- 业务详情在 `data`

## 5. 主流程接口

### 5.1 上传 PDF

对应 Rust 输出类型：`UploadView`

`POST /api/v1/uploads`

`multipart/form-data` 字段：

- `file`：必填，PDF 文件
- `developer_mode`：可选，`true/false`

成功示例：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "upload_id": "20260402073151-a80618",
    "filename": "paper.pdf",
    "bytes": 1832451,
    "page_count": 18,
    "uploaded_at": "2026-04-02T07:31:55+08:00"
  }
}
```

当前上传限制：

- 默认不做额外上传大小 / 页数限制
- 如部署方设置了 `RUST_API_UPLOAD_MAX_BYTES` 或 `RUST_API_UPLOAD_MAX_PAGES`，则以上传接口返回的服务端校验结果为准
- `developer_mode` 仍会记录到上传元数据中，但不再承担“放宽上传限制”的职责

### 5.2 创建主任务

`POST /api/v1/jobs`

当前正式请求结构是分组后的 `CreateJobInput`。推荐请求体：

```json
{
  "workflow": "mineru",
  "source": {
    "upload_id": "20260402073151-a80618"
  },
  "ocr": {
    "provider": "mineru",
    "mineru_token": "mineru-xxxx",
    "model_version": "vlm",
    "language": "ch",
    "page_ranges": ""
  },
  "translation": {
    "mode": "sci",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-xxxx",
    "batch_size": 1,
    "workers": 50,
    "classify_batch_size": 12,
    "rule_profile_name": "general_sci",
    "custom_rules_text": ""
  },
  "render": {
    "render_mode": "auto",
    "compile_workers": 8
  },
  "runtime": {
    "timeout_seconds": 1800
  }
}
```

当前强制字段：

- `source.upload_id`
- `ocr.mineru_token` 或 `ocr.paddle_token`
- `translation.base_url`
- `translation.api_key`
- `translation.model`

当前校验规则：

- `translation.base_url` 必须以 `http://` 或 `https://` 开头
- `translation.api_key` 不能看起来像 URL
- 当 workflow / provider 走 MinerU 时，会额外校验 `200MB / 600 页` 限制

字段说明补充：

- `ocr.page_ranges`
  传给 OCR provider 的页码范围字符串，例如 `1-5`、`1,3,7-9`
- 当 `provider=mineru` 时，无论任务来源是：
  - `source.upload_id` 上传 PDF
  - `source.source_url` 远程 PDF URL
  后端都会继续把 `ocr.page_ranges` 透传给 MinerU
- 当任务来源是 `source.upload_id` 且 `ocr.page_ranges` 非空时：
  - 后端会先在任务工作目录生成一份子集 PDF
  - 实际上传给 MinerU 的是这份子集 PDF，不是原始整本 PDF
  - 后续标准化、翻译、渲染、`artifacts.source_pdf` 也都基于这份子集 PDF
- 如果为空字符串，则表示不限制页码范围，按 provider 默认行为处理

实现说明：

- JSON 请求按分组后的 `CreateJobInput` 严格解析
- `multipart` / 表单字段映射逻辑在 `routes/job_requests.rs`
- 创建任务前的 provider / URL / 页数 / 文件大小校验在 `services/job_validation.rs`
- 真正的 job 构造、命令拼装、持久化与启动在 `services/job_factory.rs`

对应 Rust 输出类型：`JobSubmissionView`

### 5.3 查询任务详情

`GET /api/v1/jobs/{job_id}`

对应 Rust 输出类型：`JobDetailView`

这是前端轮询的主接口。重点字段：

- `request_payload`
- `status`
- `stage`
- `stage_detail`
- `runtime`
- `progress`
- `timestamps`
- `actions`
- `artifacts`
- `ocr_job`
- `error`
- `failure`
- `failure_diagnostic`
- `normalization_summary`
- `log_tail`

内部命名对应：

- `runtime` -> `JobRuntimeInfo`
- `progress` -> `JobProgressView`
- `timestamps` -> `JobTimestampsView`
- `links` -> `JobLinksView`
- `actions` -> `JobActionsView`
- `artifacts` -> `ArtifactLinksView`
- `ocr_job` -> `OcrJobSummaryView`
- `failure` -> `JobFailureInfo`
- `failure_diagnostic` -> `JobFailureDiagnosticView`
- `normalization_summary` -> `NormalizationSummaryView`

说明：

- 前端应以 `status` 判断任务是否结束
- 前端应优先读取 `runtime.current_stage` 理解当前运行阶段
- 失败时应优先读取 `failure.summary` / `failure.category`
- 前端应以 `actions.*.enabled` 和 `artifacts.*.ready` 判断下载按钮是否可用
- 不要用进度百分比推断任务已经完成
- `artifacts.manifest_path` / `artifacts.manifest_url` 指向稳定产物清单接口

`request_payload` 使用约定：

- `request_payload` 是后端当前任务实际保存的请求参数快照
- 可用于联调与排错，例如核对：
  - `request_payload.ocr.page_ranges`
  - `request_payload.source.upload_id`
  - `request_payload.translation.model`
- 如果前端要确认某个字段是否真的进了后端，应优先看 `request_payload`，而不是只看本地提交态

`runtime` 当前重点字段：

- `current_stage`：当前阶段
- `stage_started_at`：当前阶段开始时间
- `last_stage_transition_at`：最近一次阶段切换时间
- `active_stage_elapsed_ms`：当前阶段已运行耗时
- `total_elapsed_ms`：任务总耗时
- `retry_count`：累计重试次数
- `last_retry_at`：最近一次重试调度时间
- `stage_history`：完整阶段历史，每段包含 `stage / detail / enter_at / exit_at / duration_ms / terminal_status`
- `terminal_reason`：终态原因
- `final_failure_category`：最终失败类别
- `final_failure_summary`：最终失败摘要

阶段时间线读取约定：

- 前端展示“任务概览 -> 过程时间线”时，必须以 `runtime.stage_history` 为准
- 不要以 `GET /api/v1/jobs/{job_id}/events` 反推主时间线
- 对当前新版后端创建并由新版后端全程执行的任务，`runtime.stage_history` 按设计保留完整全过程，而不是只保留最后阶段
- 对运行中的任务，当前活跃阶段也会出现在 `runtime.stage_history` 中，此时通常 `exit_at = null`
- 当前活跃阶段的实时耗时应读取 `runtime.active_stage_elapsed_ms`，不要依赖当前阶段条目的 `duration_ms`
- 历史老任务如果产生于旧版后端，`runtime.stage_history` 可能为空或不完整；该边界只适用于历史兼容，不适用于当前新任务
- 更严格地说：历史老任务的详情接口可能出现 `runtime = null`，这表示该任务创建和执行时后端尚未持久化运行态时间线；前端应将其视为“历史数据缺失”，不是“当前任务写入失败”
- 当前约定的保证范围是：任务由已部署新版后端创建，并由同一套新版后端完成全流程执行；只有在这个范围内，`runtime.stage_history` 才保证可作为稳定的全过程时间线来源

失败任务详情示例（已省略部分 links / actions / artifacts 字段）：

```json
{
  "job_id": "20260404153000-abcd12",
  "status": "failed",
  "stage": "failed",
  "stage_detail": "外部服务请求超时",
  "runtime": {
    "current_stage": "failed",
    "stage_started_at": "2026-04-04T15:33:45Z",
    "last_stage_transition_at": "2026-04-04T15:33:45Z",
    "terminal_reason": "failed",
    "last_error_at": "2026-04-04T15:33:45Z",
    "total_elapsed_ms": 214532,
    "active_stage_elapsed_ms": 0,
    "retry_count": 3,
    "last_retry_at": "2026-04-04T15:32:11Z",
    "final_failure_category": "upstream_timeout",
    "final_failure_summary": "外部服务请求超时",
    "stage_history": [
      {
        "stage": "queued",
        "detail": "任务排队中，等待可用执行槽位",
        "enter_at": "2026-04-04T15:30:00Z",
        "exit_at": "2026-04-04T15:30:02Z",
        "duration_ms": 2000,
        "terminal_status": null
      },
      {
        "stage": "translating",
        "detail": "正在翻译，第 12/22 批",
        "enter_at": "2026-04-04T15:31:02Z",
        "exit_at": "2026-04-04T15:33:45Z",
        "duration_ms": 163000,
        "terminal_status": "failed"
      }
    ]
  },
  "failure": {
    "stage": "translation",
    "category": "upstream_timeout",
    "code": null,
    "summary": "外部服务请求超时",
    "root_cause": "任务调用 OCR 或模型服务时等待过久，超过超时阈值",
    "retryable": true,
    "upstream_host": "api.deepseek.com",
    "provider": "unknown",
    "suggestion": "可直接重试；若频繁发生，建议降低并发或检查网络稳定性",
    "last_log_line": "ReadTimeout: HTTPSConnectionPool(host='api.deepseek.com', port=443)...",
    "raw_error_excerpt": "ReadTimeout",
    "raw_diagnostic": {
      "source": "python_structured_failure",
      "label": "upstream_timeout",
      "exception_type": "ReadTimeout",
      "message": "HTTPSConnectionPool(host='api.deepseek.com', port=443): Read timed out.",
      "traceback": "Traceback (most recent call last): ...",
      "details": {
        "upstream_host": "api.deepseek.com"
      }
    },
    "ai_diagnostic": null
  }
}
```

失败字段补充约定：

- `failure` 是当前唯一真源，失败展示、重试提示、运维排错都应优先读这里
- `failure.raw_diagnostic`
  - 表示后端额外保留的原始诊断上下文
  - 当前可能来源：
    - `python_structured_failure`：Python 入口脚本捕获异常后输出的结构化失败
    - `rule_based_text_extract`：旧规则或纯文本日志回退提取
  - 适合用于排错页、开发者模式、日志展开区，不建议直接原样展示给普通用户
- `failure.ai_diagnostic`
  - 仅在主分类仍为 `unknown` 时，后端才会尝试调用 AI 做补充诊断
  - 它是补充信息，不会覆盖 `failure.category`
  - 为空表示本次没有触发 AI 诊断，或 AI 诊断未产出有效结果
- `failure_diagnostic`
  - 仍然存在，但它只是 `failure` 的兼容映射视图
  - 新接入方不要再把它当主真源

### 5.4 查询任务列表

`GET /api/v1/jobs`

对应 Rust 输出类型：`JobListView`

适合列表页。每项返回：

- `job_id`
- `workflow`
- `status`
- `stage`
- `created_at`
- `updated_at`
- `detail_url`

### 5.5 查询事件流

`GET /api/v1/jobs/{job_id}/events`

对应 Rust 输出类型：`JobEventListView`

查询参数：

- `limit`
- `offset`

每条事件包含：

- `job_id`
- `seq`
- `ts`
- `level`
- `stage`
- `event`
- `message`
- `payload`

重点事件类型：

- `stage_transition`
- `stage_progress`
- `retry_scheduled`
- `failure_classified`
- `failure_ai_diagnosed`
- `job_terminal`
- 兼容保留：`status_changed`、`stage_updated`、`job_error`

其中：

- `stage_transition` / `stage_progress` 的 payload 会附带 `active_stage_elapsed_ms`、`total_elapsed_ms`、`retry_count`、`stage_history`
- `retry_scheduled` 的 payload 会标注 `scope / attempt / max_attempts / delay_seconds / reason`
- `job_terminal` 的 payload 会标注 `total_elapsed_ms / retry_count / failure_category / failure_summary / failure_root_cause`
- `failure_classified` 的 payload 会标注当前结构化失败归类结果
- `failure_ai_diagnosed` 的 payload 会标注 AI 补充诊断结果；只有主分类仍是 `unknown` 时才可能出现

事件流用途约定：

- `/events` 主要用于调试、排查重试链路、查看失败归因变化
- `/events` 不是主时间线真源
- 如果详情接口已经返回 `runtime.stage_history`，前端不要再自行根据事件流重建阶段耗时

事件流示例：

```json
{
  "items": [
    {
      "job_id": "20260404153000-abcd12",
      "seq": 17,
      "ts": "2026-04-04T15:32:11Z",
      "level": "warn",
      "stage": "translating",
      "event": "retry_scheduled",
      "message": "MinerU bundle 下载进入重试",
      "payload": {
        "scope": "mineru_bundle_download",
        "attempt": 2,
        "max_attempts": 5,
        "delay_seconds": 4,
        "reason": "dns error"
      }
    },
    {
      "job_id": "20260404153000-abcd12",
      "seq": 18,
      "ts": "2026-04-04T15:33:45Z",
      "level": "error",
      "stage": "failed",
      "event": "failure_classified",
      "message": "外部服务请求超时",
      "payload": {
        "stage": "translation",
        "category": "upstream_timeout",
        "summary": "外部服务请求超时",
        "retryable": true
      }
    },
    {
      "job_id": "20260404153000-abcd12",
      "seq": 19,
      "ts": "2026-04-04T15:33:46Z",
      "level": "info",
      "stage": "failed",
      "event": "failure_ai_diagnosed",
      "message": "AI 已补充失败归因",
      "payload": {
        "category": "unknown",
        "summary": "任务失败，但暂未识别出明确根因",
        "ai_diagnostic": {
          "summary": "大概率是 Typst 编译阶段字体资源缺失",
          "root_cause": "日志显示 typst 编译前已完成翻译，随后渲染阶段缺少字体或模板依赖",
          "suggestion": "优先检查字体目录、typst 二进制和模板包是否完整",
          "confidence": "medium",
          "observed_signals": [
            "stage=render",
            "traceback present",
            "typst compile failed"
          ]
        }
      }
    },
    {
      "job_id": "20260404153000-abcd12",
      "seq": 20,
      "ts": "2026-04-04T15:33:45Z",
      "level": "error",
      "stage": "failed",
      "event": "job_terminal",
      "message": "任务进入终态 failed",
      "payload": {
        "status": "failed",
        "terminal_reason": "failed",
        "total_elapsed_ms": 214532,
        "retry_count": 3,
        "failure_category": "upstream_timeout",
        "failure_summary": "外部服务请求超时",
        "failure_root_cause": "任务调用 OCR 或模型服务时等待过久，超过超时阈值"
      }
    }
  ],
  "limit": 200,
  "offset": 0
}
```

事件流也会落盘到：

- `DATA_ROOT/jobs/{job_id}/logs/events.jsonl`

### 5.6 下载产物

数据库层的正式下载真源是 `job_artifact_entries`，每个产物用稳定的 `artifact_key` 标识。当前常见 key 包括：

- `source_pdf`
- `translated_pdf`
- `typst_source`
- `typst_render_pdf`
- `markdown_raw`
- `markdown_images_dir`
- `markdown_bundle_zip`
- `normalized_document_json`
- `normalization_report_json`
- `layout_json`
- `provider_bundle_zip`
- `provider_result_json`
- `pipeline_summary`

主任务下载接口：

- `GET /api/v1/jobs/{job_id}/pdf`
- `GET /api/v1/jobs/{job_id}/artifacts/{artifact_key}`
- `GET /api/v1/jobs/{job_id}/markdown`
- `GET /api/v1/jobs/{job_id}/markdown?raw=true`
- `GET /api/v1/jobs/{job_id}/markdown/images/*path`
- `GET /api/v1/jobs/{job_id}/download`
- `GET /api/v1/jobs/{job_id}/normalized-document`
- `GET /api/v1/jobs/{job_id}/normalization-report`

前端应优先读取任务详情里的返回值：

- `actions.download_pdf`
- `actions.open_markdown`
- `actions.open_markdown_raw`
- `actions.download_bundle`
- `artifacts.pdf`
- `artifacts.markdown`
- `artifacts.bundle`

### 5.7 查询稳定产物清单

`GET /api/v1/jobs/{job_id}/artifacts-manifest`

OCR 子任务同理：

- `GET /api/v1/ocr/jobs/{job_id}/artifacts-manifest`

这是面向前端和外部调用方的稳定产物清单接口。它不要求调用方理解当前 `job_id` 目录结构，只暴露：

- 这个任务有哪些产物
- 每个产物的稳定语义 key 是什么
- 是否 ready
- 应该从哪个 API 路径读取

返回结构示例：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "job_id": "20260404150516-75857c",
    "items": [
      {
        "artifact_key": "translated_pdf",
        "artifact_group": "rendered",
        "artifact_kind": "file",
        "ready": true,
        "file_name": "Quantum Mechanical Continuum Solvation Models for Ionic Liquids -translated.pdf",
        "content_type": "application/pdf",
        "size_bytes": 384374,
        "relative_path": "jobs/20260404150516-75857c/rendered/Quantum Mechanical Continuum Solvation Models for Ionic Liquids -translated.pdf",
        "checksum": null,
        "source_stage": "rendering",
        "updated_at": "2026-04-04T15:05:47Z",
        "resource_path": "/api/v1/jobs/20260404150516-75857c/pdf",
        "resource_url": "http://127.0.0.1:41000/api/v1/jobs/20260404150516-75857c/pdf"
      },
      {
        "artifact_key": "typst_source",
        "artifact_group": "typst",
        "artifact_kind": "file",
        "ready": true,
        "file_name": "book-overlay.typ",
        "content_type": "text/plain; charset=utf-8",
        "size_bytes": 12345,
        "relative_path": "jobs/20260404150516-75857c/rendered/typst/book-overlays/book-overlay.typ",
        "checksum": null,
        "source_stage": "rendering",
        "updated_at": "2026-04-04T15:05:47Z",
        "resource_path": "/api/v1/jobs/20260404150516-75857c/artifacts/typst_source",
        "resource_url": "http://127.0.0.1:41000/api/v1/jobs/20260404150516-75857c/artifacts/typst_source"
      }
    ]
  }
}
```

约定：

- `resource_path` / `resource_url` 是调用方应优先使用的下载入口
- `relative_path` 仅用于调试，不建议前端自行拼磁盘路径
- `artifact_kind = dir` 的条目表示目录资源，例如 `markdown_images_dir`；这类条目通常不能直接流式下载单个文件
- `markdown_bundle_zip` 是专门的 Markdown 产物包，只包含 `markdown/full.md` 与 `markdown/images/**`，不包含原始 PDF、翻译后 PDF、provider bundle 或其他调试 JSON
- 直连下载 `markdown_bundle_zip` 时支持可选参数 `include_job_dir=true`；默认 ZIP 内根目录是 `markdown/`，传参后改为 `{job_id}-markdown/`
- 如果数据库里尚未有 manifest 记录，后端会对旧任务按当前 `artifacts` 和标准目录约定做兼容回退构建

如果 `ready=false` 或 `enabled=false`，不要自行拼接下载链接强行访问。

相关输出类型：

- `actions` -> `JobActionsView`
- `artifacts` -> `ArtifactLinksView`
- 单个下载链接 -> `ResourceLinkView`
- Markdown 下载信息 -> `MarkdownView` / `MarkdownArtifactView`

### 5.7 取消任务

`POST /api/v1/jobs/{job_id}/cancel`

当前语义：

- 已排队任务会被标记取消
- 运行中任务会进入取消流程
- 已完成任务不会被回滚

## 6. OCR-only 接口

适合只做 OCR，不做翻译与渲染：

- `POST /api/v1/ocr/jobs`
- `GET /api/v1/ocr/jobs`
- `GET /api/v1/ocr/jobs/{job_id}`
- `GET /api/v1/ocr/jobs/{job_id}/events`
- `GET /api/v1/ocr/jobs/{job_id}/artifacts`
- `GET /api/v1/ocr/jobs/{job_id}/normalized-document`
- `GET /api/v1/ocr/jobs/{job_id}/normalization-report`
- `POST /api/v1/ocr/jobs/{job_id}/cancel`

主任务详情中的 `ocr_job` 字段会给出 OCR 子任务摘要：

- `job_id`
- `status`
- `trace_id`
- `provider_trace_id`
- `detail_url`

对应 Rust 输出类型：`OcrJobSummaryView`

## 7. 简便同步接口

`POST http://host:42000/api/v1/translate/bundle`

用途：

- 一次请求直接上传 PDF 并等待结果
- 返回最终 ZIP 或超时错误

适合：

- 内部工具
- 小型脚本
- 不想自己管理上传 + 轮询 + 下载三段式流程的调用方

不适合：

- 需要实时进度展示的前端页面
- 需要精细排错的场景

## 8. 状态与阶段

`status` 当前可能值：

- `queued`
- `running`
- `succeeded`
- `failed`
- `canceled`

主任务常见 `stage`：

- `queued`
- `ocr_submitting`
- `mineru_upload`
- `mineru_processing`
- `translation_prepare`
- `normalizing`
- `domain_inference`
- `continuation_review`
- `page_policies`
- `translating`
- `rendering`
- `saving`
- `finished`
- `failed`
- `canceled`

`stage_detail` 是当前最推荐展示给用户的阶段说明，粒度比 `stage` 更细。

健康检查接口 `GET /health` 对应 Rust 输出类型：`HealthView`

## 9. 失败诊断

`GET /api/v1/jobs/{job_id}` 在失败时通常会返回：

- `runtime.current_stage`：当前或最终阶段
- `runtime.terminal_reason`：终态原因
- `runtime.total_elapsed_ms`：总耗时
- `runtime.retry_count`：累计重试次数
- `runtime.stage_history`：阶段耗时历史
- `error`：原始错误摘要
- `failure.stage`：失败阶段
- `failure.category`：归类后的错误类型
- `failure.summary`：简短摘要
- `failure.retryable`：是否建议重试
- `failure.root_cause`：识别出的根因
- `failure.suggestion`：建议动作
- `failure.last_log_line`：最后一条高信号日志
- `failure.raw_error_excerpt`：原始错误摘录
- `failure.raw_diagnostic`：额外结构化原始诊断，上游 traceback / exception type / 识别细节都在这里
- `failure.ai_diagnostic`：仅 `unknown` 失败可能附带的 AI 补充诊断
- `failure_diagnostic.stage`：失败阶段
- `failure_diagnostic.type`：归类后的错误类型
- `failure_diagnostic.summary`：简短摘要
- `failure_diagnostic.retryable`：是否建议重试
- `failure_diagnostic.root_cause`：识别出的根因
- `failure_diagnostic.suggestion`：建议动作
- `log_tail`：最近日志尾部

字段语义：

- `runtime`：运行期状态真相，由后端在任务运行中持续写入
- `runtime.stage_history`：阶段耗时主来源，不需要再从事件时间戳反推
- `runtime.final_failure_*`：最终失败归因摘要，便于列表页或概览页直接展示
- `failure`：结构化失败归因，由后端在运行期直接分类并持久化
- 失败归因优先级：
  1. Python 结构化失败输出
  2. Rust 侧规则分类
  3. `unknown` 时再附加 AI 补充诊断
- `failure_diagnostic`：兼容旧调用方的映射视图，本质上由 `failure` 投影而来
- `error`：原始错误文本或摘要，不保证结构化

当前已重点覆盖的错误类型包括：

- 鉴权错误：如 `missing or invalid X-API-Key`
- 配置错误：如缺少 `mineru_token`、`api_key`、`model`
- 网络错误：如 DNS 解析失败、远端断连、请求超时
- OCR provider transport 错误：申请上传地址失败、轮询失败、下载 bundle 失败
- Python worker 错误：标准化、翻译、渲染阶段异常

失败诊断对象对应 Rust 输出类型：

- `failure` -> `JobFailureInfo`
- `failure_diagnostic` -> `JobFailureDiagnosticView`

前端建议：

- 失败时先展示 `failure.summary`
- 然后展示 `runtime.stage_history` 中最近阶段的耗时
- 若有重试，补充展示 `runtime.retry_count`
- 再展示 `suggestion`
- 开发模式下附带 `log_tail`

## 10. 调用方读取顺序建议

建议调用方不要混用旧字段和新字段做二次推断，优先按下面顺序读取。

### 10.1 任务详情页

推荐读取顺序：

1. `status`
2. `runtime.current_stage`
3. `stage_detail`
4. `progress`
5. `runtime.active_stage_elapsed_ms`
6. `runtime.total_elapsed_ms`
7. `actions.*` / `artifacts.*`

展示建议：

- 当前阶段名称：优先 `runtime.current_stage`
- 当前阶段说明：优先 `stage_detail`
- 当前阶段耗时：优先 `runtime.active_stage_elapsed_ms`
- 总耗时：优先 `runtime.total_elapsed_ms`
- 下载按钮：只看 `actions.*.enabled` 和 `artifacts.*.ready`

### 10.2 失败任务页

推荐读取顺序：

1. `failure.summary`
2. `failure.root_cause`
3. `failure.suggestion`
4. `failure.last_log_line`
5. `failure.retryable`
6. `runtime.final_failure_category`
7. `runtime.retry_count`
8. `runtime.stage_history`

展示建议：

- 主错误标题：`failure.summary`
- 根因说明：`failure.root_cause`
- 操作建议：`failure.suggestion`
- 最近高信号日志：`failure.last_log_line`
- 是否可重试：`failure.retryable`
- 失败前最后阶段耗时：取 `runtime.stage_history` 最后一段

兼容说明：

- `failure_diagnostic` 仍可读，但它只是 `failure` 的兼容映射
- 新接入方不要再以 `error` 做失败分类

### 10.3 列表页 / 历史记录页

列表页建议只读取这些低成本字段：

- `job_id`
- `status`
- `stage`
- `created_at`
- `updated_at`

如果列表页需要展示失败摘要，建议补拉详情接口后再读：

- `runtime.final_failure_category`
- `runtime.final_failure_summary`
- `runtime.total_elapsed_ms`

不要在列表接口上自行用 `status + stage + error` 拼失败文案。

### 10.4 事件页 / 调试页

推荐读取事件顺序：

1. `job_terminal`
2. `failure_classified`
3. `retry_scheduled`
4. `stage_transition`
5. `stage_progress`
6. `job_error`

用途建议：

- 看最终归因：`job_terminal` + `failure_classified`
- 看为何变慢：`stage_transition` / `stage_progress`
- 看为何重试：`retry_scheduled`
- 看原始错误摘录：`job_error`

## 11. 常见排查点

### 11.1 任务失败但前端只显示“任务失败”

优先看：

1. `GET /api/v1/jobs/{job_id}`
2. `failure`
3. `log_tail`
4. `GET /api/v1/jobs/{job_id}/events`

### 11.2 下载按钮不可用

先确认：

- `status` 是否已结束
- `actions.*.enabled` 是否为 `true`
- `artifacts.*.ready` 是否为 `true`

不要只因为状态是 `running` 就猜测文件已经存在。

### 11.3 MinerU 相关失败

常见原因：

- `mineru_token` 缺失或过期
- 上传 PDF 超过 MinerU 限制
- DNS 或代理环境异常
- 远端接口短时断连或 CDN 拉取失败

### 11.4 DNS / 网络异常

典型报错包括：

- `Temporary failure in name resolution`
- `Server disconnected without sending a response`
- `Failed to fetch`

这类问题通常不在前端，而在后端宿主机网络、代理或 DNS 配置。

## 12. 接入建议

前端最稳妥的调用方式：

1. `POST /api/v1/uploads`
2. `POST /api/v1/jobs`
3. 轮询 `GET /api/v1/jobs/{job_id}`
4. 成功后读取 `actions` / `artifacts` 再下载
5. 失败时展示 `failure_diagnostic` 和 `log_tail`

如果你只需要一个最小实现，直接参考：

- [frontend_request_example.md](/home/wxyhgk/tmp/Code/backend/rust_api/frontend_request_example.md)
