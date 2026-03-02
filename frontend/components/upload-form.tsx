"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Plus, X, FlaskConical, User, CalendarDays, Hash, CreditCard, Stethoscope, FileText, Send } from "lucide-react";
import type { PriorAuthRequest, ReviewResponse, ReviewProgress, ProgressEvent, AgentId } from "@/lib/types";
import { submitReviewStream } from "@/lib/api";
import { SAMPLE_REQUEST } from "@/lib/sample-case";
import { ProgressTracker } from "@/components/progress-tracker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";

interface UploadFormProps {
  onReviewComplete: (review: ReviewResponse) => void;
}

const emptyRequest: PriorAuthRequest = {
  patient_name: "",
  patient_dob: "",
  provider_npi: "",
  diagnosis_codes: [""],
  procedure_codes: [""],
  clinical_notes: "",
  insurance_id: "",
};

export function UploadForm({ onReviewComplete }: UploadFormProps) {
  const [form, setForm] = useState<PriorAuthRequest>(emptyRequest);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ReviewProgress | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const initialProgress: ReviewProgress = {
    currentPhase: "preflight",
    progressPct: 0,
    message: "Starting review...",
    agents: {
      compliance: { status: "pending", detail: "Waiting" },
      clinical: { status: "pending", detail: "Waiting" },
      coverage: { status: "pending", detail: "Waiting" },
      synthesis: { status: "pending", detail: "Waiting" },
    },
    phases: {
      preflight: "pending",
      phase_1: "pending",
      phase_2: "pending",
      phase_3: "pending",
      phase_4: "pending",
    },
  };

  function applyProgressEvent(prev: ReviewProgress, event: ProgressEvent): ReviewProgress {
    const next = { ...prev };
    next.currentPhase = event.phase;
    next.progressPct = event.progress_pct;
    next.message = event.message;
    next.phases = { ...prev.phases, [event.phase]: event.status };
    next.agents = { ...prev.agents };
    for (const [agentId, agentState] of Object.entries(event.agents ?? {})) {
      next.agents[agentId as AgentId] = agentState;
    }
    return next;
  }

  function updateField<K extends keyof PriorAuthRequest>(
    key: K,
    value: PriorAuthRequest[K]
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function updateCode(
    field: "diagnosis_codes" | "procedure_codes",
    index: number,
    value: string
  ) {
    const updated = [...form[field]];
    updated[index] = value;
    updateField(field, updated);
  }

  function addCode(field: "diagnosis_codes" | "procedure_codes") {
    updateField(field, [...form[field], ""]);
  }

  function removeCode(
    field: "diagnosis_codes" | "procedure_codes",
    index: number
  ) {
    if (form[field].length <= 1) return;
    updateField(
      field,
      form[field].filter((_, i) => i !== index)
    );
  }

  function loadSample() {
    setForm({ ...SAMPLE_REQUEST });
    setError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setProgress(initialProgress);

    const cleaned: PriorAuthRequest = {
      ...form,
      diagnosis_codes: form.diagnosis_codes.filter((c) => c.trim()),
      procedure_codes: form.procedure_codes.filter((c) => c.trim()),
    };

    abortRef.current = submitReviewStream(
      cleaned,
      (event) => {
        setProgress((prev) => prev ? applyProgressEvent(prev, event) : prev);
      },
      (result) => {
        setLoading(false);
        setProgress(null);
        onReviewComplete(result);
        toast.success("Review complete", {
          description: result.recommendation === "approve"
            ? "Recommendation: Approve"
            : "Recommendation: Pend for Review",
        });
      },
      (errMsg) => {
        setLoading(false);
        setProgress((prev) => prev ? { ...prev, error: errMsg } : prev);
        setError(errMsg);
        toast.error("Review failed", { description: errMsg });
      },
    );
  }

  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div>
          <CardTitle className="text-lg flex items-center gap-2">
            <FileText className="h-5 w-5 text-primary" />
            New Authorization Request
          </CardTitle>
          <p className="text-sm text-muted-foreground mt-1">
            Enter patient and procedure details for AI-assisted clinical review
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={loadSample}>
          <FlaskConical className="mr-1 h-3.5 w-3.5" />
          Load Sample Case
        </Button>
      </CardHeader>

      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Row 1: Patient info */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="patient_name" className="flex items-center gap-1.5">
                <User className="h-3.5 w-3.5 text-muted-foreground" />
                Patient Name
              </Label>
              <Input
                id="patient_name"
                placeholder="Jane Doe"
                value={form.patient_name}
                onChange={(e) => updateField("patient_name", e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="patient_dob" className="flex items-center gap-1.5">
                <CalendarDays className="h-3.5 w-3.5 text-muted-foreground" />
                Date of Birth
              </Label>
              <Input
                id="patient_dob"
                type="date"
                value={form.patient_dob}
                onChange={(e) => updateField("patient_dob", e.target.value)}
                required
              />
            </div>
          </div>

          {/* Row 2: Provider / Insurance */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="provider_npi" className="flex items-center gap-1.5">
                <Hash className="h-3.5 w-3.5 text-muted-foreground" />
                Provider NPI
              </Label>
              <Input
                id="provider_npi"
                placeholder="1234567890"
                value={form.provider_npi}
                onChange={(e) => updateField("provider_npi", e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="insurance_id" className="flex items-center gap-1.5">
                <CreditCard className="h-3.5 w-3.5 text-muted-foreground" />
                Insurance ID (optional)
              </Label>
              <Input
                id="insurance_id"
                placeholder="MCR-123456789A"
                value={form.insurance_id ?? ""}
                onChange={(e) => updateField("insurance_id", e.target.value)}
              />
            </div>
          </div>

          {/* Section divider: Codes */}
          <div className="relative">
            <div className="absolute inset-0 flex items-center"><span className="w-full border-t" /></div>
            <div className="relative flex justify-center text-xs uppercase"><span className="bg-card px-2 text-muted-foreground">Codes</span></div>
          </div>

          {/* Dynamic code arrays */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Diagnosis codes */}
            <div className="space-y-2">
              <Label className="flex items-center gap-1.5">
                <Stethoscope className="h-3.5 w-3.5 text-muted-foreground" />
                Diagnosis Codes (ICD-10)
              </Label>
              {form.diagnosis_codes.map((code, i) => (
                <div key={i} className="flex gap-1">
                  <Input
                    placeholder="e.g. R91.1"
                    value={code}
                    onChange={(e) =>
                      updateCode("diagnosis_codes", i, e.target.value)
                    }
                  />
                  {form.diagnosis_codes.length > 1 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => removeCode("diagnosis_codes", i)}
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => addCode("diagnosis_codes")}
              >
                <Plus className="mr-1 h-3.5 w-3.5" />
                Add Code
              </Button>
            </div>

            {/* Procedure codes */}
            <div className="space-y-2">
              <Label className="flex items-center gap-1.5">
                <Hash className="h-3.5 w-3.5 text-muted-foreground" />
                Procedure Codes (CPT)
              </Label>
              {form.procedure_codes.map((code, i) => (
                <div key={i} className="flex gap-1">
                  <Input
                    placeholder="e.g. 31628"
                    value={code}
                    onChange={(e) =>
                      updateCode("procedure_codes", i, e.target.value)
                    }
                  />
                  {form.procedure_codes.length > 1 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => removeCode("procedure_codes", i)}
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => addCode("procedure_codes")}
              >
                <Plus className="mr-1 h-3.5 w-3.5" />
                Add Code
              </Button>
            </div>
          </div>

          {/* Section divider: Clinical Information */}
          <div className="relative">
            <div className="absolute inset-0 flex items-center"><span className="w-full border-t" /></div>
            <div className="relative flex justify-center text-xs uppercase"><span className="bg-card px-2 text-muted-foreground">Clinical Information</span></div>
          </div>

          {/* Clinical notes */}
          <div className="space-y-2">
            <Label htmlFor="clinical_notes" className="flex items-center gap-1.5">
              <FileText className="h-3.5 w-3.5 text-muted-foreground" />
              Clinical Notes
            </Label>
            <Textarea
              id="clinical_notes"
              rows={5}
              placeholder="Enter clinical notes, history of present illness, prior treatments..."
              value={form.clinical_notes}
              onChange={(e) => updateField("clinical_notes", e.target.value)}
              required
            />
          </div>

          {/* Progress tracker */}
          {progress && (
            <ProgressTracker progress={progress} />
          )}

          {/* Error */}
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {/* Submit */}
          <Button type="submit" className="w-full bg-gradient-to-r from-brand to-brand-dark hover:from-brand-hover hover:to-brand-hover-dark text-white shadow-md" disabled={loading}>
            {loading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-2 h-4 w-4" />
            )}
            {loading ? "Submitting for Review..." : "Submit for Review"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
