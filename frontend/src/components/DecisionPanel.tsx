import { useState } from "react";
import { submitDecision } from "../services/api";
import type { ReviewResponse, DecisionResponse } from "../types";

interface Props {
  review: ReviewResponse;
}

type Mode = "initial" | "override" | "submitted";

const styles: Record<string, React.CSSProperties> = {
  container: {
    border: "1px solid #dee2e6",
    borderRadius: 8,
    padding: "1.25rem",
    marginTop: "1.25rem",
    background: "#f8f9fa",
  },
  heading: {
    fontSize: "1rem",
    fontWeight: 700,
    marginTop: 0,
    marginBottom: "0.75rem",
    color: "#495057",
  },
  btnRow: {
    display: "flex",
    gap: 10,
    flexWrap: "wrap" as const,
  },
  acceptBtn: {
    background: "#28a745",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "0.55rem 1.25rem",
    fontSize: "0.9rem",
    fontWeight: 600,
    cursor: "pointer",
  },
  overrideBtn: {
    background: "#ffc107",
    color: "#000",
    border: "none",
    borderRadius: 6,
    padding: "0.55rem 1.25rem",
    fontSize: "0.9rem",
    fontWeight: 600,
    cursor: "pointer",
  },
  cancelBtn: {
    background: "#6c757d",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "0.55rem 1.25rem",
    fontSize: "0.9rem",
    cursor: "pointer",
  },
  disabled: { opacity: 0.6, cursor: "not-allowed" },
  field: { marginBottom: "0.75rem" },
  label: { display: "block", fontSize: "0.85rem", fontWeight: 600, marginBottom: 4, color: "#495057" },
  select: { padding: "0.45rem", borderRadius: 4, border: "1px solid #ced4da", fontSize: "0.9rem", width: "100%" },
  textarea: {
    width: "100%",
    padding: "0.5rem",
    borderRadius: 4,
    border: "1px solid #ced4da",
    fontSize: "0.9rem",
    minHeight: 80,
    resize: "vertical" as const,
    boxSizing: "border-box" as const,
  },
  nameInput: { padding: "0.45rem", borderRadius: 4, border: "1px solid #ced4da", fontSize: "0.9rem", width: "100%" },
  error: { color: "#dc3545", marginTop: "0.5rem", fontSize: "0.85rem" },
  letterBox: {
    background: "#fff",
    border: "1px solid #dee2e6",
    borderRadius: 6,
    padding: "1rem",
    fontFamily: "monospace",
    fontSize: "0.8rem",
    whiteSpace: "pre-wrap" as const,
    maxHeight: 400,
    overflowY: "auto" as const,
    marginBottom: "0.75rem",
  },
  authBadge: {
    display: "inline-block",
    background: "#d4edda",
    color: "#155724",
    fontWeight: 700,
    padding: "0.3rem 0.8rem",
    borderRadius: 20,
    fontSize: "0.85rem",
    marginBottom: "0.75rem",
  },
  downloadBtn: {
    background: "#0d6efd",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "0.45rem 1rem",
    fontSize: "0.85rem",
    cursor: "pointer",
  },
  meta: { fontSize: "0.8rem", color: "#6c757d", marginTop: "0.5rem" },
};

