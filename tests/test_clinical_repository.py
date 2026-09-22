from uuid import uuid4

from api.v1 import ClinicalRepository


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, database, table_name):
        self.database = database
        self.table_name = table_name
        self.filters = {}
        self.selected = None
        self.operation = None
        self.payload = None

    def select(self, fields):
        self.operation = 'select'
        self.selected = fields
        return self

    def eq(self, field, value):
        self.filters[field] = value
        return self

    def limit(self, _count):
        return self

    def upsert(self, payload, on_conflict=None):
        self.operation = 'upsert'
        self.payload = payload
        return self

    def insert(self, payload):
        self.operation = 'insert'
        self.payload = payload
        return self

    def delete(self):
        self.operation = 'delete'
        return self

    def execute(self):
        rows = self.database.setdefault(self.table_name, [])
        if self.operation == 'select':
            result = [row.copy() for row in rows if all(row.get(key) == value for key, value in self.filters.items())]
            if self.selected and self.selected != '*':
                fields = [field.strip() for field in self.selected.split(',')]
                result = [{field: row.get(field) for field in fields} for row in result]
            return FakeResponse(result)
        if self.operation == 'delete':
            self.database[self.table_name] = [
                row for row in rows if not all(row.get(key) == value for key, value in self.filters.items())
            ]
            return FakeResponse([])
        if self.operation == 'insert':
            rows.extend(self.payload if isinstance(self.payload, list) else [self.payload])
            return FakeResponse(self.payload)
        if self.operation == 'upsert':
            payload = self.payload
            existing = next((row for row in rows if row.get('session_id') == payload.get('session_id')), None)
            if existing:
                existing.update(payload)
            else:
                rows.append(payload)
            return FakeResponse([payload])
        raise AssertionError(f'Unsupported fake operation: {self.operation}')


class FakeSupabase:
    def __init__(self):
        self.database = {}

    def table(self, table_name):
        return FakeQuery(self.database, table_name)


def test_memory_clinical_repository_round_trip():
    session_id = uuid4()
    repository = ClinicalRepository()

    repository.save_clinical_data(session_id, 'medical-history', {'chief_complaint': 'headache'})
    repository.save_clinical_data(session_id, 'medications', {
        'medications': [{'name_as_reported': 'Metformin', 'dose_as_reported': '500 mg', 'frequency_as_reported': 'daily', 'notes': 'reported'}]
    })
    repository.save_clinical_data(session_id, 'allergies', {'allergies': ['Penicillin']})

    assert repository.get_clinical_data(session_id, 'medical-history') == {'chief_complaint': 'headache'}
    assert repository.get_clinical_data(session_id, 'medications')['medications'][0]['name_as_reported'] == 'Metformin'
    assert repository.get_clinical_data(session_id, 'allergies') == {'allergies': [{'allergen': 'Penicillin'}]}


def test_supabase_repository_uses_normalized_tables():
    session_id = uuid4()
    client = FakeSupabase()
    repository = ClinicalRepository(client)

    repository.save_clinical_data(session_id, 'medical-history', {'chief_complaint': 'headache'})
    repository.save_clinical_data(session_id, 'medications', {
        'medications': [{'name_as_reported': 'Metformin', 'dose_as_reported': '500 mg', 'frequency_as_reported': 'daily', 'notes': 'reported'}]
    })
    repository.save_clinical_data(session_id, 'allergies', {'allergies': ['Penicillin']})

    assert client.database['medical_history'][0]['data'] == {'chief_complaint': 'headache'}
    assert client.database['medications'][0] == {
        'session_id': str(session_id),
        'name_as_reported': 'Metformin',
        'dose_as_reported': '500 mg',
        'frequency_as_reported': 'daily',
        'notes': 'reported',
    }
    assert client.database['allergies'][0] == {
        'session_id': str(session_id),
        'allergen': 'Penicillin',
    }
    assert repository.get_clinical_data(session_id, 'medications')['medications'][0]['dose_as_reported'] == '500 mg'
    assert repository.get_clinical_data(session_id, 'allergies') == {'allergies': [{'allergen': 'Penicillin'}]}
