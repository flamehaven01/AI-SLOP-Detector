# AI-SLOP-DETECTOR Mathematical Governance & Code Drift Analysis Spec
# Version: 2.4 Final (Unified Sovereign Protocol)

This specification defines the formal mathematical core and public conformance framework implemented in `AI-SLOP-DETECTOR` to detect and govern AI-generated code drift. Under the **v2.4 Final Conformance Protocol**, the system is elevated from a simple static scoring engine to a reproducible, auditable **Governance Instrument**.

---

## 1. Abstract & Problem Statement

Iterative code generation by AI agents commonly bypasses static style checks and unit test suites while introducing hidden architectural degradation, copy-paste clone clusters, inflated explanatory docstrings, and structural drift. This framework establishes an external, deterministic measurement layer to produce reconstructable **Governance Records** for repository drift assessment.

```text
[AST/Representation Taxonomy]
       │ (Layer 0-1)
       ▼
[Structural Fingerprint (DCF-1 / DCF-2)]
       │ (Layer 2: JSD / Support Smoothing)
       ▼
[Pairwise Distance Matrix d(P, Q)]
       │ (Layer 3: Prim's MST / Scaling Boundaries)
       ▼
[Repository Topology (Coherence)] ───► [File-Level Deficit (LDR/ICR/DDC)] (Layer 4)
       │
       ▼ (Layer 5: Weighted Geometric Mean Aggregation)
[Weighted Geometric Gate (Ω)]
       │ (Layer 6-7: Calibration & Decision Surfaces)
       ▼
[Reproducible Governance Record & Hash] (Layer 8)
```

---

## 2. The 9-Layer Conformance Framework

To claim conformance, any measuring instrument (including `AI-SLOP-DETECTOR`) must verify its operations across the following 9 layers.

### Layer 0: Artifact Sufficiency
Before invoking parsing pipelines, the system checks if the repository possesses sufficient code material to yield valid measurements.
- **Sufficiency Modes:**
  - `FULL`: All required source files and configs exist.
  - `PARTIAL`: Core files are present, but minor metadata/git histories are missing.
  - `LIMITED`: Suboptimal code volume; analysis runs under constraint.
  - `BLOCKED`: Core inputs are missing or unreadable. The system must abort and emit a `HOLD` status rather than fabricating a zero-deficit score.

### Layer 1: Structural Representation
The target code is transformed into a deterministic frequency distribution.
1. **DCF-1 (Node-Type Distribution):** Normalizes AST node occurrence. Fast and lightweight for standard CI.
   $$P_f(N_i) = \frac{\text{count}_f(N_i)}{\sum_j \text{count}_f(N_j)}$$
2. **DCF-2 (Depth-Bounded Subtree Distribution):** Captures local structural templates up to a maximum depth ($D_{max}$). Reserved for Nightly Audits due to high support-space requirements.
   $$P_f(S_k) = \frac{\text{count}_f(S_k)}{\sum_l \text{count}_f(S_l)}$$

### Layer 2: Distributional Distance
Computes the distance between two structural representations $P$ and $Q$ using Jensen-Shannon Divergence (JSD):
$$JSD(P \parallel Q) = \frac{1}{2}D_{KL}(P \parallel M) + \frac{1}{2}D_{KL}(Q \parallel M)$$
$$M = \frac{1}{2}(P + Q)$$
The metric distance is:
$$d(P, Q) = \sqrt{JSD(P \parallel Q)}$$

#### Support Alignment Policy
To prevent runtime failure when $P$ and $Q$ span different vocabularies:
- `UNION_EPSILON`: Combine vocabularies and smooth zero-counts with an implementation-defined $\epsilon$.
- `INTERSECTION_WITH_MISSING_REPORT`: Restrict computation to shared supports and report missing classes separately.
- `JSD_STANDARD_NO_SMOOTHING`: Treat $0 \log 0$ as $0$ under standard JSD conventions while logging zero-support events.

### Layer 3: Repository Topology
Represents the repository as a weighted structural graph where vertices are files and edge weights $d(e)$ are distances.
The outlier-sensitive backbone coherence score is derived using a Prim-based Minimum Spanning Tree (MST):
$$\text{coherence}_{\text{max\_edge}} = 1 - \max_{e \in MST} d(e)$$

#### Topology Scaling Mode
To prevent $O(N^2)$ Prim timeouts on large repositories ($N \ge \text{exact\_topology\_ceiling}$):
- `EXACT`: Computes full pairwise distance matrix and exact MST. Only allowed when $N \le ceiling$.
- `DETERMINISTIC_APPROXIMATE`: Uses a fixed random seed and ordered file subsetting to generate stable, reproducible approximate MSTs.
- `NONDETERMINISTIC_APPROXIMATE`: Nondeterministic approximation; default outcome is downgraded to `HOLD`.

