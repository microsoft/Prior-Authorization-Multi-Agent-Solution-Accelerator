import type { ReviewResponse, ToolResult, AuditTrail } from "../types";
import AgentDetails from "./AgentDetails";
import DecisionPanel from "./DecisionPanel";

interface Props {
  review: ReviewResponse;
}

const badgeColors: Record<string, { bg: string; text: string }> = {
  approve: { bg: "#d4edda", text: "#155724" },
  pend_for_review: { bg: "#fff3cd", text: "#856404" },
};

const confidenceLevelColors: Record<string, { bg: string; text: string }> = {
  HIGH: { bg: "#d4edda", text: "#155724" },
  MEDIUM: { bg: "#fff3cd", text: "#856404" },
  LOW: { bg: "#f8d7da", text: "#721c24" },
};

const statusIcon: Record<string, string> = {
  pass: "\u2713",
  fail: "\u2717",
  warning: "\u26A0",
};

const statusColor: Record<string, string> = {
  pass: "#28a745",
  fail: "#dc3545",
  warning: "#ffc107",
};

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: "#fff",
    borderRadius: 8,
    padding: "1.5rem",
    border: "1px solid #dee2e6",
  },
  heading: { fontSize: "1.2rem", marginTop: 0 },
  badge: {
    display: "inline-block",
    padding: "0.35rem 1rem",
    borderRadius: 20,
    fontWeight: 700,
    fontSize: "0.95rem",
    textTransform: "uppercase" as const,
    marginBottom: "1rem",
  },
  section: { marginBottom: "1.25rem" },
  sectionTitle: {
    fontSize: "0.95rem",
    fontWeight: 700,
    color: "#495057",
    marginBottom: "0.5rem",
    borderBottom: "1px solid #e9ecef",
    paddingBottom: 4,
  },
  toolRow: {
    display: "flex",
    alignItems: "flex-start",
    gap: 8,
    padding: "0.5rem 0",
    borderBottom: "1px solid #f1f3f5",
  },
  toolIcon: { fontWeight: 700, fontSize: "1rem", width: 20 },
  toolName: { fontWeight: 600, minWidth: 140, fontSize: "0.9rem" },
  toolDetail: { color: "#495057", fontSize: "0.9rem" },
  rationale: {
    background: "#f8f9fa",
    borderRadius: 6,
    padding: "0.75rem 1rem",
    fontSize: "0.9rem",
    lineHeight: 1.6,
    whiteSpace: "pre-wrap" as const,
  },
  requestId: { color: "#adb5bd", fontSize: "0.8rem", marginTop: "1rem" },
};

function ToolResultRow({ result }: { result: ToolResult }) {
  return (
    <div style={styles.toolRow}>
      <span style={{ ...styles.toolIcon, color: statusColor[result.status] }}>
        {statusIcon[result.status] || "?"}
      </span>
      <span style={styles.toolName}>{result.tool_name}</span>
      <span style={styles.toolDetail}>{result.detail}</span>
    </div>
  );
}

function AuditTrailSection({ audit }: { audit: AuditTrail }) {
  return (
    <div style={styles.section}>
      <div style={styles.sectionTitle}>Audit Trail</div>
      <div style={{ fontSize: "0.85rem", lineHeight: 1.8 }}>
        <div><span style={{ fontWeight: 600 }}>Criteria Met:</span> {audit.criteria_met_count}</div>
        <div><span style={{ fontWeight: 600 }}>Extraction Confidence:</span> {audit.extraction_confidence}%</div>
        <div><span style={{ fontWeight: 600 }}>Assessment Confidence:</span> {audit.assessment_confidence}%</div>
        {audit.data_sources.length > 0 && (
          <div style={{ marginTop: "0.5rem" }}>
            <span style={{ fontWeight: 600 }}>Data Sources:</span>
            <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1.2rem", fontSize: "0.8rem", color: "#6c757d" }}>
              {audit.data_sources.map((src, i) => (
                <li key={i}>{src}</li>
              ))}
            </ul>
          </div>
        )}
        <div style={{ marginTop: "0.5rem", fontSize: "0.8rem", color: "#adb5bd" }}>
          Started: {audit.review_started} | Completed: {audit.review_completed}
        </div>
      </div>
    </div>
  );
}

