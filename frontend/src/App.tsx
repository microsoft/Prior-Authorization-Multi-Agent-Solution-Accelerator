import { useState } from "react";
import UploadForm from "./components/UploadForm";
import ReviewDashboard from "./components/ReviewDashboard";
import type { ReviewResponse } from "./types";

const styles: Record<string, React.CSSProperties> = {
  container: {
    maxWidth: 900,
    margin: "0 auto",
    padding: "2rem 1rem",
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    color: "#1a1a2e",
  },
  header: {
    textAlign: "center",
    marginBottom: "2rem",
    borderBottom: "2px solid #e0e0e0",
    paddingBottom: "1rem",
  },
  title: { fontSize: "1.75rem", fontWeight: 700, margin: 0 },
  subtitle: { color: "#666", marginTop: "0.25rem", fontSize: "0.95rem" },
};

export default function App() {
  const [review, setReview] = useState<ReviewResponse | null>(null);

  return (
    <div style={styles.container}>
      <header style={styles.header}>
        <h1 style={styles.title}>Prior Authorization Review</h1>
        <p style={styles.subtitle}>
          AI-assisted clinical review powered by Claude &amp; Microsoft Agent
          Framework
        </p>
      </header>

      <UploadForm onReviewComplete={setReview} />
      {review && <ReviewDashboard review={review} />}
    </div>
  );
}
