# 前端改版 HowTo

这份文档是给前端专家的产品与接口说明。可以继续用当前静态页，也可以直接重做成 React；重点是不要改后端协议，不要暴露服务端密钥。

## 1. 项目目标

这是一个“保留排版翻译”的网页工具，主流程是：

1. 用户上传 PDF
2. 后端走 MinerU API 做解析
3. 后端调用大模型翻译
4. 后端渲染出保留排版的译文 PDF
5. 前端轮询状态并提供 ZIP 下载

当前对外主打的是 SCI 论文场景，不是通用 PDF 编辑器。

## 2. 前端必须有的组件

建议桌面端继续保留三栏结构，移动端改成纵向堆叠。

- `AppShell`
  页面总容器，科研风格，信息密度高一点，但不要花哨。
- `HeroHeader`
  标题、副标题、产品定位说明。
- `NoticeBanner`
  放限制说明：
  - 普通用户仅支持 `10MB` 以内、`30` 页以内
  - 当前主要开放 `sci` 模式
  - 建议用户自备 MinerU / DeepSeek key
- `SubmitCard`
  普通用户主入口。
- `ApiKeyInputs`
  只保留两个常驻输入框：
  - `MinerU API key`
  - `DeepSeek API key`
  留空时默认走服务端本地配置。
- `PdfUploadDropzone`
  支持点击选择和拖拽上传，文件名过长要省略，不换行撑坏卡片。
- `UploadProgress`
  文件一选择就开始上传，显示进度条，不要等到点击“运行任务”才上传。
- `RunButton`
  上传成功后才可点击。
- `StatusCard`
  显示当前任务状态。
- `StatusBadge`
  `idle / queued / running / succeeded / failed`
- `StageDetail`
  展示 `stage_detail`，这是用户判断卡在哪一步的核心信息。
- `JobProgressBar`
  基于 `progress_current / progress_total`。
- `PublicErrorBox`
  普通用户可见的错误摘要，不显示内部日志。
- `QueryDownloadCard`
  输入 `job_id` 后查询历史任务，并下载结果。
- `JobLookupInput`
  输入已有 `job_id`。
- `QueryButton`
  触发查询。
- `DownloadButton`
  成功后可点击。
- `JobTimingPanel`
  放在“查询 / 下载”区域，必须显示：
  - `完成时间`
  - `用时`
- `DeveloperEntryButton`
  一个“开发人员”按钮。
- `DeveloperAuthDialog`
  输入密码后进入开发参数区。
- `DeveloperSettingsDialog`
  放高级参数，不要常驻主界面。
- `DeveloperRawPanels`
  只给开发人员看：
  - `log_tail`
  - 原始 JSON
  - artifacts 路径

## 3. React 版本推荐拆分

如果重做成 React，建议按功能拆，而不是按页面拆。

- `src/components/layout/AppShell.tsx`
- `src/components/hero/HeroHeader.tsx`
- `src/components/notice/NoticeBanner.tsx`
- `src/features/submit/SubmitCard.tsx`
- `src/features/submit/PdfUploadDropzone.tsx`
- `src/features/submit/UploadProgress.tsx`
- `src/features/status/StatusCard.tsx`
- `src/features/query/QueryDownloadCard.tsx`
- `src/features/developer/DeveloperAuthDialog.tsx`
- `src/features/developer/DeveloperSettingsDialog.tsx`
- `src/features/developer/DeveloperRawPanels.tsx`
- `src/lib/api.ts`
- `src/lib/types.ts`
- `src/hooks/useUploadPdf.ts`
- `src/hooks/useRunJob.ts`
- `src/hooks/useJobPolling.ts`

## 4. 当前后端接口契约

普通前端主流程只需要这 4 个接口：

- `GET /health`
  健康检查。
- `POST /v1/uploads/pdf`
  先上传 PDF，返回 `upload_id`、文件名、页数、大小。
- `POST /v1/run-uploaded-mineru-case`
  用 `upload_id` 启动完整任务。
- `GET /v1/jobs/{job_id}`
  查询任务状态，前端轮询这个接口。
- `GET /v1/jobs/{job_id}/download`
  下载 ZIP。

开发人员面板可额外用：

- `GET /v1/rule-profiles`
- `GET /v1/rule-profiles/{name}`

## 5. 前端必须消费的关键字段

`GET /v1/jobs/{job_id}` 里这些字段要用起来：

- `job_id`
- `status`
- `created_at`
- `updated_at`
- `started_at`
- `finished_at`
- `stage`
- `stage_detail`
- `progress_current`
- `progress_total`
- `error`
- `log_tail`
- `artifacts`

其中：

- 普通用户重点看 `status`、`stage_detail`、`progress_current/progress_total`
- “查询 / 下载”区域重点看 `finished_at`
- “用时”可直接用 `finished_at - started_at`
- `log_tail` 只给开发人员看

## 6. 端口与服务说明

当前项目已经在用/默认开放的端口如下：

- `40000`
  主后端 FastAPI，监听 `0.0.0.0:40000`
- `40001`
  当前静态前端预览服务，监听 `0.0.0.0:40001`
- `10001`
  本地 OpenAI 兼容大模型接口，仅开发/调试时使用；前端不要默认暴露它的内部细节，但可以在开发模式里作为 provider preset

外部服务不是本机端口，但前端设计要考虑它们的存在：

- DeepSeek 官方接口：`https://api.deepseek.com/v1`
- MinerU 官方服务：走 token，不是本机端口

## 7. 前端交互约束

- 普通用户界面只保留：
  - 上传
  - 状态
  - 查询
  - 下载
- 其他参数全部收进“开发人员”弹窗
- 不要在普通用户界面泄露：
  - `log_tail`
  - 完整 `command`
  - 服务端默认 key
  - 内部路径
- 上传时就做前端校验：
  - 文件大小上限 `10MB`
  - 页数上限 `30`
- 如果当前已有任务在 `queued/running`，前端要提示用户，不要静默重复提交
- 查询历史任务时，要能直接看到：
  - 任务号
  - 状态
  - 完成时间
  - 用时
  - 下载按钮是否可用

## 8. 视觉风格要求

- 整体风格偏“科研工具”，不是消费级花哨产品
- 卡片密度可以紧凑一些
- 文本信息要稳定，不要出现卡片忽然变宽的布局抖动
- 长文件名、长 job_id、长错误信息都要做截断或换行保护
- 桌面端优先三栏：
  - 提交
  - 状态
  - 查询 / 下载
- 移动端改成单列

## 9. 明确不要做的事情

- 不要把服务端默认的 DeepSeek / MinerU key 渲染到页面
- 不要把开发日志暴露给普通用户
- 不要强依赖当前是原生 JS；React 可以直接上
- 不要改变当前后端 API 协议，除非先和后端一起改

## 10. 给前端专家的一句话总结

这是一个以“上传 PDF -> 异步跑任务 -> 轮询状态 -> 下载结果”为主链路的科研工具前端。普通用户界面必须极简，开发参数必须隐藏，状态可视化要强，接口基于 `40000` 的 FastAPI，当前静态前端跑在 `40001`，本地模型调试口是 `10001`。
