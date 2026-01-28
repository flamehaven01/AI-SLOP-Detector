import { AbsoluteFill } from "remotion";
import React from "react";

const colors = {
  bg: "#0c0c1d",
  cardBg: "#151528",
  border: "#2a2a4a",
  good: "#22c55e",
  warning: "#eab308",
  critical: "#ef4444",
  text: "#e4e4e7",
  textMuted: "#71717a",
  accent: "#818cf8",
};

const styles = {
  container: {
    backgroundColor: colors.bg,
    fontFamily: "'Inter', 'Segoe UI', sans-serif",
    padding: 40,
  } as React.CSSProperties,
  title: {
    color: "#fff",
    fontSize: 24,
    fontWeight: "bold",
    textAlign: "center" as const,
    marginBottom: 30,
  } as React.CSSProperties,
  scoreContainer: {
    display: "flex",
    justifyContent: "center",
    gap: 40,
  } as React.CSSProperties,
  mainScore: {
    backgroundColor: colors.cardBg,
    border: `2px solid ${colors.critical}`,
    borderRadius: 16,
    padding: 30,
    textAlign: "center" as const,
    minWidth: 200,
  } as React.CSSProperties,
  scoreValue: {
    fontSize: 64,
    fontWeight: "bold",
    color: colors.critical,
    lineHeight: 1,
  } as React.CSSProperties,
  scoreLabel: {
    color: colors.textMuted,
    fontSize: 14,
    marginTop: 10,
  } as React.CSSProperties,
  statusBadge: {
    display: "inline-block",
    padding: "6px 16px",
    borderRadius: 20,
    fontSize: 14,
    fontWeight: "bold",
    marginTop: 15,
    backgroundColor: colors.critical + "30",
    color: colors.critical,
  } as React.CSSProperties,
  metricsGrid: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 15,
    flex: 1,
    maxWidth: 500,
  } as React.CSSProperties,
  metricCard: {
    backgroundColor: colors.cardBg,
    border: `1px solid ${colors.border}`,
    borderRadius: 12,
    padding: 15,
    display: "flex",
    alignItems: "center",
    gap: 15,
  } as React.CSSProperties,
  metricIcon: {
    width: 44,
    height: 44,
    borderRadius: 10,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 20,
    fontWeight: "bold",
  } as React.CSSProperties,
  metricInfo: {
    flex: 1,
  } as React.CSSProperties,
  metricName: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "600",
  } as React.CSSProperties,
  metricDesc: {
    color: colors.textMuted,
    fontSize: 11,
    marginTop: 2,
  } as React.CSSProperties,
  metricValue: {
    fontSize: 18,
    fontWeight: "bold",
  } as React.CSSProperties,
  metricGrade: {
    fontSize: 12,
    marginTop: 2,
  } as React.CSSProperties,
  progressBar: {
    width: "100%",
    height: 6,
    backgroundColor: colors.border,
    borderRadius: 3,
    marginTop: 10,
    overflow: "hidden",
  } as React.CSSProperties,
  progressFill: {
    height: "100%",
    borderRadius: 3,
  } as React.CSSProperties,
};

type MetricData = {
  name: string;
  fullName: string;
  value: string;
  grade: string;
  progress: number;
  color: string;
};

const metrics: MetricData[] = [
  {
    name: "LDR",
    fullName: "Logic Density Ratio",
    value: "47.22%",
    grade: "B - Moderate",
    progress: 47,
    color: colors.warning,
  },
  {
    name: "ICR",
    fullName: "Inflation Check Ratio",
    value: "1.50",
    grade: "FAIL - Inflated",
    progress: 75,
    color: colors.critical,
  },
  {
    name: "DDC",
    fullName: "Dependency Check",
    value: "10.00%",
    grade: "SUSPICIOUS",
    progress: 10,
    color: colors.warning,
  },
  {
    name: "EVR",
    fullName: "Evidence Ratio",
    value: "14%",
    grade: "LOW - Claims unverified",
    progress: 14,
    color: colors.critical,
  },
];

const MetricCard: React.FC<MetricData> = ({
  name,
  fullName,
  value,
  grade,
  progress,
  color,
}) => (
  <div style={styles.metricCard}>
    <div style={{ ...styles.metricIcon, backgroundColor: color + "30", color }}>
      {name[0]}
    </div>
    <div style={styles.metricInfo}>
      <div style={styles.metricName}>
        {name} - {fullName}
      </div>
      <div style={styles.metricDesc}>{grade}</div>
      <div style={styles.progressBar}>
        <div
          style={{
            ...styles.progressFill,
            width: `${progress}%`,
            backgroundColor: color,
          }}
        />
      </div>
    </div>
    <div style={{ textAlign: "right" as const }}>
      <div style={{ ...styles.metricValue, color }}>{value}</div>
    </div>
  </div>
);

export const QualityScore: React.FC = () => {
  return (
    <AbsoluteFill style={styles.container}>
      <div style={styles.title}>Quality Score Dashboard</div>

      <div style={styles.scoreContainer}>
        {/* Main Score */}
        <div style={styles.mainScore}>
          <div style={styles.scoreValue}>71.1</div>
          <div style={styles.scoreLabel}>Deficit Score</div>
          <div style={styles.statusBadge}>CRITICAL</div>
        </div>

        {/* Metrics */}
        <div style={styles.metricsGrid}>
          {metrics.map((metric) => (
            <MetricCard key={metric.name} {...metric} />
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
