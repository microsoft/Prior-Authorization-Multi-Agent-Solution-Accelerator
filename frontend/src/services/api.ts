import type { PriorAuthRequest, ReviewResponse, DecisionRequest, DecisionResponse } from "../types";

const API_BASE = "/api";

export async function submitReview(
  request: PriorAuthRequest
): Promise<ReviewResponse> {
  const response = await fetch(`${API_BASE}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Review failed (${response.status})`);
  }

  return response.json();
}

export async function submitDecision(
  request: DecisionRequest
): Promise<DecisionResponse> {
  const response = await fetch(`${API_BASE}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Decision failed (${response.status})`);
  }

  return response.json();
}
