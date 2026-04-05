use crate::models::{JobFailureInfo, JobSnapshot, JobStatusKind};
use crate::ocr_provider::{OcrErrorCategory, OcrProviderDiagnostics};

pub fn classify_job_failure(job: &JobSnapshot) -> Option<JobFailureInfo> {
    if !matches!(job.status, JobStatusKind::Failed) {
        return None;
    }

    let error = job.error.as_deref().unwrap_or("").trim();
    let haystack = if error.is_empty() {
        job.log_tail.join("\n")
    } else {
        format!("{error}\n{}", job.log_tail.join("\n"))
    };
    let diagnostics = job
        .artifacts
        .as_ref()
        .and_then(|artifacts| artifacts.ocr_provider_diagnostics.as_ref());
    let failed_stage = infer_failed_stage(job, &haystack);

    if let Some(provider_failure) = classify_provider_auth_failure(
        failed_stage.clone(),
        diagnostics,
        &haystack,
        select_relevant_log_line(
            job,
            error,
            &["401", "403", "Unauthorized", "missing or invalid X-API-Key"],
        ),
        error,
    ) {
        return Some(provider_failure);
    }

    if haystack.contains("Failed to resolve")
        || haystack.contains("NameResolutionError")
        || haystack.contains("Temporary failure in name resolution")
        || haystack.contains("socket.gaierror")
    {
        return Some(JobFailureInfo {
            stage: failed_stage,
            category: "dns_resolution_failed".to_string(),
            code: None,
            summary: "外部模型服务域名解析失败".to_string(),
            root_cause: Some(
                "容器在当前时刻无法解析上游模型服务域名，任务在翻译阶段中断".to_string(),
            ),
            retryable: true,
            upstream_host: extract_upstream_host(&haystack),
            provider: provider_name(diagnostics),
            suggestion: Some(
                "优先重试一次；若持续失败，请检查 Docker DNS、宿主机网络或代理配置".to_string(),
            ),
            last_log_line: select_relevant_log_line(
                job,
                error,
                &[
                    "Temporary failure in name resolution",
                    "NameResolutionError",
                    "Failed to resolve",
                    "socket.gaierror",
                ],
            ),
            raw_error_excerpt: first_error_excerpt(error, &haystack),
        });
    }

    if haystack.contains("ReadTimeout")
        || haystack.contains("ConnectTimeout")
        || haystack.contains("timed out")
    {
        return Some(JobFailureInfo {
            stage: failed_stage,
            category: "upstream_timeout".to_string(),
            code: None,
            summary: "外部服务请求超时".to_string(),
            root_cause: Some("任务调用 OCR 或模型服务时等待过久，超过超时阈值".to_string()),
            retryable: true,
            upstream_host: extract_upstream_host(&haystack),
            provider: provider_name(diagnostics),
            suggestion: Some("可直接重试；若频繁发生，建议降低并发或检查网络稳定性".to_string()),
            last_log_line: select_relevant_log_line(
                job,
                error,
                &[
                    "ReadTimeout",
                    "ConnectTimeout",
                    "timed out",
                    "api.deepseek.com",
                ],
            ),
            raw_error_excerpt: first_error_excerpt(error, &haystack),
        });
    }

    if haystack.contains("PlaceholderInventoryError")
        || haystack.contains("UnexpectedPlaceholderError")
        || haystack.contains("placeholder inventory mismatch")
        || haystack.contains("unexpected placeholders in translation")
        || haystack.contains("placeholder instability")
        || haystack.contains("degraded to keep_origin after repeated placeholder instability")
    {
        return Some(JobFailureInfo {
            stage: failed_stage,
            category: "placeholder_unstable".to_string(),
            code: None,
            summary: "公式占位符校验失败".to_string(),
            root_cause: Some(
                "模型返回的公式占位符数量或顺序与原文不一致，翻译结果未通过保护校验".to_string(),
            ),
            retryable: true,
            upstream_host: extract_upstream_host(&haystack),
            provider: provider_name(diagnostics),
            suggestion: Some(
                "可直接重试；若稳定复现，建议对该块改用更保守的单块翻译/保留原文策略".to_string(),
            ),
            last_log_line: select_relevant_log_line(
                job,
                error,
                &[
                    "PlaceholderInventoryError",
                    "UnexpectedPlaceholderError",
                    "placeholder inventory mismatch",
                    "unexpected placeholders in translation",
                    "placeholder instability",
                    "degraded to keep_origin after repeated placeholder instability",
                ],
            ),
            raw_error_excerpt: first_error_excerpt(error, &haystack),
        });
    }

    if haystack.contains("401")
        || haystack.contains("403")
        || haystack.contains("missing or invalid X-API-Key")
        || haystack.contains("Unauthorized")
    {
        return Some(JobFailureInfo {
            stage: failed_stage,
            category: "auth_failed".to_string(),
            code: None,
            summary: "鉴权失败".to_string(),
            root_cause: Some("当前任务使用的 API Key / Token 无效、过期或权限不足".to_string()),
            retryable: false,
            upstream_host: extract_upstream_host(&haystack),
            provider: provider_name(diagnostics),
            suggestion: Some("检查 MinerU Token、模型 API Key 或后端 X-API-Key 配置".to_string()),
            last_log_line: select_relevant_log_line(
                job,
                error,
                &["401", "403", "Unauthorized", "missing or invalid X-API-Key"],
            ),
            raw_error_excerpt: first_error_excerpt(error, &haystack),
        });
    }

    if haystack.contains("429")
        || haystack.contains("rate limit")
        || haystack.contains("Too Many Requests")
    {
        return Some(JobFailureInfo {
            stage: failed_stage,
            category: "rate_limited".to_string(),
            code: None,
            summary: "上游服务触发限流".to_string(),
            root_cause: Some("短时间内请求过多，上游服务拒绝继续处理".to_string()),
            retryable: true,
            upstream_host: extract_upstream_host(&haystack),
            provider: provider_name(diagnostics),
            suggestion: Some("等待一段时间后重试，或降低 workers / 并发配置".to_string()),
            last_log_line: select_relevant_log_line(
                job,
                error,
                &["429", "rate limit", "Too Many Requests"],
            ),
            raw_error_excerpt: first_error_excerpt(error, &haystack),
        });
    }

    if haystack.contains("packages.typst.org")
        || haystack.contains("failed to download package")
        || haystack.contains("downloading @preview/")
    {
        return Some(JobFailureInfo {
            stage: "render".to_string(),
            category: "typst_dependency_download_failed".to_string(),
            code: None,
            summary: "Typst 渲染依赖下载失败".to_string(),
            root_cause: Some(
                "渲染阶段需要的 Typst 包未能成功获取，导致 PDF 编译中断".to_string(),
            ),
            retryable: true,
            upstream_host: extract_upstream_host(&haystack),
            provider: provider_name(diagnostics),
            suggestion: Some(
                "检查桌面包是否已内置 Typst packages，或确认运行环境可访问 packages.typst.org"
                    .to_string(),
            ),
            last_log_line: select_relevant_log_line(
                job,
                error,
                &[
                    "failed to download package",
                    "packages.typst.org",
                    "downloading @preview/",
                ],
            ),
            raw_error_excerpt: first_error_excerpt(error, &haystack),
        });
    }

    if contains_render_failure_signal(&haystack) {
        return Some(JobFailureInfo {
            stage: failed_stage,
            category: "render_failed".to_string(),
            code: None,
            summary: "排版或编译阶段失败".to_string(),
            root_cause: Some("翻译已部分完成，但在排版、渲染或 PDF 编译阶段中断".to_string()),
            retryable: false,
            upstream_host: None,
            provider: provider_name(diagnostics),
            suggestion: Some("检查 typst、字体、公式内容或中间产物目录是否完整".to_string()),
            last_log_line: select_relevant_log_line(
                job,
                error,
                &[
                    "typst compile",
                    "failed to compile",
                    "compile error",
                    "render failed",
                    "rendering failed",
                    "failed to render",
                    "typst error",
                    "font not found",
                    "missing bundled font",
                ],
            ),
            raw_error_excerpt: first_error_excerpt(error, &haystack),
        });
    }

    Some(JobFailureInfo {
        stage: failed_stage,
        category: "unknown".to_string(),
        code: diagnostics
            .and_then(|diag| diag.last_error.as_ref())
            .and_then(|err| err.provider_code.clone()),
        summary: "任务失败，但暂未识别出明确根因".to_string(),
        root_cause: if error.is_empty() {
            None
        } else {
            Some(error.lines().next().unwrap_or(error).to_string())
        },
        retryable: true,
        upstream_host: extract_upstream_host(&haystack),
        provider: provider_name(diagnostics),
        suggestion: Some("查看 log_tail 和完整错误日志进一步排查".to_string()),
        last_log_line: select_relevant_log_line(job, error, &[]),
        raw_error_excerpt: first_error_excerpt(error, &haystack),
    })
}

