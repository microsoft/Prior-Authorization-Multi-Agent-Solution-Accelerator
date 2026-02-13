import { useState } from "react";
import { submitReview } from "../services/api";
import type { PriorAuthRequest, ReviewResponse } from "../types";

interface Props {
  onReviewComplete: (result: ReviewResponse) => void;
}

const initial: PriorAuthRequest = {
  patient_name: "",
  patient_dob: "",
  provider_npi: "",
  diagnosis_codes: [""],
  procedure_codes: [""],
  clinical_notes: "",
  insurance_id: "",
};

const SAMPLE_REQUEST: PriorAuthRequest = {
  patient_name: "John Smith",
  patient_dob: "1958-03-15",
  provider_npi: "1902809042",
  diagnosis_codes: ["R91.1", "J18.9", "R05.9"],
  procedure_codes: ["31628"],
  clinical_notes:
    "68-year-old male with persistent right lower lobe pulmonary nodule " +
    "identified on CT chest (1.8 cm, spiculated margins). History of 40 " +
    "pack-year smoking, quit 5 years ago. PET scan shows SUV of 4.2. " +
    "Patient completed course of antibiotics with no resolution. Prior " +
    "CT 3 months ago showed interval growth from 1.2 cm. Pulmonary " +
    "function tests: FEV1 78% predicted. No prior history of malignancy. " +
    "Recommend CT-guided transbronchial lung biopsy for tissue diagnosis " +
    "given high suspicion for malignancy per Fleischner Society guidelines.",
  insurance_id: "MCR-123456789A",
};

const styles: Record<string, React.CSSProperties> = {
  form: {
    background: "#f8f9fa",
    borderRadius: 8,
    padding: "1.5rem",
    marginBottom: "2rem",
    border: "1px solid #dee2e6",
  },
  heading: { fontSize: "1.2rem", marginTop: 0, marginBottom: "1rem" },
  row: { display: "flex", gap: "1rem", marginBottom: "0.75rem" },
  field: { flex: 1, display: "flex", flexDirection: "column" },
  label: { fontSize: "0.85rem", fontWeight: 600, marginBottom: 4, color: "#495057" },
  input: {
    padding: "0.5rem",
    border: "1px solid #ced4da",
    borderRadius: 4,
    fontSize: "0.9rem",
  },
  textarea: {
    padding: "0.5rem",
    border: "1px solid #ced4da",
    borderRadius: 4,
    fontSize: "0.9rem",
    minHeight: 100,
    resize: "vertical" as const,
  },
  codeRow: { display: "flex", gap: 8, alignItems: "center", marginBottom: 4 },
  addBtn: {
    background: "none",
    border: "1px dashed #adb5bd",
    borderRadius: 4,
    padding: "0.25rem 0.75rem",
    cursor: "pointer",
    color: "#495057",
    fontSize: "0.85rem",
  },
  submit: {
    background: "#0d6efd",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "0.65rem 1.75rem",
    fontSize: "1rem",
    cursor: "pointer",
    marginTop: "0.5rem",
  },
  submitDisabled: { opacity: 0.6, cursor: "not-allowed" },
  error: { color: "#dc3545", marginTop: "0.5rem", fontSize: "0.9rem" },
  sampleBtn: {
    background: "#e9ecef",
    border: "1px solid #adb5bd",
    borderRadius: 6,
    padding: "0.4rem 1rem",
    fontSize: "0.85rem",
    cursor: "pointer",
    color: "#495057",
  },
  headerRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "1rem",
  },
};

