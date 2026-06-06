"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");

const {
  computeHealth,
  reviewChanges,
  runCleanupFamily,
  runJsonCommand,
  runTextCommand,
  scanProject,
} = require("../lib/api");

function createChild({ code = 0, stdout = "", stderr = "" } = {}) {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  process.nextTick(() => {
    if (stdout) {
      child.stdout.emit("data", stdout);
    }
    if (stderr) {
      child.stderr.emit("data", stderr);
    }
    child.emit("exit", code, null);
  });
  return child;
}

test("runJsonCommand parses backend JSON output", async () => {
  const payload = { command: "health", summary: { overall_status: "clean" } };
  const result = await runJsonCommand(["pulse", ".", "--format", "json"], {
    candidate: { command: "ai-slop-detector", args: [] },
    spawnImpl(command, args, options) {
      assert.equal(command, "ai-slop-detector");
      assert.deepEqual(args, ["pulse", ".", "--format", "json"]);
      assert.deepEqual(options.stdio, ["ignore", "pipe", "pipe"]);
      return createChild({ stdout: JSON.stringify(payload) });
    },
  });

  assert.deepEqual(result, payload);
});

test("runJsonCommand forwards cwd to the spawned backend", async () => {
  const payload = { command: "scan", project_path: "/repo" };
  const result = await runJsonCommand(["scan", "/repo", "--format", "json"], {
    cwd: "/repo",
    candidate: { command: "ai-slop-detector", args: [] },
    spawnImpl(_command, _args, options) {
      assert.equal(options.cwd, "/repo");
      return createChild({ stdout: JSON.stringify(payload) });
    },
  });

  assert.equal(result.project_path, "/repo");
});

test("runJsonCommand omits cwd when not provided", async () => {
  await runJsonCommand(["scan", ".", "--format", "json"], {
    candidate: { command: "ai-slop-detector", args: [] },
    spawnImpl(_command, _args, options) {
      assert.equal("cwd" in options, false);
      return createChild({ stdout: JSON.stringify({ command: "scan" }) });
    },
  });
});

test("runTextCommand returns raw stdout/stderr without parsing", async () => {
  const result = await runTextCommand(["--self-calibrate"], {
    cwd: "/repo",
    candidate: { command: "ai-slop-detector", args: [] },
    spawnImpl(_command, args, options) {
      assert.deepEqual(args, ["--self-calibrate"]);
      assert.equal(options.cwd, "/repo");
      return createChild({ stdout: "not-json: human report", stderr: "warn line" });
    },
  });

  assert.equal(result.stdout, "not-json: human report");
  assert.equal(result.stderr, "warn line");
  assert.equal(result.code, 0);
});

test("runTextCommand rejects on non-zero exit", async () => {
  await assert.rejects(
    runTextCommand(["--init", "."], {
      candidate: { command: "ai-slop-detector", args: [] },
      spawnImpl() {
        return createChild({ code: 2, stderr: "boom" });
      },
    }),
    (error) => {
      assert.equal(error.code, 2);
      assert.match(error.message, /boom/);
      return true;
    },
  );
});

test("reviewChanges forwards base ref and returns parsed payload", async () => {
  const payload = { command: "audit", verdict: "warn" };
  const result = await reviewChanges(".", {
    base: "origin/main",
    candidate: { command: "python", args: ["-m", "slop_detector.cli"] },
    spawnImpl(command, args) {
      assert.equal(command, "python");
      assert.deepEqual(args, ["-m", "slop_detector.cli", "review", ".", "--format", "json", "--base", "origin/main"]);
      return createChild({ stdout: JSON.stringify(payload) });
    },
  });

  assert.equal(result.command, "audit");
  assert.equal(result.verdict, "warn");
});

test("runCleanupFamily forwards family and target", async () => {
  const payload = { command: "dead-code", verdict: "fail", issues: [] };
  const result = await runCleanupFamily("dead-code", "/repo", {
    candidate: { command: "ai-slop-detector", args: [] },
    spawnImpl(_command, args) {
      assert.deepEqual(args, ["sweep", "dead-code", "/repo", "--format", "json"]);
      return createChild({ stdout: JSON.stringify(payload) });
    },
  });

  assert.equal(result.command, "dead-code");
});

test("computeHealth and scanProject use canonical command surface", async () => {
  const seen = [];
  const candidate = { command: "ai-slop-detector", args: [] };

  async function invoke(fn, expectedCommand) {
    return fn("/repo", {
      candidate,
      spawnImpl(_command, args) {
        seen.push(args[0]);
        return createChild({ stdout: JSON.stringify({ command: expectedCommand }) });
      },
    });
  }

  const health = await invoke(computeHealth, "health");
  const scan = await invoke(scanProject, "scan");

  assert.equal(health.command, "health");
  assert.equal(scan.command, "scan");
  assert.deepEqual(seen, ["pulse", "scan"]);
});

test("runJsonCommand rejects with actionable parse context", async () => {
  await assert.rejects(
    runJsonCommand(["scan", ".", "--format", "json"], {
      candidate: { command: "ai-slop-detector", args: [] },
      spawnImpl() {
        return createChild({ stdout: "not-json" });
      },
    }),
    (error) => {
      assert.match(error.message, /Failed to parse JSON output/i);
      assert.equal(error.stdout, "not-json");
      return true;
    },
  );
});