export default function DecisionPanel({ review }: Props) {
  const [mode, setMode] = useState<Mode>("initial");
  const [reviewerName, setReviewerName] = useState("");
  const [overrideRec, setOverrideRec] = useState<"approve" | "pend_for_review">(
    review.recommendation === "approve" ? "pend_for_review" : "approve"
  );
  const [overrideRationale, setOverrideRationale] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState<DecisionResponse | null>(null);

  const handleAccept = async () => {
    if (!reviewerName.trim()) {
      setError("Reviewer name is required");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const resp = await submitDecision({
        request_id: review.request_id,
        action: "accept",
        reviewer_name: reviewerName.trim(),
      });
      setDecision(resp);
      setMode("submitted");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision failed");
    } finally {
      setLoading(false);
    }
  };

  const handleOverrideSubmit = async () => {
    if (!reviewerName.trim()) {
      setError("Reviewer name is required");
      return;
    }
    if (!overrideRationale.trim()) {
      setError("Override rationale is required");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const resp = await submitDecision({
        request_id: review.request_id,
        action: "override",
        override_recommendation: overrideRec,
        override_rationale: overrideRationale.trim(),
        reviewer_name: reviewerName.trim(),
      });
      setDecision(resp);
      setMode("submitted");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision failed");
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
    if (!decision) return;

    // Prefer PDF if available, fall back to plain text
    if (decision.letter.pdf_base64) {
      const byteChars = atob(decision.letter.pdf_base64);
      const byteNumbers = new Uint8Array(byteChars.length);
      for (let i = 0; i < byteChars.length; i++) {
        byteNumbers[i] = byteChars.charCodeAt(i);
      }
      const blob = new Blob([byteNumbers], { type: "application/pdf" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${decision.authorization_number}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } else {
      const blob = new Blob([decision.letter.body_text], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${decision.authorization_number}.txt`;
      a.click();
      URL.revokeObjectURL(url);
    }
  };

  // --- Submitted mode: show letter + download ---
  if (mode === "submitted" && decision) {
    return (
      <div style={styles.container}>
        <h3 style={styles.heading}>Decision Recorded</h3>
        <div style={styles.authBadge}>
          Auth #: {decision.authorization_number}
        </div>
        <div style={{ fontSize: "0.85rem", marginBottom: "0.5rem" }}>
          <strong>Final Recommendation:</strong>{" "}
          {decision.final_recommendation.replace(/_/g, " ").toUpperCase()}
          {decision.was_overridden && (
            <span style={{ color: "#856404", marginLeft: 8 }}>(overridden)</span>
          )}
        </div>
        <div style={styles.letterBox}>{decision.letter.body_text}</div>
        <button style={styles.downloadBtn} onClick={handleDownload}>
          Download Letter
        </button>
        <div style={styles.meta}>
          Decided by: {decision.decided_by} | {decision.decided_at}
        </div>
      </div>
    );
  }

  // --- Override mode: dropdown + rationale ---
  if (mode === "override") {
    return (
      <div style={styles.container}>
        <h3 style={styles.heading}>Override Recommendation</h3>

        <div style={styles.field}>
          <label style={styles.label}>Reviewer Name</label>
          <input
            style={styles.nameInput}
            value={reviewerName}
            onChange={(e) => setReviewerName(e.target.value)}
            placeholder="Dr. Jane Doe"
          />
        </div>

        <div style={styles.field}>
          <label style={styles.label}>New Recommendation</label>
          <select
            style={styles.select}
            value={overrideRec}
            onChange={(e) => setOverrideRec(e.target.value as "approve" | "pend_for_review")}
          >
            <option value="approve">Approve</option>
            <option value="pend_for_review">Pend for Review</option>
          </select>
        </div>

        <div style={styles.field}>
          <label style={styles.label}>Override Rationale (required)</label>
          <textarea
            style={styles.textarea}
            value={overrideRationale}
            onChange={(e) => setOverrideRationale(e.target.value)}
            placeholder="Explain why you are overriding the AI recommendation..."
          />
        </div>

        <div style={styles.btnRow}>
          <button
            style={{ ...styles.overrideBtn, ...(loading ? styles.disabled : {}) }}
            onClick={handleOverrideSubmit}
            disabled={loading}
          >
            {loading ? "Submitting..." : "Submit Override"}
          </button>
          <button
            style={styles.cancelBtn}
            onClick={() => { setMode("initial"); setError(null); }}
            disabled={loading}
          >
            Cancel
          </button>
        </div>

        {error && <p style={styles.error}>{error}</p>}
      </div>
    );
  }

  // --- Initial mode: Accept / Override buttons ---
  return (
    <div style={styles.container}>
      <h3 style={styles.heading}>Reviewer Decision</h3>

      <div style={styles.field}>
        <label style={styles.label}>Reviewer Name</label>
        <input
          style={styles.nameInput}
          value={reviewerName}
          onChange={(e) => setReviewerName(e.target.value)}
          placeholder="Dr. Jane Doe"
        />
      </div>

      <div style={styles.btnRow}>
        <button
          style={{ ...styles.acceptBtn, ...(loading ? styles.disabled : {}) }}
          onClick={handleAccept}
          disabled={loading}
        >
          {loading ? "Submitting..." : "Accept Recommendation"}
        </button>
        <button
          style={{ ...styles.overrideBtn, ...(loading ? styles.disabled : {}) }}
          onClick={() => { setMode("override"); setError(null); }}
          disabled={loading}
        >
          Override
        </button>
      </div>

      {error && <p style={styles.error}>{error}</p>}
    </div>
  );
}
