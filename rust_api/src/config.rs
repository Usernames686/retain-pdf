use std::collections::HashSet;
use std::env;
use std::path::PathBuf;

use anyhow::{bail, Context, Result};
use serde::Deserialize;

#[derive(Clone, Debug)]
pub struct AppConfig {
    pub project_root: PathBuf,
    pub rust_api_root: PathBuf,
    pub scripts_dir: PathBuf,
    pub run_mineru_case_script: PathBuf,
    pub uploads_dir: PathBuf,
    pub downloads_dir: PathBuf,
    pub jobs_db_path: PathBuf,
    pub output_root: PathBuf,
    pub python_bin: String,
    pub port: u16,
    pub simple_port: u16,
    pub normal_max_bytes: u64,
    pub normal_max_pages: u32,
    pub api_keys: HashSet<String>,
    pub max_running_jobs: usize,
}

#[derive(Debug, Deserialize)]
struct LocalAuthConfig {
    #[serde(default)]
    api_keys: Vec<String>,
    max_running_jobs: Option<usize>,
    simple_port: Option<u16>,
}

impl AppConfig {
    pub fn from_env() -> Result<Self> {
        let rust_api_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let project_root = rust_api_root
            .parent()
            .context("rust_api must live directly under project root")?
            .to_path_buf();
        let scripts_dir = project_root.join("scripts");
        let run_mineru_case_script = scripts_dir.join("entrypoints").join("run_mineru_case.py");
        let uploads_dir = rust_api_root.join("uploads");
        let downloads_dir = rust_api_root.join("downloads");
        let jobs_db_path = rust_api_root.join("jobs.db");
        let output_root = project_root.join("output");
        let auth_config_path = rust_api_root.join("auth.local.json");

        std::fs::create_dir_all(&uploads_dir)?;
        std::fs::create_dir_all(&downloads_dir)?;

        let local_auth = load_local_auth_config(&auth_config_path)?;
        let api_keys = resolve_api_keys(local_auth.as_ref())?;
        let max_running_jobs = resolve_max_running_jobs(local_auth.as_ref());

        Ok(Self {
            project_root,
            rust_api_root,
            scripts_dir,
            run_mineru_case_script,
            uploads_dir,
            downloads_dir,
            jobs_db_path,
            output_root,
            python_bin: env::var("PYTHON_BIN").unwrap_or_else(|_| "python".to_string()),
            port: env::var("RUST_API_PORT")
                .ok()
                .and_then(|v| v.parse::<u16>().ok())
                .unwrap_or(41000),
            simple_port: resolve_simple_port(local_auth.as_ref()),
            normal_max_bytes: env::var("RUST_API_NORMAL_MAX_BYTES")
                .ok()
                .and_then(|v| v.parse::<u64>().ok())
                .unwrap_or(10 * 1024 * 1024),
            normal_max_pages: env::var("RUST_API_NORMAL_MAX_PAGES")
                .ok()
                .and_then(|v| v.parse::<u32>().ok())
                .unwrap_or(30),
            api_keys,
            max_running_jobs,
        })
    }
}

fn load_local_auth_config(path: &PathBuf) -> Result<Option<LocalAuthConfig>> {
    if !path.exists() {
        return Ok(None);
    }
    let text = std::fs::read_to_string(path)
        .with_context(|| format!("failed to read {}", path.display()))?;
    let config: LocalAuthConfig = serde_json::from_str(&text)
        .with_context(|| format!("failed to parse {}", path.display()))?;
    Ok(Some(config))
}

fn resolve_api_keys(local_auth: Option<&LocalAuthConfig>) -> Result<HashSet<String>> {
    if let Some(local_auth) = local_auth {
        let keys: HashSet<String> = local_auth
            .api_keys
            .iter()
            .map(String::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(ToOwned::to_owned)
            .collect();
        if !keys.is_empty() {
            return Ok(keys);
        }
    }

    let raw = env::var("RUST_API_KEYS")
        .context("auth.local.json or RUST_API_KEYS is required and must contain at least one API key")?;
    let keys: HashSet<String> = raw
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
        .collect();
    if keys.is_empty() {
        bail!("auth.local.json or RUST_API_KEYS is required and must contain at least one API key");
    }
    Ok(keys)
}

fn resolve_max_running_jobs(local_auth: Option<&LocalAuthConfig>) -> usize {
    if let Some(value) = local_auth
        .and_then(|cfg| cfg.max_running_jobs)
        .filter(|value| *value > 0)
    {
        return value;
    }
    env::var("RUST_API_MAX_RUNNING_JOBS")
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
        .filter(|v| *v > 0)
        .unwrap_or(4)
}

fn resolve_simple_port(local_auth: Option<&LocalAuthConfig>) -> u16 {
    if let Some(value) = local_auth.and_then(|cfg| cfg.simple_port) {
        return value;
    }
    env::var("RUST_API_SIMPLE_PORT")
        .ok()
        .and_then(|v| v.parse::<u16>().ok())
        .unwrap_or(42000)
}
