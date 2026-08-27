import sqlite3
import os
import json
import hashlib
import secrets
import re
import numpy as np

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "lifegraph.db")

def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """Hashes a password using SHA-256 and a hex salt."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((password + salt).encode("utf-8")).hexdigest()
    return hashed, salt

def init_db():
    """Initializes the SQLite database schemas with user authentication and partitioning."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        fullname TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 2. Documents Table (with user_id partition)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        filename TEXT NOT NULL,
        file_path TEXT,
        file_size INTEGER,
        file_type TEXT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        content TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    
    # 3. Chunks Table (cascaded delete from documents)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id INTEGER,
        chunk_index INTEGER,
        location TEXT,
        text TEXT,
        embedding TEXT, -- JSON string of floats
        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
    )
    """)
    
    # 4. Skills Table (partitioned by user)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        skill_name TEXT NOT NULL,
        category TEXT,
        level INTEGER DEFAULT 0, -- 0 to 100
        evidence TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, skill_name)
    )
    """)
    
    # 5. Settings Table (partitioned by user)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        user_id INTEGER,
        key TEXT,
        value TEXT,
        PRIMARY KEY (user_id, key),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # 6. Messages sent to the administrator
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admin_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- User Auth Functions ---

def create_user(username: str, password: str, fullname: str) -> int:
    """Registers a new user, hashes password, and returns user_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed_pwd, salt = hash_password(password)
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, salt, fullname) VALUES (?, ?, ?, ?)",
            (username.lower().strip(), hashed_pwd, salt, fullname.strip())
        )
        user_id = cursor.lastrowid
        conn.commit()
        return user_id
    except sqlite3.IntegrityError:
        raise ValueError("Username already exists")
    finally:
        conn.close()

def verify_user(username: str, password: str) -> dict:
    """Verifies a user's password, returning their details on success."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password_hash, salt, fullname FROM users WHERE username = ?", (username.lower().strip(),))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
        
    hashed_pwd, _ = hash_password(password, row["salt"])
    if hashed_pwd == row["password_hash"]:
        return {
            "id": row["id"],
            "username": row["username"],
            "fullname": row["fullname"]
        }
    return None

def get_user_profile(user_id: int) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, fullname FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_user_profile(user_id: int, username: str, fullname: str) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET username = ?, fullname = ? WHERE id = ?",
            (username.lower().strip(), fullname.strip(), user_id)
        )
        if cursor.rowcount == 0:
            raise ValueError("User profile not found")
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError("That username is already in use")
    finally:
        conn.close()
    return get_user_profile(user_id)

def save_admin_message(user_id: int, subject: str, message: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO admin_messages (user_id, subject, message) VALUES (?, ?, ?)",
        (user_id, subject.strip(), message.strip())
    )
    message_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return message_id

# --- Partitioned Document Operations ---

def save_document(user_id: int, filename: str, file_path: str, file_size: int, file_type: str, content: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO documents (user_id, filename, file_path, file_size, file_type, content) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, filename, file_path, file_size, file_type, content)
    )
    doc_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return doc_id

def delete_document(user_id: int, doc_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Check ownership
    cursor.execute("SELECT id FROM documents WHERE id = ? AND user_id = ?", (doc_id, user_id))
    row = cursor.fetchone()
    if row:
        cursor.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))
        cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
    conn.close()

def save_chunks(doc_id: int, chunks: list[dict]):
    """Saves text chunks and their embeddings."""
    conn = get_db_connection()
    cursor = conn.cursor()
    for chunk in chunks:
        embedding_json = json.dumps(chunk["embedding"])
        cursor.execute(
            "INSERT INTO chunks (document_id, chunk_index, location, text, embedding) VALUES (?, ?, ?, ?, ?)",
            (doc_id, chunk["chunk_index"], chunk["location"], chunk["text"], embedding_json)
        )
    conn.commit()
    conn.close()

