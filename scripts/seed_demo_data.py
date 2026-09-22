"""Seed synthetic Cliniqo data into Supabase."""

from __future__ import annotations

import os
from uuid import uuid4

from dotenv import load_dotenv
from supabase import create_client


load_dotenv()

url = os.getenv('SUPABASE_URL', '').strip()
key = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()
if not url or not key:
    raise SystemExit('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.')

client = create_client(url, key)
patient_id = str(uuid4())
session_id = str(uuid4())

client.table('patients').insert({
    'patient_id': patient_id,
    'abha_id': f'SYNTHETIC-{uuid4().hex[:12].upper()}',
    'display_name': 'Synthetic Demo Patient',
    'preferred_language': 'en',
}).execute()
client.table('sessions').insert({
    'session_id': session_id,
    'patient_id': patient_id,
    'source': 'seed',
}).execute()
client.table('conversation_messages').insert({
    'session_id': session_id,
    'role': 'patient',
    'content': 'Synthetic demo report of a mild headache for one day.',
    'source': 'text',
}).execute()

print(f'Seeded synthetic patient {patient_id} and session {session_id}.')