fn classify_provider_auth_failure(
    failed_stage: String,
    diagnostics: Option<&OcrProviderDiagnostics>,
    haystack: &str,
    last_log_line: Option<String>,
    error: &str,
) -> Option<JobFailureInfo> {
    let last_error = diagnostics.and_then(|diag| diag.last_error.as_ref())?;
    let auth_related = matches!(
        last_error.category,
        OcrErrorCategory::Unauthorized | OcrErrorCategory::CredentialExpired
    );
    if !auth_related {
        return None;
    }
    Some(JobFailureInfo {
        stage: failed_stage,
        category: "auth_failed".to_string(),
        code: last_error.provider_code.clone(),
        summary: "鉴权失败".to_string(),
        root_cause: Some("当前任务使用的 API Key / Token 无效、过期或权限不足".to_string()),
        retryable: false,
        upstream_host: extract_upstream_host(haystack),
        provider: provider_name(diagnostics),
        suggestion: Some("检查 MinerU Token、模型 API Key 或后端 X-API-Key 配置".to_string()),
        last_log_line,
        raw_error_excerpt: first_error_excerpt(error, haystack),
    })
}

fn provider_name(diagnostics: Option<&OcrProviderDiagnostics>) -> Option<String> {
    diagnostics.map(|diag| format!("{:?}", diag.provider).to_lowercase())
}

