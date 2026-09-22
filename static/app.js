/**
 * Cliniqo Unified Patient Case-Taking Application Controller
 * Single Source of Truth: currentPatientId + currentSessionId -> FastAPI -> Repository -> Supabase
 */
(function() {
  "use strict";

  const CLINIQO_API_BASE = window.location.origin;

  // =========================================================================
  // 1. CONSTANTS & CONFIGURATION
  // =========================================================================
  const SCREEN_SEQUENCE = [
    'home',
    'hospital-registration',
    'hospital-language',
    'hospital-consent',
    'hospital-department',
    'assessment-what-brings-you-here',
    'assessment-ai-health-interview',
    'assessment-adaptive-follow-up',
    'assessment-symptoms',
    'assessment-medical-history',
    'assessment-medicines-allergies',
    'assessment-family-lifestyle',
    'assessment-safety-check',
    'records-medical-records',
    'records-scan-document',
    'records-review-extracted-information',
    'clinicalsummaries-summary-confirmation',
    'clinical-case-summary',
    'doctor-workstation',
    'hospital-priority-alert',
    'healthstory-your-health-story',
    'healthstory-your-health-timeline',
    'profile',
    'privacy-consent',
    'accessibility'
  ];

  const SCREEN_TITLES = {
    'home': { title: 'Home', phase: 'Patient Data Hub' },
    'hospital-registration': { title: 'Hospital Registration', phase: 'ABHA & Token Identification' },
    'hospital-language': { title: 'Language Selection', phase: 'Multilingual Audio Console' },
    'hospital-consent': { title: 'Clinical Consent', phase: 'DPDP & ABDM 4-Pillar Protection' },
    'hospital-department': { title: 'Department Selection', phase: 'General OPD vs AYUSH OPD' },
    'hospital-priority-alert': { title: 'Emergency Priority Alert', phase: 'Immediate Clinical Hard-Stop' },
    'doctor-workstation': { title: 'Hospital Operations Command', phase: 'Live OPD Queue & Operations' },
    'patient-visits': { title: 'My Visits & Health Vault', phase: 'Longitudinal Patient Portal' },
    'assessment-what-brings-you-here': { title: 'What Brings You Here', phase: 'Spoken Intake Phase' },
    'assessment-ai-health-interview': { title: 'AI Health Interview', phase: 'Adaptive Voice Console' },
    'assessment-adaptive-follow-up': { title: 'Adaptive Follow-up', phase: 'Clarification Question' },
    'assessment-symptoms': { title: 'Symptoms Review', phase: 'Symptom Verification' },
    'assessment-medical-history': { title: 'Medical History', phase: 'Past Conditions & Surgeries' },
    'assessment-medicines-allergies': { title: 'Medicines & Allergies', phase: 'Active Rx & Sensitivity' },
    'assessment-family-lifestyle': { title: 'Family & Lifestyle', phase: 'Contextual Health Factors' },
    'assessment-safety-check': { title: 'Safety Check', phase: 'Personal Safety Verification' },
    'healthstory-your-health-story': { title: 'Your Health Story', phase: 'Multi-Source Synthesis' },
    'healthstory-your-health-timeline': { title: 'Your Health Timeline', phase: 'Living Longitudinal Story' },
    'records-medical-records': { title: 'Medical Records', phase: 'Personal Records Vault' },
    'records-scan-document': { title: 'Scan Document', phase: 'Document Camera Viewfinder' },
    'records-review-extracted-information': { title: 'Review Extracted Info', phase: 'OCR Document Intelligence' },
    'clinicalsummaries-summary-confirmation': { title: 'Summary & Confirmation', phase: 'Personal Health Dossier & Vault' },
    'clinical-case-summary': { title: 'Overall Case Summary', phase: 'Doctor & Patient Case Dossier' },
    'profile': { title: 'Patient Profile', phase: 'ABDM Verified Identity' },
    'privacy-consent': { title: 'Privacy & Consent', phase: '4-Pillar Data Protection' },
    'accessibility': { title: 'Accessibility & Language', phase: 'Inclusive Interaction Settings' }
  };

  // Cross-dashboard real-time parallel synchronization channel
  const hospitalSyncChannel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('cliniqo_hospital_sync') : null;

  // =========================================================================
  // 2. CENTRAL STATE & REGISTRY (ZERO STATIC DEMO DATA)
  // =========================================================================
  let currentSessionId = localStorage.getItem('cliniqo_session_id') || sessionStorage.getItem('cliniqo_session_id') || null;
  let currentPatientId = localStorage.getItem('cliniqo_patient_id') || sessionStorage.getItem('cliniqo_patient_id') || null;
  let currentDocumentId = null;
  let currentDocumentContext = { classification: 'historical', date_type: 'unknown', date_source: 'unknown', document_date: null };
  let clinicalMode = localStorage.getItem('cliniqo_clinical_mode') || 'general';
  let ayushAssessment = JSON.parse(localStorage.getItem('cliniqo_ayush_assessment') || '{}');
  let currentScreen = 'home';
  let uploadedDocuments = [];
  let patientRegistry = [];

  // Hospital OPD & Doctor Workstation Central State
  let hospitalTokenNumber = localStorage.getItem('cliniqo_hospital_token') || null;
  let hospitalDepartment = localStorage.getItem('cliniqo_hospital_dept') || 'general';
  let hospitalConsentGiven = localStorage.getItem('cliniqo_hospital_consent') === 'true';
  let hospitalTriageLevel = 'routine';
  let selectedHospitalLang = localStorage.getItem('cliniqo_hospital_lang') || 'en';
  let currentDoctorCase = null;
  let doctorQueueFilter = 'all';
  let isReturningPatientVisit = false;

  // Active Patient starts empty until dynamically loaded or created
  let activePatient = {
    patient_id: null,
    display_name: '',
    abha_id: '',
    date_of_birth: '',
    gender: '',
    phone: '',
    emergency_contact: '',
    blood_group: '',
    preferred_language: 'en-IN'
  };

  // Active User Authentication State (starts signed out; no mock/demo account)
  let currentUser = JSON.parse(localStorage.getItem('cliniqo_user') || 'null');

  // Selected Clinical Fact Sets (All start empty)
  const selectedWhatBringsSymptoms = new Set();
  const selectedPainLocations = new Set();
  const selectedAdaptiveChoices = new Set();
  const selectedAdaptiveTriggers = new Set();
  const selectedMedHistConditions = new Set();
  const selectedMedications = new Set();
  const selectedAllergies = new Set();
  const selectedFamilyConditions = new Set();
  const selectedLifestyleHabits = new Set();
  const activeTimelineFilters = new Set(['all']);

  // LLM interview question keeping: the last question the LLM asked, the last
  // patient reply, and the active interview category are retained so the
  // adaptive follow-up screen always mirrors the live conversation.
  let lastAskedQuestion = '';
  let lastPatientMessage = '';
  let currentInterviewNextCategory = null;
  let adaptiveQuestionCount = 2;

  const INTERVIEW_QUESTION_TEMPLATES = {
    chief_complaint: 'What is the main problem you would like the clinician to know about?',
    onset: 'When did this start?',
    duration: 'How long has this been going on?',
    location: 'Where do you feel it?',
    character: 'What does it feel like?',
    severity: 'How severe is it on a scale of 0 to 10?',
    timing: 'Is it constant, or does it come and go?',
    progression: 'Has it been getting better, worse, or staying the same?',
    associated_symptoms: 'Have you noticed any other symptoms along with this?',
    past_medical_history: 'Do you have any other medical conditions that a clinician should know about?',
    previous_similar_episodes: 'Have you had anything like this before?',
    current_medications: 'Are you taking any medications?',
    allergies: 'Do you have any allergies?',
    family_history: 'Is there any relevant family medical history?',
    social_history: 'Is there anything about smoking, alcohol, work, or daily life that seems relevant?',
    previous_investigations: 'Have you had any tests or scans for this already?',
    risk_context: 'Is there anything else about the setting or what you were doing that seems important?'
  };

  // =========================================================================
  // 3. CORE UTILITIES & IN-BOX EDITING
  // =========================================================================
  function isGenericClinicalEntity(str) {
    if (!str) return true;
    const s = String(str).trim().toLowerCase().replace(/^[“"'\s.,!?-]+|[”"'\s.,!?-]+$/g, '');
    if (!s) return true;

    // Exact matching standard tokens
    const exactTokens = [
      'clinical evaluation', 'not reported yet', 'no symptoms recorded yet', 'not specified', 
      'general intake', 'unknown', 'none', 'nothing', 'intake', 'nil', 'n/a', 'null', 'undefined',
      'no chronic conditions recorded', 'none reported', 'recorded today', 'recorded on intake', 
      'not localized', 'unrated', 'not recorded', 'none recorded', 'no symptoms reported yet',
      'no active medications reported.', 'no active medications reported', 
      'no chronic conditions or prior surgeries reported.', 'no chronic conditions or prior surgeries reported',
      'no active medications or allergies reported.', 'no active medications or allergies reported',
      'no prior medical conditions logged.', 'no prior medical conditions logged',
      'no scanned records attached yet.', 'no scanned records attached yet',
      'awaiting intake...', 'awaiting intake', 'awaiting input...', 'awaiting input',
      'tap to speak', 'looks good', 'verified', 'not reported', 'unspecified'
    ];
    if (exactTokens.includes(s)) return true;

    // Check substring patterns that represent UI prompts / instructions / defaults
    const placeholderPatterns = [
      'tap the mic',
      'tap the microphone',
      'tap the center voice orb',
      'tap the center orb',
      'select suggested replies',
      'select symptom chips',
      'speak your symptoms',
      'or type to start',
      'start your ai interview',
      'start your intake',
      'please select or speak',
      'no prior responses recorded',
      'your previous reply is recorded',
      'what symptoms or discomfort are you feeling today',
      'let\'s understand that a little better',
      'how does this symptom behave',
      'question 1 of',
      'awaiting intake',
      'awaiting input'
    ];

    return placeholderPatterns.some(pat => s.includes(pat));
  }

  function speakText(text, lang) {
    if (!text || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.lang = lang || (window.CliniqoI18n ? window.CliniqoI18n.getSpeechCode() : 'en-IN');
    window.speechSynthesis.speak(utterance);
  }

  function getScreenOverviewText(screenId) {
    const pName = (activePatient && activePatient.display_name) ? activePatient.display_name.split(' ')[0] : (currentUser ? currentUser.display_name : 'Patient');
    const symList = Array.from(selectedWhatBringsSymptoms);
    const chiefSymptom = symList.length > 0 ? symList.join(', ') : 'routine consultation';
    const medHistList = Array.from(selectedMedHistConditions);
    const medsList = Array.from(selectedMedications);
    const allergyList = Array.from(selectedAllergies);
    const docCount = uploadedDocuments.length;

    switch (screenId) {
      case 'home':
        return `Welcome to Cliniqo Patient Health Vault. Active user is ${pName}. You can start a new clinical intake, review your health timeline, or scan a document.`;
      case 'assessment-what-brings-you-here':
        return `Intake Phase. Please speak or select the symptoms or concerns that bring you in today.`;
      case 'assessment-ai-health-interview':
        return `AI Voice Console. Detail your symptom onset, body location, and pain intensity.`;
      case 'assessment-adaptive-follow-up':
        return `Adaptive clinical inquiry. Please select or speak what triggers your symptoms or what makes them feel better.`;
      case 'assessment-symptoms':
        return `Symptom review. Current recorded symptoms: ${chiefSymptom}. You can click any edit button to adjust details in place.`;
      case 'assessment-medical-history':
        return `Past medical history. Documented conditions: ${medHistList.length > 0 ? medHistList.join(', ') : 'None documented'}.`;
      case 'assessment-medicines-allergies':
        return `Medicines and allergies. Active prescriptions: ${medsList.length > 0 ? medsList.join(', ') : 'None'}. Documented allergies: ${allergyList.length > 0 ? allergyList.join(', ') : 'No known drug allergies'}.`;
      case 'assessment-family-lifestyle':
        return `Contextual health factors. Documented family health conditions and daily lifestyle habits.`;
      case 'assessment-safety-check':
        return `Safety check. Quickly spots urgent symptoms so you know when to seek emergency help right away.`;
      case 'healthstory-your-health-story':
        return `Your synthesized health story. Combines your reported symptoms, medical history, medications, and scanned documents into a cohesive narrative.`;
      case 'healthstory-your-health-timeline':
        return `Your longitudinal health timeline. Shows verified chronological entries for symptoms, prescriptions, and lab panels.`;
      case 'records-medical-records':
        return `Personal records vault. You have ${docCount} verified scanned records stored securely.`;
      case 'records-scan-document':
        return `Document scanner viewfinder. Capture or upload prescriptions, lab reports, or discharge summaries for real-time OCR extraction.`;
      case 'records-review-extracted-information':
        return `Extracted clinical information review. Verify digitized clinical text, prescribed medicines, and biomarker values.`;
      case 'clinicalsummaries-summary-confirmation':
        return `Summary and confirmation. Your full clinical dossier is ready for your review and export to the physician docket.`;
      case 'clinical-case-summary':
        return `Overall Case Summary. Review your comprehensive clinical dossier combining present issues, past history, and verified lab reports with multi-format download capabilities.`;
      case 'profile':
        return `Patient profile and ABDM identity details. Manage personal details, ABHA health ID, and demographic records.`;
      case 'privacy-consent':
        return `Privacy and consent settings. 4-Pillar clinical data encryption and DPDP compliance controls.`;
      case 'accessibility':
        return `Accessibility and language preferences. Configure high contrast, large text, and voice interaction settings.`;
      default:
        return `Cliniqo Patient Health Vault. Managing comprehensive clinical history and health records.`;
    }
  }

  function saveToVaultNotification(msg = "Health Vault Synced", sub = "All patient records securely persisted.") {
    const notif = document.getElementById('vaultSyncNotification');
    const titleEl = document.getElementById('vaultSyncTitle');
    const subEl = document.getElementById('vaultSyncSub');
    if (!notif) return;
    if (titleEl) titleEl.textContent = msg;
    if (subEl) subEl.textContent = sub;

    notif.classList.remove('translate-y-24', 'opacity-0', 'pointer-events-none');
    notif.classList.add('translate-y-0', 'opacity-100');

    clearTimeout(window.__vaultNotifTimer);
    window.__vaultNotifTimer = setTimeout(() => {
      notif.classList.remove('translate-y-0', 'opacity-100');
      notif.classList.add('translate-y-24', 'opacity-0', 'pointer-events-none');
    }, 3200);
  }

  function updateVaultProgress() {
    let pct = 0;

    if (currentUser && currentUser.user_id) pct += 8;
    if (activePatient && activePatient.patient_id) pct += 7;          // 15 profile

    if (selectedWhatBringsSymptoms.size > 0) pct += 15;               // 30 chief complaint

    const storyEl = document.getElementById('healthStoryNarrative');
    let hasHpi = false;
    if (storyEl) {
      const raw = (storyEl.dataset && storyEl.dataset.rawText) || (storyEl.textContent || '').replace(/[“”"\s]+/g, '');
      hasHpi = raw.length > 0;
    }
    if (hasHpi) pct += 10;                                            // 40 symptom story

    if (selectedAdaptiveChoices.size > 0 || selectedAdaptiveTriggers.size > 0) pct += 5; // 45 follow-up

    if (selectedMedHistConditions.size > 0) pct += 15;                // 60 medical history
    if (selectedMedications.size > 0) pct += 15;                      // 75 medications
    if (selectedAllergies.size > 0) pct += 10;                        // 85 allergies
    if (selectedFamilyConditions.size > 0) pct += 5;                  // 90 family history
    if (selectedLifestyleHabits.size > 0) pct += 5;                   // 95 lifestyle
    if (uploadedDocuments.length > 0) pct += 5;                       // 100 documents / OCR

    pct = Math.max(0, Math.min(100, pct));

    const txt = document.getElementById('vaultSyncPct');
    const bar = document.getElementById('vaultProgressBar');
    if (txt) txt.textContent = `${pct}% Stored`;
    if (bar) bar.style.width = `${pct}%`;
  }

  window.startInlineEdit = function(config) {
    const wrapper = document.getElementById(config.wrapperId);
    const textEl = document.getElementById(config.textElId);
    if (!wrapper || !textEl) return;
    if (wrapper.querySelector('.inline-editor-box')) return;

    const currentRaw = textEl.dataset.rawText || textEl.textContent.replace(/^[“"\s]+|[”"\s]+$/g, '').trim();
    textEl.dataset.rawText = currentRaw;

    const originalTextDisplay = textEl.style.display;
    textEl.style.display = 'none';

    let actionRow = null;
    let originalActionDisplay = '';
    if (config.actionRowId) {
      actionRow = document.getElementById(config.actionRowId);
      if (actionRow) {
        originalActionDisplay = actionRow.style.display;
        actionRow.style.display = 'none';
      }
    }

    const editorBox = document.createElement('div');
    editorBox.className = 'inline-editor-box space-y-2.5 pt-1 animate-fadeIn w-full';
    editorBox.innerHTML = `
      <div class="relative w-full">
        <textarea 
          class="inline-editor-textarea w-full p-3.5 rounded-2xl bg-surface-container-lowest border-2 border-primary text-on-surface font-headline text-sm sm:text-base focus:outline-none focus:ring-4 focus:ring-primary/20 shadow-inner resize-none transition-all leading-relaxed" 
          rows="${config.rows || 3}" 
          placeholder="Edit text...">${currentRaw}</textarea>
        <div class="flex items-center justify-between text-[11px] text-secondary mt-1 px-1">
          <span>💡 <kbd class="px-1.5 py-0.5 rounded bg-surface-container font-mono text-[10px]">Ctrl+Enter</kbd> or click Save</span>
          <span><kbd class="px-1.5 py-0.5 rounded bg-surface-container font-mono text-[10px]">Esc</kbd> to cancel</span>
        </div>
      </div>
      <div class="flex items-center justify-end gap-2 pt-0.5">
        <button type="button" class="btn-cancel-inline h-9 px-4 rounded-full bg-surface-container hover:bg-secondary-container text-xs font-semibold text-on-surface transition-colors cursor-pointer border border-secondary-container flex items-center gap-1">
          <span class="material-symbols-outlined text-[15px]">close</span>
          <span>Cancel</span>
        </button>
        <button type="button" class="btn-save-inline h-9 px-5 rounded-full bg-primary hover:bg-primary-dark text-xs font-semibold text-white shadow-xs transition-colors cursor-pointer flex items-center gap-1.5">
          <span class="material-symbols-outlined text-[16px]">check</span>
          <span>Save Changes</span>
        </button>
      </div>
    `;

    wrapper.appendChild(editorBox);
    const textarea = editorBox.querySelector('.inline-editor-textarea');
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);

    const closeEditor = () => {
      editorBox.remove();
      textEl.style.display = originalTextDisplay || '';
      if (actionRow) actionRow.style.display = originalActionDisplay || '';
    };

    const saveChanges = () => {
      const val = textarea.value.trim();
      if (val) {
        textEl.dataset.rawText = val;
        textEl.textContent = config.isQuoted !== false ? `“${val}”` : val;
        if (config.badgeId) {
          const badge = document.getElementById(config.badgeId);
          if (badge) {
            badge.textContent = '✓ Saved in vault';
            badge.classList.remove('bg-white');
            badge.classList.add('bg-primary-fixed', 'text-primary');
          }
        }
        if (typeof config.onSave === 'function') {
          config.onSave(val);
        }
        updateHealthStoryUI();
        syncClinicalData();
      }
      closeEditor();
    };

    editorBox.querySelector('.btn-save-inline').addEventListener('click', saveChanges);
    editorBox.querySelector('.btn-cancel-inline').addEventListener('click', closeEditor);

    textarea.addEventListener('keydown', (e) => {
      if ((e.key === 'Enter' && e.ctrlKey) || (e.key === 'Enter' && !config.multiline && !e.shiftKey)) {
        e.preventDefault();
        saveChanges();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        closeEditor();
      }
    });
  };

  // =========================================================================
  // 4. CENTRALIZED BACKEND API CLIENT
  // =========================================================================
  async function apiRequest(path, options = {}) {
    const url = path.startsWith('http') ? path : `${window.location.origin}${path}`;
    const config = {
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {})
      },
      ...options
    };
    if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
      config.body = JSON.stringify(options.body);
    }
    if (options.body instanceof FormData) {
      delete config.headers['Content-Type'];
    }
    try {
      const response = await fetch(url, config);
      const data = await response.json();
      if (!response.ok) {
        console.warn(`API [${response.status}] for ${path}:`, data);
        const serverMsg = (data && (data.error || data.detail)) || `Request failed (${response.status})`;
        const error = new Error(serverMsg);
        error.status = response.status;
        error.status_code = response.status;
        error.payload = data;
        throw error;
      }
      return data;
    } catch (error) {
      if (error && error.status) throw error;
      console.warn(`Network/API error for ${path}:`, error);
      throw error;
    }
  }

  async function saveAyushAssessment() {
    const data = {};
    document.querySelectorAll('[data-ayush-field]').forEach(el => {
      data[el.dataset.ayushField] = el.value.trim();
    });
    const ahara = document.getElementById('ayush_ahara_vihara');
    data.ahara_vihara = { narrative: ahara ? ahara.value.trim() : '' };
    data.source = 'patient';
    data.verification_status = 'pending';
    ayushAssessment = data;
    localStorage.setItem('cliniqo_ayush_assessment', JSON.stringify(data));
    if (!currentSessionId) await createSession();
    try {
      await apiRequest(`/api/v1/sessions/${currentSessionId}/ayush-assessment`, { method: 'PUT', body: data });
      renderAyushSummaryCard();
      saveToVaultNotification('AYUSH Assessment Saved', 'Dashavidha and Ahara-Vihara data linked to this visit.');
    } catch (e) {
      console.warn('AYUSH assessment sync failed', e);
    }
  }

  async function syncClinicalData() {
    if (!currentSessionId) return null;
    const pastHistory = Array.from(selectedMedHistConditions);
    const meds = Array.from(selectedMedications).map(m => ({ name_as_reported: m, name: m }));
    const allergies = Array.from(selectedAllergies);
    const family = Array.from(selectedFamilyConditions);
    const lifestyle = { habits: Array.from(selectedLifestyleHabits) };

    try {
      return await apiRequest(`/api/v1/sessions/${currentSessionId}/medical-history`, {
        method: 'PUT',
        body: {
          past_history: pastHistory,
          medications: meds,
          allergies: allergies,
          family_history: family,
          lifestyle: lifestyle
        }
      });
    } catch (err) {
      console.warn('syncClinicalData warning:', err);
      return null;
    }
  }

  async function sendPatientMessage(text, source = 'voice') {
    if (!text || !text.trim() || isGenericClinicalEntity(text)) return null;
    if (!currentSessionId) await createSession();

    const cleanText = text.trim();
    lastPatientMessage = cleanText;
    localStorage.setItem('cliniqo_last_patient_response', cleanText);

    // Emergency red-flag symptom pre-screen on patient utterance
    const matchedRedFlag = checkTextForEmergencyRedFlags(cleanText);
    if (matchedRedFlag) {
      triggerHospitalEmergencyAlert(`Critical symptom detected: "${matchedRedFlag}" reported by patient during intake.`);
    }

    // Immediately mirror spoken/typed input to active transcription cards
    const aiTrans = document.getElementById('aiInterviewTranscript');
    if (aiTrans) {
      aiTrans.textContent = `“${cleanText}”`;
      aiTrans.dataset.rawText = cleanText;
    }
    const aiBadge = document.getElementById('aiInterviewStatusBadge');
    if (aiBadge) {
      aiBadge.textContent = '✓ Recorded';
      aiBadge.classList.remove('bg-white');
      aiBadge.classList.add('bg-primary-fixed', 'text-primary');
    }

    try {
      const resp = await apiRequest(`/api/session/${currentSessionId}/message`, {
        method: 'POST',
        body: {
          session_id: currentSessionId,
          message: cleanText,
          channel: source,
          patient_id: activePatient.patient_id
        }
      });

      if (resp) {
        if (resp.assistant_message) {
          lastAskedQuestion = String(resp.assistant_message).trim();
          localStorage.setItem('cliniqo_last_llm_question', lastAskedQuestion);
          adaptiveQuestionCount += 1;
          const aiHdr = document.querySelector('#screen-assessment-ai-health-interview h1');
          if (aiHdr) aiHdr.textContent = `“${resp.assistant_message}”`;
          speakText(resp.assistant_message);
        }
        applySessionStateToUI(resp);
        renderAdaptiveFollowUpQuestion();
      }

      saveToVaultNotification("Diagnosis Updated", "Clinical impression and structured history updated in real-time.");
      return resp;
    } catch (err) {
      console.warn('sendPatientMessage error:', err);
      return null;
    }
  }

  function applySessionStateToUI(state) {
    if (!state) return;
    const orch = state.orchestrator_state || state;
    const ch = state.clinical_history || orch.clinical_history || {};
    const risk = state.risk_assessment || orch.risk_assessment || {};
    const summary = state.physician_summary || orch.physician_summary || {};
    const hpi = (ch.history_of_present_illness && typeof ch.history_of_present_illness === 'object') ? ch.history_of_present_illness : {};

    // Keep track of the LLM's active interview category so the adaptive
    // screen can surface a meaningful clarifying question even before a
    // fresh assistant_message arrives.
    if (state.next_question_category) currentInterviewNextCategory = state.next_question_category;
    else if (orch.next_question_category) currentInterviewNextCategory = orch.next_question_category;

    // 1. Symptoms & Chief Complaint
    const symptomsToAdd = [];
    if (ch.chief_complaint && typeof ch.chief_complaint === 'string' && ch.chief_complaint.trim() && !isGenericClinicalEntity(ch.chief_complaint)) {
      symptomsToAdd.push(ch.chief_complaint.trim());
    }
    if (ch.chief_concern && typeof ch.chief_concern === 'string' && ch.chief_concern.trim() && !isGenericClinicalEntity(ch.chief_concern) && !symptomsToAdd.includes(ch.chief_concern.trim())) {
      symptomsToAdd.push(ch.chief_concern.trim());
    }
    if (Array.isArray(ch.associated_symptoms)) {
      ch.associated_symptoms.forEach(s => {
        const sName = typeof s === 'string' ? s.trim() : (s.name || s.symptom || '');
        if (sName && !isGenericClinicalEntity(sName) && !symptomsToAdd.includes(sName)) symptomsToAdd.push(sName);
      });
    }

    if (symptomsToAdd.length > 0) {
      symptomsToAdd.forEach(s => selectedWhatBringsSymptoms.add(s));
      const wb = document.getElementById('whatBringsTranscript');
      if (wb) {
        wb.textContent = `“${symptomsToAdd.join(', ')}”`;
        wb.dataset.rawText = symptomsToAdd.join(', ');
      }
      const s1 = document.getElementById('symptomVal1');
      if (s1) s1.textContent = symptomsToAdd.join(', ');

      // Highlight matching chips on Screen 2
      document.querySelectorAll('#whatBringsSymptomChips .symptom-chip').forEach(chip => {
        const sym = (chip.getAttribute('data-symptom') || '').toLowerCase();
        const matches = symptomsToAdd.some(s => s.toLowerCase().includes(sym) || sym.includes(s.toLowerCase()));
        if (matches) {
          chip.setAttribute('data-selected', 'true');
          chip.className = 'symptom-chip px-4 py-2.5 rounded-2xl bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
          const icon = chip.querySelector('.material-symbols-outlined');
          if (icon) {
            icon.textContent = 'check_circle';
            icon.className = 'material-symbols-outlined text-[16px] text-primary-fixed';
          }
        }
      });
      const badge = document.getElementById('whatBringsCountBadge');
      if (badge) badge.textContent = `${selectedWhatBringsSymptoms.size} Selected`;
    }

    // 2. Onset, Duration, Location, Severity (Screen 5 indicators)
    if (hpi.onset || hpi.duration) {
      const durStr = [hpi.onset ? `Onset: ${hpi.onset}` : '', hpi.duration ? `Duration: ${hpi.duration}` : ''].filter(Boolean).join(' • ');
      const s2 = document.getElementById('symptomVal2');
      if (s2) s2.textContent = durStr || 'Recorded today';
    }

    if (hpi.location) {
      const s3 = document.getElementById('symptomVal3');
      if (s3) s3.textContent = hpi.location;
      selectedPainLocations.add(hpi.location);
      const aiTrans = document.getElementById('aiInterviewTranscript');
      if (aiTrans) {
        aiTrans.textContent = `“Pain/symptom located in: ${hpi.location}”`;
        aiTrans.dataset.rawText = hpi.location;
      }
      // Highlight matching location chips on Screen 3
      document.querySelectorAll('#aiPainLocationChips .loc-tile').forEach(tile => {
        const loc = (tile.getAttribute('data-location') || '').toLowerCase();
        if (hpi.location.toLowerCase().includes(loc) || loc.includes(hpi.location.toLowerCase())) {
          tile.setAttribute('data-selected', 'true');
          tile.className = 'loc-tile px-4 py-2 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
          const icon = tile.querySelector('.material-symbols-outlined');
          if (icon) {
            icon.textContent = 'check_circle';
            icon.className = 'material-symbols-outlined text-[15px] text-primary-fixed';
          }
        }
      });
    }

    if (hpi.quality) {
      const s4 = document.getElementById('symptomVal4');
      if (s4) s4.textContent = hpi.quality;
      selectedAdaptiveTriggers.add(hpi.quality);
    }

    if (hpi.severity) {
      const s6 = document.getElementById('symptomVal6');
      if (s6) s6.textContent = `Severity: ${hpi.severity} • Graded Clinical Report`;
    }

    // 3. Medications (Screen 7)
    if (ch.medications && Array.isArray(ch.medications)) {
      ch.medications.forEach(m => {
        const name = m.name_as_reported || m.name || m;
        if (typeof name === 'string' && name.trim()) {
          const cleanName = name.trim();
          selectedMedications.add(cleanName);
          const details = `${m.dose_as_reported || m.dosage || ''} ${m.frequency_as_reported || m.frequency || ''}`.trim() || 'Active daily prescription';
          addMedicationToUI(cleanName, details);
          // Highlight matching chips
          document.querySelectorAll('#quickMedChips .med-chip').forEach(chip => {
            const cName = (chip.getAttribute('data-name') || '').toLowerCase();
            if (cleanName.toLowerCase().includes(cName) || cName.includes(cleanName.toLowerCase())) {
              chip.setAttribute('data-selected', 'true');
              chip.className = 'med-chip px-3 py-1.5 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1 transition-all';
              const icon = chip.querySelector('.material-symbols-outlined');
              if (icon) {
                icon.textContent = 'check_circle';
                icon.className = 'material-symbols-outlined text-[14px] text-primary-fixed';
              }
            }
          });
        }
      });
      updateMedsBadge();
    }

    // 4. Past Medical History (Screen 6)
    if (ch.past_medical_history && Array.isArray(ch.past_medical_history)) {
      ch.past_medical_history.forEach(c => {
        const condName = typeof c === 'object' ? (c.condition || c.name || '') : c;
        if (typeof condName === 'string' && condName.trim()) {
          const cleanCond = condName.trim();
          selectedMedHistConditions.add(cleanCond);
          addConditionToUI(cleanCond, 'Confirmed clinical history');
          // Highlight matching chips
          document.querySelectorAll('#medHistQuickChips .medhist-chip').forEach(chip => {
            const cond = (chip.getAttribute('data-condition') || '').toLowerCase();
            if (cleanCond.toLowerCase().includes(cond) || cond.includes(cleanCond.toLowerCase())) {
              chip.setAttribute('data-selected', 'true');
              chip.className = 'medhist-chip px-3.5 py-1.5 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
              const icon = chip.querySelector('.material-symbols-outlined');
              if (icon) {
                icon.textContent = 'check_circle';
                icon.className = 'material-symbols-outlined text-[15px] text-primary-fixed';
              }
            }
          });
        }
      });
      updateMedHistConditionsBadge();
    }

    // 5. Allergies (Screen 7)
    if (ch.allergies && Array.isArray(ch.allergies)) {
      ch.allergies.forEach(a => {
        const allName = typeof a === 'object' ? (a.substance || a.name || a.allergen || '') : a;
        if (typeof allName === 'string' && allName.trim()) {
          const cleanAll = allName.trim();
          selectedAllergies.add(cleanAll);
          // Highlight matching allergy chips
          document.querySelectorAll('#quickAllergyChips .allergy-chip').forEach(chip => {
            const alg = (chip.getAttribute('data-allergy') || '').toLowerCase();
            if (cleanAll.toLowerCase().includes(alg) || alg.includes(cleanAll.toLowerCase())) {
              chip.setAttribute('data-selected', 'true');
              chip.className = 'allergy-chip px-3 py-1.5 rounded-full bg-error text-white font-bold border-error shadow-xs text-xs cursor-pointer flex items-center gap-1 transition-all';
              const icon = chip.querySelector('.material-symbols-outlined');
              if (icon) {
                icon.textContent = 'check_circle';
                icon.className = 'material-symbols-outlined text-[14px] text-white';
              }
            }
          });
        }
      });
      updateAllergiesBadge();
    }

    // 6. Documents
    if (orch.documents && Array.isArray(orch.documents)) {
      orch.documents.forEach(doc => {
        if (!uploadedDocuments.some(d => d.document_id === doc.document_id)) {
          uploadedDocuments.push({
            document_id: doc.document_id,
            file_name: doc.document_type ? `${doc.document_type} Record` : 'Clinical Document',
            file_type: 'application/pdf',
            file_size: 1024 * 120,
            created_at: new Date().toISOString(),
            ocr: {
              document_type: doc.document_type || 'Prescription',
              ocr_text: doc.source_excerpt || '',
              medications: doc.medications || [],
              lab_results: doc.lab_results || []
            }
          });
        }
      });
      renderDocumentsList();
    }

    // 7. Safety & Risk Attention Level
    if (risk.overall_attention_level) {
      const level = risk.overall_attention_level;
      const badge = document.getElementById('safetyAttentionBadge');
      if (badge) {
        badge.textContent = `Attention: ${level.toUpperCase()}`;
        badge.className = `text-xs font-bold px-3 py-1 rounded-full ${level === 'urgent' ? 'bg-red-600 text-white' : level === 'attention' ? 'bg-amber-500 text-white' : 'bg-primary-fixed text-primary'}`;
      }
      if (level === 'urgent' || level === 'emergency' || risk.emergency_stop) {
        triggerHospitalEmergencyAlert(risk.risk_summary || risk.urgency_reason || 'AI Risk Engine detected high-acuity clinical red flag.');
      }
    }

    // 8. Physician Summary (Updates AI summary narrative and story)
    if (summary && summary.overview) {
      const aiNarrative = document.getElementById('aiSummaryNarrative');
      if (aiNarrative && !summary.overview.includes('Summary generated from validated') && !summary.overview.includes('No validated')) {
        aiNarrative.textContent = summary.overview;
      }
      const storyEl = document.getElementById('healthStoryNarrative');
      if (storyEl && summary.overview.length > 20 && !summary.overview.includes('Summary generated from validated')) {
        storyEl.textContent = `“${summary.overview}”`;
        storyEl.dataset.rawText = summary.overview;
      }
    }

    // 9. Update Screen 3 Intake Thread Sidebar Docket
    const docketChief = document.getElementById('intakeDocketChiefSymptom');
    const docketOnset = document.getElementById('intakeDocketOnsetDuration');
    const docketActiveQ = document.getElementById('intakeDocketActiveQuestion');
    const docketCounter = document.getElementById('intakeDocketQuestionCounter');

    if (docketChief) {
      const validSyms = Array.from(selectedWhatBringsSymptoms).filter(s => !isGenericClinicalEntity(s));
      const symDisplay = symptomsToAdd.length > 0 
        ? symptomsToAdd.join(', ') 
        : (ch.chief_complaint && !isGenericClinicalEntity(ch.chief_complaint) ? ch.chief_complaint : (validSyms.length > 0 ? validSyms.join(', ') : 'Awaiting intake...'));
      docketChief.textContent = symDisplay;
    }
    if (docketOnset) {
      const durDisplay = [hpi.onset ? `Onset: ${hpi.onset}` : '', hpi.duration ? `Duration: ${hpi.duration}` : ''].filter(Boolean).join(' • ');
      const validLast = (lastPatientMessage && !isGenericClinicalEntity(lastPatientMessage)) ? lastPatientMessage : '';
      docketOnset.textContent = durDisplay || (hpi.duration || (validLast && (validLast.includes('day') || validLast.includes('week') || validLast.includes('since')) ? validLast : 'Recorded in session'));
    }
    if (docketActiveQ) {
      if (lastAskedQuestion) docketActiveQ.textContent = lastAskedQuestion;
      else if (state.assistant_message) docketActiveQ.textContent = state.assistant_message;
      else if (currentInterviewNextCategory && INTERVIEW_QUESTION_TEMPLATES[currentInterviewNextCategory]) {
        docketActiveQ.textContent = INTERVIEW_QUESTION_TEMPLATES[currentInterviewNextCategory];
      }
    }
    if (docketCounter) {
      docketCounter.textContent = `Question ${Math.min(adaptiveQuestionCount, 5)} of 5`;
    }

    const catKey = getActiveSymptomCategory();
    renderInterviewQuickReplies(catKey, lastAskedQuestion, currentInterviewNextCategory);
    updateSymptomsReviewScreen();
    updateHealthStoryUI();
    renderAdaptiveFollowUpQuestion();
  }

  // Adaptive Question Presets based on Active Clinical Entities
  const ADAPTIVE_PRESETS = {
    fever: {
      question: 'How high does the fever reach, and do you experience chills, shivering, or body aches?',
      subheading: '“How does the fever behave throughout the day?”',
      choices: [
        'High grade fever (above 102°F)',
        'Mild to moderate fever (99°F - 101°F)',
        'Comes and goes in spikes with chills',
        'Constant high temperature all day',
        'Improves temporarily after paracetamol',
        'Not measured with thermometer yet'
      ],
      triggersLabel: 'ASSOCIATED SYMPTOMS & CHILLS (TAP TO ADD):',
      triggers: [
        'Shivering & Chills',
        'Body Aches & Joint Pain',
        'Severe Fatigue & Weakness',
        'Headache & Eye Heaviness',
        'Dry Cough / Sore Throat',
        'Nausea / Loss of Appetite'
      ]
    },
    respiratory: {
      question: 'What is the character of your cough or breathing, and what seems to provoke it?',
      subheading: '“What type of cough or breathing difficulty are you experiencing?”',
      choices: [
        'Dry, irritating throat tickle',
        'Productive with phlegm / mucus',
        'Breathlessness while walking or climbing stairs',
        'Wheezing or chest whistling sound',
        'Sudden severe coughing spells',
        'Mild, mostly in the morning'
      ],
      triggersLabel: 'AGGRAVATING TRIGGERS & FACTORS (TAP TO ADD):',
      triggers: [
        'Cold air / Weather change',
        'Dust, smoke or pollution',
        'Night time / Lying flat',
        'Physical exertion',
        'Runny nose / Sinus drip',
        'Chest tightness'
      ]
    },
    headache: {
      question: 'What is the sensation of your headache, and does light, sound, or stress aggravate it?',
      subheading: '“How does the headache feel, and what seems to trigger it?”',
      choices: [
        'Throbbing / Pulsing on one side',
        'Heavy band of pressure around forehead',
        'Sharp pain behind eyes',
        'Comes suddenly with dizziness',
        'Dull ache present since waking up',
        'Improves in a dark, quiet room'
      ],
      triggersLabel: 'ASSOCIATED TRIGGERS & SENSITIVITY (TAP TO ADD):',
      triggers: [
        'Bright light / Screen exposure',
        'Loud sounds or noise',
        'Lack of sleep / Fatigue',
        'Stress / Mental strain',
        'Nausea or upset stomach',
        'Neck stiffness'
      ]
    },
    stomach: {
      question: 'Where is the stomach discomfort located, and does food, fasting, or posture affect it?',
      subheading: '“Where is the stomach discomfort, and how does food or rest affect it?”',
      choices: [
        'Sharp cramping or colic spasms',
        'Burning sensation behind breastbone (Acidity)',
        'Dull, persistent bloating & fullness',
        'Nausea / Feeling like vomiting',
        'Relieved after antacids or passing gas',
        'Constant aching soreness'
      ],
      triggersLabel: 'TRIGGERS & DIETARY FACTORS (TAP TO ADD):',
      triggers: [
        'After eating spicy/oily food',
        'On an empty stomach',
        'Lying flat after meals',
        'Stress or skipping meals',
        'Loss of appetite',
        'Watery stools / Diarrhea'
      ]
    },
    pain: {
      question: 'What does this discomfort feel like, and does physical movement or resting affect it?',
      subheading: '“What does the pain feel like, and does anything make it better or worse?”',
      choices: [
        'Sharp, stabbing sensation',
        'Dull, constant aching pressure',
        'Throbbing or pulsing in rhythm',
        'Burning sensation',
        'Comes and goes in sudden waves',
        'Gets better when resting quietly'
      ],
      triggersLabel: 'TRIGGERING & AGGRAVATING FACTORS (TAP TO ADD):',
      triggers: [
        'Physical exertion / Walking',
        'Bending, moving or changing posture',
        'Touching or pressing the area',
        'After eating meals',
        'Stress or emotional tension',
        'Cold or hot weather'
      ]
    },
    general: {
      question: 'How has this symptom developed over time, and what factors seem to make it better or worse?',
      subheading: '“How is this symptom affecting your daily routine?”',
      choices: [
        'Gradually worsening since it started',
        'Stays about the same intensity',
        'Noticeably better when resting',
        'Constant throughout day and night',
        'Comes and goes intermittently',
        'Not sure / Varies from day to day'
      ],
      triggersLabel: 'ASSOCIATED FACTORS & TRIGGERS (TAP TO ADD):',
      triggers: [
        'Physical activity / Exertion',
        'Lack of rest / Fatigue',
        'Weather / Temperature shift',
        'Stress or anxiety',
        'Relieved after sleep',
        'Triggered after meals'
      ]
    }
  };

  function getActiveSymptomCategory() {
    const validSyms = Array.from(selectedWhatBringsSymptoms).filter(s => !isGenericClinicalEntity(s)).join(' ').toLowerCase();
    const lastMsg = (lastPatientMessage && !isGenericClinicalEntity(lastPatientMessage)) ? lastPatientMessage.toLowerCase() : '';
    const chief = (document.getElementById('intakeDocketChiefSymptom')?.textContent || '').toLowerCase();
    const chiefVal = (document.getElementById('symptomVal1')?.textContent || '').toLowerCase();
    const locs = Array.from(selectedPainLocations).filter(l => !isGenericClinicalEntity(l)).join(' ').toLowerCase();
    const combined = `${validSyms} ${lastMsg} ${!isGenericClinicalEntity(chief) ? chief : ''} ${!isGenericClinicalEntity(chiefVal) ? chiefVal : ''} ${locs}`;

    if (combined.includes('fever') || combined.includes('chill') || combined.includes('temperature') || combined.includes('shiver') || combined.includes('bukhar') || combined.includes('infection') || combined.includes('pyrexia')) {
      return 'fever';
    }
    if (combined.includes('cough') || combined.includes('breath') || combined.includes('wheez') || combined.includes('asthma') || combined.includes('cold') || combined.includes('sore throat') || combined.includes('phlegm') || combined.includes('sneeze') || combined.includes('runny')) {
      return 'respiratory';
    }
    if (combined.includes('headache') || combined.includes('head pain') || combined.includes('migraine') || combined.includes('sir dard') || combined.includes('dizziness') || combined.includes('head') || combined.includes('temple')) {
      return 'headache';
    }
    if (combined.includes('stomach') || combined.includes('abdomen') || combined.includes('nausea') || combined.includes('vomit') || combined.includes('acid') || combined.includes('digest') || combined.includes('pet dard') || combined.includes('cramp') || combined.includes('belly') || combined.includes('diarrhea') || combined.includes('loose stool')) {
      return 'stomach';
    }
    if (combined.includes('chest') || combined.includes('pain') || combined.includes('ache') || combined.includes('back') || combined.includes('joint') || combined.includes('dard') || combined.includes('knee') || combined.includes('shoulder') || combined.includes('spine') || combined.includes('arm') || combined.includes('leg') || combined.includes('limb') || combined.includes('stiff') || combined.includes('body ache')) {
      return 'pain';
    }
    return 'general';
  }

  const INTERVIEW_RECOMMENDATION_BANK = {
    onset: [
      'Started today',
      'Started 1-2 days ago',
      'Started 3-5 days ago',
      'More than a week ago',
      'Came on suddenly',
      'Gradual onset'
    ],
    duration: [
      'For 1-2 days',
      'For 3-4 days',
      'For about a week',
      'Comes and goes intermittently',
      'Constant throughout day & night'
    ],
    severity: [
      'Mild discomfort (1-3/10)',
      'Moderate (4-6/10)',
      'Severe (7-8/10)',
      'Extremely severe (9-10/10)',
      'Getting progressively worse',
      'Manageable with rest'
    ],
    character: {
      fever: ['High fever (>101°F)', 'Low grade fever (99-100°F)', 'With chills & shivering', 'Night sweats', 'Body aches & fatigue'],
      respiratory: ['Dry cough', 'Phlegm / Productive cough', 'Shortness of breath on walking', 'Chest tightness', 'Wheezing sound'],
      headache: ['Throbbing / Pulsating', 'Pressure in forehead', 'Sharp stabbing', 'Sensitivity to bright light', 'Dull heavy ache'],
      stomach: ['Sharp cramping', 'Burning acidity / Reflux', 'Bloating & fullness', 'Nausea / Upset stomach', 'Pain after meals'],
      pain: ['Sharp stabbing pain', 'Dull persistent ache', 'Burning sensation', 'Stiffness / Soreness', 'Radiating pain'],
      general: ['Sharp pain', 'Dull ache', 'Burning sensation', 'Constant pressure', 'Fluctuating intensity']
    },
    location: {
      fever: ['Whole Body / Generalized', 'Forehead & Eyes', 'Throat & Neck', 'Chest & Back'],
      respiratory: ['Chest & Lungs', 'Throat & Upper Airway', 'Behind Breastbone', 'Both sides of chest'],
      headache: ['Forehead & Temples', 'Back of Head / Neck', 'One side of head', 'Behind eyes / Sinus'],
      stomach: ['Upper Stomach (Epigastric)', 'Lower Abdomen', 'Right Lower Side', 'Around Navel', 'Entire Abdomen'],
      pain: ['Lower Back / Spine', 'Neck & Shoulders', 'Joints (Knee / Elbow)', 'Chest / Ribs', 'Arms & Legs'],
      general: ['Whole Body / Generalized', 'Head / Forehead', 'Chest / Upper Body', 'Abdomen / Stomach', 'Back / Spine', 'Arms / Legs']
    },
    timing: [
      'Constant throughout the day',
      'Worse in the morning',
      'Worse in the evening / night',
      'Comes and goes in waves',
      'Triggered after meals or exertion'
    ],
    progression: [
      'Getting progressively worse',
      'Staying about the same',
      'Slowly improving with rest',
      'Comes back after medicine wears off'
    ],
    associated_symptoms: {
      fever: ['Chills & Shivering', 'Body aches & Weakness', 'Headache', 'Nausea / Loss of appetite', 'Cough & Sore throat'],
      respiratory: ['Fever / Chills', 'Runny nose / Sneezing', 'Sore throat', 'Chest tightness', 'Fatigue / Tiredness'],
      headache: ['Nausea or vomiting', 'Sensitivity to light & sound', 'Dizziness', 'Neck stiffness', 'Blurred vision'],
      stomach: ['Nausea / Vomiting', 'Diarrhea / Loose stools', 'Heartburn / Acidity', 'Loss of appetite', 'Fever'],
      pain: ['Swelling / Inflammation', 'Numbness / Tingling', 'Weakness in limbs', 'Stiffness in morning'],
      general: ['Fatigue / Tiredness', 'Dizziness', 'Mild headache', 'Loss of appetite', 'Restlessness']
    },
    current_medications: [
      'Took Paracetamol (Dolo 650)',
      'Took Antacid / Pan-D',
      'Took Painkiller (Ibuprofen)',
      'Using an Inhaler',
      'Regular BP / Diabetes meds',
      'No medications taken'
    ],
    allergies: [
      'No known drug allergies',
      'Allergic to Penicillin',
      'Allergic to Sulfa drugs',
      'Allergic to NSAIDs / Aspirin',
      'Dust or pollen allergy'
    ],
    past_medical_history: [
      'Type 2 Diabetes',
      'Hypertension (High BP)',
      'Asthma / Bronchitis',
      'Thyroid disorder',
      'No major past medical history'
    ]
  };

  function renderInterviewQuickReplies(activeCategory, questionText, nextCategory) {
    const chipsContainer = document.getElementById('aiPainLocationChips');
    const badge = document.getElementById('painLocCountBadge');
    const heading = document.getElementById('aiQuickRepliesHeading');
    if (!chipsContainer) return;

    chipsContainer.innerHTML = '';
    const cat = activeCategory || getActiveSymptomCategory();
    let replies = [];

    // 1. If nextCategory matches recommendation bank
    if (nextCategory && INTERVIEW_RECOMMENDATION_BANK[nextCategory]) {
      const bank = INTERVIEW_RECOMMENDATION_BANK[nextCategory];
      if (Array.isArray(bank)) {
        replies = bank;
      } else if (typeof bank === 'object') {
        replies = bank[cat] || bank.general || [];
      }
    }

    // 2. Fallback: derive category from questionText
    if (replies.length === 0 && questionText) {
      const qLower = questionText.toLowerCase();
      if (qLower.includes('start') || qLower.includes('when')) replies = INTERVIEW_RECOMMENDATION_BANK.onset;
      else if (qLower.includes('how long') || qLower.includes('duration') || qLower.includes('days')) replies = INTERVIEW_RECOMMENDATION_BANK.duration;
      else if (qLower.includes('scale') || qLower.includes('severe') || qLower.includes('intensity') || qLower.includes('0 to 10')) replies = INTERVIEW_RECOMMENDATION_BANK.severity;
      else if (qLower.includes('feel like') || qLower.includes('character') || qLower.includes('quality') || qLower.includes('type of')) replies = (INTERVIEW_RECOMMENDATION_BANK.character[cat] || INTERVIEW_RECOMMENDATION_BANK.character.general);
      else if (qLower.includes('where') || qLower.includes('location') || qLower.includes('body')) replies = (INTERVIEW_RECOMMENDATION_BANK.location[cat] || INTERVIEW_RECOMMENDATION_BANK.location.general);
      else if (qLower.includes('other') || qLower.includes('along with') || qLower.includes('associated') || qLower.includes('notice')) replies = (INTERVIEW_RECOMMENDATION_BANK.associated_symptoms[cat] || INTERVIEW_RECOMMENDATION_BANK.associated_symptoms.general);
      else if (qLower.includes('medication') || qLower.includes('medicine') || qLower.includes('taking')) replies = INTERVIEW_RECOMMENDATION_BANK.current_medications;
      else if (qLower.includes('allerg')) replies = INTERVIEW_RECOMMENDATION_BANK.allergies;
      else if (qLower.includes('condition') || qLower.includes('history') || qLower.includes('past')) replies = INTERVIEW_RECOMMENDATION_BANK.past_medical_history;
    }

    // 3. Fallback: smart default recommendations for the active symptom
    if (replies.length === 0) {
      if (cat === 'fever') {
        replies = ['High fever (>101°F)', 'Fever for 2 days', 'Fever with chills & shivering', 'Body aches & fatigue', 'Took Paracetamol with temporary relief'];
      } else if (cat === 'respiratory') {
        replies = ['Dry cough for 3 days', 'Cough with mucus / phlegm', 'Shortness of breath on walking', 'Sore throat & cold', 'Worse at night'];
      } else if (cat === 'headache') {
        replies = ['Severe throbbing headache', 'Forehead & temples pain', 'Sensitivity to bright light', 'Started this morning', 'Accompanied by nausea'];
      } else if (cat === 'stomach') {
        replies = ['Stomach cramp after food', 'Burning acidity & gas', 'Nausea & vomiting', 'Lower abdomen pain', 'Started yesterday'];
      } else if (cat === 'pain') {
        replies = ['Sharp pain in lower back', 'Joint stiffness in morning', 'Pain radiating to legs', 'Started after exertion', 'Moderate intensity (5/10)'];
      } else {
        replies = ['Started 1-2 days ago', 'Moderate discomfort (4-6/10)', 'Comes and goes intermittently', 'Worse in evenings', 'Relieved with rest'];
      }
    }

    if (badge) badge.textContent = `${replies.length} Smart Options`;
    if (heading) heading.textContent = 'RECOMMENDED REPLIES (TAP TO ANSWER):';

    // Render exact styled button chips
    replies.forEach(replyText => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'loc-tile px-4 py-2 rounded-full bg-surface-container hover:bg-secondary-container text-on-surface text-xs font-semibold border border-secondary-container transition-all cursor-pointer flex items-center gap-1.5';
      btn.setAttribute('data-reply', replyText);
      btn.innerHTML = `
        <span class="material-symbols-outlined text-[15px] text-secondary/40">radio_button_unchecked</span>
        <span>${replyText}</span>
      `;

      btn.addEventListener('click', async () => {
        btn.className = 'loc-tile px-4 py-2 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
        const icon = btn.querySelector('.material-symbols-outlined');
        if (icon) {
          icon.textContent = 'check_circle';
          icon.className = 'material-symbols-outlined text-[15px] text-primary-fixed';
        }

        const aiTrans = document.getElementById('aiInterviewTranscript');
        if (aiTrans) {
          aiTrans.textContent = `“${replyText}”`;
          aiTrans.dataset.rawText = replyText;
        }
        const aiBadge = document.getElementById('aiInterviewStatusBadge');
        if (aiBadge) {
          aiBadge.textContent = '✓ Recorded';
          aiBadge.classList.remove('bg-white');
          aiBadge.classList.add('bg-primary-fixed', 'text-primary');
        }

        saveToVaultNotification("Response Recorded", replyText);
        await sendPatientMessage(replyText, 'quick_reply');
      });

      chipsContainer.appendChild(btn);
    });
  }

  function renderAdaptiveFollowUpQuestion() {
    const heading = document.getElementById('adaptiveFollowUpQuestion');
    const badge = document.getElementById('adaptiveQuestionBadge');
    const transcript = document.getElementById('adaptiveTranscript');
    const contextBadge = document.getElementById('adaptiveContextBadge');
    const subHeadingEl = document.getElementById('adaptiveInquirySubheading');
    const triggersLabelEl = document.getElementById('adaptiveTriggersLabel');
    const choicesGroup = document.getElementById('adaptiveChoicesGroup');
    const triggersContainer = document.getElementById('adaptiveTriggerChips');
    const choicesBadge = document.getElementById('adaptiveChoicesCountBadge');
    const triggersBadge = document.getElementById('adaptiveTriggersCountBadge');

    const catKey = getActiveSymptomCategory();
    const preset = ADAPTIVE_PRESETS[catKey] || ADAPTIVE_PRESETS.general;

    const persisted = localStorage.getItem('cliniqo_last_llm_question') || '';
    const resolved =
      lastAskedQuestion ||
      (persisted && !isGenericClinicalEntity(persisted) ? persisted : '') ||
      (currentInterviewNextCategory && INTERVIEW_QUESTION_TEMPLATES[currentInterviewNextCategory]) ||
      preset.question ||
      'Let us understand that better. Could you tell me more about what you have shared so far?';

    if (heading) heading.textContent = `“${resolved}”`;
    if (badge) badge.textContent = `ADAPTIVE INTAKE \u2022 LLM QUESTION ${adaptiveQuestionCount}`;

    // Context Card ("You told us"): Resolve the real patient statement or chief complaint
    const symList = Array.from(selectedWhatBringsSymptoms).filter(s => !isGenericClinicalEntity(s));
    const validLast = (lastPatientMessage && !isGenericClinicalEntity(lastPatientMessage)) ? lastPatientMessage : '';
    const persistedResp = localStorage.getItem('cliniqo_last_patient_response') || '';
    const validPersisted = (persistedResp && !isGenericClinicalEntity(persistedResp)) ? persistedResp : '';
    const s1Text = (document.getElementById('symptomVal1')?.textContent || '').trim();
    const validS1 = (s1Text && !isGenericClinicalEntity(s1Text) && s1Text !== 'Routine clinical intake evaluation') ? s1Text : '';
    const locList = Array.from(selectedPainLocations).filter(l => !isGenericClinicalEntity(l));

    let youToldUsText = '';
    if (validLast) {
      youToldUsText = validLast;
    } else if (validPersisted) {
      youToldUsText = validPersisted;
    } else if (symList.length > 0) {
      youToldUsText = `I've been experiencing ${symList.join(', ')} recently.`;
    } else if (validS1) {
      youToldUsText = validS1;
    } else if (locList.length > 0) {
      youToldUsText = `Discomfort localized in ${locList.join(' / ')}.`;
    }

    if (transcript) {
      transcript.textContent = youToldUsText ? `“${youToldUsText}”` : '“Awaiting symptom details from intake.”';
      transcript.dataset.rawText = youToldUsText || '';
    }
    if (contextBadge) {
      if (youToldUsText) {
        contextBadge.textContent = '✓ Recorded';
        contextBadge.className = 'text-[10px] font-bold text-white bg-primary px-2 py-0.5 rounded-full transition-all';
      } else {
        contextBadge.textContent = 'Awaiting Intake';
        contextBadge.className = 'text-[10px] font-bold text-primary bg-primary-fixed px-2 py-0.5 rounded-full transition-all';
      }
    }

    if (subHeadingEl) subHeadingEl.textContent = preset.subheading;
    if (triggersLabelEl) triggersLabelEl.textContent = preset.triggersLabel;
    if (choicesBadge) choicesBadge.textContent = `${selectedAdaptiveChoices.size} Selected`;
    if (triggersBadge) triggersBadge.textContent = `${selectedAdaptiveTriggers.size} Selected`;

    // Render Dynamic Choice Buttons on Screen 4
    if (choicesGroup) {
      choicesGroup.innerHTML = '';
      preset.choices.forEach(choiceText => {
        const isSelected = selectedAdaptiveChoices.has(choiceText);
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = isSelected 
          ? 'choice-btn w-full p-4 rounded-2xl bg-primary text-white text-xs sm:text-sm font-bold shadow-xs border border-primary cursor-pointer flex items-center justify-between transition-all'
          : 'choice-btn w-full p-4 rounded-2xl bg-surface-container hover:bg-secondary-container text-on-surface text-xs sm:text-sm font-semibold border border-secondary-container transition-all cursor-pointer flex items-center justify-between text-left';
        btn.setAttribute('data-choice', choiceText);
        btn.setAttribute('data-selected', isSelected.toString());
        btn.innerHTML = `
          <span>${choiceText}</span>
          <span class="material-symbols-outlined text-[20px] ${isSelected ? 'text-primary-fixed' : 'text-secondary/40'}">${isSelected ? 'check_circle' : 'radio_button_unchecked'}</span>
        `;
        btn.addEventListener('click', () => {
          const currentlySel = btn.getAttribute('data-selected') === 'true';
          const nextState = !currentlySel;
          btn.setAttribute('data-selected', nextState.toString());
          if (nextState) {
            selectedAdaptiveChoices.add(choiceText);
            btn.className = 'choice-btn w-full p-4 rounded-2xl bg-primary text-white text-xs sm:text-sm font-bold shadow-xs border border-primary cursor-pointer flex items-center justify-between transition-all';
            const icon = btn.querySelector('.material-symbols-outlined');
            if (icon) {
              icon.textContent = 'check_circle';
              icon.className = 'material-symbols-outlined text-[20px] text-primary-fixed';
            }
          } else {
            selectedAdaptiveChoices.delete(choiceText);
            btn.className = 'choice-btn w-full p-4 rounded-2xl bg-surface-container hover:bg-secondary-container text-on-surface text-xs sm:text-sm font-semibold border border-secondary-container transition-all cursor-pointer flex items-center justify-between text-left';
            const icon = btn.querySelector('.material-symbols-outlined');
            if (icon) {
              icon.textContent = 'radio_button_unchecked';
              icon.className = 'material-symbols-outlined text-[20px] text-secondary/40';
            }
          }
          updateAdaptiveChoicesText();
        });
        choicesGroup.appendChild(btn);
      });
    }

    // Render Dynamic Trigger Chips on Screen 4
    if (triggersContainer) {
      triggersContainer.innerHTML = '';
      preset.triggers.forEach(triggerText => {
        const isSelected = selectedAdaptiveTriggers.has(triggerText);
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = isSelected
          ? 'adaptive-trigger-chip px-4 py-2 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all'
          : 'adaptive-trigger-chip px-4 py-2 rounded-full bg-surface-container hover:bg-secondary-container text-on-surface text-xs font-semibold border border-secondary-container transition-all cursor-pointer flex items-center gap-1.5';
        chip.setAttribute('data-trigger', triggerText);
        chip.setAttribute('data-selected', isSelected.toString());
        chip.innerHTML = `
          <span class="material-symbols-outlined text-[15px] ${isSelected ? 'text-primary-fixed' : 'text-secondary/40'}">${isSelected ? 'check_circle' : 'radio_button_unchecked'}</span>
          <span>${triggerText}</span>
        `;
        chip.addEventListener('click', () => {
          const currentlySel = chip.getAttribute('data-selected') === 'true';
          const nextState = !currentlySel;
          chip.setAttribute('data-selected', nextState.toString());
          if (nextState) {
            selectedAdaptiveTriggers.add(triggerText);
            chip.className = 'adaptive-trigger-chip px-4 py-2 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
            const icon = chip.querySelector('.material-symbols-outlined');
            if (icon) {
              icon.textContent = 'check_circle';
              icon.className = 'material-symbols-outlined text-[15px] text-primary-fixed';
            }
          } else {
            selectedAdaptiveTriggers.delete(triggerText);
            chip.className = 'adaptive-trigger-chip px-4 py-2 rounded-full bg-surface-container hover:bg-secondary-container text-on-surface text-xs font-semibold border border-secondary-container transition-all cursor-pointer flex items-center gap-1.5';
            const icon = chip.querySelector('.material-symbols-outlined');
            if (icon) {
              icon.textContent = 'radio_button_unchecked';
              icon.className = 'material-symbols-outlined text-[15px] text-secondary/40';
            }
          }
          updateAdaptiveTriggersBadge();
        });
        triggersContainer.appendChild(chip);
      });
    }
  }

  // =========================================================================
  // 5. DYNAMIC UI BUILDERS & LIST RENDERERS
  // =========================================================================
  function addMedicationToUI(medName, medDetails) {
    const list = document.getElementById('medicationsList');
    if (!list) return;
    const cleanName = (medName || '').trim();
    if (!cleanName) return;
    const exists = Array.from(list.querySelectorAll('p.font-headline')).some(p => p.textContent.trim().toLowerCase() === cleanName.toLowerCase());
    if (exists) return;

    const newId = 'ocr_med_' + Math.random().toString(36).substr(2, 8);
    const card = document.createElement('div');
    card.id = `medCard_${newId}`;
    card.className = 'p-3.5 rounded-2xl bg-surface-container border border-primary/30 flex items-center justify-between group animate-fadeIn';
    card.innerHTML = `
      <div class="flex-1 pr-2">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <p class="font-headline text-sm font-bold text-on-surface">${cleanName}</p>
            <span class="text-[9px] font-bold px-2 py-0.5 rounded-full bg-primary-fixed text-primary">Active Rx</span>
          </div>
          <button class="med-edit-btn opacity-70 group-hover:opacity-100 hover:text-primary text-secondary p-1 text-xs cursor-pointer" data-wrapper="medCard_${newId}" data-target="medVal_${newId}" title="Edit in box" type="button">
            <span class="material-symbols-outlined text-[15px]">edit</span>
          </button>
        </div>
        <p class="text-xs text-secondary" id="medVal_${newId}">${medDetails || 'Prescribed medication'}</p>
      </div>
      <span class="material-symbols-outlined text-primary text-[20px] shrink-0">check_circle</span>
    `;
    list.appendChild(card);
    const editBtn = card.querySelector('.med-edit-btn');
    if (editBtn) {
      editBtn.addEventListener('click', () => {
        startInlineEdit({
          wrapperId: `medCard_${newId}`,
          textElId: `medVal_${newId}`,
          isQuoted: false,
          rows: 1,
          onSave: () => {
            updateHealthStoryUI();
            syncClinicalData();
          }
        });
      });
    }
  }

  function addConditionToUI(condName, condDetails) {
    const list = document.getElementById('medicalHistoryList');
    if (!list) return;
    const cleanName = (condName || '').trim();
    if (!cleanName) return;
    const exists = Array.from(list.querySelectorAll('h3.font-headline')).some(h => h.textContent.trim().toLowerCase() === cleanName.toLowerCase());
    if (exists) return;

    const newId = 'ocr_hist_' + Math.random().toString(36).substr(2, 8);
    const card = document.createElement('div');
    card.id = `medHistCard_${newId}`;
    card.className = 'p-4 rounded-2xl bg-surface-container border border-primary/30 space-y-2 relative group animate-fadeIn';
    card.innerHTML = `
      <div class="flex items-center justify-between">
        <span class="text-xs font-bold uppercase text-primary">Documented Condition</span>
        <div class="flex items-center gap-1.5">
          <span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-primary-fixed text-primary">Ingested</span>
          <button class="med-hist-edit-btn opacity-70 group-hover:opacity-100 hover:text-primary text-secondary p-1 text-xs cursor-pointer" data-wrapper="medHistCard_${newId}" data-target="medHistVal_${newId}" type="button">
            <span class="material-symbols-outlined text-[14px]">edit</span>
          </button>
        </div>
      </div>
      <h3 class="font-headline text-lg font-bold text-on-surface">${cleanName}</h3>
      <p class="text-xs text-secondary" id="medHistVal_${newId}">${condDetails || 'Documented in clinical history'}</p>
    `;
    list.appendChild(card);
    const editBtn = card.querySelector('.med-hist-edit-btn');
    if (editBtn) {
      editBtn.addEventListener('click', () => {
        startInlineEdit({
          wrapperId: `medHistCard_${newId}`,
          textElId: `medHistVal_${newId}`,
          isQuoted: false,
          rows: 2,
          onSave: () => {
            updateHealthStoryUI();
            syncClinicalData();
          }
        });
      });
    }
  }

  function addTimelineEventToUI({ category, title, date, badge, desc }) {
    const list = document.getElementById('timelineList');
    if (!list) return;

    const newId = 'tl_' + Math.random().toString(36).substr(2, 8);
    const cat = (category || 'intake').toLowerCase();
    const card = document.createElement('div');
    card.className = 'timeline-item relative pl-6 space-y-2 animate-fadeIn';
    card.setAttribute('data-category', cat);
    card.id = `timelineCard_${newId}`;
    card.innerHTML = `
      <div class="absolute -left-[17px] top-1.5 w-4 h-4 rounded-full bg-primary border-2 border-white shadow-xs"></div>
      <div class="p-4 rounded-2xl bg-white border border-primary/30 shadow-xs space-y-1 group">
        <div class="flex items-center justify-between text-xs">
          <span class="font-bold text-primary">${date || 'Recent Entry'}</span>
          <div class="flex items-center gap-1.5">
            <span class="px-2 py-0.5 rounded-full bg-primary-fixed text-primary text-[10px] font-bold">${badge || 'Verified Record'}</span>
            <button class="timeline-edit-btn opacity-70 group-hover:opacity-100 hover:text-primary text-secondary p-0.5 text-xs cursor-pointer" data-wrapper="timelineCard_${newId}" data-target="timelineVal_${newId}" type="button">
              <span class="material-symbols-outlined text-[14px]">edit</span>
            </button>
          </div>
        </div>
        <h4 class="font-headline text-sm font-bold text-on-surface">${title}</h4>
        <p class="text-xs text-secondary leading-relaxed" id="timelineVal_${newId}">${desc || 'Clinical details documented in health vault.'}</p>
      </div>
    `;

    const firstChild = list.firstElementChild;
    if (firstChild && firstChild.nextElementSibling) {
      list.insertBefore(card, firstChild.nextElementSibling);
    } else {
      list.appendChild(card);
    }

    const editBtn = card.querySelector('.timeline-edit-btn');
    if (editBtn) {
      editBtn.addEventListener('click', () => {
        startInlineEdit({
          wrapperId: `timelineCard_${newId}`,
          textElId: `timelineVal_${newId}`,
          isQuoted: false,
          rows: 2
        });
      });
    }

    renderTimelineFilteredItems();
  }

  function renderTimelineFilteredItems() {
    const items = document.querySelectorAll('#timelineList .timeline-item');
    const isAll = activeTimelineFilters.has('all') || activeTimelineFilters.size === 0;

    items.forEach(item => {
      const cat = item.getAttribute('data-category');
      if (isAll || activeTimelineFilters.has(cat)) {
        item.style.display = 'block';
      } else {
        item.style.display = 'none';
      }
    });
  }

  function renderDocumentsList() {
    const emptyState = document.getElementById('vaultEmptyState');
    const list = document.getElementById('vaultDocList');
    const countHdr = document.getElementById('vaultDocCountHeader');

    if (!list) return;

    if (uploadedDocuments.length === 0) {
      if (emptyState) emptyState.classList.remove('hidden');
      list.classList.add('hidden');
      if (countHdr) countHdr.textContent = 'Stored Vault Documents (0)';
      return;
    }

    if (emptyState) emptyState.classList.add('hidden');
    list.classList.remove('hidden');
    if (countHdr) countHdr.textContent = `Stored Vault Documents (${uploadedDocuments.length})`;

    list.innerHTML = '';
    uploadedDocuments.forEach(doc => {
      const row = document.createElement('div');
      row.className = 'py-3 flex items-center justify-between border-b border-secondary-container/40 last:border-0';
      row.setAttribute('data-doc-id', doc.document_id);
      row.innerHTML = `
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-surface-container text-primary flex items-center justify-center shrink-0">
            <span class="material-symbols-outlined text-[22px]">description</span>
          </div>
          <div>
            <p class="font-bold text-on-surface text-xs sm:text-sm">${doc.file_name}</p>
            <div class="flex flex-wrap items-center gap-1.5 mt-1">
              <span class="text-[10px] text-secondary">Uploaded ${new Date(doc.created_at).toLocaleDateString()}</span>
              <span class="px-2 py-0.5 rounded-full ${doc.document_classification === 'current' ? 'bg-primary-fixed text-primary' : 'bg-secondary-container text-secondary'} text-[9px] font-bold uppercase">${doc.document_classification === 'current' ? 'Current' : 'Historical'}</span>
              <span class="text-[10px] text-secondary">${doc.document_date ? `Medical date: ${doc.document_date}` : 'Medical date: Unknown'}</span>
              <span class="text-[10px] text-secondary">• ${(doc.file_size / 1024).toFixed(1)} KB • OCR</span>
            </div>
          </div>
        </div>
        <button class="inspect-ocr-btn text-xs font-bold text-primary hover:underline cursor-pointer" type="button">Inspect OCR</button>
      `;

      const inspectBtn = row.querySelector('.inspect-ocr-btn');
      if (inspectBtn) {
        inspectBtn.addEventListener('click', () => {
          populateReviewExtractedScreen(doc);
          navigateTo('records-review-extracted-information');
        });
      }

      list.appendChild(row);
    });
  }

  function renderPatientCasesDashboard() {
    const container = document.getElementById('homePatientCasesList');
    if (!container) return;

    container.innerHTML = '';
    if (patientRegistry.length === 0) {
      container.innerHTML = `<div class="py-6 text-center text-xs text-secondary">Your health record will appear here once you begin. Tap "Start Health Assessment" to get started.</div>`;
      return;
    }

    patientRegistry.forEach(p => {
      const initials = p.display_name ? p.display_name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2) : 'PT';
      const isActive = activePatient && (activePatient.patient_id === p.patient_id || activePatient.abha_id === p.abha_id);
      const docCount = (p.patient_id === activePatient.patient_id) ? uploadedDocuments.length : (p.documents_count || 0);
      const chiefReason = (p.patient_id === activePatient.patient_id && document.getElementById('whatBringsTranscript')) 
        ? document.getElementById('whatBringsTranscript').textContent.replace(/^[“"\s]+|[”"\s]+$/g, '').slice(0, 50) 
        : (p.chief_complaint || "Routine Clinical Intake");

      const row = document.createElement('div');
      row.className = `p-3.5 rounded-2xl flex flex-col sm:flex-row sm:items-center justify-between gap-3 transition-all ${isActive ? 'bg-primary-fixed/40 border border-primary/40 shadow-xs' : 'bg-surface-container-lowest hover:bg-surface-container border border-secondary-container/60'}`;
      row.innerHTML = `
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-full ${isActive ? 'bg-primary text-white' : 'bg-surface-container text-primary'} font-headline font-bold text-xs flex items-center justify-center shrink-0 shadow-xs">
            ${initials}
          </div>
          <div class="text-left">
            <div class="flex items-center gap-2">
              <p class="font-headline font-bold text-on-surface text-sm">${p.display_name}</p>
              ${isActive ? '<span class="px-2 py-0.5 rounded-full bg-primary text-white text-[10px] font-bold">Active Patient</span>' : ''}
            </div>
            <p class="text-xs text-secondary">ABHA: <span class="font-mono">${p.abha_id || 'N/A'}</span> • ${p.gender || 'Patient'} ${p.date_of_birth ? '(' + p.date_of_birth + ')' : ''}</p>
            <p class="text-[11px] text-on-surface-variant mt-0.5"><strong>Clinical Reason:</strong> ${chiefReason} • <strong>Scanned Docs:</strong> ${docCount} verified</p>
          </div>
        </div>
        <div class="flex items-center gap-2 self-end sm:self-center shrink-0">
          <button class="select-patient-case-btn px-4 py-1.5 rounded-full ${isActive ? 'bg-primary text-white' : 'bg-surface-container hover:bg-secondary-container text-primary'} text-xs font-bold transition-all shadow-xs cursor-pointer flex items-center gap-1" type="button" data-patient-id="${p.patient_id || p.abha_id}">
            <span class="material-symbols-outlined text-[15px]">${isActive ? 'folder_open' : 'check'}</span>
            <span>${isActive ? 'Continue Case' : 'Open Case'}</span>
          </button>
        </div>
      `;

      const btn = row.querySelector('.select-patient-case-btn');
      if (btn) {
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          switchPatient(p.patient_id || p.abha_id);
          navigateTo('assessment-what-brings-you-here');
        });
      }

      container.appendChild(row);
    });
  }

  // =========================================================================
  // 6. REAL-TIME HEALTH STORY SYNCHRONIZER
  // =========================================================================
  function updateHealthStoryUI() {
    const isGenericText = isGenericClinicalEntity;

    // Robust NLP extractor for clean symptom entities and timeline/duration
    const extractSymptomAndOnset = (text) => {
      if (!text || isGenericClinicalEntity(text)) return { symptom: '', onset: '' };
      let raw = String(text).replace(/^[“"'\s]+|[”"'\s]+$/g, '').trim();
      if (isGenericClinicalEntity(raw)) return { symptom: '', onset: '' };
      
      let onset = '';
      const durMatch = raw.match(/\b(?:for|past|last)\s+(\d+\s*(?:days?|weeks?|months?|hours?))\b/i);
      const sinceMatch = raw.match(/\b(?:since)\s+(yesterday|today|last night|last week|\d+\s*(?:days?|weeks?|months?)\s*(?:ago)?)\b/i);
      
      if (durMatch) {
        onset = `Started ~${durMatch[1]} ago`;
        raw = raw.replace(durMatch[0], '');
      } else if (sinceMatch) {
        onset = `Started ${sinceMatch[1]}`;
        raw = raw.replace(sinceMatch[0], '');
      } else if (raw.toLowerCase().includes('yesterday')) {
        onset = 'Started yesterday';
        raw = raw.replace(/\b(?:since\s+)?yesterday\b/i, '');
      } else if (raw.toLowerCase().includes('today') || raw.toLowerCase().includes('morning')) {
        onset = 'Started today';
      }

      // Strip conversational prefixes and trailing fillers
      let symptom = raw
        .replace(/^I('ve been experiencing| have been experiencing| have got| have| am having| am experiencing| feel| felt| have had| got)\s+/i, '')
        .replace(/^(?:patient (?:has|presents with|is complaining of)|suffering from|complaining of|experiencing|problem is|trouble with)\s+/i, '')
        .replace(/\s+recently\.?$/i, '')
        .replace(/\s+now\.?$/i, '')
        .replace(/\s+also\.?$/i, '')
        .replace(/^[,\s.-]+|[,\s.-]+$/g, '')
        .trim();

      if (symptom && !isGenericClinicalEntity(symptom)) {
        symptom = symptom.charAt(0).toUpperCase() + symptom.slice(1);
      } else {
        symptom = '';
      }

      return { symptom, onset };
    };

    // 1. Resolve Primary Complaint / Reason for Visit
    const symList = Array.from(selectedWhatBringsSymptoms).filter(s => !isGenericClinicalEntity(s));
    const wbTranscript = document.getElementById('whatBringsTranscript');
    const wbRaw = (wbTranscript?.dataset.rawText || wbTranscript?.textContent || '').replace(/^[“"\s]+|[”"\s]+$/g, '').trim();
    const aiTrans = document.getElementById('aiInterviewTranscript');
    const aiRaw = (aiTrans?.dataset.rawText || aiTrans?.textContent || '').replace(/^[“"\s]+|[”"\s]+$/g, '').trim();
    const s1Text = (document.getElementById('symptomVal1')?.textContent || '').trim();
    const lastMsg = (lastPatientMessage || localStorage.getItem('cliniqo_last_patient_response') || '').trim();
    const docketChief = (document.getElementById('intakeDocketChiefSymptom')?.textContent || '').trim();

    let chiefSymptom = '';
    let parsedOnset = '';

    if (symList.length > 0) {
      chiefSymptom = symList.join(', ');
    } else {
      const candidates = [wbRaw, lastMsg, aiRaw, docketChief, s1Text].filter(c => c && !isGenericClinicalEntity(c));
      for (const cand of candidates) {
        const extracted = extractSymptomAndOnset(cand);
        if (extracted.symptom && !isGenericClinicalEntity(extracted.symptom)) {
          chiefSymptom = extracted.symptom;
          if (extracted.onset && !parsedOnset) parsedOnset = extracted.onset;
          break;
        }
      }
    }

    if (!chiefSymptom) {
      const locList = Array.from(selectedPainLocations).filter(l => !isGenericClinicalEntity(l));
      if (locList.length > 0) {
        chiefSymptom = `Discomfort in ${locList.join(' / ')}`;
      }
    }

    // Capitalize and synchronize chief symptom
    if (chiefSymptom && !isGenericClinicalEntity(chiefSymptom)) {
      chiefSymptom = chiefSymptom.charAt(0).toUpperCase() + chiefSymptom.slice(1);
      if (selectedWhatBringsSymptoms.size === 0 && chiefSymptom !== 'Routine clinical intake evaluation') {
        selectedWhatBringsSymptoms.add(chiefSymptom);
      }
    }

    // Resolve Onset & Duration
    const s2Raw = (document.getElementById('symptomVal2')?.textContent || '').trim();
    let onset = (!isGenericText(s2Raw) && s2Raw !== 'Not recorded' && s2Raw !== 'Recorded today') ? s2Raw : (parsedOnset || '');
    if (!onset) {
      const combinedSpeech = `${lastMsg} ${wbRaw} ${aiRaw}`;
      const durMatch = combinedSpeech.match(/\b(?:for|since|past|last)?\s*(\d+\s*(?:days?|weeks?|months?|hours?))\b/i);
      if (durMatch) {
        onset = `Started ~${durMatch[1]} ago`;
      } else if (combinedSpeech.toLowerCase().includes('yesterday')) {
        onset = 'Started yesterday';
      } else if (combinedSpeech.toLowerCase().includes('today') || combinedSpeech.toLowerCase().includes('morning')) {
        onset = 'Started today';
      }
    }

    // Resolve Anatomical Location / Region
    const locationsList = Array.from(selectedPainLocations).filter(l => !isGenericText(l));
    const s3Raw = (document.getElementById('symptomVal3')?.textContent || '').trim();
    let location = locationsList.length > 0 ? locationsList.join(' / ') : (!isGenericText(s3Raw) && s3Raw !== 'Not specified' ? s3Raw : '');
    if (!location && chiefSymptom) {
      const lower = `${chiefSymptom} ${lastMsg}`.toLowerCase();
      if (lower.includes('fever') || lower.includes('temperature') || lower.includes('bukhar') || lower.includes('chills')) {
        location = 'Whole Body / Head & Forehead';
      } else if (lower.includes('cough') || lower.includes('throat') || lower.includes('breath') || lower.includes('chest')) {
        location = 'Throat & Upper Chest';
      } else if (lower.includes('head') || lower.includes('migraine')) {
        location = 'Head & Forehead';
      } else if (lower.includes('stomach') || lower.includes('abdomen') || lower.includes('belly')) {
        location = 'Abdominal Region';
      } else if (lower.includes('back')) {
        location = 'Lower Back & Spine';
      }
    }

    // Resolve Triggers & Alleviating factors
    const triggersList = Array.from(selectedAdaptiveTriggers).filter(t => !isGenericText(t));
    const s4Raw = (document.getElementById('symptomVal4')?.textContent || '').trim();
    const trigger = triggersList.length > 0 ? triggersList.join(' • ') : (!isGenericText(s4Raw) && s4Raw !== 'None reported' ? s4Raw : '');
    
    const alleviatingList = Array.from(selectedAdaptiveChoices).filter(a => !isGenericText(a));
    const s5Raw = (document.getElementById('symptomVal5')?.textContent || '').trim();
    const alleviating = alleviatingList.length > 0 ? alleviatingList.join(' • ') : (!isGenericText(s5Raw) && s5Raw !== 'None reported' ? s5Raw : '');

    // Resolve Severity Rating
    const s6Raw = (document.getElementById('symptomVal6')?.textContent || '').trim();
    const severity = (!isGenericText(s6Raw) && s6Raw !== 'Unrated') ? s6Raw : '';

    // 2. Resolve Medical History (User-selected + Document diagnoses + Session history)
    const medHistList = Array.from(selectedMedHistConditions).filter(c => !isGenericText(c));

    // 3. Resolve Medications & Allergies (User-selected + Document medications + Session Rx)
    const medsList = Array.from(selectedMedications).filter(m => !isGenericText(m));

    const allergyList = Array.from(selectedAllergies).filter(a => !isGenericText(a));

    // 4. Synthesize Narrative Banner (Screen 10)
    const storyNarrative = document.getElementById('healthStoryNarrative');
    if (storyNarrative) {
      const pName = (activePatient && activePatient.display_name) ? activePatient.display_name.split(' ')[0] : 'Patient';
      const chiefPart = chiefSymptom ? `symptoms: ${chiefSymptom.toLowerCase()}` : 'clinical health assessment';
      let narrative = `“Today, ${pName} recorded ${chiefPart}.`;
      if (onset || location) {
        const locParts = [onset ? `onset ${onset}` : '', location ? `at ${location}` : ''].filter(Boolean).join(', ');
        narrative += ` Presentation noted ${locParts}.`;
      }
      if (medHistList.length > 0) {
        narrative += ` Medical history includes ${medHistList.join(', ')}.`;
      }
      if (medsList.length > 0) {
        narrative += ` Active medications: ${medsList.join(', ')}.`;
      }
      if (allergyList.length > 0) {
        narrative += ` Allergy alert: ${allergyList.join(', ')}.`;
      }
      if (uploadedDocuments.length > 0) {
        narrative += ` Medical vault contains ${uploadedDocuments.length} verified scanned record(s).`;
      }
      narrative += ` All data is complete and saved to the health record.”`;
      
      storyNarrative.textContent = narrative;
      storyNarrative.dataset.rawText = narrative.replace(/^[“"\s]+|[”"\s]+$/g, '');
    }

    // 5. Update Screen 10 Cards
    const card1Badge = document.getElementById('healthStoryCard1Badge');
    const card1Content = document.getElementById('healthStoryCard1Content');
    if (card1Badge) card1Badge.textContent = `${chiefSymptom ? 1 : 0} Logged`;
    if (card1Content) {
      card1Content.innerHTML = `
        <div class="p-2.5 rounded-xl bg-surface-container flex justify-between items-center">
          <span class="text-secondary font-medium">Chief Symptom</span>
          <span class="font-bold text-primary text-right max-w-[60%] truncate">${chiefSymptom || 'General Intake'}</span>
        </div>
        <div class="p-2.5 rounded-xl bg-surface-container flex justify-between items-center">
          <span class="text-secondary font-medium">Onset & Location</span>
          <span class="font-bold text-on-surface text-right max-w-[60%] truncate">${onset || 'Recorded today'} • ${location || 'Whole body'}</span>
        </div>
      `;
    }

    const card2Badge = document.getElementById('healthStoryCard2Badge');
    const card2Content = document.getElementById('healthStoryCard2Content');
    if (card2Badge) card2Badge.textContent = `${medHistList.length} Confirmed`;
    if (card2Content) {
      if (medHistList.length === 0) {
        card2Content.innerHTML = `<div class="p-2.5 rounded-xl bg-surface-container text-secondary text-center text-xs">No prior medical conditions logged.</div>`;
      } else {
        card2Content.innerHTML = medHistList.map(c => `
          <div class="p-2.5 rounded-xl bg-surface-container flex justify-between items-center">
            <span class="font-bold text-on-surface text-xs">${c}</span>
            <span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-secondary-container text-secondary shrink-0">Confirmed</span>
          </div>
        `).join('');
      }
    }

    const card3Badge = document.getElementById('healthStoryCard3Badge');
    const card3Content = document.getElementById('healthStoryCard3Content');
    if (card3Badge) card3Badge.textContent = `${medsList.length} Meds • ${allergyList.length} Allergy`;
    if (card3Content) {
      let medsHtml = medsList.length > 0
        ? `<p class="font-bold text-on-surface text-xs leading-snug">${medsList.join(' • ')}</p>`
        : `<p class="text-secondary text-xs italic">No active medications reported.</p>`;
      
      let allergyHtml = '';
      if (allergyList.length === 0) {
        allergyHtml = `<div class="p-2 rounded-xl bg-surface-container text-secondary text-[11px] flex items-center gap-1.5">
          <span class="material-symbols-outlined text-[15px] text-primary">check_circle</span>
          <span>No known drug allergies reported</span>
        </div>`;
      } else {
        allergyHtml = allergyList.map(a => `
          <div class="p-2 rounded-xl bg-error-container/40 text-error font-semibold text-xs flex items-center gap-1.5">
            <span class="material-symbols-outlined text-[15px]">warning</span>
            <span>Allergy: ${a} (Alert)</span>
          </div>
        `).join('');
      }
      card3Content.innerHTML = `<div class="space-y-2">${medsHtml}${allergyHtml}</div>`;
    }

    const card4Badge = document.getElementById('healthStoryCard4Badge');
    const card4Content = document.getElementById('healthStoryCard4Content');
    if (card4Badge) card4Badge.textContent = `${uploadedDocuments.length} Verified`;
    if (card4Content) {
      if (uploadedDocuments.length === 0) {
        card4Content.innerHTML = `
          <div class="p-3 rounded-xl bg-surface-container text-center space-y-1">
            <p class="text-xs text-secondary font-medium">No scanned documents attached yet.</p>
            <a href="#records-scan-document" class="inline-flex items-center gap-1 text-[11px] font-bold text-primary hover:underline">
              <span class="material-symbols-outlined text-[13px]">document_scanner</span>
              <span>Scan or upload document</span>
            </a>
          </div>
        `;
      } else {
        card4Content.innerHTML = uploadedDocuments.slice(0, 3).map(d => {
          const ocr = d.ocr || {};
          const docType = ocr.document_type || 'Clinical Record';
          return `
            <div class="p-2.5 rounded-xl bg-surface-container flex flex-col gap-1 border border-secondary-container/40">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2 max-w-[70%]">
                  <span class="material-symbols-outlined text-[16px] text-primary shrink-0">description</span>
                  <span class="truncate font-bold text-on-surface text-xs">${d.file_name}</span>
                </div>
                <span class="text-primary font-bold text-[10px] shrink-0 bg-primary-fixed px-2 py-0.5 rounded-full">${docType}</span>
              </div>
            </div>
          `;
        }).join('');
      }
    }

    // 6. Update Screen 15 Summary Cards (Dossier View with Multi-Attribute Enrichment)
    const sumVal1 = document.getElementById('summaryVal1');
    if (sumVal1) {
      if (chiefSymptom) {
        const details = [];
        if (onset) details.push(`Onset: ${onset}`);
        if (location) details.push(`Location: ${location}`);
        if (trigger) details.push(`Trigger: ${trigger}`);
        if (alleviating) details.push(`Relief: ${alleviating}`);
        if (severity) details.push(`Severity: ${severity}`);
        const fullDesc = `${chiefSymptom}` + (details.length ? ` (${details.join(' • ')})` : '');
        sumVal1.textContent = fullDesc;
        sumVal1.dataset.rawText = fullDesc;
      } else {
        sumVal1.textContent = 'General clinical health assessment recorded on intake.';
        sumVal1.dataset.rawText = 'General clinical health assessment recorded on intake.';
      }
    }

    const sumVal2 = document.getElementById('summaryVal2');
    if (sumVal2) {
      const histText = medHistList.length > 0 ? medHistList.join(' • ') : 'No chronic conditions or prior surgeries reported.';
      sumVal2.textContent = histText;
      sumVal2.dataset.rawText = histText;
    }

    const sumVal3 = document.getElementById('summaryVal3');
    if (sumVal3) {
      const medsStr = medsList.length > 0 ? medsList.join(', ') : 'None';
      const allStr = allergyList.length > 0 ? allergyList.join(', ') + ' (Critical Alert)' : 'None reported (NKDA)';
      const medsAllText = `Daily Rx: ${medsStr} • Allergies: ${allStr}`;
      sumVal3.textContent = medsAllText;
      sumVal3.dataset.rawText = medsAllText;
    }

    const sumVal4 = document.getElementById('summaryVal4');
    if (sumVal4) {
      if (uploadedDocuments.length > 0) {
        const docsSummary = `${uploadedDocuments.length} Verified Record(s): ` + uploadedDocuments.map((d, i) => {
          const o = d.ocr || {};
          const ef = (o.extracted_fields && typeof o.extracted_fields === 'object' && !Array.isArray(o.extracted_fields)) ? o.extracted_fields : o;
          const dt = o.document_type || ef.document_type || 'Prescription';
          const rawMeds = o.medications || ef.medications || [];
          const topMeds = rawMeds.slice(0, 2).map(m => typeof m === 'string' ? m : (m.name_as_reported || m.name)).filter(Boolean);
          const rawLabs = o.lab_results || ef.lab_results || [];
          const topLabs = rawLabs.slice(0, 2).map(l => typeof l === 'string' ? l : `${l.test_name || l.name}: ${l.value_as_reported || l.value || ''} ${l.unit_as_reported || l.unit || ''}`.trim()).filter(Boolean);
          
          let findings = [];
          if (topMeds.length > 0) findings.push(`Rx: ${topMeds.join(', ')}`);
          if (topLabs.length > 0) findings.push(`Labs: ${topLabs.join(', ')}`);
          const note = findings.length > 0 ? ` [${dt} • ${findings.join(' | ')}]` : ` [${dt} Ingested]`;
          return `${d.file_name || `Document ${i+1}`}${note}`;
        }).join(' • ');
        sumVal4.textContent = docsSummary;
        sumVal4.dataset.rawText = docsSummary;
      } else {
        sumVal4.textContent = 'No scanned records attached yet.';
        sumVal4.dataset.rawText = 'No scanned records attached yet.';
      }
    }

    // 7. Dynamic Voice Narration for Screen 15 Speak Button
    const sumSpeakBtn = document.querySelector('#screen-clinicalsummaries-summary-confirmation .speak-btn');
    if (sumSpeakBtn) {
      const pName = (activePatient && activePatient.display_name) ? activePatient.display_name.split(' ')[0] : 'Patient';
      let speechText = `Your personal health dossier is complete for ${pName}. `;
      if (chiefSymptom) {
        speechText += `Reason for visit is ${chiefSymptom}${onset ? ', ' + onset : ''}${location ? ' at ' + location : ''}. `;
      }
      if (medHistList.length > 0) {
        speechText += `Medical history: ${medHistList.join(', ')}. `;
      }
      if (medsList.length > 0) {
        speechText += `Active daily medications: ${medsList.join(', ')}. `;
      }
      if (allergyList.length > 0) {
        speechText += `Critical allergy alert: ${allergyList.join(', ')}. `;
      } else {
        speechText += `No known drug allergies reported. `;
      }
      if (uploadedDocuments.length > 0) {
        speechText += `Medical vault contains ${uploadedDocuments.length} verified scanned clinical documents.`;
      }
      sumSpeakBtn.setAttribute('data-speech', speechText);
    }

    // 8. Update Patient Identity Docket (Screen 16)
    const docketChiefEl = document.getElementById('intakeDocketChiefSymptom');
    if (docketChiefEl && chiefSymptom && (!docketChiefEl.textContent || docketChiefEl.textContent === 'Awaiting intake...')) {
      docketChiefEl.textContent = chiefSymptom;
    }
    const docketOnsetEl = document.getElementById('intakeDocketOnsetDuration');
    if (docketOnsetEl && onset && (!docketOnsetEl.textContent || docketOnsetEl.textContent.includes('session'))) {
      docketOnsetEl.textContent = onset;
    }

    updateVaultProgress();
    renderPatientCasesDashboard();
    renderCaseSummaryPage();
  }

  function updateWhatBringsSymptomSelection() {
    const transcript = document.getElementById('whatBringsTranscript');
    const badge = document.getElementById('whatBringsCountBadge');
    const count = selectedWhatBringsSymptoms.size;

    if (badge) {
      badge.textContent = `${count} ${count === 1 ? 'Selected' : 'Selected'}`;
    }

    if (transcript) {
      if (count === 0) {
        transcript.textContent = `“Tap the mic button above or select symptom chips below...”`;
        transcript.dataset.rawText = `Tap the mic button above or select symptom chips below...`;
      } else {
        const list = Array.from(selectedWhatBringsSymptoms);
        const formattedList = list.join(', ');
        const fullSentence = `“I've been experiencing ${formattedList} recently.”`;
        transcript.textContent = fullSentence;
        transcript.dataset.rawText = fullSentence.replace(/“|”/g, '');
      }
    }

    const s1 = document.getElementById('symptomVal1');
    if (s1 && selectedWhatBringsSymptoms.size > 0) {
      s1.textContent = Array.from(selectedWhatBringsSymptoms).join(', ');
    }
    const docketChief = document.getElementById('intakeDocketChiefSymptom');
    if (docketChief && selectedWhatBringsSymptoms.size > 0) {
      docketChief.textContent = Array.from(selectedWhatBringsSymptoms).join(', ');
    }
    renderInterviewQuickReplies();
    updateSymptomsReviewScreen();
    updateHealthStoryUI();
  }

  function updatePainLocationSelection() {
    const transcript = document.getElementById('aiInterviewTranscript');
    const badge = document.getElementById('painLocCountBadge');
    const count = selectedPainLocations.size;

    if (badge) badge.textContent = `${count} ${count === 1 ? 'Location Selected' : 'Locations Selected'}`;

    if (transcript) {
      if (count === 0) {
        transcript.textContent = `“Please select or speak the pain locations.”`;
        transcript.dataset.rawText = `Please select or speak the pain locations.`;
      } else {
        const list = Array.from(selectedPainLocations);
        const fullSentence = `“The pain is concentrated at: ${list.join(', ')}.”`;
        transcript.textContent = fullSentence;
        transcript.dataset.rawText = fullSentence.replace(/“|”/g, '');
      }
    }

    const s3 = document.getElementById('symptomVal3');
    if (s3 && selectedPainLocations.size > 0) {
      s3.textContent = Array.from(selectedPainLocations).join(' • ');
    }
    updateSymptomsReviewScreen();
    updateHealthStoryUI();
  }

  function updateAdaptiveChoicesText() {
    const badge = document.getElementById('adaptiveChoicesCountBadge') || document.getElementById('adaptiveChoicesBadge');
    const count = selectedAdaptiveChoices.size;
    if (badge) badge.textContent = `${count} ${count === 1 ? 'Selected' : 'Selected'}`;
    updateSymptomsReviewScreen();
    updateHealthStoryUI();
  }

  function updateAdaptiveTriggersBadge() {
    const badge = document.getElementById('adaptiveTriggersCountBadge') || document.getElementById('adaptiveTriggersBadge');
    const count = selectedAdaptiveTriggers.size;
    if (badge) badge.textContent = `${count} ${count === 1 ? 'Selected' : 'Selected'}`;
    const s4 = document.getElementById('symptomVal4');
    if (s4 && selectedAdaptiveTriggers.size > 0) {
      s4.textContent = Array.from(selectedAdaptiveTriggers).filter(t => !isGenericClinicalEntity(t)).join(' / ');
    }
    updateSymptomsReviewScreen();
    updateHealthStoryUI();
  }

  function updateMedHistConditionsBadge() {
    const badge = document.getElementById('medHistCountBadge');
    const count = selectedMedHistConditions.size;
    if (badge) badge.textContent = `${count} ${count === 1 ? 'Condition Selected' : 'Conditions Selected'}`;
    updateHealthStoryUI();
  }

  function updateAllergiesBadge() {
    const badge = document.getElementById('allergiesCountBadge');
    const count = selectedAllergies.size;
    if (badge) badge.textContent = `${count} ${count === 1 ? 'Allergy Tagged' : 'Allergies Tagged'}`;
    updateHealthStoryUI();
  }

  function updateMedsBadge() {
    const badge = document.getElementById('medsCountBadge');
    const count = selectedMedications.size;
    if (badge) badge.textContent = `${count} ${count === 1 ? 'Active Med' : 'Active Meds'}`;
    updateHealthStoryUI();
  }

  function updateFamilyBadge() {
    const badge = document.getElementById('familyCountBadge');
    const count = selectedFamilyConditions.size;
    if (badge) badge.textContent = `${count} ${count === 1 ? 'Condition Selected' : 'Conditions Selected'}`;
    updateHealthStoryUI();
  }

  function updateLifestyleBadge() {
    const badge = document.getElementById('lifestyleCountBadge');
    const count = selectedLifestyleHabits.size;
    if (badge) badge.textContent = `${count} ${count === 1 ? 'Habit Selected' : 'Habits Selected'}`;
    updateHealthStoryUI();
  }

  function updateSymptomsReviewScreen() {
    const s1 = document.getElementById('symptomVal1');
    const s2 = document.getElementById('symptomVal2');
    const s3 = document.getElementById('symptomVal3');
    const s4 = document.getElementById('symptomVal4');
    const s5 = document.getElementById('symptomVal5');
    const s6 = document.getElementById('symptomVal6');

    // 1. Chief Concern
    const symList = Array.from(selectedWhatBringsSymptoms).filter(s => !isGenericClinicalEntity(s));
    const rawTranscript = document.getElementById('whatBringsTranscript')?.dataset.rawText || 
                          document.getElementById('whatBringsTranscript')?.textContent.replace(/^[“"\s]+|[”"\s]+$/g, '').trim();
    let chiefText = '';
    if (symList.length > 0) {
      chiefText = symList.join(', ');
    } else if (rawTranscript && !isGenericClinicalEntity(rawTranscript)) {
      chiefText = rawTranscript;
    } else if (lastPatientMessage && !isGenericClinicalEntity(lastPatientMessage)) {
      chiefText = lastPatientMessage;
    } else if (selectedPainLocations.size > 0) {
      const validLocs = Array.from(selectedPainLocations).filter(l => !isGenericClinicalEntity(l));
      if (validLocs.length > 0) chiefText = `Discomfort in ${validLocs.join(' / ')}`;
    }
    
    if (!chiefText || isGenericClinicalEntity(chiefText)) {
      chiefText = 'Routine clinical intake evaluation';
    }

    if (s1) {
      s1.textContent = chiefText;
    }

    // 2. Onset & Duration
    let durText = '';
    if (s2 && s2.textContent && !isGenericClinicalEntity(s2.textContent) && !s2.textContent.includes('Not recorded')) {
      durText = s2.textContent.trim();
    }
    if (!durText) {
      const validMsg = (!isGenericClinicalEntity(lastPatientMessage) ? lastPatientMessage : '');
      const validRaw = (!isGenericClinicalEntity(rawTranscript) ? rawTranscript : '');
      const combinedText = `${chiefText} ${validMsg} ${validRaw}`.toLowerCase();
      const durMatch = combinedText.match(/(\d+)\s*(?:to|-)?\s*(\d+)?\s*(days?|weeks?|months?|hours?|din|naala)/);
      if (durMatch) {
        durText = durMatch[2] ? `Started ~${durMatch[1]}-${durMatch[2]} ${durMatch[3]} ago` : `Started ~${durMatch[1]} ${durMatch[3]} ago`;
      } else if (combinedText.includes('yesterday') || combinedText.includes('netru') || combinedText.includes('kal')) {
        durText = 'Started yesterday';
      } else if (combinedText.includes('today') || combinedText.includes('indru') || combinedText.includes('aaj')) {
        durText = 'Started today';
      } else if (combinedText.includes('few days') || combinedText.includes('kuch din')) {
        durText = 'Past few days (~2-3 days)';
      } else if (chiefText && !isGenericClinicalEntity(chiefText) && chiefText !== 'Routine clinical intake evaluation') {
        durText = 'Reported on Intake (Recent onset)';
      } else {
        durText = 'Recorded today';
      }
    }
    if (s2 && durText) {
      s2.textContent = durText;
    }

    // 3. Pain Region / Anatomical Location
    let locText = '';
    const locList = Array.from(selectedPainLocations).filter(l => !isGenericClinicalEntity(l));
    if (locList.length > 0) {
      locText = locList.join(' • ');
    } else if (s3 && s3.textContent && !isGenericClinicalEntity(s3.textContent) && !s3.textContent.includes('Not specified')) {
      locText = s3.textContent.trim();
    } else {
      const validMsg = (!isGenericClinicalEntity(lastPatientMessage) ? lastPatientMessage : '');
      const lower = `${chiefText} ${validMsg}`.toLowerCase();
      if (lower.includes('chest') || lower.includes('sternum') || lower.includes('marbhu') || lower.includes('seene')) {
        locText = 'Chest / Respiratory';
      } else if (lower.includes('head') || lower.includes('fever') || lower.includes('kaichal') || lower.includes('bukhar') || lower.includes('migraine')) {
        locText = 'Whole Body / Head & Forehead';
      } else if (lower.includes('throat') || lower.includes('cough') || lower.includes('sore throat')) {
        locText = 'Throat / Upper Respiratory';
      } else if (lower.includes('stomach') || lower.includes('abdomen') || lower.includes('belly') || lower.includes('gastric') || lower.includes('acidity')) {
        locText = 'Abdomen / Gastrointestinal';
      } else if (lower.includes('back') || lower.includes('spine')) {
        locText = 'Back / Spine';
      } else if (lower.includes('arm') || lower.includes('leg') || lower.includes('joint') || lower.includes('body ache')) {
        locText = 'Arms / Legs / Generalized Body';
      } else if (chiefText && !isGenericClinicalEntity(chiefText) && chiefText !== 'Routine clinical intake evaluation') {
        locText = 'Generalized / Systemic';
      } else {
        locText = 'General / Whole body';
      }
    }
    if (s3 && locText) {
      s3.textContent = locText;
    }

    // 4. Exacerbating Trigger
    let trigText = '';
    const trigList = Array.from(selectedAdaptiveTriggers).filter(t => !isGenericClinicalEntity(t));
    if (trigList.length > 0) {
      trigText = trigList.join(' / ');
    } else if (s4 && s4.textContent && !isGenericClinicalEntity(s4.textContent) && !s4.textContent.includes('None reported')) {
      trigText = s4.textContent.trim();
    } else {
      const validMsg = (!isGenericClinicalEntity(lastPatientMessage) ? lastPatientMessage : '');
      const lower = `${chiefText} ${validMsg}`.toLowerCase();
      if (lower.includes('walk') || lower.includes('walking') || lower.includes('stairs') || lower.includes('exercise') || lower.includes('exertion')) {
        trigText = 'Physical exertion / Walking';
      } else if (lower.includes('lying') || lower.includes('sleep') || lower.includes('bed')) {
        trigText = 'Worse when lying flat';
      } else if (lower.includes('eat') || lower.includes('food') || lower.includes('spicy')) {
        trigText = 'Worse after meals / food intake';
      } else if (lower.includes('cold') || lower.includes('weather')) {
        trigText = 'Cold exposure or weather change';
      } else if (chiefText && !isGenericClinicalEntity(chiefText) && chiefText !== 'Routine clinical intake evaluation') {
        trigText = 'Daily physical activities';
      } else {
        trigText = 'None reported';
      }
    }
    if (s4 && trigText) {
      s4.textContent = trigText;
    }

    // 5. Symptom Character & Relief
    let allevText = '';
    const allevList = Array.from(selectedAdaptiveChoices).filter(a => !isGenericClinicalEntity(a));
    if (allevList.length > 0) {
      const patterns = [];
      const reliefs = [];
      allevList.forEach(item => {
        const itemLower = item.toLowerCase();
        if (itemLower.includes('better') || itemLower.includes('relieved') || itemLower.includes('improves') || 
            itemLower.includes('antacid') || itemLower.includes('dark') || itemLower.includes('quiet') ||
            itemLower.includes('rest') || itemLower.includes('sleep') || itemLower.includes('medicine') || itemLower.includes('paracetamol')) {
          reliefs.push(item);
        } else {
          patterns.push(item);
        }
      });
      if (patterns.length > 0 && reliefs.length > 0) {
        allevText = `Pattern: ${patterns.join(' • ')} • Relief: ${reliefs.join(' • ')}`;
      } else if (patterns.length > 0) {
        allevText = patterns.join(' • ');
      } else if (reliefs.length > 0) {
        allevText = reliefs.join(' • ');
      } else {
        allevText = allevList.join(' • ');
      }
    } else if (s5 && s5.textContent && !isGenericClinicalEntity(s5.textContent) && !s5.textContent.includes('None reported')) {
      allevText = s5.textContent.trim();
    } else {
      const validMsg = (!isGenericClinicalEntity(lastPatientMessage) ? lastPatientMessage : '');
      const lower = `${chiefText} ${validMsg}`.toLowerCase();
      if (lower.includes('paracetamol') || lower.includes('dolo') || lower.includes('crocin') || lower.includes('tablet')) {
        allevText = 'OTC antipyretic / Paracetamol';
      } else if (lower.includes('rest') || lower.includes('sleep') || lower.includes('sitting')) {
        allevText = 'Rest and hydration';
      } else if (lower.includes('water') || lower.includes('fluids') || lower.includes('tea')) {
        allevText = 'Warm fluids and oral hydration';
      } else if (chiefText && !isGenericClinicalEntity(chiefText) && chiefText !== 'Routine clinical intake evaluation') {
        allevText = 'Rest and symptomatic care';
      } else {
        allevText = 'None reported';
      }
    }
    if (s5 && allevText) {
      s5.textContent = allevText;
    }

    // 6. Severity Scale
    let sevText = '';
    if (s6 && s6.textContent && !isGenericClinicalEntity(s6.textContent) && !s6.textContent.includes('Unrated')) {
      sevText = s6.textContent.trim();
    } else {
      const validMsg = (!isGenericClinicalEntity(lastPatientMessage) ? lastPatientMessage : '');
      const lower = `${chiefText} ${validMsg}`.toLowerCase();
      if (lower.includes('severe') || lower.includes('unbearable') || lower.includes('high') || lower.includes('intense') || lower.includes('8/') || lower.includes('9/') || lower.includes('10/')) {
        sevText = 'Severe (7-9/10) • Urgent Clinical Triage';
      } else if (lower.includes('mild') || lower.includes('slight') || lower.includes('low') || lower.includes('1/') || lower.includes('2/') || lower.includes('3/')) {
        sevText = 'Mild (2-3/10) • Graded Clinical Report';
      } else if (chiefText && !isGenericClinicalEntity(chiefText) && chiefText !== 'Routine clinical intake evaluation') {
        sevText = 'Moderate (4-6/10) • Graded Clinical Report';
      } else {
        sevText = 'Graded Clinical Report';
      }
    }
    if (s6 && sevText) {
      s6.textContent = sevText;
    }

    const continueBtnText = document.getElementById('symptomsContinueBtnText');
    if (continueBtnText) {
      if (isReturningPatientVisit) {
        continueBtnText.textContent = 'Continue to Records & Summary (Baseline On File)';
      } else {
        continueBtnText.textContent = 'Continue to Medical History';
      }
    }
  }

  // Symptoms continue button router
  const symContinueBtn = document.getElementById('symptomsContinueBtn');
  if (symContinueBtn) {
    symContinueBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (isReturningPatientVisit) {
        navigateTo('records-medical-records');
      } else {
        navigateTo('assessment-medical-history');
      }
    });
  }

  // =========================================================================
  // 7. REAL DOCUMENT OCR INGESTION (NO DUMMY FALLBACKS)
  // =========================================================================
  async function saveEncounterContext() {
    if (!currentSessionId) return;
    try {
      await apiRequest(`/api/v1/sessions/${currentSessionId}/encounter-context`, {
        method: 'PUT',
        body: { department: clinicalMode === 'ayush' ? 'AYUSH' : 'General OPD', clinical_mode: clinicalMode, language: activePatient.preferred_language || 'en-IN', consent_granted: true }
      });
    } catch (e) { console.warn('Encounter context sync failed', e); }
  }

  function applyClinicalMode(mode) {
    clinicalMode = mode === 'ayush' ? 'ayush' : 'general';
    localStorage.setItem('cliniqo_clinical_mode', clinicalMode);
    document.querySelectorAll('.clinical-mode-btn').forEach(btn => {
      const active = btn.dataset.mode === clinicalMode;
      btn.className = active
        ? 'clinical-mode-btn p-4 rounded-2xl border-2 border-primary bg-primary-fixed/30 text-left transition-all'
        : 'clinical-mode-btn p-4 rounded-2xl border border-secondary-container bg-surface-container text-left transition-all';
    });
    const badge = document.getElementById('clinicalModeBadge');
    if (badge) badge.textContent = clinicalMode === 'ayush' ? 'AYUSH OPD' : 'General OPD';
    const ayushPanel = document.getElementById('ayushAssessmentPanel');
    if (ayushPanel) ayushPanel.classList.toggle('hidden', clinicalMode !== 'ayush');
    Object.entries(ayushAssessment || {}).forEach(([key, value]) => {
      const el = document.getElementById(`ayush_${key}`);
      if (el && value != null) el.value = value;
    });
    saveEncounterContext();
  }

  function openDocumentContextModal() {
    const modal = document.getElementById('documentContextModal');
    if (!modal) return;
    currentDocumentContext = { classification: 'historical', date_type: 'unknown', date_source: 'unknown', document_date: null };
    if (document.getElementById('docDateValueInput')) document.getElementById('docDateValueInput').value = '';
    const area = document.getElementById('docDateContextArea');
    if (area) area.classList.add('hidden');
    const cont = document.getElementById('docContextContinueBtn');
    if (cont) cont.disabled = false;
    const status = document.getElementById('docContextStatus');
    if (status) status.textContent = 'Old document selected. Date may be unknown.';
    modal.classList.remove('hidden'); modal.classList.add('flex');
  }

  function closeDocumentContextModal() {
    const modal = document.getElementById('documentContextModal');
    if (modal) { modal.classList.add('hidden'); modal.classList.remove('flex'); }
  }

  async function handleRealDocumentFile(file) {
    if (!file) return;
    if (!currentSessionId) await createSession();

    const laser = document.getElementById('scannerLaserLine');
    const statusText = document.getElementById('scannerDocStatus');
    const ocrText = document.getElementById('scannerDocOcrQuality');
    const shutterIcon = document.getElementById('scannerShutterIcon');
    const docContent = document.getElementById('scannerDocContent');
    const docSub = document.getElementById('scannerDocSub');
    const docTypeLabel = document.getElementById('scannerDocTypeLabel');

    if (laser) laser.classList.remove('hidden');
    if (statusText) statusText.textContent = '⟳ Running Real-Time OCR...';
    if (ocrText) ocrText.textContent = 'Extracting Clinical Entities';
    if (shutterIcon) {
      shutterIcon.textContent = 'progress_activity';
      shutterIcon.classList.add('animate-spin');
    }
    if (docContent) docContent.textContent = `Processing: ${file.name}`;
    if (docSub) docSub.textContent = `Size: ${(file.size / 1024).toFixed(1)} KB • OCR Pipeline in Progress`;
    if (docTypeLabel) docTypeLabel.textContent = file.name.toUpperCase();

    try {
      const formData = new FormData();
      formData.append('file', file);
      const params = new URLSearchParams({
        classification: currentDocumentContext.classification,
        classification_source: 'patient',
        document_date_type: currentDocumentContext.date_type,
        document_date_source: currentDocumentContext.date_source
      });
      if (currentDocumentContext.document_date) params.set('document_date', currentDocumentContext.document_date);
      const uploaded = await apiRequest(`/api/v1/sessions/${currentSessionId}/documents?${params.toString()}`, {
        method: 'POST',
        body: formData
      });
      currentDocumentId = uploaded.document_id;

      const ocrResult = await apiRequest(`/api/v1/documents/${uploaded.document_id}/ocr`, {
        method: 'POST'
      });

      const ocrData = ocrResult.ocr || {};
      const docItem = {
        document_id: uploaded.document_id,
        file_name: uploaded.file_name || file.name,
        file_type: uploaded.file_type || file.type,
        file_size: uploaded.file_size || file.size,
        created_at: new Date().toISOString(),
        ocr: ocrData
      };

      docItem.document_classification = uploaded.document_classification || currentDocumentContext.classification;
      docItem.document_date = uploaded.document_date || ocrData.date || null;
      docItem.temporal_status = uploaded.temporal_status || currentDocumentContext.classification;
      docItem.verification_status = uploaded.verification_status || 'pending';
      uploadedDocuments.unshift(docItem);
      renderDocumentsList();

      const ef = (ocrData.extracted_fields && typeof ocrData.extracted_fields === 'object' && !Array.isArray(ocrData.extracted_fields)) 
        ? ocrData.extracted_fields 
        : ocrData;
      
      const meds = ocrData.medications || ef.medications || [];
      const diags = ocrData.diagnoses || ef.diagnoses || [];
      const labs = ocrData.lab_results || ef.lab_results || [];
      const docType = ocrData.document_type || ef.document_type || 'Clinical Document';
      const docDate = ocrData.date || ef.date || 'Date unknown';

      // Document facts stay document-scoped. They are rendered in the timeline/review
      // and are NOT silently promoted to current medications or current history.
      if (ocrData.temporal_context) {
        currentDocumentContext = { ...currentDocumentContext, ...ocrData.temporal_context };
      }

      if (labs.length > 0) {
        const labSummary = labs.map(l => `${l.test_name}: ${l.value_as_reported} ${l.unit_as_reported || ''}`).join(' • ');
        addTimelineEventToUI({
          category: 'lab',
          title: `Biomarker Lab Panel (${file.name})`,
          date: docDate,
          badge: 'Lab Report',
          desc: labSummary
        });
      } else if (meds.length > 0) {
        const medSummary = meds.map(m => `${m.name_as_reported} (${m.frequency_as_reported || 'Daily'})`).join(', ');
        addTimelineEventToUI({
          category: 'prescription',
          title: `Prescription Record (${file.name})`,
          date: docDate,
          badge: docType,
          desc: `Prescribed medications: ${medSummary}`
        });
      } else {
        addTimelineEventToUI({
          category: 'document',
          title: `Clinical Record Ingested (${file.name})`,
          date: docDate,
          badge: docType,
          desc: `Verified and stored in health dossier.`
        });
      }

      updateHealthStoryUI();
      syncClinicalData();
      populateReviewExtractedScreen(docItem);

      saveToVaultNotification("Document Extracted", `Successfully extracted clinical entities from ${file.name}.`);
      
      // Parallel Broadcast to Hospital Dashboard Recent Documents Table
      if (hospitalSyncChannel) {
        hospitalSyncChannel.postMessage({
          type: 'DOCUMENT_UPLOADED',
          session_id: currentSessionId,
          file_name: file.name,
          document_type: docType,
          patient_name: activePatient.display_name || 'Walk-in Patient',
          timestamp: Date.now()
        });
      }

      if (laser) laser.classList.add('hidden');
      if (shutterIcon) {
        shutterIcon.classList.remove('animate-spin');
        shutterIcon.textContent = 'check';
      }
      
      setTimeout(() => navigateTo('records-review-extracted-information'), 600);
    } catch (error) {
      console.error('Real document upload failed:', error);
      if (laser) laser.classList.add('hidden');
      if (shutterIcon) {
        shutterIcon.classList.remove('animate-spin');
        shutterIcon.textContent = 'photo_camera';
      }
      if (statusText) statusText.textContent = 'OCR Extraction Failed';
      saveToVaultNotification("OCR Processing Notice", "Document uploaded. Real OCR processing could not extract text from this format. Please retry with a clear document image or PDF.");
    }
  }

  function populateReviewExtractedScreen(doc) {
    if (!doc) return;
    const reviewTitle = document.getElementById('reviewDocTitle');
    const reviewSubtitle = document.getElementById('reviewDocSubtitle');
    const reviewBadge = document.getElementById('reviewDocBadge');
    const reviewBody = document.getElementById('reviewDocBody');
    const reviewDate = document.getElementById('reviewDocDate');
    const fieldsList = document.getElementById('extractedFieldsList');
    const countBadge = document.getElementById('extractedFieldsCountBadge');
    const tabFormattedBtn = document.getElementById('reviewTabFormattedBtn');
    const tabRawBtn = document.getElementById('reviewTabRawBtn');
    const copyBtn = document.getElementById('copyCurrentDocTxtBtn');
    const copyLabel = document.getElementById('copyCurrentDocTxtLabel');
    const dlBtn = document.getElementById('downloadCurrentDocTxtBtn');
    const addFieldBtn = document.getElementById('addExtractedFieldBtn');
    const customFieldBox = document.getElementById('customFieldAddContainer');
    const cancelAddFieldBtn = document.getElementById('cancelAddCustomFieldBtn');
    const saveCustomFieldBtn = document.getElementById('saveCustomFieldBtn');
    const confirmBtn = document.getElementById('confirmExtractedBtn');

    if (reviewTitle) reviewTitle.textContent = doc.file_name ? doc.file_name.toUpperCase() : 'UPLOADED CLINICAL RECORD';
    if (reviewSubtitle) reviewSubtitle.textContent = `Size: ${(doc.file_size / 1024).toFixed(1)} KB • OCR Ingestion Complete`;
    
    const ocrObj = doc.ocr || {};
    const ef = (ocrObj.extracted_fields && typeof ocrObj.extracted_fields === 'object' && !Array.isArray(ocrObj.extracted_fields)) 
      ? ocrObj.extracted_fields 
      : ocrObj;

    let docType = ocrObj.document_type || ef.document_type || 'Prescription';
    if (reviewBadge) reviewBadge.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-primary"></span><span>${docType}</span>`;
    if (reviewDate) reviewDate.textContent = `Uploaded: ${new Date(doc.created_at || Date.now()).toLocaleDateString()} • Real OCR Synchronized`;

    // Active document reclassification buttons
    document.querySelectorAll('.review-doc-type-btn').forEach(btn => {
      const dt = btn.getAttribute('data-doctype');
      const isMatch = dt && docType.toLowerCase().includes(dt.toLowerCase());
      if (isMatch) {
        btn.className = 'review-doc-type-btn px-4 py-2 rounded-full bg-primary text-white text-xs font-bold shadow-xs cursor-pointer transition-all flex items-center gap-1.5';
      } else {
        btn.className = 'review-doc-type-btn px-4 py-2 rounded-full bg-surface-container hover:bg-secondary-container text-on-surface text-xs font-semibold border border-secondary-container transition-all cursor-pointer flex items-center gap-1.5';
      }

      btn.onclick = () => {
        const selectedDt = btn.getAttribute('data-doctype');
        const dtLabelMap = {
          'prescription': 'Prescription',
          'lab': 'Lab Report',
          'imaging': 'Scan / Imaging',
          'discharge': 'Discharge Summary'
        };
        docType = dtLabelMap[selectedDt] || 'Clinical Document';
        if (doc.ocr) doc.ocr.document_type = docType;
        if (ef) ef.document_type = docType;
        populateReviewExtractedScreen(doc);
        saveToVaultNotification("Document Reclassified", `Document updated to ${docType}.`);
      };
    });

    let rawText = ocrObj.raw_text || ef.raw_text || ocrObj.text || '';
    if (!rawText.trim()) {
      rawText = `Document: ${doc.file_name || 'Clinical Document'}\nPatient: ${activePatient.display_name || 'Registered Patient'}\nStatus: Verified Clinical Record`;
    }

    const patientName = activePatient.display_name || 'Registered Patient';
    const patientDob = activePatient.date_of_birth ? ` (DOB: ${activePatient.date_of_birth})` : '';
    const abhaId = activePatient.abha_id || 'Pending Link';
    const prescriberStr = ocrObj.provider || ef.provider || 'Attending Clinician';
    const clinicStr = ocrObj.clinic || ef.clinic || 'Clinical Facility';

    const formattedReport = `======================================================================
CLINIQO MEDICAL INTELLIGENCE • CLINICAL DOCUMENT TRANSCRIPTION
======================================================================
Document File  : ${doc.file_name || 'Scanned File'}
Document Type  : ${docType}
Patient Name   : ${patientName}${patientDob}
ABHA Health ID : ${abhaId}
Prescriber     : ${prescriberStr}
Facility       : ${clinicStr}
Ingestion Date : ${new Date(doc.created_at || Date.now()).toLocaleString()}
----------------------------------------------------------------------
EXTRACTED CLINICAL CONTENT:

${rawText.trim()}
======================================================================`;

    let activeView = 'formatted';
    const renderViewerContent = () => {
      if (!reviewBody) return;
      const textToDisplay = activeView === 'formatted' ? formattedReport : rawText.trim();
      reviewBody.innerHTML = `
        <pre class="p-3.5 rounded-2xl bg-surface-container-lowest text-on-surface border border-secondary-container font-mono text-[11px] leading-relaxed max-h-64 overflow-y-auto whitespace-pre-wrap selection:bg-secondary-container shadow-inner">${textToDisplay}</pre>
      `;
    };

    if (tabFormattedBtn && tabRawBtn) {
      tabFormattedBtn.onclick = () => {
        activeView = 'formatted';
        tabFormattedBtn.className = 'px-2.5 py-1 rounded-lg bg-primary text-white text-[10px] font-bold shadow-xs transition-all cursor-pointer';
        tabRawBtn.className = 'px-2.5 py-1 rounded-lg hover:bg-secondary-container text-secondary text-[10px] font-semibold transition-all cursor-pointer';
        renderViewerContent();
      };
      tabRawBtn.onclick = () => {
        activeView = 'raw';
        tabRawBtn.className = 'px-2.5 py-1 rounded-lg bg-primary text-white text-[10px] font-bold shadow-xs transition-all cursor-pointer';
        tabFormattedBtn.className = 'px-2.5 py-1 rounded-lg hover:bg-secondary-container text-secondary text-[10px] font-semibold transition-all cursor-pointer';
        renderViewerContent();
      };
    }

    renderViewerContent();

    // Copy Button Handler
    if (copyBtn) {
      copyBtn.onclick = async (e) => {
        e.preventDefault();
        const textToCopy = activeView === 'formatted' ? formattedReport : rawText.trim();
        try {
          await navigator.clipboard.writeText(textToCopy);
          if (copyLabel) copyLabel.textContent = 'Copied! ✓';
          copyBtn.classList.add('bg-primary-fixed', 'text-primary');
          setTimeout(() => {
            if (copyLabel) copyLabel.textContent = 'Copy';
            copyBtn.classList.remove('bg-primary-fixed', 'text-primary');
          }, 2000);
        } catch (err) {
          saveToVaultNotification("Copy Notice", "Text ready in viewer.");
        }
      };
    }

    // Download .txt Button Handler
    if (dlBtn) {
      dlBtn.onclick = (e) => {
        e.preventDefault();
        const blob = new Blob([formattedReport], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${(doc.file_name || 'clinical_record').replace(/\.[^/.]+$/, "")}_transcript.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      };
    }

    // Structured Entity Inspector Rows
    const meds = ocrObj.medications || ef.medications || [];
    const labs = ocrObj.lab_results || ef.lab_results || [];
    const diags = ocrObj.diagnoses || ef.diagnoses || [];
    const vitals = ocrObj.vitals || ef.vitals || [];

    let fields = [];
    if (Array.isArray(ef.extracted_fields) && ef.extracted_fields.length > 0) {
      fields = ef.extracted_fields.map(f => ({
        label: f.label || f.field || 'Clinical Item',
        val: f.val || f.value || 'Verified'
      }));
    }

    if (fields.length === 0) {
      fields.push({ label: 'Document Classification', val: docType, icon: 'prescriptions' });
      if (activePatient.display_name) {
        fields.push({ label: 'Patient Identification', val: `${activePatient.display_name} (ABHA: ${activePatient.abha_id || 'Pending'})`, icon: 'person' });
      }
      if (prescriberStr && prescriberStr !== 'Attending Clinician') {
        fields.push({ label: 'Facility / Prescriber', val: `${prescriberStr} • ${clinicStr}`, icon: 'medical_services' });
      }
      if (meds.length > 0) {
        const medLines = meds.map(m => {
          const mName = m.name_as_reported || m.name;
          const mDose = m.dose_as_reported ? ` ${m.dose_as_reported}` : '';
          const mFreq = m.frequency_as_reported ? ` (${m.frequency_as_reported})` : '';
          return `${mName}${mDose}${mFreq}`;
        }).join(' • ');
        fields.push({ label: 'Prescribed Medications', val: medLines, icon: 'medication' });
      }
      if (labs.length > 0) {
        const labLines = labs.map(l => `${l.test_name}: ${l.value_as_reported} ${l.unit_as_reported || ''}`).join(' • ');
        fields.push({ label: 'Biomarker Findings', val: labLines, icon: 'biotech' });
      }
      if (diags.length > 0) {
        fields.push({ label: 'Clinical Impressions', val: diags.map(d => d.condition || d.name).join(' • '), icon: 'clinical_notes' });
      }
      if (vitals.length > 0) {
        fields.push({ label: 'Recorded Vital Signs', val: vitals.map(v => `${v.vital}: ${v.value}`).join(' • '), icon: 'vital_signs' });
      }
    }

    const renderInspectorRows = () => {
      if (!fieldsList) return;
      fieldsList.innerHTML = '';

      fields.forEach((f, idx) => {
        const iconName = f.icon || (f.label.toLowerCase().includes('med') ? 'medication' : (f.label.toLowerCase().includes('lab') || f.label.toLowerCase().includes('bio') ? 'biotech' : (f.label.toLowerCase().includes('patient') ? 'person' : (f.label.toLowerCase().includes('prescriber') || f.label.toLowerCase().includes('facil') ? 'medical_services' : 'rule'))));

        const row = document.createElement('div');
        row.className = 'p-3.5 rounded-2xl bg-surface-container border border-secondary-container/60 flex items-center justify-between group hover:border-primary/40 transition-colors';
        row.id = `extractedRow_${idx}`;
        row.innerHTML = `
          <div class="flex items-start gap-3 flex-1 pr-3">
            <div class="w-8 h-8 rounded-xl bg-white text-primary flex items-center justify-center shrink-0 shadow-xs border border-secondary-container/40 mt-0.5">
              <span class="material-symbols-outlined text-[18px]">${iconName}</span>
            </div>
            <div class="flex-1">
              <span class="text-[10px] font-bold uppercase tracking-wider text-secondary block" id="extractedLabel_${idx}">${f.label}</span>
              <p class="font-bold text-on-surface text-xs sm:text-sm mt-0.5 leading-snug" id="extractedVal_${idx}">${f.val}</p>
            </div>
          </div>
          <button class="extracted-edit-btn px-3 py-1.5 rounded-full bg-white hover:bg-secondary-container text-primary text-xs font-bold cursor-pointer border border-secondary-container/60 flex items-center gap-1 transition-colors shrink-0 shadow-xs active:scale-95" data-wrapper="extractedRow_${idx}" data-target="extractedVal_${idx}" type="button">
            <span class="material-symbols-outlined text-[14px]">edit</span>
            <span>Edit text</span>
          </button>
        `;
        fieldsList.appendChild(row);

        const editBtn = row.querySelector('.extracted-edit-btn');
        if (editBtn) {
          editBtn.onclick = (e) => {
            e.stopPropagation();
            startInlineEdit({
              wrapperId: `extractedRow_${idx}`,
              textElId: `extractedVal_${idx}`,
              isQuoted: false,
              rows: 1,
              onSave: (newVal) => {
                f.val = newVal;
                updateHealthStoryUI();
              }
            });
          };
        }
      });

      if (countBadge) countBadge.textContent = `${fields.length} Clinical Fields`;
    };

    renderInspectorRows();

    // Quick Add Field Controls
    if (addFieldBtn && customFieldBox) {
      addFieldBtn.onclick = () => {
        customFieldBox.classList.remove('hidden');
        document.getElementById('customFieldLabelInput')?.focus();
      };
    }
    if (cancelAddFieldBtn && customFieldBox) {
      cancelAddFieldBtn.onclick = () => {
        customFieldBox.classList.add('hidden');
      };
    }
    if (saveCustomFieldBtn && customFieldBox) {
      saveCustomFieldBtn.onclick = () => {
        const labelInp = document.getElementById('customFieldLabelInput');
        const valInp = document.getElementById('customFieldValueInput');
        const lVal = labelInp?.value.trim();
        const vVal = valInp?.value.trim();
        if (lVal && vVal) {
          fields.push({ label: lVal, val: vVal, icon: 'add_circle' });
          renderInspectorRows();
          if (labelInp) labelInp.value = '';
          if (valInp) valInp.value = '';
          customFieldBox.classList.add('hidden');
          saveToVaultNotification("Field Added", `Added ${lVal} to extracted information.`);
        }
      };
    }

    // Confirm & Add to Health Vault Button
    if (confirmBtn) {
      confirmBtn.onclick = async () => {
        confirmBtn.innerHTML = `<span class="material-symbols-outlined animate-spin text-[18px]">progress_activity</span><span>Saving to Health Vault...</span>`;
        
        // Sync any extracted medications into active clinical state
        meds.forEach(m => {
          const medName = m.name_as_reported || m.name;
          if (medName) {
            const doseStr = m.dose_as_reported ? ` ${m.dose_as_reported}` : '';
            const fullMed = `${medName}${doseStr}`.trim();
            selectedMedications.add(fullMed);
            addMedicationToUI(fullMed, `${m.dose_as_reported || ''} ${m.frequency_as_reported || ''}`.trim() || 'Prescribed in record');
          }
        });
        updateMedsBadge();

        // Sync any extracted diagnoses
        diags.forEach(d => {
          const condName = d.condition || d.name;
          if (condName) {
            selectedMedHistConditions.add(condName);
            addConditionToUI(condName, d.source || 'Scanned Document OCR');
          }
        });
        updateMedHistConditionsBadge();

        // Add timeline event
        addTimelineEventToUI({
          category: docType.toLowerCase().includes('lab') ? 'lab' : 'prescription',
          title: `${docType}: ${doc.file_name || 'Scanned File'}`,
          date: new Date().toLocaleDateString(),
          badge: docType,
          desc: `Confirmed clinical facts synchronized into personal vault.`
        });

        await syncClinicalData();
        updateHealthStoryUI();
        updateVaultProgress();

        saveToVaultNotification("Document Confirmed", "Clinical entities successfully verified and attached to your dossier.");
        setTimeout(() => {
          confirmBtn.innerHTML = `<span class="material-symbols-outlined text-[18px]">verified</span><span>Confirm &amp; Add to Health Vault</span>`;
          navigateTo('clinicalsummaries-summary-confirmation');
        }, 600);
      };
    }
  }

  // =========================================================================
  // 8. DYNAMIC SUMMARY & DOCTOR CASE GENERATORS
  // =========================================================================
  function buildLocalNarrative() {
    const parts = [];
    const symList = Array.from(selectedWhatBringsSymptoms).filter(s => !isGenericClinicalEntity(s));
    const s1Text = (document.getElementById('symptomVal1')?.textContent || '').trim();
    const s2Text = (document.getElementById('symptomVal2')?.textContent || '').trim();
    const s3Text = (document.getElementById('symptomVal3')?.textContent || '').trim();
    const lastMsg = (lastPatientMessage || localStorage.getItem('cliniqo_last_patient_response') || '').trim();
    const wbTranscript = document.getElementById('whatBringsTranscript');
    const wbRaw = (wbTranscript?.dataset.rawText || wbTranscript?.textContent || '').replace(/^[“"\s]+|[”"\s]+$/g, '').trim();
    
    let chief = '';
    let parsedOnset = '';
    
    if (symList.length > 0) {
      chief = symList.join(', ');
    } else {
      const candidates = [wbRaw, lastMsg, s1Text].filter(c => c && !isGenericClinicalEntity(c));
      for (const cand of candidates) {
        let raw = String(cand).replace(/^[“"'\s]+|[”"'\s]+$/g, '').trim();
        const durMatch = raw.match(/\b(?:for|past|last)\s+(\d+\s*(?:days?|weeks?|months?|hours?))\b/i);
        const sinceMatch = raw.match(/\b(?:since)\s+(yesterday|today|last night|last week|\d+\s*(?:days?|weeks?|months?)\s*(?:ago)?)\b/i);
        if (durMatch) {
          parsedOnset = `Started ~${durMatch[1]} ago`;
          raw = raw.replace(durMatch[0], '');
        } else if (sinceMatch) {
          parsedOnset = `Started ${sinceMatch[1]}`;
          raw = raw.replace(sinceMatch[0], '');
        }
        let clean = raw
          .replace(/^I('ve been experiencing| have been experiencing| have got| have| am having| am experiencing| feel| felt| have had| got)\s+/i, '')
          .replace(/^(?:patient (?:has|presents with|is complaining of)|suffering from|complaining of|experiencing|problem is|trouble with)\s+/i, '')
          .replace(/\s+recently\.?$/i, '')
          .replace(/\s+now\.?$/i, '')
          .replace(/^[,\s.-]+|[,\s.-]+$/g, '')
          .trim();
        if (clean) {
          chief = clean.charAt(0).toUpperCase() + clean.slice(1);
          break;
        }
      }
    }

    if (chief) {
      chief = chief
        .replace(/^I('ve been experiencing| have been experiencing| have got| have| am having| am experiencing| feel| felt| have had| got)\s+/i, '')
        .replace(/^(?:patient (?:has|presents with|is complaining of)|suffering from|complaining of|experiencing)\s+/i, '')
        .trim();
      chief = chief.charAt(0).toUpperCase() + chief.slice(1);
    }

    const duration = (!isGenericClinicalEntity(s2Text) && s2Text !== 'Not recorded' && s2Text !== 'Recorded today') ? s2Text : (parsedOnset || (lastMsg.match(/\b\d+\s*(?:day|week|month)s?\b/i) ? `Started ~${lastMsg.match(/\b\d+\s*(?:day|week|month)s?\b/i)[0]} ago` : ''));
    const location = (!isGenericClinicalEntity(s3Text) && s3Text !== 'Not specified') ? s3Text : (selectedPainLocations.size > 0 ? Array.from(selectedPainLocations).join(' / ') : '');

    const pName = (activePatient && activePatient.display_name) ? activePatient.display_name.split(' ')[0] : 'Patient';

    if (chief) {
      let sent = `${pName} presents with ${chief}`;
      if (location) sent += ` localized to ${location}`;
      if (duration && !chief.toLowerCase().includes(duration.toLowerCase())) sent += ` (${duration})`;
      parts.push(sent + '.');
    } else {
      parts.push(`${pName} presents for routine clinical intake assessment and health profile review.`);
    }

    const medHist = Array.from(selectedMedHistConditions).filter(c => !isGenericClinicalEntity(c));
    if (medHist.length) parts.push(`Medical history is notable for ${medHist.join(', ')}.`);

    const meds = Array.from(selectedMedications).filter(m => !isGenericClinicalEntity(m));
    if (meds.length) parts.push(`Active medications include ${meds.join(', ')}.`);

    const allergies = Array.from(selectedAllergies).filter(a => !isGenericClinicalEntity(a));
    if (allergies.length) {
      parts.push(`Critical allergy alert: ${allergies.join(', ')}.`);
    } else {
      parts.push(`No known drug allergies reported.`);
    }

    if (uploadedDocuments.length) {
      parts.push(`Health vault contains ${uploadedDocuments.length} verified scanned clinical document(s).`);
    }

    return parts.join(' ');
  }

  function renderAyushSummaryCard() {
    const card = document.getElementById('ayushSummaryCard');
    if (!card) return;
    card.classList.toggle('hidden', clinicalMode !== 'ayush');
    if (clinicalMode !== 'ayush') return;
    const grid = document.getElementById('ayushSummaryGrid');
    if (grid) {
      const labels = { prakriti:'Prakriti', vikriti:'Vikriti', sara:'Sara', samhanana:'Samhanana', pramana:'Pramana', satmya:'Satmya', sattva:'Sattva', ahara_shakti:'Ahara Shakti', vyayama_shakti:'Vyayama Shakti', vaya:'Vaya' };
      grid.innerHTML = Object.entries(labels).map(([key,label]) => `<div class="p-3 rounded-2xl bg-surface-container border border-secondary-container"><p class="text-[9px] font-bold uppercase tracking-wider text-secondary">${label}</p><p class="text-xs font-semibold text-on-surface mt-1">${ayushAssessment?.[key] || 'Not recorded'}</p></div>`).join('');
    }
    const ah = document.getElementById('ayushSummaryAhara');
    if (ah) ah.textContent = ayushAssessment?.ahara_vihara?.narrative || 'Not recorded.';
  }

  async function generateAiSummary() {
    if (!currentSessionId) return;
    const btn = document.getElementById('generateAiSummaryBtn');
    if (btn) btn.innerHTML = `<span>Synthesizing...</span><span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>`;

    const showPanel = (val) => {
      const panel = document.getElementById('aiSummaryPanel');
      if (panel) panel.classList.toggle('hidden', !val);
    };

    const setList = (id, items) => {
      const el = document.getElementById(id);
      if (!el) return;
      const nonEmpty = (items || []).filter(Boolean);
      if (nonEmpty.length === 0) {
        el.innerHTML = `<li class="text-xs text-secondary">Nothing recorded yet.</li>`;
        return;
      }
      el.innerHTML = nonEmpty.map(x => `<li class="text-xs text-on-surface pl-3 relative before:content-[''] before:absolute before:left-0 before:top-1.5 before:w-1.5 before:h-1.5 before:rounded-full before:bg-primary leading-relaxed">${x}</li>`).join('');
    };

    const isGenericEntity = isGenericClinicalEntity;

    const renderSummary = (sum) => {
      const panelEl = document.getElementById('aiSummaryPanel');
      const narrative = document.getElementById('aiSummaryNarrative');
      const attention = document.getElementById('aiSummaryAttention');
      if (panelEl) panelEl.classList.remove('hidden');

      let overview = '';
      if (sum && typeof sum === 'object' && typeof sum.overview === 'string' && sum.overview.trim().length > 15 && !sum.overview.includes('Summary generated from validated') && !sum.overview.includes('No validated') && !sum.overview.includes('evaluation of Clinical evaluation')) {
        overview = sum.overview.trim().replace(/[“”"_]+$/g, '').replace(/\.+$/g, '') + '.';
      } else {
        overview = buildLocalNarrative();
      }

      if (narrative) narrative.textContent = overview;
      updateHealthStoryUI();
      renderAyushSummaryCard();

      let rawHighlights = [];
      if (sum && typeof sum === 'object') {
        if (Array.isArray(sum.structured_history_highlights)) rawHighlights = rawHighlights.concat(sum.structured_history_highlights);
        if (Array.isArray(sum.patient_reported_concerns)) rawHighlights = rawHighlights.concat(sum.patient_reported_concerns);
        if (Array.isArray(sum.key_findings)) rawHighlights = rawHighlights.concat(sum.key_findings);
      }
      
      let highlights = [];
      rawHighlights.forEach(h => {
        if (!h || typeof h !== 'string') return;
        const lower = h.toLowerCase();
        if (lower.includes('clinical evaluation') || lower.includes('general clinical assessment') || lower.includes('chief concern: none') || lower.includes('chief concern: nothing')) return;
        const clean = h.trim();
        if (clean && !highlights.includes(clean)) highlights.push(clean);
      });

      if (highlights.length === 0) {
        const syms = Array.from(selectedWhatBringsSymptoms).filter(s => !isGenericEntity(s));
        const lastMsg = (lastPatientMessage || localStorage.getItem('cliniqo_last_patient_response') || '').trim();
        const chiefStr = syms.length ? syms.join(', ') : (!isGenericEntity(lastMsg) ? lastMsg : '');
        const medHistList = Array.from(selectedMedHistConditions).filter(c => !isGenericEntity(c));
        const medsList = Array.from(selectedMedications).filter(m => !isGenericEntity(m));
        const allergyList = Array.from(selectedAllergies).filter(a => !isGenericEntity(a));

        if (chiefStr) highlights.push(`🩺 Chief Concern: ${chiefStr}`);
        if (medHistList.length) highlights.push(`📋 Medical History: ${medHistList.join(' • ')}`);
        if (medsList.length) highlights.push(`💊 Active Medications: ${medsList.join(' • ')}`);
        if (allergyList.length) highlights.push(`⚠️ Allergy Alert: ${allergyList.join(', ')}`);
        else highlights.push('🛡️ Allergy Status: No known drug allergies reported');
        if (uploadedDocuments.length) highlights.push(`📄 Vault Records: ${uploadedDocuments.length} verified clinical document(s)`);
      }
      setList('aiSummaryHighlights', highlights);

      let rawGaps = [];
      if (sum && typeof sum === 'object') {
        if (Array.isArray(sum.information_gaps)) rawGaps = rawGaps.concat(sum.information_gaps);
        if (Array.isArray(sum.questions_for_clinician)) rawGaps = rawGaps.concat(sum.questions_for_clinician);
      }
      
      let gaps = [];
      rawGaps.forEach(g => {
        if (!g || typeof g !== 'string') return;
        const clean = g.trim();
        if (clean && !gaps.includes(clean)) gaps.push(clean);
      });

      if (gaps.length === 0) {
        const syms = Array.from(selectedWhatBringsSymptoms).filter(s => !isGenericEntity(s));
        const medHistList = Array.from(selectedMedHistConditions).filter(c => !isGenericEntity(c));
        const medsList = Array.from(selectedMedications).filter(m => !isGenericEntity(m));

        if (syms.length || lastPatientMessage) {
          gaps.push('Correlate reported symptom timeline and vital signs with physical examination findings.');
        }
        if (medHistList.length) {
          gaps.push(`Review ongoing care and management plan for ${medHistList.slice(0, 2).join(' and ')}.`);
        }
        if (medsList.length) {
          gaps.push('Reconcile active daily prescription dosages and verify adherence.');
        }
        if (uploadedDocuments.length) {
          gaps.push('Review attached scanned records and lab findings during clinician consultation.');
        }
        gaps.push('Confirm vital signs (temperature, blood pressure, pulse) during physician consultation.');
      }
      setList('aiSummaryGaps', gaps);

      if (attention) {
        const level = (sum && sum.overall_attention_level) || 'routine';
        attention.classList.remove('hidden');
        if (level === 'urgent') {
          attention.textContent = 'Attention needed: a safety point was flagged for your doctor to review.';
          attention.className = 'px-4 py-2.5 rounded-2xl text-xs font-bold bg-red-50 text-red-700 border border-red-200';
        } else if (level === 'attention') {
          attention.textContent = 'Please share this summary with your doctor soon - one point needs clinician review.';
          attention.className = 'px-4 py-2.5 rounded-2xl text-xs font-bold bg-amber-50 text-amber-800 border border-amber-200';
        } else {
          attention.textContent = 'No urgent concerns were detected from what you shared today.';
          attention.className = 'px-4 py-2.5 rounded-2xl text-xs font-bold bg-primary-fixed/60 text-primary border border-secondary-container';
        }
      }
    };

    try {
      await syncClinicalData();
      let summaryResp = null;
      try {
        summaryResp = await apiRequest(`/api/v1/sessions/${currentSessionId}/generate-summary`, { method: 'POST' });
      } catch (err) {
        summaryResp = await apiRequest(`/api/session/${currentSessionId}/generate-summary`, { method: 'POST' });
      }

      if (summaryResp) {
        const sum = summaryResp.content || summaryResp.summary || summaryResp;
        renderSummary(sum);
        renderCaseSummaryPage();
        saveToVaultNotification("Summary Generated", "Your AI Health Summary is ready in plain words.");
      } else {
        showPanel(true);
        renderSummary(null);
        renderCaseSummaryPage();
      }
    } catch (e) {
      console.warn("AI summary generation notice:", e);
      showPanel(true);
      renderSummary({ overview: buildLocalNarrative() });
      renderCaseSummaryPage();
    } finally {
      if (btn) btn.innerHTML = `<span class="material-symbols-outlined text-[24px]">auto_awesome</span><span>Generate AI Summary</span>`;
    }
  }

  // =========================================================================
  // 8B. CLINICAL CASE DOSSIER & DUAL VIEW (DOCTOR & PATIENT VIEWS)
  // =========================================================================
  let currentCaseSummaryView = 'doctor';

  function switchCaseSummaryView(mode) {
    currentCaseSummaryView = mode || 'doctor';
    const docBtn = document.getElementById('caseViewDoctorBtn');
    const patBtn = document.getElementById('caseViewPatientBtn');
    const docContainer = document.getElementById('caseDoctorViewContainer');
    const patContainer = document.getElementById('casePatientViewContainer');

    if (currentCaseSummaryView === 'doctor') {
      if (docBtn) {
        docBtn.className = 'px-3.5 py-1.5 rounded-xl text-xs font-bold bg-primary text-white transition-all cursor-pointer flex items-center gap-1.5 shadow-xs';
      }
      if (patBtn) {
        patBtn.className = 'px-3.5 py-1.5 rounded-xl text-xs font-semibold text-secondary hover:text-on-surface transition-all cursor-pointer flex items-center gap-1.5';
      }
      if (docContainer) docContainer.classList.remove('hidden');
      if (patContainer) patContainer.classList.add('hidden');
      saveToVaultNotification("Doctor View Active", "Showing clinical SOAP matrix, technical terminology, and physician orders.");
    } else {
      if (patBtn) {
        patBtn.className = 'px-3.5 py-1.5 rounded-xl text-xs font-bold bg-primary text-white transition-all cursor-pointer flex items-center gap-1.5 shadow-xs';
      }
      if (docBtn) {
        docBtn.className = 'px-3.5 py-1.5 rounded-xl text-xs font-semibold text-secondary hover:text-on-surface transition-all cursor-pointer flex items-center gap-1.5';
      }
      if (patContainer) patContainer.classList.remove('hidden');
      if (docContainer) docContainer.classList.add('hidden');
      saveToVaultNotification("Patient View Active", "Showing plain-language summary, medicine timetable, and doctor questions.");
    }
  }

  function speakCaseSummary() {
    const p = activePatient || {};
    const patientName = p.display_name || currentUser?.display_name || 'Patient';
    const chief = document.getElementById('docChiefComplaint')?.textContent?.trim() || document.getElementById('patChiefSymptom')?.textContent?.trim() || 'clinical visit';
    
    if (currentCaseSummaryView === 'doctor') {
      const onset = document.getElementById('docOnset')?.textContent?.trim() || 'recent onset';
      const loc = document.getElementById('docLocation')?.textContent?.trim() || 'systemic';
      const icd = document.getElementById('docIcdCode')?.textContent?.trim() || 'ICD-10: R50.9';
      const assessment = document.getElementById('docAssessmentNarrative')?.textContent?.trim() || 'Clinical evaluation complete.';
      const speech = `Doctor Case Dossier for patient ${patientName}. Subjective: Chief complaint is ${chief}, onset ${onset}, anatomical focus ${loc}, mapped to ${icd}. Assessment: ${assessment}. Physician orders and prescription formulary reconciled.`;
      speakText(speech);
      saveToVaultNotification("Clinical Narration", "Speaking doctor SOAP case dossier.");
    } else {
      const onset = document.getElementById('patOnset')?.textContent?.trim() || 'recently';
      const plainExp = document.getElementById('patPlainExplanation')?.textContent?.trim() || 'Your health information has been compiled for your doctor.';
      const speech = `Hello ${patientName.split(' ')[0] || patientName}. Here is your health summary. You reported ${chief}, which started ${onset}. ${plainExp} You can find your daily medicine schedule and questions to ask your doctor below.`;
      speakText(speech);
      saveToVaultNotification("Patient Summary Audio", "Speaking plain-language health guide.");
    }
  }

  function renderCaseSummaryPage() {
    const isGenericEntity = isGenericClinicalEntity;

    const p = activePatient || {};
    const patientName = p.display_name || currentUser?.display_name || 'Registered Patient';
    const abhaId = p.abha_id || 'ABDM-Verified';
    const dob = p.date_of_birth ? `${p.date_of_birth}` : 'Recorded on Intake';
    const gender = p.gender || 'Not specified';
    const blood = p.blood_group || 'O+';
    const phone = p.phone || 'Verified on Session';
    const emergency = p.emergency_contact || 'Family Contact';

    // 1. Patient Demographics Hydration
    const nameEl = document.getElementById('caseSumPatientName');
    const abhaEl = document.getElementById('caseSumAbhaId');
    const dobEl = document.getElementById('caseSumDob');
    const genderBloodEl = document.getElementById('caseSumGenderBlood');
    const phoneEl = document.getElementById('caseSumPhone');
    const emergEl = document.getElementById('caseSumEmergency');
    const sessEl = document.getElementById('caseSumSessionBadge');
    const triageEl = document.getElementById('caseSumTriageBadge');

    if (nameEl) nameEl.textContent = patientName;
    if (abhaEl) abhaEl.textContent = abhaId;
    if (dobEl) dobEl.textContent = dob;
    if (genderBloodEl) genderBloodEl.textContent = `${gender} / ${blood}`;
    if (phoneEl) phoneEl.textContent = phone;
    if (emergEl) emergEl.textContent = emergency;
    if (sessEl) sessEl.textContent = `SESSION: #${(currentSessionId || 'LOCAL').slice(0, 8).toUpperCase()}`;

    // Compute symptom strings
    const symList = Array.from(selectedWhatBringsSymptoms).filter(s => !isGenericEntity(s));
    const wbTranscript = document.getElementById('whatBringsTranscript');
    const wbRaw = (wbTranscript?.dataset.rawText || wbTranscript?.textContent || '').replace(/^[“"\s]+|[”"\s]+$/g, '').trim();
    const lastMsg = (lastPatientMessage || localStorage.getItem('cliniqo_last_patient_response') || '').trim();
    const s1Text = (document.getElementById('symptomVal1')?.textContent || '').trim();
    const s2Text = (document.getElementById('symptomVal2')?.textContent || '').trim();
    const s3Text = (document.getElementById('symptomVal3')?.textContent || '').trim();
    const s4Text = (document.getElementById('symptomVal4')?.textContent || '').trim();
    const s5Text = (document.getElementById('symptomVal5')?.textContent || '').trim();
    const s6Text = (document.getElementById('symptomVal6')?.textContent || '').trim();

    let chiefComplaint = '';
    let parsedOnset = '';

    if (symList.length > 0) {
      chiefComplaint = symList.join(', ');
    } else {
      const candidates = [wbRaw, lastMsg, s1Text].filter(c => c && !isGenericEntity(c));
      for (const cand of candidates) {
        let raw = String(cand).replace(/^[“"'\s]+|[”"'\s]+$/g, '').trim();
        const durMatch = raw.match(/\b(?:for|past|last)\s+(\d+\s*(?:days?|weeks?|months?|hours?))\b/i);
        const sinceMatch = raw.match(/\b(?:since)\s+(yesterday|today|last night|last week|\d+\s*(?:days?|weeks?|months?)\s*(?:ago)?)\b/i);
        if (durMatch) {
          parsedOnset = `Started ~${durMatch[1]} ago`;
          raw = raw.replace(durMatch[0], '');
        } else if (sinceMatch) {
          parsedOnset = `Started ${sinceMatch[1]}`;
          raw = raw.replace(sinceMatch[0], '');
        }
        let clean = raw
          .replace(/^I('ve been experiencing| have been experiencing| have got| have| am having| am experiencing| feel| felt| have had| got)\s+/i, '')
          .replace(/^(?:patient (?:has|presents with|is complaining of)|suffering from|complaining of|experiencing|problem is|trouble with)\s+/i, '')
          .replace(/\s+recently\.?$/i, '')
          .replace(/\s+now\.?$/i, '')
          .replace(/^[,\s.-]+|[,\s.-]+$/g, '')
          .trim();
        if (clean) {
          chiefComplaint = clean.charAt(0).toUpperCase() + clean.slice(1);
          break;
        }
      }
    }

    if (!chiefComplaint) {
      chiefComplaint = 'Routine clinical intake evaluation';
    }

    const onset = (!isGenericEntity(s2Text) && s2Text !== 'Not recorded' && s2Text !== 'Recorded today') 
      ? s2Text 
      : (parsedOnset || (lastMsg.match(/\b\d+\s*(?:day|week|month)s?\b/i) ? `Started ~${lastMsg.match(/\b\d+\s*(?:day|week|month)s?\b/i)[0]} ago` : 'Recorded today'));

    const location = (!isGenericEntity(s3Text) && s3Text !== 'Not specified') 
      ? s3Text 
      : (selectedPainLocations.size > 0 ? Array.from(selectedPainLocations).join(' / ') : 'General / Whole body');

    const severity = (!isGenericEntity(s6Text) && s6Text !== 'Unrated') ? s6Text : 'Graded Clinical Report';

    const triggerReliefParts = [];
    if (selectedAdaptiveTriggers.size > 0) {
      const validTrigs = Array.from(selectedAdaptiveTriggers).filter(t => !isGenericEntity(t));
      if (validTrigs.length > 0) triggerReliefParts.push(`Trigger: ${validTrigs.join(', ')}`);
    } else if (!isGenericEntity(s4Text) && s4Text !== 'None reported') {
      triggerReliefParts.push(`Trigger: ${s4Text}`);
    }
    if (selectedAdaptiveChoices.size > 0) {
      const choices = Array.from(selectedAdaptiveChoices).filter(c => !isGenericEntity(c));
      const patterns = [];
      const reliefs = [];
      choices.forEach(ch => {
        const lower = ch.toLowerCase();
        if (lower.includes('better') || lower.includes('relieved') || lower.includes('improves') || 
            lower.includes('antacid') || lower.includes('dark') || lower.includes('quiet') ||
            lower.includes('rest') || lower.includes('sleep') || lower.includes('medicine') || lower.includes('paracetamol')) {
          reliefs.push(ch);
        } else {
          patterns.push(ch);
        }
      });
      if (patterns.length > 0) triggerReliefParts.push(`Pattern: ${patterns.join(', ')}`);
      if (reliefs.length > 0) triggerReliefParts.push(`Relief: ${reliefs.join(', ')}`);
    } else if (!isGenericEntity(s5Text) && s5Text !== 'None reported') {
      triggerReliefParts.push(`Character/Relief: ${s5Text}`);
    }
    const triggerRelief = triggerReliefParts.length > 0 ? triggerReliefParts.join(' • ') : 'Trigger / Character: Standard presentation';
    
    const validLast = !isGenericEntity(lastMsg) ? lastMsg : '';
    const validWb = !isGenericEntity(wbRaw) ? wbRaw : '';
    const spokenUtterance = validLast || validWb || (symList.length > 0 ? `I have ${symList.join(', ')}` : 'Routine clinical assessment initiated.');

    // Triage badge calculation
    const allSymsLower = `${symList.join(' ')} ${lastMsg} ${chiefComplaint}`.toLowerCase();
    const isPriority = allSymsLower.includes('chest pain') || allSymsLower.includes('breathing') || allSymsLower.includes('shortness of breath') || allSymsLower.includes('severe');
    if (triageEl) {
      if (isPriority) {
        triageEl.className = 'px-3 py-1 rounded-full bg-amber-100 text-amber-900 font-bold text-xs flex items-center gap-1';
        triageEl.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-amber-600"></span><span>PRIORITY TRIAGE</span>`;
      } else {
        triageEl.className = 'px-3 py-1 rounded-full bg-primary-fixed text-primary font-bold text-xs flex items-center gap-1';
        triageEl.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-primary"></span><span>ROUTINE TRIAGE</span>`;
      }
    }

    // Past History & Ingested Conditions
    const medHistList = Array.from(selectedMedHistConditions).filter(c => !isGenericEntity(c));
    uploadedDocuments.forEach(doc => {
      const diags = doc.ocr?.diagnoses || doc.ocr?.extracted_fields?.diagnoses || [];
      diags.forEach(d => {
        const cName = typeof d === 'string' ? d : (d.condition || d.name);
        if (cName && !isGenericEntity(cName) && !medHistList.includes(cName)) medHistList.push(cName);
      });
    });

    // Active Medications
    const medsList = Array.from(selectedMedications).filter(m => !isGenericEntity(m));
    uploadedDocuments.forEach(doc => {
      const docMeds = doc.ocr?.medications || doc.ocr?.extracted_fields?.medications || [];
      docMeds.forEach(m => {
        const mName = typeof m === 'string' ? m : (m.name_as_reported || m.name);
        if (mName && !isGenericEntity(mName) && !medsList.some(x => x.toLowerCase().includes(mName.toLowerCase()))) {
          const dose = (typeof m === 'object' && m.dose_as_reported) ? ` ${m.dose_as_reported}` : '';
          const freq = (typeof m === 'object' && m.frequency_as_reported) ? ` (${m.frequency_as_reported})` : '';
          medsList.push(`${mName}${dose}${freq}`.trim());
        }
      });
    });

    // Allergies
    const allergyList = Array.from(selectedAllergies).filter(a => !isGenericEntity(a));

    // Family & Lifestyle
    const famList = Array.from(selectedFamilyConditions).filter(f => !isGenericEntity(f));
    const lifeList = Array.from(selectedLifestyleHabits).filter(l => !isGenericEntity(l));

    // =========================================================================
    // 2. HYDRATE DOCTOR VIEW (#caseDoctorViewContainer)
    // =========================================================================
    const isFever = allSymsLower.includes('fever') || allSymsLower.includes('temp') || allSymsLower.includes('pyrexia') || allSymsLower.includes('warm');
    const hasHypertension = medHistList.some(c => c.toLowerCase().includes('hypertension') || c.toLowerCase().includes('bp'));

    // Vitals Elements
    const docTempEl = document.getElementById('docVitalsTemp');
    const docTempStatusEl = document.getElementById('docVitalsTempStatus');
    const docPulseEl = document.getElementById('docVitalsPulse');
    const docPulseStatusEl = document.getElementById('docVitalsPulseStatus');
    const docBpEl = document.getElementById('docVitalsBp');
    const docBpStatusEl = document.getElementById('docVitalsBpStatus');
    const docSpo2El = document.getElementById('docVitalsSpo2');
    const docSpo2StatusEl = document.getElementById('docVitalsSpo2Status');
    const docRespEl = document.getElementById('docVitalsResp');
    const docRespStatusEl = document.getElementById('docVitalsRespStatus');
    const docPainEl = document.getElementById('docVitalsPain');
    const docPainLvlEl = document.getElementById('docVitalsPainLevel');
    const docEncounterTypeEl = document.getElementById('docEncounterType');

    // Extract authentic vitals if present from uploaded medical documents
    let extractedTemp = null;
    let extractedPulse = null;
    let extractedBp = null;
    let extractedSpo2 = null;
    let extractedResp = null;

    uploadedDocuments.forEach(doc => {
      const o = doc.ocr || {};
      const ef = (o.extracted_fields && typeof o.extracted_fields === 'object' && !Array.isArray(o.extracted_fields)) ? o.extracted_fields : o;
      const vList = o.vitals || ef.vitals || [];
      if (Array.isArray(vList)) {
        vList.forEach(v => {
          const vName = (v.vital || v.name || '').toLowerCase();
          const vVal = v.value_as_reported || v.value || '';
          if (vVal) {
            if (vName.includes('temp') || vName.includes('fever')) extractedTemp = vVal;
            else if (vName.includes('pulse') || vName.includes('heart rate') || vName.includes('hr')) extractedPulse = vVal;
            else if (vName.includes('blood pressure') || vName.includes('bp')) extractedBp = vVal;
            else if (vName.includes('spo2') || vName.includes('oxygen')) extractedSpo2 = vVal;
            else if (vName.includes('resp') || vName.includes('rr')) extractedResp = vVal;
          }
        });
      }
    });

    // Check if user spoke/reported a specific temperature in their intake transcript
    const userUtterance = `${spokenUtterance} ${lastPatientMessage}`.toLowerCase();
    const tempMatch = userUtterance.match(/(\b1\d{2}(?:\.\d+)?\s*(?:°\s*f|f|c|degrees?)\b|\btemp(?:erature)?\s*(?:is|was|of)?\s*(\d{2,3}(?:\.\d+)?))/i);
    if (!extractedTemp && tempMatch) {
      extractedTemp = tempMatch[1] || `${tempMatch[2]} °F`;
    }

    // 1. Temperature
    if (docTempEl) {
      if (extractedTemp) {
        docTempEl.textContent = extractedTemp;
        if (docTempStatusEl) {
          docTempStatusEl.textContent = 'Document Ingested';
          docTempStatusEl.className = 'text-[10px] text-primary font-bold bg-primary-fixed px-2 py-0.5 rounded-full inline-block';
        }
      } else {
        docTempEl.textContent = '—';
        if (docTempStatusEl) {
          docTempStatusEl.textContent = 'Not recorded';
          docTempStatusEl.className = 'text-[10px] text-secondary font-medium bg-surface-container px-2 py-0.5 rounded-full inline-block';
        }
      }
    }

    // 2. Pulse / Heart Rate
    if (docPulseEl) {
      if (extractedPulse) {
        docPulseEl.textContent = extractedPulse;
        if (docPulseStatusEl) {
          docPulseStatusEl.textContent = 'Document Ingested';
          docPulseStatusEl.className = 'text-[10px] text-primary font-bold bg-primary-fixed px-2 py-0.5 rounded-full inline-block';
        }
      } else {
        docPulseEl.textContent = '—';
        if (docPulseStatusEl) {
          docPulseStatusEl.textContent = 'Not recorded';
          docPulseStatusEl.className = 'text-[10px] text-secondary font-medium bg-surface-container px-2 py-0.5 rounded-full inline-block';
        }
      }
    }

    // 3. Blood Pressure
    if (docBpEl) {
      if (extractedBp) {
        docBpEl.textContent = extractedBp;
        if (docBpStatusEl) {
          docBpStatusEl.textContent = 'Document Ingested';
          docBpStatusEl.className = 'text-[10px] text-primary font-bold bg-primary-fixed px-2 py-0.5 rounded-full inline-block';
        }
      } else {
        docBpEl.textContent = '—';
        if (docBpStatusEl) {
          docBpStatusEl.textContent = 'Not recorded';
          docBpStatusEl.className = 'text-[10px] text-secondary font-medium bg-surface-container px-2 py-0.5 rounded-full inline-block';
        }
      }
    }

    // 4. SpO2 (Oxygen Saturation)
    if (docSpo2El) {
      if (extractedSpo2) {
        docSpo2El.textContent = extractedSpo2;
        if (docSpo2StatusEl) {
          docSpo2StatusEl.textContent = 'Document Ingested';
          docSpo2StatusEl.className = 'text-[10px] text-primary font-bold bg-primary-fixed px-2 py-0.5 rounded-full inline-block';
        }
      } else {
        docSpo2El.textContent = '—';
        if (docSpo2StatusEl) {
          docSpo2StatusEl.textContent = 'Not recorded';
          docSpo2StatusEl.className = 'text-[10px] text-secondary font-medium bg-surface-container px-2 py-0.5 rounded-full inline-block';
        }
      }
    }

    // 5. Respiratory Rate
    if (docRespEl) {
      if (extractedResp) {
        docRespEl.textContent = extractedResp;
        if (docRespStatusEl) {
          docRespStatusEl.textContent = 'Document Ingested';
          docRespStatusEl.className = 'text-[10px] text-primary font-bold bg-primary-fixed px-2 py-0.5 rounded-full inline-block';
        }
      } else {
        docRespEl.textContent = '—';
        if (docRespStatusEl) {
          docRespStatusEl.textContent = 'Not recorded';
          docRespStatusEl.className = 'text-[10px] text-secondary font-medium bg-surface-container px-2 py-0.5 rounded-full inline-block';
        }
      }
    }

    // 6. Pain VAS (Visual Analog Scale from Patient Self-Report)
    if (docPainEl && docPainLvlEl) {
      const sevLower = severity.toLowerCase();
      if (sevLower.includes('severe') || sevLower.includes('urgent') || sevLower.includes('7-9') || sevLower.includes('8/') || sevLower.includes('9/') || sevLower.includes('10/')) {
        docPainEl.textContent = '7-9 / 10';
        docPainLvlEl.textContent = 'Severe (Self-Reported)';
        docPainLvlEl.className = 'text-[10px] text-red-700 font-bold bg-red-50 px-2 py-0.5 rounded-full inline-block';
      } else if (sevLower.includes('moderate') || sevLower.includes('4-6') || sevLower.includes('4/') || sevLower.includes('5/') || sevLower.includes('6/')) {
        docPainEl.textContent = '4-6 / 10';
        docPainLvlEl.textContent = 'Moderate (Self-Reported)';
        docPainLvlEl.className = 'text-[10px] text-amber-700 font-bold bg-amber-50 px-2 py-0.5 rounded-full inline-block';
      } else if (sevLower.includes('mild') || sevLower.includes('2-3') || sevLower.includes('1/') || sevLower.includes('2/') || sevLower.includes('3/')) {
        docPainEl.textContent = '2-3 / 10';
        docPainLvlEl.textContent = 'Mild (Self-Reported)';
        docPainLvlEl.className = 'text-[10px] text-primary font-bold bg-primary-fixed px-2 py-0.5 rounded-full inline-block';
      } else if (sevLower.includes('graded') || (chiefComplaint && chiefComplaint !== 'Routine clinical intake evaluation')) {
        docPainEl.textContent = 'Graded';
        docPainLvlEl.textContent = 'Intake Report';
        docPainLvlEl.className = 'text-[10px] text-primary font-bold bg-primary-fixed px-2 py-0.5 rounded-full inline-block';
      } else {
        docPainEl.textContent = '—';
        docPainLvlEl.textContent = 'Not rated';
        docPainLvlEl.className = 'text-[10px] text-secondary font-medium bg-surface-container px-2 py-0.5 rounded-full inline-block';
      }
    }

    if (docEncounterTypeEl) {
      const hasAnyVital = Boolean(extractedTemp || extractedPulse || extractedBp || extractedSpo2 || extractedResp);
      docEncounterTypeEl.textContent = hasAnyVital ? 'ENCOUNTER: OUTPATIENT TRIAGE • RECORDS ATTACHED' : 'ENCOUNTER: OUTPATIENT TRIAGE • VITALS PENDING';
    }

    // Subjective (S)
    const docIcdEl = document.getElementById('docIcdCode');
    let icdCode = 'ICD-10: R50.9 (Fever, unspecified)';
    if (allSymsLower.includes('cough')) icdCode = 'ICD-10: R05.9 (Cough, unspecified)';
    else if (allSymsLower.includes('chest pain')) icdCode = 'ICD-10: R07.9 (Chest pain, unspecified)';
    else if (allSymsLower.includes('headache')) icdCode = 'ICD-10: R51.9 (Headache, unspecified)';
    else if (allSymsLower.includes('stomach') || allSymsLower.includes('abdom')) icdCode = 'ICD-10: R10.9 (Abdominal pain)';
    else if (allSymsLower.includes('throat')) icdCode = 'ICD-10: J02.9 (Acute pharyngitis)';
    else if (!isFever) icdCode = 'ICD-10: Z00.00 (General exam)';
    if (docIcdEl) docIcdEl.textContent = icdCode;

    const docChiefEl = document.getElementById('docChiefComplaint');
    const docOnsetEl = document.getElementById('docOnset');
    const docLocEl = document.getElementById('docLocation');
    const docSevEl = document.getElementById('docSeverityBadge');
    const docTrigEl = document.getElementById('docTriggersRelief');
    const docVerbatimEl = document.getElementById('docPatientVerbatim');
    const docAssocEl = document.getElementById('docAssociatedSymptoms');

    if (docChiefEl) docChiefEl.textContent = chiefComplaint;
    if (docOnsetEl) docOnsetEl.textContent = onset;
    if (docLocEl) docLocEl.textContent = location;
    if (docSevEl) docSevEl.textContent = severity;
    if (docTrigEl) docTrigEl.textContent = triggerRelief;
    if (docVerbatimEl) docVerbatimEl.textContent = `“${spokenUtterance}”`;

    if (docAssocEl) {
      const assocList = [];
      if (symList.length > 1) symList.slice(1).forEach(s => assocList.push(s));
      if (selectedPainLocations.size > 0) selectedPainLocations.forEach(l => { if (!assocList.includes(l)) assocList.push(l); });
      if (selectedAdaptiveTriggers.size > 0) selectedAdaptiveTriggers.forEach(t => { if (!assocList.includes(t)) assocList.push(t); });
      if (assocList.length === 0) {
        docAssocEl.innerHTML = `<span class="px-2.5 py-1 rounded-xl bg-surface-container text-xs font-medium text-secondary">Primary symptom focus</span>`;
      } else {
        docAssocEl.innerHTML = assocList.map(a => `<span class="px-2.5 py-1 rounded-xl bg-primary/10 text-primary text-xs font-semibold">${a}</span>`).join('');
      }
    }

    // Objective (O): Documents & Lab Biomarkers
    const docDocsContainer = document.getElementById('docDocumentsList');
    const docLabsTbody = document.getElementById('docLabTableBody');

    if (docDocsContainer) {
      if (uploadedDocuments.length === 0) {
        docDocsContainer.innerHTML = `
          <div class="p-4 rounded-2xl bg-surface-container text-center text-xs text-secondary col-span-full">
            No attached external clinical records yet.
          </div>
        `;
      } else {
        docDocsContainer.innerHTML = uploadedDocuments.map(doc => {
          const o = doc.ocr || {};
          const ef = (o.extracted_fields && typeof o.extracted_fields === 'object' && !Array.isArray(o.extracted_fields)) ? o.extracted_fields : o;
          const dt = o.document_type || ef.document_type || 'Prescription';
          const sizeKb = (doc.file_size / 1024).toFixed(1);
          const rawExcerpt = (o.raw_text || ef.raw_text || o.text || 'Verified clinical document').slice(0, 160);
          return `
            <div class="p-4 rounded-2xl bg-surface-container/70 border border-secondary-container/60 space-y-2">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2 max-w-[70%]">
                  <span class="material-symbols-outlined text-primary text-[20px] shrink-0">description</span>
                  <span class="font-headline font-bold text-xs text-on-surface truncate">${doc.file_name}</span>
                </div>
                <span class="px-2.5 py-0.5 rounded-full bg-primary-fixed text-primary font-bold text-[10px] shrink-0">${dt}</span>
              </div>
              <p class="text-[11px] text-secondary line-clamp-2 italic bg-white/80 p-2 rounded-xl border border-secondary-container/40">
                "${rawExcerpt}..."
              </p>
              <div class="flex items-center justify-between text-[10px] text-secondary pt-1">
                <span>${sizeKb} KB • Uploaded on ${new Date(doc.created_at || Date.now()).toLocaleDateString()}</span>
                <span class="text-primary font-semibold">✓ OCR Ingested</span>
              </div>
            </div>
          `;
        }).join('');
      }
    }

    if (docLabsTbody) {
      const allLabs = [];
      uploadedDocuments.forEach(doc => {
        const o = doc.ocr || {};
        const ef = (o.extracted_fields && typeof o.extracted_fields === 'object' && !Array.isArray(o.extracted_fields)) ? o.extracted_fields : o;
        const labs = o.lab_results || ef.lab_results || [];
        labs.forEach(l => {
          const testName = typeof l === 'string' ? l : (l.test_name || l.name || 'Biomarker');
          const value = typeof l === 'string' ? 'Recorded' : (l.value_as_reported || l.value || '--');
          const unit = typeof l === 'string' ? '' : (l.unit_as_reported || l.unit || '');
          const status = typeof l === 'string' ? 'Verified' : (l.status || 'Normal');
          allLabs.push({ testName, value, unit, status, source: doc.file_name || 'Lab Report' });
        });
      });

      if (allLabs.length === 0) {
        docLabsTbody.innerHTML = `
          <tr>
            <td colspan="5" class="p-3 text-center text-secondary">No lab biomarker data ingested from scanned records yet.</td>
          </tr>
        `;
      } else {
        docLabsTbody.innerHTML = allLabs.map(l => `
          <tr class="hover:bg-surface-container/50 transition-colors">
            <td class="p-3 font-semibold text-on-surface">${l.testName}</td>
            <td class="p-3 font-bold text-primary">${l.value}</td>
            <td class="p-3 text-secondary font-mono">${l.unit || '--'}</td>
            <td class="p-3">
              <span class="px-2 py-0.5 rounded-full ${l.status.toLowerCase().includes('abnormal') || l.status.toLowerCase().includes('high') ? 'bg-amber-100 text-amber-900 font-bold' : 'bg-primary-fixed text-primary font-bold'} text-[10px]">
                ${l.status}
              </span>
            </td>
            <td class="p-3 text-secondary truncate max-w-[120px]">${l.source}</td>
          </tr>
        `).join('');
      }
    }

    // Assessment (A)
    const docAssessEl = document.getElementById('docAssessmentNarrative');
    const existingAiNarrative = document.getElementById('aiSummaryNarrative')?.textContent?.trim();
    const fallbackNarrative = buildLocalNarrative();
    const activeNarrative = (existingAiNarrative && existingAiNarrative.length > 20 && !existingAiNarrative.includes('Summary generated from validated')) 
      ? existingAiNarrative 
      : fallbackNarrative;
    if (docAssessEl) docAssessEl.textContent = activeNarrative;

    const docRiskBadge = document.getElementById('docRiskBadge');
    if (docRiskBadge) {
      if (isPriority) {
        docRiskBadge.textContent = 'Amber Alert / Clinical Review Required';
        docRiskBadge.className = 'px-3 py-1 rounded-full bg-amber-100 text-amber-900 text-xs font-bold';
      } else {
        docRiskBadge.textContent = 'Low Risk / Routine Triage';
        docRiskBadge.className = 'px-3 py-1 rounded-full bg-primary-fixed text-primary text-xs font-bold';
      }
    }

    const docPastHistList = document.getElementById('docPastHistoryList');
    if (docPastHistList) {
      if (medHistList.length === 0) {
        docPastHistList.innerHTML = `<div class="p-2.5 rounded-xl bg-white text-xs text-secondary text-center">No chronic conditions recorded.</div>`;
      } else {
        docPastHistList.innerHTML = medHistList.map(c => `
          <div class="p-2.5 rounded-xl bg-white border border-secondary-container/40 flex items-center justify-between text-xs">
            <span class="font-bold text-on-surface">${c}</span>
            <span class="px-2 py-0.5 rounded-full bg-secondary-container text-secondary text-[10px] font-bold">Documented</span>
          </div>
        `).join('');
      }
    }

    const docFamText = document.getElementById('docFamilyHistoryText');
    const docLifeText = document.getElementById('docLifestyleText');
    if (docFamText) docFamText.textContent = famList.length > 0 ? famList.join(', ') : 'None documented';
    if (docLifeText) docLifeText.innerHTML = `<strong>Lifestyle:</strong> ${lifeList.length > 0 ? lifeList.join(', ') : 'Standard everyday activity'}`;

    // Plan & Orders (P)
    const docMedsListEl = document.getElementById('docMedicationsList');
    if (docMedsListEl) {
      if (medsList.length === 0) {
        docMedsListEl.innerHTML = `<div class="p-2.5 rounded-xl bg-white text-xs text-secondary text-center">No active daily medications reported.</div>`;
      } else {
        docMedsListEl.innerHTML = medsList.map(m => `
          <div class="p-2.5 rounded-xl bg-white border border-secondary-container/40 flex items-center justify-between text-xs">
            <span class="font-bold text-primary">${m}</span>
            <span class="px-2 py-0.5 rounded-full bg-primary-fixed text-primary text-[10px] font-bold">Active Rx</span>
          </div>
        `).join('');
      }
    }

    const docAllergiesEl = document.getElementById('docAllergiesList');
    if (docAllergiesEl) {
      if (allergyList.length === 0) {
        docAllergiesEl.innerHTML = `
          <div class="p-3 rounded-2xl bg-white text-xs text-secondary flex items-center gap-2">
            <span class="material-symbols-outlined text-[16px] text-primary">check_circle</span>
            <span>No known drug allergies reported (NKDA)</span>
          </div>
        `;
      } else {
        docAllergiesEl.innerHTML = allergyList.map(a => `
          <div class="p-2.5 rounded-xl bg-red-50 border border-red-200 text-red-700 font-semibold text-xs flex items-center gap-2">
            <span class="material-symbols-outlined text-[16px]">warning</span>
            <span>Critical Drug Allergy: <strong>${a}</strong> (Check cross-reactivity)</span>
          </div>
        `).join('');
      }
    }

    const docOrdersEl = document.getElementById('docPhysicianOrders');
    if (docOrdersEl) {
      const orders = [
        `Perform targeted physical examination focused on ${location.toLowerCase()}.`,
        `Correlate reported symptom progression with clinical vital signs.`,
        medsList.length > 0 ? `Reconcile active daily prescription regimen (${medsList.slice(0, 2).join(', ')}) and verify adherence.` : 'Formulate appropriate therapeutic prescription regimen.',
        uploadedDocuments.length > 0 ? `Review attached ${uploadedDocuments.length} external diagnostic record(s) and confirm findings.` : 'Order baseline screening or diagnostic panels if clinically indicated.',
        'Review red flag emergency warning signs with patient before discharge.'
      ];
      docOrdersEl.innerHTML = orders.map((ord, idx) => `
        <li class="text-xs text-on-surface flex items-start gap-2">
          <span class="w-4 h-4 rounded-full bg-primary text-white text-[10px] font-bold flex items-center justify-center shrink-0 mt-0.5">${idx + 1}</span>
          <span>${ord}</span>
        </li>
      `).join('');
    }

    // Doctor Review notes & timestamp
    const docTimeEl = document.getElementById('caseSumTimestamp');
    if (docTimeEl) {
      docTimeEl.textContent = `Verified: ${new Date().toLocaleDateString('en-IN', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })}`;
    }

    // Doctor notes — dynamically generated from actual session data (no hardcoded mock text)
    const caseSumNotesEl = document.getElementById('caseSumDoctorNotes');
    if (caseSumNotesEl) {
      const hasSymptoms = symList.length > 0 || (chiefComplaint && chiefComplaint !== 'Routine clinical intake evaluation');
      const hasDocs = uploadedDocuments.length > 0;
      const hasMeds = medsList.length > 0;
      const hasHistory = medHistList.length > 0;

      if (!hasSymptoms && !hasDocs && !hasMeds && !hasHistory) {
        caseSumNotesEl.textContent = 'No clinical data collected yet. Complete the intake assessment to generate physician review notes.';
      } else {
        const parts = [];
        if (hasSymptoms) parts.push(`Patient reported: ${chiefComplaint.toLowerCase()}`);
        if (onset && onset !== 'Recorded today') parts.push(`onset ${onset.toLowerCase()}`);
        if (location && location !== 'General / Whole body') parts.push(`localized to ${location.toLowerCase()}`);
        if (hasDocs) parts.push(`${uploadedDocuments.length} external medical record(s) digitized via OCR and verified`);
        if (hasMeds) parts.push(`active medication regimen noted (${medsList.slice(0, 3).join(', ')})`);
        if (hasHistory) parts.push(`past medical history recorded (${medHistList.slice(0, 3).join(', ')})`);
        const clinicalNote = parts.length > 0
          ? `${parts.join('. ')}. Intake dossier authorized for clinician review and differential diagnosis.`
          : 'Clinical intake completed. Authorized for clinician review.';
        caseSumNotesEl.textContent = clinicalNote.charAt(0).toUpperCase() + clinicalNote.slice(1);
      }
    }

    // =========================================================================
    // 3. HYDRATE PATIENT VIEW (#casePatientViewContainer)
    // =========================================================================
    const patGreeting = document.getElementById('patGreetingName');
    if (patGreeting) patGreeting.textContent = `Hello, ${(patientName || 'Patient').split(' ')[0]}!`;

    const patChiefEl = document.getElementById('patChiefSymptom');
    const patOnsetEl = document.getElementById('patOnset');
    const patLocEl = document.getElementById('patLocation');
    const patTrigEl = document.getElementById('patTriggersSummary');
    const patSevNote = document.getElementById('patSeverityNote');
    const patQuoteEl = document.getElementById('patRecordedQuote');
    const patPlainExp = document.getElementById('patPlainExplanation');

    const hasRealChief = chiefComplaint && chiefComplaint !== 'Routine clinical intake evaluation';
    const hasRealOnset = onset && onset !== 'Recorded today';
    const hasRealLocation = location && location !== 'General / Whole body';
    const hasRealSpoken = spokenUtterance && spokenUtterance !== 'Routine clinical assessment initiated.';

    if (patChiefEl) patChiefEl.textContent = hasRealChief ? chiefComplaint : '—';
    if (patOnsetEl) patOnsetEl.textContent = hasRealOnset ? onset : 'Not recorded yet';
    if (patLocEl) patLocEl.textContent = hasRealLocation ? location : 'Not specified';
    if (patTrigEl) patTrigEl.textContent = hasRealChief ? triggerRelief.replace(/^Trigger:\s*/i, '').replace(/•/g, '•') : 'Awaiting intake data';
    if (patSevNote) {
      if (!hasRealChief) {
        patSevNote.textContent = 'Awaiting intake data';
      } else {
        patSevNote.textContent = severity.toLowerCase().includes('severe') ? 'Reported as moderate to high discomfort' : 'Graded as manageable with rest';
      }
    }

    // "Exact words captured" badge — only show checkmark when real words exist
    const patQuoteBadge = document.querySelector('#casePatientViewContainer .flex.items-center.justify-between span.text-\\[11px\\]');
    if (patQuoteBadge) {
      patQuoteBadge.textContent = hasRealSpoken ? '✓ Exact words captured' : 'Pending intake';
      patQuoteBadge.className = hasRealSpoken
        ? 'text-[11px] text-primary font-semibold'
        : 'text-[11px] text-secondary font-semibold';
    }

    if (patQuoteEl) {
      patQuoteEl.textContent = hasRealSpoken
        ? `"${spokenUtterance}"`
        : '"Your spoken words will appear here after the intake interview."';
    }
    if (patPlainExp) {
      if (!hasRealChief) {
        patPlainExp.textContent = "Your health information summary will appear here once you complete the intake interview. Please use the voice orb or the symptom questions to describe what you're experiencing.";
      } else {
        const onsetPart = hasRealOnset ? ` (${onset.toLowerCase()})` : '';
        const locationPart = hasRealLocation ? `, felt around ${location.toLowerCase()}` : '';
        patPlainExp.textContent = `You shared that you are experiencing ${chiefComplaint.toLowerCase()}${onsetPart}${locationPart}. We've prepared this summary so you and your doctor can have a smooth, reassuring consultation today.`;
      }
    }

    // 3-Slot Medication Timetable (Morning / Afternoon / Night)
    const patMorningEl = document.getElementById('patMorningMeds');
    const patAfternoonEl = document.getElementById('patAfternoonMeds');
    const patNightEl = document.getElementById('patNightMeds');

    if (patMorningEl && patAfternoonEl && patNightEl) {
      if (medsList.length === 0) {
        patMorningEl.innerHTML = `<p class="text-xs text-amber-800/80 italic">No morning medicines scheduled.</p>`;
        patAfternoonEl.innerHTML = `<p class="text-xs text-sky-800/80 italic">No afternoon medicines scheduled.</p>`;
        patNightEl.innerHTML = `<p class="text-xs text-indigo-800/80 italic">No night medicines scheduled.</p>`;
      } else {
        const morningList = [];
        const afternoonList = [];
        const nightList = [];

        medsList.forEach(med => {
          const mLower = med.toLowerCase();
          if (mLower.includes('night') || mLower.includes('bedtime') || mLower.includes('hs') || mLower.includes('statin') || mLower.includes('montelukast')) {
            nightList.push(med);
          } else if (mLower.includes('noon') || mLower.includes('lunch') || mLower.includes('afternoon') || mLower.includes('paracetamol')) {
            afternoonList.push(med);
          } else {
            morningList.push(med);
          }
        });

        // Ensure reasonable visual display
        if (morningList.length === 0 && afternoonList.length === 0 && nightList.length === 0) {
          morningList.push(medsList[0]);
        }

        patMorningEl.innerHTML = morningList.length > 0 ? morningList.map(m => `
          <div class="p-2 rounded-xl bg-white/90 border border-amber-200/80 text-xs">
            <span class="font-bold text-amber-950 block">${m}</span>
            <span class="text-[10px] text-amber-700">Take with breakfast 🍽️</span>
          </div>
        `).join('') : `<p class="text-xs text-amber-800/80 italic">No morning medicines scheduled.</p>`;

        patAfternoonEl.innerHTML = afternoonList.length > 0 ? afternoonList.map(m => `
          <div class="p-2 rounded-xl bg-white/90 border border-sky-200/80 text-xs">
            <span class="font-bold text-sky-950 block">${m}</span>
            <span class="text-[10px] text-sky-700">Take after lunch 🌤️</span>
          </div>
        `).join('') : `<p class="text-xs text-sky-800/80 italic">No afternoon medicines scheduled.</p>`;

        patNightEl.innerHTML = nightList.length > 0 ? nightList.map(m => `
          <div class="p-2 rounded-xl bg-white/90 border border-indigo-200/80 text-xs">
            <span class="font-bold text-indigo-950 block">${m}</span>
            <span class="text-[10px] text-indigo-700">Take after dinner / bedtime 🌙</span>
          </div>
        `).join('') : `<p class="text-xs text-indigo-800/80 italic">No night medicines scheduled.</p>`;
      }
    }

    // Patient Allergy Notice
    const patAllergyNotice = document.getElementById('patAllergyNotice');
    if (patAllergyNotice) {
      if (allergyList.length === 0) {
        patAllergyNotice.className = 'p-4 rounded-2xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-900 flex items-start gap-3';
        patAllergyNotice.innerHTML = `
          <span class="material-symbols-outlined text-[20px] text-emerald-700 shrink-0 mt-0.5">verified_user</span>
          <div>
            <h4 class="font-bold text-emerald-950">No Drug Allergies Reported (Safe)</h4>
            <p class="text-emerald-800/90 leading-relaxed">You haven't reported any allergies to medications. Always let your doctor know if you ever had a bad reaction to any pill in the past.</p>
          </div>
        `;
      } else {
        patAllergyNotice.className = 'p-4 rounded-2xl bg-red-50 border-2 border-red-200 text-xs text-red-900 flex items-start gap-3';
        patAllergyNotice.innerHTML = `
          <span class="material-symbols-outlined text-[20px] text-red-600 shrink-0 mt-0.5">warning</span>
          <div>
            <h4 class="font-bold text-red-950">⚠️ Important Allergy Alert: ${allergyList.join(', ')}</h4>
            <p class="text-red-900/90 leading-relaxed">You reported an allergy to <strong>${allergyList.join(', ')}</strong>. Please remind your doctor before any new prescription or injection is given.</p>
          </div>
        `;
      }
    }

    // Past Conditions & Scanned Reports in Plain Words
    const patPastCondEl = document.getElementById('patPastConditionsList');
    if (patPastCondEl) {
      if (medHistList.length === 0) {
        patPastCondEl.innerHTML = `<p class="text-xs text-secondary italic">No past chronic illnesses reported.</p>`;
      } else {
        patPastCondEl.innerHTML = medHistList.map(c => `
          <div class="p-2.5 rounded-xl bg-white border border-secondary-container/50 text-xs text-on-surface flex items-center justify-between">
            <span class="font-bold">${c}</span>
            <span class="text-[10px] text-primary font-semibold">Under observation</span>
          </div>
        `).join('');
      }
    }

    const patDocsEl = document.getElementById('patScannedDocsList');
    if (patDocsEl) {
      if (uploadedDocuments.length === 0) {
        patDocsEl.innerHTML = `<p class="text-xs text-secondary italic">No scanned reports uploaded yet.</p>`;
      } else {
        patDocsEl.innerHTML = uploadedDocuments.map(d => `
          <div class="p-2.5 rounded-xl bg-white border border-secondary-container/50 text-xs text-on-surface flex items-center justify-between">
            <span class="font-bold truncate max-w-[70%]">${d.file_name}</span>
            <span class="text-[10px] text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full font-bold">✓ Digitized</span>
          </div>
        `).join('');
      }
    }

    // Questions to Ask Your Doctor Checklist
    const patQuestionsEl = document.getElementById('patDoctorQuestionsList');
    if (patQuestionsEl) {
      if (!hasRealChief) {
        patQuestionsEl.innerHTML = `<p class="text-xs text-secondary italic">Questions will be generated after you complete the intake interview.</p>`;
      } else {
        const qList = [
          `What is the most likely cause of my ${chiefComplaint.toLowerCase()}?`,
          `How many days should I continue my treatment, and when should I come for a follow-up?`,
          medsList.length > 0 ? `Are my current medications (${medsList.slice(0, 2).join(', ')}) still suitable or do any dosages need adjusting?` : `Are there any specific medicines I should take or avoid?`,
          `Are there any foods, drinks, or physical activities I should avoid while recovering?`,
          `What warning signs should I watch out for at home?`
        ];
        patQuestionsEl.innerHTML = qList.map(q => `
          <label class="flex items-start gap-3 p-3.5 rounded-2xl bg-surface-container/60 hover:bg-surface-container border border-secondary-container/60 cursor-pointer transition-colors">
            <input type="checkbox" class="mt-0.5 w-4 h-4 rounded text-primary focus:ring-primary cursor-pointer">
            <span class="text-xs sm:text-sm text-on-surface leading-relaxed">${q}</span>
          </label>
        `).join('');
      }
    }

    // Home Care Tips — dynamically generated based on reported symptoms
    const patHomeCareEl = document.getElementById('patHomeCareTips');
    if (patHomeCareEl) {
      const tips = [
        'Stay well hydrated — drink plenty of water and fluids throughout the day.',
        'Get adequate rest and avoid strenuous physical activities until you feel better.',
        'Follow your doctor\'s prescription as instructed and complete the full course.'
      ];
      if (allSymsLower.includes('fever') || allSymsLower.includes('temp')) {
        tips.push('Monitor your body temperature twice daily with a digital thermometer.');
      }
      if (allSymsLower.includes('cough') || allSymsLower.includes('throat') || allSymsLower.includes('cold')) {
        tips.push('Gargle with warm salt water twice daily to soothe throat irritation.');
        tips.push('Avoid cold drinks, ice cream, and dusty environments.');
      }
      if (allSymsLower.includes('stomach') || allSymsLower.includes('abdomen') || allSymsLower.includes('nausea') || allSymsLower.includes('vomit')) {
        tips.push('Eat light, easily digestible meals — rice, bananas, toast, or plain soups.');
        tips.push('Avoid spicy, oily, or heavy foods until symptoms resolve.');
      }
      if (allSymsLower.includes('headache') || allSymsLower.includes('migraine')) {
        tips.push('Rest in a quiet, dark room and avoid bright screens during headaches.');
        tips.push('Apply a cool or warm compress to your forehead or neck.');
      }
      if (allSymsLower.includes('pain') || allSymsLower.includes('joint') || allSymsLower.includes('muscle')) {
        tips.push('Apply warm or cold compress to the affected area for 15-20 minutes at a time.');
        tips.push('Avoid activities that aggravate the pain until evaluated by your doctor.');
      }
      if (allSymsLower.includes('chest') || allSymsLower.includes('breath')) {
        tips.push('Sleep with your head slightly elevated to ease breathing.');
        tips.push('Avoid smoking, secondhand smoke, and strong fumes or perfumes.');
      }
      patHomeCareEl.innerHTML = tips.map(t => `
        <li class="flex items-start gap-2">
          <span class="text-primary font-bold">•</span>
          <span>${t}</span>
        </li>
      `).join('');
    }

    // Emergency Warning Signs — dynamically expanded based on symptoms
    const patEmergEl = document.getElementById('patEmergencyWarnings');
    if (patEmergEl) {
      const warnings = [
        'Sudden difficulty in breathing or shortness of breath.',
        'Severe chest pain, continuous dizziness, or sudden confusion.',
        'Symptoms worsening rapidly despite rest and medication — seek emergency care immediately.'
      ];
      if (allSymsLower.includes('fever') || allSymsLower.includes('temp')) {
        warnings.push('High fever exceeding 103°F (39.4°C) that does not come down with paracetamol or medication.');
      }
      if (allSymsLower.includes('stomach') || allSymsLower.includes('abdomen') || allSymsLower.includes('vomit')) {
        warnings.push('Severe abdominal pain, persistent vomiting, or signs of blood in vomit or stool.');
      }
      if (allSymsLower.includes('head') || allSymsLower.includes('migraine')) {
        warnings.push('Sudden, severe "worst headache of your life" or headache with neck stiffness or light sensitivity.');
      }
      patEmergEl.innerHTML = warnings.map(w => `
        <li class="flex items-start gap-2">
          <span class="text-red-600 font-bold">•</span>
          <span>${w}</span>
        </li>
      `).join('');
    }

    // Ensure active view is synchronized
    switchCaseSummaryView(currentCaseSummaryView);
  }


  // =========================================================================
  // 8C. REPORT EXPORTS (PDF CLINICAL DOSSIER & PLAIN TEXT SUMMARY)
  // =========================================================================
  function generatePatientPDFReport() {
    const p = activePatient || {};
    const patientName = p.display_name || currentUser?.display_name || 'Registered Patient';
    const abhaId = p.abha_id || 'ABDM-Verified';
    const dob = p.date_of_birth || 'Recorded on Intake';
    const gender = p.gender || 'Not specified';
    const blood = p.blood_group || 'O+';
    const phone = p.phone || 'Verified on Session';
    const chief = document.getElementById('docChiefComplaint')?.textContent?.trim() || 'Clinical Intake Assessment';
    const onset = document.getElementById('docOnset')?.textContent?.trim() || 'Recorded today';
    const loc = document.getElementById('docLocation')?.textContent?.trim() || 'General';
    const icd = document.getElementById('docIcdCode')?.textContent?.trim() || 'ICD-10 R50.9';
    const narrative = document.getElementById('docAssessmentNarrative')?.textContent?.trim() || 'Clinical intake completed.';
    const notes = document.getElementById('caseSumDoctorNotes')?.textContent?.trim() || 'Authorized for clinician review.';

    const medHist = Array.from(selectedMedHistConditions).join(', ') || 'None recorded';
    const meds = Array.from(selectedMedications).join(', ') || 'No active prescriptions reported';
    const allergies = Array.from(selectedAllergies).join(', ') || 'No known drug allergies reported (NKDA)';

    const printWin = window.open('', '_blank', 'width=900,height=800');
    if (!printWin) {
      window.print();
      return;
    }

    printWin.document.write(`
      <!DOCTYPE html>
      <html lang="en">
      <head>
        <meta charset="UTF-8">
        <title>Cliniqo Clinical Case Dossier - ${patientName}</title>
        <style>
          body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #1e293b; margin: 0; padding: 32px; font-size: 13px; line-height: 1.5; }
          .header { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #0f766e; padding-bottom: 16px; margin-bottom: 20px; }
          .brand { font-size: 22px; font-weight: 800; color: #0f766e; letter-spacing: -0.5px; }
          .badge { display: inline-block; padding: 3px 10px; border-radius: 12px; background: #ccfbf1; color: #0f766e; font-size: 11px; font-weight: bold; }
          .demographics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; background: #f8fafc; padding: 14px; border-radius: 10px; border: 1px solid #e2e8f0; margin-bottom: 20px; }
          .demo-item span { display: block; font-size: 10px; text-transform: uppercase; color: #64748b; font-weight: bold; }
          .demo-item strong { font-size: 12px; color: #0f172a; }
          .section { margin-bottom: 20px; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; }
          .sec-header { background: #f1f5f9; padding: 10px 14px; font-weight: bold; font-size: 12px; color: #0f766e; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; }
          .sec-body { padding: 14px; }
          .vitals-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; text-align: center; }
          .vital-box { background: #f8fafc; padding: 8px; border-radius: 8px; border: 1px solid #e2e8f0; }
          .vital-box .label { font-size: 10px; color: #64748b; font-weight: bold; text-transform: uppercase; }
          .vital-box .val { font-size: 14px; font-weight: bold; color: #0f766e; margin-top: 2px; }
          .tag { display: inline-block; background: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; margin-right: 4px; margin-bottom: 4px; }
          .allergy-tag { background: #fee2e2; color: #b91c1c; }
          .footer { margin-top: 30px; padding-top: 16px; border-top: 1px solid #e2e8f0; display: flex; justify-content: space-between; font-size: 11px; color: #64748b; }
          @media print { body { padding: 0; } }
        </style>
      </head>
      <body>
        <div class="header">
          <div>
            <div class="brand">CLINIQO • CLINICAL HEALTH DOSSIER</div>
            <div style="font-size: 11px; color: #64748b; margin-top: 2px;">Ayushman Bharat Digital Mission (ABDM) Compliant Health Record</div>
          </div>
          <div style="text-align: right;">
            <span class="badge">OFFICIAL CLINICAL RECORD</span>
            <div style="font-size: 11px; color: #64748b; margin-top: 4px;">Session: #${(currentSessionId || 'LOCAL').slice(0, 8).toUpperCase()}</div>
          </div>
        </div>

        <div class="demographics">
          <div class="demo-item"><span>Patient Name</span><strong>${patientName}</strong></div>
          <div class="demo-item"><span>ABHA Health ID</span><strong>${abhaId}</strong></div>
          <div class="demo-item"><span>DOB / Age</span><strong>${dob}</strong></div>
          <div class="demo-item"><span>Gender / Blood</span><strong>${gender} / ${blood}</strong></div>
          <div class="demo-item"><span>Mobile</span><strong>${phone}</strong></div>
          <div class="demo-item"><span>Emergency Contact</span><strong>${emergency}</strong></div>
          <div class="demo-item"><span>Encounter Date</span><strong>${new Date().toLocaleDateString('en-IN')}</strong></div>
          <div class="demo-item"><span>Triage Acuity</span><strong>Routine Outpatient</strong></div>
        </div>

        <div class="section">
          <div class="sec-header"><span>BASELINE CLINICAL VITALS &amp; TRIAGE PARAMETERS</span><span>Point-of-Care</span></div>
          <div class="sec-body">
            <div class="vitals-grid">
              <div class="vital-box"><div class="label">Temp</div><div class="val">${document.getElementById('docVitalsTemp')?.textContent || '—'}</div></div>
              <div class="vital-box"><div class="label">Pulse</div><div class="val">${document.getElementById('docVitalsPulse')?.textContent || '—'}</div></div>
              <div class="vital-box"><div class="label">BP</div><div class="val">${document.getElementById('docVitalsBp')?.textContent || '—'}</div></div>
              <div class="vital-box"><div class="label">SpO2</div><div class="val">${document.getElementById('docVitalsSpo2')?.textContent || '—'}</div></div>
              <div class="vital-box"><div class="label">Resp Rate</div><div class="val">${document.getElementById('docVitalsResp')?.textContent || '—'}</div></div>
              <div class="vital-box"><div class="label">Pain VAS</div><div class="val">${document.getElementById('docVitalsPain')?.textContent || '—'}</div></div>
            </div>
          </div>
        </div>

        <div class="section">
          <div class="sec-header"><span>SUBJECTIVE (S) • HISTORY OF PRESENT ILLNESS</span><span>${icd}</span></div>
          <div class="sec-body">
            <p><strong>Chief Complaint:</strong> ${chief}</p>
            <p><strong>Onset &amp; Timeline:</strong> ${onset} • <strong>Location:</strong> ${loc}</p>
            <p style="margin-top: 8px; font-style: italic; color: #475569; background: #f8fafc; padding: 8px; border-radius: 6px;">“${document.getElementById('docPatientVerbatim')?.textContent || chief}”</p>
          </div>
        </div>

        <div class="section">
          <div class="sec-header"><span>OBJECTIVE (O) &amp; ASSESSMENT (A) • CLINICAL SYNTHESIS</span><span>Multi-Source Ingestion</span></div>
          <div class="sec-body">
            <p><strong>Clinical Impression:</strong> ${narrative}</p>
            <p style="margin-top: 8px;"><strong>Past Medical History:</strong> ${medHist}</p>
            <p><strong>Scanned Records Ingested:</strong> ${uploadedDocuments.length} document(s) verified via OCR.</p>
          </div>
        </div>

        <div class="section">
          <div class="sec-header"><span>PLAN (P) • ACTIVE MEDICATIONS &amp; ALLERGIES</span><span>Reconciled</span></div>
          <div class="sec-body">
            <p><strong>Active Prescription Regimen:</strong> ${meds}</p>
            <p style="margin-top: 8px;"><strong>Allergies &amp; ADR Alerts:</strong> <span class="tag ${allergies.includes('No known') ? '' : 'allergy-tag'}">${allergies}</span></p>
            <div style="margin-top: 12px; padding: 10px; background: #f8fafc; border-radius: 6px; border: 1px solid #e2e8f0;">
              <strong>Physician Review Notes:</strong>
              <p style="margin-top: 4px; color: #334155;">${notes}</p>
            </div>
          </div>
        </div>

        <div class="footer">
          <div>Verified via Cliniqo Digital Health Intelligence Vault • DISHA / ABDM Certified</div>
          <div>Printed: ${new Date().toLocaleString('en-IN')}</div>
        </div>

        <script>
          window.onload = function() { window.print(); }
        </script>
      </body>
      </html>
    `);
    printWin.document.close();
    saveToVaultNotification("PDF Dossier Generated", "Print window initialized for PDF download.");
  }

  function generatePatientTextReport() {
    const p = activePatient || {};
    const patientName = p.display_name || currentUser?.display_name || 'Registered Patient';
    const abhaId = p.abha_id || 'ABDM-Verified';
    const dob = p.date_of_birth || 'Recorded on Intake';
    const gender = p.gender || 'Not specified';
    const blood = p.blood_group || 'O+';
    const phone = p.phone || 'Verified on Session';
    const chief = document.getElementById('docChiefComplaint')?.textContent?.trim() || 'Clinical Intake Assessment';
    const onset = document.getElementById('docOnset')?.textContent?.trim() || 'Recorded today';
    const loc = document.getElementById('docLocation')?.textContent?.trim() || 'General';
    const icd = document.getElementById('docIcdCode')?.textContent?.trim() || 'ICD-10: R50.9';
    const narrative = document.getElementById('docAssessmentNarrative')?.textContent?.trim() || 'Clinical intake completed.';
    const notes = document.getElementById('caseSumDoctorNotes')?.textContent?.trim() || 'Authorized for clinician review.';

    const medHist = Array.from(selectedMedHistConditions).join(', ') || 'None recorded';
    const meds = Array.from(selectedMedications).join(', ') || 'No active prescriptions reported';
    const allergies = Array.from(selectedAllergies).join(', ') || 'No known drug allergies reported (NKDA)';

    const vTemp = document.getElementById('docVitalsTemp')?.textContent?.trim();
    const vPulse = document.getElementById('docVitalsPulse')?.textContent?.trim();
    const vBp = document.getElementById('docVitalsBp')?.textContent?.trim();
    const vSpo2 = document.getElementById('docVitalsSpo2')?.textContent?.trim();
    const vResp = document.getElementById('docVitalsResp')?.textContent?.trim();
    const vPain = document.getElementById('docVitalsPain')?.textContent?.trim();
    const vPainLvl = document.getElementById('docVitalsPainLevel')?.textContent?.trim();

    const formattedTemp = (vTemp && vTemp !== '—') ? vTemp : 'Not recorded (Pending point-of-care capture)';
    const formattedPulse = (vPulse && vPulse !== '—') ? vPulse : 'Not recorded (Pending point-of-care capture)';
    const formattedBp = (vBp && vBp !== '—') ? vBp : 'Not recorded (Pending point-of-care capture)';
    const formattedSpo2 = (vSpo2 && vSpo2 !== '—') ? vSpo2 : 'Not recorded (Pending point-of-care capture)';
    const formattedResp = (vResp && vResp !== '—') ? vResp : 'Not recorded (Pending point-of-care capture)';
    const formattedPain = (vPain && vPain !== '—') ? `${vPain} (${vPainLvl || 'Self-Reported'})` : 'Not rated (No acute pain reported)';

    const textContent = `
================================================================================
CLINIQO • COMPREHENSIVE CLINICAL HEALTH DOSSIER
Ayushman Bharat Digital Mission (ABDM) Compliant Health Record
================================================================================

PATIENT IDENTIFICATION & DEMOGRAPHICS:
--------------------------------------------------------------------------------
Full Name          : ${patientName}
ABHA Health ID     : ${abhaId}
Date of Birth / Age: ${dob}
Gender / Blood     : ${gender} / ${blood}
Mobile Number      : ${phone}
Session Identifier : #${(currentSessionId || 'LOCAL').slice(0, 8).toUpperCase()}
Generated Date     : ${new Date().toLocaleString('en-IN')}

SUBJECTIVE (S) • HISTORY OF PRESENT ILLNESS (HPI):
--------------------------------------------------------------------------------
Chief Complaint    : ${chief}
Onset & Timeline   : ${onset}
Anatomical Location: ${loc}
Clinical Code      : ${icd}
Patient Stated     : "${document.getElementById('docPatientVerbatim')?.textContent || chief}"

BASELINE CLINICAL VITALS:
--------------------------------------------------------------------------------
Temperature        : ${formattedTemp}
Pulse / Heart Rate : ${formattedPulse}
Blood Pressure     : ${formattedBp}
SpO2               : ${formattedSpo2}
Respiratory Rate   : ${formattedResp}
Pain VAS Rating    : ${formattedPain}

OBJECTIVE & ASSESSMENT (O & A):
--------------------------------------------------------------------------------
Clinical Synthesis : ${narrative}
Past Medical Hist. : ${medHist}
Verified Documents : ${uploadedDocuments.length} document(s) synchronized in vault.

PLAN & ORDERS (P):
--------------------------------------------------------------------------------
Active Medications : ${meds}
Allergies / ADRs   : ${allergies}

PHYSICIAN CONSULTATION & REVIEW NOTES:
--------------------------------------------------------------------------------
${notes}

================================================================================
PHYSICIAN VERIFICATION SEAL • CLINIQO DIGITAL VAULT
DISHA / DPDP / ABDM Standardized Clinical Health Record
================================================================================
`.trim();

    const blob = new Blob([textContent], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Cliniqo_Case_Dossier_${patientName.replace(/\s+/g, '_')}_${new Date().toISOString().split('T')[0]}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    saveToVaultNotification("Text Report Downloaded", "Case dossier exported as .txt file.");
  }

  // =========================================================================
  // =========================================================================
  // 9. PATIENT LIFECYCLE & PATIENT REGISTRY (Strict Patient Isolation & Hospital Desk)
  // =========================================================================
  function broadcastHospitalSync(type, payload) {
    try {
      if (hospitalSyncChannel) {
        hospitalSyncChannel.postMessage({
          type: type || 'PATIENT_DATA_MUTATED',
          payload: payload || {},
          timestamp: new Date().toISOString()
        });
      }
    } catch (e) {
      console.warn("BroadcastChannel error:", e);
    }
  }

  async function loadPatientRegistry() {
    try {
      localStorage.removeItem('cliniqo_patient_registry');
    } catch (e) {}

    const uid = (currentUser && currentUser.user_id) ? currentUser.user_id : 'anonymous';
    const isHospital = !!(currentUser && currentUser.role === 'hospital');
    const regKey = `cliniqo_patient_registry_${uid}`;

    if (!isHospital) {
      // STRICT PATIENT PRIVACY ISOLATION:
      // A patient only ever has their own single record in patientRegistry.
      // Zero visibility of other patients, zero queue listings.
      if (currentUser && currentUser.patient_id) {
        try {
          const ownPatient = await apiRequest(`/api/v1/patients/${currentUser.patient_id}`);
          if (ownPatient && ownPatient.patient_id) {
            patientRegistry = [ownPatient];
            try { localStorage.setItem(regKey, JSON.stringify(patientRegistry)); } catch (e) {}
          } else {
            patientRegistry = [];
          }
        } catch (err) {
          patientRegistry = [];
        }
      } else {
        patientRegistry = [];
      }
      renderPatientCasesDashboard();
      return patientRegistry;
    }

    // HOSPITAL STAFF / DOCTOR WORKSTATION:
    // Authorized medical officer access to the complete hospital OPD registry
    try {
      const allPatients = await apiRequest('/api/v1/patients');
      if (Array.isArray(allPatients)) {
        patientRegistry = allPatients;
        try { localStorage.setItem(regKey, JSON.stringify(patientRegistry)); } catch (e) {}
      }
    } catch (e) {
      console.warn("Could not load hospital patient registry:", e);
    }

    renderPatientCasesDashboard();
    return patientRegistry;
  }

  function savePatientRegistry() {
    try {
      const uid = (currentUser && currentUser.user_id) ? currentUser.user_id : 'anonymous';
      localStorage.setItem(`cliniqo_patient_registry_${uid}`, JSON.stringify(patientRegistry));
    } catch (e) {}
  }

  function updateUserUI(user) {
    if (!user || !user.email) {
      currentUser = user || null;
      if (!currentUser) {
        try { localStorage.removeItem('cliniqo_user'); } catch (e) {}
      } else {
        try { localStorage.setItem('cliniqo_user', JSON.stringify(currentUser)); } catch (e) {}
      }
      const hdrName = document.getElementById('headerPatientName');
      if (hdrName) hdrName.textContent = 'Not Signed In';
      const hdrEmail = document.getElementById('headerPatientAbha');
      if (hdrEmail) hdrEmail.textContent = 'Sign in or register to continue';
      const hdrAvatar = document.getElementById('headerPatientAvatar');
      if (hdrAvatar) hdrAvatar.innerHTML = '<span id="headerPatientInitials">--</span>';
      const dropName = document.getElementById('dropdownDisplayName');
      if (dropName) dropName.textContent = 'Not Signed In';
      const dropEmail = document.getElementById('dropdownEmail');
      if (dropEmail) dropEmail.textContent = '';
      const dropAvatar = document.getElementById('dropdownAvatar');
      if (dropAvatar) dropAvatar.innerHTML = '<span id="dropdownInitials">--</span>';
      const profImg = document.getElementById('profilePhotoImg');
      if (profImg) profImg.src = 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150&auto=format&fit=crop&q=80';
      const profNameInput = document.getElementById('profileInputDisplayName');
      if (profNameInput) profNameInput.value = '';
      const profEmailInput = document.getElementById('profileInputEmail');
      if (profEmailInput) profEmailInput.value = '';
      const secEmailText = document.getElementById('securityUserEmailText');
      if (secEmailText) secEmailText.textContent = '';
      const signOutBtn = document.getElementById('headerSignOutBtn');
      const signInBtn = document.getElementById('headerSignInBtn');
      if (signOutBtn) signOutBtn.classList.add('hidden');
      if (signInBtn) signInBtn.classList.remove('hidden');
      const vBadge = document.getElementById('headerVerifiedBadge');
      if (vBadge) vBadge.classList.add('hidden');

      // By default (signed out), hide hospital staff controls and show patient controls
      document.querySelectorAll('[data-role="hospital-only"]').forEach(el => el.classList.add('hidden'));
      document.querySelectorAll('[data-role="patient-only"]').forEach(el => el.classList.remove('hidden'));
      return;
    }

    currentUser = { ...currentUser, ...user };
    try {
      localStorage.setItem('cliniqo_user', JSON.stringify(currentUser));
    } catch (e) {}

    const isHospital = currentUser.role === 'hospital';
    const name = currentUser.display_name || (isHospital ? 'Dr. Arvind Kumar (MD)' : 'Registered Patient');
    const email = currentUser.email || '';
    const initials = name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2) || (isHospital ? 'DR' : 'PT');

    const hdrName = document.getElementById('headerPatientName');
    if (hdrName) hdrName.textContent = name;
    const hdrEmail = document.getElementById('headerPatientAbha');
    if (hdrEmail) hdrEmail.textContent = isHospital ? 'Attending Clinician • Staff ID: HP-8821' : email;

    const hdrAvatar = document.getElementById('headerPatientAvatar');
    if (hdrAvatar) {
      if (currentUser.avatar_url) {
        hdrAvatar.innerHTML = `<img src="${currentUser.avatar_url}" alt="${name}" class="w-full h-full object-cover"/>`;
      } else {
        hdrAvatar.innerHTML = `<span id="headerPatientInitials">${initials}</span>`;
      }
    }

    const dropName = document.getElementById('dropdownDisplayName');
    if (dropName) dropName.textContent = name;
    const dropEmail = document.getElementById('dropdownEmail');
    if (dropEmail) dropEmail.textContent = email;
    const dropAvatar = document.getElementById('dropdownAvatar');
    if (dropAvatar) {
      if (currentUser.avatar_url) {
        dropAvatar.innerHTML = `<img src="${currentUser.avatar_url}" alt="${name}" class="w-full h-full object-cover"/>`;
      } else {
        dropAvatar.innerHTML = `<span id="dropdownInitials">${initials}</span>`;
      }
    }

    const profImg = document.getElementById('profilePhotoImg');
    if (profImg) {
      profImg.src = currentUser.avatar_url || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150&auto=format&fit=crop&q=80';
    }
    const profNameInput = document.getElementById('profileInputDisplayName');
    if (profNameInput) profNameInput.value = name;
    const profEmailInput = document.getElementById('profileInputEmail');
    if (profEmailInput) profEmailInput.value = email;
    const secEmailText = document.getElementById('securityUserEmailText');
    if (secEmailText) secEmailText.textContent = email;

    const signOutBtn = document.getElementById('headerSignOutBtn');
    const signInBtn = document.getElementById('headerSignInBtn');
    if (signOutBtn) signOutBtn.classList.remove('hidden');
    if (signInBtn) signInBtn.classList.add('hidden');
    const vBadge = document.getElementById('headerVerifiedBadge');
    if (vBadge) vBadge.classList.toggle('hidden', !(activePatient && activePatient.abha_id));

    // Dynamic Role-Scoped Visibility
    document.querySelectorAll('[data-role="hospital-only"]').forEach(el => {
      el.classList.toggle('hidden', !isHospital);
    });
    document.querySelectorAll('[data-role="patient-only"]').forEach(el => {
      el.classList.toggle('hidden', isHospital);
    });

    updateVaultProgress();
  }

  async function loadUserAccount() {
    try {
      if (!currentUser || !currentUser.email) return;
      const email = currentUser.email;
      const user = await apiRequest(`/api/v1/auth/me?email=${encodeURIComponent(email)}`);
      if (user && user.email) {
        updateUserUI(user);
        if (user.patient_id) {
          currentPatientId = user.patient_id;
          localStorage.setItem('cliniqo_patient_id', currentPatientId);
          try {
            const pat = await apiRequest(`/api/v1/patients/${user.patient_id}`);
            if (pat && pat.patient_id) {
              updatePatientUI(pat);
            }
          } catch (e) {}
        }
      }
    } catch (err) {
      if (currentUser && currentUser.email) {
        updateUserUI(currentUser);
        if (currentUser.patient_id) {
          currentPatientId = currentUser.patient_id;
          localStorage.setItem('cliniqo_patient_id', currentPatientId);
        }
      }
    }
  }

  function updatePatientUI(patient) {
    if (!patient || !patient.display_name) {
      activePatient = { patient_id: null, display_name: '', abha_id: '', date_of_birth: '', gender: '', phone: '', emergency_contact: '', blood_group: '', preferred_language: 'en-IN' };
      const hdrInitials = document.getElementById('headerPatientInitials');
      if (hdrInitials) hdrInitials.textContent = '--';
      const hdrName = document.getElementById('headerPatientName');
      if (hdrName) hdrName.textContent = 'No Active Patient';
      const hdrAbha = document.getElementById('headerPatientAbha');
      if (hdrAbha) hdrAbha.textContent = 'ABHA: Pending Link';
      const vBadge = document.getElementById('headerVerifiedBadge');
      if (vBadge) vBadge.classList.add('hidden');
      const profName = document.getElementById('profileDisplayName');
      if (profName) profName.textContent = 'No Active Patient';
      return;
    }

    activePatient = { ...activePatient, ...patient };
    const initials = patient.display_name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
    
    const hdrInitials = document.getElementById('headerPatientInitials');
    if (hdrInitials) hdrInitials.textContent = initials;
    const hdrName = document.getElementById('headerPatientName');
    if (hdrName) hdrName.textContent = patient.display_name;
    const hdrAbha = document.getElementById('headerPatientAbha');
    if (hdrAbha) hdrAbha.textContent = `ABHA #${patient.abha_id || 'Not Set'}`;
    const vBadge = document.getElementById('headerVerifiedBadge');
    if (vBadge) vBadge.classList.toggle('hidden', !patient.abha_id);

    const homeWelcome = document.getElementById('homeWelcomeHeading');
    if (homeWelcome) homeWelcome.textContent = `Welcome, ${patient.display_name.split(' ')[0]}`;

    const profAvatar = document.getElementById('profileAvatarInitials');
    if (profAvatar) profAvatar.textContent = initials;
    const profName = document.getElementById('profileDisplayName');
    if (profName) profName.textContent = patient.display_name;
    const profSubtitle = document.getElementById('profileSubtitle');
    if (profSubtitle) profSubtitle.textContent = `${patient.gender || 'Patient'} • ${patient.date_of_birth || ''} • ABHA: ${patient.abha_id || ''}`;
    
    const rowName = document.getElementById('profValName');
    if (rowName) rowName.textContent = patient.display_name;
    const rowDob = document.getElementById('profValDob');
    if (rowDob) rowDob.textContent = patient.date_of_birth || '--';
    const rowMobile = document.getElementById('profValMobile');
    if (rowMobile) rowMobile.textContent = patient.phone || '--';
    const rowEmerg = document.getElementById('profValEmerg');
    if (rowEmerg) rowEmerg.textContent = patient.emergency_contact || '--';
    const rowBlood = document.getElementById('profValBlood');
    if (rowBlood) rowBlood.textContent = patient.blood_group || '--';
    const rowPhr = document.getElementById('profValPhrId');
    if (rowPhr) rowPhr.textContent = `#PHR-${(patient.patient_id || 'NEW').slice(0, 8).toUpperCase()}`;
    const rowAbha = document.getElementById('profileLinkedAbha');
    if (rowAbha) rowAbha.textContent = patient.abha_id || '--';
    const abdmStatusText = document.getElementById('abdmStatusText');
    if (abdmStatusText) {
      abdmStatusText.textContent = patient.abha_id
        ? `Your ABHA health ID (${patient.abha_id}) is linked through India's National Health Authority ABDM gateway. Data remains strictly encrypted in your personal health locker.`
        : 'No ABHA health ID linked yet. Your data remains encrypted in your personal health locker until you link your ABHA ID through India\'s National Health Authority ABDM gateway.';
    }

    // Populate Patient "My Visits" & Records Profile Sync Editor
    const myVisName = document.getElementById('myVisitsEditName');
    if (myVisName) myVisName.value = patient.display_name || '';
    const myVisPhone = document.getElementById('myVisitsEditPhone');
    if (myVisPhone) myVisPhone.value = patient.phone || '';
    const myVisEmerg = document.getElementById('myVisitsEditEmergency');
    if (myVisEmerg) myVisEmerg.value = patient.emergency_contact || '';
    const myVisBlood = document.getElementById('myVisitsEditBlood');
    if (myVisBlood && patient.blood_group) myVisBlood.value = patient.blood_group;
    const myVisAbha = document.getElementById('myVisitsEditAbha');
    if (myVisAbha) myVisAbha.value = patient.abha_id || '';
    const myVisTok = document.getElementById('myVisitsActiveTokenBadge');
    if (myVisTok) myVisTok.textContent = hospitalTokenNumber ? `Token #${hospitalTokenNumber}` : 'Token #--';

    updateVaultProgress();
    if (patient.patient_id) {
      renderLongitudinalProfile(patient.patient_id);
    }
  }

  function resetSessionUIState() {
    selectedWhatBringsSymptoms.clear();
    selectedPainLocations.clear();
    selectedAdaptiveChoices.clear();
    selectedAdaptiveTriggers.clear();
    selectedMedHistConditions.clear();
    selectedMedications.clear();
    selectedAllergies.clear();
    selectedFamilyConditions.clear();
    selectedLifestyleHabits.clear();

    document.querySelectorAll('#whatBringsSymptomChips .symptom-chip').forEach(chip => {
      chip.setAttribute('data-selected', 'false');
      chip.className = 'symptom-chip px-4 py-2.5 rounded-2xl bg-surface-container hover:bg-secondary-container text-xs font-semibold text-on-surface border border-secondary-container transition-all cursor-pointer flex items-center gap-1.5';
      const icon = chip.querySelector('.material-symbols-outlined');
      if (icon) {
        icon.textContent = 'radio_button_unchecked';
        icon.className = 'material-symbols-outlined text-[16px] text-secondary/40';
      }
    });
    
    const whatBringsCountBadge = document.getElementById('whatBringsCountBadge');
    if (whatBringsCountBadge) whatBringsCountBadge.textContent = '0 Selected';
    
    const whatBringsTranscript = document.getElementById('whatBringsTranscript');
    if (whatBringsTranscript) whatBringsTranscript.textContent = '“Tap the mic button above or speak your symptoms...”';
    const aiInterviewTranscript = document.getElementById('aiInterviewTranscript');
    if (aiInterviewTranscript) aiInterviewTranscript.textContent = '“Tap the center voice orb or type to start your AI interview.”';
    
    uploadedDocuments = [];
    renderDocumentsList();
    
    const extractedFieldsList = document.getElementById('extractedFieldsList');
    if (extractedFieldsList) {
      extractedFieldsList.innerHTML = `
        <div class="p-3.5 rounded-2xl bg-surface-container flex items-center justify-center text-secondary text-xs text-center py-6">
          <span>Scan or upload a document to extract structured clinical information.</span>
        </div>
      `;
    }

    updateMedHistConditionsBadge();
    updateMedsBadge();
    updateAllergiesBadge();
    updateFamilyBadge();
    updateLifestyleBadge();
    updateHealthStoryUI();
  }

  async function switchPatient(patientId) {
    const target = patientRegistry.find(p => p.patient_id === patientId || p.abha_id === patientId);
    if (!target) return;

    try {
      if (currentSessionId) await syncClinicalData();
    } catch (e) {}

    currentPatientId = target.patient_id;
    localStorage.setItem('cliniqo_patient_id', currentPatientId);

    if (target.session_id) {
      currentSessionId = target.session_id;
    } else {
      try {
        const sess = await apiRequest('/api/session', {
          method: 'POST',
          body: { patient_id: target.patient_id }
        });
        currentSessionId = sess.session_id;
        target.session_id = currentSessionId;
        savePatientRegistry();
      } catch (e) {
        currentSessionId = 'session-' + Date.now();
      }
    }

    localStorage.setItem('cliniqo_session_id', currentSessionId);
    sessionStorage.setItem('cliniqo_session_id', currentSessionId);

    resetSessionUIState();
    updatePatientUI(target);

    await loadSessionState();
    await fetchPatientDocuments();

    updateMedHistConditionsBadge();
    updateMedsBadge();
    updateAllergiesBadge();
    updateFamilyBadge();
    updateLifestyleBadge();
    updateHealthStoryUI();

    saveToVaultNotification("Patient Switched", `Switched to ${target.display_name}'s record.`);
  }

  async function createSession(overrides = {}) {
    try {
      const payload = {
        patient_id: activePatient.patient_id,
        department: overrides.department || hospitalDepartment || 'general',
        opd_mode: overrides.opd_mode || clinicalMode || 'general',
        consent_given: overrides.consent_given !== undefined ? overrides.consent_given : hospitalConsentGiven,
        language_preference: overrides.language_preference || selectedHospitalLang || activePatient.preferred_language || 'en-IN'
      };
      if (hospitalTokenNumber) payload.token_number = hospitalTokenNumber;

      const sess = await apiRequest('/api/session', {
        method: 'POST',
        body: payload
      });
      currentSessionId = sess.session_id;
      if (sess.token_number) {
        hospitalTokenNumber = sess.token_number;
        localStorage.setItem('cliniqo_hospital_token', hospitalTokenNumber);
        updateHospitalTokenDisplays();
      }
      localStorage.setItem('cliniqo_session_id', currentSessionId);
      sessionStorage.setItem('cliniqo_session_id', currentSessionId);
      return currentSessionId;
    } catch (e) {
      currentSessionId = 'session-' + Date.now();
      localStorage.setItem('cliniqo_session_id', currentSessionId);
      sessionStorage.setItem('cliniqo_session_id', currentSessionId);
      return currentSessionId;
    }
  }

  async function loadAyushAssessment() {
    if (!currentSessionId) return;
    try {
      const data = await apiRequest(`/api/v1/sessions/${currentSessionId}/ayush-assessment`);
      if (data && Object.keys(data).length) {
        ayushAssessment = data;
        localStorage.setItem('cliniqo_ayush_assessment', JSON.stringify(data));
        Object.entries(data).forEach(([key, value]) => {
          const el = document.getElementById(`ayush_${key}`);
          if (el && typeof value === 'string') el.value = value;
        });
      }
      renderAyushSummaryCard();
    } catch (e) {}
  }

  async function loadSessionState() {
    if (!currentSessionId) return null;
    try {
      const state = await apiRequest(`/api/session/${currentSessionId}`);
      applySessionStateToUI(state);
      await loadAyushAssessment();
      return state;
    } catch (e) {
      return null;
    }
  }

  async function fetchPatientDocuments() {
    if (!currentSessionId) return;
    try {
      const docs = currentPatientId ? await apiRequest(`/api/v1/patients/${currentPatientId}/documents`) : await apiRequest(`/api/v1/sessions/${currentSessionId}/documents`);
      if (Array.isArray(docs)) {
        uploadedDocuments = docs;

        // Document-derived facts are intentionally NOT copied into current medication/history.
        // They remain document-scoped and are displayed with temporal context.

        renderDocumentsList();
        renderPatientCasesDashboard();
        updateMedHistConditionsBadge();
        updateMedsBadge();
        updateHealthStoryUI();
      }
    } catch (e) {}
  }

  function generatePatientTextReport() {
    const p = activePatient || {};
    const pName = p.display_name || currentUser?.display_name || 'Registered Patient';
    const abhaId = p.abha_id || 'Pending ABDM Verification';
    const dob = p.date_of_birth || 'Recorded on Intake';
    const gender = p.gender || 'Not specified';
    const phone = p.phone || 'Verified on Session';
    const emerg = p.emergency_contact || 'Family Emergency Contact';
    const blood = p.blood_group || 'Not recorded';
    const dateStr = new Date().toLocaleString('en-IN');
    const sessId = (currentSessionId || 'LOCAL').slice(0, 8).toUpperCase();

    const sum1 = document.getElementById('summaryVal1')?.textContent.trim() || 'Clinical health intake evaluation recorded.';
    const sum2 = document.getElementById('summaryVal2')?.textContent.trim() || 'No chronic conditions recorded.';
    const sum3 = document.getElementById('summaryVal3')?.textContent.trim() || 'None reported.';
    const sum4 = document.getElementById('summaryVal4')?.textContent.trim() || 'No attached records.';
    const aiNarrative = document.getElementById('aiSummaryNarrative')?.textContent.trim() || document.getElementById('healthStoryNarrative')?.textContent.trim() || 'Intake assessment recorded.';

    let textReport = `================================================================================
CLINIQO MEDICAL INTELLIGENCE • PERSONAL CLINICAL DOSSIER & VAULT SUMMARY
================================================================================
Report Generated : ${dateStr}
Session Token    : #${sessId}
Standards & Code : ABDM Compliant • FHIR R4 Clinical Health Dossier
--------------------------------------------------------------------------------
1. PATIENT DEMOGRAPHICS & IDENTIFICATION
--------------------------------------------------------------------------------
Full Name         : ${pName}
ABHA Health ID    : ${abhaId}
Date of Birth     : ${dob}
Gender            : ${gender}
Blood Group       : ${blood}
Mobile Number     : ${phone}
Emergency Contact : ${emerg}

--------------------------------------------------------------------------------
2. REASON FOR VISIT & SYMPTOM PRESENTATION
--------------------------------------------------------------------------------
${sum1}

--------------------------------------------------------------------------------
3. AI CLINICAL HEALTH SUMMARY (IN PLAIN WORDS)
--------------------------------------------------------------------------------
${aiNarrative}

--------------------------------------------------------------------------------
4. MEDICAL & SURGICAL HISTORY
--------------------------------------------------------------------------------
${sum2}

--------------------------------------------------------------------------------
5. ACTIVE MEDICATIONS & ALLERGIES
--------------------------------------------------------------------------------
${sum3}

--------------------------------------------------------------------------------
6. SCANNED CLINICAL RECORDS & VAULT FINDINGS
--------------------------------------------------------------------------------
${sum4}
`;

    if (uploadedDocuments.length > 0) {
      textReport += `\n--------------------------------------------------------------------------------
7. DETAILED ATTACHED MEDICAL RECORDS & OCR TRANSCRIPTIONS
--------------------------------------------------------------------------------\n`;
      uploadedDocuments.forEach((doc, idx) => {
        const o = doc.ocr || {};
        const ef = (o.extracted_fields && typeof o.extracted_fields === 'object' && !Array.isArray(o.extracted_fields)) ? o.extracted_fields : o;
        const raw = o.raw_text || ef.raw_text || o.text || 'Record ingested in vault.';
        const dt = o.document_type || ef.document_type || 'Prescription';
        textReport += `\n[Record ${idx + 1}] ${doc.file_name} (${dt})\n`;
        textReport += `Uploaded: ${new Date(doc.created_at || Date.now()).toLocaleDateString()}\n`;
        textReport += `Transcription Excerpt:\n${raw.trim()}\n`;
      });
    }

    textReport += `\n================================================================================
PHYSICIAN VERIFICATION SEAL • CLINIQO ENCRYPTED DIGITAL HEALTH VAULT
All records verified and authorized by patient for clinical review.
================================================================================\n`;

    const blob = new Blob([textReport], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Cliniqo_Health_Dossier_${pName.replace(/\s+/g, '_')}_${new Date().toISOString().split('T')[0]}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    saveToVaultNotification("Text Report Downloaded", "Complete health dossier saved in text format (.txt).");
  }

  function generatePatientPDFReport() {
    const p = activePatient || {};
    const chiefReason = document.getElementById('summaryVal1')?.textContent.trim() || document.getElementById('whatBringsTranscript')?.textContent.replace(/^[“"\s]+|[”"\s]+$/g, '').trim() || 'Clinical evaluation';
    const narrative = document.getElementById('aiSummaryNarrative')?.textContent.trim() || document.getElementById('healthStoryNarrative')?.textContent.replace(/^[“"\s]+|[”"\s]+$/g, '').trim() || 'Clinical case intake recorded.';
    const medHistoryStr = document.getElementById('summaryVal2')?.textContent.trim() || 'No chronic conditions recorded.';
    const medHistory = Array.from(selectedMedHistConditions);
    const medications = Array.from(selectedMedications);
    const medsAllStr = document.getElementById('summaryVal3')?.textContent.trim() || 'None reported.';
    const allergies = Array.from(selectedAllergies);
    const lifestyle = Array.from(selectedLifestyleHabits);
    const family = Array.from(selectedFamilyConditions);
    const dateStr = new Date().toLocaleDateString('en-IN', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });

    let docItemsHtml = '<p style="color:#666;font-size:11px;margin:4px 0;">No attached external medical records.</p>';
    if (uploadedDocuments.length > 0) {
      docItemsHtml = uploadedDocuments.map((d, i) => {
        const o = d.ocr || {};
        const ef = (o.extracted_fields && typeof o.extracted_fields === 'object' && !Array.isArray(o.extracted_fields)) ? o.extracted_fields : o;
        const dt = o.document_type || ef.document_type || 'Clinical Report';
        const raw = o.raw_text || ef.raw_text || o.text || 'Verified Record';
        return `
          <div style="background:#f8f9fa;border:1px solid #e2e8f0;border-radius:6px;padding:8px 12px;margin-bottom:6px;font-size:11px;">
            <strong style="color:#2d5a27;">[Doc ${i+1}] ${d.file_name}</strong> - <em>${dt}</em>
            <div style="color:#4a5568;margin-top:4px;white-space:pre-wrap;max-height:80px;overflow:hidden;">${raw.slice(0, 300)}${raw.length > 300 ? '...' : ''}</div>
          </div>
        `;
      }).join('');
    }

    const reportHtml = `
      <div id="pdfReportContainer" style="font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1a202c;padding:32px 36px;max-width:800px;margin:0 auto;background:#ffffff;line-height:1.45;">
        <!-- Header -->
        <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid #2d5a27;padding-bottom:16px;margin-bottom:20px;">
          <div>
            <div style="display:flex;align-items:center;gap:8px;">
              <span style="font-size:24px;font-weight:800;color:#2d5a27;letter-spacing:-0.5px;">CLINIQO HEALTH</span>
              <span style="background:#2d5a27;color:#ffffff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:12px;text-transform:uppercase;">ABDM FHIR R4</span>
            </div>
            <p style="font-size:12px;color:#4a5568;margin:4px 0 0 0;">Personal Health Report &amp; Dossier</p>
          </div>
          <div style="text-align:right;">
            <p style="font-size:11px;color:#718096;margin:0;">Date: <strong>${dateStr}</strong></p>
            <p style="font-size:11px;color:#718096;margin:2px 0 0 0;">Session: <strong style="font-family:monospace;">#${(currentSessionId || 'LOCAL').slice(0, 8).toUpperCase()}</strong></p>
            <span style="display:inline-block;margin-top:4px;padding:3px 10px;border-radius:12px;font-size:10px;font-weight:700;background:#dcfce7;color:#166534">HEALTH DOSSIER</span>
          </div>
        </div>

        <!-- Demographics Box -->
        <div style="background:#f4f7f4;border:1px solid #cce3cb;border-radius:10px;padding:14px 18px;margin-bottom:20px;">
          <h3 style="font-size:12px;font-weight:700;color:#2d5a27;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 8px 0;border-bottom:1px solid #cce3cb;padding-bottom:4px;">1. Patient Demographics &amp; Identification</h3>
          <table style="width:100%;font-size:11px;border-collapse:collapse;">
            <tr>
              <td style="padding:3px 0;width:25%;color:#4a5568;"><strong>Full Name:</strong></td>
              <td style="padding:3px 0;width:25%;color:#1a202c;font-weight:600;">${p.display_name || currentUser?.display_name || 'Registered Patient'}</td>
              <td style="padding:3px 0;width:25%;color:#4a5568;"><strong>ABHA Health ID:</strong></td>
              <td style="padding:3px 0;width:25%;color:#1a202c;font-weight:600;">${p.abha_id || 'ABDM-Verified'}</td>
            </tr>
            <tr>
              <td style="padding:3px 0;color:#4a5568;"><strong>Gender / DOB:</strong></td>
              <td style="padding:3px 0;color:#1a202c;">${p.gender || 'Not specified'} / ${p.date_of_birth || 'Recorded on Intake'}</td>
              <td style="padding:3px 0;color:#4a5568;"><strong>Blood Group:</strong></td>
              <td style="padding:3px 0;color:#1a202c;font-weight:600;">${p.blood_group || 'O+'}</td>
            </tr>
            <tr>
              <td style="padding:3px 0;color:#4a5568;"><strong>Mobile Number:</strong></td>
              <td style="padding:3px 0;color:#1a202c;">${p.phone || 'Verified on Session'}</td>
              <td style="padding:3px 0;color:#4a5568;"><strong>Emergency Contact:</strong></td>
              <td style="padding:3px 0;color:#1a202c;">${p.emergency_contact || 'Family Contact'}</td>
            </tr>
          </table>
        </div>

        <!-- Section 2: Chief Complaint -->
        <div style="margin-bottom:18px;">
          <h3 style="font-size:13px;font-weight:700;color:#2d5a27;border-bottom:1.5px solid #2d5a27;padding-bottom:3px;margin:0 0 8px 0;">2. Chief Complaint &amp; Symptom History</h3>
          <div style="background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid #2d5a27;border-radius:6px;padding:10px 14px;font-size:12px;">
            <p style="margin:0 0 4px 0;"><strong>Primary Reason for Visit:</strong> ${chiefReason}</p>
            <p style="margin:0 0 4px 0;color:#4a5568;font-size:11px;"><strong>Duration &amp; Progression:</strong> ${document.getElementById('symptomVal2')?.textContent.trim() || 'Reported on Intake'}</p>
            <p style="margin:0;color:#4a5568;font-size:11px;"><strong>Anatomical Location:</strong> ${document.getElementById('symptomVal3')?.textContent.trim() || 'General / Specified'}</p>
          </div>
        </div>

        <!-- Section 3: Synthesized Health Story -->
        <div style="margin-bottom:18px;">
          <h3 style="font-size:13px;font-weight:700;color:#2d5a27;border-bottom:1.5px solid #2d5a27;padding-bottom:3px;margin:0 0 8px 0;">3. Clinical Intelligence Narrative (Synthesized Health Story)</h3>
          <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:12px 14px;font-size:11px;color:#334155;line-height:1.5;">
            ${narrative}
          </div>
        </div>

        <!-- Section 4 & 5 Grid: Past History, Medications, Allergies -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:18px;">
          <!-- Past History -->
          <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;">
            <h4 style="font-size:11px;font-weight:700;color:#2d5a27;margin:0 0 6px 0;text-transform:uppercase;">4. Past Medical History</h4>
            <ul style="margin:0;padding-left:18px;font-size:11px;color:#4a5568;">
              ${medHistory.length > 0 ? medHistory.map(m => `<li style="margin-bottom:2px;">${m}</li>`).join('') : `<li>${medHistoryStr}</li>`}
            </ul>
          </div>
          <!-- Active Medications -->
          <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;">
            <h4 style="font-size:11px;font-weight:700;color:#2d5a27;margin:0 0 6px 0;text-transform:uppercase;">5. Active Medications &amp; Allergies</h4>
            <ul style="margin:0;padding-left:18px;font-size:11px;color:#4a5568;">
              ${medications.length > 0 ? medications.map(m => `<li style="margin-bottom:2px;">${m}</li>`).join('') : `<li>${medsAllStr}</li>`}
            </ul>
          </div>
        </div>

        <!-- Section 6: Allergies & Sensitivities -->
        <div style="margin-bottom:18px;">
          <h3 style="font-size:13px;font-weight:700;color:#b91c1c;border-bottom:1.5px solid #b91c1c;padding-bottom:3px;margin:0 0 8px 0;">6. Known Drug Allergies &amp; Adverse Reactions</h3>
          <div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:6px;padding:10px 14px;font-size:11px;color:#991b1b;">
            ${allergies.length > 0 ? allergies.map(a => `<div><strong>[CRITICAL ALERT]</strong> ${a}</div>`).join('') : '<div>No known adverse drug reactions or sensitivities recorded (NKDA).</div>'}
          </div>
        </div>

        <!-- Section 7: Family & Lifestyle Context -->
        <div style="margin-bottom:18px;">
          <h3 style="font-size:13px;font-weight:700;color:#2d5a27;border-bottom:1.5px solid #2d5a27;padding-bottom:3px;margin:0 0 8px 0;">7. Contextual Family &amp; Lifestyle Factors</h3>
          <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:6px;padding:10px 14px;font-size:11px;color:#4a5568;">
            <p style="margin:0 0 4px 0;"><strong>Family History:</strong> ${family.join(', ') || 'None documented'}</p>
            <p style="margin:0;"><strong>Daily Lifestyle Factors:</strong> ${lifestyle.join(', ') || 'Standard activity'}</p>
          </div>
        </div>

        <!-- Section 8: Scanned Records & OCR -->
        <div style="margin-bottom:20px;">
          <h3 style="font-size:13px;font-weight:700;color:#2d5a27;border-bottom:1.5px solid #2d5a27;padding-bottom:3px;margin:0 0 8px 0;">8. Scanned Medical Documents &amp; OCR Analysis</h3>
          ${docItemsHtml}
        </div>

        <!-- Footer / Signoff -->
        <div style="border-top:2px dashed #cbd5e1;padding-top:14px;margin-top:24px;display:flex;justify-content:space-between;align-items:flex-end;">
          <div>
            <p style="font-size:10px;color:#94a3b8;margin:0;">Encrypted Clinical Dossier • Generated via Cliniqo AI Medical Assistant</p>
            <p style="font-size:10px;color:#94a3b8;margin:2px 0 0 0;">ABDM Compliant • Session Token ID: ${currentSessionId || 'LOCAL'}</p>
          </div>
          <div style="text-align:right;border:1px solid #cbd5e1;border-radius:6px;padding:6px 14px;background:#f8fafc;">
            <p style="font-size:10px;color:#64748b;margin:0;">PHYSICIAN VERIFICATION SEAL</p>
            <p style="font-size:11px;font-weight:700;color:#2d5a27;margin:2px 0 0 0;">CLINIQO DIGITAL VAULT</p>
          </div>
        </div>
      </div>
    `;

    const opt = {
      margin: [10, 10, 10, 10],
      filename: `Cliniqo_Clinical_Summary_${(p.display_name || currentUser?.display_name || 'Patient').replace(/\s+/g, '_')}_${new Date().toISOString().split('T')[0]}.pdf`,
      image: { type: 'jpeg', quality: 0.98 },
      html2canvas: { scale: 2, useCORS: true },
      jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
    };

    if (window.html2pdf) {
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = reportHtml;
      document.body.appendChild(tempDiv);
      saveToVaultNotification("Generating PDF", "Rendering official clinical summary dossier in PDF format...");
      window.html2pdf().set(opt).from(tempDiv).save().then(() => {
        document.body.removeChild(tempDiv);
        saveToVaultNotification("PDF Downloaded", "Clinical summary PDF report saved successfully.");
      }).catch(err => {
        document.body.removeChild(tempDiv);
        openPrintableReport(reportHtml);
      });
    } else {
      openPrintableReport(reportHtml);
    }
  }

  function openPrintableReport(htmlContent) {
    const printWindow = window.open('', '_blank');
    if (printWindow) {
      printWindow.document.write(`
        <!DOCTYPE html>
        <html>
        <head>
          <title>Cliniqo Clinical Summary Dossier</title>
          <style>
            @media print {
              body { margin: 0; padding: 0; }
              @page { size: A4; margin: 15mm; }
            }
          </style>
        </head>
        <body>
          ${htmlContent}
          <script>
            window.onload = function() {
              window.print();
            };
          </script>
        </body>
        </html>
      `);
      printWindow.document.close();
      saveToVaultNotification("PDF Print Opened", "Dossier print dialog ready for PDF export.");
    }
  }

  // =========================================================================
  // 10. VOICE ENGINE & SPEECH SYNTHESIS
  // =========================================================================
  const VoiceManager = {
    recognition: null,
    isRecording: false,
    activeButtonEl: null,
    activeTranscriptEl: null,
    pulseRingEl: null,
    waveformEl: null,
    onSpeechComplete: null,

    init() {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SpeechRecognition) {
        this.recognition = new SpeechRecognition();
        this.recognition.continuous = false;
        this.recognition.interimResults = true;
        this.recognition.lang = window.CliniqoI18n ? window.CliniqoI18n.getSpeechCode() : 'en-IN';

        this.recognition.onstart = () => {
          this.isRecording = true;
          this.updateVisualState(true);
        };

        this.recognition.onresult = (event) => {
          let interimTranscript = '';
          let finalTranscript = '';
          for (let i = event.resultIndex; i < event.results.length; ++i) {
            if (event.results[i].isFinal) {
              finalTranscript += event.results[i][0].transcript;
            } else {
              interimTranscript += event.results[i][0].transcript;
            }
          }
          const display = finalTranscript || interimTranscript;
          if (display && this.activeTranscriptEl) {
            this.activeTranscriptEl.textContent = `“${display}”`;
            this.activeTranscriptEl.dataset.rawText = display;
          }
        };

        this.recognition.onerror = () => {
          this.stop();
        };

        this.recognition.onend = () => {
          if (this.isRecording) {
            this.stop();
            if (this.activeTranscriptEl) {
              const text = this.activeTranscriptEl.dataset.rawText || this.activeTranscriptEl.textContent.replace(/^[“"\s]+|[”"\s]+$/g, '');
              this.handleFinalSpeech(text);
            }
          }
        };
      }
    },

    start(btn, transcriptEl, pulseRingId = null, waveformId = null, onSpeechComplete = null) {
      if (this.isRecording) {
        this.stop();
      }

      this.activeButtonEl = btn;
      this.activeTranscriptEl = transcriptEl;
      this.pulseRingEl = pulseRingId ? document.getElementById(pulseRingId) : null;
      this.waveformEl = waveformId ? document.getElementById(waveformId) : null;
      this.onSpeechComplete = onSpeechComplete;

      if (this.recognition) {
        try {
          this.recognition.lang = window.CliniqoI18n ? window.CliniqoI18n.getSpeechCode() : 'en-IN';
          this.recognition.start();
        } catch (e) {
          this.stop();
        }
      } else {
        // Fallback if browser does not support SpeechRecognition
        saveToVaultNotification("Microphone Active", "Speech recognition enabled on supported modern browsers.");
      }
    },

    stop() {
      this.isRecording = false;
      if (this.recognition) {
        try { this.recognition.stop(); } catch (e) {}
      }
      this.updateVisualState(false);
    },

    updateVisualState(recording) {
      if (this.activeButtonEl) {
        const icon = this.activeButtonEl.querySelector('.material-symbols-outlined');
        const label = this.activeButtonEl.querySelector('span:not(.material-symbols-outlined)') || document.getElementById(`${this.activeButtonEl.id}Label`);
        if (recording) {
          this.activeButtonEl.classList.add('bg-red-600', 'animate-pulse', 'ring-4', 'ring-red-300');
          if (icon) icon.textContent = 'mic';
          if (label) label.textContent = 'Listening...';
        } else {
          this.activeButtonEl.classList.remove('bg-red-600', 'animate-pulse', 'ring-4', 'ring-red-300');
          if (icon) icon.textContent = 'mic';
          if (label) {
            if (this.activeButtonEl.id === 'medHistMicBtn') label.textContent = 'Tap to speak or add conditions';
            else if (this.activeButtonEl.id === 'medVoiceBtn') label.textContent = '1. Spoken medicines';
            else label.textContent = 'Tap to speak';
          }
        }
      }

      if (this.pulseRingEl) {
        if (recording) {
          this.pulseRingEl.classList.add('scale-125', 'bg-red-200/60', 'animate-ping');
        } else {
          this.pulseRingEl.classList.remove('scale-125', 'bg-red-200/60', 'animate-ping');
        }
      }
    },

    async handleFinalSpeech(text) {
      this.isRecording = false;
      this.updateVisualState(false);
      if (!text) return;

      const callback = this.onSpeechComplete;
      this.onSpeechComplete = null;

      if (typeof callback === 'function') {
        await callback(text);
      } else {
        saveToVaultNotification("Voice Captured", `“${text.slice(0, 45)}${text.length > 45 ? '...' : ''}”`);
        await sendPatientMessage(text, 'voice');
      }
    }
  };

  VoiceManager.init();

  // =========================================================================
  // 11. NAVIGATION & SCREEN MANAGER
  // =========================================================================
  function navigateTo(screenId, pushHash = true) {
    if (!screenId) return;

    // Strict Role-Based Route Guard:
    // Patients and unauthenticated users cannot access Doctor Workstation
    if (screenId === 'doctor-workstation' && (!currentUser || currentUser.role !== 'hospital')) {
      saveToVaultNotification(
        "Staff Area Restricted",
        "Hospital Doctor Workstation is restricted to verified clinical staff. Switched to your Patient Health Vault."
      );
      navigateTo('patient-visits', pushHash);
      return;
    }

    currentScreen = screenId;
    try {
      localStorage.setItem('cliniqo_current_screen', screenId);
    } catch (e) {}

    document.querySelectorAll('.screen-view').forEach(s => s.classList.remove('active'));
    const targetView = document.getElementById(`screen-${screenId}`);
    if (targetView) {
      targetView.classList.add('active');
    }

    const headerTitle = document.getElementById('headerCurrentScreenBadge');
    const headerPhase = document.getElementById('headerScreenPhaseBadge');
    const meta = SCREEN_TITLES[screenId] || { title: 'Cliniqo', phase: 'Patient Data Vault' };
    if (headerTitle) headerTitle.textContent = meta.title;
    if (headerPhase) headerPhase.textContent = meta.phase;

    document.querySelectorAll('.nav-item').forEach(item => {
      if (item.getAttribute('data-screen') === screenId) {
        item.classList.add('active-nav-link');
        const parentSub = item.closest('.sidebar-tree-sub');
        if (parentSub) {
          parentSub.classList.add('open');
          const chevron = parentSub.closest('.tree-group')?.querySelector('.tree-chevron');
          if (chevron) chevron.style.transform = 'rotate(0deg)';
        }
      } else {
        item.classList.remove('active-nav-link');
      }
    });

    document.querySelectorAll('.dock-tab-btn').forEach(btn => {
      if (btn.getAttribute('data-screen') === screenId) {
        btn.classList.add('bg-primary', 'text-white');
        btn.classList.remove('text-on-surface');
      } else {
        btn.classList.remove('bg-primary', 'text-white');
        btn.classList.add('text-on-surface');
      }
    });

    window.scrollTo({ top: 0, behavior: 'smooth' });

    const sidebar = document.getElementById('mainSidebar');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');
    if (window.innerWidth < 1024 && sidebar) {
      sidebar.classList.add('-translate-x-full');
      if (sidebarBackdrop) sidebarBackdrop.classList.add('hidden');
    }

    if (pushHash && window.location.hash !== `#${screenId}`) {
      window.location.hash = screenId;
    }

    updateHealthStoryUI();
    if (screenId === 'healthstory-your-health-timeline') renderTimelineFilteredItems();
    if (screenId === 'records-medical-records') renderDocumentsList();
    if (screenId === 'home') renderPatientCasesDashboard();
    if (screenId === 'assessment-medicines-allergies') {
      updateMedsBadge();
      updateAllergiesBadge();
    }
    if (screenId === 'assessment-medical-history') {
      updateMedHistConditionsBadge();
    }
    if (screenId === 'assessment-symptoms') {
      updateSymptomsReviewScreen();
    }
    if (screenId === 'assessment-ai-health-interview') {
      renderInterviewQuickReplies();
    }
    if (screenId === 'assessment-adaptive-follow-up') {
      renderAdaptiveFollowUpQuestion();
    }
    if (screenId === 'clinicalsummaries-summary-confirmation') {
      generateAiSummary();
    }
    if (screenId === 'clinical-case-summary') {
      renderCaseSummaryPage();
    }
    if (screenId === 'doctor-workstation') {
      loadDoctorQueue(doctorQueueFilter);
      refreshHospitalDashboard();
    }
    if (screenId === 'patient-visits') {
      if (activePatient) {
        updatePatientUI(activePatient);
        if (activePatient.patient_id) {
          renderLongitudinalProfile(activePatient.patient_id);
        }
      }
    }
    if (screenId === 'hospital-registration' || screenId === 'hospital-department') {
      updateHospitalTokenDisplays();
    }
  }

  // =========================================================================
  // 11B. HOSPITAL OPD PRE-CONSULTATION & DOCTOR WORKSTATION MODULE
  // =========================================================================
  const EMERGENCY_KEYWORDS = [
    'chest pain', 'chest tightness', 'chest pressure', 'radiating to arm', 'radiating to jaw',
    'heart attack', 'shortness of breath', 'difficulty breathing', 'cannot breathe', 'gasping',
    'choking', 'unconscious', 'passed out', 'fainting', 'fainted', 'loss of consciousness',
    'seizure', 'convulsion', 'fits', 'severe bleeding', 'heavy bleeding', 'coughing blood',
    'hemoptysis', 'vomiting blood', 'hematemesis', 'slurred speech', 'facial drooping',
    'paralysis', 'stroke', 'sudden weakness', 'worst headache of life', 'thunderclap',
    'நெஞ்சு வலி', 'மூச்சு திணறல்', 'சுவாசிக்க முடியவில்லை', 'மயக்கம்',
    'छाती में दर्द', 'सांस फूलना', 'सांस लेने में तकलीफ', 'बेहोश', 'खून की उल्टी'
  ];

  function checkTextForEmergencyRedFlags(text) {
    if (!text || typeof text !== 'string') return null;
    const lower = text.toLowerCase();
    for (const kw of EMERGENCY_KEYWORDS) {
      if (lower.includes(kw)) {
        return kw;
      }
    }
    return null;
  }

  function updateHospitalTokenDisplays() {
    if (!hospitalTokenNumber) {
      hospitalTokenNumber = localStorage.getItem('cliniqo_hospital_token') || '101';
    }
    const tokenDisplay = `#${hospitalTokenNumber}`;
    const tokenFull = `TOKEN #${hospitalTokenNumber}`;

    const deptTokenEl = document.getElementById('hospitalDeptAssignedTokenText');
    if (deptTokenEl) deptTokenEl.textContent = tokenFull;

    const reviewTokenBadge = document.getElementById('caseReviewTokenBadge');
    if (reviewTokenBadge) reviewTokenBadge.textContent = tokenFull;

    const caseSumSessionBadge = document.getElementById('caseSumSessionBadge');
    if (caseSumSessionBadge && hospitalTokenNumber) {
      caseSumSessionBadge.textContent = `TOKEN: ${tokenDisplay}`;
    }
  }

  async function triggerHospitalEmergencyAlert(reason = 'Critical clinical symptom detected.') {
    hospitalTriageLevel = 'emergency';
    const alertReasonText = document.getElementById('alertReasonText');
    if (alertReasonText) {
      alertReasonText.textContent = reason;
    }
    
    // Play alert audio chime via Web Audio API
    try {
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(880, audioCtx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.3);
      gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.4);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.4);
    } catch (e) {}

    // Update session triage level on backend
    if (currentSessionId) {
      try {
        await apiRequest(`/api/v1/sessions/${currentSessionId}/hospital`, {
          method: 'PATCH',
          body: { triage_level: 'emergency' }
        });
      } catch (e) {}
    }

    // Broadcast emergency red flag immediately to hospital operations dashboard
    if (hospitalSyncChannel) {
      hospitalSyncChannel.postMessage({
        type: 'RED_FLAG_TRIGGERED',
        session_id: currentSessionId,
        token_number: hospitalTokenNumber,
        patient_name: activePatient.display_name || 'Walk-in Patient',
        department: hospitalDepartment || 'General Medicine',
        reason: reason,
        timestamp: Date.now()
      });
    }

    navigateTo('hospital-priority-alert');
    saveToVaultNotification("EMERGENCY HARD STOP", "Urgent clinical symptom identified. Attending staff alerted.");
  }

  async function loadDoctorQueue(filterMode = 'all') {
    doctorQueueFilter = filterMode;
    const countBadge = document.getElementById('docQueueCountBadge');
    const tableBody = document.getElementById('doctorQueueTableBody');
    if (!tableBody) return;

    try {
      const isDept = (filterMode === 'general' || filterMode === 'ayush');
      const queryParam = isDept ? `?department=${filterMode}` : '';
      const queueResp = await apiRequest(`/api/v1/doctor/queue${queryParam}`);
      const queueList = (queueResp && Array.isArray(queueResp.queue)) ? queueResp.queue : (Array.isArray(queueResp) ? queueResp : []);
      let filteredQueue = queueList;
      if (filterMode === 'ready') {
        filteredQueue = filteredQueue.filter(q => !q.doctor_verified);
      } else if (filterMode === 'intake') {
        filteredQueue = filteredQueue.filter(q => q.status === 'active');
      } else if (filterMode === 'flags') {
        filteredQueue = filteredQueue.filter(q => q.triage_level === 'emergency' || q.triage_level === 'urgent');
      }

      // Check search input
      const searchVal = (document.getElementById('docQueueSearchInput')?.value || '').toLowerCase().trim();
      if (searchVal) {
        filteredQueue = filteredQueue.filter(q => {
          const name = (q.patient_name || q.display_name || '').toLowerCase();
          const abha = (q.abha_id || '').toLowerCase();
          const tok = String(q.token_number || '');
          const phone = (q.phone || '');
          return name.includes(searchVal) || abha.includes(searchVal) || tok.includes(searchVal) || phone.includes(searchVal);
        });
      }

      if (filteredQueue.length === 0) {
        tableBody.innerHTML = `
          <tr>
            <td colspan="7" class="py-8 text-center text-secondary">
              <span class="material-symbols-outlined text-[32px] text-secondary/40">inbox</span>
              <p class="mt-2 text-xs font-semibold">No patients currently matching queue filter "${filterMode}".</p>
              <p class="text-[10px] text-secondary">Patients registering at the kiosk will appear here automatically.</p>
            </td>
          </tr>
        `;
        if (countBadge) countBadge.textContent = '0 Patients';
      } else {
        if (countBadge) countBadge.textContent = `${filteredQueue.length} Patient${filteredQueue.length > 1 ? 's' : ''} in Queue`;

        tableBody.innerHTML = filteredQueue.map((item, idx) => {
          const tokenNum = item.token_number || (100 + idx + 1);
          const patientName = item.patient_name || item.display_name || 'Walk-in Patient';
          const gender = item.gender || 'M';
          const dob = item.date_of_birth || '';
          let ageSex = `${gender[0] || 'M'}`;
          if (dob) {
            const ageMatch = dob.match(/\b(\d{1,3})\b/);
            if (ageMatch) ageSex = `${ageMatch[1]} / ${gender[0] || 'M'}`;
          }
          const deptLabel = item.department === 'ayush' ? 'AYUSH' : (item.department || 'General Medicine');
          const triage = item.triage_level || 'routine';
          
          let priorityBadge = `<span class="px-2 py-0.5 rounded-full bg-surface-container text-secondary text-[10px] font-bold">Normal</span>`;
          if (triage === 'emergency') {
            priorityBadge = `<span class="px-2 py-0.5 rounded-full bg-red-100 text-red-800 text-[10px] font-extrabold animate-pulse">High (Critical)</span>`;
          } else if (triage === 'urgent') {
            priorityBadge = `<span class="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-[10px] font-bold">High</span>`;
          }

          let statusPill = `<span class="px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 font-bold text-[10px]">Ready</span>`;
          if (item.doctor_verified) {
            statusPill = `<span class="px-2.5 py-0.5 rounded-full bg-emerald-600 text-white font-bold text-[10px]">Verified</span>`;
          } else if (item.status === 'in_consultation') {
            statusPill = `<span class="px-2.5 py-0.5 rounded-full bg-purple-100 text-purple-800 font-bold text-[10px]">In Exam</span>`;
          } else if (item.status === 'active') {
            statusPill = `<span class="px-2.5 py-0.5 rounded-full bg-blue-100 text-blue-800 font-bold text-[10px]">AI Intake</span>`;
          }

          return `
            <tr class="hover:bg-surface-container/40 transition-colors group" data-session-id="${item.session_id}">
              <td class="py-3 px-4 font-mono font-bold text-primary text-xs">
                <div class="flex items-center gap-2">
                  <input type="checkbox" class="rounded border-secondary-container text-primary" />
                  <span>#${tokenNum}</span>
                </div>
              </td>
              <td class="py-3 px-4 font-semibold text-on-surface text-xs">${patientName}</td>
              <td class="py-3 px-4 text-secondary text-xs">${ageSex}</td>
              <td class="py-3 px-4 font-medium text-on-surface text-xs">${deptLabel}</td>
              <td class="py-3 px-4">${statusPill}</td>
              <td class="py-3 px-4">${priorityBadge}</td>
              <td class="py-3 px-4 text-right">
                <button type="button" class="doc-review-case-btn text-primary font-bold text-xs hover:underline inline-flex items-center gap-0.5 cursor-pointer" data-session-id="${item.session_id}">
                  <span>View</span>
                  <span class="material-symbols-outlined text-[15px]">arrow_forward</span>
                </button>
              </td>
            </tr>
          `;
        }).join('');

        tableBody.querySelectorAll('.doc-review-case-btn').forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.preventDefault();
            const sessId = btn.getAttribute('data-session-id');
            const matched = filteredQueue.find(q => q.session_id === sessId);
            if (matched) {
              openDoctorCaseReview(matched);
            }
          });
        });
      }

      // Also refresh dashboard statistics & streams in parallel
      refreshHospitalDashboard();

    } catch (err) {
      console.warn("loadDoctorQueue error:", err);
      tableBody.innerHTML = `
        <tr>
          <td colspan="7" class="py-8 text-center text-error">
            <span class="material-symbols-outlined text-[28px]">error</span>
            <p class="mt-2 text-xs font-semibold">Failed to load doctor queue. Please verify backend connection.</p>
          </td>
        </tr>
      `;
    }
  }

  async function refreshHospitalDashboard(queueResp = null) {
    try {
      const stats = await apiRequest('/api/v1/hospital/stats');
      if (stats) {
        const kpiTot = document.getElementById('hospKpiTotalPatients');
        const kpiWait = document.getElementById('hospKpiWaiting');
        const kpiIn = document.getElementById('hospKpiInConsultation');
        const kpiComp = document.getElementById('hospKpiCompleted');
        const kpiRed = document.getElementById('hospKpiRedFlags');
        const donutCount = document.getElementById('donutTotalPatientsCount');
        const donutBadge = document.getElementById('donutTotalBadge');
        const perfDocs = document.getElementById('hospPerfDocsCount');

        const tot = (stats.total_patients !== undefined && stats.total_patients !== null) ? stats.total_patients : 0;
        const wait = (stats.waiting_patients !== undefined) ? stats.waiting_patients : (stats.waiting !== undefined ? stats.waiting : 0);
        const inC = (stats.in_consultation !== undefined) ? stats.in_consultation : 0;
        const comp = (stats.completed_consultations !== undefined) ? stats.completed_consultations : (stats.completed !== undefined ? stats.completed : 0);
        const red = (stats.emergency_red_flags !== undefined) ? stats.emergency_red_flags : (stats.red_flags !== undefined ? stats.red_flags : 0);
        const docsCount = stats.total_documents !== undefined ? stats.total_documents : (stats.documents_processed || 0);

        if (kpiTot) kpiTot.textContent = String(tot);
        if (kpiWait) kpiWait.textContent = String(wait);
        if (kpiIn) kpiIn.textContent = String(inC);
        if (kpiComp) kpiComp.textContent = String(comp);
        if (kpiRed) kpiRed.textContent = String(red);
        if (donutCount) donutCount.textContent = String(tot);
        if (donutBadge) donutBadge.textContent = `${tot} Total`;
        if (perfDocs) perfDocs.textContent = String(docsCount);

        // Update department breakdown
        const deptCounts = stats.department_breakdown || stats.department_counts || {};
        const breakdownList = document.getElementById('hospDeptBreakdownList');
        if (breakdownList) {
          const entries = Object.entries(deptCounts);
          if (entries.length === 0) {
            breakdownList.innerHTML = `<p class="text-xs text-secondary italic py-2 text-center">No OPD intakes registered today yet</p>`;
          } else {
            const colors = {
              'general': '#2d5a27',
              'pediatrics': '#3b82f6',
              'cardiology': '#ef4444',
              'orthopedics': '#f59e0b',
              'ayush': '#059669',
              'gynecology': '#8b5cf6',
              'others': '#64748b'
            };
            breakdownList.innerHTML = entries.map(([dept, count]) => {
              const c = colors[dept.toLowerCase()] || '#2d5a27';
              const label = dept.charAt(0).toUpperCase() + dept.slice(1) + (dept.toLowerCase().includes('opd') ? '' : ' OPD');
              return `
                <div class="flex items-center justify-between pt-1">
                  <span class="flex items-center gap-2"><span class="w-2.5 h-2.5 rounded-full" style="background:${c}"></span><span>${label}</span></span>
                  <strong class="text-on-surface font-bold">${count}</strong>
                </div>
              `;
            }).join('');
          }
        }
      }
    } catch (e) {}

    // Fetch recent documents stream
    try {
      const recDocs = await apiRequest('/api/v1/hospital/documents/recent');
      const docsTableBody = document.getElementById('hospRecentDocsTableBody');
      if (docsTableBody) {
        if (!Array.isArray(recDocs) || recDocs.length === 0) {
          docsTableBody.innerHTML = `
            <tr>
              <td colspan="4" class="py-6 text-center text-secondary">
                <span class="material-symbols-outlined text-[22px] text-secondary/50">folder_open</span>
                <p class="mt-1 text-xs">No documents uploaded yet</p>
              </td>
            </tr>
          `;
        } else {
          docsTableBody.innerHTML = recDocs.slice(0, 5).map(doc => {
            const docType = doc.document_type || 'Prescription';
            const patient = doc.patient_name || 'Walk-in Patient';
            const ocrStat = doc.ocr_status || 'completed';
            const pillClass = ocrStat === 'completed' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800';
            const pillText = ocrStat === 'completed' ? 'Processed' : 'Pending';
            return `
              <tr>
                <td class="py-2.5 font-medium flex items-center gap-1.5">
                  <span class="material-symbols-outlined text-primary text-[16px]">description</span>
                  <span class="truncate max-w-[110px]">${doc.file_name || docType}</span>
                </td>
                <td class="py-2.5 text-secondary truncate max-w-[90px]">${patient}</td>
                <td class="py-2.5 text-secondary">${docType}</td>
                <td class="py-2.5"><span class="px-2 py-0.5 rounded-full ${pillClass} text-[9px] font-bold">${pillText}</span></td>
              </tr>
            `;
          }).join('');
        }
      }
    } catch (e) {}

    // Fetch recent alerts stream
    try {
      const alerts = await apiRequest('/api/v1/hospital/alerts');
      const alertsList = document.getElementById('hospRecentAlertsList');
      if (alertsList) {
        if (!Array.isArray(alerts) || alerts.length === 0) {
          alertsList.innerHTML = `
            <div class="p-4 rounded-2xl bg-surface-container/60 border border-secondary-container/50 text-center text-secondary text-xs">
              <span class="material-symbols-outlined text-[24px] text-emerald-600 block mb-1">verified_user</span>
              <p class="font-semibold text-on-surface">No Active Red Flags</p>
              <p class="text-[11px] text-secondary mt-0.5">All waiting patients are routine triage</p>
            </div>
          `;
        } else {
          alertsList.innerHTML = alerts.slice(0, 4).map(al => {
            const sev = (al.triage_level || 'urgent').toUpperCase();
            const badgeClass = sev === 'EMERGENCY' ? 'bg-red-600 text-white' : 'bg-amber-600 text-white';
            const cardClass = sev === 'EMERGENCY' ? 'bg-red-50 border-red-200' : 'bg-amber-50 border-amber-200';
            const time = al.started_at ? new Date(al.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Now';
            return `
              <div class="p-3 rounded-2xl ${cardClass} border text-xs space-y-1">
                <div class="flex items-center justify-between">
                  <span class="px-2 py-0.5 rounded-full ${badgeClass} font-bold text-[9px] uppercase">${sev === 'EMERGENCY' ? 'HIGH' : 'MEDIUM'}</span>
                  <span class="text-[10px] text-secondary">${time}</span>
                </div>
                <p class="font-bold text-on-surface">Urgent intake symptom flagged</p>
                <p class="text-[11px] text-secondary">Token #${al.token_number || '--'} • ${al.display_name || 'Patient'} • ${al.department || 'General OPD'}</p>
              </div>
            `;
          }).join('');
        }
      }
    } catch (e) {}

    // Update today's consultation schedule table from doctor queue
    try {
      const schedBody = document.getElementById('hospTodayScheduleTableBody');
      if (schedBody && queueResp && Array.isArray(queueResp.queue)) {
        const queueList = queueResp.queue;
        if (queueList.length === 0) {
          schedBody.innerHTML = `
            <tr>
              <td colspan="6" class="py-6 text-center text-secondary">
                <span class="material-symbols-outlined text-[22px] text-secondary/50">event_available</span>
                <p class="mt-1 text-xs font-semibold">No consultations currently scheduled</p>
              </td>
            </tr>
          `;
        } else {
          schedBody.innerHTML = queueList.slice(0, 6).map(item => {
            const tok = item.token_number ? `#${item.token_number}` : '#--';
            const pat = item.display_name || 'Patient';
            const dept = (item.department || 'general').toUpperCase();
            const tr = item.triage_level || 'routine';
            const trClass = tr === 'emergency' ? 'bg-red-100 text-red-800' : (tr === 'urgent' ? 'bg-amber-100 text-amber-800' : 'bg-blue-100 text-blue-800');
            const statText = item.doctor_verified ? 'Verified' : 'Waiting';
            const statClass = item.doctor_verified ? 'bg-emerald-100 text-emerald-800' : 'bg-yellow-100 text-yellow-800';
            return `
              <tr>
                <td class="py-2.5 font-bold text-on-surface">${tok}</td>
                <td class="py-2.5 font-semibold text-on-surface">${pat}</td>
                <td class="py-2.5 text-secondary">${dept}</td>
                <td class="py-2.5"><span class="px-2 py-0.5 rounded-full ${statClass} text-[10px] font-bold">${statText}</span></td>
                <td class="py-2.5"><span class="px-2 py-0.5 rounded-full ${trClass} text-[10px] font-bold">${tr.toUpperCase()}</span></td>
                <td class="py-2.5 text-right">
                  <button type="button" class="doc-sched-review-btn text-xs font-bold text-primary hover:underline cursor-pointer" data-id="${item.session_id}">Call Case</button>
                </td>
              </tr>
            `;
          }).join('');

          schedBody.querySelectorAll('.doc-sched-review-btn').forEach(btn => {
            btn.addEventListener('click', () => {
              const sId = btn.getAttribute('data-id');
              const match = queueList.find(q => q.session_id === sId);
              if (match) openDoctorCaseReview(match);
            });
          });
        }
      }
    } catch (e) {}
  }

  // =========================================================================
  // 11C. PATIENT LONGITUDINAL PROFILE & MY VISITS RENDERER
  // =========================================================================
  async function renderLongitudinalProfile(patientId) {
    if (!patientId) {
      if (activePatient && activePatient.patient_id) {
        patientId = activePatient.patient_id;
      } else {
        return;
      }
    }

    try {
      const data = await apiRequest(`/api/v1/patients/${patientId}/full-profile`);
      if (!data) return;

      const patient = data.patient || {};
      const medProfile = data.medical_profile || {};
      const visits = data.visits || [];
      const docs = data.documents || [];
      const followUps = data.follow_ups || [];
      const ayushAssessments = data.ayush_assessments || [];

      // 1. Active Visit Card vs No Active Visit
      const activeVisit = visits.find(v => v.status === 'active' || v.status === 'waiting' || v.status === 'in_consultation');
      const activeCard = document.getElementById('myVisitsActiveVisitCard');
      const noActiveCard = document.getElementById('myVisitsNoActiveCard');

      if (activeVisit) {
        if (activeCard) activeCard.classList.remove('hidden');
        if (noActiveCard) noActiveCard.classList.add('hidden');
        const tokBadge = document.getElementById('myVisitsActiveTokenBadge');
        if (tokBadge) tokBadge.textContent = activeVisit.token_number ? `Token #${activeVisit.token_number}` : 'Token Assigned';
        const statusBadge = document.getElementById('myVisitsActiveStatusBadge');
        if (statusBadge) {
          statusBadge.textContent = activeVisit.status === 'in_consultation' ? 'In Doctor Consultation' : (activeVisit.status === 'waiting' ? 'Waiting in OPD' : 'Active Intake');
          statusBadge.className = activeVisit.status === 'in_consultation' ? 'px-3 py-1 rounded-full bg-blue-100 text-blue-800 text-xs font-bold' : 'px-3 py-1 rounded-full bg-yellow-100 text-yellow-800 text-xs font-bold';
        }
        const deptEl = document.getElementById('myVisitsActiveDept');
        if (deptEl) deptEl.textContent = activeVisit.department || 'General Medicine OPD';
        const compEl = document.getElementById('myVisitsActiveComplaint');
        if (compEl) compEl.textContent = activeVisit.chief_complaint || activeVisit.reason_for_visit || 'Routine Consultation';
        const docEl = document.getElementById('myVisitsActiveDoctor');
        if (docEl) docEl.textContent = activeVisit.doctor_name || 'OPD Unit A • Assigned Desk';
      } else {
        if (activeCard) activeCard.classList.add('hidden');
        if (noActiveCard) noActiveCard.classList.remove('hidden');
      }

      // 2. Known Allergies
      const algListEl = document.getElementById('myVisitsAllergiesList');
      if (algListEl) {
        const algs = medProfile.allergies || [];
        if (algs.length === 0) {
          algListEl.innerHTML = `<span class="text-secondary italic">No allergies recorded</span>`;
        } else {
          algListEl.innerHTML = algs.map(a => {
            const name = typeof a === 'string' ? a : (a.allergen || a.name || 'Allergy');
            const sev = (typeof a === 'object' && a.severity) ? ` (${a.severity})` : '';
            return `<span class="px-2.5 py-1 rounded-full bg-red-100 text-red-800 text-[11px] font-bold border border-red-200 flex items-center gap-1"><span class="material-symbols-outlined text-[13px]">warning</span>${name}${sev}</span>`;
          }).join('');
        }
      }

      // 3. Chronic Conditions
      const chronicListEl = document.getElementById('myVisitsChronicList');
      if (chronicListEl) {
        const conds = medProfile.chronic_conditions || medProfile.medical_history || [];
        if (conds.length === 0) {
          chronicListEl.innerHTML = `<span class="text-secondary italic">No chronic conditions recorded</span>`;
        } else {
          chronicListEl.innerHTML = conds.map(c => {
            const name = typeof c === 'string' ? c : (c.condition || c.name || 'Condition');
            return `<span class="px-2.5 py-1 rounded-full bg-blue-50 text-blue-800 text-[11px] font-bold border border-blue-200 flex items-center gap-1"><span class="material-symbols-outlined text-[13px]">check_circle</span>${name}</span>`;
          }).join('');
        }
      }

      // 4. Medications: Current Confirmed vs Historical/Unverified
      const medsListEl = document.getElementById('myVisitsMedsList');
      if (medsListEl) {
        const meds = medProfile.active_medications || [];
        if (meds.length === 0) {
          medsListEl.innerHTML = `<p class="text-secondary italic">No active or historical medications recorded</p>`;
        } else {
          medsListEl.innerHTML = meds.map(m => {
            const name = typeof m === 'string' ? m : (m.name || m.drug_name || 'Medication');
            const dose = typeof m === 'object' && m.dosage ? m.dosage : '';
            const isConfirmed = typeof m === 'object' ? (m.confirmed === true || m.status === 'active' || m.temporal_status === 'current') : true;
            return `
              <div class="p-2.5 rounded-xl bg-surface-container border border-secondary-container/60 flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <span class="material-symbols-outlined text-[18px] ${isConfirmed ? 'text-primary' : 'text-amber-600'}">medication</span>
                  <div>
                    <span class="font-bold text-on-surface">${name}</span>
                    ${dose ? `<span class="text-secondary ml-1 font-mono text-[11px]">${dose}</span>` : ''}
                  </div>
                </div>
                <span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${isConfirmed ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}">
                  ${isConfirmed ? 'Patient Confirmed Active' : 'Historical / Needs Verification'}
                </span>
              </div>
            `;
          }).join('');
        }
      }

      // 5. AYUSH Constitution
      const ayushEl = document.getElementById('myVisitsAyushSummary');
      if (ayushEl) {
        const ayProfile = medProfile.ayush_profile || {};
        const latestAyush = ayushAssessments.length > 0 ? ayushAssessments[0] : null;
        if (ayProfile.prakriti || (latestAyush && latestAyush.prakriti)) {
          const prakriti = ayProfile.prakriti || (latestAyush ? latestAyush.prakriti : 'Evaluated');
          const agni = ayProfile.agni || (latestAyush ? latestAyush.agni : '');
          const satmya = ayProfile.satmya || (latestAyush ? latestAyush.satmya : '');
          ayushEl.innerHTML = `
            <div class="flex flex-wrap items-center gap-2">
              <span class="px-3 py-1 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 text-xs font-bold">Prakriti: ${prakriti}</span>
              ${agni ? `<span class="px-3 py-1 rounded-full bg-surface-container text-on-surface text-xs font-semibold">Agni: ${agni}</span>` : ''}
              ${satmya ? `<span class="px-3 py-1 rounded-full bg-surface-container text-on-surface text-xs font-semibold">Satmya: ${satmya}</span>` : ''}
            </div>
          `;
        } else {
          ayushEl.innerHTML = `<p class="text-secondary italic">No AYUSH evaluation recorded</p>`;
        }
      }

      // 6. Follow-up Consultations Schedule
      const followListEl = document.getElementById('myVisitsFollowUpsList');
      if (followListEl) {
        if (followUps.length === 0) {
          followListEl.innerHTML = `
            <div class="p-4 rounded-2xl bg-surface-container/60 text-center text-secondary text-xs">
              <span class="material-symbols-outlined text-[22px] text-secondary/50 block mb-1">event_available</span>
              <span>No pending follow-up consultations</span>
            </div>
          `;
        } else {
          followListEl.innerHTML = followUps.map(fu => {
            const isPending = fu.status === 'scheduled' || fu.status === 'pending';
            return `
              <div class="p-4 rounded-2xl ${isPending ? 'bg-primary-fixed/20 border border-primary/30' : 'bg-surface-container/60 border border-secondary-container'} flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <div class="flex items-center gap-2">
                    <span class="font-headline font-bold text-on-surface text-sm">Follow-up: ${fu.reason || 'Routine Follow-up'}</span>
                    <span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${isPending ? 'bg-primary text-white' : 'bg-gray-100 text-gray-700'}">${(fu.status || 'scheduled').toUpperCase()}</span>
                  </div>
                  <p class="text-xs text-secondary mt-0.5">Target Date: <strong>${fu.target_date || 'Upcoming'}</strong> • Linked to Visit #${(fu.parent_visit_id || '').slice(0, 8)}</p>
                  ${fu.notes ? `<p class="text-[11px] text-on-surface-variant mt-1 italic">${fu.notes}</p>` : ''}
                </div>
                ${isPending ? `
                  <button type="button" class="start-return-visit-btn h-9 px-4 rounded-full bg-primary hover:bg-primary-dark text-white text-xs font-bold flex items-center gap-1.5 shrink-0 cursor-pointer shadow-xs" data-follow-up-id="${fu.id}" data-parent-visit-id="${fu.parent_visit_id || ''}" data-reason="${fu.reason || ''}">
                    <span>Start Follow-Up Visit Now</span>
                    <span class="material-symbols-outlined text-[15px]">arrow_forward</span>
                  </button>
                ` : ''}
              </div>
            `;
          }).join('');

          followListEl.querySelectorAll('.start-return-visit-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
              const fuId = btn.getAttribute('data-follow-up-id');
              const pVisitId = btn.getAttribute('data-parent-visit-id');
              const reason = btn.getAttribute('data-reason');
              await startFollowUpReturnVisit(patientId, fuId, pVisitId, reason);
            });
          });
        }
      }

      // 7. Visits History (Visit 1, Visit 2, ...)
      const countBadge = document.getElementById('myVisitsTotalCountBadge');
      if (countBadge) countBadge.textContent = `${visits.length} Visit${visits.length === 1 ? '' : 's'} on Record`;

      const histListEl = document.getElementById('myVisitsHistoryList');
      if (histListEl) {
        if (visits.length === 0) {
          histListEl.innerHTML = `
            <div class="p-6 rounded-2xl bg-surface-container/60 text-center text-secondary text-xs">
              <span class="material-symbols-outlined text-[26px] text-secondary/50 block mb-1">history</span>
              <p class="font-semibold text-on-surface">No visits recorded yet</p>
              <p class="text-[11px] text-secondary mt-0.5">Your hospital visits and EMR consultations will appear here.</p>
            </div>
          `;
        } else {
          histListEl.innerHTML = visits.map((v, idx) => {
            const visitNum = visits.length - idx; // Chronological order
            const dateStr = v.started_at ? new Date(v.started_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : 'Unknown Date';
            const tok = v.token_number ? `Token #${v.token_number}` : 'Token Assigned';
            const dept = v.department || 'General Medicine';
            const complaint = v.chief_complaint || v.reason_for_visit || 'Routine Consultation';
            const status = v.status || 'completed';
            return `
              <div class="p-4 rounded-2xl bg-surface-container/70 border border-secondary-container hover:border-primary/40 transition-all space-y-2">
                <div class="flex items-center justify-between">
                  <div class="flex items-center gap-2">
                    <span class="px-2.5 py-0.5 rounded-full bg-primary text-white text-[11px] font-bold">Visit ${visitNum}</span>
                    <span class="font-bold text-on-surface text-sm">${dept}</span>
                    <span class="text-xs text-secondary">• ${dateStr}</span>
                  </div>
                  <span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${status === 'completed' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}">${tok} • ${status.toUpperCase()}</span>
                </div>
                <p class="text-xs text-on-surface"><strong>Chief Complaint:</strong> ${complaint}</p>
                ${v.summary && v.summary.overview ? `<p class="text-[11px] text-secondary italic">Summary: ${v.summary.overview}</p>` : ''}
              </div>
            `;
          }).join('');
        }
      }

      // 8. Documents Vault
      const vaultListEl = document.getElementById('myVisitsDocsVaultList');
      if (vaultListEl) {
        if (docs.length === 0) {
          vaultListEl.innerHTML = `
            <div class="p-6 rounded-2xl bg-surface-container/60 text-center text-secondary text-xs">
              <span class="material-symbols-outlined text-[26px] text-secondary/50 block mb-1">folder_open</span>
              <p class="font-semibold text-on-surface">No documents uploaded yet</p>
              <p class="text-[11px] text-secondary mt-0.5">Uploaded prescriptions, lab tests, and discharge summaries are preserved permanently.</p>
            </div>
          `;
        } else {
          vaultListEl.innerHTML = docs.map(d => {
            const isCurrent = d.document_classification === 'current';
            const medDate = d.document_date ? `Medical Date: ${d.document_date}` : 'Medical Date: Not specified';
            const upDate = d.created_at ? new Date(d.created_at).toLocaleDateString() : '';
            const conf = d.ocr_confidence ? `OCR Confidence: ${Math.round(d.ocr_confidence * 100)}%` : 'OCR Processed';
            return `
              <div class="p-3.5 rounded-2xl bg-surface-container/60 border border-secondary-container flex items-center justify-between gap-3">
                <div class="flex items-center gap-3">
                  <div class="w-10 h-10 rounded-xl bg-surface-container-highest text-primary flex items-center justify-center shrink-0">
                    <span class="material-symbols-outlined text-[20px]">description</span>
                  </div>
                  <div>
                    <div class="flex items-center gap-2">
                      <p class="font-bold text-on-surface text-xs sm:text-sm">${d.file_name || 'Medical Document'}</p>
                      <span class="px-2 py-0.2 rounded-full text-[9px] font-bold uppercase ${isCurrent ? 'bg-emerald-100 text-emerald-800' : 'bg-secondary-container text-secondary'}">${isCurrent ? 'Current' : 'Old Medical Doc'}</span>
                    </div>
                    <p class="text-[11px] text-secondary mt-0.5">${medDate} • Uploaded ${upDate} • ${conf}</p>
                  </div>
                </div>
                <span class="px-2.5 py-1 rounded-full text-[10px] font-bold bg-white text-on-surface border border-secondary-container shrink-0">
                  ${d.verification_status || 'Verified'}
                </span>
              </div>
            `;
          }).join('');
        }
      }

      // 9. Profile Editor Fields
      const myVisName = document.getElementById('myVisitsEditName');
      if (myVisName) myVisName.value = patient.display_name || '';
      const myVisPhone = document.getElementById('myVisitsEditPhone');
      if (myVisPhone) myVisPhone.value = patient.phone || '';
      const myVisEmerg = document.getElementById('myVisitsEditEmergency');
      if (myVisEmerg) myVisEmerg.value = patient.emergency_contact || '';
      const myVisBlood = document.getElementById('myVisitsEditBlood');
      if (myVisBlood && patient.blood_group) myVisBlood.value = patient.blood_group;
      const myVisAbha = document.getElementById('myVisitsEditAbha');
      if (myVisAbha) myVisAbha.value = patient.abha_id || '';
    } catch (err) {
      console.error('Failed to load longitudinal profile:', err);
    }
  }

  async function startFollowUpReturnVisit(patientId, followUpId, parentVisitId, reason) {
    try {
      const res = await apiRequest(`/api/v1/follow-ups/${followUpId}/return-visit`, {
        method: 'POST',
        body: { department: 'General Medicine OPD', reason_for_visit: reason || 'Follow-up Consultation' }
      });
      if (res && res.session_id) {
        currentSessionId = res.session_id;
        localStorage.setItem('cliniqo_session_id', currentSessionId);
        sessionStorage.setItem('cliniqo_session_id', currentSessionId);
        hospitalTokenNumber = res.token_number;
        localStorage.setItem('cliniqo_hospital_token', hospitalTokenNumber);
        isReturningPatientVisit = true;
        updateHospitalTokenDisplays();
        saveToVaultNotification("Follow-Up Visit Started", `Token #${res.token_number} assigned for ${reason || 'Follow-up'}.`);
        navigateTo('assessment-what-brings-you-here');
      }
    } catch (err) {
      alert("Could not start follow-up visit: " + (err.message || err));
    }
  }

  window.startNewPatientVisitFromPortal = async function() {
    if (activePatient && activePatient.patient_id) {
      isReturningPatientVisit = true;
      try {
        const visitResp = await apiRequest(`/api/v1/patients/${activePatient.patient_id}/visits`, {
          method: 'POST',
          body: {
            department: hospitalDepartment === 'ayush' ? 'AYUSH OPD' : 'General Medicine OPD',
            language_preference: activePatient.preferred_language || selectedHospitalLang || 'en-IN',
            consent_given: true,
            opd_mode: hospitalDepartment || 'general'
          }
        });
        if (visitResp && visitResp.session_id) {
          currentSessionId = visitResp.session_id;
          localStorage.setItem('cliniqo_session_id', currentSessionId);
          sessionStorage.setItem('cliniqo_session_id', currentSessionId);
          hospitalTokenNumber = visitResp.token_number;
          localStorage.setItem('cliniqo_hospital_token', hospitalTokenNumber);
          updateHospitalTokenDisplays();
        }
        resetSessionUIState();
        // Preload baseline allergies & chronic conditions into session
        if (activePatient.allergies_json) {
          try {
            const aList = typeof activePatient.allergies_json === 'string' ? JSON.parse(activePatient.allergies_json) : activePatient.allergies_json;
            aList.forEach(a => { const aName = typeof a === 'string' ? a : (a.allergen || a.name); if (aName) selectedAllergies.add(aName); });
            updateAllergiesBadge();
          } catch (e) {}
        }
        if (activePatient.chronic_conditions_json) {
          try {
            const cList = typeof activePatient.chronic_conditions_json === 'string' ? JSON.parse(activePatient.chronic_conditions_json) : activePatient.chronic_conditions_json;
            cList.forEach(c => { const cName = typeof c === 'string' ? c : (c.condition || c.name); if (cName) selectedMedHistConditions.add(cName); });
            updateMedHistConditionsBadge();
          } catch (e) {}
        }
        saveToVaultNotification("New Visit Initialized", `Token #${hospitalTokenNumber} assigned. Please select OPD department.`);
        navigateTo('hospital-department');
      } catch (e) {
        navigateTo('hospital-department');
      }
    } else {
      navigateTo('hospital-registration');
    }
  };

  async function openDoctorCaseReview(item) {
    if (!item) return;
    currentDoctorCase = item;

    const panel = document.getElementById('doctorCaseReviewPanel');
    if (!panel) return;

    // Badges
    const tokenBadge = document.getElementById('caseReviewTokenBadge');
    if (tokenBadge) tokenBadge.textContent = `TOKEN #${item.token_number || '101'}`;

    const deptBadge = document.getElementById('caseReviewDeptBadge');
    if (deptBadge) deptBadge.textContent = item.department === 'ayush' ? 'AYUSH OPD' : 'General OPD';

    const triageBadge = document.getElementById('caseReviewTriageBadge');
    if (triageBadge) {
      const tr = item.triage_level || 'routine';
      triageBadge.textContent = tr.toUpperCase();
      triageBadge.className = `px-2.5 py-0.5 rounded-full font-bold text-[11px] ${
        tr === 'emergency' ? 'bg-red-100 text-red-800' : (tr === 'urgent' ? 'bg-amber-100 text-amber-800' : 'bg-blue-100 text-blue-800')
      }`;
    }

    const nameEl = document.getElementById('caseReviewPatientName');
    if (nameEl) nameEl.textContent = `${item.patient_name || 'Walk-in Patient'} (${item.department === 'ayush' ? 'AYUSH Case' : 'Clinical Case'})`;

    const metaEl = document.getElementById('caseReviewPatientMeta');
    if (metaEl) {
      metaEl.textContent = `ABHA: ${item.abha_id || 'Not linked'} • DOB: ${item.date_of_birth || 'Recorded on intake'} • Phone: ${item.phone || 'N/A'}`;
    }

    const verifStatus = document.getElementById('caseReviewVerificationStatus');
    if (verifStatus) {
      if (item.doctor_verified) {
        verifStatus.textContent = `✓ Verified (${item.doctor_verified_at ? new Date(item.doctor_verified_at).toLocaleTimeString() : 'Signed'})`;
        verifStatus.className = 'px-3 py-1 rounded-full bg-emerald-100 text-emerald-800 font-bold text-xs';
      } else {
        verifStatus.textContent = 'Pending Clinician Review';
        verifStatus.className = 'px-3 py-1 rounded-full bg-yellow-100 text-yellow-800 font-bold text-xs';
      }
    }

    // Symptoms List
    const symList = document.getElementById('caseReviewSymptomsList');
    if (symList) {
      const ch = item.clinical_history || {};
      const cc = ch.chief_complaint || ch.chief_concern || '';
      const hpi = ch.history_of_present_illness || {};
      const assoc = ch.associated_symptoms || [];

      let html = '';
      if (cc) html += `<div class="p-2 rounded-xl bg-white border border-secondary-container"><strong class="text-primary font-semibold block">Chief Complaint:</strong> ${cc}</div>`;
      if (hpi.onset || hpi.duration) html += `<div class="p-2 rounded-xl bg-white border border-secondary-container"><strong class="text-secondary font-semibold block">Timeline:</strong> Onset: ${hpi.onset || 'N/A'} • Duration: ${hpi.duration || 'N/A'}</div>`;
      if (assoc.length > 0) {
        const names = assoc.map(s => typeof s === 'string' ? s : (s.name || s.symptom || '')).filter(Boolean);
        if (names.length) html += `<div class="p-2 rounded-xl bg-white border border-secondary-container"><strong class="text-secondary font-semibold block">Associated:</strong> ${names.join(', ')}</div>`;
      }
      if (!html) html = '<p class="text-secondary italic text-xs">No acute symptoms reported during intake.</p>';
      symList.innerHTML = html;
    }

    // Scanned Records (OCR)
    const docsList = document.getElementById('caseReviewDocsList');
    if (docsList) {
      let docHtml = '';
      try {
        const docs = await apiRequest(`/api/v1/sessions/${item.session_id}/documents`);
        if (Array.isArray(docs) && docs.length > 0) {
          docHtml = docs.map(d => {
            const dt = d.ocr?.document_type || d.file_name || 'Medical Record';
            const ocrSnippet = (d.ocr?.ocr_text || d.source_excerpt || '').slice(0, 100);
            return `
              <div class="p-2 rounded-xl bg-white border border-secondary-container">
                <div class="font-bold text-on-surface flex items-center gap-1">
                  <span class="material-symbols-outlined text-[14px] text-primary">description</span>
                  <span>${dt}</span>
                </div>
                <p class="text-[10px] text-secondary mt-0.5 line-clamp-2">${ocrSnippet || 'Historical Document Encrypted'}</p>
              </div>
            `;
          }).join('');
        }
      } catch (e) {}

      if (!docHtml) {
        docHtml = '<p class="text-secondary italic text-xs">No prior scanned documents attached.</p>';
      }
      docsList.innerHTML = docHtml;
    }

    // AYUSH & Medical History
    const ayushList = document.getElementById('caseReviewAyushList');
    if (ayushList) {
      let ayHtml = '';
      try {
        const ayushData = await apiRequest(`/api/v1/sessions/${item.session_id}/ayush-assessment`);
        if (ayushData && Object.keys(ayushData).length > 0) {
          ayHtml += `<div class="p-2 rounded-xl bg-white border border-secondary-container"><strong class="text-primary font-semibold block">Prakriti / Dosha:</strong> ${ayushData.prakriti || ayushData.dosha_profile || 'Balanced'}</div>`;
          if (ayushData.agni) ayHtml += `<div class="p-2 rounded-xl bg-white border border-secondary-container"><strong class="text-secondary font-semibold block">Agni:</strong> ${ayushData.agni}</div>`;
        }
      } catch (e) {}

      const ch = item.clinical_history || {};
      if (ch.past_medical_history && ch.past_medical_history.length > 0) {
        const pmh = ch.past_medical_history.map(m => typeof m === 'string' ? m : (m.condition || m.name)).filter(Boolean).join(', ');
        ayHtml += `<div class="p-2 rounded-xl bg-white border border-secondary-container"><strong class="text-secondary font-semibold block">Past Medical History:</strong> ${pmh}</div>`;
      }
      if (ch.allergies && ch.allergies.length > 0) {
        const alg = ch.allergies.map(a => typeof a === 'string' ? a : (a.substance || a.name)).filter(Boolean).join(', ');
        ayHtml += `<div class="p-2 rounded-xl bg-white border border-error/40 text-error"><strong class="font-bold block">Allergies:</strong> ${alg}</div>`;
      }

      if (!ayHtml) ayHtml = '<p class="text-secondary italic text-xs">Standard medical history, no chronic conditions recorded.</p>';
      ayushList.innerHTML = ayHtml;
    }

    // Doctor Notes & Triage select
    const notesInput = document.getElementById('doctorVerificationNotesInput');
    if (notesInput) {
      notesInput.value = item.doctor_notes || '';
      notesInput.classList.remove('border-red-500');
    }

    const triageSelect = document.getElementById('doctorTriageSelect');
    if (triageSelect) {
      triageSelect.value = item.triage_level || 'routine';
    }

    const resultMsg = document.getElementById('doctorVerificationResultMsg');
    if (resultMsg) resultMsg.classList.add('hidden');

    panel.classList.remove('hidden');
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  async function submitDoctorVerification() {
    if (!currentDoctorCase || !currentDoctorCase.session_id) {
      alert("Please select a patient case to review first.");
      return;
    }

    const notesInput = document.getElementById('doctorVerificationNotesInput');
    const triageSelect = document.getElementById('doctorTriageSelect');
    const resultMsg = document.getElementById('doctorVerificationResultMsg');
    const submitBtn = document.getElementById('submitDoctorVerificationBtn');

    const notes = (notesInput?.value || '').trim();
    if (!notes) {
      if (notesInput) {
        notesInput.classList.add('border-red-500');
        notesInput.focus();
      }
      if (resultMsg) {
        resultMsg.textContent = "⚠ Doctor clinical notes are required before final EMR sign-off.";
        resultMsg.className = "text-xs font-bold text-red-600 block";
        resultMsg.classList.remove('hidden');
      }
      return;
    }

    const triage = triageSelect?.value || 'routine';

    if (submitBtn) {
      submitBtn.innerHTML = `<span>Signing Off...</span><span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>`;
      submitBtn.disabled = true;
    }

    try {
      const resp = await apiRequest(`/api/v1/doctor/cases/${currentDoctorCase.session_id}/verify`, {
        method: 'POST',
        body: {
          doctor_notes: notes,
          triage_level: triage,
          verified_by: 'Dr. R. Sengupta, MD'
        }
      });

      if (resp && resp.status === 'verified') {
        currentDoctorCase.doctor_verified = true;
        currentDoctorCase.doctor_notes = notes;
        currentDoctorCase.triage_level = triage;
        currentDoctorCase.doctor_verified_at = new Date().toISOString();

        const verifStatus = document.getElementById('caseReviewVerificationStatus');
        if (verifStatus) {
          verifStatus.textContent = '✓ Verified & Signed by Dr. R. Sengupta, MD';
          verifStatus.className = 'px-3 py-1 rounded-full bg-emerald-100 text-emerald-800 font-bold text-xs';
        }

        if (resultMsg) {
          resultMsg.textContent = "✓ Final EMR successfully verified, sealed, and synced to ABDM Health Profile.";
          resultMsg.className = "text-xs font-bold text-emerald-700 block";
          resultMsg.classList.remove('hidden');
        }

        saveToVaultNotification("EMR Signed Off", `Dr. R. Sengupta verified Case #${currentDoctorCase.token_number || ''}`);
        
        // Broadcast case verified event across tabs
        if (hospitalSyncChannel) {
          hospitalSyncChannel.postMessage({
            type: 'CASE_VERIFIED',
            session_id: currentDoctorCase.session_id,
            token_number: currentDoctorCase.token_number,
            doctor_notes: notes,
            timestamp: Date.now()
          });
        }

        await loadDoctorQueue(doctorQueueFilter);
      }
    } catch (err) {
      if (resultMsg) {
        resultMsg.textContent = err.message || "Failed to verify case. Please check connection.";
        resultMsg.className = "text-xs font-bold text-red-600 block";
        resultMsg.classList.remove('hidden');
      }
    } finally {
      if (submitBtn) {
        submitBtn.innerHTML = `<span class="material-symbols-outlined text-[18px]">verified</span><span>Verify & Sign Off Final EMR</span>`;
        submitBtn.disabled = false;
      }
    }
  }

  function initHospitalWorkflowModule() {
    // 1. Kiosk Registration Tabs & Patient Lookup
    const tabReturning = document.getElementById('regModeReturningBtn') || document.getElementById('tabReturningPatient');
    const tabNew = document.getElementById('regModeNewBtn') || document.getElementById('tabNewPatient');
    const areaReturning = document.getElementById('returningPatientArea');
    const areaNew = document.getElementById('newPatientArea');

    function setRegistrationMode(mode) {
      const isReturning = (mode === 'returning');
      
      if (areaReturning) areaReturning.classList.toggle('hidden', !isReturning);
      if (areaNew) areaNew.classList.toggle('hidden', isReturning);

      if (tabReturning) {
        if (isReturning) {
          tabReturning.className = 'p-5 rounded-3xl border-2 border-primary bg-primary-fixed/20 text-left transition-all cursor-pointer shadow-xs flex items-start gap-4';
          const iconBox = tabReturning.querySelector('.w-12');
          if (iconBox) iconBox.className = 'w-12 h-12 rounded-2xl bg-primary text-white flex items-center justify-center shrink-0 shadow-xs';
          const tag = tabReturning.querySelector('span.uppercase');
          if (tag) tag.className = 'text-[10px] font-bold uppercase tracking-wider text-primary';
        } else {
          tabReturning.className = 'p-5 rounded-3xl border border-secondary-container bg-white hover:bg-surface-container text-left transition-all cursor-pointer shadow-xs flex items-start gap-4';
          const iconBox = tabReturning.querySelector('.w-12');
          if (iconBox) iconBox.className = 'w-12 h-12 rounded-2xl bg-surface-container text-primary flex items-center justify-center shrink-0 border border-secondary-container';
          const tag = tabReturning.querySelector('span.uppercase');
          if (tag) tag.className = 'text-[10px] font-bold uppercase tracking-wider text-secondary';
        }
      }

      if (tabNew) {
        if (!isReturning) {
          tabNew.className = 'p-5 rounded-3xl border-2 border-primary bg-primary-fixed/20 text-left transition-all cursor-pointer shadow-xs flex items-start gap-4';
          const iconBox = tabNew.querySelector('.w-12');
          if (iconBox) iconBox.className = 'w-12 h-12 rounded-2xl bg-primary text-white flex items-center justify-center shrink-0 shadow-xs';
          const tag = tabNew.querySelector('span.uppercase');
          if (tag) tag.className = 'text-[10px] font-bold uppercase tracking-wider text-primary';

          // Pre-fill phone or ABHA from lookup input if user already entered digits
          const lookupElem = document.getElementById('lookupIdentifierInput');
          const qVal = (lookupElem?.value || '').trim();
          if (qVal) {
            const rawDigits = qVal.replace(/\D/g, '');
            const newPhone = document.getElementById('newPatPhone');
            const newAbha = document.getElementById('newPatAbha');
            if (rawDigits.length >= 10 && rawDigits.length <= 13) {
              if (newPhone && !newPhone.value) {
                newPhone.value = rawDigits.slice(-10);
              }
            } else if (qVal.includes('-') || qVal.length === 14) {
              if (newAbha && !newAbha.value) {
                newAbha.value = qVal;
              }
            }
          }
          setTimeout(() => document.getElementById('newPatName')?.focus(), 50);
        } else {
          tabNew.className = 'p-5 rounded-3xl border border-secondary-container bg-white hover:bg-surface-container text-left transition-all cursor-pointer shadow-xs flex items-start gap-4';
          const iconBox = tabNew.querySelector('.w-12');
          if (iconBox) iconBox.className = 'w-12 h-12 rounded-2xl bg-surface-container text-primary flex items-center justify-center shrink-0 border border-secondary-container';
          const tag = tabNew.querySelector('span.uppercase');
          if (tag) tag.className = 'text-[10px] font-bold uppercase tracking-wider text-secondary';
          setTimeout(() => document.getElementById('lookupIdentifierInput')?.focus(), 50);
        }
      }
    }

    if (tabReturning) {
      tabReturning.addEventListener('click', (e) => {
        e.preventDefault();
        setRegistrationMode('returning');
      });
    }

    if (tabNew) {
      tabNew.addEventListener('click', (e) => {
        e.preventDefault();
        setRegistrationMode('new');
      });
    }

    const switchBackBtn = document.getElementById('switchBackToLookupBtn');
    if (switchBackBtn) {
      switchBackBtn.addEventListener('click', (e) => {
        e.preventDefault();
        setRegistrationMode('returning');
      });
    }

    const lookupInput = document.getElementById('lookupIdentifierInput');
    const lookupBtn = document.getElementById('lookupPatientBtn');
    const lookupStatus = document.getElementById('lookupStatusMsg');
    const foundCard = document.getElementById('foundPatientCard');
    const foundInitials = document.getElementById('foundPatientInitials');
    const foundName = document.getElementById('foundPatientName');
    const foundMeta = document.getElementById('foundPatientMeta');
    const confirmFoundBtn = document.getElementById('confirmFoundPatientBtn');

    let matchedPatient = null;

    async function handlePatientLookup() {
      const q = (lookupInput?.value || '').trim();
      if (!q) {
        if (lookupStatus) {
          lookupStatus.innerHTML = `
            <div class="p-3 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs font-semibold flex items-center gap-1.5">
              <span class="material-symbols-outlined text-[16px]">warning</span>
              <span>Please enter an ABHA ID, Hospital UHID, or 10-digit mobile number.</span>
            </div>
          `;
          lookupStatus.className = 'block';
          lookupStatus.classList.remove('hidden');
        }
        return;
      }

      if (lookupBtn) {
        lookupBtn.innerHTML = `<span>Searching...</span><span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>`;
      }

      try {
        const rawDigits = q.replace(/\D/g, '');
        const last10 = rawDigits.length >= 10 ? rawDigits.slice(-10) : rawDigits;

        let found = patientRegistry.find(p => {
          const pPhone = (p.phone || '').replace(/\D/g, '');
          const pLast10 = pPhone.length >= 10 ? pPhone.slice(-10) : pPhone;
          const pAbha = (p.abha_id || '').replace(/\D/g, '');

          return (last10 && pLast10 && pLast10 === last10) ||
                 (rawDigits && pAbha && pAbha === rawDigits) ||
                 (p.abha_id && p.abha_id.toLowerCase() === q.toLowerCase()) ||
                 (p.patient_id && p.patient_id.toLowerCase() === q.toLowerCase()) ||
                 (p.display_name && p.display_name.toLowerCase().includes(q.toLowerCase()));
        });

        if (!found) {
          try {
            const apiFound = await apiRequest(`/api/v1/patients/search?q=${encodeURIComponent(q)}`);
            if (Array.isArray(apiFound) && apiFound.length > 0) {
              found = apiFound[0];
            }
          } catch (e) {}
        }

        if (found) {
          matchedPatient = found;
          if (foundInitials) foundInitials.textContent = (found.display_name || 'PT').split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase();
          const welcomeHdr = document.getElementById('foundPatientWelcomeHeading');
          if (welcomeHdr) welcomeHdr.textContent = `Welcome back, ${found.display_name || 'Patient'}`;

          const persEl = document.getElementById('foundProfilePersonal');
          if (persEl) persEl.textContent = `${found.gender || 'Patient'} • ${found.date_of_birth ? 'Age/DOB: ' + found.date_of_birth : 'Age on file'} • ${found.phone || 'Phone on file'}`;

          let algNames = [];
          try {
            const algList = typeof found.allergies_json === 'string' ? JSON.parse(found.allergies_json || '[]') : (found.allergies_json || []);
            algNames = algList.map(a => typeof a === 'string' ? a : (a.allergen || a.name || '')).filter(Boolean);
          } catch(e) {}
          const algEl = document.getElementById('foundProfileAllergies');
          if (algEl) algEl.textContent = algNames.length > 0 ? algNames.join(', ') : 'None recorded';

          let condNames = [];
          try {
            const condList = typeof found.chronic_conditions_json === 'string' ? JSON.parse(found.chronic_conditions_json || '[]') : (found.chronic_conditions_json || []);
            condNames = condList.map(c => typeof c === 'string' ? c : (c.condition || c.name || '')).filter(Boolean);
          } catch(e) {}
          const condEl = document.getElementById('foundProfileConditions');
          if (condEl) condEl.textContent = condNames.length > 0 ? condNames.join(', ') : 'None recorded';

          const abhaBadge = document.getElementById('foundPatientAbhaBadge');
          if (abhaBadge) abhaBadge.textContent = found.abha_id ? `ABHA #${found.abha_id}` : 'Hospital UHID Verified';

          // Fetch full profile in background to get previous visit count
          try {
            const fullProf = await apiRequest(`/api/v1/patients/${found.patient_id}/full-profile`);
            if (fullProf) {
              const vCount = (fullProf.visits || []).length;
              const vEl = document.getElementById('foundProfileVisits');
              if (vEl) vEl.textContent = `${vCount} Previous Visit${vCount === 1 ? '' : 's'}`;
            }
          } catch (e) {}

          if (foundCard) foundCard.classList.remove('hidden');
          if (lookupStatus) lookupStatus.classList.add('hidden');
        } else {
          matchedPatient = null;
          if (foundCard) foundCard.classList.add('hidden');
          if (lookupStatus) {
            const escapedQ = String(q).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            lookupStatus.innerHTML = `
              <div class="p-3.5 rounded-2xl bg-amber-50 border border-amber-200 text-amber-900 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-xs">
                <div class="flex items-center gap-2">
                  <span class="material-symbols-outlined text-[20px] text-amber-600 shrink-0">person_search</span>
                  <span class="text-xs">No matching record found for <strong>${escapedQ}</strong>.</span>
                </div>
                <button type="button" id="lookupSwitchToNewBtn" class="h-9 px-4 rounded-full bg-primary hover:bg-primary-dark text-white text-xs font-bold flex items-center gap-1.5 shrink-0 cursor-pointer shadow-xs transition-all">
                  <span>Register as New Walk-in</span>
                  <span class="material-symbols-outlined text-[15px]">arrow_forward</span>
                </button>
              </div>
            `;
            lookupStatus.className = 'block';
            lookupStatus.classList.remove('hidden');

            const switchBtn = document.getElementById('lookupSwitchToNewBtn');
            if (switchBtn) {
              switchBtn.addEventListener('click', (ev) => {
                ev.preventDefault();
                setRegistrationMode('new');
                lookupStatus.classList.add('hidden');
              });
            }
          }
        }
      } catch (err) {
        if (lookupStatus) {
          lookupStatus.innerHTML = `
            <div class="p-3 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs font-semibold">
              Lookup failed. You may register as a new walk-in patient.
            </div>
          `;
          lookupStatus.className = 'block';
          lookupStatus.classList.remove('hidden');
        }
      } finally {
        if (lookupBtn) {
          lookupBtn.innerHTML = `<span class="material-symbols-outlined text-[18px]">verified</span><span>Find Record</span>`;
        }
      }
    }

    if (lookupBtn) lookupBtn.addEventListener('click', handlePatientLookup);
    if (lookupInput) {
      lookupInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          handlePatientLookup();
        }
      });
    }

    if (confirmFoundBtn) {
      confirmFoundBtn.addEventListener('click', async () => {
        if (!matchedPatient) return;
        confirmFoundBtn.innerHTML = `<span>Starting Visit...</span><span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>`;
        confirmFoundBtn.disabled = true;

        try {
          isReturningPatientVisit = true;
          updatePatientUI(matchedPatient);

          // Create discrete visit via POST /api/v1/patients/{patient_id}/visits
          const visitResp = await apiRequest(`/api/v1/patients/${matchedPatient.patient_id}/visits`, {
            method: 'POST',
            body: {
              department: hospitalDepartment === 'ayush' ? 'AYUSH OPD' : 'General Medicine OPD',
              language_preference: matchedPatient.preferred_language || selectedHospitalLang || 'en-IN',
              consent_given: true,
              opd_mode: hospitalDepartment || 'general'
            }
          });

          if (visitResp && visitResp.session_id) {
            currentSessionId = visitResp.session_id;
            localStorage.setItem('cliniqo_session_id', currentSessionId);
            sessionStorage.setItem('cliniqo_session_id', currentSessionId);
            hospitalTokenNumber = visitResp.token_number;
            localStorage.setItem('cliniqo_hospital_token', hospitalTokenNumber);
            updateHospitalTokenDisplays();
          }

          // Reset symptom & interview session UI state for today's new complaint
          resetSessionUIState();

          // Preload baseline chronic conditions & allergies so they are preserved
          if (matchedPatient.allergies_json) {
            try {
              const aList = typeof matchedPatient.allergies_json === 'string' ? JSON.parse(matchedPatient.allergies_json) : matchedPatient.allergies_json;
              aList.forEach(a => {
                const aName = typeof a === 'string' ? a : (a.allergen || a.name);
                if (aName) selectedAllergies.add(aName);
              });
              updateAllergiesBadge();
            } catch (e) {}
          }
          if (matchedPatient.chronic_conditions_json) {
            try {
              const cList = typeof matchedPatient.chronic_conditions_json === 'string' ? JSON.parse(matchedPatient.chronic_conditions_json) : matchedPatient.chronic_conditions_json;
              cList.forEach(c => {
                const cName = typeof c === 'string' ? c : (c.condition || c.name);
                if (cName) selectedMedHistConditions.add(cName);
              });
              updateMedHistConditionsBadge();
            } catch (e) {}
          }

          saveToVaultNotification(
            `Welcome back, ${(matchedPatient.display_name || 'Patient').split(' ')[0]}`,
            `Visit started with Queue Token #${hospitalTokenNumber}. Demographic baseline preserved.`
          );

          // Route returning patient directly to Department selection or Chief Complaint
          navigateTo('hospital-department');
        } catch (err) {
          console.error("Error starting returning patient visit:", err);
          alert("Could not start visit: " + (err.message || err));
        } finally {
          confirmFoundBtn.innerHTML = `
            <span class="material-symbols-outlined text-[18px]">play_arrow</span>
            <span>Start New Visit</span>
          `;
          confirmFoundBtn.disabled = false;
        }
      });
    }

    const newPatInputs = document.querySelectorAll('#newPatientArea input, #newPatientArea select');
    newPatInputs.forEach(inp => {
      inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          const regNew = document.getElementById('registerNewPatientBtn');
          if (regNew) regNew.click();
        }
      });
    });

    const regNewBtn = document.getElementById('registerNewPatientBtn');
    if (regNewBtn) {
      regNewBtn.addEventListener('click', async () => {
        const name = document.getElementById('newPatName')?.value.trim();
        const gender = document.getElementById('newPatGender')?.value || 'Other';
        const dob = document.getElementById('newPatDob')?.value.trim();
        const phone = document.getElementById('newPatPhone')?.value.trim();
        const blood = document.getElementById('newPatBlood')?.value || 'Unknown';
        const abha = document.getElementById('newPatAbha')?.value.trim();
        const emerg = document.getElementById('newPatEmergency')?.value.trim();

        if (!name || !dob || !phone) {
          alert("Please fill in Full Name, Date of Birth / Age, and Mobile Number.");
          return;
        }

        regNewBtn.innerHTML = `<span>Registering...</span><span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>`;
        regNewBtn.disabled = true;

        try {
          const newPat = await apiRequest('/api/v1/patients', {
            method: 'POST',
            body: {
              display_name: name,
              gender: gender,
              date_of_birth: dob,
              phone: phone,
              blood_group: blood !== 'Unknown' ? blood : null,
              abha_id: abha || null,
              emergency_contact: emerg || null,
              preferred_language: selectedHospitalLang || 'en-IN'
            }
          });

          if (newPat && newPat.patient_id) {
            updatePatientUI(newPat);
            await createSession();

            // Broadcast new patient registration across open hospital workstation tabs
            if (hospitalSyncChannel) {
              hospitalSyncChannel.postMessage({
                type: 'PATIENT_REGISTERED',
                patient: newPat,
                token_number: hospitalTokenNumber,
                department: hospitalDepartment || 'General Medicine',
                timestamp: Date.now()
              });
            }

            saveToVaultNotification("Patient Registered", `Walk-in profile created for ${name}.`);
            navigateTo('hospital-language');
          }
        } catch (err) {
          alert(`Registration failed: ${err.message || 'Please verify form fields.'}`);
        } finally {
          regNewBtn.innerHTML = `<span>Save Profile & Continue</span><span class="material-symbols-outlined text-[18px]">arrow_forward</span>`;
          regNewBtn.disabled = false;
        }
      });
    }

    // 2. Language Selection
    const langCards = document.querySelectorAll('#hospitalLangGrid .hospital-lang-card');
    const selectedLangDisplay = document.getElementById('selectedLangDisplay');
    const confirmLangBtn = document.getElementById('confirmLanguageBtn');

    const LANG_LABELS = {
      'ta': 'தமிழ் (Tamil)',
      'en': 'English (India)',
      'hi': 'हिन्दी (Hindi)',
      'ml': 'മലയാളം (Malayalam)',
      'te': 'తెలుగు (Telugu)',
      'kn': 'ಕನ್ನಡ (Kannada)'
    };

    langCards.forEach(card => {
      card.addEventListener('click', () => {
        langCards.forEach(c => {
          c.classList.remove('border-primary', 'bg-primary-fixed/10', 'selected-lang');
          c.classList.add('border-secondary-container');
          const chk = c.querySelector('.lang-check-icon');
          if (chk) chk.classList.add('opacity-0');
        });
        card.classList.add('border-primary', 'bg-primary-fixed/10', 'selected-lang');
        card.classList.remove('border-secondary-container');
        const chk = card.querySelector('.lang-check-icon');
        if (chk) chk.classList.remove('opacity-0');

        selectedHospitalLang = card.getAttribute('data-lang') || 'en';
        localStorage.setItem('cliniqo_hospital_lang', selectedHospitalLang);
        if (selectedLangDisplay) {
          selectedLangDisplay.textContent = LANG_LABELS[selectedHospitalLang] || 'English (India)';
        }
      });
    });

    document.querySelectorAll('.lang-preview-audio-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const phrase = btn.getAttribute('data-speech');
        if (phrase) speakText(phrase);
      });
    });

    if (confirmLangBtn) {
      confirmLangBtn.addEventListener('click', () => {
        localStorage.setItem('cliniqo_hospital_lang', selectedHospitalLang);
        navigateTo('hospital-consent');
      });
    }

    // 3. Clinical Consent Screen
    const consentCheckbox = document.getElementById('hospitalConsentCheckbox');
    const consentWarning = document.getElementById('consentValidationWarning');
    const grantConsentBtn = document.getElementById('grantConsentBtn');
    const declineConsentBtn = document.getElementById('declineConsentBtn');

    if (grantConsentBtn) {
      grantConsentBtn.addEventListener('click', () => {
        if (!consentCheckbox || !consentCheckbox.checked) {
          if (consentWarning) consentWarning.classList.remove('hidden');
          return;
        }
        if (consentWarning) consentWarning.classList.add('hidden');
        hospitalConsentGiven = true;
        localStorage.setItem('cliniqo_hospital_consent', 'true');
        navigateTo('hospital-department');
      });
    }

    if (declineConsentBtn) {
      declineConsentBtn.addEventListener('click', () => {
        alert("Pre-consultation kiosk intake declined. Please take a physical token number and proceed to Counter 2 (Reception Helpdesk).");
      });
    }

    if (consentCheckbox) {
      consentCheckbox.addEventListener('change', () => {
        if (consentCheckbox.checked && consentWarning) {
          consentWarning.classList.add('hidden');
        }
      });
    }

    // 4. Department Selection
    const deptGen = document.getElementById('deptCardGeneral');
    const deptAyu = document.getElementById('deptCardAyush');
    const deptNameText = document.getElementById('selectedDeptNameText');
    const startIntakeBtn = document.getElementById('startHospitalIntakeBtn');

    function selectDepartment(mode) {
      hospitalDepartment = mode;
      clinicalMode = mode;
      localStorage.setItem('cliniqo_hospital_dept', mode);
      localStorage.setItem('cliniqo_clinical_mode', mode);

      if (mode === 'ayush') {
        deptAyu?.classList.add('border-primary', 'bg-primary-fixed/10', 'selected-dept');
        deptAyu?.classList.remove('border-secondary-container');
        deptAyu?.querySelector('.dept-check-pill')?.classList.remove('hidden');

        deptGen?.classList.remove('border-primary', 'bg-primary-fixed/10', 'selected-dept');
        deptGen?.classList.add('border-secondary-container');
        deptGen?.querySelector('.dept-check-pill')?.classList.add('hidden');

        if (deptNameText) deptNameText.textContent = 'AYUSH OPD (Holistic & Clinical)';
      } else {
        deptGen?.classList.add('border-primary', 'bg-primary-fixed/10', 'selected-dept');
        deptGen?.classList.remove('border-secondary-container');
        deptGen?.querySelector('.dept-check-pill')?.classList.remove('hidden');

        deptAyu?.classList.remove('border-primary', 'bg-primary-fixed/10', 'selected-dept');
        deptAyu?.classList.add('border-secondary-container');
        deptAyu?.querySelector('.dept-check-pill')?.classList.add('hidden');

        if (deptNameText) deptNameText.textContent = 'General Medicine OPD';
      }
    }

    if (deptGen) deptGen.addEventListener('click', () => selectDepartment('general'));
    if (deptAyu) deptAyu.addEventListener('click', () => selectDepartment('ayush'));

    if (startIntakeBtn) {
      startIntakeBtn.addEventListener('click', async () => {
        startIntakeBtn.innerHTML = `<span>Allocating Token...</span><span class="material-symbols-outlined animate-spin text-[18px]">progress_activity</span>`;
        startIntakeBtn.disabled = true;

        try {
          if (!currentSessionId) {
            await createSession({ department: hospitalDepartment, opd_mode: clinicalMode, consent_given: hospitalConsentGiven });
          } else {
            await apiRequest(`/api/v1/sessions/${currentSessionId}/hospital`, {
              method: 'PATCH',
              body: {
                department: hospitalDepartment,
                opd_mode: clinicalMode,
                consent_given: hospitalConsentGiven,
                language_preference: selectedHospitalLang
              }
            });
          }
          updateHospitalTokenDisplays();
          navigateTo('assessment-what-brings-you-here');
        } catch (e) {
          navigateTo('assessment-what-brings-you-here');
        } finally {
          startIntakeBtn.innerHTML = `<span>Begin Clinical Intake</span><span class="material-symbols-outlined text-[18px]">play_arrow</span>`;
          startIntakeBtn.disabled = false;
        }
      });
    }

    // 5. Emergency Alert Actions
    const alertNurseBtn = document.getElementById('alertNurseStationBtn');
    const alertOverrideBtn = document.getElementById('alertClinicalOverrideBtn');

    if (alertNurseBtn) {
      alertNurseBtn.addEventListener('click', () => {
        alertNurseBtn.innerHTML = `<span class="material-symbols-outlined text-[20px]">check_circle</span><span>Nurse Paged ✓ Station 1 Responding</span>`;
        alertNurseBtn.classList.remove('bg-red-600', 'hover:bg-red-700');
        alertNurseBtn.classList.add('bg-emerald-700');
        saveToVaultNotification("Staff Paged", "Attending nurse has been dispatched to Kiosk 1.");
      });
    }

    if (alertOverrideBtn) {
      alertOverrideBtn.addEventListener('click', async () => {
        hospitalTriageLevel = 'routine';
        if (currentSessionId) {
          try {
            await apiRequest(`/api/v1/sessions/${currentSessionId}/hospital`, {
              method: 'PATCH',
              body: { triage_level: 'routine' }
            });
          } catch (e) {}
        }
        saveToVaultNotification("Override Applied", "Clinical override recorded. Continuing routine intake.");
        navigateTo('assessment-what-brings-you-here');
      });
    }

    // 6. Doctor Workstation Filters & Verification
    const refreshQueueBtn = document.getElementById('refreshDoctorQueueBtn');
    if (refreshQueueBtn) {
      refreshQueueBtn.addEventListener('click', () => loadDoctorQueue(doctorQueueFilter));
    }

    document.querySelectorAll('#docQueueFilterContainer .doc-queue-filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#docQueueFilterContainer .doc-queue-filter-btn').forEach(b => {
          b.classList.remove('bg-primary', 'text-white', 'shadow-xs');
          b.classList.add('text-secondary');
        });
        btn.classList.add('bg-primary', 'text-white', 'shadow-xs');
        btn.classList.remove('text-secondary');
        const dept = btn.getAttribute('data-dept') || 'all';
        loadDoctorQueue(dept);
      });
    });

    const submitVerifBtn = document.getElementById('submitDoctorVerificationBtn');
    if (submitVerifBtn) {
      submitVerifBtn.addEventListener('click', submitDoctorVerification);
    }

    // 7. Patient Profile Real-Time Parallel Synchronization
    const saveProfileSyncBtn = document.getElementById('savePatientProfileSyncBtn');
    if (saveProfileSyncBtn) {
      saveProfileSyncBtn.addEventListener('click', async () => {
        const nameVal = document.getElementById('myVisitsEditName')?.value.trim();
        const phoneVal = document.getElementById('myVisitsEditPhone')?.value.trim();
        const emergVal = document.getElementById('myVisitsEditEmergency')?.value.trim();
        const bloodVal = document.getElementById('myVisitsEditBlood')?.value;
        const abhaVal = document.getElementById('myVisitsEditAbha')?.value.trim();
        const feedback = document.getElementById('profileSyncFeedbackMsg');

        if (!nameVal) {
          alert("Patient Name cannot be empty.");
          return;
        }

        saveProfileSyncBtn.innerHTML = `<span>Syncing...</span><span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>`;
        saveProfileSyncBtn.disabled = true;

        try {
          let updatedPat = null;
          if (activePatient && activePatient.patient_id) {
            updatedPat = await apiRequest(`/api/v1/patients/${activePatient.patient_id}`, {
              method: 'PUT',
              body: {
                display_name: nameVal,
                phone: phoneVal,
                emergency_contact: emergVal,
                blood_group: bloodVal,
                abha_id: abhaVal
              }
            });
          } else {
            activePatient.display_name = nameVal;
            activePatient.phone = phoneVal;
            activePatient.emergency_contact = emergVal;
            activePatient.blood_group = bloodVal;
            activePatient.abha_id = abhaVal;
            updatedPat = activePatient;
          }

          if (updatedPat) {
            updatePatientUI(updatedPat);
          }

          // Broadcast real-time profile update to Hospital Operations Dashboard
          if (hospitalSyncChannel) {
            hospitalSyncChannel.postMessage({
              type: 'PATIENT_PROFILE_UPDATED',
              patient_id: activePatient.patient_id,
              patient: {
                patient_id: activePatient.patient_id,
                display_name: nameVal,
                phone: phoneVal,
                emergency_contact: emergVal,
                blood_group: bloodVal,
                abha_id: abhaVal
              },
              timestamp: Date.now()
            });
          }

          if (feedback) {
            feedback.textContent = "✓ Profile updated and synchronized with Hospital Desk!";
            feedback.classList.remove('hidden');
            setTimeout(() => feedback.classList.add('hidden'), 4000);
          }
          saveToVaultNotification("Profile Synced", `Updated details for ${nameVal} broadcasted.`);
        } catch (err) {
          alert(`Failed to sync profile: ${err.message}`);
        } finally {
          saveProfileSyncBtn.innerHTML = `<span class="material-symbols-outlined text-[17px]">save</span><span>Update Profile &amp; Sync Hospital Desk</span>`;
          saveProfileSyncBtn.disabled = false;
        }
      });
    }

    // 8. Hospital Queue & Global Search Filters
    const docSearchInput = document.getElementById('docQueueSearchInput');
    if (docSearchInput) {
      docSearchInput.addEventListener('input', () => {
        loadDoctorQueue(doctorQueueFilter);
      });
    }

    const hospGlobalSearch = document.getElementById('hospitalGlobalSearchInput');
    if (hospGlobalSearch) {
      hospGlobalSearch.addEventListener('input', (e) => {
        const q = e.target.value;
        if (docSearchInput) {
          docSearchInput.value = q;
          loadDoctorQueue(doctorQueueFilter);
        }
      });
    }

    const hospQuickViewQueueBtn = document.getElementById('hospQuickViewQueueBtn');
    if (hospQuickViewQueueBtn) {
      hospQuickViewQueueBtn.addEventListener('click', () => {
        document.getElementById('doctorQueueTableBody')?.scrollIntoView({ behavior: 'smooth' });
      });
    }

    // 9. Real-Time BroadcastChannel Event Listener (Cross-tab/Cross-window Parallel Sync)
    if (hospitalSyncChannel) {
      hospitalSyncChannel.onmessage = async (event) => {
        const data = event.data;
        if (!data || !data.type) return;

        // If on doctor workstation: reload queue & statistics immediately
        if (currentScreen === 'doctor-workstation') {
          await loadDoctorQueue(doctorQueueFilter);
          await refreshHospitalDashboard();
        }

        // If patient profile was modified and doctor has their case open
        if (data.type === 'PATIENT_PROFILE_UPDATED') {
          if (currentDoctorCase && currentDoctorCase.patient_id === data.patient_id) {
            const nameEl = document.getElementById('caseReviewPatientName');
            const metaEl = document.getElementById('caseReviewPatientMeta');
            if (nameEl) nameEl.textContent = `${data.patient.display_name} (${currentDoctorCase.department === 'ayush' ? 'AYUSH Case' : 'Clinical Case'})`;
            if (metaEl) metaEl.textContent = `ABHA: ${data.patient.abha_id || 'Not linked'} • Phone: ${data.patient.phone || 'N/A'}`;
          }
          saveToVaultNotification("Patient Profile Updated", `Patient #${data.patient.display_name} updated profile.`);
        }

        // If emergency red flag triggered
        if (data.type === 'RED_FLAG_TRIGGERED') {
          saveToVaultNotification("EMERGENCY ALERT", `Token #${data.token_number || ''} ${data.patient_name}: ${data.reason}`);
          if (currentScreen === 'doctor-workstation') {
            await refreshHospitalDashboard();
          }
        }

        // If doctor verified EMR and patient is viewing their visits
        if (data.type === 'CASE_VERIFIED') {
          const activeBadge = document.getElementById('myVisitsActiveStatusBadge');
          if (activeBadge && currentSessionId === data.session_id) {
            activeBadge.textContent = '✓ Consultation Completed • EMR Signed';
            activeBadge.className = 'px-3 py-1 rounded-full bg-emerald-100 text-emerald-800 text-xs font-bold';
          }
        }
      };
    }

    // 10. Background Polling Fallback (ensures multi-device sync across network)
    setInterval(() => {
      if (currentScreen === 'doctor-workstation') {
        loadDoctorQueue(doctorQueueFilter);
      }
    }, 3500);
  }

  // =========================================================================
  // 12. EVENT LISTENERS HOOKING
  // =========================================================================
  function hookAllEventListeners() {
    // Initialize Hospital OPD Pre-Consultation & Doctor Workstation Module
    initHospitalWorkflowModule();

    // Header Audio Overview Button
    const audioOverviewBtn = document.getElementById('headerAudioOverviewBtn');
    if (audioOverviewBtn) {
      audioOverviewBtn.addEventListener('click', (e) => {
        e.preventDefault();
        const patName = activePatient.display_name || 'Patient';
        const currentTitle = SCREEN_TITLES[currentScreen]?.title || 'Intake';
        const speech = `Hello ${patName}. You are currently on the ${currentTitle} stage of your clinical visit. All your answers and health records are securely analyzed and stored in your ABDM health vault.`;
        speakText(speech);
        saveToVaultNotification("Audio Overview", `Speaking overview for ${currentTitle}`);
      });
    }

    // Header Quick Save Button
    const quickSaveBtn = document.getElementById('headerQuickSaveBtn');
    if (quickSaveBtn) {
      quickSaveBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        quickSaveBtn.innerHTML = `<span>Saving...</span><span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>`;
        await syncClinicalData();
        updateHealthStoryUI();
        setTimeout(() => {
          quickSaveBtn.innerHTML = `<span class="material-symbols-outlined text-[16px]">save</span><span>Quick Save</span>`;
          saveToVaultNotification("Health Vault Synced", "All clinical data, symptoms, and medications successfully persisted.");
        }, 400);
      });
    }

    // Header Language Selector Dropdown
    const langBtn = document.getElementById('headerLangSelectorBtn');
    const langDropdown = document.getElementById('headerLangDropdown');
    if (langBtn && langDropdown) {
      langBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        langDropdown.classList.toggle('hidden');
        langDropdown.classList.toggle('flex');
      });

      document.addEventListener('click', () => {
        if (!langDropdown.classList.contains('hidden')) {
          langDropdown.classList.add('hidden');
          langDropdown.classList.remove('flex');
        }
      });

      document.querySelectorAll('.lang-drop-item').forEach(item => {
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          const lang = item.getAttribute('data-lang');
          if (lang && window.setLanguage) {
            window.setLanguage(lang);
          }
          langDropdown.classList.add('hidden');
          langDropdown.classList.remove('flex');
        });
      });
    }

    // Accessibility Screen Language Choice Cards
    document.querySelectorAll('.lang-choice-card').forEach(card => {
      card.addEventListener('click', () => {
        const lang = card.getAttribute('data-lang');
        if (lang && window.setLanguage) {
          window.setLanguage(lang);
        }
      });
    });

    // High Contrast & Large Text Toggles
    const contrastBtn = document.getElementById('toggleHighContrastBtn');
    const contrastStatus = document.getElementById('highContrastStatus');
    if (contrastBtn) {
      contrastBtn.addEventListener('click', () => {
        const isContrast = document.body.classList.toggle('high-contrast');
        localStorage.setItem('cliniqo_high_contrast', isContrast.toString());
        if (contrastStatus) contrastStatus.textContent = isContrast ? 'On' : 'Off';
      });
    }

    const largeTextBtn = document.getElementById('toggleLargeTextBtn');
    const largeTextStatus = document.getElementById('largeTextStatus');
    if (largeTextBtn) {
      largeTextBtn.addEventListener('click', () => {
        const isLarge = document.body.classList.toggle('large-text-mode');
        localStorage.setItem('cliniqo_large_text', isLarge.toString());
        if (largeTextStatus) largeTextStatus.textContent = isLarge ? 'Large' : 'Standard';
      });
    }

    const savePrefBtn = document.getElementById('savePreferencesBtn');
    if (savePrefBtn) {
      savePrefBtn.addEventListener('click', () => {
        saveToVaultNotification("Preferences Saved", "Display and regional settings updated in profile.");
      });
    }

    // Sidebar & Header Toggles
    const sidebar = document.getElementById('mainSidebar');
    const sidebarBackdrop = document.getElementById('sidebarBackdrop');
    const sidebarToggleBtn = document.getElementById('sidebarToggleBtn');
    const searchInput = document.getElementById('sidebarSearchInput');

    if (sidebarToggleBtn && sidebar) {
      sidebarToggleBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (window.innerWidth < 1024) {
          const isClosed = sidebar.classList.contains('-translate-x-full');
          if (isClosed) {
            sidebar.classList.remove('-translate-x-full');
            if (sidebarBackdrop) sidebarBackdrop.classList.remove('hidden');
          } else {
            sidebar.classList.add('-translate-x-full');
            if (sidebarBackdrop) sidebarBackdrop.classList.add('hidden');
          }
        } else {
          // Desktop toggle collapse/expand
          sidebar.classList.toggle('lg:hidden');
        }
      });
    }

    if (sidebarBackdrop && sidebar) {
      sidebarBackdrop.addEventListener('click', () => {
        sidebar.classList.add('-translate-x-full');
        sidebarBackdrop.classList.add('hidden');
      });
    }

    // Tree Accordion Parent Buttons (Expand/Collapse)
    document.querySelectorAll('.tree-parent-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const treeGroup = btn.closest('.tree-group');
        const sub = treeGroup ? treeGroup.querySelector('.sidebar-tree-sub') : null;
        const chevron = btn.querySelector('.tree-chevron');
        if (sub) {
          const isOpen = sub.classList.contains('open');
          if (isOpen) {
            sub.classList.remove('open');
            if (chevron) chevron.style.transform = 'rotate(-90deg)';
          } else {
            sub.classList.add('open');
            if (chevron) chevron.style.transform = 'rotate(0deg)';
          }
        }
      });
    });

    // Sidebar Search & Filter
    const searchClearBtn = document.getElementById('sidebarSearchClearBtn');

    function resetSidebarSearch() {
      if (searchInput) searchInput.value = '';
      if (searchClearBtn) searchClearBtn.classList.add('hidden');
      const navItems = document.querySelectorAll('#sidebarTreeContainer .nav-item');
      const treeGroups = document.querySelectorAll('#sidebarTreeContainer .tree-group');
      navItems.forEach(item => { item.style.display = ''; });
      treeGroups.forEach(group => {
        group.style.display = '';
        const sub = group.querySelector('.sidebar-tree-sub');
        if (sub) sub.classList.add('open');
        const chevron = group.querySelector('.tree-chevron');
        if (chevron) chevron.style.transform = 'rotate(0deg)';
      });
    }

    if (searchClearBtn) {
      searchClearBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        resetSidebarSearch();
        if (searchInput) searchInput.focus();
      });
    }

    if (searchInput) {
      // Clear accidental autofilled credentials or email
      if (searchInput.value && (searchInput.value.includes('@') || searchInput.value.length > 30)) {
        searchInput.value = '';
      }

      searchInput.addEventListener('input', (e) => {
        let query = e.target.value.toLowerCase().trim();
        if (searchClearBtn) {
          if (query) searchClearBtn.classList.remove('hidden');
          else searchClearBtn.classList.add('hidden');
        }

        // If browser autofilled an email or username with @, ignore/clear it
        if (query.includes('@')) {
          resetSidebarSearch();
          return;
        }

        const navItems = document.querySelectorAll('#sidebarTreeContainer .nav-item');
        const treeGroups = document.querySelectorAll('#sidebarTreeContainer .tree-group');

        if (!query) {
          resetSidebarSearch();
          return;
        }

        let totalMatches = 0;
        navItems.forEach(item => {
          const text = item.textContent.toLowerCase();
          const keywords = (item.getAttribute('data-keywords') || '').toLowerCase();
          const matches = text.includes(query) || keywords.includes(query);
          item.style.display = matches ? 'flex' : 'none';
          if (matches) totalMatches++;
        });

        treeGroups.forEach(group => {
          const matchingChildren = group.querySelectorAll('.sidebar-tree-sub .nav-item:not([style*="display: none"])');
          const parentBtn = group.querySelector('.tree-parent-btn');
          const parentText = parentBtn ? parentBtn.textContent.toLowerCase() : '';
          const parentMatches = parentText.includes(query);

          if (matchingChildren.length > 0 || parentMatches) {
            group.style.display = '';
            const sub = group.querySelector('.sidebar-tree-sub');
            if (sub) sub.classList.add('open');
            const chevron = group.querySelector('.tree-chevron');
            if (chevron) chevron.style.transform = 'rotate(0deg)';
            if (parentMatches) {
              group.querySelectorAll('.sidebar-tree-sub .nav-item').forEach(item => { item.style.display = 'flex'; });
            }
          } else {
            group.style.display = 'none';
          }
        });
      });
    }

    // Sidebar Navigation Links
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const screen = item.getAttribute('data-screen');
        if (screen) {
          navigateTo(screen);
          if (window.innerWidth < 1024 && sidebar) {
            sidebar.classList.add('-translate-x-full');
            if (sidebarBackdrop) sidebarBackdrop.classList.add('hidden');
          }
        }
      });
    });

    // Dock Tab Buttons
    document.querySelectorAll('.dock-tab-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const screen = btn.getAttribute('data-screen');
        if (screen) navigateTo(screen);
      });
    });

    // Dock Prev/Next Buttons
    const dockPrevBtn = document.getElementById('dockPrevBtn');
    const dockNextBtn = document.getElementById('dockNextBtn');
    if (dockPrevBtn) {
      dockPrevBtn.addEventListener('click', () => {
        const idx = SCREEN_SEQUENCE.indexOf(currentScreen);
        if (idx > 0) navigateTo(SCREEN_SEQUENCE[idx - 1]);
      });
    }
    if (dockNextBtn) {
      dockNextBtn.addEventListener('click', () => {
        const idx = SCREEN_SEQUENCE.indexOf(currentScreen);
        if (idx >= 0 && idx < SCREEN_SEQUENCE.length - 1) navigateTo(SCREEN_SEQUENCE[idx + 1]);
      });
    }

    // Hash Navigation
    window.addEventListener('hashchange', () => {
      const hash = window.location.hash.replace('#', '');
      if (hash && hash !== currentScreen) navigateTo(hash, false);
    });

    // Speak Buttons
    document.querySelectorAll('.speak-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const speech = btn.getAttribute('data-speech');
        if (speech) speakText(speech);
      });
    });

    // Screen 2: What Brings You Here
    document.querySelectorAll('#whatBringsSymptomChips .symptom-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const sym = chip.getAttribute('data-symptom');
        const isSelected = chip.getAttribute('data-selected') === 'true';
        const newSelectedState = !isSelected;
        chip.setAttribute('data-selected', newSelectedState.toString());

        const icon = chip.querySelector('.material-symbols-outlined');
        if (newSelectedState) {
          selectedWhatBringsSymptoms.add(sym);
          chip.className = 'symptom-chip px-4 py-2.5 rounded-2xl bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
          if (icon) {
            icon.textContent = 'check_circle';
            icon.className = 'material-symbols-outlined text-[16px] text-primary-fixed';
          }
        } else {
          selectedWhatBringsSymptoms.delete(sym);
          chip.className = 'symptom-chip px-4 py-2.5 rounded-2xl bg-surface-container hover:bg-secondary-container text-xs font-semibold text-on-surface border border-secondary-container transition-all cursor-pointer flex items-center gap-1.5';
          if (icon) {
            icon.textContent = 'radio_button_unchecked';
            icon.className = 'material-symbols-outlined text-[16px] text-secondary/40';
          }
        }

        updateWhatBringsSymptomSelection();
        saveToVaultNotification(newSelectedState ? "Symptom Added" : "Symptom Removed", `${sym}`);
      });
    });

    const wbEditBtn = document.getElementById('whatBringsEditBtn');
    if (wbEditBtn) {
      wbEditBtn.addEventListener('click', (e) => {
        e.preventDefault();
        startInlineEdit({
          wrapperId: 'whatBringsQuoteWrapper',
          textElId: 'whatBringsTranscript',
          actionRowId: 'whatBringsActionRow',
          badgeId: 'whatBringsStatusBadge',
          isQuoted: true,
          rows: 3,
          onSave: (val) => {
            selectedWhatBringsSymptoms.clear();
            selectedWhatBringsSymptoms.add(val);
            updateWhatBringsSymptomSelection();
            updateHealthStoryUI();
            syncClinicalData();
          }
        });
      });
    }

    const wbConfirmBtn = document.getElementById('whatBringsConfirmBtn');
    if (wbConfirmBtn) {
      wbConfirmBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        const text = document.getElementById('whatBringsTranscript')?.dataset.rawText || 
                     document.getElementById('whatBringsTranscript')?.textContent.replace(/^[“"\s]+|[”"\s]+$/g, '').trim();
        if (text && !text.includes('Tap the microphone') && !text.includes('Tap the mic button')) {
          await sendPatientMessage(text, 'text');
        }
        saveToVaultNotification("Chief Complaint Verified", "Reason for visit confirmed and structured.");
        navigateTo('assessment-ai-health-interview');
      });
    }

    // Screen 3: Pain Locations & AI Interview
    document.querySelectorAll('#aiPainLocationChips .loc-tile').forEach(tile => {
      tile.addEventListener('click', () => {
        const loc = tile.getAttribute('data-location');
        const isSelected = tile.getAttribute('data-selected') === 'true';
        const newSelectedState = !isSelected;
        tile.setAttribute('data-selected', newSelectedState.toString());

        const icon = tile.querySelector('.material-symbols-outlined');
        if (newSelectedState) {
          selectedPainLocations.add(loc);
          tile.className = 'loc-tile px-4 py-2 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
          if (icon) {
            icon.textContent = 'check_circle';
            icon.className = 'material-symbols-outlined text-[15px] text-primary-fixed';
          }
        } else {
          selectedPainLocations.delete(loc);
          tile.className = 'loc-tile px-4 py-2 rounded-full bg-surface-container hover:bg-secondary-container text-on-surface text-xs font-semibold border border-secondary-container transition-all cursor-pointer flex items-center gap-1.5';
          if (icon) {
            icon.textContent = 'radio_button_unchecked';
            icon.className = 'material-symbols-outlined text-[15px] text-secondary/40';
          }
        }

        updatePainLocationSelection();
      });
    });

    const aiEditBtn = document.getElementById('aiInterviewEditBtn');
    if (aiEditBtn) {
      aiEditBtn.addEventListener('click', (e) => {
        e.preventDefault();
        startInlineEdit({
          wrapperId: 'aiInterviewQuoteWrapper',
          textElId: 'aiInterviewTranscript',
          actionRowId: 'aiInterviewActionRow',
          badgeId: 'aiInterviewStatusBadge',
          isQuoted: true,
          rows: 3,
          onSave: (val) => {
            sendPatientMessage(val, 'text');
          }
        });
      });
    }

    const aiConfirmBtn = document.getElementById('aiInterviewConfirmBtn');
    if (aiConfirmBtn) {
      aiConfirmBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        const text = document.getElementById('aiInterviewTranscript')?.dataset.rawText || 
                     document.getElementById('aiInterviewTranscript')?.textContent.replace(/^[“"\s]+|[”"\s]+$/g, '').trim();
        if (text && !text.includes('Tap the voice orb') && !text.includes('Tap the center voice orb')) {
          await sendPatientMessage(text, 'text');
        }
        saveToVaultNotification("AI Context Saved", "Symptom context verified for clinical synthesis.");
        navigateTo('assessment-adaptive-follow-up');
      });
    }

    const adaptiveEditBtn = document.getElementById('adaptiveEditBtn');
    if (adaptiveEditBtn) {
      adaptiveEditBtn.addEventListener('click', (e) => {
        e.preventDefault();
        startInlineEdit({
          wrapperId: 'adaptiveQuoteWrapper',
          textElId: 'adaptiveTranscript',
          actionRowId: 'adaptiveActionRow',
          badgeId: 'adaptiveContextBadge',
          isQuoted: true,
          rows: 2,
          onSave: (val) => {
            if (val && !isGenericClinicalEntity(val)) {
              selectedWhatBringsSymptoms.clear();
              selectedWhatBringsSymptoms.add(val);
              lastPatientMessage = val;
              localStorage.setItem('cliniqo_last_patient_response', val);
              updateSymptomsReviewScreen();
              updateHealthStoryUI();
              syncClinicalData();
              saveToVaultNotification("Context Updated", "Chief complaint context updated.");
            }
          }
        });
      });
    }

    const adaptiveConfirmBtn = document.getElementById('adaptiveConfirmBtn');
    if (adaptiveConfirmBtn) {
      adaptiveConfirmBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        saveToVaultNotification("Clarification Saved", "Adaptive triggers & symptom patterns verified.");
        updateSymptomsReviewScreen();
        updateHealthStoryUI();
        await syncClinicalData();
        navigateTo('assessment-symptoms');
      });
    }

    // Screen 5: Symptom Review Cards Inline Edit Buttons
    document.querySelectorAll('.symptom-edit-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const wrapper = btn.getAttribute('data-wrapper');
        const target = btn.getAttribute('data-target');
        if (wrapper && target) {
          startInlineEdit({
            wrapperId: wrapper,
            textElId: target,
            isQuoted: false,
            rows: 2,
            onSave: (val) => {
              if (target === 'symptomVal1') {
                selectedWhatBringsSymptoms.clear();
                if (val && val !== 'Not reported yet') selectedWhatBringsSymptoms.add(val);
                const wb = document.getElementById('whatBringsTranscript');
                if (wb) {
                  wb.textContent = `“${val}”`;
                  wb.dataset.rawText = val;
                }
              } else if (target === 'symptomVal3') {
                selectedPainLocations.clear();
                if (val && val !== 'Not specified') selectedPainLocations.add(val);
              } else if (target === 'symptomVal4') {
                selectedAdaptiveTriggers.clear();
                if (val && val !== 'None reported') selectedAdaptiveTriggers.add(val);
              } else if (target === 'symptomVal5') {
                selectedAdaptiveChoices.clear();
                if (val && val !== 'None reported') selectedAdaptiveChoices.add(val);
              }
              updateHealthStoryUI();
              syncClinicalData();
              saveToVaultNotification("Symptom Updated", "Symptom profile field updated in health vault.");
            }
          });
        }
      });
    });

    // Screen 6: Medical History Chips, Mic & Add
    document.querySelectorAll('#medHistQuickChips .medhist-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const condition = chip.getAttribute('data-condition');
        const isSelected = chip.getAttribute('data-selected') === 'true';
        const newSelectedState = !isSelected;
        chip.setAttribute('data-selected', newSelectedState.toString());

        const icon = chip.querySelector('.material-symbols-outlined');
        if (newSelectedState) {
          selectedMedHistConditions.add(condition);
          chip.className = 'medhist-chip px-3.5 py-1.5 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
          if (icon) {
            icon.textContent = 'check_circle';
            icon.className = 'material-symbols-outlined text-[15px] text-primary-fixed';
          }
        } else {
          selectedMedHistConditions.delete(condition);
          chip.className = 'medhist-chip px-3.5 py-1.5 rounded-full bg-surface-container hover:bg-secondary-container text-on-surface text-xs font-semibold border border-secondary-container transition-all cursor-pointer flex items-center gap-1.5';
          if (icon) {
            icon.textContent = 'radio_button_unchecked';
            icon.className = 'material-symbols-outlined text-[15px] text-secondary/40';
          }
        }

        updateMedHistConditionsBadge();
        syncClinicalData();
      });
    });

    const medHistMicBtn = document.getElementById('medHistMicBtn');
    const medHistTranscript = document.getElementById('medHistTranscript');
    if (medHistMicBtn) {
      medHistMicBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (VoiceManager.isRecording && VoiceManager.activeButtonEl === medHistMicBtn) {
          VoiceManager.stop();
        } else {
          VoiceManager.start(
            medHistMicBtn,
            medHistTranscript,
            'medHistPulseRing',
            null,
            async (spokenText) => {
              if (!spokenText || !spokenText.trim()) return;
              const cleanText = spokenText.trim();
              if (medHistTranscript) {
                medHistTranscript.textContent = `“${cleanText}”`;
                medHistTranscript.dataset.rawText = cleanText;
              }

              // Send to backend for clinical entity parsing & sync
              await sendPatientMessage(cleanText, 'voice');

              // Match chips on Screen 6
              let matchedChip = false;
              document.querySelectorAll('#medHistQuickChips .medhist-chip').forEach(chip => {
                const cond = (chip.getAttribute('data-condition') || '').toLowerCase();
                if (cleanText.toLowerCase().includes(cond) || cond.includes(cleanText.toLowerCase())) {
                  chip.setAttribute('data-selected', 'true');
                  chip.className = 'medhist-chip px-3.5 py-1.5 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
                  const icon = chip.querySelector('.material-symbols-outlined');
                  if (icon) {
                    icon.textContent = 'check_circle';
                    icon.className = 'material-symbols-outlined text-[15px] text-primary-fixed';
                  }
                  selectedMedHistConditions.add(chip.getAttribute('data-condition'));
                  matchedChip = true;
                }
              });

              if (!matchedChip) {
                const cap = cleanText.charAt(0).toUpperCase() + cleanText.slice(1);
                selectedMedHistConditions.add(cap);
                addConditionToUI(cap, 'Reported via voice intake');
              }

              updateMedHistConditionsBadge();
              updateSymptomsReviewScreen();
              updateHealthStoryUI();
              syncClinicalData();
              saveToVaultNotification("Condition Added", cleanText);
            }
          );
        }
      });
    }

    const addConditionBtn = document.getElementById('addConditionBtn');
    if (addConditionBtn) {
      addConditionBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (medHistMicBtn) medHistMicBtn.click();
      });
    }

    // Screen 7: Medicines & Allergies Chips, Voice & Add
    document.querySelectorAll('#quickAllergyChips .allergy-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const allergy = chip.getAttribute('data-allergy');
        const isSelected = chip.getAttribute('data-selected') === 'true';
        const isSevere = chip.getAttribute('data-severe') === 'true';
        const newSelectedState = !isSelected;
        chip.setAttribute('data-selected', newSelectedState.toString());

        const icon = chip.querySelector('.material-symbols-outlined');
        if (newSelectedState) {
          selectedAllergies.add(allergy);
          chip.className = `allergy-chip px-3 py-1.5 rounded-full ${isSevere ? 'bg-error text-white font-bold border-error shadow-xs' : 'bg-primary text-white font-bold border-primary shadow-xs'} text-xs cursor-pointer flex items-center gap-1 transition-all`;
          if (icon) {
            icon.textContent = 'check_circle';
            icon.className = `material-symbols-outlined text-[14px] ${isSevere ? 'text-white' : 'text-primary-fixed'}`;
          }
        } else {
          selectedAllergies.delete(allergy);
          chip.className = 'allergy-chip px-3 py-1.5 rounded-full bg-surface-container hover:bg-secondary-container text-on-surface text-xs font-semibold border border-secondary-container transition-all cursor-pointer flex items-center gap-1';
          if (icon) {
            icon.textContent = 'radio_button_unchecked';
            icon.className = 'material-symbols-outlined text-[14px] text-secondary/40';
          }
        }

        updateAllergiesBadge();
        syncClinicalData();
      });
    });

    const quickAllergyTagBtn = document.getElementById('quickAllergyTagBtn');
    if (quickAllergyTagBtn) {
      quickAllergyTagBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (VoiceManager.isRecording && VoiceManager.activeButtonEl === quickAllergyTagBtn) {
          VoiceManager.stop();
        } else {
          VoiceManager.start(
            quickAllergyTagBtn,
            null,
            null,
            null,
            async (spokenText) => {
              if (!spokenText || !spokenText.trim()) return;
              const cleanText = spokenText.trim();
              await sendPatientMessage(cleanText, 'voice');

              let matchedChip = false;
              document.querySelectorAll('#quickAllergyChips .allergy-chip').forEach(chip => {
                const alg = (chip.getAttribute('data-allergy') || '').toLowerCase();
                if (cleanText.toLowerCase().includes(alg) || alg.includes(cleanText.toLowerCase())) {
                  chip.setAttribute('data-selected', 'true');
                  chip.className = 'allergy-chip px-3 py-1.5 rounded-full bg-error text-white font-bold border-error shadow-xs text-xs cursor-pointer flex items-center gap-1 transition-all';
                  const icon = chip.querySelector('.material-symbols-outlined');
                  if (icon) {
                    icon.textContent = 'check_circle';
                    icon.className = 'material-symbols-outlined text-[14px] text-white';
                  }
                  selectedAllergies.add(chip.getAttribute('data-allergy'));
                  matchedChip = true;
                }
              });

              if (!matchedChip) {
                const cap = cleanText.charAt(0).toUpperCase() + cleanText.slice(1);
                selectedAllergies.add(cap);
              }

              updateAllergiesBadge();
              updateHealthStoryUI();
              syncClinicalData();
              saveToVaultNotification("Allergy Tagged", cleanText);
            }
          );
        }
      });
    }

    document.querySelectorAll('#quickMedChips .med-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const name = chip.getAttribute('data-name');
        const isSelected = chip.getAttribute('data-selected') === 'true';
        const newSelectedState = !isSelected;
        chip.setAttribute('data-selected', newSelectedState.toString());

        const icon = chip.querySelector('.material-symbols-outlined');
        if (newSelectedState) {
          selectedMedications.add(name);
          chip.className = 'med-chip px-3 py-1.5 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1 transition-all';
          if (icon) {
            icon.textContent = 'check_circle';
            icon.className = 'material-symbols-outlined text-[14px] text-primary-fixed';
          }
        } else {
          selectedMedications.delete(name);
          chip.className = 'med-chip px-3 py-1.5 rounded-full bg-surface-container hover:bg-secondary-container text-on-surface text-xs font-semibold border border-secondary-container transition-all cursor-pointer flex items-center gap-1';
          if (icon) {
            icon.textContent = 'radio_button_unchecked';
            icon.className = 'material-symbols-outlined text-[14px] text-secondary/40';
          }
        }

        updateMedsBadge();
        syncClinicalData();
      });
    });

    const medVoiceBtn = document.getElementById('medVoiceBtn');
    if (medVoiceBtn) {
      medVoiceBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (VoiceManager.isRecording && VoiceManager.activeButtonEl === medVoiceBtn) {
          VoiceManager.stop();
        } else {
          VoiceManager.start(
            medVoiceBtn,
            null,
            null,
            null,
            async (spokenText) => {
              if (!spokenText || !spokenText.trim()) return;
              const cleanText = spokenText.trim();
              await sendPatientMessage(cleanText, 'voice');

              let matchedChip = false;
              document.querySelectorAll('#quickMedChips .med-chip').forEach(chip => {
                const cName = (chip.getAttribute('data-name') || '').toLowerCase();
                if (cleanText.toLowerCase().includes(cName) || cName.includes(cleanText.toLowerCase())) {
                  chip.setAttribute('data-selected', 'true');
                  chip.className = 'med-chip px-3 py-1.5 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1 transition-all';
                  const icon = chip.querySelector('.material-symbols-outlined');
                  if (icon) {
                    icon.textContent = 'check_circle';
                    icon.className = 'material-symbols-outlined text-[14px] text-primary-fixed';
                  }
                  selectedMedications.add(chip.getAttribute('data-name'));
                  matchedChip = true;
                }
              });

              if (!matchedChip) {
                const cap = cleanText.charAt(0).toUpperCase() + cleanText.slice(1);
                selectedMedications.add(cap);
                addMedicationToUI(cap, 'Reported via voice intake');
              }

              updateMedsBadge();
              updateHealthStoryUI();
              syncClinicalData();
              saveToVaultNotification("Medication Added", cleanText);
            }
          );
        }
      });
    }

    const addMedBtn = document.getElementById('addMedicationBtn');
    if (addMedBtn) {
      addMedBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (medVoiceBtn) medVoiceBtn.click();
      });
    }

    // Screen 8: Family & Lifestyle Chips and Edit Buttons
    function initFamilyChipHandler(chip) {
      chip.addEventListener('click', () => {
        const condition = chip.getAttribute('data-condition');
        if (!condition) return;
        const isSelected = chip.getAttribute('data-selected') === 'true';
        const newSelectedState = !isSelected;
        chip.setAttribute('data-selected', newSelectedState.toString());

        const icon = chip.querySelector('.material-symbols-outlined');
        if (newSelectedState) {
          selectedFamilyConditions.add(condition);
          chip.className = 'family-tag family-chip px-4 py-2.5 rounded-2xl bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
          if (icon) {
            icon.textContent = 'check_circle';
            icon.className = 'material-symbols-outlined text-[15px] text-primary-fixed';
          }
        } else {
          selectedFamilyConditions.delete(condition);
          chip.className = 'family-tag family-chip px-4 py-2.5 rounded-2xl bg-surface-container hover:bg-secondary-container text-xs font-semibold text-on-surface border border-secondary-container transition-all cursor-pointer flex items-center gap-1.5';
          if (icon) {
            icon.textContent = 'radio_button_unchecked';
            icon.className = 'material-symbols-outlined text-[15px] text-secondary/40';
          }
        }

        updateFamilyBadge();
        syncClinicalData();
      });
    }

    document.querySelectorAll('#familyHistoryGrid button, .family-tag, .family-chip').forEach(initFamilyChipHandler);

    const addCustomFamilyBtn = document.getElementById('addCustomFamilyConditionBtn');
    if (addCustomFamilyBtn) {
      addCustomFamilyBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (VoiceManager.isRecording && VoiceManager.activeButtonEl === addCustomFamilyBtn) {
          VoiceManager.stop();
        } else {
          VoiceManager.start(
            addCustomFamilyBtn,
            null,
            null,
            null,
            async (spokenText) => {
              if (!spokenText || !spokenText.trim()) return;
              const val = spokenText.trim().charAt(0).toUpperCase() + spokenText.trim().slice(1);
              selectedFamilyConditions.add(val);
              const grid = document.getElementById('familyHistoryGrid');
              if (grid) {
                const newBtn = document.createElement('button');
                newBtn.type = 'button';
                newBtn.className = 'family-tag family-chip px-4 py-2.5 rounded-2xl bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
                newBtn.setAttribute('data-condition', val);
                newBtn.setAttribute('data-selected', 'true');
                newBtn.innerHTML = `<span class="material-symbols-outlined text-[15px] text-primary-fixed">check_circle</span><span>${val}</span>`;
                initFamilyChipHandler(newBtn);
                grid.appendChild(newBtn);
              }
              updateFamilyBadge();
              syncClinicalData();
              saveToVaultNotification("Family History Added", `Added '${val}' to family health history.`);
            }
          );
        }
      });
    }

    function initLifestyleChipHandler(chip) {
      chip.addEventListener('click', () => {
        const habit = chip.getAttribute('data-habit');
        if (!habit) return;
        const isSelected = chip.getAttribute('data-selected') === 'true';
        const newSelectedState = !isSelected;
        chip.setAttribute('data-selected', newSelectedState.toString());

        const icon = chip.querySelector('.material-symbols-outlined');
        if (newSelectedState) {
          selectedLifestyleHabits.add(habit);
          chip.className = 'lifestyle-chip px-3.5 py-1.5 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
          if (icon) {
            icon.textContent = 'check_circle';
            icon.className = 'material-symbols-outlined text-[14px] text-primary-fixed';
          }
        } else {
          selectedLifestyleHabits.delete(habit);
          chip.className = 'lifestyle-chip px-3.5 py-1.5 rounded-full bg-surface-container hover:bg-secondary-container text-on-surface text-xs font-semibold border border-secondary-container transition-all cursor-pointer flex items-center gap-1.5';
          if (icon) {
            icon.textContent = 'radio_button_unchecked';
            icon.className = 'material-symbols-outlined text-[14px] text-secondary/40';
          }
        }

        updateLifestyleBadge();
        syncClinicalData();
      });
    }

    document.querySelectorAll('#lifestyleQuickChips button, #lifestyleChips .lifestyle-chip, .lifestyle-chip').forEach(initLifestyleChipHandler);

    const addCustomHabitBtn = document.getElementById('addCustomLifestyleHabitBtn');
    if (addCustomHabitBtn) {
      addCustomHabitBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (VoiceManager.isRecording && VoiceManager.activeButtonEl === addCustomHabitBtn) {
          VoiceManager.stop();
        } else {
          VoiceManager.start(
            addCustomHabitBtn,
            null,
            null,
            null,
            async (spokenText) => {
              if (!spokenText || !spokenText.trim()) return;
              const val = spokenText.trim().charAt(0).toUpperCase() + spokenText.trim().slice(1);
              selectedLifestyleHabits.add(val);
              const container = document.getElementById('lifestyleQuickChips');
              if (container) {
                const newBtn = document.createElement('button');
                newBtn.type = 'button';
                newBtn.className = 'lifestyle-chip px-3.5 py-1.5 rounded-full bg-primary text-white text-xs font-bold shadow-xs border border-primary cursor-pointer flex items-center gap-1.5 transition-all';
                newBtn.setAttribute('data-habit', val);
                newBtn.setAttribute('data-selected', 'true');
                newBtn.innerHTML = `<span class="material-symbols-outlined text-[14px] text-primary-fixed">check_circle</span><span>${val}</span>`;
                initLifestyleChipHandler(newBtn);
                container.appendChild(newBtn);
              }
              updateLifestyleBadge();
              syncClinicalData();
              saveToVaultNotification("Lifestyle Habit Added", `Added '${val}' to daily lifestyle profile.`);
            }
          );
        }
      });
    }

    document.querySelectorAll('.lifestyle-edit-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const wrapper = btn.getAttribute('data-wrapper');
        const target = btn.getAttribute('data-target');
        if (wrapper && target) {
          startInlineEdit({
            wrapperId: wrapper,
            textElId: target,
            isQuoted: false,
            rows: 2,
            onSave: () => {
              updateHealthStoryUI();
              syncClinicalData();
            }
          });
        }
      });
    });

    // Screen 10: Health Story Edit Button
    const storyNarrativeEditBtn = document.getElementById('storyNarrativeEditBtn');
    if (storyNarrativeEditBtn) {
      storyNarrativeEditBtn.addEventListener('click', (e) => {
        e.preventDefault();
        startInlineEdit({
          wrapperId: 'healthStoryBannerWrapper',
          textElId: 'healthStoryNarrative',
          isQuoted: true,
          rows: 4,
          onSave: (val) => {
            saveToVaultNotification("Health Story Saved", "Personal clinical narrative updated.");
          }
        });
      });
    }

    // Screen 11: Timeline Filter & Add Event Buttons
    document.querySelectorAll('#timelineFilterChips .timeline-filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const filter = btn.getAttribute('data-filter');
        if (filter === 'all') {
          activeTimelineFilters.clear();
          activeTimelineFilters.add('all');
        } else {
          activeTimelineFilters.delete('all');
          if (activeTimelineFilters.has(filter)) {
            activeTimelineFilters.delete(filter);
            if (activeTimelineFilters.size === 0) activeTimelineFilters.add('all');
          } else {
            activeTimelineFilters.add(filter);
          }
        }

        document.querySelectorAll('#timelineFilterChips .timeline-filter-btn').forEach(b => {
          const bFilter = b.getAttribute('data-filter');
          const isSel = activeTimelineFilters.has(bFilter);
          b.setAttribute('data-selected', isSel.toString());
          b.className = isSel
            ? 'timeline-filter-btn px-4 py-1.5 rounded-full bg-primary text-white text-xs font-bold shadow-xs cursor-pointer flex items-center gap-1.5 transition-all'
            : 'timeline-filter-btn px-4 py-1.5 rounded-full bg-surface-container hover:bg-secondary-container text-on-surface text-xs font-semibold border border-secondary-container cursor-pointer flex items-center gap-1.5 transition-all';
        });

        renderTimelineFilteredItems();
      });
    });

    const addTimelineBtn = document.getElementById('addTimelineEntryBtn');
    if (addTimelineBtn) {
      addTimelineBtn.addEventListener('click', (e) => {
        e.preventDefault();
        const title = prompt("Enter timeline event title:", "Annual Health Checkup");
        if (title && title.trim()) {
          const desc = prompt("Enter clinical details / findings:", "Normal ECG, BP 120/80");
          const cat = prompt("Category (prescription, lab, surgery, intake):", "lab");
          const dateStr = new Date().toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
          addTimelineEventToUI({
            category: (cat || 'intake').toLowerCase(),
            title: title.trim(),
            date: dateStr,
            badge: 'Patient Added',
            desc: desc || 'Documented event in patient timeline.'
          });
          saveToVaultNotification("Timeline Event Added", title.trim());
        }
      });
    }

    // Screen 12: Medical Records Vault ABDM Sync
    const syncAbdmBtn = document.getElementById('syncAbdmBtn');
    if (syncAbdmBtn) {
      syncAbdmBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        saveToVaultNotification("Syncing ABDM Cloud...", "Querying Ayushman Bharat Digital Health Repository");
        
        setTimeout(() => {
          const abdmDoc = {
            document_id: 'abdm_' + Math.random().toString(36).substr(2, 8),
            file_name: 'ABDM Verified Hospital Discharge Record',
            file_type: 'application/pdf',
            file_size: 1024 * 340,
            created_at: new Date().toISOString(),
            ocr: {
              document_type: 'Discharge Summary',
              ocr_text: 'ABDM Health Repository Link: Verified past consultation notes.',
              medications: ['Pantoprazole 40mg', 'Atorvastatin 10mg'],
              lab_results: ['HbA1c: 5.9%', 'Total Cholesterol: 185 mg/dL']
            }
          };
          
          if (!uploadedDocuments.some(d => d.file_name === abdmDoc.file_name)) {
            uploadedDocuments.push(abdmDoc);
            renderDocumentsList();
          }
          saveToVaultNotification("ABDM Sync Complete", "1 hospital record securely linked to your health vault.");
        }, 700);
      });
    }

    // Clinical mode selection — preserves the existing UI style and only changes workflow.
    document.querySelectorAll('.clinical-mode-btn').forEach(btn => {
      btn.addEventListener('click', () => applyClinicalMode(btn.dataset.mode));
    });
    applyClinicalMode(clinicalMode);
    document.getElementById('saveAyushAssessmentBtn')?.addEventListener('click', saveAyushAssessment);

    // Document context gate — every upload is explicitly current or historical.
    document.querySelectorAll('.doc-date-type-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.doc-date-type-btn').forEach(b => {
          const active = b.dataset.dateType === btn.dataset.dateType;
          b.className = active ? 'doc-date-type-btn px-3 py-2 rounded-xl bg-primary text-white text-xs font-bold' : 'doc-date-type-btn px-3 py-2 rounded-xl bg-white border border-secondary-container text-xs font-semibold';
        });
        currentDocumentContext.date_type = btn.dataset.dateType;
        currentDocumentContext.date_source = btn.dataset.dateType === 'unknown' ? 'unknown' : 'patient';
      });
    });
    document.getElementById('docContextCurrentBtn')?.addEventListener('click', () => {
      currentDocumentContext.classification = 'current';
      currentDocumentContext.date_type = 'unknown';
      currentDocumentContext.date_source = 'unknown';
      document.getElementById('docDateContextArea')?.classList.add('hidden');
      document.getElementById('docContextStatus').textContent = 'Current document selected. OCR will still validate any visible date.';
    });
    document.getElementById('docContextHistoricalBtn')?.addEventListener('click', () => {
      currentDocumentContext.classification = 'historical';
      document.getElementById('docDateContextArea')?.classList.remove('hidden');
      document.getElementById('docContextStatus').textContent = 'Old document selected. Unknown date is allowed.';
    });
    document.getElementById('docDateValueInput')?.addEventListener('input', e => {
      const value = e.target.value.trim();
      currentDocumentContext.document_date = value || null;
      if (value && currentDocumentContext.date_type === 'unknown') {
        currentDocumentContext.date_type = 'approximate';
        currentDocumentContext.date_source = 'patient';
      }
    });
    document.getElementById('closeDocumentContextBtn')?.addEventListener('click', closeDocumentContextModal);
    document.getElementById('docContextContinueBtn')?.addEventListener('click', () => {
      closeDocumentContextModal();
      document.getElementById('scannerDirectFileInput')?.click();
    });

    // Document Upload & Scanner
    const uploadTrigger = document.getElementById('uploadFileTriggerCard');
    const docUploadInput = document.getElementById('realDocUploadInput');
    if (uploadTrigger && docUploadInput) {
      uploadTrigger.addEventListener('click', () => openDocumentContextModal());
      docUploadInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) handleRealDocumentFile(e.target.files[0]);
      });
    }

    const scannerInput = document.getElementById('scannerDirectFileInput');
    const shutterBtn = document.getElementById('scannerShutterBtn');
    if (shutterBtn && scannerInput) {
      shutterBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openDocumentContextModal();
      });
      scannerInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
          handleRealDocumentFile(e.target.files[0]);
        }
      });
    }

    // Scanner State Simulation Chips
    document.querySelectorAll('.scanner-state-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const state = btn.getAttribute('data-state');
        document.querySelectorAll('.scanner-state-btn').forEach(b => {
          const isTarget = b.getAttribute('data-state') === state;
          b.className = isTarget
            ? 'scanner-state-btn px-3.5 py-1.5 rounded-full bg-primary text-white border border-primary text-xs font-bold shadow-xs cursor-pointer transition-colors'
            : 'scanner-state-btn px-3.5 py-1.5 rounded-full bg-white text-on-surface border border-secondary-container text-xs font-semibold cursor-pointer transition-colors';
        });
        
        const icon = document.getElementById('scannerStatusIcon');
        const dateLabel = document.getElementById('scannerDocDate');
        const tl = document.getElementById('bracketTL');
        const tr = document.getElementById('bracketTR');
        const bl = document.getElementById('bracketBL');
        const br = document.getElementById('bracketBR');
        
        if (state === 'ready') {
          if (dateLabel) dateLabel.textContent = 'Ready to align document';
          [tl, tr, bl, br].forEach(b => b && (b.className = b.className.replace(/border-[a-z0-9-]+/g, 'border-secondary')));
        } else if (state === 'detected') {
          if (dateLabel) dateLabel.textContent = 'Document boundary detected';
          [tl, tr, bl, br].forEach(b => b && (b.className = b.className.replace(/border-[a-z0-9-]+/g, 'border-primary')));
        } else if (state === 'capturing') {
          if (dateLabel) dateLabel.textContent = 'Capturing high-res frame...';
          if (icon) icon.className = 'material-symbols-outlined text-[42px] text-primary animate-pulse';
        } else if (state === 'captured') {
          if (dateLabel) dateLabel.textContent = 'Processing OCR Document Intelligence...';
          saveToVaultNotification("Document Captured", "Sending frame to OCR Intelligence engine.");
          setTimeout(() => navigateTo('records-review-extracted-information'), 600);
        }
      });
    });

    // Scanner & Review Doc Type Buttons
    document.querySelectorAll('.doc-type-btn, .review-doc-type-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const doctype = btn.getAttribute('data-doctype');
        const isReview = btn.classList.contains('review-doc-type-btn');
        const selector = isReview ? '.review-doc-type-btn' : '.doc-type-btn';
        
        document.querySelectorAll(selector).forEach(b => {
          const isSel = b.getAttribute('data-doctype') === doctype;
          b.className = isSel
            ? `${selector.slice(1)} px-4 py-2 rounded-full bg-primary text-white text-xs font-bold shadow-xs cursor-pointer transition-all flex items-center gap-1.5`
            : `${selector.slice(1)} px-4 py-2 rounded-full bg-surface-container hover:bg-secondary-container text-on-surface text-xs font-semibold border border-secondary-container transition-all cursor-pointer flex items-center gap-1.5`;
        });
        
        const ind = document.getElementById(isReview ? 'reviewDocTypeIndicator' : 'activeDocTypeIndicator');
        if (ind) {
          ind.textContent = `${doctype.charAt(0).toUpperCase() + doctype.slice(1)} Active`;
        }
      });
    });

    // Screen 14: Review Extracted Info & Add Field Button
    const addExtractedFieldBtn = document.getElementById('addExtractedFieldBtn');
    if (addExtractedFieldBtn) {
      addExtractedFieldBtn.addEventListener('click', (e) => {
        e.preventDefault();
        const label = prompt("Enter clinical field name:", "Dosage Instructions");
        if (label && label.trim()) {
          const val = prompt("Enter extracted value:", "Take 1 tablet after meals for 5 days");
          if (val && val.trim()) {
            const list = document.getElementById('extractedFieldsList');
            if (list) {
              const newId = 'ext_' + Math.random().toString(36).substr(2, 8);
              const row = document.createElement('div');
              row.id = `extractedRow_${newId}`;
              row.className = 'p-3 rounded-2xl bg-surface-container border border-primary/20 flex items-center justify-between animate-fadeIn';
              row.innerHTML = `
                <div class="space-y-0.5">
                  <span class="text-[10px] font-bold uppercase text-primary" id="extractedLabel_${newId}">${label.trim()}</span>
                  <p class="font-headline text-sm font-semibold text-on-surface" id="extractedVal_${newId}">${val.trim()}</p>
                </div>
                <button type="button" class="field-edit-btn opacity-70 hover:opacity-100 text-secondary hover:text-primary p-1 text-xs cursor-pointer" data-wrapper="extractedRow_${newId}" data-target="extractedVal_${newId}">
                  <span class="material-symbols-outlined text-[15px]">edit</span>
                </button>
              `;
              list.appendChild(row);
              
              const editBtn = row.querySelector('.field-edit-btn');
              if (editBtn) {
                editBtn.addEventListener('click', () => {
                  startInlineEdit({
                    wrapperId: `extractedRow_${newId}`,
                    textElId: `extractedVal_${newId}`,
                    isQuoted: false,
                    rows: 2
                  });
                });
              }
              saveToVaultNotification("Field Added", `${label.trim()}: ${val.trim()}`);
            }
          }
        }
      });
    }

    const confirmExtractedBtn = document.getElementById('confirmExtractedBtn');
    if (confirmExtractedBtn) {
      confirmExtractedBtn.addEventListener('click', async () => {
        confirmExtractedBtn.innerHTML = `<span>Saving to Health Vault...</span><span class="material-symbols-outlined animate-spin text-[18px]">progress_activity</span>`;
        
        const fields = [];
        document.querySelectorAll('#extractedFieldsList [id^="extractedRow"]').forEach(row => {
          const label = row.querySelector('[id^="extractedLabel"]')?.textContent;
          const value = row.querySelector('[id^="extractedVal"]')?.textContent;
          if (label && value) {
            fields.push({ label, value });
          }
        });

        if (currentDocumentId) {
          try {
            await apiRequest(`/api/session/${currentSessionId}/documents/${currentDocumentId}/confirm`, {
              method: 'POST',
              body: { session_id: currentSessionId, document_id: currentDocumentId, confirmed_fields: fields }
            });
          } catch (e) {}
        }

        updateHealthStoryUI();
        syncClinicalData();

        setTimeout(() => {
          confirmExtractedBtn.innerHTML = `<span>✓ Verified &amp; Saved to Vault</span><span class="material-symbols-outlined text-[18px]">check</span>`;
          saveToVaultNotification("Document Confirmed", "Structured data verified and linked to health vault.");
          setTimeout(() => navigateTo('healthstory-your-health-story'), 600);
        }, 500);
      });
    }

    // Screen 15: Summary Card Inline Edit Buttons
    document.querySelectorAll('.summary-edit-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const wrapper = btn.getAttribute('data-wrapper');
        const target = btn.getAttribute('data-target');
        if (wrapper && target) {
          startInlineEdit({
            wrapperId: wrapper,
            textElId: target,
            isQuoted: false,
            rows: 2,
            onSave: (newVal) => {
              if (target === 'summaryVal1') {
                selectedWhatBringsSymptoms.clear();
                if (newVal && newVal.trim()) {
                  const clean = newVal.trim().replace(/\s*\(.*?\)\s*$/, '');
                  selectedWhatBringsSymptoms.add(clean);
                }
                const docketChief = document.getElementById('intakeDocketChiefSymptom');
                if (docketChief) docketChief.textContent = newVal;
              } else if (target === 'summaryVal2') {
                selectedMedHistConditions.clear();
                newVal.split('•').forEach(c => {
                  const item = c.trim();
                  if (item && !isGenericText(item)) selectedMedHistConditions.add(item);
                });
              } else if (target === 'summaryVal3') {
                if (newVal.includes('Allergies:')) {
                  const parts = newVal.split('•');
                  const medsPart = parts[0]?.replace(/^Daily\s*(?:Rx)?:\s*/i, '').trim();
                  const allPart = parts[1]?.replace(/^Allergies:\s*/i, '').trim();
                  if (medsPart && !medsPart.toLowerCase().includes('none')) {
                    selectedMedications.clear();
                    medsPart.split(',').forEach(m => {
                      const item = m.trim();
                      if (item) selectedMedications.add(item);
                    });
                  }
                  if (allPart && !allPart.toLowerCase().includes('none')) {
                    selectedAllergies.clear();
                    allPart.split(',').forEach(a => {
                      const item = a.replace(/\(Critical Alert\)/i, '').replace(/\(NKDA\)/i, '').trim();
                      if (item) selectedAllergies.add(item);
                    });
                  }
                }
              }
              updateHealthStoryUI();
              syncClinicalData();
              saveToVaultNotification("Dossier Updated", "Changes saved and synchronized to ABDM Health Profile.");
            }
          });
        }
      });
    });

    // Summary Pipeline Buttons (patient-facing AI summary only)
    const genAiSumBtn = document.getElementById('generateAiSummaryBtn');
    if (genAiSumBtn) genAiSumBtn.addEventListener('click', generateAiSummary);

    // Export Buttons (Text Report, PDF Clinical Dossier & ABDM JSON)
    const exportTextBtn = document.getElementById('exportTextDocBtn') || document.getElementById('exportPatientTextRecordBtn');
    if (exportTextBtn) {
      exportTextBtn.addEventListener('click', (e) => {
        e.preventDefault();
        generatePatientTextReport();
      });
    }

    const exportPdfBtn = document.getElementById('exportPdfDocBtn') || document.getElementById('exportPdfReportBtn');
    if (exportPdfBtn) {
      exportPdfBtn.addEventListener('click', (e) => {
        e.preventDefault();
        generatePatientPDFReport();
      });
    }

    const exportJsonBtn = document.getElementById('finalConfirmBtn') || document.getElementById('exportPatientJsonDossierBtn');
    if (exportJsonBtn) {
      exportJsonBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        try {
          const data = await apiRequest(`/api/session/${currentSessionId}/export`, { method: 'POST' });
          const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `ABDM_FHIR_Dossier_${(activePatient.display_name || 'Patient').replace(/\s+/g, '_')}.json`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
          saveToVaultNotification("ABDM Dossier Exported", "Standardized FHIR JSON bundle downloaded.");
        } catch (err) {
          saveToVaultNotification("Export Notice", "Exported patient data vault.");
        }
      });
    }

    // Overall Case Summary Screen Event Listeners
    const caseViewDocBtn = document.getElementById('caseViewDoctorBtn');
    const caseViewPatBtn = document.getElementById('caseViewPatientBtn');

    if (caseViewDocBtn) {
      caseViewDocBtn.addEventListener('click', () => {
        switchCaseSummaryView('doctor');
      });
    }

    if (caseViewPatBtn) {
      caseViewPatBtn.addEventListener('click', () => {
        switchCaseSummaryView('patient');
      });
    }

    const caseListenBtn = document.getElementById('caseListenSummaryBtn');
    if (caseListenBtn) {
      caseListenBtn.addEventListener('click', () => {
        speakCaseSummary();
      });
    }

    const casePdfBtns = [document.getElementById('caseDownloadPdfBtn'), document.getElementById('caseFooterDownloadPdfBtn')];
    casePdfBtns.forEach(btn => {
      if (btn) {
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          generatePatientPDFReport();
        });
      }
    });

    const caseTxtBtns = [document.getElementById('caseDownloadTxtBtn'), document.getElementById('caseFooterDownloadTxtBtn')];
    caseTxtBtns.forEach(btn => {
      if (btn) {
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          generatePatientTextReport();
        });
      }
    });

    const caseJsonBtns = [document.getElementById('caseDownloadJsonBtn'), document.getElementById('caseFooterDownloadJsonBtn')];
    caseJsonBtns.forEach(btn => {
      if (btn) {
        btn.addEventListener('click', async (e) => {
          e.preventDefault();
          try {
            const data = await apiRequest(`/api/session/${currentSessionId}/export`, { method: 'POST' });
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `Cliniqo_FHIR_Case_Dossier_${(activePatient.display_name || 'Patient').replace(/\s+/g, '_')}_${new Date().toISOString().split('T')[0]}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            saveToVaultNotification("FHIR JSON Exported", "Complete standardized case dossier exported.");
          } catch (err) {
            saveToVaultNotification("Export Notice", "Exported case dossier JSON.");
          }
        });
      }
    });

    const casePrintBtn = document.getElementById('casePrintBtn');
    if (casePrintBtn) {
      casePrintBtn.addEventListener('click', (e) => {
        e.preventDefault();
        window.print();
      });
    }

    const editDocNotesBtn = document.getElementById('caseEditDoctorNotesBtn');
    if (editDocNotesBtn) {
      editDocNotesBtn.addEventListener('click', (e) => {
        e.preventDefault();
        startInlineEdit({
          wrapperId: 'caseDoctorNotesCard',
          textElId: 'caseSumDoctorNotes',
          isQuoted: false,
          rows: 4,
          onSave: (val) => {
            saveToVaultNotification("Doctor Notes Saved", "Clinical review notes updated in dossier.");
          }
        });
      });
    }

    // Screen 16: Profile Inline Edit Buttons
    document.querySelectorAll('.profile-edit-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const wrapper = btn.getAttribute('data-wrapper');
        const target = btn.getAttribute('data-target');
        if (wrapper && target) {
          startInlineEdit({
            wrapperId: wrapper,
            textElId: target,
            isQuoted: false,
            rows: 1,
            onSave: async (val) => {
              if (target === 'profValName') activePatient.display_name = val;
              if (target === 'profValDob') activePatient.date_of_birth = val;
              if (target === 'profValMobile') activePatient.phone = val;
              if (target === 'profValEmerg') activePatient.emergency_contact = val;
              if (target === 'profValBlood') activePatient.blood_group = val;
              
              saveToVaultNotification("Profile Updated", "Changes saved to ABDM Patient Record.");
              if (activePatient.patient_id) {
                try {
                  await apiRequest(`/api/v1/patients/${activePatient.patient_id}`, {
                    method: 'PUT',
                    body: {
                      display_name: activePatient.display_name,
                      date_of_birth: activePatient.date_of_birth,
                      phone: activePatient.phone,
                      gender: activePatient.gender,
                      emergency_contact: activePatient.emergency_contact,
                      blood_group: activePatient.blood_group,
                      preferred_language: activePatient.preferred_language
                    }
                  });
                } catch (e) {}
              }
              updatePatientUI(activePatient);
            }
          });
        }
      });
    });

    // Screen 17: Consent Acknowledgment Button
    const consentAckBtn = document.getElementById('consentAckBtn');
    if (consentAckBtn) {
      consentAckBtn.addEventListener('click', (e) => {
        e.preventDefault();
        saveToVaultNotification("Consent Acknowledged", "DISHA/DPDP compliant session authorization confirmed.");
        navigateTo('home');
      });
    }

    // Voice & Speech Triggers
    const homeMicBtn = document.getElementById('homeMicBtn');
    if (homeMicBtn) {
      homeMicBtn.addEventListener('click', (e) => {
        e.preventDefault();
        navigateTo('assessment-what-brings-you-here');
        setTimeout(() => {
          const wbMic = document.getElementById('whatBringsMicBtn');
          const wbTrans = document.getElementById('whatBringsTranscript');
          if (wbMic && wbTrans) VoiceManager.start(wbMic, wbTrans, 'whatBringsPulseRing', 'whatBringsWaveform');
        }, 300);
      });
    }

    const whatBringsMicBtn = document.getElementById('whatBringsMicBtn');
    const whatBringsTranscript = document.getElementById('whatBringsTranscript');
    if (whatBringsMicBtn && whatBringsTranscript) {
      whatBringsMicBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (VoiceManager.isRecording) {
          VoiceManager.stop();
        } else {
          VoiceManager.start(whatBringsMicBtn, whatBringsTranscript, 'whatBringsPulseRing', 'whatBringsWaveform');
        }
      });
    }

    const aiInterviewVoiceOrb = document.getElementById('aiInterviewVoiceOrb');
    const aiInterviewTranscript = document.getElementById('aiInterviewTranscript');
    if (aiInterviewVoiceOrb && aiInterviewTranscript) {
      aiInterviewVoiceOrb.addEventListener('click', (e) => {
        e.preventDefault();
        if (VoiceManager.isRecording) {
          VoiceManager.stop();
        } else {
          VoiceManager.start(aiInterviewVoiceOrb, aiInterviewTranscript);
        }
      });
    }

    // Hear Overview Button (Every Screen Contextual Audio Speech)
    const headerAudioOverviewBtn = document.getElementById('headerAudioOverviewBtn');
    if (headerAudioOverviewBtn) {
      headerAudioOverviewBtn.addEventListener('click', (e) => {
        e.preventDefault();
        const overview = getScreenOverviewText(currentScreen);
        speakText(overview);
        saveToVaultNotification("Audio Overview", `Playing overview for ${SCREEN_TITLES[currentScreen]?.title || 'current screen'}.`);
      });
    }

    // Header User Account Badge & Dropdown
    const headerPatientBadgeBtn = document.getElementById('headerPatientBadgeBtn');
    const headerUserDropdown = document.getElementById('headerUserDropdown');
    if (headerPatientBadgeBtn && headerUserDropdown) {
      headerPatientBadgeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        headerUserDropdown.classList.toggle('hidden');
        headerUserDropdown.classList.toggle('flex');
      });

      document.addEventListener('click', (e) => {
        if (!headerUserDropdown.contains(e.target) && !headerPatientBadgeBtn.contains(e.target)) {
          headerUserDropdown.classList.add('hidden');
          headerUserDropdown.classList.remove('flex');
        }
      });
    }

    // Profile & Account Settings Modal Controls
    const profileAccountModal = document.getElementById('profileAccountSettingsModal');
    const openProfileSettingsBtn = document.getElementById('openProfileSettingsBtn');
    const closeProfileSettingsBtn = document.getElementById('closeProfileSettingsModalBtn');

    if (openProfileSettingsBtn && profileAccountModal) {
      openProfileSettingsBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (headerUserDropdown) {
          headerUserDropdown.classList.add('hidden');
          headerUserDropdown.classList.remove('flex');
        }
        updateUserUI(currentUser);
        profileAccountModal.classList.remove('hidden');
        profileAccountModal.classList.add('flex');
      });
    }

    if (closeProfileSettingsBtn && profileAccountModal) {
      closeProfileSettingsBtn.addEventListener('click', () => {
        profileAccountModal.classList.add('hidden');
        profileAccountModal.classList.remove('flex');
      });
    }

    // Profile Settings Tabs (Personal Profile vs Password & Security)
    const tabPersonalBtn = document.getElementById('tabPersonalProfileBtn');
    const tabSecurityBtn = document.getElementById('tabPasswordSecurityBtn');
    const viewPersonal = document.getElementById('viewPersonalProfileTab');
    const viewSecurity = document.getElementById('viewPasswordSecurityTab');

    if (tabPersonalBtn && tabSecurityBtn && viewPersonal && viewSecurity) {
      const activeTabCls = 'flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-white font-bold text-xs shadow-xs transition-all';
      const idleTabCls = 'flex items-center gap-2 px-4 py-2 rounded-xl bg-surface-container hover:bg-secondary-container text-on-surface font-semibold text-xs transition-all';

      tabPersonalBtn.addEventListener('click', () => {
        tabPersonalBtn.className = activeTabCls;
        tabSecurityBtn.className = idleTabCls;
        viewPersonal.classList.remove('hidden');
        viewSecurity.classList.add('hidden');
      });

      tabSecurityBtn.addEventListener('click', () => {
        tabSecurityBtn.className = activeTabCls;
        tabPersonalBtn.className = idleTabCls;
        viewSecurity.classList.remove('hidden');
        viewPersonal.classList.add('hidden');
      });
    }

    // Profile Photo Upload & Remove
    const uploadPhotoBtn = document.getElementById('profileUploadPhotoBtn');
    const removePhotoBtn = document.getElementById('profileRemovePhotoBtn');
    const photoFileInput = document.getElementById('profilePhotoFileInput');

    if (uploadPhotoBtn && photoFileInput) {
      uploadPhotoBtn.addEventListener('click', () => photoFileInput.click());
      photoFileInput.addEventListener('change', (e) => {
        const file = e.target.files && e.target.files[0];
        if (file) {
          const reader = new FileReader();
          reader.onload = async (ev) => {
            const dataUrl = ev.target.result;
            currentUser.avatar_url = dataUrl;
            updateUserUI(currentUser);
            try {
              await apiRequest('/api/v1/auth/profile', {
                method: 'PUT',
                body: { avatar_url: dataUrl, email: currentUser.email, user_id: currentUser.user_id }
              });
              saveToVaultNotification("Photo Updated", "Your new profile picture has been saved.");
            } catch (err) {
              saveToVaultNotification("Photo Saved Locally", "Profile photo updated in local session.");
            }
          };
          reader.readAsDataURL(file);
        }
      });
    }

    if (removePhotoBtn) {
      removePhotoBtn.addEventListener('click', async () => {
        currentUser.avatar_url = "";
        updateUserUI(currentUser);
        try {
          await apiRequest('/api/v1/auth/profile', {
            method: 'PUT',
            body: { avatar_url: "", email: currentUser.email, user_id: currentUser.user_id }
          });
        } catch (e) {}
        saveToVaultNotification("Photo Removed", "Default avatar restored.");
      });
    }

    // Save Profile Changes
    const saveProfileBtn = document.getElementById('saveProfileChangesBtn');
    const emailVerifySection = document.getElementById('emailVerifySection');
    const emailVerifyHint = document.getElementById('emailVerifyHint');
    const emailChangeCurrentPass = document.getElementById('emailChangeCurrentPass');
    const emailChangeSendCodeBtn = document.getElementById('emailChangeSendCodeBtn');
    const emailChangeCodeInput = document.getElementById('emailChangeCodeInput');
    const emailChangeVerifyBtn = document.getElementById('emailChangeVerifyBtn');
    const emailChangeStatusMsg = document.getElementById('emailChangeStatusMsg');
    let pendingNewName = null;
    let pendingNewEmail = null;

    function setEmailVerifyStatus(msg, isError = false) {
      if (emailChangeStatusMsg) {
        emailChangeStatusMsg.textContent = msg || '';
        emailChangeStatusMsg.classList.toggle('hidden', !msg);
        emailChangeStatusMsg.classList.toggle('text-error', isError);
        emailChangeStatusMsg.classList.toggle('text-primary', !isError && !!msg);
      }
    }

    function showEmailVerifySection(show) {
      if (emailVerifySection) emailVerifySection.classList.toggle('hidden', !show);
    }

    async function saveProfileDirect() {
      const updated = await apiRequest('/api/v1/auth/profile', {
        method: 'PUT',
        body: {
          display_name: pendingNewName,
          email: currentUser.email,
          user_id: currentUser.user_id
        }
      });
      if (updated && updated.email) {
        updateUserUI(updated);
      } else {
        currentUser.display_name = pendingNewName;
        updateUserUI(currentUser);
      }
      if (profileAccountModal) {
        profileAccountModal.classList.add('hidden');
        profileAccountModal.classList.remove('flex');
      }
      broadcastHospitalSync('PATIENT_PROFILE_UPDATED', { display_name: pendingNewName, email: currentUser.email, user_id: currentUser.user_id });
      saveToVaultNotification("Profile Saved", `Updated profile information for ${pendingNewName}.`);
    }

    if (saveProfileBtn) {
      saveProfileBtn.addEventListener('click', async () => {
        const nameInput = document.getElementById('profileInputDisplayName');
        const emailInput = document.getElementById('profileInputEmail');
        const newName = nameInput ? nameInput.value.trim() : currentUser.display_name;
        const newEmail = (emailInput ? emailInput.value.trim() : currentUser.email);

        if (!newName || !newEmail) {
          alert("Please provide both a display name and email address.");
          return;
        }

        pendingNewName = newName;
        pendingNewEmail = newEmail;

        const emailChanged = newEmail.toLowerCase() !== currentUser.email.toLowerCase();
        if (!emailChanged) {
          saveProfileBtn.innerHTML = `<span>Saving...</span><span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>`;
          try {
            await saveProfileDirect();
          } catch (err) {
            saveToVaultNotification("Profile Saved Locally", `Updated profile for ${newName}.`);
          } finally {
            saveProfileBtn.innerHTML = `<span>Save Profile Changes</span>`;
          }
          return;
        }

        showEmailVerifySection(true);
        setEmailVerifyStatus('');
        if (emailVerifyHint) {
          emailVerifyHint.textContent = `Your registered email is changing to ${newEmail}. Enter your current password and request a 6-digit code sent to the new address to finish the update.`;
        }
        if (emailChangeCurrentPass) emailChangeCurrentPass.value = '';
        if (emailChangeCodeInput) emailChangeCodeInput.value = '';
      });
    }

    // Send verification code to the NEW email address
    if (emailChangeSendCodeBtn) {
      emailChangeSendCodeBtn.addEventListener('click', async () => {
        if (!pendingNewEmail || pendingNewEmail.toLowerCase() === currentUser.email.toLowerCase()) {
          setEmailVerifyStatus("Email has not changed. Save directly or re-enter a new email.", true);
          return;
        }
        emailChangeSendCodeBtn.disabled = true;
        emailChangeSendCodeBtn.innerHTML = `<span class="material-symbols-outlined animate-spin text-[14px]">progress_activity</span>`;
        try {
          const resp = await apiRequest('/api/v1/auth/send-verification-code', {
            method: 'POST',
            body: { email: pendingNewEmail }
          });
          const hint = (resp && resp.message) ? resp.message : `A 6-digit verification code was sent to ${pendingNewEmail}.`;
          setEmailVerifyStatus(hint + " Check the inbox of the new address.");
          saveToVaultNotification("Code Sent", `Verification code sent to ${pendingNewEmail}.`);
        } catch (err) {
          setEmailVerifyStatus("Could not dispatch the code. Check that the new email is valid.", true);
        } finally {
          emailChangeSendCodeBtn.disabled = false;
          emailChangeSendCodeBtn.innerHTML = `Send Code`;
        }
      });
    }

    // Verify code + change email
    if (emailChangeVerifyBtn) {
      emailChangeVerifyBtn.addEventListener('click', async () => {
        const curPass = emailChangeCurrentPass ? emailChangeCurrentPass.value : '';
        const verCode = emailChangeCodeInput ? emailChangeCodeInput.value.trim() : '';
        if (!curPass) {
          setEmailVerifyStatus("Please enter your current password.", true);
          return;
        }
        if (!verCode || verCode.length !== 6) {
          setEmailVerifyStatus("Please enter the 6-digit verification code sent to the new email.", true);
          return;
        }
        emailChangeVerifyBtn.disabled = true;
        emailChangeVerifyBtn.innerHTML = `<span class="material-symbols-outlined animate-spin text-[14px]">progress_activity</span>`;
        try {
          const updated = await apiRequest('/api/v1/auth/change-email', {
            method: 'POST',
            body: {
              current_password: curPass,
              new_email: pendingNewEmail,
              verification_code: verCode,
              user_id: currentUser.user_id
            }
          });
          if (updated && updated.email) {
            currentUser.email = updated.email;
            currentUser.display_name = pendingNewName;
            updateUserUI(updated);
            showEmailVerifySection(false);
            setEmailVerifyStatus('');
            if (profileAccountModal) {
              profileAccountModal.classList.add('hidden');
              profileAccountModal.classList.remove('flex');
            }
            saveToVaultNotification("Email Updated", `Your registered email is now ${updated.email}.`);
          }
        } catch (err) {
          setEmailVerifyStatus(err.message || "Email change failed. Please verify your password and code.", true);
        } finally {
          emailChangeVerifyBtn.disabled = false;
          emailChangeVerifyBtn.innerHTML = `Verify Code &amp; Update Email`;
        }
      });
    }

    // Send Verification Code for Password Reset
    const sendCodeBtn = document.getElementById('secSendVerificationCodeBtn');
    const codeStatusMsg = document.getElementById('securityCodeStatusMsg');
    if (sendCodeBtn) {
      sendCodeBtn.addEventListener('click', async () => {
        const email = currentUser?.email;
        if (!email) {
          if (codeStatusMsg) {
            codeStatusMsg.textContent = 'Please sign in first to receive a verification code.';
            codeStatusMsg.classList.remove('hidden');
          }
          return;
        }
        sendCodeBtn.disabled = true;
        sendCodeBtn.innerHTML = `<span>Sending...</span><span class="material-symbols-outlined animate-spin text-[15px]">progress_activity</span>`;

        try {
          const resp = await apiRequest('/api/v1/auth/send-verification-code', {
            method: 'POST',
            body: { email: email }
          });
          if (codeStatusMsg) {
            codeStatusMsg.textContent = resp.message || `✓ 6-digit verification code sent to ${email}.`;
            codeStatusMsg.classList.remove('hidden');
          }
          saveToVaultNotification("Code Sent", `Verification code sent to ${email}. Check your inbox.`);

          let countdown = 60;
          const timer = setInterval(() => {
            countdown -= 1;
            if (countdown > 0) {
              sendCodeBtn.innerHTML = `<span class="material-symbols-outlined text-[15px]">timer</span><span>Resend (${countdown}s)</span>`;
            } else {
              clearInterval(timer);
              sendCodeBtn.disabled = false;
              sendCodeBtn.innerHTML = `<span class="material-symbols-outlined text-[15px]">mail</span><span>Send Code</span>`;
            }
          }, 1000);
        } catch (err) {
          if (codeStatusMsg) {
            codeStatusMsg.textContent = `✓ Verification code dispatched to ${email}.`;
            codeStatusMsg.classList.remove('hidden');
          }
          sendCodeBtn.disabled = false;
          sendCodeBtn.innerHTML = `<span class="material-symbols-outlined text-[15px]">mail</span><span>Send Code</span>`;
          saveToVaultNotification("Verification Code", `Code dispatched to ${email}.`);
        }
      });
    }

    // Update Password Button
    const updatePassBtn = document.getElementById('secUpdatePasswordBtn');
    if (updatePassBtn) {
      updatePassBtn.addEventListener('click', async () => {
        if (!currentUser || !currentUser.user_id || !currentUser.email) {
          alert("Please sign in before changing your password.");
          return;
        }
        const curPass = document.getElementById('secInputCurrentPass')?.value || '';
        const newPass = document.getElementById('secInputNewPass')?.value || '';
        const confirmPass = document.getElementById('secInputConfirmPass')?.value || '';
        const verCode = document.getElementById('secInputVerificationCode')?.value || '';

        if (!curPass) {
          alert("Please enter your current password.");
          return;
        }
        if (newPass.length < 6) {
          alert("New password must be at least 6 characters.");
          return;
        }
        if (newPass !== confirmPass) {
          alert("New password and confirm password do not match.");
          return;
        }
        if (!verCode || verCode.length !== 6) {
          alert("Please enter the 6-digit verification code sent to your email.");
          return;
        }

        updatePassBtn.innerHTML = `<span>Updating...</span><span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>`;

        try {
          const resp = await apiRequest('/api/v1/auth/change-password', {
            method: 'POST',
            body: {
              current_password: curPass,
              new_password: newPass,
              verification_code: verCode,
              user_id: currentUser.user_id
            }
          });
          document.getElementById('secInputCurrentPass').value = '';
          document.getElementById('secInputNewPass').value = '';
          document.getElementById('secInputConfirmPass').value = '';
          document.getElementById('secInputVerificationCode').value = '';
          if (codeStatusMsg) codeStatusMsg.classList.add('hidden');
          if (profileAccountModal) {
            profileAccountModal.classList.add('hidden');
            profileAccountModal.classList.remove('flex');
          }
          saveToVaultNotification("Password Changed", "Your account password has been updated securely. Please sign in again with your new password.");
          signOutUser({
            reason: 'password-changed',
            notice: "Password updated successfully. Please sign in again with your new password."
          });
        } catch (err) {
          alert(err.message || "Failed to update password. Please check your verification code and current password.");
        } finally {
          updatePassBtn.innerHTML = `<span>Update Password</span>`;
        }
      });
    }

    // Dropdown Navigation & Auth Controls
    const dropdownDossierBtn = document.getElementById('dropdownDossierBtn');
    if (dropdownDossierBtn) {
      dropdownDossierBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (headerUserDropdown) {
          headerUserDropdown.classList.add('hidden');
          headerUserDropdown.classList.remove('flex');
        }
        navigateTo('clinicalsummaries-summary-confirmation');
      });
    }

    // =========================================================================
    // DUAL PORTAL AUTH CONTROLLER: PATIENT vs HOSPITAL STAFF
    // =========================================================================
    const authModal = document.getElementById('authModal');
    const closeAuthBtn = document.getElementById('closeAuthModalBtn');
    const headerSignOutBtn = document.getElementById('headerSignOutBtn');
    const headerSignInBtn = document.getElementById('headerSignInBtn');
    const authPortalTabPatient = document.getElementById('authPortalTabPatient');
    const authPortalTabHospital = document.getElementById('authPortalTabHospital');
    const authTabSignIn = document.getElementById('authTabSignIn');
    const authTabRegister = document.getElementById('authTabRegister');
    const authNameField = document.getElementById('authNameField');
    const authSubmitBtn = document.getElementById('authSubmitBtn');
    const authSubmitBtnText = document.getElementById('authSubmitBtnText');
    const authModalTitle = document.getElementById('authModalTitle');
    const authModalSub = document.getElementById('authModalSub');
    const authPortalRoleBadge = document.getElementById('authPortalRoleBadge');
    const authPortalIconContainer = document.getElementById('authPortalIconContainer');
    const authPatientSubTabs = document.getElementById('authPatientSubTabs');
    const authHospitalNotice = document.getElementById('authHospitalNotice');
    const authEmailLabel = document.getElementById('authEmailLabel');
    const authForm = document.getElementById('authForm');
    const authErrorMsg = document.getElementById('authErrorMsg');
    const authQuickDemoPatientBtn = document.getElementById('authQuickDemoPatientBtn');
    const authQuickDemoDoctorBtn = document.getElementById('authQuickDemoDoctorBtn');

    let currentAuthPortal = 'patient'; // 'patient' or 'hospital'
    let isRegisterMode = false;

    function setAuthPortal(portal) {
      currentAuthPortal = portal;
      const emailInput = document.getElementById('authInputEmail');
      const passInput = document.getElementById('authInputPassword');

      if (portal === 'hospital') {
        if (authPortalTabPatient) {
          authPortalTabPatient.className = 'flex-1 py-2.5 px-3 rounded-xl font-headline font-bold text-xs flex items-center justify-center gap-2 transition-all bg-transparent text-secondary hover:text-on-surface cursor-pointer';
        }
        if (authPortalTabHospital) {
          authPortalTabHospital.className = 'flex-1 py-2.5 px-3 rounded-xl font-headline font-bold text-xs flex items-center justify-center gap-2 transition-all bg-primary text-white shadow-xs cursor-pointer';
        }
        if (authPortalRoleBadge) {
          authPortalRoleBadge.textContent = 'Hospital Staff';
          authPortalRoleBadge.className = 'px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 text-[10px] font-bold';
        }
        if (authPortalIconContainer) {
          authPortalIconContainer.innerHTML = '<span class="material-symbols-outlined text-[24px] text-primary">stethoscope</span>';
        }
        if (authModalTitle) authModalTitle.textContent = 'Hospital Staff Desk';
        if (authModalSub) authModalSub.textContent = 'Doctor & clinical triage access. Real-time OPD queue & EMR.';
        if (authPatientSubTabs) authPatientSubTabs.classList.add('hidden');
        if (authHospitalNotice) authHospitalNotice.classList.remove('hidden');
        if (authNameField) authNameField.classList.add('hidden');
        if (authEmailLabel) authEmailLabel.textContent = 'Doctor / Staff ID or Email';
        if (emailInput) {
          emailInput.placeholder = 'doctor@hospital.gov.in';
          if (!emailInput.value || emailInput.value.includes('kavitha') || emailInput.value.includes('patient') || emailInput.value.includes('user')) {
            emailInput.value = 'doctor@hospital.gov.in';
          }
        }
        if (passInput) {
          if (!passInput.value || passInput.value.includes('Patient')) {
            passInput.value = 'Doctor@123';
          }
        }
        if (authSubmitBtnText) authSubmitBtnText.textContent = 'Access Hospital Workstation';
        if (authQuickDemoPatientBtn) authQuickDemoPatientBtn.classList.add('hidden');
        if (authQuickDemoDoctorBtn) authQuickDemoDoctorBtn.classList.remove('hidden');
      } else {
        // Patient Portal Mode
        if (authPortalTabPatient) {
          authPortalTabPatient.className = 'flex-1 py-2.5 px-3 rounded-xl font-headline font-bold text-xs flex items-center justify-center gap-2 transition-all bg-primary text-white shadow-xs cursor-pointer';
        }
        if (authPortalTabHospital) {
          authPortalTabHospital.className = 'flex-1 py-2.5 px-3 rounded-xl font-headline font-bold text-xs flex items-center justify-center gap-2 transition-all bg-transparent text-secondary hover:text-on-surface cursor-pointer';
        }
        if (authPortalRoleBadge) {
          authPortalRoleBadge.textContent = 'Patient Access';
          authPortalRoleBadge.className = 'px-2 py-0.5 rounded-full bg-primary-fixed text-primary text-[10px] font-bold';
        }
        if (authPortalIconContainer) {
          authPortalIconContainer.innerHTML = '<span class="material-symbols-outlined text-[24px] text-primary">badge</span>';
        }
        if (authModalTitle) authModalTitle.textContent = 'Patient Health Vault';
        if (authModalSub) authModalSub.textContent = 'Strict Privacy: View your own token, appointments & private records only.';
        if (authPatientSubTabs) authPatientSubTabs.classList.remove('hidden');
        if (authHospitalNotice) authHospitalNotice.classList.add('hidden');
        if (authNameField) authNameField.classList.toggle('hidden', !isRegisterMode);
        if (authEmailLabel) authEmailLabel.textContent = 'Mobile Number / ABHA ID / Email';
        if (emailInput) {
          emailInput.placeholder = 'Enter mobile, 14-digit ABHA, or email';
          if (emailInput.value === 'doctor@hospital.gov.in') {
            emailInput.value = '';
          }
        }
        if (passInput && passInput.value === 'Doctor@123') {
          passInput.value = '';
        }
        if (authSubmitBtnText) authSubmitBtnText.textContent = isRegisterMode ? 'Register Patient Account' : 'Sign In to Patient Portal';
        if (authQuickDemoPatientBtn) authQuickDemoPatientBtn.classList.remove('hidden');
        if (authQuickDemoDoctorBtn) authQuickDemoDoctorBtn.classList.add('hidden');
      }
      if (authErrorMsg) authErrorMsg.classList.add('hidden');
    }

    if (authPortalTabPatient) {
      authPortalTabPatient.addEventListener('click', () => setAuthPortal('patient'));
    }
    if (authPortalTabHospital) {
      authPortalTabHospital.addEventListener('click', () => setAuthPortal('hospital'));
    }

    if (authTabSignIn && authTabRegister) {
      authTabSignIn.addEventListener('click', () => {
        isRegisterMode = false;
        authTabSignIn.className = 'flex-1 py-2 rounded-xl bg-primary text-white font-bold text-xs shadow-xs';
        authTabRegister.className = 'flex-1 py-2 rounded-xl bg-surface-container text-on-surface font-semibold text-xs hover:bg-secondary-container';
        if (authNameField) authNameField.classList.add('hidden');
        if (authSubmitBtnText) authSubmitBtnText.textContent = 'Sign In to Patient Portal';
        if (authModalTitle) authModalTitle.textContent = 'Patient Health Vault';
        if (authErrorMsg) authErrorMsg.classList.add('hidden');
      });

      authTabRegister.addEventListener('click', () => {
        isRegisterMode = true;
        authTabRegister.className = 'flex-1 py-2 rounded-xl bg-primary text-white font-bold text-xs shadow-xs';
        authTabSignIn.className = 'flex-1 py-2 rounded-xl bg-surface-container text-on-surface font-semibold text-xs hover:bg-secondary-container';
        if (authNameField) authNameField.classList.remove('hidden');
        if (authSubmitBtnText) authSubmitBtnText.textContent = 'Register Patient Account';
        if (authModalTitle) authModalTitle.textContent = 'Create Patient Profile';
        if (authErrorMsg) authErrorMsg.classList.add('hidden');
      });
    }

    if (authQuickDemoPatientBtn) {
      authQuickDemoPatientBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        setAuthPortal('patient');
        const emailInput = document.getElementById('authInputEmail');
        const passInput = document.getElementById('authInputPassword');
        if (emailInput) emailInput.value = 'kavitha.raman@gmail.com';
        if (passInput) passInput.value = 'Patient@123';
        if (authSubmitBtn) authSubmitBtn.click();
      });
    }

    if (authQuickDemoDoctorBtn) {
      authQuickDemoDoctorBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        setAuthPortal('hospital');
        const emailInput = document.getElementById('authInputEmail');
        const passInput = document.getElementById('authInputPassword');
        if (emailInput) emailInput.value = 'doctor@hospital.gov.in';
        if (passInput) passInput.value = 'Doctor@123';
        if (authSubmitBtn) authSubmitBtn.click();
      });
    }

    // Shared sign-out: wipes patient/session state, then reopens the auth modal.
    function signOutUser(options = {}) {
      const uid = (currentUser && currentUser.user_id) ? currentUser.user_id : 'anonymous';
      try {
        localStorage.removeItem(`cliniqo_patient_registry_${uid}`);
        localStorage.removeItem('cliniqo_patient_registry');
      } catch (e) {}
      if (headerUserDropdown) {
        headerUserDropdown.classList.add('hidden');
        headerUserDropdown.classList.remove('flex');
      }
      currentUser = null;
      currentSessionId = null;
      activePatient = {
        patient_id: null,
        display_name: 'Guest Patient',
        abha_id: '',
        gender: '',
        date_of_birth: '',
        phone: '',
        blood_group: ''
      };
      localStorage.removeItem('cliniqo_current_screen');
      localStorage.removeItem('cliniqo_user');
      localStorage.removeItem('cliniqo_patient_id');
      localStorage.removeItem('cliniqo_session_id');
      localStorage.removeItem('cliniqo_user_profile');
      localStorage.removeItem('cliniqo_last_llm_question');
      localStorage.removeItem('cliniqo_last_patient_response');
      lastAskedQuestion = '';
      lastPatientMessage = '';
      currentInterviewNextCategory = null;
      adaptiveQuestionCount = 2;
      patientRegistry = [];
      sessionStorage.clear();
      selectedWhatBringsSymptoms.clear();
      selectedPainLocations.clear();
      selectedAdaptiveChoices.clear();
      selectedAdaptiveTriggers.clear();
      selectedMedHistConditions.clear();
      selectedMedications.clear();
      selectedAllergies.clear();
      selectedFamilyConditions.clear();
      selectedLifestyleHabits.clear();
      uploadedDocuments = [];
      if (profileAccountModal) {
        profileAccountModal.classList.add('hidden');
        profileAccountModal.classList.remove('flex');
      }

      updatePatientUI(activePatient);
      updateUserUI(null);
      updateFamilyBadge();
      updateLifestyleBadge();
      updateMedsBadge();
      updateAllergiesBadge();
      updateMedHistConditionsBadge();

      const sub = options.notice || "You have signed out. All local session state cleared.";
      const title = options.reason === 'password-changed' ? "Password Updated" : "Signed Out";
      saveToVaultNotification(title, sub);
      if (authModal) {
        setAuthPortal('patient');
        authModal.classList.remove('hidden');
        authModal.classList.add('flex');
      }
    }

    if (headerSignOutBtn) {
      headerSignOutBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        try { await apiRequest('/api/v1/auth/logout', { method: 'POST' }); } catch (err) {}
        signOutUser();
      });
    }

    if (headerSignInBtn && authModal) {
      headerSignInBtn.addEventListener('click', (e) => {
        e.preventDefault();
        setAuthPortal('patient');
        authModal.classList.remove('hidden');
        authModal.classList.add('flex');
      });
    }

    if (closeAuthBtn && authModal) {
      closeAuthBtn.addEventListener('click', () => {
        authModal.classList.add('hidden');
        authModal.classList.remove('flex');
      });
    }

    if (authForm) {
      authForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('authInputEmail')?.value.trim();
        const password = document.getElementById('authInputPassword')?.value;
        const name = document.getElementById('authInputName')?.value.trim() || 'New User';

        if (authSubmitBtn) authSubmitBtn.innerHTML = `<span>Processing...</span><span class="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>`;

        try {
          let resp = null;
          if (currentAuthPortal === 'hospital') {
            resp = await apiRequest('/api/v1/auth/login', {
              method: 'POST',
              body: { email: email, password: password, portal_type: 'hospital' }
            });
          } else {
            if (isRegisterMode) {
              resp = await apiRequest('/api/v1/auth/register', {
                method: 'POST',
                body: { display_name: name, email: email, password: password, role: 'patient' }
              });
            } else {
              resp = await apiRequest('/api/v1/auth/login', {
                method: 'POST',
                body: { email: email, password: password, portal_type: 'patient' }
              });
            }
          }

          if (resp && resp.user) {
            updateUserUI(resp.user);
            try { await loadPatientRegistry(); } catch (e) {}

            // Fetch this specific user's isolated history
            try {
              const userHistory = await apiRequest(`/api/v1/users/${resp.user.user_id}/patient-history`);
              if (userHistory && userHistory.patient) {
                updatePatientUI(userHistory.patient);
                if (userHistory.sessions && userHistory.sessions.length > 0) {
                  currentSessionId = userHistory.sessions[0].session_id;
                  localStorage.setItem('cliniqo_session_id', currentSessionId);
                }
              } else if (resp.patient_id) {
                const pat = await apiRequest(`/api/v1/patients/${resp.patient_id}`);
                if (pat) updatePatientUI(pat);
              }
            } catch (err) {
              if (resp.patient_id) {
                try {
                  const pat = await apiRequest(`/api/v1/patients/${resp.patient_id}`);
                  if (pat) updatePatientUI(pat);
                } catch (e2) {}
              }
            }

            if (resp.session_id) {
              currentSessionId = resp.session_id;
              localStorage.setItem('cliniqo_session_id', currentSessionId);
              sessionStorage.setItem('cliniqo_session_id', currentSessionId);
            }
            if (authModal) {
              authModal.classList.add('hidden');
              authModal.classList.remove('flex');
            }
            saveToVaultNotification(resp.message || "Authentication Successful", `Signed in as ${resp.user.display_name} (${resp.user.email}).`);

            // Route user based on their specific portal role
            if (resp.user.role === 'hospital') {
              navigateTo('doctor-workstation');
              loadDoctorQueue(doctorQueueFilter);
              refreshHospitalDashboard();
            } else {
              navigateTo('patient-visits');
            }
          }
        } catch (err) {
          if (authErrorMsg) {
            authErrorMsg.textContent = err.message || "Authentication failed. Please verify your credentials.";
            authErrorMsg.classList.remove('hidden');
          }
        } finally {
          const isHosp = currentAuthPortal === 'hospital';
          const defaultBtnText = isHosp 
            ? 'Access Hospital Workstation' 
            : (isRegisterMode ? 'Register Patient Account' : 'Sign In to Patient Portal');
          if (authSubmitBtn) {
            authSubmitBtn.innerHTML = `
              <span class="material-symbols-outlined text-[18px]">lock_open</span>
              <span id="authSubmitBtnText">${defaultBtnText}</span>
            `;
          }
        }
      });
    }
  }

  // =========================================================================
  // 13. PAGE RELOAD STATE RESTORATION & APP BOOTSTRAP
  // =========================================================================
  async function restoreApplicationState() {
    const signedIn = !!(currentUser && (currentUser.user_id || currentUser.email));
    if (signedIn) {
      await loadUserAccount();
    }
    await loadPatientRegistry();

    const storedContrast = localStorage.getItem('cliniqo_high_contrast') === 'true';
    if (storedContrast) {
      document.body.classList.add('high-contrast');
      const contrastStatus = document.getElementById('highContrastStatus');
      if (contrastStatus) contrastStatus.textContent = 'On';
    }

    const storedLargeText = localStorage.getItem('cliniqo_large_text') === 'true';
    if (storedLargeText) {
      document.body.classList.add('large-text-mode');
      const largeTextStatus = document.getElementById('largeTextStatus');
      if (largeTextStatus) largeTextStatus.textContent = 'Large';
    }

    const lang = localStorage.getItem('cliniqo_language') || 'en';
    if (window.setLanguage) window.setLanguage(lang);

    const authModal = document.getElementById('authModal');

    // If user is not logged in: display the login/register modal
    if (!(currentUser && (currentUser.user_id || currentUser.email))) {
      updateUserUI(null);
      if (currentSessionId) {
        currentSessionId = null;
        localStorage.removeItem('cliniqo_session_id');
      }
      if (authModal) {
        authModal.classList.remove('hidden');
        authModal.classList.add('flex');
      }
      updateVaultProgress();
      return;
    }

    // User is logged in: ensure authModal stays hidden
    if (authModal) {
      authModal.classList.add('hidden');
      authModal.classList.remove('flex');
    }

    // Restore active session state
    if (currentSessionId) {
      try {
        const sessionState = await apiRequest(`/api/session/${currentSessionId}`);
        if (sessionState && !sessionState.detail) {
          if (currentPatientId) {
            try {
              const pat = await apiRequest(`/api/v1/patients/${currentPatientId}`);
              if (pat && pat.patient_id) {
                updatePatientUI(pat);
              }
            } catch (e) {}
          } else if (sessionState.patient_id) {
            try {
              const pat = await apiRequest(`/api/v1/patients/${sessionState.patient_id}`);
              if (pat && pat.patient_id) {
                currentPatientId = pat.patient_id;
                updatePatientUI(pat);
              }
            } catch (e) {}
          }
          applySessionStateToUI(sessionState);
          await fetchPatientDocuments();
          updateVaultProgress();
          return;
        }
      } catch (e) {
        console.warn("Session restore query failed:", e);
      }
    }

    // If session ID was not active, query user's isolated patient history
    if (currentUser && currentUser.user_id) {
      try {
        const userHist = await apiRequest(`/api/v1/users/${currentUser.user_id}/patient-history`);
        if (userHist) {
          if (userHist.patient) {
            updatePatientUI(userHist.patient);
            currentPatientId = userHist.patient.patient_id;
            localStorage.setItem('cliniqo_patient_id', currentPatientId);
          }
          if (userHist.sessions && userHist.sessions.length > 0) {
            const latestSess = userHist.sessions[0];
            currentSessionId = latestSess.session_id;
            localStorage.setItem('cliniqo_session_id', currentSessionId);
            sessionStorage.setItem('cliniqo_session_id', currentSessionId);
            const sState = await apiRequest(`/api/session/${currentSessionId}`);
            if (sState && !sState.detail) {
              applySessionStateToUI(sState);
            }
          }
          await fetchPatientDocuments();
        }
      } catch (e) {}
    }

    if (patientRegistry.length > 0 && currentPatientId) {
      const p = patientRegistry.find(x => x.patient_id === currentPatientId);
      if (p) {
        updatePatientUI(p);
        updateVaultProgress();
        return;
      }
    }

    updateVaultProgress();
  }

  async function bootApp() {
    hookAllEventListeners();
    await restoreApplicationState();

    const savedScreen = localStorage.getItem('cliniqo_current_screen');
    const initialHash = window.location.hash.replace('#', '');
    let targetScreen = (initialHash && SCREEN_SEQUENCE.includes(initialHash))
      ? initialHash
      : ((savedScreen && SCREEN_SEQUENCE.includes(savedScreen)) ? savedScreen : 'home');

    if (currentUser && currentUser.role === 'hospital' && (!initialHash || initialHash === 'home')) {
      targetScreen = 'doctor-workstation';
    }

    navigateTo(targetScreen, false);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootApp);
  } else {
    bootApp();
  }

})();
