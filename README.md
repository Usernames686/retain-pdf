# RetainPDF：PDF 保留排版翻译工具

<p align="center">
  <img src="image/RetainPDF-github.svg" alt="RetainPDF" width="320" />
</p>
# 对原作者的2次修改
  # 翻译链路修复说明（2026-04-17）

## 背景

本次排查包含两类问题：

1. 某些 PDF 已经可以跑通，但生成结果存在英文残留、中英叠字、版面覆盖等问题。
2. 修复版面问题之后，出现了“之前能翻译的文件现在整单失败”的回归现象。

本说明记录本轮定位、修复、线上同步和验证结果，方便后续留档与交接。

## 一、PDF 渲染层问题

### 现象

- 第 1、2、3 页出现明显中英重叠。
- 中文正文已写入，但原英文正文没有被视觉上清掉。
- 结果表现为不是翻译文本本身坏，而是“背景清理失败后又叠写中文”。

### 根因

问题位于 Typst 渲染链路的 cleaned background 阶段。

在 `book-background-cleaned.pdf` 中，部分原英文正文虽然逻辑上参与了 redaction，但视觉上没有被真正盖白，最终 Typst 再把中文叠上去，就形成了中英重影。

### 修复

- 调整 redaction 标准路径：
  - 即使块被判定为“文本可删除”，也同步附带背景填充。
  - 不再依赖 PDF 内部文本删除一定成功。
- 增加回归测试，确保可移除文本块会带 fill 进入 redaction。

### 结果

- 第 1、2、3 页中英叠字问题已消失。
- 修正后的 PDF 已覆盖回原任务输出。

## 二、翻译链路回归问题

### 现象

网站上出现“任务不是翻译效果差，而是直接失败”的情况。

近期失败单的典型模式是：

- 某个单独块在 plain-text、structured、raw、sentence-level fallback 全部走完后，
- 仍然因为 `EnglishResidueError` 或类似校验异常被抛出，
- 最后把整页甚至整单任务一起打死。

### 关键结论

#### 1. provider 的翻译 key 不是登录 token

线上真实翻译使用的 provider key 来自任务请求中的：

`translation.api_key`

它会沿着以下路径进入运行时：

1. Rust API 接收创建任务请求。
2. `translation.api_key` 写入 job request payload。
3. job runner 启动 Python worker 时，把它作为 `--api-key` 传入。

因此：

- Rust API 的 `X-API-Key` 是接口鉴权 key。
- 翻译 provider key 是任务级参数，不是同一个东西。
- 手工 `translate-only` 复跑时，如果没有真实 provider key，就不能代表线上真实任务一定没带 key。

#### 2. 真正的回归点是“单块异常升级成整单失败”

根因不是整个翻译服务不可用，而是翻译链路中某些单块校验异常没有被 item 级隔离。

也就是说：

- 某个块翻译后仍被判断为英文残留、
- 或者命中了其他 `ValueError` 类校验异常，
- 本应只影响该块，
- 但之前实际会一路向上抛出，导致整个批次失败。

## 三、本次翻译链路修复

### 已完成改动

#### 1. 重复 English residue 降级为内部 keep_origin

在 repeated `EnglishResidueError` / `SuspiciousKeepOriginError` 且 sentence-level 也失败时：

- 不再抛错终止整单；
- 改为返回内部降级结果：
  - `decision = keep_origin`
  - `_internal_reason = english_residue_repeated`
    或
  - `_internal_reason = suspicious_keep_origin_repeated`

同时：

- 这类内部降级结果不会写入缓存，
- 避免污染后续任务。

#### 2. 补上 item 级异常隔离

在 `translate_items_plain_text()` 中加入了单块级保护：

- 如果某个 item 在单块翻译重试链路中抛出可恢复的 `ValueError` 类校验异常，
- 则该 item 会就地降级为内部 `keep_origin`，
- 不再继续向上抛出，
- 同批其他 item 继续正常翻译。

新增内部降级原因：

- `single_item_validation_failed`

这样可以避免“一个坏块把整个批次拖死”。

### 本次涉及文件

#### 渲染修复

- `backend/scripts/services/rendering/redaction/redaction_routes.py`
- `backend/scripts/devtools/tests/rendering/test_typst_render_refactor.py`

#### 翻译修复

- `backend/scripts/services/translation/llm/placeholder_guard.py`
- `backend/scripts/services/translation/llm/fallbacks.py`
- `backend/scripts/devtools/tests/translation/test_keep_origin_recovery.py`

## 四、验证结果

### 本地验证

已通过：

- `test_typst_render_refactor.py`
- `test_render_mode.py`
- `test_keep_origin_recovery.py`
- `test_translation_json_recovery.py`

### 容器内验证

已将补丁同步到运行中的容器：

- `retainpdf-app-1`

并完成最小复现验证：

- 同批中正常 item 仍然返回翻译结果；
- 失败 item 会降级成内部 `keep_origin`；
- 不再导致整批中断。

### 线上状态

当前状态为：

- 服务器源码已同步；
- 运行中的容器已同步；
- 新发起的任务会走到本次修复后的逻辑。

说明：

- 本次是直接把补丁同步进线上运行容器；
- 没有重建镜像；
- 也没有重启整站。

## 五、已知剩余问题

虽然“整单失败”问题已经明显收敛，但仍有一个未完全闭环的点：

- 目前没有拿到真实可用的 provider API key 做完整线上实跑复验；
- 因此已经完成：
  - 本地测试验证
  - 容器内最小复现验证
- 但尚未完成：
  - 指定真实文件的 provider-backed 全链路重跑验证

另外，部分 PDF 即使不再失败，翻译产物中仍可能存在：

- OCR 重复句
- 粘连重复
- 模型自述残留

这些属于翻译质量清洗问题，不是本轮“整单失败”回归的主因，但后续仍建议继续收。

## 六、结论

本轮修复后的结论如下：

- PDF 中英叠字问题已经定位并修复，原因是 cleaned background 阶段未真正视觉清底。
- “之前能翻译的文件现在整单失败”的回归问题，主要根因是单块校验异常缺少 item 级隔离。
- 当前线上环境已经同步到修复版本。
- 新任务会使用修复后的逻辑运行。

如果后续继续推进，建议优先顺序为：

1. 用真实 provider key 选一份曾经失败的 PDF 做线上实跑复验。
2. 继续优化重复句、OCR 粘连重复、模型思考残留等翻译质量问题。
