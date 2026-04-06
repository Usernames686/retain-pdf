use std::ops::{Deref, DerefMut};

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::ocr_provider::{parse_provider_kind, OcrProviderDiagnostics};

use super::common::{now_iso, JobStatusKind, WorkflowKind, LOG_TAIL_LIMIT};
use super::input::ResolvedJobSpec;

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
pub struct JobArtifacts {
    pub ocr_job_id: Option<String>,
    pub ocr_status: Option<JobStatusKind>,
    pub ocr_trace_id: Option<String>,
    pub ocr_provider_trace_id: Option<String>,
    pub job_root: Option<String>,
    pub source_pdf: Option<String>,
    pub layout_json: Option<String>,
    pub normalized_document_json: Option<String>,
    pub normalization_report_json: Option<String>,
    pub provider_raw_dir: Option<String>,
    pub provider_zip: Option<String>,
    pub provider_summary_json: Option<String>,
    pub schema_version: Option<String>,
    pub trace_id: Option<String>,
    pub provider_trace_id: Option<String>,
    pub translations_dir: Option<String>,
    pub output_pdf: Option<String>,
    pub summary: Option<String>,
    pub pages_processed: Option<i64>,
    pub translated_items: Option<i64>,
    pub translate_render_time_seconds: Option<f64>,
    pub save_time_seconds: Option<f64>,
    pub total_time_seconds: Option<f64>,
    pub ocr_provider_diagnostics: Option<OcrProviderDiagnostics>,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default, PartialEq, Eq)]
pub struct JobArtifactRecord {
    pub job_id: String,
    pub artifact_key: String,
    pub artifact_group: String,
    pub artifact_kind: String,
    pub relative_path: String,
    pub file_name: Option<String>,
    pub content_type: String,
    pub ready: bool,
    pub size_bytes: Option<u64>,
    pub checksum: Option<String>,
    pub source_stage: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
pub struct ProcessResult {
    pub success: bool,
    pub return_code: i32,
    pub duration_seconds: f64,
    pub command: Vec<String>,
    pub cwd: String,
    pub stdout: String,
    pub stderr: String,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default, PartialEq, Eq)]
pub struct JobStageTiming {
    pub stage: String,
    pub detail: Option<String>,
    pub enter_at: String,
    pub exit_at: Option<String>,
    pub duration_ms: Option<i64>,
    pub terminal_status: Option<JobStatusKind>,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default, PartialEq, Eq)]
pub struct JobRuntimeInfo {
    pub current_stage: Option<String>,
    pub stage_started_at: Option<String>,
    pub last_stage_transition_at: Option<String>,
    pub terminal_reason: Option<String>,
    pub last_error_at: Option<String>,
    pub total_elapsed_ms: Option<i64>,
    pub active_stage_elapsed_ms: Option<i64>,
    pub retry_count: u32,
    pub last_retry_at: Option<String>,
    pub stage_history: Vec<JobStageTiming>,
    pub final_failure_category: Option<String>,
    pub final_failure_summary: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default, PartialEq, Eq)]
pub struct JobFailureInfo {
    pub stage: String,
    pub category: String,
    pub code: Option<String>,
    pub summary: String,
    pub root_cause: Option<String>,
    pub retryable: bool,
    pub upstream_host: Option<String>,
    pub provider: Option<String>,
    pub suggestion: Option<String>,
    pub last_log_line: Option<String>,
    pub raw_error_excerpt: Option<String>,
    pub raw_diagnostic: Option<JobRawDiagnostic>,
    pub ai_diagnostic: Option<JobAiDiagnostic>,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default, PartialEq, Eq)]
pub struct JobRawDiagnostic {
    pub structured_error_type: Option<String>,
    pub raw_exception_type: Option<String>,
    pub raw_exception_message: Option<String>,
    pub traceback: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default, PartialEq, Eq)]
