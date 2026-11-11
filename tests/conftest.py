"""Every test gets an in-memory credential store; the real one is never touched."""

import keyring
import pytest
from keyring.backend import KeyringBackend

from papernym.core import keystore


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.items = {}

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        self.items.pop((service, username), None)


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch):
    monkeypatch.delenv("PAPERNYM_KEYRING", raising=False)
    previous = keyring.get_keyring()
    store = MemoryKeyring()
    keyring.set_keyring(store)
    keystore.reset_cache()
    yield store
    keyring.set_keyring(previous)
    keystore.reset_cache()
