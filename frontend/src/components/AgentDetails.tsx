import { useState } from "react";
import type {
  AgentResults,
  ComplianceResult,
  ClinicalResult,
  CoverageResult,
} from "../types";

interface Props {
  agentResults: AgentResults;
}

const tabs = ["Compliance", "Clinical Reviewer", "Coverage"] as const;
type Tab = (typeof tabs)[number];

const s = {
  container: {
    border: "1px solid #dee2e6",
    borderRadius: 8,
    overflow: "hidden" as const,
    marginTop: "1.25rem",
  },
  tabBar: {
    display: "flex",
    borderBottom: "2px solid #dee2e6",
    background: "#f8f9fa",
  },
  tab: (active: boolean) => ({
    padding: "0.6rem 1.25rem",
    cursor: "pointer" as const,
    fontWeight: active ? 700 : 400,
    fontSize: "0.9rem",
    borderBottom: active ? "2px solid #0d6efd" : "2px solid transparent",
    marginBottom: -2,
    background: active ? "#fff" : "transparent",
    color: active ? "#0d6efd" : "#495057",
  }),
  body: { padding: "1rem 1.25rem" },
  sectionTitle: {
    fontSize: "0.85rem",
    fontWeight: 700,
    color: "#495057",
    marginBottom: "0.5rem",
    marginTop: "0.75rem",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse" as const,
    fontSize: "0.85rem",
    marginBottom: "0.75rem",
  },
  th: {
    textAlign: "left" as const,
    padding: "0.4rem 0.6rem",
    borderBottom: "1px solid #dee2e6",
    background: "#f8f9fa",
    fontWeight: 600,
    fontSize: "0.8rem",
    color: "#6c757d",
  },
  td: {
    padding: "0.4rem 0.6rem",
    borderBottom: "1px solid #f1f3f5",
  },
  list: {
    margin: 0,
    paddingLeft: "1.2rem",
    fontSize: "0.85rem",
    marginBottom: "0.75rem",
  },
  badge: (color: string) => ({
    display: "inline-block",
    padding: "0.15rem 0.5rem",
    borderRadius: 10,
    fontSize: "0.75rem",
    fontWeight: 600,
    background: color,
    color: "#fff",
  }),
  error: {
    background: "#f8d7da",
    color: "#721c24",
    padding: "0.5rem 0.75rem",
    borderRadius: 6,
    fontSize: "0.85rem",
  },
  fieldLabel: {
    fontWeight: 600,
    fontSize: "0.8rem",
    color: "#6c757d",
    marginTop: "0.5rem",
  },
  fieldValue: { fontSize: "0.85rem", marginBottom: "0.25rem" },
};

const statusBadge = (status: string) => {
  const colors: Record<string, string> = {
    complete: "#28a745",
    incomplete: "#ffc107",
    missing: "#dc3545",
    active: "#28a745",
    inactive: "#dc3545",
    not_found: "#dc3545",
    MET: "#28a745",
    NOT_MET: "#dc3545",
    INSUFFICIENT: "#ffc107",
  };
  return (
    <span style={s.badge(colors[status] || "#6c757d")}>
      {status}
    </span>
  );
};

function ConfidenceBar({ value }: { value: number }) {
  const color = value >= 80 ? "#28a745" : value >= 50 ? "#ffc107" : "#dc3545";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{
        width: 60,
        height: 6,
        background: "#e9ecef",
        borderRadius: 3,
        overflow: "hidden",
      }}>
        <div style={{
          width: `${Math.min(100, value)}%`,
          height: "100%",
          background: color,
          borderRadius: 3,
        }} />
      </div>
      <span style={{ fontSize: "0.75rem", color: "#6c757d" }}>{value}%</span>
    </div>
  );
}