pub struct JobAiDiagnostic {
    pub summary: String,
    pub root_cause: Option<String>,
    pub suggestion: Option<String>,
    pub confidence: Option<String>,
    pub observed_signals: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct JobRecord {
    pub job_id: String,
    pub workflow: WorkflowKind,
    pub status: JobStatusKind,
    pub created_at: String,
    pub updated_at: String,
    pub started_at: Option<String>,
    pub finished_at: Option<String>,
    pub upload_id: Option<String>,
    pub pid: Option<u32>,
    pub command: Vec<String>,
    pub request_payload: ResolvedJobSpec,
    pub error: Option<String>,
    pub stage: Option<String>,
    pub stage_detail: Option<String>,
    pub progress_current: Option<i64>,
    pub progress_total: Option<i64>,
    pub log_tail: Vec<String>,
    pub result: Option<ProcessResult>,
    pub runtime: Option<JobRuntimeInfo>,
    pub failure: Option<JobFailureInfo>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct JobSnapshot {
    pub record: JobRecord,
    pub artifacts: Option<JobArtifacts>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct JobRuntimeState {
    pub record: JobRecord,
    pub artifacts: Option<JobArtifacts>,
}

impl Deref for JobSnapshot {
    type Target = JobRecord;

    fn deref(&self) -> &Self::Target {
        &self.record
    }
}

impl DerefMut for JobSnapshot {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.record
    }
}

impl Deref for JobRuntimeState {
    type Target = JobRecord;

    fn deref(&self) -> &Self::Target {
        &self.record
    }
}

impl DerefMut for JobRuntimeState {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.record
    }
}

fn append_log_line(log_tail: &mut Vec<String>, line: &str) {
    let text = line.trim();
    if text.is_empty() {
        return;
    }
    log_tail.push(text.to_string());
    if log_tail.len() > LOG_TAIL_LIMIT {
        let drain = log_tail.len() - LOG_TAIL_LIMIT;
        log_tail.drain(0..drain);
    }
}

fn terminal_reason_for_status(status: &JobStatusKind) -> Option<String> {
    match status {
        JobStatusKind::Succeeded => Some("succeeded".to_string()),
        JobStatusKind::Failed => Some("failed".to_string()),
        JobStatusKind::Canceled => Some("canceled".to_string()),
        JobStatusKind::Queued | JobStatusKind::Running => None,
    }
}

fn parse_iso_timestamp(value: &str) -> Option<DateTime<Utc>> {
    chrono::DateTime::parse_from_rfc3339(value)
        .ok()
        .map(|dt| dt.with_timezone(&Utc))
}

fn duration_ms_between(start: &str, end: &str) -> Option<i64> {
    let start = parse_iso_timestamp(start)?;
    let end = parse_iso_timestamp(end)?;
    Some((end - start).num_milliseconds().max(0))
}

impl JobRecord {
    fn ensure_runtime_info(&mut self) -> &mut JobRuntimeInfo {
        if self.runtime.is_none() {
            self.runtime = Some(JobRuntimeInfo::default());
        }
        self.runtime.as_mut().unwrap()
    }

    fn sync_runtime_info(&mut self) {
        let updated_at = self.updated_at.clone();
        let stage = self.stage.clone();
        let stage_detail = self.stage_detail.clone();
        let terminal_reason = terminal_reason_for_status(&self.status);
        let started_at = self.started_at.clone();
        let finished_at = self
            .finished_at
            .clone()
            .unwrap_or_else(|| updated_at.clone());
        let failure = self.failure.clone();

        let runtime = self.ensure_runtime_info();
        let previous_stage = runtime.current_stage.clone();
        let previous_stage_started_at = runtime.stage_started_at.clone();

        if previous_stage != stage {
            close_active_stage_entry(
                runtime,
                previous_stage.as_deref(),
                previous_stage_started_at.as_deref(),
                &updated_at,
                terminal_reason.as_ref(),
            );

            runtime.current_stage = stage.clone();
            runtime.stage_started_at = Some(updated_at.clone());
            runtime.last_stage_transition_at = Some(updated_at.clone());

            if let Some(stage_name) = stage.as_ref() {
                runtime.stage_history.push(JobStageTiming {
                    stage: stage_name.clone(),
                    detail: stage_detail.clone(),
                    enter_at: updated_at.clone(),
                    exit_at: None,
                    duration_ms: None,
                    terminal_status: None,
                });
            }
        } else if let Some(active) = runtime
            .stage_history
            .last_mut()
            .filter(|entry| entry.exit_at.is_none())
        {
            active.detail = stage_detail.clone();
        }

        if terminal_reason.is_some() {
            let current_stage_started_at = runtime.stage_started_at.clone();
            close_active_stage_entry(
                runtime,
                stage.as_deref(),
                current_stage_started_at.as_deref(),
                &finished_at,
                terminal_reason.as_ref(),
            );
        }

        runtime.terminal_reason = terminal_reason;
        runtime.active_stage_elapsed_ms = runtime
            .stage_started_at
            .as_deref()
            .and_then(|start| duration_ms_between(start, &updated_at));
        runtime.total_elapsed_ms = started_at
            .as_deref()
            .and_then(|start| duration_ms_between(start, &finished_at));
        runtime.final_failure_category = failure.as_ref().map(|item| item.category.clone());
        runtime.final_failure_summary = failure.as_ref().map(|item| item.summary.clone());
    }

