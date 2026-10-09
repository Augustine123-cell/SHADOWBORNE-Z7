"""SQLite-backed aiogram FSM storage so conversations survive process restarts."""
import asyncio
import os
import pickle
import sqlite3
from aiogram.fsm.storage.base import BaseStorage, StorageKey

class SQLiteFSMStorage(BaseStorage):
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = asyncio.Lock()
        with sqlite3.connect(self.path) as c:
            c.execute('''CREATE TABLE IF NOT EXISTS fsm_state (
                storage_key TEXT PRIMARY KEY, state TEXT, data BLOB NOT NULL DEFAULT X'80047D942E')''')

    @staticmethod
    def _key(key: StorageKey) -> str:
        return '|'.join(str(getattr(key, name, '') or '') for name in (
            'bot_id','chat_id','user_id','thread_id','business_connection_id','destiny'))

    @staticmethod
    def _state_str(state):
        # aiogram passes a State object (or str/None). sqlite can only store text.
        if state is None or isinstance(state, str): return state
        return getattr(state, 'state', None) or str(state)

    async def set_state(self, key: StorageKey, state=None) -> None:
        k=self._key(key); state=self._state_str(state)
        async with self._lock:
            with sqlite3.connect(self.path) as c:
                c.execute('INSERT INTO fsm_state(storage_key,state,data) VALUES(?,?,?) ON CONFLICT(storage_key) DO UPDATE SET state=excluded.state',(k, state, pickle.dumps({})))

    async def get_state(self, key: StorageKey):
        async with self._lock:
            with sqlite3.connect(self.path) as c:
                row=c.execute('SELECT state FROM fsm_state WHERE storage_key=?',(self._key(key),)).fetchone()
                return row[0] if row else None

    async def set_data(self, key: StorageKey, data: dict) -> None:
        k=self._key(key)
        async with self._lock:
            with sqlite3.connect(self.path) as c:
                row=c.execute('SELECT state FROM fsm_state WHERE storage_key=?',(k,)).fetchone()
                c.execute('INSERT INTO fsm_state(storage_key,state,data) VALUES(?,?,?) ON CONFLICT(storage_key) DO UPDATE SET data=excluded.data',(k,row[0] if row else None,pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)))

    async def get_data(self, key: StorageKey) -> dict:
        async with self._lock:
            with sqlite3.connect(self.path) as c:
                row=c.execute('SELECT data FROM fsm_state WHERE storage_key=?',(self._key(key),)).fetchone()
                if not row: return {}
                try: return pickle.loads(row[0])
                except Exception: return {}

    async def close(self) -> None:
        return None
