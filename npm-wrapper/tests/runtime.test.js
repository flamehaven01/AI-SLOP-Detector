"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");

const {
  buildBackendCandidates,
  buildInvocation,
  discoverBackend,
  runWrapper,
} = require("../lib/runtime");

test("buildBackendCandidates prefers explicit executable override", () => {
  const candidates = buildBackendCandidates({
    env: {
      AI_SLOP_DETECTOR_EXECUTABLE: "/custom/ai-slop-detector",
      VIRTUAL_ENV: "/venv",
    },
    platform: "linux",
  });

  assert.equal(candidates[0].command, "/custom/ai-slop-detector");
  assert.equal(candidates[0].label, "env:AI_SLOP_DETECTOR_EXECUTABLE");
});

test("discoverBackend returns first healthy candidate", () => {
  const seen = [];
  const backend = discoverBackend({
    env: { VIRTUAL_ENV: "/venv" },
    platform: "linux",
    probeImpl(command) {
      seen.push(command);
      return { status: command.endsWith("/slop-detector") ? 0 : 1 };
    },
  });

  assert.ok(backend);
  assert.equal(backend.command, "/venv/bin/slop-detector");
  assert.deepEqual(seen.slice(0, 2), [
    "/venv/bin/ai-slop-detector",
    "/venv/bin/slop-detector",
  ]);
});

test("buildInvocation preserves forwarded arguments", () => {
  const invocation = buildInvocation(
    {
      command: "python",
      args: ["-m", "slop_detector.cli"],
    },
    ["scan", ".", "--json"],
  );

  assert.equal(invocation.command, "python");
  assert.deepEqual(invocation.args, ["-m", "slop_detector.cli", "scan", ".", "--json"]);
});

test("runWrapper propagates exit code and stdio", async () => {
  const calls = [];
  const exitCode = await runWrapper(["scan", "."], {
    candidate: {
      command: "ai-slop-detector",
      args: [],
    },
    spawnImpl(command, args, options) {
      calls.push({ command, args, options });
      const child = new EventEmitter();
      process.nextTick(() => child.emit("exit", 7, null));
      return child;
    },
  });

  assert.equal(exitCode, 7);
  assert.equal(calls[0].command, "ai-slop-detector");
  assert.deepEqual(calls[0].args, ["scan", "."]);
  assert.equal(calls[0].options.stdio, "inherit");
});

test("runWrapper returns actionable failure when backend is missing", async () => {
  let stderr = "";
  const exitCode = await runWrapper(["scan", "."], {
    env: {},
    platform: "linux",
    probeImpl() {
      return { status: 1 };
    },
    stderr: {
      write(chunk) {
        stderr += chunk;
      },
    },
  });

  assert.equal(exitCode, 1);
  assert.match(stderr, /Python backend not found/i);
  assert.match(stderr, /AI_SLOP_DETECTOR_EXECUTABLE/);
});
