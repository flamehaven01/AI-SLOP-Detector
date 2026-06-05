"use strict";

const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

function _scriptDirName(platform) {
  return platform === "win32" ? "Scripts" : "bin";
}

function _scriptExtension(platform) {
  return platform === "win32" ? ".exe" : "";
}

function _platformPath(platform) {
  return platform === "win32" ? path.win32 : path.posix;
}

function buildBackendCandidates(options = {}) {
  const env = options.env || process.env;
  const platform = options.platform || process.platform;
  const candidates = [];

  const explicitExecutable = env.AI_SLOP_DETECTOR_EXECUTABLE;
  if (explicitExecutable) {
    candidates.push({
      kind: "direct",
      command: explicitExecutable,
      args: [],
      label: "env:AI_SLOP_DETECTOR_EXECUTABLE",
    });
  }

  const venv = env.VIRTUAL_ENV;
  if (venv) {
    const platformPath = _platformPath(platform);
    const scriptsDir = platformPath.join(venv, _scriptDirName(platform));
    const extension = _scriptExtension(platform);
    candidates.push(
      {
        kind: "direct",
        command: platformPath.join(scriptsDir, `ai-slop-detector${extension}`),
        args: [],
        label: "venv:ai-slop-detector",
      },
      {
        kind: "direct",
        command: platformPath.join(scriptsDir, `slop-detector${extension}`),
        args: [],
        label: "venv:slop-detector",
      },
    );
  }

  candidates.push(
    { kind: "direct", command: "ai-slop-detector", args: [], label: "path:ai-slop-detector" },
    { kind: "direct", command: "slop-detector", args: [], label: "path:slop-detector" },
    {
      kind: "module",
      command: "python",
      args: ["-m", "slop_detector.cli"],
      label: "python -m slop_detector.cli",
    },
    {
      kind: "module",
      command: "python3",
      args: ["-m", "slop_detector.cli"],
      label: "python3 -m slop_detector.cli",
    },
  );

  if (platform === "win32") {
    candidates.push({
      kind: "module",
      command: "py",
      args: ["-m", "slop_detector.cli"],
      label: "py -m slop_detector.cli",
    });
  }

  return candidates;
}

function _probeArgs(candidate) {
  if (candidate.kind === "module") {
    return [...candidate.args, "--version"];
  }
  return ["--version"];
}

function probeCandidate(candidate, options = {}) {
  const probe = options.probeImpl || spawnSync;
  const result = probe(candidate.command, _probeArgs(candidate), {
    encoding: "utf8",
    stdio: "pipe",
  });
  return Boolean(result && result.status === 0);
}

function discoverBackend(options = {}) {
  const candidates = buildBackendCandidates(options);
  for (const candidate of candidates) {
    if (probeCandidate(candidate, options)) {
      return candidate;
    }
  }
  return null;
}

function buildInvocation(candidate, forwardedArgs) {
  return {
    command: candidate.command,
    args: [...candidate.args, ...forwardedArgs],
  };
}

function runWrapper(forwardedArgs, options = {}) {
  const spawnImpl = options.spawnImpl || spawn;
  const stderr = options.stderr || process.stderr;
  const stdio = options.stdio || "inherit";
  const candidate = options.candidate || discoverBackend(options);

  if (!candidate) {
    stderr.write(
      "[ai-slop-detector npm wrapper] Python backend not found. " +
        "Install the Python package or set AI_SLOP_DETECTOR_EXECUTABLE.\n",
    );
    return Promise.resolve(1);
  }

  const invocation = buildInvocation(candidate, forwardedArgs);

  return new Promise((resolve, reject) => {
    const child = spawnImpl(invocation.command, invocation.args, { stdio });
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      if (signal) {
        resolve(1);
        return;
      }
      resolve(typeof code === "number" ? code : 1);
    });
  });
}

module.exports = {
  buildBackendCandidates,
  buildInvocation,
  discoverBackend,
  probeCandidate,
  runWrapper,
};
