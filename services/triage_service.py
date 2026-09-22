from __future__ import annotations

import re

from services.contracts import TriageFlag


_RULES = (
    ('severe_chest_pain', 'chest pain', 'Chest pain requires urgent clinical review.'),
    ('severe_breathing_difficulty', 'cannot breathe', 'Severe breathing difficulty requires urgent clinical review.'),
    ('stroke_like_symptoms', 'face drooping', 'Possible stroke-like symptom requires urgent clinical review.'),
    ('severe_bleeding', 'uncontrolled bleeding', 'Uncontrolled bleeding requires urgent clinical review.'),
    ('seizure', 'seizure', 'Seizure activity requires urgent clinical review.'),
    ('self_harm_emergency', 'kill myself', 'Possible self-harm emergency requires immediate clinical support.'),
    ('severe_allergic_reaction', 'throat swelling', 'Possible severe allergic reaction requires urgent clinical review.'),
)


class DeterministicTriageService:
    def evaluate(self, text: str) -> list[TriageFlag]:
        normalized = re.sub(r'\s+', ' ', text.lower()).strip()
        flags: list[TriageFlag] = []
        for category, phrase, reason in _RULES:
            if phrase in normalized:
                flags.append(
                    TriageFlag(
                        is_red_flag=True,
                        severity='urgent',
                        category=category,
                        reason=reason,
                        source='rule',
                    )
                )
        return flags
