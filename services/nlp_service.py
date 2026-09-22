from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Literal

from services.contracts import NLPResult

logger = logging.getLogger(__name__)


class BasicNLPService:
    """Safe local rule-based extractor; external ASR/NLP can replace this implementation."""

    def process(
        self,
        text: str,
        *,
        source: Literal['voice', 'text'],
        language: str | None = None,
    ) -> NLPResult:
        clean_text = text.strip()
        entities = self._rule_based_extract(clean_text, language)
        return NLPResult(
            text=clean_text,
            source=source,
            language=language or "en",
            confidence=0.8,
            processing_status='completed',
            entities=entities,
        )

    def _rule_based_extract(self, text: str, language: str | None = None) -> dict[str, Any]:
        lower = text.lower()
        symptoms = []
        body_parts = []
        medications = []
        allergies = []
        diseases = []
        red_flags = []

        # Comprehensive symptom dictionary
        symptom_keywords = {
            "chest tightness": "chest tightness", "chest pain": "chest pain", "tightness in chest": "chest tightness",
            "stomach pain": "stomach pain", "abdominal pain": "stomach pain", "stomach ache": "stomach pain",
            "belly pain": "stomach pain", "cramps": "abdominal cramps", "acidity": "acidity / heartburn",
            "heartburn": "acidity / heartburn", "gas": "gas / bloating", "bloating": "gas / bloating",
            "headache": "headache", "migraine": "headache", "throbbing head": "headache",
            "shortness of breath": "shortness of breath", "breathlessness": "shortness of breath",
            "difficulty breathing": "shortness of breath", "heavy breathing": "shortness of breath",
            "wheezing": "wheezing", "asthma attack": "wheezing",
            "fever": "fever", "chills": "fever / chills", "shivering": "fever / chills", "high temp": "fever",
            "cough": "cough", "dry cough": "dry cough", "wet cough": "productive cough", "phlegm": "productive cough",
            "cold": "common cold", "runny nose": "rhinorrhea", "sneezing": "sneezing", "congestion": "nasal congestion",
            "sore throat": "sore throat", "throat pain": "sore throat", "difficulty swallowing": "dysphagia",
            "vomiting": "vomiting", "nausea": "nausea", "feeling sick": "nausea",
            "dizziness": "dizziness", "lightheaded": "dizziness", "giddiness": "dizziness", "spinning": "vertigo",
            "fatigue": "fatigue", "tiredness": "fatigue", "weakness": "weakness", "exhaustion": "fatigue",
            "body aches": "body aches", "muscle pain": "body aches", "joint pain": "joint pain", "back pain": "back pain",
            "rash": "skin rash", "itching": "pruritus", "swelling": "swelling / edema",
            "loose motion": "diarrhea", "diarrhea": "diarrhea", "constipation": "constipation",
            # Tamil common terms
            "vali": "pain", "nenju vali": "chest pain", "marbhu vali": "chest pain", "nenjerichal": "heartburn",
            "kaichal": "fever", "irumal": "cough", "varattu irumal": "dry cough", "thalaivali": "headache",
            "vayiru vali": "stomach pain", "vayitru vali": "stomach pain", "moochu thinaral": "shortness of breath",
            "asathi": "fatigue", "mayakkam": "dizziness", "vaandhi": "vomiting",
            # Hindi common terms
            "dard": "pain", "seene me dard": "chest pain", "chhati me dard": "chest pain", "jalan": "heartburn",
            "bukhar": "fever", "khansi": "cough", "sukhi khansi": "dry cough", "sardard": "headache",
            "sar dard": "headache", "pet dard": "stomach pain", "saans lene me takleef": "shortness of breath",
            "dam phoolna": "shortness of breath", "kamzori": "weakness", "chakkar": "dizziness", "ulti": "vomiting",
        }
        for kw, sym in symptom_keywords.items():
            if kw in lower and sym not in symptoms:
                symptoms.append(sym)

        # Body parts
        body_part_keywords = {
            "chest": "Chest", "sternum": "Center / Sternum", "left chest": "Left side of chest",
            "right chest": "Right side of chest", "stomach": "Stomach / Abdomen", "abdomen": "Abdomen",
            "belly": "Abdomen", "head": "Head", "forehead": "Forehead", "temple": "Temples",
            "throat": "Throat", "neck": "Neck", "back": "Back", "lower back": "Lower Back",
            "upper back": "Upper Back", "shoulder": "Shoulder", "arm": "Arm", "left arm": "Left Arm",
            "leg": "Leg", "knee": "Knee", "foot": "Foot", "joints": "Joints"
        }
        for kw, bp in body_part_keywords.items():
            if kw in lower and bp not in body_parts:
                body_parts.append(bp)

        # Duration detection
        duration = ""
        dur_match = re.search(r'(\d+)\s*(?:to|-)?\s*(\d+)?\s*(days?|naal|naala|din|weeks?|vaaram|hafta|months?|maasam|mahina|hours?|ghante|mani)', lower)
        if dur_match:
            if dur_match.group(2):
                duration = f"{dur_match.group(1)}-{dur_match.group(2)} {dur_match.group(3)}"
            else:
                duration = f"{dur_match.group(1)} {dur_match.group(3)}"
        elif "yesterday" in lower or "kal se" in lower or "netru" in lower:
            duration = "Since yesterday"
        elif "today" in lower or "aaj" in lower or "indru" in lower or "morning" in lower:
            duration = "Started today"
        elif "few days" in lower or "kuch din" in lower or "sila naala" in lower:
            duration = "Past few days"
        elif "week" in lower or "hafta" in lower or "vaaram" in lower:
            duration = "Past 1 week"

        # Severity detection
        severity = "moderate"
        if any(w in lower for w in ("severe", "high", "unbearable", "athigama", "romba", "bahut", "bahut zyada", "acute", "10/10", "9/10", "8/10", "intense", "crushing")):
            severity = "severe"
        elif any(w in lower for w in ("mild", "slight", "leesa", "kam", "thoda", "1/10", "2/10", "3/10", "light")):
            severity = "mild"

        # Exacerbating triggers
        triggers = []
        trigger_keywords = {
            "walking": "Worse when walking", "running": "Physical exertion", "exertion": "Physical exertion",
            "exercise": "Physical exertion", "stairs": "Climbing stairs", "climbing": "Climbing stairs",
            "lying down": "Lying down / Posture", "sleeping": "Lying down / Night", "bending": "Bending forward",
            "deep breath": "Deep breathing", "coughing": "Coughing or straining",
            "eating": "After meals / Eating", "food": "After food", "spicy": "Spicy food",
            "cold": "Cold exposure", "stress": "Stress or anxiety", "standing": "Prolonged standing",
            "working": "Work exertion", "lifting": "Lifting weights / heavy objects"
        }
        for tk, tval in trigger_keywords.items():
            if tk in lower and tval not in triggers:
                triggers.append(tval)

        # Alleviating factors
        alleviating_factors = []
        alleviating_keywords = {
            "rest": "Rest and sitting still", "resting": "Rest and sitting still",
            "antacid": "Antacid / Water", "water": "Hydration / Fluids", "warm water": "Warm fluids",
            "warm tea": "Warm fluids", "tea": "Warm fluids", "steam": "Steam inhalation",
            "sleep": "Sleep and rest", "sitting": "Sitting upright", "sitting up": "Sitting upright",
            "inhaler": "Using inhaler", "tablet": "OTC symptomatic medication",
            "paracetamol": "Paracetamol / Pain relief", "crocin": "Paracetamol / Crocin", "dolo": "Paracetamol / Dolo"
        }
        for ak, aval in alleviating_keywords.items():
            if ak in lower and aval not in alleviating_factors:
                alleviating_factors.append(aval)

        # Symptom quality / character
        quality = ""
        quality_keywords = {
            "sharp": "Sharp / Piercing", "dull": "Dull Ache", "throbbing": "Throbbing / Pulsating",
            "burning": "Burning sensation", "tight": "Tightness / Pressure", "tightness": "Tightness / Constriction",
            "crushing": "Crushing / Heavy pressure", "heavy": "Heaviness / Pressure",
            "aching": "Aching discomfort", "stabbing": "Stabbing pain", "cramping": "Cramping", "spasm": "Spasm / Cramps"
        }
        for qk, qval in quality_keywords.items():
            if qk in lower:
                quality = qval
                break

        # Medications detection
        med_keywords = [
            "metformin", "amlodipine", "atorvastatin", "omeprazole", "pantoprazole",
            "paracetamol", "aspirin", "insulin", "azithromycin", "amoxicillin",
            "ibuprofen", "cetirizine", "montelukast", "losartan", "telmisartan",
            "crocin", "dolo", "pan d", "glycomet", "lipitor", "augmentin"
        ]
        for mk in med_keywords:
            if mk in lower:
                # find dosage if present
                dose_match = re.search(rf'{mk}\s*(\d+\s*(?:mg|mcg|gm|iu)?)', lower)
                dose_str = dose_match.group(1) if dose_match else None
                medications.append({
                    "name_as_reported": mk.title(),
                    "dosage": dose_str or "Standard dose",
                    "frequency": "Daily"
                })

        # Allergies detection
        allergy_keywords = {
            "penicillin": "Penicillin", "sulfa": "Sulfa Drugs", "aspirin allergy": "Aspirin",
            "nsaid": "NSAIDs", "peanuts": "Peanuts / Tree Nuts", "latex": "Latex",
            "ciprofloxacin": "Ciprofloxacin", "dust": "Dust", "pollen": "Pollen"
        }
        for ak, aname in allergy_keywords.items():
            if ak in lower and aname not in allergies:
                allergies.append(aname)

        # Diseases / Past conditions
        disease_keywords = {
            "diabetes": "Type 2 Diabetes", "sugar": "Type 2 Diabetes", "sugar patient": "Type 2 Diabetes",
            "hypertension": "Hypertension (High BP)", "high bp": "Hypertension (High BP)", "bp": "Hypertension (High BP)",
            "asthma": "Asthma / Respiratory", "wheeze": "Asthma / Respiratory",
            "cholesterol": "High Cholesterol", "thyroid": "Thyroid Disorder",
            "gerd": "Acid Reflux / GERD", "gastric": "Acid Reflux / GERD",
            "appendix": "Appendix Surgery", "appendectomy": "Appendix Surgery",
            "heart problem": "Cardiovascular Disease", "heart attack": "Past Myocardial Infarction"
        }
        for dk, dname in disease_keywords.items():
            if dk in lower and dname not in diseases:
                diseases.append(dname)

        # Red flags check
        if any(w in lower for w in ("chest pain", "shortness of breath", "breathlessness", "unconscious", "blood", "marbhu vali", "seene me dard", "severe crushing", "radiating to left arm")):
            red_flags.append("Cardiorespiratory distress / Acute pain presentation")

        # Fallback for direct input: if no keyword matched and text is informative, treat input as symptom
        if not symptoms and len(text.strip()) > 2 and not text.strip().endswith('?'):
            cleaned = text.strip().replace('"', '').replace('“', '').replace('”', '')
            if len(cleaned) < 80:
                symptoms.append(cleaned.title())

        return {
            "success": True,
            "language": language or "en",
            "intent": "symptom_report" if symptoms else "general",
            "symptoms": symptoms,
            "negated_symptoms": [],
            "body_parts": body_parts,
            "duration": duration,
            "severity": severity,
            "quality": quality,
            "triggers": triggers,
            "alleviating_factors": alleviating_factors,
            "medications": medications,
            "dosage": "",
            "frequency": "",
            "diseases": diseases,
            "allergies": allergies,
            "red_flags": red_flags,
            "additional_information": [],
            "raw_text": text
        }


