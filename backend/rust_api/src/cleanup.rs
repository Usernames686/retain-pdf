use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration as StdDuration;

use anyhow::{Context, Result};
use chrono::{Duration, Utc};
use tokio::sync::Notify;

use crate::config::AppConfig;
use crate::db::Db;
use crate::models::JobSnapshot;
use crate::storage_paths::resolve_data_path;
use crate::AppState;

#[derive(Debug, Default)]
pub struct CleanupSummary {
    pub jobs_deleted: usize,
    pub paths_deleted: usize,
}

pub fn spawn_retention_cleanup(state: AppState, shutdown_signal: Arc<Notify>) {
    if state.config.job_retention_days == 0 {
        tracing::info!("job retention cleanup disabled");
        return;
    }

    tokio::spawn(async move {
        run_cleanup_once(state.clone()).await;
        let interval_hours = state.config.cleanup_interval_hours.max(1);
        let mut interval =
            tokio::time::interval(StdDuration::from_secs(interval_hours.saturating_mul(3600)));
        loop {
            tokio::select! {
                _ = shutdown_signal.notified() => break,
                _ = interval.tick() => run_cleanup_once(state.clone()).await,
            }
        }
    });
}

async fn run_cleanup_once(state: AppState) {
    let config = state.config.clone();
    let db = state.db.clone();
    match tokio::task::spawn_blocking(move || cleanup_expired_jobs(&config, &db)).await {
        Ok(Ok(summary)) => {
            if summary.jobs_deleted > 0 || summary.paths_deleted > 0 {
                tracing::info!(
                    jobs_deleted = summary.jobs_deleted,
                    paths_deleted = summary.paths_deleted,
                    "job retention cleanup completed"
                );
            }
        }
        Ok(Err(err)) => tracing::warn!(error = %err, "job retention cleanup failed"),
        Err(err) => tracing::warn!(error = %err, "job retention cleanup task failed"),
    }
}

pub fn cleanup_expired_jobs(config: &AppConfig, db: &Db) -> Result<CleanupSummary> {
    if config.job_retention_days == 0 {
        return Ok(CleanupSummary::default());
    }

    let cutoff = Utc::now() - Duration::days(config.job_retention_days as i64);
    let cutoff_iso = cutoff.to_rfc3339();
    let expired_jobs = db.list_expired_terminal_jobs(&cutoff_iso)?;
    let mut summary = CleanupSummary::default();

    for job in expired_jobs {
        match cleanup_one_job(config, db, &job) {
            Ok(paths_deleted) => {
                summary.jobs_deleted += 1;
                summary.paths_deleted += paths_deleted;
            }
            Err(err) => {
                tracing::warn!(
                    job_id = %job.job_id,
                    error = %err,
                    "failed to cleanup expired job; will retry later"
                );
            }
        }
    }

    Ok(summary)
}

fn cleanup_one_job(config: &AppConfig, db: &Db, job: &JobSnapshot) -> Result<usize> {
    let mut paths = cleanup_paths_for_job(config, job);
    let mut deleted = 0usize;
    for path in paths.drain() {
        deleted += remove_path_if_safe(&config.data_root, &path)
            .with_context(|| format!("failed to remove {}", path.display()))?;
    }
    db.delete_job_records(&job.job_id)?;
    Ok(deleted)
}

fn cleanup_paths_for_job(config: &AppConfig, job: &JobSnapshot) -> HashSet<PathBuf> {
    let mut paths = HashSet::new();
    paths.insert(config.output_root.join(&job.job_id));
    paths.insert(config.downloads_dir.join(format!("{}.zip", job.job_id)));
    paths.insert(
        config
            .downloads_dir
            .join(format!("{}-markdown.zip", job.job_id)),
    );

    if let Some(job_root) = job
        .artifacts
        .as_ref()
        .and_then(|artifacts| artifacts.job_root.as_ref())
        .and_then(|raw| resolve_data_path(&config.data_root, raw).ok())
    {
        paths.insert(job_root);
    }

    paths
}

fn remove_path_if_safe(data_root: &Path, path: &Path) -> Result<usize> {
    if !path.exists() {
        return Ok(0);
    }

    let data_root = fs::canonicalize(data_root)
        .with_context(|| format!("failed to canonicalize data root {}", data_root.display()))?;
    let canonical = fs::canonicalize(path)
        .with_context(|| format!("failed to canonicalize cleanup path {}", path.display()))?;
    if !canonical.starts_with(&data_root) {
        anyhow::bail!("refusing to delete path outside data root: {}", path.display());
    }

    let metadata = fs::symlink_metadata(&canonical)?;
    if metadata.is_dir() {
        fs::remove_dir_all(&canonical)?;
    } else {
        fs::remove_file(&canonical)?;
    }
    Ok(1)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::{JobRecord, JobStatusKind, WorkflowKind};

    fn sample_config(root: PathBuf) -> AppConfig {
        AppConfig::from_desktop(
            root.join("resources"),
            root.join("data"),
            "python".to_string(),
            41000,
            42000,
            "test-key".to_string(),
        )
        .expect("config")
    }

    fn sample_job(job_id: &str, updated_at: String) -> JobSnapshot {
        JobSnapshot {
            record: JobRecord {
                job_id: job_id.to_string(),
                workflow: WorkflowKind::Mineru,
                status: JobStatusKind::Succeeded,
                created_at: updated_at.clone(),
                updated_at,
                started_at: None,
                finished_at: None,
                upload_id: None,
                pid: None,
                command: vec![],
                request_payload: Default::default(),
                error: None,
                stage: None,
                stage_detail: None,
                progress_current: None,
                progress_total: None,
                log_tail: vec![],
                result: None,
                runtime: None,
                failure: None,
            },
            artifacts: None,
        }
    }

    #[test]
    fn cleanup_removes_only_expired_terminal_jobs() {
        let root = std::env::temp_dir().join(format!(
            "retainpdf-cleanup-test-{}",
            fastrand::u32(..=u32::MAX)
        ));
        let config = sample_config(root.clone());
        let db = Db::new(config.jobs_db_path.clone(), config.data_root.clone());
        db.init().expect("init db");

        let old = (Utc::now() - Duration::days(31)).to_rfc3339();
        let fresh = Utc::now().to_rfc3339();
        let old_job = sample_job("old-job", old);
        let fresh_job = sample_job("fresh-job", fresh);
        db.save_job(&old_job).expect("save old");
        db.save_job(&fresh_job).expect("save fresh");

        fs::create_dir_all(config.output_root.join("old-job")).expect("old dir");
        fs::write(config.downloads_dir.join("old-job.zip"), b"zip").expect("old zip");
        fs::create_dir_all(config.output_root.join("fresh-job")).expect("fresh dir");

        let summary = cleanup_expired_jobs(&config, &db).expect("cleanup");

        assert_eq!(summary.jobs_deleted, 1);
        assert!(!config.output_root.join("old-job").exists());
        assert!(!config.downloads_dir.join("old-job.zip").exists());
        assert!(config.output_root.join("fresh-job").exists());
        assert!(db.get_job("old-job").is_err());
        assert!(db.get_job("fresh-job").is_ok());

        let _ = fs::remove_dir_all(root);
    }
}
