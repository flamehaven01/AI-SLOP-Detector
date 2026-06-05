"use strict";

const { EventEmitter } = require("node:events");
const { spawn } = require("node:child_process");

const { buildInvocation, discoverBackend } = require("./runtime");

function _collectText(stream, chunks) {
  if (!stream || typeof stream.on !== "function") {
    return;
  }
  stream.on("data", (chunk) => {
    chunks.push(Buffer.isBuffer(chunk) ? chunk.toString("utf8") : String(chunk));
  });
}

function _createBackendNotFoundError() {
  return new Error(
    "[ai-slop-detector npm api] Python backend not found. " +
      "Install the Python package or set AI_SLOP_DETECTOR_EXECUTABLE.",
  );
}

function runJsonCommand(forwardedArgs, options = {}) {
  const spawnImpl = options.spawnImpl || spawn;
  const candidate = options.candidate || discoverBackend(options);
  if (!candidate) {
    return Promise.reject(_createBackendNotFoundError());
  }

  const invocation = buildInvocation(candidate, forwardedArgs);

  return new Promise((resolve, reject) => {
    const child = spawnImpl(invocation.command, invocation.args, {
      stdio: ["ignore", "pipe", "pipe"],
    });

    const stdoutChunks = [];
    const stderrChunks = [];
    _collectText(child.stdout, stdoutChunks);
    _collectText(child.stderr, stderrChunks);

    child.on("error", reject);
    child.on("exit", (code, signal) => {
      const stdout = stdoutChunks.join("");
      const stderr = stderrChunks.join("");

      if (signal || code !== 0) {
        const error = new Error(
          stderr.trim() ||
            `ai-slop-detector backend exited with code ${typeof code === "number" ? code : 1}`,
        );
        error.code = typeof code === "number" ? code : 1;
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }

      try {
        resolve(JSON.parse(stdout));
      } catch (parseError) {
        parseError.message =
          `[ai-slop-detector npm api] Failed to parse JSON output: ${parseError.message}`;
        parseError.stdout = stdout;
        parseError.stderr = stderr;
        reject(parseError);
      }
    });
  });
}

function scanProject(root = ".", options = {}) {
  return runJsonCommand(["scan", root, "--format", "json"], options);
}

function scanFile(filePath, options = {}) {
  return runJsonCommand(["scan", filePath, "--format", "json"], options);
}

function reviewChanges(root = ".", options = {}) {
  const args = ["review", root, "--format", "json"];
  if (options.base) {
    args.push("--base", options.base);
  }
  return runJsonCommand(args, options);
}

function computeHealth(root = ".", options = {}) {
  return runJsonCommand(["pulse", root, "--format", "json"], options);
}

function runCleanupFamily(family, root = ".", options = {}) {
  return runJsonCommand(["sweep", family, root, "--format", "json"], options);
}

function explain(identifier, options = {}) {
  return runJsonCommand(["explain", identifier, "--format", "json"], options);
}

module.exports = {
  computeHealth,
  explain,
  reviewChanges,
  runCleanupFamily,
  runJsonCommand,
  scanFile,
  scanProject,
};