export default function UploadForm({ onReviewComplete }: Props) {
  const [form, setForm] = useState<PriorAuthRequest>(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (field: keyof PriorAuthRequest, value: string) =>
    setForm((f) => ({ ...f, [field]: value }));

  const setCode = (
    field: "diagnosis_codes" | "procedure_codes",
    idx: number,
    value: string
  ) =>
    setForm((f) => {
      const arr = [...f[field]];
      arr[idx] = value;
      return { ...f, [field]: arr };
    });

  const addCode = (field: "diagnosis_codes" | "procedure_codes") =>
    setForm((f) => ({ ...f, [field]: [...f[field], ""] }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const payload = {
        ...form,
        diagnosis_codes: form.diagnosis_codes.filter(Boolean),
        procedure_codes: form.procedure_codes.filter(Boolean),
      };
      const result = await submitReview(payload);
      onReviewComplete(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form style={styles.form} onSubmit={handleSubmit}>
      <div style={styles.headerRow}>
        <h2 style={{ ...styles.heading, marginBottom: 0 }}>Submit Prior Auth Request</h2>
        <button
          type="button"
          style={styles.sampleBtn}
          onClick={() => setForm({ ...SAMPLE_REQUEST })}
          disabled={loading}
        >
          Load Sample Case
        </button>
      </div>

      <div style={styles.row}>
        <div style={styles.field}>
          <label style={styles.label}>Patient Name</label>
          <input
            style={styles.input}
            value={form.patient_name}
            onChange={(e) => set("patient_name", e.target.value)}
            required
          />
        </div>
        <div style={styles.field}>
          <label style={styles.label}>Date of Birth</label>
          <input
            style={styles.input}
            type="date"
            value={form.patient_dob}
            onChange={(e) => set("patient_dob", e.target.value)}
            required
          />
        </div>
      </div>

      <div style={styles.row}>
        <div style={styles.field}>
          <label style={styles.label}>Provider NPI</label>
          <input
            style={styles.input}
            value={form.provider_npi}
            onChange={(e) => set("provider_npi", e.target.value)}
            placeholder="10-digit NPI"
            required
          />
        </div>
        <div style={styles.field}>
          <label style={styles.label}>Insurance ID (optional)</label>
          <input
            style={styles.input}
            value={form.insurance_id || ""}
            onChange={(e) => set("insurance_id", e.target.value)}
          />
        </div>
      </div>

      <div style={styles.row}>
        <div style={styles.field}>
          <label style={styles.label}>Diagnosis Codes (ICD-10)</label>
          {form.diagnosis_codes.map((code, i) => (
            <div key={i} style={styles.codeRow}>
              <input
                style={{ ...styles.input, flex: 1 }}
                value={code}
                onChange={(e) => setCode("diagnosis_codes", i, e.target.value)}
                placeholder="e.g. M17.11"
              />
            </div>
          ))}
          <button type="button" style={styles.addBtn} onClick={() => addCode("diagnosis_codes")}>
            + Add code
          </button>
        </div>
        <div style={styles.field}>
          <label style={styles.label}>Procedure Codes (CPT)</label>
          {form.procedure_codes.map((code, i) => (
            <div key={i} style={styles.codeRow}>
              <input
                style={{ ...styles.input, flex: 1 }}
                value={code}
                onChange={(e) => setCode("procedure_codes", i, e.target.value)}
                placeholder="e.g. 27447"
              />
            </div>
          ))}
          <button type="button" style={styles.addBtn} onClick={() => addCode("procedure_codes")}>
            + Add code
          </button>
        </div>
      </div>

      <div style={{ marginBottom: "0.75rem" }}>
        <label style={styles.label}>Clinical Notes</label>
        <textarea
          style={styles.textarea}
          value={form.clinical_notes}
          onChange={(e) => set("clinical_notes", e.target.value)}
          placeholder="Enter clinical justification, history, and supporting documentation..."
          required
        />
      </div>

      <button
        type="submit"
        style={{
          ...styles.submit,
          ...(loading ? styles.submitDisabled : {}),
        }}
        disabled={loading}
      >
        {loading ? "Reviewing..." : "Submit for Review"}
      </button>

      {error && <p style={styles.error}>{error}</p>}
    </form>
  );
}
