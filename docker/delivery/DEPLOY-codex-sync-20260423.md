# 从 `codex/sync-20260423` 分支进行 Docker 部署

这份文档针对当前这批已经做过实际服务器验证的改动，说明如何直接从 GitHub 分支 `codex/sync-20260423` 拉代码并用 Docker 部署。

适用场景：

- 你想部署“今天这一版”而不是仓库当前 `main`
- 你需要自定义 OpenAI 兼容模型 API
- 你希望包含这批修复：
  - 标题翻译修复
  - 下载 / 在线浏览修复
  - 翻译脏文本清洗增强
  - 渲染 / 字体路径兼容增强
  - 30 天任务产物自动清理

---

## 1. 这版分支包含什么

当前部署文档对应分支：

- 分支名：`codex/sync-20260423`
- 仓库地址：`https://github.com/Usernames686/retain-pdf`

这版分支相对旧版本，重点多了这些能力：

1. 支持自定义 OpenAI 兼容模型 API
2. 标题不再被错误跳过翻译
3. 任务详情里的下载 / 在线查看链路更完整
4. 目录项、短标题、标题里的模型英文点评会被额外清洗
5. 渲染时字体路径和 Typst project root 兼容更稳
6. 任务文件默认保留 30 天，超期自动清理

---

## 2. 机器要求

建议环境：

- 系统：`Ubuntu 22.04 / 24.04`
- 架构：`x86_64 / amd64`
- CPU：至少 `4 核`
- 内存：至少 `8GB`，推荐 `16GB`
- 磁盘：至少 `10GB` 可用空间

说明：

- 这套部署主要吃 CPU、内存和网络，不依赖独显
- 如果你是 ARM 机器，需要额外确认镜像兼容性

---

## 3. 先安装 Docker

确认机器里已经有：

- `docker`
- `docker compose`

检查命令：

```bash
docker --version
docker compose version
```

---

## 4. 拉取指定分支代码

不要直接拉默认分支，按下面方式拉指定分支：

```bash
git clone -b codex/sync-20260423 https://github.com/Usernames686/retain-pdf.git
cd retain-pdf/docker/delivery
```

如果你已经有仓库，也可以这样切换：

```bash
git fetch origin
git checkout codex/sync-20260423
cd docker/delivery
```

---

## 5. 部署前要改哪些文件

当前部署主要会用到下面这些文件：

- `docker-compose.yml`
- `docker/app.env`
- `docker/web.env`
- `docker/auth.local.json`

### 5.1 `docker/auth.local.json`

这个文件控制后端访问鉴权。

你至少要保证：

- `api_keys` 里有一个你自己的后端访问 key

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

后面 `docker/web.env` 里的 `FRONT_X_API_KEY` 必须和这里保持一致。

---

### 5.2 `docker/web.env`

这版最关键的是这里支持预置你的自定义模型接口。

建议至少改这几项：

```env
FRONT_X_API_KEY=replace-with-your-backend-key
FRONT_MINERU_TOKEN=你的_MinerU_Token
FRONT_MODEL_API_KEY=你的模型APIKey
FRONT_MODEL=your-model-name
FRONT_BASE_URL=https://your-openai-compatible-endpoint.example/v1
FRONT_PROVIDER_PRESET=deepseek
```

说明：

- `FRONT_X_API_KEY`
  必须和 `docker/auth.local.json` 中的 key 一致
- `FRONT_MINERU_TOKEN`
  如果想让前端默认带出 OCR token，就填这里
- `FRONT_MODEL_API_KEY`
  你的模型接口 key
- `FRONT_MODEL`
  模型名，例如 `your-model-name`
- `FRONT_BASE_URL`
  你的 OpenAI 兼容接口地址，例如：
  - `https://your-openai-compatible-endpoint.example/v1`

如果你不想把这些值写死在前端，也可以留空，后续用户在网页里自己填。

---

### 5.3 `docker/app.env`

通常不用大改，但建议确认以下项：

```env
RUST_API_MAX_RUNNING_JOBS=4
RUST_API_NORMAL_MAX_BYTES=209715200
RUST_API_NORMAL_MAX_PAGES=600
PDF_TRANSLATOR_DEEPSEEK_STREAM=1
RETAIN_PDF_FONT_PATH=/usr/local/share/fonts/source-han-serif/SourceHanSerifSC-Regular.otf
RETAIN_PDF_TYPST_FONT_FAMILY=Source Han Serif SC
```

说明：

- `RUST_API_MAX_RUNNING_JOBS`
  同时运行的任务数
- `RUST_API_NORMAL_MAX_BYTES`
  上传大小限制，当前是 `200MB`
- `RUST_API_NORMAL_MAX_PAGES`
  页数限制，当前是 `600`
