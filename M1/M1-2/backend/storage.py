"""Small document store. Personal records are always scoped by browser owner."""
import json
from hashlib import sha256
import sqlite3
import threading
from . import config

MEMBER_TABLES = {'wardrobe': 'garments', 'wardrobe_images': 'garment_images'}


def member_id(owner):
    return int(owner[7:]) if owner.startswith('member:') else None


def user_key(username):
    return sha256(username.encode('utf-8')).hexdigest()


class Store:
    def __init__(self, path=None, mode=None):
        self.mode = mode or config.STORAGE
        self.lock = threading.RLock()
        if self.mode == 'firestore':
            import firebase_admin
            from firebase_admin import credentials, firestore
            if not config.FIREBASE_CREDENTIAL:
                raise RuntimeError('Firestore credential is required')
            raw = config.FIREBASE_CREDENTIAL
            credential = credentials.Certificate(json.loads(raw) if raw.lstrip().startswith('{') else raw)
            app = firebase_admin.initialize_app(credential, name='my-closet')
            self.db = firestore.client(app)
        else:
            self.db = sqlite3.connect(path or config.RUNTIME / 'closet.sqlite3', check_same_thread=False)
            self.db.executescript('''
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS documents (collection TEXT, owner TEXT, id TEXT, payload TEXT, PRIMARY KEY(collection,owner,id));
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                    password_salt TEXT NOT NULL, password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS garments (
                    user_id INTEGER NOT NULL REFERENCES users(id), id TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY (user_id,id)
                );
                CREATE TABLE IF NOT EXISTS garment_images (
                    user_id INTEGER NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (user_id,id),
                    FOREIGN KEY (user_id,id) REFERENCES garments(user_id,id) ON DELETE CASCADE
                );
            ''')

    def get_user(self, username):
        if self.mode == 'firestore':
            key = user_key(username)
            row = self.get('users', 'server', key)
            return (key, row['password_salt'], row['password_hash']) if row else None
        with self.lock:
            return self.db.execute('SELECT id, password_salt, password_hash FROM users WHERE username=?', (username,)).fetchone()

    def create_firestore_user(self, username, salt, password_hash):
        if self.mode != 'firestore':
            raise RuntimeError('Firestore is required to create a deployment account')
        self._collection('users', 'server').document(user_key(username)).create(
            {'password_salt': salt, 'password_hash': password_hash}, timeout=10)

    def _collection(self, collection, owner):
        # Top-level names retain the required data/conversations collections.
        return self.db.collection(collection).document(owner).collection('records')

    def get(self, collection, owner, identifier):
        if self.mode == 'firestore':
            doc = self._collection(collection, owner).document(identifier).get(timeout=10)
            return doc.to_dict() if doc.exists else None
        with self.lock:
            table = MEMBER_TABLES.get(collection)
            if table and (user_id := member_id(owner)) is not None:
                row = self.db.execute(f'SELECT payload FROM {table} WHERE user_id=? AND id=?', (user_id, identifier)).fetchone()
            else:
                row = self.db.execute('SELECT payload FROM documents WHERE collection=? AND owner=? AND id=?', (collection, owner, identifier)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, collection, owner):
        if self.mode == 'firestore':
            return [doc.to_dict() for doc in self._collection(collection, owner).stream(timeout=10)]
        with self.lock:
            table = MEMBER_TABLES.get(collection)
            if collection == 'wardrobe' and (user_id := member_id(owner)) is not None:
                rows = self.db.execute('''SELECT g.payload FROM users u
                    JOIN garments g ON g.user_id=u.id
                    JOIN garment_images i ON i.user_id=g.user_id AND i.id=g.id
                    WHERE u.id=?''', (user_id,)).fetchall()
            elif table and (user_id := member_id(owner)) is not None:
                rows = self.db.execute(f'SELECT payload FROM {table} WHERE user_id=?', (user_id,)).fetchall()
            else:
                rows = self.db.execute('SELECT payload FROM documents WHERE collection=? AND owner=?', (collection, owner)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, collection, owner, identifier, payload):
        if self.mode == 'firestore':
            self._collection(collection, owner).document(identifier).set(payload, timeout=10)
        else:
            with self.lock:
                serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
                table = MEMBER_TABLES.get(collection)
                if table and (user_id := member_id(owner)) is not None:
                    self.db.execute(f'''INSERT INTO {table} VALUES (?,?,?)
                        ON CONFLICT(user_id,id) DO UPDATE SET payload=excluded.payload''', (user_id, identifier, serialized))
                else:
                    self.db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?,?)', (collection, owner, identifier, serialized))
                self.db.commit()
        return payload

    def delete(self, collection, owner, identifier):
        if self.mode == 'firestore':
            self._collection(collection, owner).document(identifier).delete(timeout=10)
        else:
            with self.lock:
                table = MEMBER_TABLES.get(collection)
                if table and (user_id := member_id(owner)) is not None:
                    self.db.execute(f'DELETE FROM {table} WHERE user_id=? AND id=?', (user_id, identifier))
                else:
                    self.db.execute('DELETE FROM documents WHERE collection=? AND owner=? AND id=?', (collection, owner, identifier))
                self.db.commit()

    def attach_outfit_preview(self, owner, identifier, preview_key):
        if self.mode == 'firestore':
            from google.api_core.exceptions import NotFound

            try:
                self._collection('outfits', owner).document(identifier).update({'preview_key': preview_key}, timeout=10)
            except NotFound:
                return False
            return True
        with self.lock, self.db:
            updated = self.db.execute("""UPDATE documents SET payload=json_set(payload, '$.preview_key', ?)
                WHERE collection='outfits' AND owner=? AND id=?""", (preview_key, owner, identifier))
            return updated.rowcount == 1

    def prune_conversations(self, cutoff):
        if self.mode == 'firestore':
            from google.api_core.exceptions import FailedPrecondition, NotFound
            from google.cloud.firestore_v1.base_query import FieldFilter

            for owner in self.db.collection('conversations').list_documents(timeout=10):
                expired = owner.collection('records').where(filter=FieldFilter('updated_at', '<=', cutoff))
                for record in expired.stream(timeout=10):
                    # A reply saved after the query refreshes retention.
                    option = self.db.write_option(last_update_time=record.update_time)
                    try:
                        record.reference.delete(option=option, timeout=10)
                    except (FailedPrecondition, NotFound):
                        continue
            return
        with self.lock, self.db:
            self.db.execute("""DELETE FROM documents
                WHERE collection='conversations' AND json_extract(payload, '$.updated_at') <= ?""",
                (cutoff,))

    def save_garment(self, owner, row, images):
        key = row['id']
        if self.mode == 'firestore':
            batch = self.db.batch()
            batch.create(self._collection('wardrobe', owner).document(key), row)
            batch.create(self._collection('wardrobe_images', owner).document(key), images)
            batch.commit(timeout=10)
            return
        if self.mode == 'local' and (user_id := member_id(owner)) is not None:
            with self.lock, self.db:
                self.db.execute('INSERT INTO garments VALUES (?,?,?)', (user_id, key, json.dumps(row, ensure_ascii=False, allow_nan=False)))
                self.db.execute('INSERT INTO garment_images VALUES (?,?,?)', (user_id, key, json.dumps(images, ensure_ascii=False, allow_nan=False)))
            return
        self.put('wardrobe_images', owner, key, images)
        try:
            self.put('wardrobe', owner, key, row)
        except Exception:
            self.delete('wardrobe_images', owner, key)
            raise

    def reserve_ai(self, day, owner, limit):
        """Persist daily budgets atomically, including across server restarts."""
        def increment(data):
            data = data or {'count': 0, 'owners': {}}
            if limit is not None and (data['count'] >= limit or data['owners'].get(owner, 0) >= 30):
                return None
            data['count'] += 1
            data['owners'][owner] = data['owners'].get(owner, 0) + 1
            return data
        if self.mode == 'firestore':
            from firebase_admin import firestore
            reference = self._collection('usage', 'server').document(day)
            @firestore.transactional
            def reserve(transaction):
                updated = increment(reference.get(transaction=transaction).to_dict())
                if updated is None:
                    return False
                transaction.set(reference, updated)
                return True
            return reserve(self.db.transaction())
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                updated = increment(self.get('usage', 'server', day))
                if updated is None:
                    self.db.rollback()
                    return False
                self.put('usage', 'server', day, updated)
                return True
            except Exception:
                self.db.rollback()
                raise


store = Store()
