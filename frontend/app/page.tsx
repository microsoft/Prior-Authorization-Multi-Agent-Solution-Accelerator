"use client";

import { useState } from "react";
import type { ReviewResponse } from "@/lib/types";
import { Header } from "@/components/header";
import { UploadForm } from "@/components/upload-form";
import { ReviewDashboard } from "@/components/review-dashboard";

export default function Home() {
  const [review, setReview] = useState<ReviewResponse | null>(null);

  return (
    <div className="min-h-screen bg-gradient-to-b from-info-light/50 via-background to-background">
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-12">
        <Header />
        <UploadForm onReviewComplete={setReview} onClear={() => setReview(null)} />
        {review && <ReviewDashboard review={review} />}
      </main>

      <footer className="border-t mt-16 py-6">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>Prior Authorization Review System</span>
          <span>
            AI-assisted draft &mdash; all decisions require human clinical review
          </span>
        </div>
      </footer>
    </div>
  );
}
