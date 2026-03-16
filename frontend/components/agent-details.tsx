"use client";

import type {
  AgentResults,
  AgentCheck,
  ComplianceResult,
  ClinicalResult,
  CoverageResult,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ConfidenceBar } from "@/components/confidence-bar";
import {
  ClipboardCheck,
  Stethoscope,
  Shield,
  Bot,
  AlertTriangle,
  Info,
  FileSearch,
  BookOpen,
  FlaskConical,
  UserCheck,
  FileCheck,
  ListChecks,
  ScrollText,
  CheckCircle2,
  XCircle,
  AlertCircle,
  HelpCircle,
  ChevronDown,
  ChevronRight,
  GitBranch,
} from "lucide-react";
import { useState } from "react";

function statusBadge(status: string) {
  const map: Record<string, "success" | "warning" | "destructive" | "secondary"> = {
    complete: "success",
    pass: "success",
    MET: "success",
    active: "success",
    incomplete: "warning",
    warning: "warning",
    INSUFFICIENT: "warning",
    missing: "destructive",
    fail: "destructive",
    NOT_MET: "destructive",
    inactive: "destructive",
    not_found: "destructive",
  };
  return <Badge variant={map[status] ?? "secondary"}>{status}</Badge>;
}

function checkIcon(result: string) {
  switch (result) {
    case "pass":
      return <CheckCircle2 className="h-4 w-4 text-success shrink-0" />;
    case "fail":
      return <XCircle className="h-4 w-4 text-destructive shrink-0" />;
    case "warning":
      return <AlertCircle className="h-4 w-4 text-warning shrink-0" />;
    default:
      return <HelpCircle className="h-4 w-4 text-muted-foreground shrink-0" />;
  }
}