    fn replace_failure_info(&mut self, failure: Option<JobFailureInfo>) {
        let updated_at = self.updated_at.clone();
        self.failure = failure;
        let has_failure = self.failure.is_some();
        let status_is_failed = matches!(self.status, JobStatusKind::Failed);
        let final_failure_category = self.failure.as_ref().map(|item| item.category.clone());
        let final_failure_summary = self.failure.as_ref().map(|item| item.summary.clone());
        let runtime = self.ensure_runtime_info();
        if has_failure {
            runtime.last_error_at = Some(updated_at);
            runtime.terminal_reason = Some("failed".to_string());
        } else if !status_is_failed {
            runtime.last_error_at = None;
        }
        runtime.final_failure_category = final_failure_category;
        runtime.final_failure_summary = final_failure_summary;
    }

    fn register_retry(&mut self) {
        let updated_at = self.updated_at.clone();
        let runtime = self.ensure_runtime_info();
        runtime.retry_count = runtime.retry_count.saturating_add(1);
        runtime.last_retry_at = Some(updated_at);
    }
}

fn close_active_stage_entry(
    runtime: &mut JobRuntimeInfo,
    stage: Option<&str>,
    stage_started_at: Option<&str>,
    exit_at: &str,
    terminal_reason: Option<&String>,
) {
    let Some(stage_name) = stage.filter(|value| !value.trim().is_empty()) else {
        return;
    };
    let Some(active) = runtime
        .stage_history
        .iter_mut()
        .rev()
        .find(|entry| entry.stage == stage_name && entry.exit_at.is_none())
    else {
        return;
    };
    let enter_at = stage_started_at.unwrap_or(active.enter_at.as_str());
    active.exit_at = Some(exit_at.to_string());
    active.duration_ms = duration_ms_between(enter_at, exit_at);
    active.terminal_status = terminal_reason.and_then(|reason| match reason.as_str() {
        "succeeded" => Some(JobStatusKind::Succeeded),
        "failed" => Some(JobStatusKind::Failed),
        "canceled" => Some(JobStatusKind::Canceled),
        _ => None,
    });
}

impl JobSnapshot {
    pub fn new<T: Into<ResolvedJobSpec>>(
        job_id: String,
        request_payload: T,
        command: Vec<String>,
    ) -> Self {
        let request_payload: ResolvedJobSpec = request_payload.into();
        let now = now_iso();
        let provider_kind = parse_provider_kind(&request_payload.ocr.provider);
        Self {
            record: JobRecord {
                job_id,
                workflow: request_payload.workflow.clone(),
                status: JobStatusKind::Queued,
                created_at: now.clone(),
                updated_at: now,
                started_at: None,
                finished_at: None,
                upload_id: Some(request_payload.source.upload_id.clone()),
                pid: None,
                command,
                request_payload,
                error: None,
                stage: Some("queued".to_string()),
                stage_detail: Some("任务已创建，等待可用执行槽位".to_string()),
                progress_current: Some(0),
                progress_total: None,
                log_tail: Vec::new(),
                result: None,
                runtime: None,
                failure: None,
            },
            artifacts: Some(JobArtifacts {
                ocr_provider_diagnostics: Some(OcrProviderDiagnostics::new(provider_kind)),
                ..JobArtifacts::default()
            }),
        }
        .with_synced_runtime()
    }