### Layer 4: File-Level Structural Risk
Computes static metrics at the file level:
- **Logic Density (LDR):** Ratio of AST statements containing executable code versus total file length.
- **Deep Dependency Coupling (DDC):** Coupling and nested complexity depth.
- **Inflation Resistance (ICR):** Ratio of actual code statements to docstrings, buzzwords, and comments.
- **Critical Patterns:** Exact pattern matches (e.g., empty mocks, phantom imports) recorded as source-anchored findings.

### Layer 5: Aggregation (Weighted Geometric Gate)
Normalized variables $v_i \in [0, 1]$ are aggregated. Let:
- $v_1$: Normalized Logic Density (LDR)
- $v_2$: Normalized Dependency Alignment (DDC)
- $v_3$: Normalized Inflation Resistance (ICR)
- $v_4$: Purity Signal from critical pattern matches:
  $$v_4 = \exp(-\lambda \cdot N_{\text{critical}})$$
  *(where $\lambda$ is the Purity Decay Coefficient)*

The overall structural quality score $\Omega$ is aggregated via a weighted geometric mean:
$$\Omega = \exp\left( \frac{\sum_{i=1}^{3} w_i \ln(v_i) + w_{pur} \ln(v_4)}{W_{\text{total}}} \right)$$
$$W_{\text{total}} = \left( \sum_{i=1}^{3} w_i \right) + w_{pur}$$

#### Zero Handling Policy
- `CLIP_TO_EPSILON`: Clip inputs to $[\epsilon, 1.0]$ before log operations.
- `HARD_FLOOR`: A zero score on any critical dimension instantly forces $\Omega = 0$.

### Layer 6: Calibration
Tunes weights and thresholds based on historical developer interactions:
- **Confirmed Improvement Event:** A flagged file is subsequently modified, resulting in a structural deficit reduction exceeding a specified threshold.
- **Ignored Finding Proxy:** A flagged file remains unchanged across $K$ subsequent commits.
*Policy constraint: Calibration must run offline and produce a report (`calibration_report.json`); it must not automatically mutate CI enforcement weights without human approval.*

### Layer 7: CI Decision Surface
Maps the aggregate metrics to four deterministic verdicts:
- `PASS`: Repository structural deficit remains within policy bounds.
- `REVIEW`: Safe boundary exceeded; manual audit required.
- `HOLD`: Measurement was blocked, unstable, non-comparable, or timed out.
- `BLOCK`: Policy threshold violated (fail-closed CI merge blockade).

### Layer 8: Governance Record
The primary deliverable of the scanner is the **Governance Record** (not the raw score). The record captures all metadata required for a reviewer to reconstruct the audit:
$$\text{record\_hash} = \text{SHA256}(\text{metadata} \mathbin{\Vert} \text{findings\_ledger} \mathbin{\Vert} \text{policies})$$

---

## 3. Delta Governance & Temporal Drift

Snapshot analysis evaluates a single repository state $G_t$. **Temporal drift** is measured by comparing comparable snapshots over time under a declared delta policy.

### Deficit Definition
The overall structural deficit $D_t$ at state $t$ combines the inverse quality score and explicit pattern penalties:
$$D_t = \text{clamp}\left((1 - \Omega_t) + \text{penalty\_mass}_t, \ 0, \ 1\right)$$

### Temporal Metrics
1. **Simple Score Delta:**
   $$\Delta \Omega_t = \Omega_t - \Omega_{t-1}$$
   $$\Delta D_t = D_t - D_{t-1}$$
2. **Record-Indexed Drift Rate:**
   $$\text{record\_indexed\_drift\_rate}_k = \frac{D_t - D_{t-k}}{k}$$
3. **Time-Normalized Drift Rate:**
   $$\text{time\_normalized\_drift\_rate} = \frac{D_t - D_{t_0}}{\Delta \text{time}}$$

### Comparability Rule
Two governance records are comparable for drift tracking if and only if their underlying parser version, taxonomy, distance policies, exclusions, and aggregation weights are identical. Any mismatch must trigger a `HOLD_FOR_NON_COMPARABLE_RECORDS` status.

---

## 4. Failure Mode Mitigations

Conforming implementations must explicitly register mitigations for known failure modes:

| Failure Mode | Risk | Mitigation Policy |
| :--- | :--- | :--- |
| **Representation Loss** | AST discards semantic logic | Treat signals as representations, not absolute verdicts; escalate to manual review. |
| **Parser/Taxonomy Drift** | Python update changes AST nodes | Pin parser version and taxonomy version tags in `governance_record.json`. |
| **Support Mismatch** | Distance calc fails on disjoint sets | Declare `UNION_EPSILON` smoothing policy; fallback to `HOLD` if undefined. |
| **Tail-Mass Compression** | Merging low-frequency nodes hides structural anomalies | Do not use top-$k$ truncation for final governance verdicts. |
| **Exclusion Abuse** | Developers whitelist problematic files | Emit a visible `exclusion_manifest.json` with mandatory reason codes. |
| **Topology Timeout** | Prim MST calculation halts CI/CD | Enforce `exact_topology_ceiling` threshold and transition to deterministic approximation. |
