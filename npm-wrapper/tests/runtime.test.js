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

test("fetch candidates come last and pin the PyPI release to this package version", () => {
  const candidates = buildBackendCandidates({ env: {}, platform: "linux", version: "9.9.9" });
  const fetchers = candidates.filter((c) => c.kind === "fetch");
  assert.deepEqual(
    fetchers.map((c) => [c.command, ...c.args]),
    [
      ["uvx", "--from", "ai-slop-detector==9.9.9", "slop-detector"],
      ["pipx", "run", "--spec", "ai-slop-detector==9.9.9", "slop-detector"],
    ],
  );
  assert.equal(candidates.indexOf(fetchers[0]), candidates.length - 2);
});

test("default pin is the version in package.json", () => {
  const { version } = require("../package.json");
  const uvx = buildBackendCandidates({ env: {}, platform: "linux" }).find((c) => c.command === "uvx");
  assert.ok(uvx.args.includes(`ai-slop-detector==${version}`));
});

test("with nothing installed, uvx is chosen and probed for the tool only", () => {
  const probes = [];
  const backend = discoverBackend({
    env: {},
    platform: "linux",
    version: "1.2.3",
    probeImpl(command, args) {
      probes.push([command, ...args]);
      return { status: command === "uvx" ? 0 : 1 };
    },
  });
  assert.equal(backend.command, "uvx");
  assert.deepEqual(probes[probes.length - 1], ["uvx", "--version"]);
  assert.deepEqual(buildInvocation(backend, ["--json", "."]).args, [
    "--from",
    "ai-slop-detector==1.2.3",
    "slop-detector",
    "--json",
    ".",
  ]);
});

function runWithBackend(reported, expected) {
  let stderr = "";
  return runWrapper(["--json", "."], {
    version: expected,
    probeImpl(command) {
      return command === "ai-slop-detector"
        ? { status: 0, stdout: `ai-slop-detector ${reported}\n` }
        : { status: 1 };
    },
    env: {},
    platform: "linux",
    stderr: { write(chunk) { stderr += chunk; } },
    spawnImpl() {
      const child = new EventEmitter();
      process.nextTick(() => child.emit("exit", 0, null));
      return child;
    },
  }).then((code) => ({ code, stderr }));
}

test("an installed backend of another version is named on stderr", async () => {
  const { code, stderr } = await runWithBackend("3.12.0", "3.13.0");
  assert.equal(code, 0);
  assert.match(stderr, /using backend 3\.12\.0 \(path:ai-slop-detector\); this wrapper is 3\.13\.0/);
});

test("an installed backend of the wrapper's version runs silently", async () => {
  const { stderr } = await runWithBackend("3.13.0", "3.13.0");
  assert.equal(stderr, "");
});
