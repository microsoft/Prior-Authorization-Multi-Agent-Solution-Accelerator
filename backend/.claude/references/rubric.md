# Decision Policy Rubric

This rubric defines the decision framework for prior authorization review.
It is referenced by the Synthesis Decision Skill and applies to the final
recommendation after all agent outputs have been aggregated.

---

## Decision Modes

### LENIENT Mode (Default)

In LENIENT mode, the system recommends **APPROVE** or **PEND** only -- never
DENY. The philosophy is: request additional information instead of denying.
Only approve when clearly supported by evidence.

### Strict Mode (Optional)

Organizations can enable Strict Mode by setting `DECISION_MODE=strict` in
configuration. In Strict Mode, certain PEND outcomes become DENY:

| Scenario | LENIENT | STRICT |
|----------|---------|--------|
| Invalid ICD-10/CPT codes | PEND | DENY |
| Required criterion NOT_MET | PEND | DENY |
| Provider NPI inactive | PEND | PEND |
| INSUFFICIENT evidence | PEND | PEND |
| No coverage policy found | PEND | PEND |

---

## Gate-Based Evaluation

Evaluate gates in strict sequential order. **Stop at the first failing gate.**

### Gate 1: Provider Verification

| Scenario | Action |
|----------|--------|
| Provider NPI valid and active | PASS -- continue to Gate 2 |
| Provider NPI invalid format | PEND -- request corrected NPI |
| Provider NPI not found in NPPES | PEND -- request credentialing documentation |
| Provider NPI inactive/deactivated | PEND -- request current credentialing info |
| Demo mode NPI (matched with sample member ID) | PASS -- continue to Gate 2 |

### Gate 2: Code Validation

| Scenario | Action |
|----------|--------|
| All ICD-10 codes valid and billable | PASS -- continue to Gate 3 |
| Any ICD-10 code invalid | PEND -- request diagnosis code clarification |
| ICD-10 code valid but not billable (category header) | PEND -- request specific code |
| All CPT/HCPCS codes valid and active | PASS -- continue to Gate 3 |
| Any CPT/HCPCS code invalid or inactive | PEND -- request procedure code clarification |
| CPT/HCPCS format valid but not verified | PASS with warning -- continue to Gate 3 |

### Gate 3: Medical Necessity Criteria

| Scenario | Action |
|----------|--------|
| All required criteria MET | APPROVE |
| Any required criterion NOT_MET | PEND -- request additional documentation |
| Any required criterion INSUFFICIENT | PEND -- specify what evidence is needed |
| No coverage policy found | PEND -- manual policy review needed |
| Documentation incomplete (from Compliance) | PEND -- specify missing items |
| Diagnosis-Policy Alignment NOT_MET | PEND -- diagnosis outside policy scope |

### Catch-All

| Scenario | Action |
|----------|--------|
| Uncertain or conflicting signals | PEND -- default safe option |
| Agent error in any sub-agent | PEND -- note agent error, require manual review |

---

## Confidence Scoring

### Formula

```
overall = (0.4 * avg_criteria / 100)
        + (0.3 * extraction / 100)
        + (0.2 * compliance_score)
        + (0.1 * policy_match)
```

Where:
- **avg_criteria** (0-100): Average of per-criterion confidence scores from Coverage Agent
- **extraction** (0-100): Clinical Reviewer's extraction_confidence
- **compliance_score** (0.0-1.0): 1.0 if all items complete, minus 0.1 per incomplete/missing item (floor 0.0)
- **policy_match** (0.0-1.0): 1.0 if policy found and primary diagnosis aligns, 0.5 if policy found but alignment unclear, 0.0 if no policy found

### Confidence Levels

| Level | Range | Meaning |
|-------|-------|---------|
| HIGH | 0.80 - 1.0 | All criteria MET with strong evidence, no documentation gaps |
| MEDIUM | 0.50 - 0.79 | Most criteria MET but some with moderate evidence or minor gaps |
| LOW | 0.0 - 0.49 | Significant gaps, INSUFFICIENT criteria, agent errors, or missing policy |

### Penalty Adjustments

- Agent error: -0.20 per agent that returned an error
- Missing policy: -0.10 (applied via policy_match = 0.0)
- Low extraction confidence (< 60%): flag as LOW CONFIDENCE WARNING

---

## Override Permissions

Human reviewers may override AI recommendations with documented justification:

| Override | When Appropriate | Requirement |
|----------|-----------------|-------------|
| PEND --> APPROVE | Additional documentation received that satisfies all requirements | Document which criteria are now MET |
| APPROVE --> PEND | New information raises clinical or coverage concerns | Document the specific concern |
| PEND --> DENY (Strict only) | Clear policy exclusion with no ambiguity | Clinical justification required |
| Any override | Reviewer disagrees with AI assessment | Written rationale required |

**Note**: In this multi-agent pipeline, overrides are performed by the human
reviewer through the frontend UI, not by the AI agents. The override permissions
are documented here for completeness and to guide the human reviewer.

---

## Appeals Guidance (for PEND Decisions)

When a request is PEND, the output should include:
1. Specific documentation that would resolve the PEND
2. Which criteria need additional evidence
3. Which gate blocked the approval
4. Suggested items for the provider to submit

This information is used in the notification letter sent to the provider.
