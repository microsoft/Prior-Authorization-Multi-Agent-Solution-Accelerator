# Copy summary

Status: Implemented.

## Purpose

Let a reviewer copy the completed automated review's summary into a clinical notes field or another plain-text destination with one action. Confirm whether copying succeeded.

## Behavior

### Placement and availability

- Add a button labeled **Copy summary** beside the **Summary** label in the **Review Result** card.
- Make it available as soon as the automated review result appears, for both **Recommend Approve** and **Pend for Review**. Clinician acceptance or override is not required.
- The button always belongs to the displayed review result. If a previous result remains visible while another review runs, it copies that displayed result. When a new result replaces it, subsequent clicks copy the new summary. Clearing the result removes its button.
- Keep the button adjacent to the summary on narrow layouts, allowing wrapping without overlap or horizontal overflow.

### Copied content

- Copy the displayed review's top-level `review.summary` as plain text. The separate **Clinical Summary** is a different field.
- Preserve the summary's original text, punctuation, spacing, and line breaks. Do not add a heading, recommendation badge, confidence value, patient details, disclaimer, or other metadata from surrounding fields.
- Use trimming only to detect an empty or whitespace-only summary. In that case, show the button disabled, make no clipboard write, and show no copy notification.
- Keep the summary selectable for manual copying.

### Copy attempt and feedback

- Start copying only when the user activates the button. Copy the summary associated with that activation.
- While the copy attempt is pending, temporarily disable the button to prevent overlapping attempts. Do not show success before the write completes.
- On confirmed success, show a success toast with the exact text: "Summary copied to clipboard."
- If copying fails, including when browser clipboard access is unavailable or blocked, show an error toast with the exact text: "Couldn't copy summary. Select and copy the text manually."
- Use the existing Sonner notifications at the top right, including their default styling and dismissal behavior.
- After either outcome, enable the button again if the displayed summary is nonempty. A later activation starts a fresh attempt.
- Manual selection and copying is the fallback. No alternate automatic copying method is required.

### Interaction

- Use a native button with the accessible name **Copy summary**, visible keyboard focus, and Enter/Space activation. It must not submit the authorization request form.
- Make success and error feedback available to screen readers through the notification system.
- Copying is a local clipboard action. It does not submit a request, record a clinician decision, or modify the review result.

## Acceptance checks

1. Complete an automated review with each recommendation outcome. The button appears beside Summary and works before and after a clinician records a decision.
2. Copy a summary containing multiple paragraphs, punctuation, and leading or trailing whitespace. Paste into a plain-text field and verify the original summary content, including paragraph breaks, with no surrounding labels or metadata.
3. Give the top-level Summary and Clinical Summary different values. Verify that only the top-level Summary is copied.
4. Hold a copy attempt pending. Verify that the button is temporarily disabled and no success toast appears. Resolve the attempt successfully and verify the exact success message and that copying can be repeated.
5. Reject a copy attempt, then separately make clipboard access unavailable. Each case shows the exact error message, shows no success message, leaves the summary selectable, and permits another attempt.
6. Display an empty summary, then a whitespace-only summary. The button is disabled, the existing clipboard content is untouched, and no copy notification appears.
7. Display a previous result while a new review runs, then replace it with the new result. Each activation copies the summary displayed at that moment. Clear the form and verify that the result and copy button disappear.
8. Activate the button with the keyboard. Verify visible focus, Enter/Space activation, accessible notifications, and no form submission. Check that the button and summary remain usable at desktop and narrow widths.

## Implementation references

- [Review dashboard](../frontend/components/review-dashboard.tsx): Summary rendering and the copy action.
- [Shared button](../frontend/components/ui/button.tsx): Existing button styles and native interaction.
- [App layout](../frontend/app/layout.tsx): Existing Sonner toaster.
- [Review result type](../frontend/lib/types.ts): `ReviewResponse.summary`.
- [Glossary](../CONTEXT.md): Meaning of review result and review summary.

## Verification

- Browser checks passed against the local frontend with simulated review responses, clinician decisions, and clipboard outcomes. They covered exact summary content, pending writes, success, rejection, missing clipboard access, empty summaries, retries, and result replacement or clearing.
- Clear-form integration checks ran with [PR #44](https://github.com/microsoft/Prior-Authorization-Multi-Agent-Solution-Accelerator/pull/44) applied. That PR supplies the Clear form action; the Copy summary action works independently of it.
- Copying worked for both recommendation outcomes before and after clinician acceptance or override. Keyboard activation, visible focus, notification live-region markup, and manual text selection passed without accidental form submission or browser errors.
- Layout checks passed at 1280, 640, 375, and 320 pixels. Desktop and mobile screenshots were visually inspected.
- TypeScript checking passed. All 15 existing backend tests passed.
- Independent standards and spec reviews reported no findings.
- The production build passed with `npm run build -- --webpack`. The default Turbopack build failed while its CSS worker attempted to bind a local port, including on a retry outside the sandbox.
- ESLint could not run: the installed React plugin crashes with `contextOrFilename.getFilename is not a function`. The same crash occurs on the unchanged `components/header.tsx` file.
