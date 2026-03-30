# Rust API 接口文档

本文档面向前端和外部调用方，描述当前 `rust_api` 服务已经实现的接口、返回结构、调用顺序和接入建议。

前端如果想直接照抄请求流程，可以同时参考：

- [frontend_request_example.md](/home/wxyhgk/tmp/Code/rust_api/frontend_request_example.md)

当前 Rust API 在后端会调用 Python 入口脚本：

- `scripts/entrypoints/run_mineru_case.py`

也就是说，`rust_api` 负责对外服务、任务排队和状态落库，实际 PDF 主链路仍由 Python worker 执行。

## 1. 基础信息

- 服务职责：提供上传、创建翻译任务、查询任务状态、下载 PDF / Markdown / Bundle、取消任务等对外 API。
- 默认端口：
  - `41000`：完整 API
  - `42000`：简便同步 API
- 健康检查：`GET /health`
- 业务前缀：`/api/v1`
- 数据格式：除文件下载接口外，默认返回 `application/json`
- 鉴权方式：除 `GET /health` 外，其余接口默认要求请求头 `X-API-Key`

### 1.1 服务端鉴权配置

推荐方式：使用本地配置文件 `rust_api/auth.local.json`

示例：

```json
{
  "api_keys": [
    "replace-with-your-backend-key"
  ],
  "max_running_jobs": 4,
  "simple_port": 42000
}
```

仓库内提供示例文件：

- `rust_api/auth.local.example.json`

说明：

- `auth.local.json` 优先级高于环境变量
- `api_keys`：允许访问 Rust API 的后端 key 列表
- `max_running_jobs`：同时运行中的任务数上限
- `simple_port`：简便同步 API 端口，默认 `42000`

如果你仍想走环境变量，也支持：

- `RUST_API_PORT`：服务端口，默认 `41000`
- `RUST_API_SIMPLE_PORT`：简便同步 API 端口，默认 `42000`
- `RUST_API_KEYS`：访问 Rust API 的 key 白名单，逗号分隔
- `RUST_API_MAX_RUNNING_JOBS`：同时运行中的任务数上限，默认 `4`
- `RUST_API_NORMAL_MAX_BYTES`：普通用户上传大小限制
- `RUST_API_NORMAL_MAX_PAGES`：普通用户上传页数限制

### 1.2 请求头要求

除健康检查外，其余请求都应携带：

```http
X-API-Key: your-rust-api-key
```

注意区分两类 key：

- `X-API-Key`：访问 Rust API 的凭证
- 请求体中的 `api_key`：下游大模型服务的凭证

## 2. 统一响应格式

成功响应统一为：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

失败时通常返回：

```json
{
  "code": 400,
  "message": "具体错误信息"
}
```

说明：

- `code=0` 表示成功。
- `message` 为简短说明。
- `data` 为具体业务数据。

## 3. 典型调用流程

推荐调用顺序：

1. 上传 PDF：`POST /api/v1/uploads`
2. 创建任务：`POST /api/v1/jobs`
3. 轮询状态：`GET /api/v1/jobs/{job_id}`
4. 获取产物：
   - PDF：`GET /api/v1/jobs/{job_id}/pdf`
   - Markdown：`GET /api/v1/jobs/{job_id}/markdown`
   - Bundle：`GET /api/v1/jobs/{job_id}/download`
5. 如需中止：`POST /api/v1/jobs/{job_id}/cancel`

前端建议：

- 列表页优先用 `GET /api/v1/jobs`
- 详情页优先用 `GET /api/v1/jobs/{job_id}`
- 下载、跳转、按钮启用状态优先使用返回里的 `actions`

如果你只想“提交一次，直接拿 ZIP”，可以直接用简便同步接口：

- `POST http://host:42000/api/v1/translate/bundle`

## 4. 任务状态说明

`status` 当前可能值：

- `queued`：已入队，正在等待可用执行槽位
- `running`：运行中
- `succeeded`：成功完成
- `failed`：执行失败
- `canceled`：已取消

