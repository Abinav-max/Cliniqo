# Cliniqo Supabase setup

## Run the migration

1. Create or open the Supabase project.
2. Open **SQL Editor** in the Supabase dashboard.
3. Create a new query and paste the complete contents of:
   `migrations/001_initial_medikiosk_schema.sql`.
4. Run the query once and confirm that it completes without errors.
5. Run the existing legacy migrations afterward if this project needs the
   legacy snapshot API:
   - `migrations/202609160001_create_clinical_sessions.sql`
   - `migrations/202609160002_create_medikiosk_schema.sql`

The existing migration files are retained unchanged for backward compatibility.
The new migration creates the normalized UUID-based schema. The legacy
`clinical_sessions.session_id` remains `text` and is intentionally not linked
to `sessions.session_id`.

## Tables created by `001_initial_medikiosk_schema.sql`

- `patients`
- `sessions`
- `conversation_messages`
- `medical_history`
- `medications`
- `allergies`
- `family_history`
- `lifestyle`
- `documents`
- `ocr_results`
- `clinical_observations`
- `red_flags`
- `summaries`
- `doctor_cases`
- `consents`
- `audit_logs`

The migration also creates the private `medical-documents` Storage bucket.

## Relationships

```text
patients
  |
  +--< sessions
          |
          +--< conversation_messages
          +---- medical_history
          +--< medications
          +--< allergies
          +---- family_history
          +---- lifestyle
          +--< documents --< ocr_results
          +--< clinical_observations
          +--< red_flags
          +---- summaries
          +---- doctor_cases
          +--< consents
          +--< audit_logs
```

All child records use `session_id`. Patient deletion cascades to sessions and
session-owned records. Document deletion cascades to OCR results. Audit logs
retain their row when a session is deleted by setting `session_id` to `NULL`.

## Sensitive information

The following fields contain, or may contain, sensitive patient information:

- `patients.abha_id`, `display_name`, `date_of_birth`, and `phone`
- `conversation_messages.content`
- `medical_history.data`
- Medication and allergy values
- `documents.file_name` and all private Storage objects
- `ocr_results.raw_output`, `raw_text`, and `normalized_output`
- `clinical_observations.observation`
- `red_flags.reason`
- `summaries.content`
- `doctor_cases.content`
- Consent and audit metadata when it identifies a session or resource

Do not put API keys, passwords, or unnecessary identifiers in `metadata` or
clinical JSONB fields.

## RLS and credentials

RLS is enabled on every clinical table. This migration intentionally creates no
`anon` or `authenticated` policies. The FastAPI backend uses the Supabase
service-role key server-side; service-role access bypasses RLS. Browser code
must call FastAPI and must never call Supabase directly with the service-role
key.

Add these values only to the backend `.env` file:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-server-only-service-role-key
SUPABASE_REQUIRED=true
```

Never place `SUPABASE_SERVICE_ROLE_KEY` in `index.html`, frontend JavaScript,
mobile code, public environment variables, or source control. Keep `.env`
uncommitted.

## Supabase Storage

The migration creates a private bucket named `medical-documents`. Store only
document binaries there; PostgreSQL stores metadata in `documents` and OCR
content in `ocr_results`. Files use backend-controlled paths such as:

```text
{session_id}/{document_id}/{file_name}
```

The backend uploads and downloads files through the service-role client. Do not
create public URLs for medical documents. Production deployments should also
add authentication, role-based access control, retention enforcement, and key
management before exposing patient data outside a trusted backend.

## Local development

Without Supabase credentials, set:

```env
SUPABASE_REQUIRED=false
```

The API then uses its local in-memory adapter. After the migrations and `.env`
configuration are complete, run the synthetic seed from the project root:

```powershell
python scripts/seed_demo_data.py
```

The seed data is synthetic and is not medical advice or real patient data.