class PatientNLPService(BasicNLPService):
    """Use the repository's patient-nlp module with Gemini backend when configured."""

    def __init__(self) -> None:
        super().__init__()
        self._analyzer = None
        current_file = Path(__file__).resolve()
        candidate_paths = [
            current_file.parents[3] / "patient-nlp" / "patient-nlp",
            current_file.parents[2] / "patient-nlp" / "patient-nlp",
            current_file.parents[1] / "patient-nlp" / "patient-nlp",
            Path.cwd() / "patient-nlp" / "patient-nlp",
            Path.cwd().parent / "patient-nlp" / "patient-nlp",
        ]
        
        nlp_root = next((p for p in candidate_paths if p.exists() and (p / "extractor.py").exists()), None)
        if nlp_root:
            if str(nlp_root) not in sys.path:
                sys.path.insert(0, str(nlp_root))
            env_file = nlp_root / ".env"
            if env_file.exists():
                from dotenv import load_dotenv
                load_dotenv(env_file)
        try:
            from extractor import analyze_patient_input

            self._analyzer = analyze_patient_input
        except (ImportError, ModuleNotFoundError) as exc:
            logger.info("patient-nlp extractor import note: %s", exc)
            self._analyzer = None

    def process(
        self,
        text: str,
        *,
        source: Literal['voice', 'text'],
        language: str | None = None,
    ) -> NLPResult:
        clean_text = text.strip()
        if not clean_text:
            return super().process(text, source=source, language=language)

        # 1. Get instant reliable rule-based extraction baseline
        rule_result = super().process(clean_text, source=source, language=language)
        rule_entities = rule_result.entities if isinstance(rule_result.entities, dict) else {}

        if not self._analyzer or not (os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')):
            return rule_result

        # 2. Query Gemini analyzer with strict timeout for sub-second responsiveness
        import concurrent.futures
        gemini_result = None
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self._analyzer, clean_text)
                gemini_result = future.result(timeout=4.0)
        except Exception as exc:
            logger.info("Analyzer call notice (using rule baseline): %s", exc)
            gemini_result = None

        if not isinstance(gemini_result, dict) or not gemini_result.get('success'):
            return rule_result

        # 3. Synergize Gemini output with rule baseline
        merged_entities = dict(rule_entities)
        for k, v in gemini_result.items():
            if v and v != "unknown" and v != []:
                if isinstance(v, list) and isinstance(merged_entities.get(k), list):
                    # Combine without duplicates
                    combined = list(merged_entities[k])
                    for item in v:
                        if item not in combined:
                            combined.append(item)
                    merged_entities[k] = combined
                else:
                    merged_entities[k] = v

        merged_entities["raw_text"] = clean_text

        return NLPResult(
            text=clean_text,
            language=gemini_result.get('language') or rule_entities.get('language') or language or 'en',
            confidence=1.0,
            source=source,
            processing_status='completed',
            entities=merged_entities,
        )