fn first_error_excerpt(error: &str, haystack: &str) -> Option<String> {
    let source = if error.trim().is_empty() {
        haystack
    } else {
        error
    };
    source
        .lines()
        .map(str::trim)
        .find(|line| !line.is_empty())
        .map(|line| line.to_string())
}

fn select_relevant_log_line(job: &JobSnapshot, error: &str, keywords: &[&str]) -> Option<String> {
    let lowered_keywords: Vec<String> = keywords.iter().map(|item| item.to_lowercase()).collect();
    for line in error.lines().rev() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        if lowered_keywords.is_empty() {
            return Some(trimmed.to_string());
        }
        let lowered = trimmed.to_lowercase();
        if lowered_keywords
            .iter()
            .any(|keyword| lowered.contains(keyword))
        {
            return Some(trimmed.to_string());
        }
    }
    for line in job.log_tail.iter().rev() {
        let trimmed = line.trim();
        if trimmed.is_empty() || is_low_signal_log_line(trimmed) {
            continue;
        }
        if lowered_keywords.is_empty() {
            return Some(trimmed.to_string());
        }
        let lowered = trimmed.to_lowercase();
        if lowered_keywords
            .iter()
            .any(|keyword| lowered.contains(keyword))
        {
            return Some(trimmed.to_string());
        }
    }
    job.log_tail
        .iter()
        .rev()
        .find(|line| {
            let trimmed = line.trim();
            !trimmed.is_empty() && !is_low_signal_log_line(trimmed)
        })
        .cloned()
}

fn is_low_signal_log_line(line: &str) -> bool {
    let lowered = line.to_lowercase();
    lowered.starts_with("image-only compress:")
        || lowered.starts_with("cover page image")
        || lowered.starts_with("saved ")
        || lowered.starts_with("rendered page ")
        || lowered.starts_with("auto render mode selected:")
}

fn infer_failed_stage(job: &JobSnapshot, haystack: &str) -> String {
    let stage = job.stage.clone().unwrap_or_default();
    let stage_detail = job.stage_detail.clone().unwrap_or_default();
    let combined = format!("{stage}\n{stage_detail}\n{haystack}").to_lowercase();

    if stage == "rendering"
        || stage == "render"
        || stage_detail.contains("排版")
        || stage_detail.contains("渲染")
        || contains_render_failure_signal(&combined)
    {
        return "render".to_string();
    }
    if stage == "translation" || combined.contains("translation") || stage_detail.contains("翻译") {
        return "translation".to_string();
    }
    if combined.contains("normaliz") || stage_detail.contains("标准化") {
        return "normalization".to_string();
    }
    if combined.contains("ocr")
        || combined.contains("mineru")
        || combined.contains("paddle")
        || stage_detail.contains("解析")
    {
        return "ocr".to_string();
    }
    "failed".to_string()
}