export default function ReviewDashboard({ review }: Props) {
  const colors = badgeColors[review.recommendation] || badgeColors.pend_for_review;
  const levelColors = confidenceLevelColors[review.confidence_level] || { bg: "#e9ecef", text: "#495057" };

  return (
    <div style={styles.container}>
      <h2 style={styles.heading}>Review Results</h2>

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: "1rem", flexWrap: "wrap" }}>
        <span style={{ ...styles.badge, background: colors.bg, color: colors.text, marginBottom: 0 }}>
          {review.recommendation.replace(/_/g, " ")}
        </span>
        <span style={{ fontSize: "0.85rem", color: "#6c757d" }}>
          Confidence: {Math.round(review.confidence * 100)}%
        </span>
        {review.confidence_level && (
          <span style={{
            display: "inline-block",
            padding: "0.2rem 0.6rem",
            borderRadius: 10,
            fontSize: "0.75rem",
            fontWeight: 600,
            background: levelColors.bg,
            color: levelColors.text,
          }}>
            {review.confidence_level}
          </span>
        )}
      </div>

      <div style={styles.section}>
        <div style={styles.sectionTitle}>Summary</div>
        <p style={{ margin: 0, fontSize: "0.95rem" }}>{review.summary}</p>
      </div>

      {review.tool_results.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Verification Checks</div>
          {review.tool_results.map((tr, i) => (
            <ToolResultRow key={i} result={tr} />
          ))}
        </div>
      )}

      {review.coverage_criteria_met.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Coverage Criteria Met</div>
          <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.9rem" }}>
            {review.coverage_criteria_met.map((c, i) => (
              <li key={i} style={{ color: "#155724", marginBottom: 4 }}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {review.coverage_criteria_not_met.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Coverage Criteria Not Met</div>
          <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.9rem" }}>
            {review.coverage_criteria_not_met.map((c, i) => (
              <li key={i} style={{ color: "#856404", marginBottom: 4 }}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      {review.missing_documentation.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Missing Documentation</div>
          <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.9rem" }}>
            {review.missing_documentation.map((d, i) => (
              <li key={i} style={{ color: "#dc3545", marginBottom: 4 }}>{d}</li>
            ))}
          </ul>
        </div>
      )}

      {review.documentation_gaps && review.documentation_gaps.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Documentation Gaps</div>
          {review.documentation_gaps.map((g, i) => (
            <div key={i} style={{
              padding: "0.5rem 0.75rem",
              marginBottom: 6,
              borderLeft: `3px solid ${g.critical ? "#dc3545" : "#ffc107"}`,
              background: g.critical ? "#f8d7da" : "#fff3cd",
              borderRadius: "0 4px 4px 0",
              fontSize: "0.85rem",
            }}>
              <span style={{ fontWeight: 600 }}>{g.critical ? "CRITICAL" : "Non-critical"}:</span>{" "}
              {g.what}
              {g.request && <div style={{ color: "#6c757d", marginTop: 2 }}>Request: {g.request}</div>}
            </div>
          ))}
        </div>
      )}

      <div style={styles.section}>
        <div style={styles.sectionTitle}>Clinical Rationale</div>
        <div style={styles.rationale}>{review.clinical_rationale}</div>
      </div>

      {review.policy_references.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Policy References</div>
          <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.85rem", color: "#495057" }}>
            {review.policy_references.map((p, i) => (
              <li key={i} style={{ marginBottom: 2 }}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      {review.audit_trail && (
        <AuditTrailSection audit={review.audit_trail} />
      )}

      {review.agent_results && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Agent Details</div>
          <AgentDetails agentResults={review.agent_results} />
        </div>
      )}

      <div style={{
        background: "#fff3cd",
        border: "1px solid #ffc107",
        borderRadius: 6,
        padding: "0.6rem 1rem",
        fontSize: "0.8rem",
        color: "#856404",
        marginTop: "1rem",
      }}>
        {review.disclaimer}
      </div>

      <DecisionPanel review={review} />

      <div style={styles.requestId}>Request ID: {review.request_id}</div>
    </div>
  );
}
