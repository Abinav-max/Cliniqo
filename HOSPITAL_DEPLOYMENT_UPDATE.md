# MediKiosk Hospital Update

This version keeps the existing Cliniqo visual design and extends the application for the hospital workflow discussed for the Patient Case-Taking problem statement.

## Major changes

1. **General OPD / AYUSH OPD mode**
   - Same UI and application shell.
   - AYUSH mode captures Dashavidha Pariksha fields and Ahara-Vihara.
   - AYUSH information is explicitly patient-reported and marked pending clinician verification.

2. **Document temporal gate**
   - Every uploaded medical document is explicitly classified as `current` or `historical` by the patient.
   - Historical documents can have an exact, approximate, or unknown medical date.
   - Unknown dates remain unknown; upload time is never silently treated as the medical-event date.

3. **No silent promotion of document facts**
   - OCR-derived medicines/diagnoses remain document-scoped.
   - They are not automatically copied into today's current medications or current medical history.
   - This prevents an old prescription from being mistaken for today's treatment.

4. **Longitudinal patient timeline**
   - Added `clinical_events` persistence.
   - Added patient-level document and timeline APIs across visits/sessions.
   - Each event retains source, temporal status, date type, confidence and verification status.

5. **Doctor review context**
   - Document records expose current/historical status, date source, date type and verification status.
   - Document confirmation marks the record verified without changing its temporal meaning.

6. **Summary safety improvements**
   - Document-derived medication statements are labelled as document findings and explicitly do not imply current use.
   - Document dates and temporal status are preserved in summary evidence.
   - AYUSH assessment can be carried into the summary workflow.

## Database changes

SQLite migrations are automatic when the application starts. New tables/fields include:

- `documents.document_classification`
- `documents.classification_source`
- `documents.document_date`
- `documents.document_date_type`
- `documents.document_date_source`
- `documents.temporal_status`
- `documents.verification_status`
- `clinical_events`

A Supabase migration is also included:

`supabase/20260922_hospital_intake_migration.sql`

## Environment

The existing `.env` keys were retained. No new environment variable is required for these updates.

## Run

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload
```

Open the same Cliniqo frontend served by the FastAPI application.

## Important production note

ABDM/HIS/FHIR connectivity still requires the hospital's real integration endpoints, credentials, consent configuration and approved deployment infrastructure. The update prepares the application data model and workflow for those integrations; it does not fabricate live hospital connectivity.