fn contains_render_failure_signal(text: &str) -> bool {
    let lowered = text.to_lowercase();
    if [
        "typst compile",
        "typst compilation",
        "typst error",
        "failed to compile",
        "compile error",
        "render failed",
        "rendering failed",
        "failed to render",
        "missing bundled font",
        "font not found",
    ]
    .iter()
    .any(|pattern| lowered.contains(pattern))
    {
        return true;
    }

    (lowered.contains("no such file or directory")
        || lowered.contains("the system cannot find the file specified"))
        && (lowered.contains("typst") || lowered.contains("font"))
}

fn extract_upstream_host(haystack: &str) -> Option<String> {
    for marker in ["host='", "host=\"", "https://", "http://"] {
        if let Some(start) = haystack.find(marker) {
            let rest = &haystack[start + marker.len()..];
            let host: String = rest
                .chars()
                .take_while(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '-'))
                .collect();
            if !host.is_empty() {
                return Some(host);
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::classify_job_failure;
    use crate::models::CreateJobInput;

    #[test]
    fn classify_job_failure_maps_placeholder_instability() {
        let mut job = crate::models::JobSnapshot::new(
            "job-failure".to_string(),
            CreateJobInput::default(),
            vec!["python".to_string()],
        );
        job.status = crate::models::JobStatusKind::Failed;
        job.error = Some("PlaceholderInventoryError: placeholder inventory mismatch".to_string());
        job.stage = Some("translation".to_string());
        job.stage_detail = Some("正在翻译".to_string());

        let failure = classify_job_failure(&job).expect("failure");
        assert_eq!(failure.category, "placeholder_unstable");
        assert_eq!(failure.stage, "translation");
    }

    #[test]
    fn classify_job_failure_does_not_treat_render_mode_log_as_render_failure() {
        let mut job = crate::models::JobSnapshot::new(
            "job-failure".to_string(),
            CreateJobInput::default(),
            vec!["python".to_string()],
        );
        job.status = crate::models::JobStatusKind::Failed;
        job.error = Some(
            "PlaceholderInventoryError: placeholder inventory mismatch".to_string(),
        );
        job.stage = Some("translation".to_string());
        job.stage_detail = Some("正在翻译".to_string());
        job.log_tail = vec![
            "auto render mode selected: overlay (removable_items=18, checked_items=18, removable_ratio=1.00)"
                .to_string(),
        ];

        let failure = classify_job_failure(&job).expect("failure");
        assert_eq!(failure.category, "placeholder_unstable");
        assert_eq!(failure.stage, "translation");
    }

    #[test]
    fn classify_job_failure_maps_typst_compile_error_to_render_stage() {
        let mut job = crate::models::JobSnapshot::new(
            "job-failure".to_string(),
            CreateJobInput::default(),
            vec!["python".to_string()],
        );
        job.status = crate::models::JobStatusKind::Failed;
        job.error = Some("typst compile failed: font not found".to_string());
        job.stage = Some("translation".to_string());
        job.stage_detail = Some("正在翻译".to_string());

        let failure = classify_job_failure(&job).expect("failure");
        assert_eq!(failure.category, "render_failed");
        assert_eq!(failure.stage, "render");
    }

    #[test]
    fn classify_job_failure_maps_typst_package_download_failure() {
        let mut job = crate::models::JobSnapshot::new(
            "job-failure".to_string(),
            CreateJobInput::default(),
            vec!["python".to_string()],
        );
        job.status = crate::models::JobStatusKind::Failed;
        job.error = Some(
            "RuntimeError: downloading @preview/cmarker:0.1.8\nerror: failed to download package (https://packages.typst.org/preview/cmarker-0.1.8.tar.gz: Connection Failed)"
                .to_string(),
        );
        job.stage = Some("rendering".to_string());
        job.stage_detail = Some("正在准备渲染".to_string());

        let failure = classify_job_failure(&job).expect("failure");
        assert_eq!(failure.category, "typst_dependency_download_failed");
        assert_eq!(failure.stage, "render");
        assert_eq!(failure.upstream_host.as_deref(), Some("packages.typst.org"));
    }
}
