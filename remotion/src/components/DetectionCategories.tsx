import { AbsoluteFill } from "remotion";
import React from "react";

const colors = {
  bg: "#0f0f23",
  cardBg: "#1a1a2e",
  border: "#3d3d5c",
  critical: "#ff6b6b",
  warning: "#feca57",
  info: "#54a0ff",
  accent: "#5f27cd",
  text: "#e4e4e7",
  textMuted: "#a1a1aa",
  code: "#10b981",
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
    marginBottom: 10,
  } as React.CSSProperties,
  subtitle: {
    color: colors.textMuted,
    fontSize: 14,
    textAlign: "center" as const,
    marginBottom: 30,
  } as React.CSSProperties,
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: 20,
    padding: "0 20px",
  } as React.CSSProperties,
  card: {
    backgroundColor: colors.cardBg,
    border: `1px solid ${colors.border}`,
    borderRadius: 12,
    padding: 20,
    position: "relative" as const,
  } as React.CSSProperties,
  cardNumber: {
    position: "absolute" as const,
    top: -10,
    left: 15,
    backgroundColor: colors.accent,
    color: "#fff",
    width: 24,
    height: 24,
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 12,
    fontWeight: "bold",
  } as React.CSSProperties,
  cardTitle: {
    color: "#fff",
    fontSize: 16,
    fontWeight: "bold",
    marginBottom: 8,
    marginTop: 5,
  } as React.CSSProperties,
  cardDesc: {
    color: colors.textMuted,
    fontSize: 12,
    marginBottom: 12,
    lineHeight: 1.4,
  } as React.CSSProperties,
  codeBlock: {
    backgroundColor: "#0d0d14",
    borderRadius: 6,
    padding: 10,
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 10,
    color: colors.code,
    overflow: "hidden",
  } as React.CSSProperties,
  badge: {
    display: "inline-block",
    padding: "3px 8px",
    borderRadius: 4,
    fontSize: 10,
    fontWeight: "bold",
    marginTop: 10,
  } as React.CSSProperties,
  critical: { backgroundColor: colors.critical + "30", color: colors.critical },
  warning: { backgroundColor: colors.warning + "30", color: colors.warning },
  info: { backgroundColor: colors.info + "30", color: colors.info },
};

type Severity = "critical" | "warning" | "info";

const categories: Array<{
  num: number;
  title: string;
  desc: string;
  code: string;
  severity: Severity;
  count: string;
}> = [
  {
    num: 1,
    title: "Placeholder Code",
    desc: "Empty implementations, pass statements, NotImplementedError",
    code: 'def quantum_encode(data):\n    """Advanced encoding"""\n    pass  # Empty!',
    severity: "critical",
    count: "14 patterns",
  },
  {
    num: 2,
    title: "Buzzword Inflation",
    desc: "Quality claims without supporting evidence",
    code: '"""Production-ready,\n   enterprise-grade..."""\nreturn data + 1',
    severity: "critical",
    count: "15 claim types",
  },
  {
    num: 3,
    title: "Docstring Inflation",
    desc: "Documentation-heavy, implementation-light code",
    code: '"""12 lines of docs\n   for sophisticated\n   algorithm..."""\nreturn a + b',
    severity: "warning",
    count: "Ratio analysis",
  },
  {
    num: 4,
    title: "Hallucinated Deps",
    desc: "Purpose-specific imports that are never used",
    code: "import torch     # ML\nimport requests  # HTTP\n# None used!",
    severity: "critical",
    count: "12 categories",
  },
  {
    num: 5,
    title: "Evidence Validation",
    desc: "Cross-validates claims against actual codebase",
    code: '"scalable" claim\n  - tests: 0\n  - logging: 0\n  FAIL: 0% evidence',
    severity: "warning",
    count: "15 evidence types",
  },
  {
    num: 6,
    title: "CI Gate System",
    desc: "Soft/Hard/Quarantine enforcement modes",
    code: "--ci-mode hard\n--ci-report\nExit: 1 (FAIL)",
    severity: "info",
    count: "3 modes",
  },
];

const Card: React.FC<(typeof categories)[0]> = ({
  num,
  title,
  desc,
  code,
  severity,
  count,
}) => (
  <div style={styles.card}>
    <div style={styles.cardNumber}>{num}</div>
    <div style={styles.cardTitle}>{title}</div>
    <div style={styles.cardDesc}>{desc}</div>
    <div style={styles.codeBlock}>
      <pre style={{ margin: 0 }}>{code}</pre>
    </div>
    <div style={{ ...styles.badge, ...styles[severity] }}>{count}</div>
  </div>
);

export const DetectionCategories: React.FC = () => {
  return (
    <AbsoluteFill style={styles.container}>
      <div style={styles.title}>6 Detection Categories</div>
      <div style={styles.subtitle}>
        Detecting AI-generated code quality issues with evidence-based
        validation
      </div>

      <div style={styles.grid}>
        {categories.map((cat) => (
          <Card key={cat.num} {...cat} />
        ))}
      </div>
    </AbsoluteFill>
  );
};
