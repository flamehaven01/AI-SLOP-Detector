import { AbsoluteFill } from "remotion";
import React from "react";

const colors = {
  bg: "#0d1117",
  primary: "#58a6ff",
  secondary: "#8b949e",
  accent: "#7ee787",
  warning: "#d29922",
  critical: "#f85149",
  boxBg: "#161b22",
  border: "#30363d",
};

const styles = {
  container: {
    backgroundColor: colors.bg,
    fontFamily: "'Inter', 'Segoe UI', sans-serif",
    padding: 40,
  } as React.CSSProperties,
  title: {
    color: "#fff",
    fontSize: 28,
    fontWeight: "bold",
    textAlign: "center" as const,
    marginBottom: 40,
  } as React.CSSProperties,
  flowContainer: {
    display: "flex",
    flexDirection: "column" as const,
    alignItems: "center",
    gap: 20,
  } as React.CSSProperties,
  row: {
    display: "flex",
    justifyContent: "center",
    gap: 30,
    width: "100%",
  } as React.CSSProperties,
  box: {
    backgroundColor: colors.boxBg,
    border: `2px solid ${colors.border}`,
    borderRadius: 12,
    padding: "15px 25px",
    minWidth: 180,
    textAlign: "center" as const,
  } as React.CSSProperties,
  inputBox: {
    backgroundColor: "#1f6feb20",
    borderColor: colors.primary,
  } as React.CSSProperties,
  processBox: {
    backgroundColor: "#23262d",
    borderColor: colors.secondary,
  } as React.CSSProperties,
  outputBox: {
    backgroundColor: "#f8514920",
    borderColor: colors.critical,
  } as React.CSSProperties,
  boxTitle: {
    color: "#fff",
    fontSize: 14,
    fontWeight: "bold",
    marginBottom: 5,
  } as React.CSSProperties,
  boxDesc: {
    color: colors.secondary,
    fontSize: 11,
  } as React.CSSProperties,
  arrow: {
    color: colors.primary,
    fontSize: 24,
  } as React.CSSProperties,
  badge: {
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 10,
    fontSize: 10,
    fontWeight: "bold",
    marginTop: 8,
  } as React.CSSProperties,
  versionBadge: {
    backgroundColor: colors.accent + "30",
    color: colors.accent,
  } as React.CSSProperties,
};

const Box: React.FC<{
  title: string;
  desc: string;
  version?: string;
  style?: React.CSSProperties;
}> = ({ title, desc, version, style }) => (
  <div style={{ ...styles.box, ...style }}>
    <div style={styles.boxTitle}>{title}</div>
    <div style={styles.boxDesc}>{desc}</div>
    {version && (
      <div style={{ ...styles.badge, ...styles.versionBadge }}>{version}</div>
    )}
  </div>
);

const Arrow: React.FC = () => <div style={styles.arrow}>v</div>;
const HArrow: React.FC = () => <div style={{ ...styles.arrow, transform: "rotate(-90deg)" }}>&gt;</div>;

export const ArchitectureDiagram: React.FC = () => {
  return (
    <AbsoluteFill style={styles.container}>
      <div style={styles.title}>AI-SLOP Detector v2.6.2 Architecture</div>

      <div style={styles.flowContainer}>
        {/* Input */}
        <Box
          title="Python Code"
          desc="Source files to analyze"
          style={styles.inputBox}
        />

        <Arrow />

        {/* Core Metrics Row */}
        <div style={styles.row}>
          <Box
            title="Core Metrics"
            desc="LDR, Inflation, DDC"
            version="v2.0"
            style={styles.processBox}
          />
        </div>

        <Arrow />

        {/* Pattern Detection Row */}
        <div style={styles.row}>
          <Box
            title="Pattern Detection"
            desc="14 Placeholder Patterns"
            version="v2.1"
            style={styles.processBox}
          />
          <Box
            title="Evidence Validation"
            desc="Context-Based Jargon"
            version="v2.2"
            style={styles.processBox}
          />
        </div>

        <Arrow />

        {/* Analysis Layer */}
        <div style={styles.row}>
          <Box
            title="Docstring Inflation"
            desc="Ratio Analysis"
            style={styles.processBox}
          />
          <Box
            title="Hallucination Deps"
            desc="12 Categories"
            style={styles.processBox}
          />
          <Box
            title="Question Generation"
            desc="Actionable UX"
            style={styles.processBox}
          />
        </div>

        <Arrow />

        {/* Output */}
        <Box
          title="Deficit Score + Report"
          desc="Critical/Warning/Info findings"
          style={styles.outputBox}
        />
      </div>
    </AbsoluteFill>
  );
};
