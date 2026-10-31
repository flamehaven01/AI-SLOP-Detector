"use strict";

const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

const PACKAGE_VERSION = require("../package.json").version;

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

  // Nothing installed: run the PyPI release of this package's own version
  // through uv (which can also fetch Python) or pipx.
  const spec = `ai-slop-detector==${options.version || PACKAGE_VERSION}`;
  candidates.push(
    {
      kind: "fetch",
      command: "uvx",
      args: ["--from", spec, "slop-detector"],
      label: `uvx ${spec}`,
    },
    {
      kind: "fetch",
      command: "pipx",
      args: ["run", "--spec", spec, "slop-detector"],
      label: `pipx run ${spec}`,
    },
  );

  return candidates;
}

function _probeArgs(candidate) {
  if (candidate.kind === "module") {
    return [...candidate.args, "--version"];
  }
  // A fetch candidate is probed for the tool alone: probing the package would
  // download it before the user's command runs.
  return ["--version"];
}

function _probe(candidate, options) {
  const probe = options.probeImpl || spawnSync;
  return probe(candidate.command, _probeArgs(candidate), {
    encoding: "utf8",
    stdio: "pipe",
  });
}

function probeCandidate(candidate, options = {}) {
  const result = _probe(candidate, options);
  return Boolean(result && result.status === 0);
}

function _reportedVersion(result) {
  const match = /ai-slop-detector (\S+)/.exec((result && result.stdout) || "");
  return match ? match[1] : null;
}

function discoverBackend(options = {}) {
  const candidates = buildBackendCandidates(options);
  for (const candidate of candidates) {
    const result = _probe(candidate, options);
    if (result && result.status === 0) {
      // A fetch candidate runs this package's own version; an installed one
      // reports its version, which may be older or newer than the wrapper.
      return candidate.kind === "fetch" ? candidate : { ...candidate, version: _reportedVersion(result) };
    }
  }
  return null;
}

function _versionWarning(candidate, expected) {
  if (!candidate.version || candidate.version === expected) {
    return null;
  }
  return (
    `[ai-slop-detector npm wrapper] using backend ${candidate.version} ` +
    `(${candidate.label}); this wrapper is ${expected}. Output follows the backend's version.\n`
  );
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
        "Run `pip install ai-slop-detector`, install uv (https://docs.astral.sh/uv/) " +
        "or pipx, or set AI_SLOP_DETECTOR_EXECUTABLE.\n",
    );
    return Promise.resolve(1);
  }

  const warning = _versionWarning(candidate, options.version || PACKAGE_VERSION);
  if (warning) {
    stderr.write(warning);
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
