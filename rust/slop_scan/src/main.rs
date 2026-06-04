use clap::Parser;
use globset::{Glob, GlobSet, GlobSetBuilder};
use serde::Serialize;
use std::collections::HashSet;
use std::error::Error;
use std::path::PathBuf;
use walkdir::{DirEntry, WalkDir};

const DEFAULT_EXCLUDE_PARTS: &[&str] = &[
    ".venv",
    "venv",
    "site-packages",
    "node_modules",
    "__pycache__",
    ".git",
];

#[derive(Parser, Debug)]
#[command(
    name = "slop_scan",
    about = "Rust file discovery hot-path for slop-detector"
)]
struct Args {
    #[arg(long)]
    root: PathBuf,
    #[arg(long = "include")]
    include: Vec<String>,
    #[arg(long = "ignore")]
    ignore: Vec<String>,
}

#[derive(Serialize)]
struct ScanOutput {
    files: Vec<String>,
}

fn build_globset(patterns: &[String]) -> Result<GlobSet, Box<dyn Error>> {
    let mut builder = GlobSetBuilder::new();
    for pattern in patterns {
        builder.add(Glob::new(pattern)?);
    }
    Ok(builder.build()?)
}

fn has_excluded_part(entry: &DirEntry) -> bool {
    entry.path().components().any(|component| {
        let part = component.as_os_str().to_string_lossy();
        DEFAULT_EXCLUDE_PARTS
            .iter()
            .any(|excluded| part == *excluded)
    })
}

fn keep_entry(entry: &DirEntry) -> bool {
    !has_excluded_part(entry)
}

fn main() -> Result<(), Box<dyn Error>> {
    let args = Args::parse();
    let root = args.root.canonicalize()?;
    let include_patterns = if args.include.is_empty() {
        vec!["**/*".to_string()]
    } else {
        args.include.clone()
    };
    let include_set = build_globset(&include_patterns)?;
    let ignore_set = build_globset(&args.ignore)?;
    let ignore_parts: HashSet<&str> = DEFAULT_EXCLUDE_PARTS.iter().copied().collect();

    let mut files = Vec::new();
    for entry in WalkDir::new(&root)
        .follow_links(false)
        .into_iter()
        .filter_entry(|entry| keep_entry(entry))
    {
        let entry = match entry {
            Ok(entry) => entry,
            Err(_) => continue,
        };
        if !entry.file_type().is_file() {
            continue;
        }
        let path = entry.path();
        if path
            .components()
            .any(|component| ignore_parts.contains(component.as_os_str().to_str().unwrap_or("")))
        {
            continue;
        }
        let rel = match path.strip_prefix(&root) {
            Ok(value) => value,
            Err(_) => continue,
        };
        let rel_str = rel.to_string_lossy().replace('\\', "/");
        if ignore_set.is_match(&rel_str) {
            continue;
        }
        if !include_set.is_match(&rel_str) {
            continue;
        }
        files.push(path.to_string_lossy().to_string());
    }

    files.sort();
    files.dedup();
    println!("{}", serde_json::to_string(&ScanOutput { files })?);
    Ok(())
}