## 5. 接口列表

### 5.1 健康检查

**请求**

```http
GET /health
```

**成功响应示例**

```json
{
  "status": "ok"
}
```

---

### 5.2 上传 PDF

**请求**

```http
POST /api/v1/uploads
Content-Type: multipart/form-data
X-API-Key: your-rust-api-key
```

**表单字段**

- `file`：必填，PDF 文件
- `developer_mode`：可选，是否开发者模式，布尔风格字符串，例如 `true` / `false`

**普通用户限制**

- 文件大小不超过 `10MB`
- 页数不超过 `30` 页

**成功响应示例**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "upload_id": "20260327-abc123",
    "filename": "paper.pdf",
    "bytes": 1832451,
    "page_count": 18,
    "uploaded_at": "2026-03-27T18:20:31+08:00"
  }
}
```

**失败场景**

- 文件缺失
- 不是 PDF
- 文件超限
- 页数超限

---

### 5.3 简便同步接口：直接返回 ZIP

这个接口运行在简便端口，默认 `42000`。

**请求**

```http
POST http://127.0.0.1:42000/api/v1/translate/bundle
Content-Type: multipart/form-data
X-API-Key: your-rust-api-key
```

**必须字段**

- `file`：PDF 文件
- `mineru_token`：MinerU API Key
- `base_url`：模型服务 URL
- `api_key`：模型服务 API Key
- `model`：模型名字

**常用可选字段**

- `developer_mode`
- `mode`
- `workers`
- `batch_size`
- `render_mode`
- `compile_workers`
- `page_ranges`
- `rule_profile_name`
- `custom_rules_text`

**DeepSeek 示例**

```bash
curl -X POST "http://127.0.0.1:42000/api/v1/translate/bundle" \
  -H "X-API-Key: your-rust-api-key" \
  -F "file=@/path/to/file.pdf" \
  -F "developer_mode=true" \
  -F "mineru_token=your-mineru-api-key" \
  -F "base_url=https://api.deepseek.com/v1" \
  -F "api_key=your-deepseek-api-key" \
  -F "model=deepseek-chat" \
  -F "mode=sci" \
  -F "workers=50" \
  -F "batch_size=1" \
  -o result.zip