def get_documents(user_id: int) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, filename, file_path, file_size, file_type, uploaded_at FROM documents WHERE user_id = ? ORDER BY uploaded_at DESC", 
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_document(user_id: int, doc_id: int) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM documents WHERE id = ? AND user_id = ?", (doc_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_user_chunks(user_id: int) -> list[dict]:
    """Retrieves all chunks belonging to a user's documents."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.document_id, c.chunk_index, c.location, c.text, c.embedding, d.filename 
        FROM chunks c 
        JOIN documents d ON c.document_id = d.id
        WHERE d.user_id = ?
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    
    chunks = []
    for row in rows:
        d = dict(row)
        try:
            d["embedding"] = json.loads(d["embedding"])
        except Exception:
            d["embedding"] = []
        chunks.append(d)
    return chunks

# --- Search Algorithms ---

def cosine_similarity(v1, v2):
    try:
        arr1 = np.array(v1, dtype=np.float32)
        arr2 = np.array(v2, dtype=np.float32)
        dot = np.dot(arr1, arr2)
        norm1 = np.linalg.norm(arr1)
        norm2 = np.linalg.norm(arr2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(dot / (norm1 * norm2))
    except Exception:
        dot_product = sum(x * y for x, y in zip(v1, v2))
        norm_v1 = sum(x * x for x in v1) ** 0.5
        norm_v2 = sum(x * x for x in v2) ** 0.5
        if not norm_v1 or not norm_v2:
            return 0.0
        return dot_product / (norm_v1 * norm_v2)

def vector_search(user_id: int, query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """Performs semantic search across the user's vector embeddings."""
    user_chunks = get_all_user_chunks(user_id)
    if not user_chunks or not query_embedding:
        return []
    
    scored_chunks = []
    for chunk in user_chunks:
        if not chunk["embedding"]:
            continue
        sim = cosine_similarity(query_embedding, chunk["embedding"])
        scored_chunks.append({
            "chunk_id": chunk["id"],
            "document_id": chunk["document_id"],
            "filename": chunk["filename"],
            "location": chunk["location"],
            "text": chunk["text"],
            "score": sim
        })
        
    scored_chunks.sort(key=lambda x: x["score"], reverse=True)
    return scored_chunks[:top_k]

def keyword_search(user_id: int, keyword: str) -> list[dict]:
    """Searches filenames and extracted document text for any supplied keyword."""
    terms = list(dict.fromkeys(re.findall(r"[a-zA-Z0-9_]+", keyword.lower())))
    if not terms:
        return []

    conn = get_db_connection()
    cursor = conn.cursor()
    conditions = []
    params = [user_id]
    for term in terms:
        conditions.append("(LOWER(c.text) LIKE ? OR LOWER(d.filename) LIKE ?)")
        like_pattern = f"%{term}%"
        params.extend([like_pattern, like_pattern])

    cursor.execute(f"""
        SELECT c.id as chunk_id, c.document_id, c.location, c.text, d.filename
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE d.user_id = ? AND ({' OR '.join(conditions)})
        LIMIT 20
    """, params)
    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        result = dict(row)
        searchable_text = f"{result['filename']} {result['text']}".lower()
        result["keyword_matches"] = sum(1 for term in terms if term in searchable_text)
        results.append(result)

    results.sort(key=lambda result: result["keyword_matches"], reverse=True)
    return results

# --- Partitioned Skill Profile Operations ---

def save_skills(user_id: int, skills: list[dict]):
    """Saves or updates skills in the database for a specific user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    for s in skills:
        cursor.execute("""
            INSERT INTO skills (user_id, skill_name, category, level, evidence)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, skill_name) DO UPDATE SET
                category = excluded.category,
                level = MAX(skills.level, excluded.level),
                evidence = skills.evidence || '; ' || excluded.evidence
        """, (user_id, s["skill_name"], s.get("category", "General"), s.get("level", 50), s.get("evidence", "")))
    conn.commit()
    conn.close()

def get_skills(user_id: int) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, skill_name, category, level, evidence FROM skills WHERE user_id = ? ORDER BY level DESC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def clear_skills(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM skills WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# --- Partitioned Settings Operations ---

def save_setting(user_id: int, key: str, value: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?)
        ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value
    """, (user_id, key, value))
    conn.commit()
    conn.close()

def get_setting(user_id: int, key: str) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE user_id = ? AND key = ?", (user_id, key))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else None
