/**
 * Cliniqo Multilingual Internationalization (i18n) Engine
 * Supported Languages: English (en), Tamil (ta), Hindi (hi), Telugu (te), Kannada (kn), Bengali (bn)
 */
(function() {
  "use strict";

  const I18N_DICTIONARIES = {
    en: {
      brandTitle: "Cliniqo",
      brandSubtitle: "Patient Health Hub",
      navHome: "Home",
      navStory: "Story",
      navRecords: "Records",
      navProfile: "Profile",
      navPrevious: "Previous",
      navNext: "Next",
      hearOverview: "Hear overview",
      newPatient: "New Patient",
      saved: "Saved",
      noActivePatient: "No Active Patient",
      activePatient: "Active Patient",
      abhaPending: "ABHA: Pending Link",
      selectPatient: "Select Patient",

      // Home Screen
      homeWelcome: "Welcome to Cliniqo",
      homeSubtitle: "Your health records, symptoms, and medical timeline are securely organized in your personal vault.",
      recordUpdate: "Record & update your health data",
      startAssessment: "Start Health Assessment",
      yourHealthStory: "Your Health Story",
      viewHealthStory: "View your synthesized health history, timeline, and stored records.",
      medicalRecords: "Medical Records",
      scanMedicalRecords: "Scan prescriptions, upload lab reports, and verify document OCR.",
      patientCaseRecords: "My Health Record",
      newCaseIntake: "Begin Intake",
      tapToSpeak: "Tap to speak",
      speakNaturally: "Speak naturally or tap below",

      // Intake & Assessment
      whatBringsTitle: "What Brings You In Today?",
      whatBringsSubtitle: "Tap the microphone to speak freely or select your key symptoms below.",
      aiInterviewTitle: "AI Health Assessment Interview",
      aiInterviewSubtitle: "Interactive adaptive interview analyzing clinical symptoms in real time.",
      painLocationTitle: "Where is the discomfort located?",
      followUpQuestions: "Follow-Up Questions",
      symptomsReview: "Symptoms Review",
      pastMedicalHistory: "Past Medical History & Conditions",
      medicinesAllergies: "Active Medications & Allergies",
      familyLifestyle: "Family & Lifestyle Context",
      safetyCheck: "Safety & Emergency Attention Check",

      // Summary & Dossier
      summaryTitle: "Your health data is verified & saved",
      summarySubtitle: "Cliniqo has synthesized your intake answers, scanned documents, and history into your personal health vault.",
      reasonForVisit: "Reason for Visit",
      medicalHistory: "Medical History",
      scannedDocs: "Scanned Clinical Records & Vault Findings",
      generateAiSummary: "Generate AI Summary",
      generateDoctorCase: "Generate Doctor Case",
      checkRedFlags: "Check Red Flags & Triage",
      downloadDossier: "Download Report in Text Format (.txt)",
      exportJson: "Save & Export JSON Dossier",

      // Profile & Accessibility
      profileTitle: "Patient Profile",
      accessibilityTitle: "Accessibility & Language Options",
      accessibilitySubtitle: "Choose your preferred regional dialect, contrast mode, and voice assistance speed.",
      selectLanguage: "Select Preferred Language",
      highContrast: "High Contrast Display Mode",
      largeText: "Large Text Sizing",
      savePreferences: "Save Preferences to Profile"
    },

    ta: {
      brandTitle: "கிளினிகோ",
      brandSubtitle: "நோயாளி சுகாதார மையம்",
      navHome: "முகப்பு",
      navStory: "வரலாறு",
      navRecords: "ஆவணங்கள்",
      navProfile: "சுயவிவரம்",
      navPrevious: "முந்தைய",
      navNext: "அடுத்தது",
      hearOverview: "குரலில் கேட்கவும்",
      newPatient: "புதிய நோயாளி",
      saved: "சேமிக்கப்பட்டது",
      noActivePatient: "செயலில் உள்ள நோயாளி இல்லை",
      activePatient: "செயலில் உள்ள நோயாளி",
      abhaPending: "ABHA: இணைக்கப்படவில்லை",
      selectPatient: "நோயாளியைத் தேர்ந்தெடுக்கவும்",

      homeWelcome: "கிளினிகோவிற்கு வரவேற்கிறோம்",
      homeSubtitle: "உங்கள் மருத்துவ ஆவணங்கள், அறிகுறிகள் மற்றும் சிகிச்சை வரலாறு உங்கள் தனிப்பட்ட பெட்டகத்தில் பாதுகாப்பாக உள்ளன.",
      recordUpdate: "உங்கள் சுகாதாரத் தரவைப் பதிவுசெய்து புதுப்பிக்கவும்",
      startAssessment: "சுகாதார மதிப்பீட்டைத் தொடங்கு",
      yourHealthStory: "உங்கள் சுகாதார வரலாறு",
      viewHealthStory: "உங்கள் ஒருங்கிணைந்த மருத்துவ வரலாறு மற்றும் ஆவணங்களைப் பார்க்கவும்.",
      medicalRecords: "மருத்துவ ஆவணங்கள்",
      scanMedicalRecords: "மருந்துச் சீட்டுகளை ஸ்கேன் செய்து ஆய்வக அறிக்கைகளைச் சரிபார்க்கவும்.",
      patientCaseRecords: "நோயாளி மருத்துவப் பதிவேடு",
      newCaseIntake: "புதிய மருத்துவப் பதிவு",
      tapToSpeak: "பேச தட்டவும்",
      speakNaturally: "இயற்கையாகப் பேசுங்கள் அல்லது கீழே தேர்வுசெய்யவும்",

      whatBringsTitle: "இன்று உங்களுக்கு என்ன பிரச்சனை?",
      whatBringsSubtitle: "பேச மைக்ரோஃபோனைத் தட்டவும் அல்லது உங்கள் அறிகுறிகளைத் தேர்ந்தெடுக்கவும்.",
      aiInterviewTitle: "AI மருத்துவ கலந்துரையாடல்",
      aiInterviewSubtitle: "உங்கள் அறிகுறிகளை உடனுக்குடன் ஆய்வு செய்யும் அறிவார்ந்த நேர்காணல்.",
      painLocationTitle: "வலி அல்லது அசௌகரியம் எங்குள்ளது?",
      followUpQuestions: "தொடர் கேள்விகள்",
      symptomsReview: "அறிகுறிகள் சரிபார்ப்பு",
      pastMedicalHistory: "முந்தைய மருத்துவ வரலாறு",
      medicinesAllergies: "மருந்துகள் & ஒவ்வாமைகள்",
      familyLifestyle: "குடும்பம் & வாழ்க்கை முறை",
      safetyCheck: "பாதுகாப்பு & அவசர சரிபார்ப்பு",

      summaryTitle: "உங்கள் சுகாதாரத் தரவு சரிபார்க்கப்பட்டு சேமிக்கப்பட்டது",
      summarySubtitle: "உங்கள் பதில்கள் மற்றும் ஸ்கேன் செய்யப்பட்ட ஆவணங்கள் முழுமையாகப் பதிவு செய்யப்பட்டுள்ளன.",
      reasonForVisit: "வருகைக்கான காரணம்",
      medicalHistory: "மருத்துவ வரலாறு",
      scannedDocs: "ஸ்கேன் செய்யப்பட்ட மருத்துவ ஆவணங்கள்",
      generateAiSummary: "AI சுருக்கத்தை உருவாக்கு",
      generateDoctorCase: "மருத்துவர் கேஸ் உருவாக்கு",
      checkRedFlags: "அபாயக் குறிகளைச் சரிபார்",
      downloadDossier: "உரை வடிவில் பதிவிறக்கு (.txt)",
      exportJson: "JSON ஆவணத்தை ஏற்றுமதி செய்",

      profileTitle: "நோயாளி சுயவிவரம்",
      accessibilityTitle: "அணுகல்தன்மை & மொழி விருப்பங்கள்",
      accessibilitySubtitle: "உங்கள் விருப்பமான மொழி, மாறுபட்ட காட்சி முறை மற்றும் அமைப்புகளைத் தேர்வுசெய்யவும்.",
      selectLanguage: "விருப்பமான மொழியைத் தேர்ந்தெடுக்கவும்",
      highContrast: "அதிக மாறுபட்ட காட்சி முறை",
      largeText: "பெரிய எழுத்து அளவு",
      savePreferences: "சுயவிவரத்தில் சேமிக்கவும்"
    },

    hi: {
      brandTitle: "क्लिनिको",
      brandSubtitle: "रोगी स्वास्थ्य केंद्र",
      navHome: "मुख्य पृष्ठ",
      navStory: "कथा",
      navRecords: "रिकॉर्ड",
      navProfile: "प्रोफ़ाइल",
      navPrevious: "पिछला",
      navNext: "अगला",
      hearOverview: "आवाज़ में सुनें",
      newPatient: "नया मरीज़",
      saved: "सुरक्षित",
      noActivePatient: "कोई सक्रिय मरीज़ नहीं",
      activePatient: "सक्रिय मरीज़",
      abhaPending: "ABHA: लंबित",
      selectPatient: "मरीज़ चुनें",

      homeWelcome: "क्लिनिको में आपका स्वागत है",
      homeSubtitle: "आपके स्वास्थ्य रिकॉर्ड, लक्षण और इतिहास आपके निजी वॉल्ट में सुरक्षित रूप से व्यवस्थित हैं।",
      recordUpdate: "अपना स्वास्थ्य डेटा रिकॉर्ड और अपडेट करें",
      startAssessment: "स्वास्थ्य मूल्यांकन शुरू करें",
      yourHealthStory: "आपकी स्वास्थ्य कथा",
      viewHealthStory: "अपना संश्लेषित स्वास्थ्य इतिहास, समयरेखा और रिकॉर्ड देखें।",
      medicalRecords: "चिकित्सा रिकॉर्ड",
      scanMedicalRecords: "नुस्खे स्कैन करें, लैब रिपोर्ट अपलोड करें और ओसीआर सत्यापित करें।",
      patientCaseRecords: "रोगी केस रिकॉर्ड और नैदानिक निर्देशिका",
      newCaseIntake: "नया केस इंटेक",
      tapToSpeak: "बोलने के लिए टैप करें",
      speakNaturally: "स्वाभाविक रूप से बोलें या नीचे चुनें",

      whatBringsTitle: "आज आपकी क्या समस्या है?",
      whatBringsSubtitle: "बोलने के लिए माइक टैप करें या नीचे अपने मुख्य लक्षणों का चयन करें।",
      aiInterviewTitle: "एआई स्वास्थ्य मूल्यांकन साक्षात्कार",
      aiInterviewSubtitle: "वास्तविक समय में लक्षणों का विश्लेषण करने वाला संवादात्मक साक्षात्कार।",
      painLocationTitle: "तकलीफ कहाँ पर है?",
      followUpQuestions: "अनुवर्ती प्रश्न",
      symptomsReview: "लक्षण समीक्षा",
      pastMedicalHistory: "पिछला चिकित्सा इतिहास और स्थितियां",
      medicinesAllergies: "सक्रिय दवाएं और एलर्जी",
      familyLifestyle: "परिवार और जीवन शैली संदर्भ",
      safetyCheck: "नैदानिक सुरक्षा और ट्राइएज सत्यापन",

      summaryTitle: "आपका स्वास्थ्य डेटा सत्यापित और सुरक्षित है",
      summarySubtitle: "क्लिनिको ने आपके इनटेक उत्तरों और स्कैन किए गए दस्तावेज़ों को संश्लेषित किया है।",
      reasonForVisit: "आने का मुख्य कारण",
      medicalHistory: "चिकित्सा इतिहास",
      scannedDocs: "स्कैन किए गए नैदानिक रिकॉर्ड",
      generateAiSummary: "एआई सारांश तैयार करें",
      generateDoctorCase: "डॉक्टर केस तैयार करें",
      checkRedFlags: "रेड फ्लैग्स और ट्राइएज जांचें",
      downloadDossier: "टेक्स्ट प्रारूप में डाउनलोड करें (.txt)",
      exportJson: "JSON डॉसियर निर्यात करें",

      profileTitle: "रोगी प्रोफ़ाइल",
      accessibilityTitle: "सुलभता और भाषा विकल्प",
      accessibilitySubtitle: "अपनी पसंदीदा भाषा, कंट्रास्ट मोड और प्राथमिकताओं का चयन करें।",
      selectLanguage: "पसंदीदा भाषा चुनें",
      highContrast: "उच्च कंट्रास्ट डिस्प्ले मोड",
      largeText: "बड़ा टेक्स्ट आकार",
      savePreferences: "प्रोफ़ाइल में प्राथमिकताएं सहेजें"
    },

    te: {
      brandTitle: "క్లినికో",
      brandSubtitle: "రోగి ఆరోగ్య కేంద్రం",
      navHome: "హోమ్",
      navStory: "కథనం",
      navRecords: "రికార్డులు",
      navProfile: "ప్రొఫైల్",
      navPrevious: "మునుపటి",
      navNext: "తదుపరి",
      hearOverview: "వినండి",
      newPatient: "కొత్త రోగి",
      saved: "సేవ్ చేయబడింది",
      noActivePatient: "యాక్టివ్ రోగి లేరు",
      activePatient: "యాక్టివ్ రోగి",
      abhaPending: "ABHA: పెండింగ్",
      selectPatient: "రోగిని ఎంచుకోండి",

      homeWelcome: "క్లినికోకు స్వాగతం",
      homeSubtitle: "మీ ఆరోగ్య రికార్డులు మరియు లక్షణాలు మీ వ్యక్తిగత వాల్ట్‌లో సురక్షితంగా నిర్వహించబడతాయి.",
      recordUpdate: "మీ ఆరోగ్య సమాచారాన్ని నమోదు చేయండి",
      startAssessment: "ఆరోగ్య అంచనా ప్రారంభించండి",
      yourHealthStory: "మీ ఆరోగ్య కథనం",
      viewHealthStory: "మీ ఆరోగ్య చరిత్ర మరియు రికార్డులను వీక్షించండి.",
      medicalRecords: "వైద్య రికార్డులు",
      scanMedicalRecords: "ప్రిస్క్రిప్షన్లను స్కాన్ చేయండి మరియు ల్యాబ్ రిపోర్టులను అప్‌లోడ్ చేయండి.",
      patientCaseRecords: "రోగి కేసు రికార్డులు",
      newCaseIntake: "కొత్త కేసు నమోదు",
      tapToSpeak: "మాట్లాడటానికి నొక్కండి",
      speakNaturally: "సహజంగా మాట్లాడండి లేదా కింద ఎంచుకోండి",

      whatBringsTitle: "ఈ రోజు మీ సమస్య ఏమిటి?",
      whatBringsSubtitle: "లక్షణాలను చెప్పడానికి మైక్ నొక్కండి లేదా కింద ఎంచుకోండి.",
      aiInterviewTitle: "AI ఆరోగ్య ఇంటర్వ్యూ",
      aiInterviewSubtitle: "లక్షణాలను విశ్లేషించే నిజ-సమయ సంభాషణ.",
      painLocationTitle: "నొప్పి లేదా అసౌకర్యం ఎక్కడ ఉంది?",
      followUpQuestions: "తదుపరి ప్రశ్నలు",
      symptomsReview: "లక్షణాల సమీక్ష",
      pastMedicalHistory: "గత వైద్య చరిత్ర",
      medicinesAllergies: "మందులు & అలర్జీలు",
      familyLifestyle: "కుటుంబం & జీవనశైలి",
      safetyCheck: "క్లినికల్ భద్రతా తనిఖీ",

      summaryTitle: "మీ ఆరోగ్య సమాచారం ధృవీకరించబడింది",
      summarySubtitle: "మీ సమాచారం మీ వ్యక్తిగత వాల్ట్‌లో సురక్షితంగా భద్రపరచబడింది.",
      reasonForVisit: "సందర్శన కారణం",
      medicalHistory: "వైద్య చరిత్ర",
      scannedDocs: "స్కాన్ చేసిన రికార్డులు",
      generateAiSummary: "AI సారాంశం రూపొందించండి",
      generateDoctorCase: "డాక్టర్ కేస్ రూపొందించండి",
      checkRedFlags: "రెడ్ ఫ్లాగ్స్ తనిఖీ చేయండి",
      downloadDossier: "టెక్స్ట్ నివేదిక డౌన్‌లోడ్ చేయండి (.txt)",
      exportJson: "JSON నివేదికను ఎగుమతి చేయండి",

      profileTitle: "రోగి ప్రొఫైల్",
      accessibilityTitle: "యాక్సెసిబిలిటీ & భాషా ఎంపికలు",
      accessibilitySubtitle: "మీ ప్రాధాన్య భాష మరియు డిస్ప్లే సెట్టింగ్‌లను ఎంచుకోండి.",
      selectLanguage: "ప్రాధాన్య భాషను ఎంచుకోండి",
      highContrast: "హై కాంట్రాస్ట్ మోడ్",
      largeText: "పెద్ద టెక్స్ట్ పరిమాణం",
      savePreferences: "సెట్టింగ్‌లను సేవ్ చేయండి"
    },

    kn: {
      brandTitle: "ಕ್ಲಿನಿಕ್ಕೋ",
      brandSubtitle: "ರೋಗಿ ಆರೋಗ್ಯ ಕೇಂದ್ರ",
      navHome: "ಮುಖಪುಟ",
      navStory: "ವಿವರ",
      navRecords: "ದಾಖಲೆಗಳು",
      navProfile: "ಪ್ರೊಫೈಲ್",
      navPrevious: "ಹಿಂದಿನ",
      navNext: "ಮುಂದಿನ",
      hearOverview: "ಆಡಿಯೋದಲ್ಲಿ ಕೇಳಿ",
      newPatient: "ಹೊಸ ರೋಗಿ",
      saved: "ಉಳಿಸಲಾಗಿದೆ",
      noActivePatient: "ಯಾವುದೇ ಸಕ್ರಿಯ ರೋಗಿ ಇಲ್ಲ",
      activePatient: "ಸಕ್ರಿಯ ರೋಗಿ",
      abhaPending: "ABHA: ಬಾಕಿ ಇದೆ",
      selectPatient: "ರೋಗಿಯನ್ನು ಆಯ್ಕೆಮಾಡಿ",

      homeWelcome: "ಕ್ಲಿನಿಕ್ಕೋಗೆ ಸುಸ್ವಾಗತ",
      homeSubtitle: "ನಿಮ್ಮ ಆರೋಗ್ಯ ದಾಖಲೆಗಳು ಮತ್ತು ರೋಗಲಕ್ಷಣಗಳು ನಿಮ್ಮ ವೈಯಕ್ತಿಕ ವಾಲ್ಟ್‌ನಲ್ಲಿ ಸುರಕ್ಷಿತವಾಗಿವೆ.",
      recordUpdate: "ನಿಮ್ಮ ಆರೋಗ್ಯ ಮಾಹಿತಿಯನ್ನು ನಮೂದಿಸಿ",
      startAssessment: "ಆರೋಗ್ಯ ಮೌಲ್ಯಮಾಪನ ಪ್ರಾರಂಭಿಸಿ",
      yourHealthStory: "ನಿಮ್ಮ ಆರೋಗ್ಯ ವಿವರ",
      viewHealthStory: "ನಿಮ್ಮ ಆರೋಗ್ಯ ಇತಿಹಾಸ ಮತ್ತು ದಾಖಲೆಗಳನ್ನು ವೀಕ್ಷಿಸಿ.",
      medicalRecords: "ವೈದ್ಯಕೀಯ ದಾಖಲೆಗಳು",
      scanMedicalRecords: "ಪ್ರಿಸ್ಕ್ರಿಪ್ಷನ್‌ಗಳನ್ನು ಸ್ಕ್ಯಾನ್ ಮಾಡಿ ಮತ್ತು ಲ್ಯಾಬ್ ವರದಿಗಳನ್ನು ಅಪ್‌ಲೋಡ್ ಮಾಡಿ.",
      patientCaseRecords: "ರೋಗಿ ಕೇಸ್ ಡೈರೆಕ್ಟರಿ",
      newCaseIntake: "ಹೊಸ ಕೇಸ್ ನೋಂದಣಿ",
      tapToSpeak: "ಮಾತನಾಡಲು ಒತ್ತಿರಿ",
      speakNaturally: "ಸಹಜವಾಗಿ ಮಾತನಾಡಿ ಅಥವಾ ಕೆಳಗೆ ಆಯ್ಕೆಮಾಡಿ",

      whatBringsTitle: "ಇಂದು ನಿಮ್ಮ ಆರೋಗ್ಯ ಸಮಸ್ಯೆ ಏನು?",
      whatBringsSubtitle: "ಮಾತನಾಡಲು ಮೈಕ್ ಒತ್ತಿರಿ ಅಥವಾ ಕೆಳಗೆ ರೋಗಲಕ್ಷಣಗಳನ್ನು ಆಯ್ಕೆಮಾಡಿ.",
      aiInterviewTitle: "AI ಆರೋಗ್ಯ ಸಂದರ್ಶನ",
      aiInterviewSubtitle: "ನೈಜ-ಸಮಯದಲ್ಲಿ ರೋಗಲಕ್ಷಣಗಳನ್ನು ವಿಶ್ಲೇಷಿಸುವ ಸಂವಾದ.",
      painLocationTitle: "ನೋವು ಅಥವಾ ತೊಂದರೆ ಎಲ್ಲಿದೆ?",
      followUpQuestions: "ಮುಂದಿನ ಪ್ರಶ್ನೆಗಳು",
      symptomsReview: "ರೋಗಲಕ್ಷಣಗಳ ಪರಿಶೀಲನೆ",
      pastMedicalHistory: "ಹಿಂದಿನ ವೈದ್ಯಕೀಯ ಇತಿಹಾಸ",
      medicinesAllergies: "ಔಷಧಿಗಳು ಮತ್ತು ಅಲರ್ಜಿಗಳು",
      familyLifestyle: "ಕುಟುಂಬ ಮತ್ತು ಜೀವನಶೈಲಿ",
      safetyCheck: "ಸುರಕ್ಷತಾ ಪರಿಶೀಲನೆ",

      summaryTitle: "ನಿಮ್ಮ ಆರೋಗ್ಯ ಮಾಹಿತಿ ದೃಢೀಕರಿಸಲ್ಪಟ್ಟಿದೆ",
      summarySubtitle: "ನಿಮ್ಮ ಮಾಹಿತಿ ವೈಯಕ್ತಿಕ ವಾಲ್ಟ್‌ನಲ್ಲಿ ಸುರಕ್ಷಿತವಾಗಿ ಸಂಗ್ರಹವಾಗಿದೆ.",
      reasonForVisit: "ಭೇಟಿಯ ಕಾರಣ",
      medicalHistory: "ವೈದ್ಯಕೀಯ ಇತಿಹಾಸ",
      scannedDocs: "ಸ್ಕ್ಯಾನ್ ಮಾಡಿದ ದಾಖಲೆಗಳು",
      generateAiSummary: "AI ಸಾರಾಂಶ ತಯಾರಿಸಿ",
      generateDoctorCase: "ವೈದ್ಯರ ಕೇಸ್ ತಯಾರಿಸಿ",
      checkRedFlags: "ರೆಡ್ ಫ್ಲ್ಯಾಗ್‌ಗಳನ್ನು ಪರಿಶೀಲಿಸಿ",
      downloadDossier: "ವರದಿ ಡೌನ್‌ಲೋಡ್ ಮಾಡಿ (.txt)",
      exportJson: "JSON ರಫ್ತು ಮಾಡಿ",

      profileTitle: "ರೋಗಿ ಪ್ರೊಫೈಲ್",
      accessibilityTitle: "ಪ್ರವೇಶಿಸುವಿಕೆ ಮತ್ತು ಭಾಷೆ",
      accessibilitySubtitle: "ನಿಮ್ಮ ಆಯ್ಕೆಯ ಭಾಷೆ ಮತ್ತು ಕಾಂಟ್ರಾಸ್ಟ್ ಮೋಡ್ ಆಯ್ಕೆಮಾಡಿ.",
      selectLanguage: "ಭಾಷೆಯನ್ನು ಆಯ್ಕೆಮಾಡಿ",
      highContrast: "ಹೈ ಕಾಂಟ್ರಾಸ್ಟ್ ಮೋಡ್",
      largeText: "ದೊಡ್ಡ ಅಕ್ಷರ ಗಾತ್ರ",
      savePreferences: "ಆಯ್ಕೆಗಳನ್ನು ಉಳಿಸಿ"
    },

    bn: {
      brandTitle: "ক্লিনিকো",
      brandSubtitle: "রোগী স্বাস্থ্য কেন্দ্র",
      navHome: "হোম",
      navStory: "বিবরণ",
      navRecords: "নথি",
      navProfile: "প্রোফাইল",
      navPrevious: "পূর্ববর্তী",
      navNext: "পরবর্তী",
      hearOverview: "শুনে নিন",
      newPatient: "নতুন রোগী",
      saved: "সংরক্ষিত",
      noActivePatient: "কোনো সক্রিয় রোগী নেই",
      activePatient: "সক্রিয় রোগী",
      abhaPending: "ABHA: অপেক্ষমান",
      selectPatient: "রোগী নির্বাচন করুন",

      homeWelcome: "ক্লিনিকোতে স্বাগতম",
      homeSubtitle: "আপনার চিকিৎসা নথি ও স্বাস্থ্য বিবরণ আপনার ব্যক্তিগত ভল্টে সুরক্ষিত রয়েছে।",
      recordUpdate: "আপনার স্বাস্থ্য তথ্য রেকর্ড ও আপডেট করুন",
      startAssessment: "স্বাস্থ্য মূল্যায়ন শুরু করুন",
      yourHealthStory: "আপনার স্বাস্থ্য বিবরণ",
      viewHealthStory: "আপনার স্বাস্থ্য ইতিহাস ও সংরক্ষিত নথি দেখুন।",
      medicalRecords: "চিকিৎসা রেকর্ড",
      scanMedicalRecords: "প্রেসক্রিপশন স্ক্যান করুন এবং ল্যাব রিপোর্ট আপলোড করুন।",
      patientCaseRecords: "রোগীর কেস ডিরেক্টরি",
      newCaseIntake: "নতুন কেস গ্রহণ",
      tapToSpeak: "বলতে ট্যাপ করুন",
      speakNaturally: "স্বাভাবিকভাবে বলুন বা নিচে নির্বাচন করুন",

      whatBringsTitle: "আজ আপনার কী সমস্যা?",
      whatBringsSubtitle: "কথা বলতে মাইক ট্যাপ করুন বা নিচে উপসর্গ নির্বাচন করুন।",
      aiInterviewTitle: "এআই স্বাস্থ্য মূল্যায়ন সাক্ষাৎকার",
      aiInterviewSubtitle: "বাস্তব সময়ে উপসর্গ বিশ্লেষণের জন্য ইন্টারেক্টিভ ইন্টারভিউ।",
      painLocationTitle: "ব্যথা বা অস্বস্তি কোথায়?",
      followUpQuestions: "পরবর্তী প্রশ্নাবলী",
      symptomsReview: "উপসর্গ পর্যালোচনা",
      pastMedicalHistory: "পূর্ববর্তী চিকিৎসা ইতিহাস",
      medicinesAllergies: "ওষুধ ও অ্যালার্জি",
      familyLifestyle: "পরিবার ও জীবনধারা",
      safetyCheck: "ক্লিনিকাল সুরক্ষা যাচাই",

      summaryTitle: "আপনার স্বাস্থ্য তথ্য যাচাই ও সংরক্ষিত হয়েছে",
      summarySubtitle: "আপনার সমস্ত উত্তর ও নথি সুরক্ষিতভাবে ভল্টে সংরক্ষিত।",
      reasonForVisit: "পরিদর্শনের কারণ",
      medicalHistory: "চিকিৎসা ইতিহাস",
      scannedDocs: "স্ক্যান করা চিকিৎসা নথি",
      generateAiSummary: "এআই সারাংশ তৈরি করুন",
      generateDoctorCase: "ডাক্তার কেস তৈরি করুন",
      checkRedFlags: "রেড ফ্ল্যাগ যাচাই করুন",
      downloadDossier: "টেক্সট রিপোর্ট ডাউনলোড করুন (.txt)",
      exportJson: "JSON ডসিয়ার রপ্তানি করুন",

      profileTitle: "রোগীর প্রোফাইল",
      accessibilityTitle: "অ্যাক্সেসিবিলিটি ও ভাষা বিকল্প",
      accessibilitySubtitle: "আপনার পছন্দের ভাষা এবং প্রদর্শন মোড নির্বাচন করুন।",
      selectLanguage: "পছন্দের ভাষা নির্বাচন করুন",
      highContrast: "উচ্চ বৈসাদৃশ্য মোড",
      largeText: "বড় লেখার আকার",
      savePreferences: "পছন্দ সংরক্ষণ করুন"
    }
  };

  const LANG_NAMES = {
    en: "English",
    ta: "தமிழ் (Tamil)",
    hi: "हिन्दी (Hindi)",
    te: "తెలుగు (Telugu)",
    kn: "ಕನ್ನಡ (Kannada)",
    bn: "বাংলা (Bengali)"
  };

  const SPEECH_LANG_CODES = {
    en: "en-IN",
    ta: "ta-IN",
    hi: "hi-IN",
    te: "te-IN",
    kn: "kn-IN",
    bn: "bn-IN"
  };

  let currentLanguage = localStorage.getItem("cliniqo_language") || "en";
  if (!I18N_DICTIONARIES[currentLanguage]) currentLanguage = "en";

  function t(key, lang = currentLanguage) {
    const dict = I18N_DICTIONARIES[lang] || I18N_DICTIONARIES.en;
    return dict[key] || I18N_DICTIONARIES.en[key] || key;
  }

  function setLanguage(lang) {
    if (!I18N_DICTIONARIES[lang]) lang = "en";
    currentLanguage = lang;
    localStorage.setItem("cliniqo_language", lang);
    document.documentElement.lang = lang;

    // Update Header Text
    const headerLangText = document.getElementById("headerCurrentLangText");
    if (headerLangText) {
      headerLangText.textContent = LANG_NAMES[lang] || "English";
    }

    // Update Dropdown checkmarks
    document.querySelectorAll(".lang-drop-item").forEach(item => {
      const itemLang = item.getAttribute("data-lang");
      const check = item.querySelector(".lang-drop-check");
      if (check) {
        if (itemLang === lang) {
          check.classList.remove("hidden");
        } else {
          check.classList.add("hidden");
        }
      }
    });

    // Update Accessibility Screen Cards
    document.querySelectorAll(".lang-choice-card").forEach(card => {
      const cardLang = card.getAttribute("data-lang");
      const checkIcon = card.querySelector(".lang-check");
      if (cardLang === lang) {
        card.className = "lang-choice-card p-4 rounded-2xl bg-primary text-white flex items-center justify-between border-2 border-primary shadow-xs cursor-pointer text-left";
        if (checkIcon) {
          checkIcon.textContent = "check_circle";
          checkIcon.className = "material-symbols-outlined text-[22px] text-primary-fixed lang-check";
        }
      } else {
        card.className = "lang-choice-card p-4 rounded-2xl bg-surface-container hover:bg-secondary-container text-on-surface flex items-center justify-between border border-secondary-container cursor-pointer text-left";
        if (checkIcon) {
          checkIcon.textContent = "radio_button_unchecked";
          checkIcon.className = "material-symbols-outlined text-[20px] text-secondary lang-check";
        }
      }
    });

    // Translate all elements with data-i18n
    document.querySelectorAll("[data-i18n]").forEach(el => {
      const key = el.getAttribute("data-i18n");
      if (key) {
        el.textContent = t(key, lang);
      }
    });

    // Translate placeholders
    document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
      const key = el.getAttribute("data-i18n-placeholder");
      if (key) {
        el.placeholder = t(key, lang);
      }
    });

    // Translate title attributes
    document.querySelectorAll("[data-i18n-title]").forEach(el => {
      const key = el.getAttribute("data-i18n-title");
      if (key) {
        el.title = t(key, lang);
      }
    });

    // Dispatch global language change event
    window.dispatchEvent(new CustomEvent("cliniqo:languageChange", { detail: { language: lang } }));
  }

  // Export to window
  window.CliniqoI18n = {
    t,
    setLanguage,
    getCurrentLanguage: () => currentLanguage,
    getSpeechCode: () => SPEECH_LANG_CODES[currentLanguage] || "en-IN",
    DICTIONARIES: I18N_DICTIONARIES
  };
  window.t = t;
  window.setLanguage = setLanguage;

})();