```

**成功返回**

- 直接返回 ZIP 文件
- 响应头里会带 `X-Job-Id`
- ZIP 内包含：
  - 翻译后的 PDF
  - `markdown/full.md`
  - `markdown/images/*`
- 同时还会把同一份 ZIP 复制到：
  - `output/<job_id>/translated/<job_id>.zip`

**说明**

- 这个接口会一直占住连接，直到任务完成后才返回 ZIP
- 如果任务失败，会直接返回 JSON 错误体，而不是 ZIP

---

### 5.4 创建任务

**请求**

```http
POST /api/v1/jobs
Content-Type: application/json
X-API-Key: your-rust-api-key
```

**最小可用请求体**

```json
{
  "upload_id": "20260327-abc123",
  "mineru_token": "your-mineru-api-key",
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "your-llm-api-key",
  "model": "deepseek-chat"
}
```

**调用时必须同时提供的内容**

- 请求头里的后端访问 key：`X-API-Key`
- 请求体里的 `mineru_token`：MinerU 的 API Key
- 请求体里的 `base_url`：模型服务的 OpenAI 兼容 URL
- 请求体里的 `api_key`：对应模型服务的 API Key
- 请求体里的 `model`：模型名字

也就是说，调用 `POST /api/v1/jobs` 时，必须同时带上：

1. 你的后端 key
2. MinerU API Key
3. 模型服务 URL
4. 模型服务 API Key
5. 模型名字

**常用字段**

- `upload_id`：必填，上传接口返回的 ID
- `workflow`：可选，默认 `mineru`
- `mode`：可选，例如 `sci`、`precise`
- `model`：必填，模型名
- `base_url`：必填，模型服务地址，必须以 `http://` 或 `https://` 开头
- `api_key`：必填，下游模型 API Key
- `mineru_token`：必填，MinerU API Key
- `workers`：可选，翻译并发数
- `batch_size`：可选，翻译批大小
- `render_mode`：可选，渲染模式
- `compile_workers`：可选，Typst 编译并发数
- `model_version`：可选，前端记录或展示用途
- `language`：可选，目标语言
- `page_ranges`：可选，页码范围
- `rule_profile_name`：可选，规则配置名
- `custom_rules_text`：可选，自定义规则文本

此外还支持若干布局、渲染、压缩相关字段，前端可按需要逐步接入。

**示例 1：DeepSeek**

```http
POST /api/v1/jobs
Content-Type: application/json
X-API-Key: your-rust-api-key
```

```json
{
  "upload_id": "20260327-abc123",
  "mineru_token": "your-mineru-api-key",
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "your-deepseek-api-key",
  "model": "deepseek-chat",
  "mode": "sci",
  "workers": 50,
  "batch_size": 1
}
```

**示例 2：OpenAI 兼容接口**

```http
POST /api/v1/jobs
Content-Type: application/json
X-API-Key: your-rust-api-key
```

```json
{
  "upload_id": "20260327-abc123",
  "mineru_token": "your-mineru-api-key",
  "base_url": "http://127.0.0.1:10001/v1",
  "api_key": "your-openai-compatible-api-key",
  "model": "Q3.5-turbo",
  "mode": "precise",
  "workers": 4,
  "batch_size": 1
}
```

**成功响应示例**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "job_id": "20260327180000-9f85c8",
    "status": "queued",
    "workflow": "mineru",
    "links": {
      "self": "/api/v1/jobs/20260327180000-9f85c8",
      "artifacts": "/api/v1/jobs/20260327180000-9f85c8/artifacts"
    },
    "actions": {
      "open_job": {
        "enabled": true,
        "method": "GET",
        "path": "/api/v1/jobs/20260327180000-9f85c8",
        "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8"
      },
      "cancel": {
        "enabled": true,
        "method": "POST",
        "path": "/api/v1/jobs/20260327180000-9f85c8/cancel",
        "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/cancel"
      }
    }
  }
}
```

**注意**

- 现在 `create_job` 会强制校验 `mineru_token`、`base_url`、`api_key`、`model`
- 不再依赖 Rust API 服务端默认填充下游模型和 MinerU 凭证
- 新任务创建后先进入 `queued`，当有空闲执行槽位时才会转为 `running`

---

### 5.5 获取任务列表

**请求**

```http
GET /api/v1/jobs
X-API-Key: your-rust-api-key
```

**用途**

- 查询最近任务
- 前端“查询 / 下载”页面展示

**成功响应示例**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "job_id": "20260327180000-9f85c8",
        "workflow": "mineru",
        "status": "running",
        "stage": "translation",
        "stage_detail": "正在翻译，第 3/28 批",
        "progress": {
          "current": 3,
          "total": 28,
          "percent": 10.71
        },
        "timestamps": {
          "created_at": "2026-03-27T18:20:31+08:00",
          "updated_at": "2026-03-27T18:23:08+08:00",
          "started_at": "2026-03-27T18:20:34+08:00",
          "finished_at": null,
          "duration_seconds": 157.0
        },
        "links": {},
        "actions": {}
      }
    ]
  }
}
```

---

### 5.6 获取任务详情

**请求**

```http
GET /api/v1/jobs/{job_id}
X-API-Key: your-rust-api-key
```

**成功响应示例**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "job_id": "20260327180000-9f85c8",
    "workflow": "mineru",
    "status": "running",
    "stage": "translation",
    "stage_detail": "正在翻译，第 3/28 批",
    "progress": {
      "current": 3,
      "total": 28,
      "percent": 10.71
    },
    "timestamps": {
      "created_at": "2026-03-27T18:20:31+08:00",
      "updated_at": "2026-03-27T18:23:08+08:00",
      "started_at": "2026-03-27T18:20:34+08:00",
      "finished_at": null,
      "duration_seconds": 157.0
    },
    "links": {
      "self": "/api/v1/jobs/20260327180000-9f85c8",
      "artifacts": "/api/v1/jobs/20260327180000-9f85c8/artifacts"
    },
    "actions": {
      "open_job": {
        "enabled": true,
        "method": "GET",
        "path": "/api/v1/jobs/20260327180000-9f85c8",
        "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8"
      },
      "open_artifacts": {
        "enabled": true,
        "method": "GET",
        "path": "/api/v1/jobs/20260327180000-9f85c8/artifacts",
        "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/artifacts"
      },
      "cancel": {
        "enabled": true,
        "method": "POST",
        "path": "/api/v1/jobs/20260327180000-9f85c8/cancel",
        "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/cancel"
      }
    },
    "artifacts": {
      "pdf_ready": false,
      "markdown_ready": false,
      "bundle_ready": false
    },
    "log_tail": [
      "job dir: output/20260327180000-9f85c8",
      "stage: translation"
    ]
  }
}
```

**字段说明**

- `stage`：当前阶段标识
- `stage_detail`：适合前端直接显示的说明文本
- `progress.percent`：百分比，前端建议显示但不要拿它直接判断完成
- `timestamps.finished_at`：非空才表示真正结束
- `timestamps.duration_seconds`：从开始到当前或结束的耗时秒数
- `log_tail`：最近日志摘要，适合开发者模式展示

---

### 5.7 获取任务产物信息

**请求**

```http
GET /api/v1/jobs/{job_id}/artifacts
X-API-Key: your-rust-api-key
```

**用途**

- 查询 PDF / Markdown / Bundle 是否可用
- 获取前端可直接使用的下载链接

**成功响应示例**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "job_id": "20260327180000-9f85c8",
    "pdf_ready": true,
    "markdown_ready": true,
    "bundle_ready": true,
    "pdf_url": "/api/v1/jobs/20260327180000-9f85c8/pdf",
    "markdown_url": "/api/v1/jobs/20260327180000-9f85c8/markdown",
    "markdown_images_base_url": "/api/v1/jobs/20260327180000-9f85c8/markdown/images/",
    "bundle_url": "/api/v1/jobs/20260327180000-9f85c8/download",
    "pdf": {
      "ready": true,
      "path": "/api/v1/jobs/20260327180000-9f85c8/pdf",
      "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/pdf",
      "method": "GET",
      "content_type": "application/pdf",
      "file_name": "paper-translated.pdf",
      "size_bytes": 2384512
    },
    "markdown": {
      "ready": true,
      "path": "/api/v1/jobs/20260327180000-9f85c8/markdown",
      "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/markdown",
      "method": "GET",
      "content_type": "application/json",
      "file_name": "paper.md.json",
      "size_bytes": 18452,
      "json_path": "/api/v1/jobs/20260327180000-9f85c8/markdown",
      "json_url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/markdown",
      "raw_path": "/api/v1/jobs/20260327180000-9f85c8/markdown?raw=true",
      "raw_url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/markdown?raw=true",
      "images_base_path": "/api/v1/jobs/20260327180000-9f85c8/markdown/images/",
      "images_base_url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/markdown/images/"
    },
    "bundle": {
      "ready": true,
      "path": "/api/v1/jobs/20260327180000-9f85c8/download",
      "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/download",
      "method": "GET",
      "content_type": "application/zip",
      "file_name": "20260327180000-9f85c8.zip",
      "size_bytes": 5280341
    },
    "actions": {
      "download_pdf": {
        "enabled": true,
        "method": "GET",
        "path": "/api/v1/jobs/20260327180000-9f85c8/pdf",
        "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/pdf"
      },
      "open_markdown": {
        "enabled": true,
        "method": "GET",
        "path": "/api/v1/jobs/20260327180000-9f85c8/markdown",
        "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/markdown"
      },
      "open_markdown_raw": {
        "enabled": true,
        "method": "GET",
        "path": "/api/v1/jobs/20260327180000-9f85c8/markdown?raw=true",
        "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/markdown?raw=true"
      },
      "download_bundle": {
        "enabled": true,
        "method": "GET",
        "path": "/api/v1/jobs/20260327180000-9f85c8/download",
        "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/download"
      }
    }
  }
}
```

**说明**

- `actions` 是前端首选字段。
- `pdf_url`、`markdown_url`、`bundle_url` 等旧字段仍保留，主要用于兼容。

---

### 5.8 下载翻译后的 PDF

**请求**

```http
GET /api/v1/jobs/{job_id}/pdf
X-API-Key: your-rust-api-key
```

**返回**

- 成功时返回 `application/pdf`
- 文件名通常为 `原文件名-translated.pdf`

**注意**

- 适合浏览器直接下载
- 也可由前端拿到 `actions.download_pdf.url` 后直接打开

---

### 5.9 获取 Markdown

**请求**

```http
GET /api/v1/jobs/{job_id}/markdown
X-API-Key: your-rust-api-key
```

**Query 参数**

- `raw=true`：返回原始 Markdown 文本

**默认返回 JSON 示例**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "job_id": "20260327180000-9f85c8",
    "content": "# Title\n\nTranslated content...",
    "raw_path": "/api/v1/jobs/20260327180000-9f85c8/markdown?raw=true",
    "raw_url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/markdown?raw=true",
    "images_base_path": "/api/v1/jobs/20260327180000-9f85c8/markdown/images/",
    "images_base_url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8/markdown/images/"
  }
}
```

**`raw=true` 时**

- 返回 `text/markdown`
- 适合前端直接保存、展示或送往 Markdown 编辑器

---

### 5.10 获取 Markdown 图片资源

**请求**

```http
GET /api/v1/jobs/{job_id}/markdown/images/*path
X-API-Key: your-rust-api-key
```

**用途**

- 配合 Markdown 中的图片路径使用
- 前端渲染 Markdown 时可直接拼接该路径

---

### 5.11 下载任务打包文件

**请求**

```http
GET /api/v1/jobs/{job_id}/download
X-API-Key: your-rust-api-key
```

**返回**

- 成功时返回 ZIP

**限制**

- 只有任务成功完成时才可下载
- 如果任务未完成或失败，通常返回 `409`

---

### 5.12 取消任务

**请求**

```http
POST /api/v1/jobs/{job_id}/cancel
X-API-Key: your-rust-api-key
```

**成功响应示例**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "job_id": "20260327180000-9f85c8",
    "status": "canceled",
    "workflow": "mineru",
    "links": {
      "self": "/api/v1/jobs/20260327180000-9f85c8",
      "artifacts": "/api/v1/jobs/20260327180000-9f85c8/artifacts"
    },
    "actions": {
      "open_job": {
        "enabled": true,
        "method": "GET",
        "path": "/api/v1/jobs/20260327180000-9f85c8",
        "url": "http://127.0.0.1:41000/api/v1/jobs/20260327180000-9f85c8"
      }
    }
  }
}
```

**说明**

- 该接口会尝试终止本地 Python worker 进程组。
- 成功后任务终态应稳定为 `canceled`。

## 6. 前端重点字段说明

### 6.1 progress

```json
{
  "current": 9,
  "total": 10,
  "percent": 90.0
}
```

说明：

- `percent` 只用于展示进度，不应用来判断任务结束。
- 任务是否完成应以 `status` 是否为 `succeeded` / `failed` / `canceled` 为准。
- 任务是否真正开始执行，应结合 `status=running` 或 `started_at` 是否非空判断。

### 6.2 timestamps

```json
{
  "created_at": "2026-03-27T18:20:31+08:00",
  "updated_at": "2026-03-27T18:23:08+08:00",
  "started_at": "2026-03-27T18:20:34+08:00",
  "finished_at": "2026-03-27T18:28:10+08:00",
  "duration_seconds": 456.0
}
```

说明：

- `finished_at` 可用于显示“完成时间”
- `duration_seconds` 可用于显示“耗时”

### 6.3 actions

前端建议优先使用 `actions`，不要自己硬编码 URL。典型结构如下：

```json
{
  "download_pdf": {
    "enabled": true,
    "method": "GET",
    "path": "/api/v1/jobs/xxx/pdf",
    "url": "http://127.0.0.1:41000/api/v1/jobs/xxx/pdf"
  }
}
```

说明：

- `enabled`：按钮是否可点击
- `method`：请求方法
- `path`：相对路径
- `url`：完整 URL，前端可直接使用

### 6.4 artifacts

`artifacts` 分为两类字段：

- 兼容字段：`pdf_url`、`markdown_url`、`bundle_url`
- 新字段：`pdf`、`markdown`、`bundle`、`actions`

前端优先顺序建议：

1. `actions`
2. `artifacts.pdf / markdown / bundle`
3. 旧字段作为兜底

## 7. 推荐前端接入方式

### 7.1 上传页

最少需要：

- PDF 文件选择
- 模式选择：如 `sci` / `precise`
- 模型选择
- 是否开发者模式

推荐高级参数折叠起来：

- `workers`
- `batch_size`
- `compile_workers`
- `render_mode`
- `page_ranges`
- `rule_profile_name`
- `custom_rules_text`

### 7.2 任务详情页

建议展示：

- `job_id`
- `status`
- `stage`
- `stage_detail`
- `progress`
- `finished_at`
- `duration_seconds`
- `log_tail`（仅开发者模式显示）

### 7.3 查询 / 下载页

建议直接展示：

- 任务创建时间
- 完成时间
- 总耗时
- PDF 下载按钮
- Markdown 按钮
- Bundle 下载按钮

## 8. 常见错误

常见错误信息包括但不限于：

- `upload_id is required`
- `upload not found`
- `job not found`
- `job is not finished successfully`
- `file is required`
- `mineru_token is required`  
  说明：当前实现要求显式传入
- `base_url is required`
- `base_url must start with http:// or https://`
- `api_key is required`
- `model is required`
- `missing or invalid X-API-Key`

## 9. 接入建议

### 9.1 关于密钥

- 如果前端部署在公网，不建议把真正的 `api_key`、`mineru_token` 直接暴露给终端用户。
- `X-API-Key` 也不应硬编码在公开前端产物中。
- 更稳妥的做法是：
  - 前端只负责选择服务商、模式和参数
  - 默认密钥由服务端环境变量提供

### 9.2 关于轮询

建议：

- 任务运行中每 `2~3` 秒轮询一次 `GET /api/v1/jobs/{job_id}`
- 到终态后停止轮询

### 9.3 关于完成判断

不要用：

- `progress.percent >= 90`

应该用：

- `status === "succeeded"`
- `status === "failed"`
- `status === "canceled"`

## 10. 当前已实现路由清单

- `GET /health`
- `POST /api/v1/uploads`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/artifacts`
- `GET /api/v1/jobs/{job_id}/pdf`
- `GET /api/v1/jobs/{job_id}/markdown`
- `GET /api/v1/jobs/{job_id}/markdown/images/*path`
- `GET /api/v1/jobs/{job_id}/download`
- `POST /api/v1/jobs/{job_id}/cancel`

## 11. 后续建议

如果你后面要把这个 Rust API 作为正式对外服务层，建议下一步补这些内容：

- OpenAPI / Swagger 自动文档
- 统一错误码枚举
- 鉴权与限流
- Webhook / 回调
- 更细的任务过滤与分页参数
- 批量查询接口
- 面向第三方的稳定字段版本承诺
