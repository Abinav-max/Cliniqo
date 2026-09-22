from fastapi.testclient import TestClient

from api.main import app
from api import v1
from core.schemas import OrchestrationState


client = TestClient(app)


def test_patient_session_message_flow(monkeypatch):
    class FakeOrchestrator:
        def __init__(self, session_id=None):
            self.state = OrchestrationState(session_id=session_id)

        def handle_patient_message(self, message):
            self.state.interview_state = {
                'conversation_history': [
                    {'role': 'patient', 'content': message},
                    {'role': 'assistant', 'content': 'Synthetic follow-up'},
                ]
            }
            return self.state

    monkeypatch.setattr(v1, 'MedicalOrchestrator', FakeOrchestrator)

    patient_response = client.post('/api/v1/patients', json={'display_name': 'Synthetic Patient', 'preferred_language': 'en'})
    assert patient_response.status_code == 201
    patient = patient_response.json()

    session_response = client.post('/api/v1/sessions', json={'patient_id': patient['patient_id'], 'source': 'test'})
    assert session_response.status_code == 201
    session = session_response.json()

    message_response = client.post(
        f"/api/v1/sessions/{session['session_id']}/messages",
        json={'content': 'I have a headache', 'source': 'text'},
    )
    assert message_response.status_code == 201
    assert message_response.json()['session_id'] == session['session_id']

    messages_response = client.get(f"/api/v1/sessions/{session['session_id']}/messages")
    assert messages_response.status_code == 200
    assert len(messages_response.json()) == 1

    complete_response = client.post(f"/api/v1/sessions/{session['session_id']}/complete")
    assert complete_response.status_code == 200
    assert complete_response.json()['status'] == 'completed'
