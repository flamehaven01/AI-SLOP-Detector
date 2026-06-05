#!/usr/bin/env node
"use strict";

const { runWrapper } = require("../lib/runtime");

runWrapper(process.argv.slice(2))
  .then((code) => {
    process.exitCode = code;
  })
  .catch((error) => {
    const message = error && error.message ? error.message : String(error);
    process.stderr.write(`[ai-slop-detector npm wrapper] ${message}\n`);
    process.exitCode = 1;
  });