function ChecksSummary({ checks, title }: { checks: AgentCheck[]; title: string }) {
  if (!checks || checks.length === 0) return null;

  const passCount = checks.filter((c) => c.result === "pass").length;
  const failCount = checks.filter((c) => c.result === "fail").length;
  const warnCount = checks.filter((c) => c.result === "warning").length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold flex items-center gap-1.5">
          <ListChecks className="h-4 w-4 text-primary" />
          {title}
        </h4>
        <div className="flex items-center gap-3 text-xs">
          {passCount > 0 && (
            <span className="flex items-center gap-1 text-success">
              <CheckCircle2 className="h-3 w-3" /> {passCount} passed
            </span>
          )}
          {warnCount > 0 && (
            <span className="flex items-center gap-1 text-warning">
              <AlertCircle className="h-3 w-3" /> {warnCount} warnings
            </span>
          )}
          {failCount > 0 && (
            <span className="flex items-center gap-1 text-destructive">
              <XCircle className="h-3 w-3" /> {failCount} failed
            </span>
          )}
        </div>
      </div>

      <div className="border rounded-lg overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead className="w-8"></TableHead>
              <TableHead>Rule / Check</TableHead>
              <TableHead className="w-20">Result</TableHead>
              <TableHead>Detail</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {checks.map((check, i) => {
              const isSubItem = check.rule.startsWith("  ");
              return (
                <TableRow
                  key={i}
                  className={isSubItem ? "bg-muted/20" : undefined}
                >
                  <TableCell className="py-2">{checkIcon(check.result)}</TableCell>
                  <TableCell
                    className={`py-2 ${
                      isSubItem
                        ? "pl-6 text-sm text-muted-foreground"
                        : "font-medium"
                    }`}
                  >
                    {isSubItem ? check.rule.trim() : check.rule}
                  </TableCell>
                  <TableCell className="py-2">{statusBadge(check.result)}</TableCell>
                  <TableCell className="py-2 text-sm text-muted-foreground">
                    {check.detail}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function CollapsibleSection({
  title,
  icon: Icon,
  children,
  defaultOpen = false,
  hasData = true,
}: {
  title: string;
  icon: React.ElementType;
  children: React.ReactNode;
  defaultOpen?: boolean;
  hasData?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="border rounded-lg">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-2 p-3 hover:bg-muted/40 transition-colors text-left"
      >
        {isOpen ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
        )}
        <Icon className="h-4 w-4 text-primary shrink-0" />
        <span className="text-sm font-medium flex-1">{title}</span>
        {!hasData && (
          <Badge variant="secondary" className="text-xs">
            No data
          </Badge>
        )}
      </button>
      {isOpen && (
        <div className="px-3 pb-3 border-t">
          <div className="pt-3">{children}</div>
        </div>
      )}
    </div>
  );
}

function ComplianceTab({ data: raw }: { data: ComplianceResult }) {
  // Normalize potentially-null arrays from API response
  const data = {
    ...raw,
    checks_performed: raw.checks_performed ?? [],
    checklist: raw.checklist ?? [],
    missing_items: raw.missing_items ?? [],
    additional_info_requests: raw.additional_info_requests ?? [],
  };
  return (
    <div className="space-y-4">
      {/* Checks summary — always visible */}
      <ChecksSummary
        checks={data.checks_performed}
        title="Compliance Checks Performed"
      />

      {/* Detailed sections */}
      {data.checklist.length > 0 && (
        <CollapsibleSection
          title={`Documentation Checklist (${data.checklist.length} items)`}
          icon={ClipboardCheck}
          hasData={data.checklist.length > 0}
        >
          <div className="flex items-center gap-2 mb-3">
            <span className="text-sm font-medium">Overall:</span>
            {statusBadge(data.overall_status)}
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead className="w-28">Status</TableHead>
                  <TableHead>Detail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.checklist.map((item, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-medium">{item.item}</TableCell>
                    <TableCell>{statusBadge(item.status)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {item.detail}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CollapsibleSection>
      )}

      {data.missing_items.length > 0 && (
        <div>
          <h4 className="text-sm font-medium mb-1 flex items-center gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5 text-warning" />
            Missing Items
          </h4>
          <ul className="list-disc list-inside text-sm text-muted-foreground space-y-0.5">
            {data.missing_items.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </div>
      )}

      {data.additional_info_requests.length > 0 && (
        <div>
          <h4 className="text-sm font-medium mb-1 flex items-center gap-1.5">
            <Info className="h-3.5 w-3.5 text-info" />
            Additional Info Requests
          </h4>
          <ul className="list-disc list-inside text-sm text-muted-foreground space-y-0.5">
            {data.additional_info_requests.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {data.error && (
        <p className="text-sm text-destructive">Error: {data.error}</p>
      )}
    </div>
  );
}

function ClinicalTab({ data: raw }: { data: ClinicalResult }) {
  // Normalize potentially-null arrays from API response
  const data = {
    ...raw,
    checks_performed: raw.checks_performed ?? [],
    diagnosis_validation: raw.diagnosis_validation ?? [],
    literature_support: raw.literature_support ?? [],
    clinical_trials: raw.clinical_trials ?? [],
    tool_results: raw.tool_results ?? [],
    clinical_extraction: raw.clinical_extraction ? {
      ...raw.clinical_extraction,
      prior_treatments: raw.clinical_extraction.prior_treatments ?? [],
      severity_indicators: raw.clinical_extraction.severity_indicators ?? [],
      functional_limitations: raw.clinical_extraction.functional_limitations ?? [],
      diagnostic_findings: raw.clinical_extraction.diagnostic_findings ?? [],
    } : undefined,
  };
  return (
    <div className="space-y-4">
      {/* Low confidence extraction warning */}
      {data.clinical_extraction && data.clinical_extraction.extraction_confidence < 60 && (
        <div className="flex items-start gap-2 rounded-md border border-warning/50 bg-warning/5 p-3">
          <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" />
          <div className="text-sm">
            <span className="font-medium text-warning">Low Extraction Confidence</span>
            <span className="text-muted-foreground">
              {" "}({data.clinical_extraction.extraction_confidence}%) — clinical documentation
              was insufficient for high-confidence extraction. Findings below may be incomplete.
              Consider requesting additional supporting documentation.
            </span>
          </div>
        </div>
      )}

      {/* Checks summary — always visible */}
      <ChecksSummary
        checks={data.checks_performed}
        title="Clinical Review Checks Performed"
      />

      {/* Detailed sections — collapsible */}
      <CollapsibleSection
        title={`Diagnosis Validation (${data.diagnosis_validation.length} codes)`}
        icon={FileCheck}
        hasData={data.diagnosis_validation.length > 0}
        defaultOpen={data.diagnosis_validation.length > 0}
      >
        {data.diagnosis_validation.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-24">Code</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="w-20">Valid</TableHead>
                  <TableHead className="w-24">Billable</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.diagnosis_validation.map((d, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-mono text-sm">
                      {d.code}
                    </TableCell>
                    <TableCell>{d.description}</TableCell>
                    <TableCell>
                      {statusBadge(d.valid ? "pass" : "fail")}
                    </TableCell>
                    <TableCell>
                      {statusBadge(d.billable ? "pass" : "fail")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No diagnosis validation data available.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title="Clinical Extraction"
        icon={FileSearch}
        hasData={!!data.clinical_extraction}
        defaultOpen={!!data.clinical_extraction}
      >
        {data.clinical_extraction ? (
          <Card className="bg-muted/40">
            <CardContent className="pt-4 space-y-2 text-sm">
              <div>
                <span className="font-medium">Chief Complaint: </span>
                <span className="text-muted-foreground">
                  {data.clinical_extraction.chief_complaint}
                </span>
              </div>
              <div>
                <span className="font-medium">HPI: </span>
                <span className="text-muted-foreground">
                  {data.clinical_extraction.history_of_present_illness}
                </span>
              </div>
              <div>
                <span className="font-medium">Duration/Progression: </span>
                <span className="text-muted-foreground">
                  {data.clinical_extraction.duration_and_progression}
                </span>
              </div>
              {data.clinical_extraction.prior_treatments.length > 0 && (
                <div>
                  <span className="font-medium">Prior Treatments: </span>
                  <span className="text-muted-foreground">
                    {data.clinical_extraction.prior_treatments.join(", ")}
                  </span>
                </div>
              )}
              {data.clinical_extraction.severity_indicators.length > 0 && (
                <div>
                  <span className="font-medium">Severity Indicators: </span>
                  <span className="text-muted-foreground">
                    {data.clinical_extraction.severity_indicators.join(", ")}
                  </span>
                </div>
              )}
              {data.clinical_extraction.diagnostic_findings.length > 0 && (
                <div>
                  <span className="font-medium">Diagnostic Findings: </span>
                  <span className="text-muted-foreground">
                    {data.clinical_extraction.diagnostic_findings.join(", ")}
                  </span>
                </div>
              )}
              <div className="flex items-center gap-2 pt-1">
                <span className="font-medium">Extraction Confidence:</span>
                <ConfidenceBar
                  value={data.clinical_extraction.extraction_confidence}
                  className="w-40"
                />
              </div>
            </CardContent>
          </Card>
        ) : (
          <p className="text-sm text-muted-foreground">
            No clinical extraction data available.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title={`Literature Support (${data.literature_support.length} references)`}
        icon={BookOpen}
        hasData={data.literature_support.length > 0}
      >
        {data.literature_support.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead className="w-28">PMID</TableHead>
                  <TableHead>Relevance</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.literature_support.map((ref, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-medium">{ref.title}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {ref.pmid}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {ref.relevance}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No literature references found.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title={`Clinical Trials (${data.clinical_trials.length} trials)`}
        icon={FlaskConical}
        hasData={data.clinical_trials.length > 0}
      >
        {data.clinical_trials.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead className="w-32">NCT ID</TableHead>
                  <TableHead className="w-24">Status</TableHead>
                  <TableHead>Relevance</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.clinical_trials.map((trial, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-medium">{trial.title}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {trial.nct_id}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{trial.status}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {trial.relevance}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No clinical trials found.
          </p>
        )}
      </CollapsibleSection>

      {/* Clinical Summary */}
      {data.clinical_summary && (
        <CollapsibleSection
          title="Clinical Summary"
          icon={ScrollText}
          hasData={!!data.clinical_summary}
          defaultOpen
        >
          <p className="text-sm text-muted-foreground whitespace-pre-wrap">
            {data.clinical_summary}
          </p>
        </CollapsibleSection>
      )}

      {/* Tool results */}
      {data.tool_results.length > 0 && (
        <CollapsibleSection
          title={`Tool Results (${data.tool_results.length} tools)`}
          icon={ListChecks}
          hasData={data.tool_results.length > 0}
        >
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tool</TableHead>
                  <TableHead className="w-24">Status</TableHead>
                  <TableHead>Detail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.tool_results.map((t, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-medium">
                      {t.tool_name}
                    </TableCell>
                    <TableCell>{statusBadge(t.status)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {t.detail}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CollapsibleSection>
      )}

      {data.error && (
        <p className="text-sm text-destructive">Error: {data.error}</p>
      )}
    </div>
  );
}

function CoverageTab({ data: raw }: { data: CoverageResult }) {
  // Normalize potentially-null arrays from API response
  const data = {
    ...raw,
    checks_performed: raw.checks_performed ?? [],
    coverage_policies: raw.coverage_policies ?? [],
    criteria_assessment: raw.criteria_assessment ?? [],
    coverage_criteria_met: raw.coverage_criteria_met ?? [],
    coverage_criteria_not_met: raw.coverage_criteria_not_met ?? [],
    policy_references: raw.policy_references ?? [],
    coverage_limitations: raw.coverage_limitations ?? [],
    documentation_gaps: raw.documentation_gaps ?? [],
    tool_results: raw.tool_results ?? [],
  };
  return (
    <div className="space-y-4">
      {/* Checks summary — always visible */}
      <ChecksSummary
        checks={data.checks_performed}
        title="Coverage Assessment Checks Performed"
      />

      {/* Detailed sections — collapsible */}
      <CollapsibleSection
        title="Provider Verification"
        icon={UserCheck}
        hasData={!!data.provider_verification}
        defaultOpen={!!data.provider_verification}
      >
        {data.provider_verification ? (
          <Card className="bg-muted/40">
            <CardContent className="pt-4 text-sm space-y-1">
              <div>
                <span className="font-medium">NPI: </span>
                <span className="font-mono">
                  {data.provider_verification.npi}
                </span>
              </div>
              <div>
                <span className="font-medium">Name: </span>
                {data.provider_verification.name}
              </div>
              <div>
                <span className="font-medium">Specialty: </span>
                {data.provider_verification.specialty}
              </div>
              <div className="flex items-center gap-2">
                <span className="font-medium">Status:</span>
                {statusBadge(data.provider_verification.status)}
              </div>
              <p className="text-muted-foreground">
                {data.provider_verification.detail}
              </p>
            </CardContent>
          </Card>
        ) : (
          <p className="text-sm text-muted-foreground">
            No provider verification data available.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title={`Coverage Policies (${data.coverage_policies.length} policies)`}
        icon={BookOpen}
        hasData={data.coverage_policies.length > 0}
        defaultOpen={data.coverage_policies.length > 0}
      >
        {data.coverage_policies.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Policy ID</TableHead>
                  <TableHead>Title</TableHead>
                  <TableHead className="w-20">Type</TableHead>
                  <TableHead className="w-24">Relevant</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.coverage_policies.map((p, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-mono text-xs">
                      {p.policy_id}
                    </TableCell>
                    <TableCell>{p.title}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{p.type}</Badge>
                    </TableCell>
                    <TableCell>
                      {statusBadge(p.relevant ? "pass" : "fail")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No coverage policies found.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title={`Criteria Assessment (${data.criteria_assessment.length} criteria)`}
        icon={ListChecks}
        hasData={data.criteria_assessment.length > 0}
        defaultOpen={data.criteria_assessment.length > 0}
      >
        {data.criteria_assessment.length > 0 ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Criterion</TableHead>
                  <TableHead className="w-28">Status</TableHead>
                  <TableHead className="w-28">Confidence</TableHead>
                  <TableHead>Notes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.criteria_assessment.map((c, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-medium">
                      {c.criterion}
                    </TableCell>
                    <TableCell>{statusBadge(c.status)}</TableCell>
                    <TableCell>
                      <ConfidenceBar value={c.confidence} className="w-24" />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {c.notes}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No criteria assessment data available.
          </p>
        )}
      </CollapsibleSection>

      {/* Documentation gaps */}
      {data.documentation_gaps.length > 0 && (
        <CollapsibleSection
          title={`Documentation Gaps (${data.documentation_gaps.length} gaps)`}
          icon={AlertTriangle}
          hasData={data.documentation_gaps.length > 0}
          defaultOpen
        >
          <div className="space-y-2">
            {data.documentation_gaps.map((gap, i) => (
              <Card
                key={i}
                className={
                  gap.critical ? "border-destructive/50" : "border-amber-500/50"
                }
              >
                <CardContent className="py-3 text-sm">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant={gap.critical ? "destructive" : "warning"}>
                      {gap.critical ? "Critical" : "Non-critical"}
                    </Badge>
                    <span className="font-medium">{gap.what}</span>
                  </div>
                  <p className="text-muted-foreground">{gap.request}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {/* Coverage limitations */}
      {data.coverage_limitations.length > 0 && (
        <div>
          <h4 className="text-sm font-medium mb-1 flex items-center gap-1.5">
            <Info className="h-3.5 w-3.5 text-muted-foreground" />
            Coverage Limitations
          </h4>
          <ul className="list-disc list-inside text-sm text-muted-foreground space-y-0.5">
            {data.coverage_limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Tool results */}
      {data.tool_results.length > 0 && (
        <CollapsibleSection
          title={`Tool Results (${data.tool_results.length} tools)`}
          icon={ListChecks}
          hasData={data.tool_results.length > 0}
        >
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tool</TableHead>
                  <TableHead className="w-24">Status</TableHead>
                  <TableHead>Detail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.tool_results.map((t, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-medium">
                      {t.tool_name}
                    </TableCell>
                    <TableCell>{statusBadge(t.status)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {t.detail}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CollapsibleSection>
      )}

      {data.error && (
        <p className="text-sm text-destructive">Error: {data.error}</p>
      )}
    </div>
  );
}

interface AgentDetailsProps {
  results: AgentResults;
  synthesis?: SynthesisData;
}

// Minimal shape of synthesis data needed for this tab — avoids importing
// the full ReviewResponse type and creating a circular dep.
interface SynthesisData {
  recommendation: string;
  confidence: number;
  confidence_level: string;
  decision_gate?: string;
  criteria_summary?: string;
  clinical_rationale?: string;
  missing_documentation?: string[];
  disclaimer?: string;
  synthesis_audit_trail?: {
    gate_results?: Record<string, string>;
    confidence_components?: Record<string, number>;
    agents_consulted?: string[];
  };
}

type GateStatus = "pass" | "fail" | "na";

function getGateStatuses(decisionGate: string): [GateStatus, GateStatus, GateStatus] {
  // Exact match first
  switch (decisionGate) {
    case "approved":           return ["pass", "pass", "pass"];
    case "gate_1_provider":    return ["fail", "na",   "na"];
    case "gate_2_codes":       return ["pass", "fail", "na"];
    case "gate_3_necessity":   return ["pass", "pass", "fail"];
  }
  // Fuzzy match for free-text responses from the agent
  const lower = decisionGate.toLowerCase();
  if (lower.includes("approved") || lower.includes("all gates pass"))
    return ["pass", "pass", "pass"];
  if (lower.includes("gate 1") || lower.includes("provider"))
    return ["fail", "na", "na"];
  if (lower.includes("gate 2") || lower.includes("code"))
    return ["pass", "fail", "na"];
  if (lower.includes("gate 3") || lower.includes("necessity") || lower.includes("insufficient"))
    return ["pass", "pass", "fail"];
  return ["na", "na", "na"];
}

const GATES = [
  {
    label: "Gate 1 — Provider Verification",
    description: "NPI valid and active in NPPES registry",
  },
  {
    label: "Gate 2 — Code Validation",
    description: "All ICD-10 and CPT/HCPCS codes valid and billable",
  },
  {
    label: "Gate 3 — Medical Necessity",
    description: "All coverage criteria MET with sufficient clinical evidence",
  },
];

function GateIcon({ status }: { status: GateStatus }) {
  if (status === "pass") return <CheckCircle2 className="h-4 w-4 text-success shrink-0" />;
  if (status === "fail") return <XCircle className="h-4 w-4 text-destructive shrink-0" />;
  return <HelpCircle className="h-4 w-4 text-muted-foreground shrink-0" />;
}

function SynthesisTab({ data }: { data: SynthesisData }) {
  const isApprove = data.recommendation === "approve";
  const confidenceVal = data.confidence <= 1
    ? Math.round(data.confidence * 100)
    : Math.round(data.confidence);
  const gateStatuses = getGateStatuses(data.decision_gate ?? "");
  const missingDocs = data.missing_documentation ?? [];

  return (
    <div className="space-y-5 pt-4">
      {/* Decision + confidence header */}
      <div className="space-y-2">
        <div className="flex items-center gap-3 flex-wrap">
          <Badge
            variant={isApprove ? "success" : "warning"}
            className="text-sm px-3 py-1"
          >
            {isApprove ? "APPROVE" : "PEND FOR REVIEW"}
          </Badge>
          <Badge variant="outline">{data.confidence_level}</Badge>
          {data.criteria_summary && (
            <span className="text-sm text-muted-foreground">{data.criteria_summary}</span>
          )}
        </div>
        <ConfidenceBar value={confidenceVal} className="max-w-sm" />
      </div>

      {/* 3-gate pipeline */}
      <div className="space-y-2">
        <h4 className="text-sm font-semibold flex items-center gap-1.5">
          <GitBranch className="h-4 w-4 text-primary" />
          Decision Gate Pipeline
        </h4>
        <div className="space-y-2">
          {GATES.map((gate, i) => {
            const status = gateStatuses[i];
            const rowCls =
              status === "pass"
                ? "bg-success/5 border-success/30"
                : status === "fail"
                  ? "bg-destructive/5 border-destructive/30"
                  : "bg-muted/20 border-muted/40";
            return (
              <div
                key={i}
                className={`flex items-start gap-3 rounded-lg border p-3 ${rowCls}`}
              >
                <GateIcon status={status} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{gate.label}</p>
                  <p className="text-xs text-muted-foreground">{gate.description}</p>
                </div>
                <Badge
                  variant={
                    status === "pass"
                      ? "success"
                      : status === "fail"
                        ? "destructive"
                        : "secondary"
                  }
                  className="shrink-0 text-xs"
                >
                  {status === "pass" ? "PASS" : status === "fail" ? "FAIL" : "N/A"}
                </Badge>
              </div>
            );
          })}
        </div>
      </div>

      {/* Clinical rationale */}
      {data.clinical_rationale && (
        <CollapsibleSection
          title="Clinical Rationale"
          icon={ScrollText}
          defaultOpen
        >
          <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-line">
            {data.clinical_rationale}
          </p>
        </CollapsibleSection>
      )}

      {/* Missing documentation */}
      {missingDocs.length > 0 && (
        <CollapsibleSection
          title={`Missing Documentation (${missingDocs.length})`}
          icon={AlertTriangle}
        >
          <ul className="space-y-1.5">
            {missingDocs.map((doc, i) => (
              <li key={i} className="text-sm text-muted-foreground flex items-start gap-1.5">
                <AlertCircle className="h-3.5 w-3.5 text-warning shrink-0 mt-0.5" />
                {doc}
              </li>
            ))}
          </ul>
        </CollapsibleSection>
      )}

      {/* Confidence Score Breakdown */}
      {data.synthesis_audit_trail?.confidence_components &&
        Object.keys(data.synthesis_audit_trail.confidence_components).length > 0 && (
        <CollapsibleSection title="Confidence Score Breakdown" icon={Bot}>
          <div className="space-y-2.5">
            <p className="text-xs text-muted-foreground pb-1">
              Weighted: 40% criteria quality + 30% extraction + 20% documentation + 10% policy alignment
            </p>
            {([
              { label: "Criteria Quality",           wKey: "criteria_weight",   sKey: "criteria_score" },
              { label: "Clinical Extraction",         wKey: "extraction_weight", sKey: "extraction_score" },
              { label: "Documentation Completeness",  wKey: "compliance_weight", sKey: "compliance_score" },
              { label: "Policy Alignment",            wKey: "policy_weight",     sKey: "policy_score" },
            ] as const).map((row, i) => {
              const cc = data.synthesis_audit_trail!.confidence_components!;
              const score = cc[row.sKey] ?? 0;
              const weight = cc[row.wKey] ?? 0;
              return (
                <div key={i} className="flex items-center gap-3">
                  <span className="text-sm flex-1">{row.label}</span>
                  <span className="text-xs text-muted-foreground w-10 text-right shrink-0">
                    ×{Math.round(weight * 100)}%
                  </span>
                  <ConfidenceBar value={Math.round(score * 100)} className="w-28 shrink-0" />
                  <span className="text-xs text-muted-foreground w-8 text-right shrink-0">
                    {Math.round(score * 100)}%
                  </span>
                </div>
              );
            })}
          </div>
        </CollapsibleSection>
      )}

      {/* Disclaimer */}
      {data.disclaimer && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-50/40 dark:bg-amber-950/20 p-3">
          <AlertCircle className="h-3.5 w-3.5 text-amber-600 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-700 dark:text-amber-400 leading-relaxed">{data.disclaimer}</p>
        </div>
      )}
    </div>
  );
}

export function AgentDetails({ results, synthesis }: AgentDetailsProps) {
  const tabs = [
    { id: "compliance", label: "Compliance", icon: ClipboardCheck, data: results.compliance },
    { id: "clinical",   label: "Clinical",   icon: Stethoscope,    data: results.clinical },
    { id: "coverage",   label: "Coverage",   icon: Shield,          data: results.coverage },
    ...(synthesis ? [{ id: "synthesis", label: "Synthesis", icon: GitBranch, data: synthesis as object }] : []),
  ].filter((t) => t.data);

  if (tabs.length === 0) return null;

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Bot className="h-5 w-5 text-primary" />
          Agent Details
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue={tabs[0].id}>
          <TabsList>
            {tabs.map((t) => (
              <TabsTrigger key={t.id} value={t.id} className="flex items-center gap-1.5">
                <t.icon className="h-3.5 w-3.5" />
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>

          {results.compliance && (
            <TabsContent value="compliance">
              <ComplianceTab data={results.compliance} />
            </TabsContent>
          )}
          {results.clinical && (
            <TabsContent value="clinical">
              <ClinicalTab data={results.clinical} />
            </TabsContent>
          )}
          {results.coverage && (
            <TabsContent value="coverage">
              <CoverageTab data={results.coverage} />
            </TabsContent>
          )}
          {synthesis && (
            <TabsContent value="synthesis">
              <SynthesisTab data={synthesis} />
            </TabsContent>
          )}
        </Tabs>
      </CardContent>
    </Card>
  );
}