    pub fn into_runtime(self) -> JobRuntimeState {
        JobRuntimeState {
            record: self.record,
            artifacts: self.artifacts,
        }
    }

    pub fn append_log(&mut self, line: &str) {
        append_log_line(&mut self.record.log_tail, line);
    }

    pub fn sync_runtime_state(&mut self) {
        self.record.sync_runtime_info();
    }

    pub fn replace_failure_info(&mut self, failure: Option<JobFailureInfo>) {
        self.record.replace_failure_info(failure);
    }

    pub fn register_retry(&mut self) {
        self.record.register_retry();
    }

    fn with_synced_runtime(mut self) -> Self {
        self.sync_runtime_state();
        self
    }
}

impl JobRuntimeState {
    pub fn snapshot(&self) -> JobSnapshot {
        JobSnapshot {
            record: self.record.clone(),
            artifacts: self.artifacts.clone(),
        }
    }

    pub fn into_snapshot(self) -> JobSnapshot {
        JobSnapshot {
            record: self.record,
            artifacts: self.artifacts,
        }
    }

    pub fn append_log(&mut self, line: &str) {
        append_log_line(&mut self.record.log_tail, line);
    }

    pub fn sync_runtime_state(&mut self) {
        self.record.sync_runtime_info();
    }

    pub fn replace_failure_info(&mut self, failure: Option<JobFailureInfo>) {
        self.record.replace_failure_info(failure);
    }

    pub fn register_retry(&mut self) {
        self.record.register_retry();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::CreateJobInput;

    #[test]
    fn sync_runtime_state_tracks_stage_history_and_elapsed() {
        let mut job = JobSnapshot::new(
            "job-runtime-metrics".to_string(),
            CreateJobInput::default(),
            vec!["python".to_string()],
        );
        job.started_at = Some("2026-04-04T00:00:00Z".to_string());
        job.updated_at = "2026-04-04T00:00:05Z".to_string();
        job.stage = Some("running".to_string());
        job.stage_detail = Some("正在运行".to_string());
        job.sync_runtime_state();

        job.updated_at = "2026-04-04T00:00:12Z".to_string();
        job.stage = Some("rendering".to_string());
        job.stage_detail = Some("正在渲染".to_string());
        job.sync_runtime_state();

        job.updated_at = "2026-04-04T00:00:20Z".to_string();
        job.finished_at = Some("2026-04-04T00:00:20Z".to_string());
        job.status = JobStatusKind::Succeeded;
        job.sync_runtime_state();

        let runtime = job.runtime.as_ref().expect("runtime");
        assert_eq!(runtime.stage_history.len(), 3);
        assert_eq!(runtime.total_elapsed_ms, Some(20_000));
        assert_eq!(runtime.retry_count, 0);
        assert_eq!(runtime.stage_history[0].stage, "queued");
        assert_eq!(runtime.stage_history[1].duration_ms, Some(7_000));
        assert_eq!(
            runtime
                .stage_history
                .last()
                .and_then(|item| item.duration_ms),
            Some(8_000)
        );
    }

    #[test]
    fn register_retry_updates_runtime_retry_counters() {
        let mut job = JobSnapshot::new(
            "job-runtime-retry".to_string(),
            CreateJobInput::default(),
            vec!["python".to_string()],
        );
        job.updated_at = "2026-04-04T00:00:10Z".to_string();
        job.register_retry();
        job.register_retry();

        let runtime = job.runtime.as_ref().expect("runtime");
        assert_eq!(runtime.retry_count, 2);
        assert_eq!(
            runtime.last_retry_at.as_deref(),
            Some("2026-04-04T00:00:10Z")
        );
    }
}
