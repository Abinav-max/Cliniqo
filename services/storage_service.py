from __future__ import annotations

from typing import Any


class StorageServiceError(RuntimeError):
    pass


class SupabaseStorageService:
    def __init__(self, client: Any, bucket: str = 'medical-documents') -> None:
        self.client = client
        self.bucket = bucket

    def upload(self, content: bytes, path: str, mime_type: str) -> str:
        try:
            self.client.storage.from_(self.bucket).upload(
                path,
                content,
                {'content-type': mime_type, 'upsert': 'false'},
            )
        except Exception as exc:
            raise StorageServiceError('Unable to store document.') from exc
        return path

    def delete(self, path: str) -> None:
        try:
            self.client.storage.from_(self.bucket).remove([path])
        except Exception as exc:
            raise StorageServiceError('Unable to delete document.') from exc

    def download(self, path: str) -> bytes:
        try:
            return self.client.storage.from_(self.bucket).download(path)
        except Exception as exc:
            raise StorageServiceError('Unable to retrieve document.') from exc
