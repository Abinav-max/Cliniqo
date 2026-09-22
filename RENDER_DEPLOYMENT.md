# Deploying MediKiosk (Cliniqo) to Render.com

This guide provides step-by-step instructions to deploy the complete **MediKiosk** hospital intake and longitudinal patient record system to [Render](https://render.com).

All **21 requirements** (longitudinal health profiles, returning patient fast-track, discrete visits, multi-stage OCR, medication confirmation, AYUSH intake, doctor workstation, zero mock data) are fully supported on Render.

---

## Deployment Architecture on Render

```
GitHub Repository (main branch)
            │
            ▼
     Render Web Service
 ┌────────────────────────────────────────┐
 │   Docker Container (python:3.11-slim)   │
 │   ├── Tesseract OCR (Eng + Hin)        │
 │   ├── FastAPI + Uvicorn ($PORT:10000)  │
 │   ├── SQLite Durable Health Vault      │
 │   └── Persistent Document Store        │
 └────────────────────────────────────────┘
            │
            ├──► Groq API (Clinical LLM Engine)
            ├──► Google Gemini API (Multimodal Vision OCR)
            └──► Supabase (Optional Cloud Sync)
```

---

## Method 1: Automated Blueprint Deploy (Recommended)

Render Blueprints use the included [`render.yaml`](file:///d:/ai_medical_assistant_UPDATED/render.yaml) to configure the entire deployment automatically.

1. **Push your code to GitHub**:
   Ensure all changes are pushed to your GitHub repository:
   ```powershell
   .\push_to_github.ps1
   ```

2. **Open Render Dashboard**:
   - Log into [dashboard.render.com](https://dashboard.render.com).
   - Click the **"New +"** button at the top right and select **"Blueprint"**.

3. **Connect Your Repository**:
   - Select your `Cliniqo` repository.
   - Render will detect `render.yaml` and display the `cliniqo-medikiosk` web service.

4. **Set Environment Variables**:
   In the Blueprint setup screen, fill in your environment variables:
   - `GROQ_API_KEY`: Your Groq API key (for medical interview and summaries).
   - `GEMINI_API_KEY`: (Optional) Your Google Gemini API key (for multimodal handwritten OCR).
   - `SUPABASE_URL`: (Optional) Leave blank if using local SQLite storage.
   - `SUPABASE_SERVICE_ROLE_KEY`: (Optional) Leave blank if using local SQLite storage.

5. **Click "Apply"**:
   Render will build the Docker container, install Tesseract OCR, start the FastAPI server, and provide your live URL (e.g., `https://cliniqo-medikiosk.onrender.com`).

---

## Method 2: Manual Web Service Deploy (Docker)

If you prefer setting up the web service manually:

1. Click **"New +"** $\to$ **"Web Service"**.
2. Select your `Cliniqo` GitHub repository.
3. Configure the service settings:
   - **Name**: `cliniqo-medikiosk`
   - **Region**: Choose the region closest to you (e.g., `Oregon (US West)` or `Frankfurt (EU)` or `Singapore`).
   - **Branch**: `main`
   - **Runtime**: **`Docker`** *(Recommended: Docker includes pre-installed Tesseract OCR & language libraries)*
   - **Plan**: `Free` (or `Starter` for persistent disk)
4. Set the **Health Check Path**:
   - Health Check Path: `/health`
5. Under **Environment Variables**, add:
   | Key | Value | Notes |
   |---|---|---|
   | `PORT` | `10000` | Render assigns dynamically |
   | `ENVIRONMENT` | `production` | Production mode |
   | `DATA_DIR` | `/app/data` | Path for database and documents |
   | `GROQ_API_KEY` | `gsk_...` | Required for clinical interview |
   | `GEMINI_API_KEY` | `AIza...` | Optional for vision OCR |
   | `SUPABASE_REQUIRED` | `false` | Fallback to durable SQLite |
6. Click **"Create Web Service"**.

---

## Method 3: Native Python Runtime (Alternative)

If you select **Python 3** instead of Docker in the Render dashboard:

- **Build Command**: `./build.sh` (or `pip install -r requirements.txt`)
- **Start Command**: `./start.sh` (or `uvicorn api.main:app --host 0.0.0.0 --port $PORT`)
- **Note on OCR in Python Runtime**: If Tesseract system binaries are not available in Render's native Python environment, Cliniqo automatically falls back to **Gemini Multimodal Vision OCR** or text PDF extraction. Set `GEMINI_API_KEY` in environment variables for vision OCR.

---

## Optional: Render Persistent Disk (For Starter Plan and above)

On Render's Free tier, the filesystem is ephemeral (resets on container redeployment). If you upgrade to a Render **Starter plan ($7/mo)**:

1. Go to your Web Service settings $\to$ **Disks**.
2. Click **"Add Disk"**:
   - **Name**: `cliniqo-data`
   - **Mount Path**: `/app/data`
   - **Size**: `1 GB` (or more)
3. Save changes.
Your patient database (`cliniqo_vault.db`) and uploaded medical documents (`/app/data/documents/`) will permanently persist across every code update and redeployment!

---

## Verification Checklist on Render

Once your service is deployed, verify your live URL:

1. **Health Check**:
   Visit `https://<your-render-subdomain>.onrender.com/health` $\to$ Returns `{"status": "ok", "service": "cliniqo-api", "version": "2.5.0"}`.
2. **Main Application**:
   Visit `https://<your-render-subdomain>.onrender.com/` $\to$ Loads Cliniqo MediKiosk.
3. **Patient Registration & Lookup**:
   Register a new patient or test returning patient lookup by Mobile/ABHA.
4. **Document Upload & OCR**:
   Upload a prescription or lab report; verify OCR extraction and classification (*Current* vs *Old*).
5. **Hospital Staff Workstation**:
   Log in with staff credentials (`doctor@hospital.gov.in` / `Doctor@123`) to review the live triaged queue, KPI metrics, and sign off cases.
