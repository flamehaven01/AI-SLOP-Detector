import { AbsoluteFill } from "remotion";
import React from "react";

const styles = {
  container: {
    backgroundColor: "#1a1b26",
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
    fontSize: 14,
    padding: 30,
    color: "#a9b1d6",
    lineHeight: 1.6,
  } as React.CSSProperties,
  header: {
    borderBottom: "1px solid #3d59a1",
    paddingBottom: 15,
    marginBottom: 20,
  } as React.CSSProperties,
  title: {
    color: "#7aa2f7",
    fontSize: 18,
    fontWeight: "bold",
  } as React.CSSProperties,
  box: {
    border: "1px solid #3d59a1",
    borderRadius: 8,
    padding: 20,
    marginBottom: 20,
    backgroundColor: "#16161e",
  } as React.CSSProperties,
  boxTitle: {
    color: "#bb9af7",
    fontSize: 16,
    marginBottom: 15,
    borderBottom: "1px solid #3d59a1",
    paddingBottom: 10,
  } as React.CSSProperties,
  row: {
    display: "flex",
    justifyContent: "space-between",
    marginBottom: 8,
  } as React.CSSProperties,
  label: {
    color: "#7dcfff",
  } as React.CSSProperties,
  critical: {
    color: "#f7768e",
    fontWeight: "bold",
  } as React.CSSProperties,
  warning: {
    color: "#e0af68",
  } as React.CSSProperties,
  good: {
    color: "#9ece6a",
  } as React.CSSProperties,
  info: {
    color: "#7aa2f7",
  } as React.CSSProperties,
  command: {
    color: "#9ece6a",
    marginBottom: 15,
  } as React.CSSProperties,
  prompt: {
    color: "#bb9af7",
  } as React.CSSProperties,
  section: {
    marginTop: 20,
  } as React.CSSProperties,
  questionItem: {
    marginBottom: 10,
    paddingLeft: 15,
  } as React.CSSProperties,
};

export const CLIOutput: React.FC = () => {
  return (
    <AbsoluteFill style={styles.container}>
      {/* Command line */}
      <div style={styles.command}>
        <span style={styles.prompt}>$ </span>
        slop-detector mycode.py --json
      </div>

      {/* Main Report Box */}
      <div style={styles.box}>
        <div style={styles.boxTitle}>AI CODE QUALITY REPORT</div>

        <div style={styles.row}>
          <span style={styles.label}>File:</span>
          <span>mycode.py</span>
        </div>
        <div style={styles.row}>
          <span style={styles.label}>Status:</span>
          <span style={styles.critical}>CRITICAL</span>
        </div>
        <div style={styles.row}>
          <span style={styles.label}>Deficit Score:</span>
          <span style={styles.critical}>71.1/100</span>
        </div>
      </div>

      {/* Metrics Box */}
      <div style={styles.box}>
        <div style={styles.boxTitle}>Core Metrics</div>

        <div style={styles.row}>
          <span style={styles.label}>LDR (Logic Density):</span>
          <span style={styles.warning}>47.22% (B)</span>
        </div>
        <div style={styles.row}>
          <span style={styles.label}>ICR (Inflation Check):</span>
          <span style={styles.critical}>1.50 (FAIL)</span>
        </div>
        <div style={styles.row}>
          <span style={styles.label}>DDC (Dependency Check):</span>
          <span style={styles.warning}>10.00% (SUSPICIOUS)</span>
        </div>
        <div style={styles.row}>
          <span style={styles.label}>Justification Ratio:</span>
          <span style={styles.critical}>14% evidence</span>
        </div>
      </div>

      {/* Questions Section */}
      <div style={styles.box}>
        <div style={styles.boxTitle}>Review Questions</div>

        <div style={styles.questionItem}>
          <span style={styles.critical}>[CRITICAL] </span>
          Only 14% of quality claims backed by evidence.
        </div>
        <div style={styles.questionItem}>
          <span style={styles.critical}>[CRITICAL] </span>
          "production-ready" claim lacks: error_handling, logging, tests
        </div>
        <div style={styles.questionItem}>
          <span style={styles.warning}>[WARNING] </span>
          Function has 15 lines docstring, 2 lines implementation
        </div>
        <div style={styles.questionItem}>
          <span style={styles.warning}>[WARNING] </span>
          Why import "torch" for ML but never use it?
        </div>
      </div>
    </AbsoluteFill>
  );
};