- `PDF_TRANSLATOR_DEEPSEEK_STREAM=1`
  开启流式翻译读取
- `RETAIN_PDF_FONT_PATH`
  默认中文字体路径

---

## 6. 直接启动

在 `retain-pdf/docker/delivery` 目录下执行：

```bash
docker compose up -d --build
```

说明：

- `--build` 会按当前分支代码重新构建镜像
- 这一步会同时启动：
  - `app`
  - `web`

---

## 7. 检查服务是否启动成功

先看容器状态：

```bash
docker compose ps
```

正常情况下应该能看到：

- `app` 为 `healthy`
- `web` 为 `healthy`

再看日志：

```bash
docker compose logs -f app
docker compose logs -f web
```

---

## 8. 默认访问地址

启动完成后，网页入口默认是：

```text
http://127.0.0.1:40001
```

如果你做了域名反代，就访问你的域名。

当前 compose 默认还暴露：

- `41000`：完整 Rust API
- `42000`：简便同步接口
- `40001`：前端页面

---

## 9. 上线后建议先做的验证

### 9.1 健康检查

```bash
curl http://127.0.0.1:41000/health
```

### 9.2 打开网页检查

确认这些功能正常：

1. 首页能打开
2. API 配置弹窗能打开
3. 提交任务后能轮询状态
4. 任务完成后：
   - 下载 PDF 可点
   - 下载 Markdown ZIP 可点
   - 在线浏览可打开

### 9.3 实测一份 PDF

建议至少跑两类：

1. 普通论文 PDF
2. 扫描版 / OCR 噪声比较重的 PDF

重点看：

- 标题是否被翻译
- 目录项里是否混入英文解释
- 是否还出现 `This feels like...`、`could also work...` 这类模型点评残留
- 下载链接是否可用

---

## 10. 这版新增的自动清理机制

这版部署后，任务产物会默认保留 30 天。

自动清理范围包括：

- `/data/jobs/<job_id>`
- `/data/downloads/<job_id>.zip`
- 数据库中的历史任务记录

作用：

- 防止服务器上历史 PDF、ZIP、任务目录越堆越多

如果你后续想改保留策略，可以再看：

- `backend/rust_api/src/cleanup.rs`
- `backend/rust_api/src/config.rs`

---

## 11. 常见更新方式

如果你只是拉到了这条分支，后续又想继续更新这条分支：

```bash
cd retain-pdf
git checkout codex/sync-20260423
git pull origin codex/sync-20260423
cd docker/delivery
docker compose up -d --build
```

---

## 12. 常见问题

### 12.1 下载按钮点了没反应

优先检查：

1. `web` 容器是否是最新构建
2. `docker/web.env` 是否正确
3. 反向代理是否把 `/api/` 路由代理到了后端

建议先看：

```bash
docker compose logs -f web
```

---

### 12.2 在线浏览打不开

优先检查：

1. 任务是否真的成功完成
2. `/api/v1/jobs/<job_id>/pdf` 是否可访问
3. 前端是不是还是旧缓存

可以强刷浏览器再试。

---

### 12.3 标题还是没翻

优先确认：

- 当前代码确实来自 `codex/sync-20260423`
- 不是旧镜像
- 不是旧容器

建议执行：

```bash
docker compose down
docker compose up -d --build
```

---

### 12.4 目录页还有英文点评残留

这版已经清理了很大一批常见模式，但不是说从此所有 PDF 100% 完全无残留。

如果还有漏网样例，优先保留：

- 原 PDF
- 任务 ID
- 对应页截图

这样可以继续补成新的通用规则，而不是做一次性人工修补。

---

## 13. 推荐的部署后检查清单

建议部署完按这个顺序检查：

1. `docker compose ps`
2. `curl http://127.0.0.1:41000/health`
3. 浏览器打开首页
4. 提交一份普通 PDF
5. 提交一份 OCR 噪声重的 PDF
6. 检查标题、目录、下载、在线浏览

---

## 14. 总结

如果你要部署“今天修过并做过线上验证的这一版”，推荐直接使用：

- 仓库：`https://github.com/Usernames686/retain-pdf`
- 分支：`codex/sync-20260423`

核心启动命令就是：

```bash
git clone -b codex/sync-20260423 https://github.com/Usernames686/retain-pdf.git
cd retain-pdf/docker/delivery
docker compose up -d --build
```

只要把下面几个值配好，基本就能跑：

- `docker/auth.local.json`
- `docker/web.env` 里的：
  - `FRONT_X_API_KEY`
  - `FRONT_MINERU_TOKEN`
  - `FRONT_MODEL_API_KEY`
  - `FRONT_MODEL`
  - `FRONT_BASE_URL`