function ComplianceTab({ data }: { data: ComplianceResult }) {
  if (data.error) return <div style={s.error}>Agent error: {data.error}</div>;
  return (
    <div>
      <div style={s.sectionTitle}>Documentation Checklist</div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>Item</th>
            <th style={s.th}>Status</th>
            <th style={s.th}>Detail</th>
          </tr>
        </thead>
        <tbody>
          {data.checklist.map((item, i) => (
            <tr key={i}>
              <td style={s.td}>{item.item}</td>
              <td style={s.td}>{statusBadge(item.status)}</td>
              <td style={s.td}>{item.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {data.missing_items.length > 0 && (
        <>
          <div style={s.sectionTitle}>Missing Items</div>
          <ul style={s.list}>
            {data.missing_items.map((m, i) => (
              <li key={i} style={{ color: "#dc3545" }}>{m}</li>
            ))}
          </ul>
        </>
      )}

      {data.additional_info_requests.length > 0 && (
        <>
          <div style={s.sectionTitle}>Additional Information Requested</div>
          <ul style={s.list}>
            {data.additional_info_requests.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function ClinicalTab({ data }: { data: ClinicalResult }) {
  if (data.error) return <div style={s.error}>Agent error: {data.error}</div>;
  const ext = data.clinical_extraction;
  return (
    <div>
      {data.diagnosis_validation.length > 0 && (
        <>
          <div style={s.sectionTitle}>Diagnosis Code Validation</div>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>Code</th>
                <th style={s.th}>Valid</th>
                <th style={s.th}>Description</th>
                <th style={s.th}>Billable</th>
              </tr>
            </thead>
            <tbody>
              {data.diagnosis_validation.map((d, i) => (
                <tr key={i}>
                  <td style={{ ...s.td, fontFamily: "monospace" }}>{d.code}</td>
                  <td style={s.td}>{statusBadge(d.valid ? "complete" : "missing")}</td>
                  <td style={s.td}>{d.description}</td>
                  <td style={s.td}>{d.billable ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {ext && (
        <>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={s.sectionTitle}>Clinical Extraction</div>
            {ext.extraction_confidence > 0 && (
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.8rem" }}>
                <span style={{ color: "#6c757d", fontWeight: 600 }}>Extraction Confidence:</span>
                <ConfidenceBar value={ext.extraction_confidence} />
              </div>
            )}
          </div>
          {ext.chief_complaint && (
            <><div style={s.fieldLabel}>Chief Complaint</div><div style={s.fieldValue}>{ext.chief_complaint}</div></>
          )}
          {ext.history_of_present_illness && (
            <><div style={s.fieldLabel}>History of Present Illness</div><div style={s.fieldValue}>{ext.history_of_present_illness}</div></>
          )}
          {ext.prior_treatments.length > 0 && (
            <><div style={s.fieldLabel}>Prior Treatments</div><ul style={s.list}>{ext.prior_treatments.map((t, i) => <li key={i}>{t}</li>)}</ul></>
          )}
          {ext.severity_indicators.length > 0 && (
            <><div style={s.fieldLabel}>Severity Indicators</div><ul style={s.list}>{ext.severity_indicators.map((t, i) => <li key={i}>{t}</li>)}</ul></>
          )}
          {ext.functional_limitations.length > 0 && (
            <><div style={s.fieldLabel}>Functional Limitations</div><ul style={s.list}>{ext.functional_limitations.map((t, i) => <li key={i}>{t}</li>)}</ul></>
          )}
          {ext.diagnostic_findings.length > 0 && (
            <><div style={s.fieldLabel}>Diagnostic Findings</div><ul style={s.list}>{ext.diagnostic_findings.map((t, i) => <li key={i}>{t}</li>)}</ul></>
          )}
          {ext.duration_and_progression && (
            <><div style={s.fieldLabel}>Duration & Progression</div><div style={s.fieldValue}>{ext.duration_and_progression}</div></>
          )}
        </>
      )}

      {data.clinical_summary && (
        <>
          <div style={s.sectionTitle}>Clinical Summary</div>
          <div style={{ ...s.fieldValue, whiteSpace: "pre-wrap" }}>{data.clinical_summary}</div>
        </>
      )}

      {data.literature_support.length > 0 && (
        <>
          <div style={s.sectionTitle}>Literature Support</div>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>Title</th>
                <th style={s.th}>PMID</th>
                <th style={s.th}>Relevance</th>
              </tr>
            </thead>
            <tbody>
              {data.literature_support.map((ref, i) => (
                <tr key={i}>
                  <td style={s.td}>{ref.title}</td>
                  <td style={{ ...s.td, fontFamily: "monospace" }}>{ref.pmid}</td>
                  <td style={s.td}>{ref.relevance}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {data.clinical_trials && data.clinical_trials.length > 0 && (
        <>
          <div style={s.sectionTitle}>Relevant Clinical Trials</div>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>NCT ID</th>
                <th style={s.th}>Title</th>
                <th style={s.th}>Status</th>
                <th style={s.th}>Relevance</th>
              </tr>
            </thead>
            <tbody>
              {data.clinical_trials.map((trial, i) => (
                <tr key={i}>
                  <td style={{ ...s.td, fontFamily: "monospace" }}>{trial.nct_id}</td>
                  <td style={s.td}>{trial.title}</td>
                  <td style={s.td}>{statusBadge(trial.status === "RECRUITING" ? "active" : trial.status === "COMPLETED" ? "complete" : trial.status)}</td>
                  <td style={s.td}>{trial.relevance}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function CoverageTab({ data }: { data: CoverageResult }) {
  if (data.error) return <div style={s.error}>Agent error: {data.error}</div>;
  const pv = data.provider_verification;
  return (
    <div>
      {pv && (
        <>
          <div style={s.sectionTitle}>Provider Verification</div>
          <div style={{ display: "flex", gap: "1.5rem", marginBottom: "0.75rem", fontSize: "0.85rem", flexWrap: "wrap" }}>
            <div><span style={{ fontWeight: 600 }}>NPI:</span> {pv.npi}</div>
            <div><span style={{ fontWeight: 600 }}>Name:</span> {pv.name}</div>
            <div><span style={{ fontWeight: 600 }}>Specialty:</span> {pv.specialty}</div>
            <div><span style={{ fontWeight: 600 }}>Status:</span> {statusBadge(pv.status)}</div>
          </div>
          {pv.detail && <div style={s.fieldValue}>{pv.detail}</div>}
        </>
      )}

      {data.coverage_policies.length > 0 && (
        <>
          <div style={s.sectionTitle}>Coverage Policies Found</div>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>Policy ID</th>
                <th style={s.th}>Type</th>
                <th style={s.th}>Title</th>
              </tr>
            </thead>
            <tbody>
              {data.coverage_policies.map((p, i) => (
                <tr key={i}>
                  <td style={{ ...s.td, fontFamily: "monospace" }}>{p.policy_id}</td>
                  <td style={s.td}>{p.type}</td>
                  <td style={s.td}>{p.title}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {data.criteria_assessment.length > 0 && (
        <>
          <div style={s.sectionTitle}>Criteria Assessment</div>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>Criterion</th>
                <th style={s.th}>Status</th>
                <th style={s.th}>Confidence</th>
                <th style={s.th}>Evidence</th>
                <th style={s.th}>Source</th>
              </tr>
            </thead>
            <tbody>
              {data.criteria_assessment.map((c, i) => (
                <tr key={i}>
                  <td style={s.td}>{c.criterion}</td>
                  <td style={s.td}>{statusBadge(c.status)}</td>
                  <td style={s.td}><ConfidenceBar value={c.confidence} /></td>
                  <td style={s.td}>
                    {Array.isArray(c.evidence)
                      ? c.evidence.map((e, j) => <div key={j} style={{ fontSize: "0.8rem", marginBottom: 2 }}>{e}</div>)
                      : c.evidence}
                  </td>
                  <td style={{ ...s.td, fontFamily: "monospace", fontSize: "0.8rem" }}>{c.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {data.documentation_gaps && data.documentation_gaps.length > 0 && (
        <>
          <div style={s.sectionTitle}>Documentation Gaps</div>
          {data.documentation_gaps.map((g, i) => (
            <div key={i} style={{
              padding: "0.4rem 0.6rem",
              marginBottom: 4,
              borderLeft: `3px solid ${g.critical ? "#dc3545" : "#ffc107"}`,
              background: g.critical ? "#f8d7da" : "#fff3cd",
              borderRadius: "0 4px 4px 0",
              fontSize: "0.8rem",
            }}>
              <span style={{ fontWeight: 600 }}>{g.critical ? "CRITICAL" : "Non-critical"}:</span>{" "}
              {g.what}
              {g.request && <div style={{ color: "#6c757d", marginTop: 2 }}>Request: {g.request}</div>}
            </div>
          ))}
        </>
      )}

      {data.coverage_limitations.length > 0 && (
        <>
          <div style={s.sectionTitle}>Coverage Limitations</div>
          <ul style={s.list}>
            {data.coverage_limitations.map((l, i) => (
              <li key={i} style={{ color: "#856404" }}>{l}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export default function AgentDetails({ agentResults }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("Compliance");

  return (
    <div style={s.container}>
      <div style={s.tabBar}>
        {tabs.map((tab) => (
          <div
            key={tab}
            style={s.tab(activeTab === tab)}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </div>
        ))}
      </div>
      <div style={s.body}>
        {activeTab === "Compliance" && agentResults.compliance && (
          <ComplianceTab data={agentResults.compliance} />
        )}
        {activeTab === "Clinical Reviewer" && agentResults.clinical && (
          <ClinicalTab data={agentResults.clinical} />
        )}
        {activeTab === "Coverage" && agentResults.coverage && (
          <CoverageTab data={agentResults.coverage} />
        )}
        {activeTab === "Compliance" && !agentResults.compliance && (
          <div style={s.error}>Compliance agent data not available</div>
        )}
        {activeTab === "Clinical Reviewer" && !agentResults.clinical && (
          <div style={s.error}>Clinical reviewer agent data not available</div>
        )}
        {activeTab === "Coverage" && !agentResults.coverage && (
          <div style={s.error}>Coverage agent data not available</div>
        )}
      </div>
    </div>
  );
}
