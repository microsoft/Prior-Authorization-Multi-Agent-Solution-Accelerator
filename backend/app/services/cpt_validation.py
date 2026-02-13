"""CPT/HCPCS code format validation and curated lookup table.

Pre-agent validation layer:
  - Format validation: definitive (5-digit CPT or letter+4 HCPCS)
  - Lookup table: informational (~30 common PA-trigger codes)

This does NOT replace payer-specific code checks. It catches typos and
provides descriptions for well-known codes before agents run.
"""

import re


# --- Format validation ---

_CPT_PATTERN = re.compile(r"^\d{5}$")
_HCPCS_PATTERN = re.compile(r"^[A-V]\d{4}$")


def validate_code_format(code: str) -> dict:
    """Validate CPT/HCPCS code format.

    Returns dict with:
      code: the original code
      valid_format: True if format matches CPT or HCPCS pattern
      code_type: "CPT" | "HCPCS" | "unknown"
      detail: human-readable message
    """
    code = code.strip().upper()

    if _CPT_PATTERN.match(code):
        return {
            "code": code,
            "valid_format": True,
            "code_type": "CPT",
            "detail": f"{code} — valid CPT format (5-digit numeric)",
        }
    elif _HCPCS_PATTERN.match(code):
        return {
            "code": code,
            "valid_format": True,
            "code_type": "HCPCS",
            "detail": f"{code} — valid HCPCS Level II format (letter + 4 digits)",
        }
    else:
        return {
            "code": code,
            "valid_format": False,
            "code_type": "unknown",
            "detail": (
                f"{code} — invalid format. "
                "Expected 5-digit CPT (e.g. 31628) or "
                "letter+4 HCPCS (e.g. J9271)."
            ),
        }


# --- Curated lookup table (~30 common PA-trigger codes) ---

_KNOWN_CODES: dict[str, dict] = {
    # Pulmonary / Bronchoscopy
    "31628": {"description": "Bronchoscopy with transbronchial lung biopsy", "category": "Pulmonary"},
    "31629": {"description": "Bronchoscopy with transbronchial needle aspiration", "category": "Pulmonary"},
    "31652": {"description": "Bronchoscopy with endobronchial ultrasound (EBUS)", "category": "Pulmonary"},
    # Imaging - Advanced
    "71260": {"description": "CT chest with contrast", "category": "Imaging"},
    "71250": {"description": "CT chest without contrast", "category": "Imaging"},
    "77014": {"description": "CT guidance for biopsy/aspiration", "category": "Imaging"},
    "70553": {"description": "MRI brain with and without contrast", "category": "Imaging"},
    "74177": {"description": "CT abdomen and pelvis with contrast", "category": "Imaging"},
    # Oncology - Infusion / Chemo
    "96413": {"description": "Chemotherapy administration IV infusion, first hour", "category": "Oncology"},
    "96415": {"description": "Chemotherapy administration IV infusion, each additional hour", "category": "Oncology"},
    "96417": {"description": "Chemotherapy administration IV push, additional drug", "category": "Oncology"},
    # Oncology - Specific Drugs (HCPCS)
    "J9271": {"description": "Injection, pembrolizumab, 1 mg", "category": "Oncology - Drug"},
    "J9299": {"description": "Injection, nivolumab, 1 mg", "category": "Oncology - Drug"},
    "J9035": {"description": "Injection, bevacizumab, 10 mg", "category": "Oncology - Drug"},
    "J9305": {"description": "Injection, pemetrexed, 10 mg", "category": "Oncology - Drug"},
    "J9228": {"description": "Injection, ipilimumab, 1 mg", "category": "Oncology - Drug"},
    # Orthopedic
    "27447": {"description": "Total knee arthroplasty (replacement)", "category": "Orthopedic"},
    "27130": {"description": "Total hip arthroplasty (replacement)", "category": "Orthopedic"},
    "29881": {"description": "Arthroscopy knee, meniscectomy", "category": "Orthopedic"},
    # Cardiology
    "93458": {"description": "Left heart catheterization with angiography", "category": "Cardiology"},
    "93306": {"description": "Transthoracic echocardiography, complete", "category": "Cardiology"},
    "33361": {"description": "Transcatheter aortic valve replacement (TAVR)", "category": "Cardiology"},
    # Neurology / Spine
    "63030": {"description": "Lumbar laminotomy/discectomy, single level", "category": "Spine"},
    "22551": {"description": "Anterior cervical discectomy and fusion (ACDF)", "category": "Spine"},
    # GI
    "43239": {"description": "Upper GI endoscopy with biopsy", "category": "GI"},
    "45385": {"description": "Colonoscopy with polyp removal", "category": "GI"},
    # DME (HCPCS)
    "E0601": {"description": "CPAP device", "category": "DME"},
    "L8614": {"description": "Cochlear implant device", "category": "DME"},
    # Genetic Testing
    "81479": {"description": "Unlisted molecular pathology procedure", "category": "Genetic Testing"},
    "81455": {"description": "Targeted genomic sequence analysis panel, solid organ neoplasm", "category": "Genetic Testing"},
}


def lookup_code(code: str) -> dict:
    """Look up a CPT/HCPCS code in the curated table.

    Returns dict with:
      code: the code
      found: True if in the table
      description: human-readable description (or "")
      category: clinical category (or "")
    """
    code = code.strip().upper()
    entry = _KNOWN_CODES.get(code)
    if entry:
        return {
            "code": code,
            "found": True,
            "description": entry["description"],
            "category": entry["category"],
        }
    return {
        "code": code,
        "found": False,
        "description": "",
        "category": "",
    }


def validate_procedure_codes(codes: list[str]) -> dict:
    """Validate a list of procedure codes: format check + curated lookup.

    Returns dict with:
      valid: True if ALL codes have valid format
      results: list of per-code results
      summary: human-readable summary
    """
    results = []
    all_valid = True

    for code in codes:
        fmt = validate_code_format(code)
        info = lookup_code(code)

        entry = {
            "code": fmt["code"],
            "valid_format": fmt["valid_format"],
            "code_type": fmt["code_type"],
            "known": info["found"],
            "description": info["description"],
            "category": info["category"],
            "detail": fmt["detail"],
        }

        if not fmt["valid_format"]:
            all_valid = False

        results.append(entry)

    # Build summary
    total = len(results)
    valid_count = sum(1 for r in results if r["valid_format"])
    known_count = sum(1 for r in results if r["known"])

    summary = f"{valid_count}/{total} codes valid format"
    if known_count:
        summary += f", {known_count} recognized in lookup table"
    if not all_valid:
        invalid = [r["code"] for r in results if not r["valid_format"]]
        summary += f". INVALID: {', '.join(invalid)}"

    return {
        "valid": all_valid,
        "results": results,
        "summary": summary,
    }
