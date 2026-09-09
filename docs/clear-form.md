# Clear form

Status: Implemented.

## Behavior

Add a button labeled **Clear form** beside **Load Sample Case** in the New Authorization Request header.

Activating the button clears:

- Patient name, date of birth, provider NPI, insurance ID, and clinical notes.
- All diagnosis codes, leaving exactly one blank diagnosis row.
- All procedure codes, leaving exactly one blank procedure row.
- The form error alert and any failed-review progress card.
- The completed review result displayed below the form, including its decision controls.

This is a local UI reset. It does not submit a request or change a previously recorded review or decision.

The button is disabled throughout a review, from submission until success or failure. It becomes available again after either outcome. It also works when the form is already empty.

## Acceptance checks

1. Load a sample case, add diagnosis and procedure rows, and clear the form. Every field is empty and each code section contains exactly one blank row.
2. Trigger a form validation error, then clear. The error disappears without submitting the form.
3. Fail a review, then clear. Both the form alert and failed progress card disappear.
4. Complete a review, then clear. The result and its decision controls disappear along with the request values.
5. Keep a review running. Clear form remains disabled until the review succeeds or fails.
6. Clear an already empty form, then load a sample or enter a new request. The form remains usable.

## Verification

- Browser checks passed against the local frontend with simulated API validation errors, a failed stream held open, and a successful review. Clearing a failed review also closes its lingering stream so later events cannot restore cleared errors.
- Desktop and narrow layouts passed at 1280, 640, 375, and 320 pixels. The sample and clear buttons remain adjacent at 375 pixels.
- TypeScript checking passed. All 15 existing backend tests passed.
- Standards and spec reviews reported no findings.
- ESLint could not run: the installed React plugin crashes with `contextOrFilename.getFilename is not a function`. The same crash occurs on the unchanged `components/header.tsx` file.
