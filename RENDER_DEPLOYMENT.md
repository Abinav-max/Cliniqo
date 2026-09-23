# Deploying MediKiosk (Cliniqo) to Render.com

This guide provides step-by-step instructions to deploy the complete **Cliniqo MediKiosk** hospital intake and longitudinal patient record system to [Render](https://render.com).

All features—including the **newly optimized 2-page ABDM FHIR R4 Clinical Consultation Dossier (jsPDF Vector Engine)**, longitudinal health profiles, returning patient fast-track, discrete visits, multi-stage OCR, medication confirmation, AYUSH intake, doctor workstation, and zero mock data—are fully and optimistically supported on Render.

---

## Deployment Architecture on Render

```
GitHub Repository (main branch)
            │
            ▼
     Render Web Service
 ┌──────────────────────────────────────────────────┐
 │   Docker Container (python:3.11-slim)            │
 │   ├── Tesseract OCR (English + Hindi)            │
 │   ├── FastAPI + Uvicorn ($PORT:10000)            │
 │   │   └── Reverse-Proxy Headers & SSL Forwarding │
 │   ├── 2-Page Vector PDF Dossier Engine (jsPDF)   │
 │   ├── SQLite Durable Health Vault (Local/Disk)   │
 │   └── Persistent Document Store (/app/data)      │
 └──────────────────────────────────────────────────┘
            │
            ├──► Groq API (Clinical LLM Engine - openai/gpt-oss-120b)
            ├──► Google Gemini API (Multimodal Vision OCR - gemini-2.5-flash)
            └──► Supabase (Optional Cloud Database Sync)
```

---

## Method 1: Automated Blueprint Deploy (Recommended & Fastest)

Render Blueprints use the included [`render.yaml`](file:///d:/ai_medical_assistant_UPDATED/render.yaml) to configure the entire deployment automatically.

1. **Commit & Push to GitHub**:
   Ensure all changes are pushed to your GitHub repository:
   ```bash
   git add .
   git commit -m "Update Render deployment configuration"
   git push origin main
   ```

2. **Open Render Dashboard**:
   - Log into [dashboard.render.com](https://dashboard.render.com).
   - Click **"New +"** at the top right and select **"Blueprint"**.

3. **Connect Your Repository**:
   - Select your `Cliniqo` repository (`Abinav-max/Cliniqo`).
   - Render detects `render.yaml` and provisions the `cliniqo-medikiosk` web service.

4. **Fill Environment Variables**:
   - `GROQ_API_KEY`: Your Groq API key (for medical interview and diagnostic synthesis).
   - `GEMINI_API_KEY`: (Optional) Your Google Gemini API key (for multimodal vision OCR on handwritten prescriptions).
   - `SUPABASE_URL`: (Optional) Leave empty to use local durable SQLite.
   - `SUPABASE_SERVICE_ROLE_KEY`: (Optional) Leave empty to use local durable SQLite.

5. **Click "Apply"**:
   Render builds the Docker container, installs Tesseract OCR & language libraries, binds Uvicorn to `$PORT`, and gives you a live HTTPS URL (e.g. `https://cliniqo-medikiosk.onrender.com`).

---

## Method 2: Manual Web Service Deploy (Docker)

If setting up manually in the Render dashboard:

1. Click **"New +"** $\to$ **"Web Service"**.
2. Select your `Cliniqo` repository.
3. Configure the service:
   - **Name**: `cliniqo-medikiosk`
   - **Region**: Choose closest region (e.g., `Oregon (US West)` or `Singapore`).
   - **Branch**: `main`
   - **Runtime**: **`Docker`** *(Pre-installs Tesseract OCR, Poppler & image libraries)*
   - **Plan**: `Free` (or `Starter` for persistent disk)
4. Set the **Health Check Path**:
   - Health Check Path: `/health`
5. Under **Environment Variables**, add:
   | Key | Value | Notes |
   |---|---|---|
   | `PORT` | `10000` | Render dynamically binds `$PORT` |
   | `ENVIRONMENT` | `production` | Production mode |
   | `DATA_DIR` | `/app/data` | Database and document storage |
   | `GROQ_API_KEY` | `gsk_...` | Required for clinical interview & diagnosis |
   | `GROQ_MODEL` | `openai/gpt-oss-120b` | High-accuracy clinical model |
   | `GEMINI_API_KEY` | `AIza...` | Optional for multimodal vision OCR |
   | `GEMINI_MODEL` | `gemini-2.5-flash` | Multimodal OCR engine |
   | `SUPABASE_REQUIRED` | `false` | Resilient local SQLite vault fallback |
   | `LLM_PRIMARY_PROVIDER` | `groq` | Primary LLM engine |
   | `LLM_FALLBACK_ENABLED` | `true` | Resilient fallback handler |
6. Click **"Create Web Service"**.

---

## Method 3: Native Python Runtime (Alternative)

If you select **Python 3** instead of Docker:

- **Build Command**: `./build.sh` (or `pip install -r requirements.txt`)
- **Start Command**: `./start.sh` (or `uvicorn api.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`)
- **OCR Note**: If Tesseract system binaries are unavailable on Render's native Python environment, Cliniqo automatically falls back to **Gemini Multimodal Vision OCR** or text PDF extraction. Supply `GEMINI_API_KEY` in environment variables.

---

## Optional: Render Persistent Disk (For Starter Plan and above)

On Render's Free tier, the filesystem is ephemeral (resets upon redeployment). With a Render **Starter plan ($7/mo)**:

1. In your Web Service settings $\to$ **Disks**.
2. Click **"Add Disk"**:
   - **Name**: `cliniqo-data`
   - **Mount Path**: `/app/data`
   - **Size**: `1 GB` (or more)
3. Save changes.
Your patient database (`cliniqo_vault.db`) and uploaded medical records (`/app/data/documents/`) will permanently persist across container redeployments!

---

## Verification Checklist on Render

Once your service finishes building and goes live:

1. **Health Check**:
   `https://<your-service>.onrender.com/health` $\to$ Returns `{"status": "ok", "service": "cliniqo-api", "version": "2.5.0", "persistence": "sqlite"}`.
2. **Main Application**:
   `https://<your-service>.onrender.com/` $\to$ Loads Cliniqo MediKiosk UI.
3. **Patient Registration & Lookup**:
   Register a new patient or look up returning patients by Mobile or ABHA.
4. **Prescription Upload & OCR**:
   Upload an image/PDF document; verify OCR extracts medications and biomarkers.
5. **2-Page Clinical Consultation Dossier (PDF)**:
   Click **"Download PDF Dossier"**; verify the generated 2-page hospital-grade PDF renders instantly with crisp vector primitives, complete clinical assessment synthesis, baseline vitals, and clean non-overlapping badges.
6. **Hospital Staff Workstation**:
   Log in with staff credentials (`doctor@hospital.gov.in` / `Doctor@123`) to review the triaged queue, longitudinal timeline, and sign off visits.
