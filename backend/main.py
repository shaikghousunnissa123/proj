import os
import sys

# Ensure parent directory is in python path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import shutil

from backend import db, parser, rag, jobs

# Initialize FastAPI
app = FastAPI(title="Life Graph AI API")

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "data", "uploads")
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(FRONTEND_DIR, exist_ok=True)

# Startup DB init
@app.on_event("startup")
def startup_event():
    db.init_db()

# Pydantic schemas
class RegisterRequest(BaseModel):
    username: str
    password: str
    fullname: str

class LoginRequest(BaseModel):
    username: str
    password: str

class ProfileUpdate(BaseModel):
    username: str
    fullname: str

class SettingsUpdate(BaseModel):
    target_role: Optional[str] = None

class ContactAdminRequest(BaseModel):
    subject: str
    message: str

class ChatQuery(BaseModel):
    query: str

class StudyToolRequest(BaseModel):
    tool_type: str  # 'quiz', 'summary', 'explain'
    document_id: int

# Header dependency to extract user_id session context
async def get_current_user_id(x_user_id: Optional[str] = Header(None)) -> int:
    if not x_user_id or x_user_id == "undefined" or x_user_id == "null":
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return int(x_user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid session token")

def get_user_api_key(user_id: int) -> Optional[str]:
    """Returns the developer-managed Gemini API key from Replit Secrets."""
    return os.environ.get("GEMINI_API_KEY")

# --- Authentication Routes ---

@app.post("/api/auth/register")
def register_student(data: RegisterRequest):
    try:
        user_id = db.create_user(data.username, data.password, data.fullname)
        return {
            "status": "success",
            "user": {
                "id": user_id,
                "username": data.username.lower(),
                "fullname": data.fullname
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/auth/login")
def login_student(data: LoginRequest):
    user = db.verify_user(data.username, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {
        "status": "success",
        "user": user
    }

# --- Partitioned API Routes ---

@app.post("/api/settings")
def update_settings(data: SettingsUpdate, user_id: int = Depends(get_current_user_id)):
    if data.target_role is not None:
        db.save_setting(user_id, "target_role", data.target_role)
    return {"status": "success", "message": "Settings updated"}

@app.get("/api/settings")
def get_settings(user_id: int = Depends(get_current_user_id)):
    return {
        "gemini_configured": bool(os.environ.get("GEMINI_API_KEY")),
        "target_role": db.get_setting(user_id, "target_role") or "Frontend Developer"
    }

@app.get("/api/profile")
def get_profile(user_id: int = Depends(get_current_user_id)):
    profile = db.get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    return profile

@app.put("/api/profile")
def update_profile(data: ProfileUpdate, user_id: int = Depends(get_current_user_id)):
    username = data.username.strip()
    fullname = data.fullname.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(fullname) < 2:
        raise HTTPException(status_code=400, detail="Full name must be at least 2 characters")
    try:
        return db.update_user_profile(user_id, username, fullname)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.post("/api/contact-admin")
def contact_admin(data: ContactAdminRequest, user_id: int = Depends(get_current_user_id)):
    subject = data.subject.strip()
    message = data.message.strip()
    if len(subject) < 3:
        raise HTTPException(status_code=400, detail="Please enter a subject")
    if len(message) < 10:
        raise HTTPException(status_code=400, detail="Please enter at least 10 characters")
    message_id = db.save_admin_message(user_id, subject, message)
    return {
        "status": "success",
        "message_id": message_id,
        "message": "Your message was sent to the admin review inbox."
    }

@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    is_resume: bool = Form(False),
    user_id: int = Depends(get_current_user_id)
):
    try:
        # Save file to upload directory
        user_upload_dir = os.path.join(UPLOAD_DIR, str(user_id))
        os.makedirs(user_upload_dir, exist_ok=True)
        
        file_path = os.path.join(user_upload_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Re-open file to read bytes
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        file_size = len(file_bytes)
        
        # 1. Parse content
        pages = parser.extract_file_content(file.filename, file_bytes)
        full_content = "\n\n".join([page["text"] for page in pages])
        
        # 2. Save document to SQLite
        doc_id = db.save_document(
            user_id=user_id,
            filename=file.filename,
            file_path=file_path,
            file_size=file_size,
            file_type=file.filename.split(".")[-1].lower(),
            content=full_content
        )
        
        # 3. Chunk text, embed and store chunks
        api_key = get_user_api_key(user_id)
        chunks = rag.chunk_document_pages(pages)
        
        # Generate embeddings for each chunk
        for chunk in chunks:
            chunk["embedding"] = rag.get_embedding(chunk["text"], api_key, task_type="retrieval_document")
            
        db.save_chunks(doc_id, chunks)
        
        # 4. If identified as resume, extract and save student skills
        extracted_skills = []
        is_resume_filename = any(kw in file.filename.lower() for kw in ["resume", "cv", "bio", "portfolio"])
        
        if is_resume or is_resume_filename:
            extracted_skills = rag.extract_skills_from_text(full_content, api_key)
            db.save_skills(user_id, extracted_skills)
            
        return {
            "status": "success",
            "document_id": doc_id,
            "filename": file.filename,
            "chunks_count": len(chunks),
            "is_resume_detected": is_resume or is_resume_filename,
            "skills_extracted_count": len(extracted_skills)
        }
        
    except Exception as e:
        print(f"Error processing upload: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@app.get("/api/documents")
def list_documents(user_id: int = Depends(get_current_user_id)):
    return db.get_documents(user_id)

@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: int, user_id: int = Depends(get_current_user_id)):
    # Find file path to delete file from disk
    doc = db.get_document(user_id, doc_id)
    if doc and doc["file_path"] and os.path.exists(doc["file_path"]):
        try:
            os.remove(doc["file_path"])
        except Exception as e:
            print(f"Could not remove file from disk: {e}")
            
    db.delete_document(user_id, doc_id)
    return {"status": "success", "message": "Document and associated memory deleted."}

@app.get("/api/documents/{doc_id}/download")
def download_document(doc_id: int, user_id: int = Depends(get_current_user_id)):
    doc = db.get_document(user_id, doc_id)
    if not doc or not doc["file_path"] or not os.path.exists(doc["file_path"]):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        doc["file_path"],
        filename=doc["filename"],
        media_type="application/octet-stream"
    )

@app.get("/api/search")
def search_documents(q: str, user_id: int = Depends(get_current_user_id)):
    if not q or not q.strip():
        # Fallback to search all user documents chunk snippets for document viewer
        all_chunks = db.get_all_user_chunks(user_id)
        return [{
            "chunk_id": c["id"],
            "document_id": c["document_id"],
            "filename": c["filename"],
            "location": c["location"],
            "text": c["text"],
            "match_type": "list",
            "score": 1.0
        } for c in all_chunks]
        
    api_key = get_user_api_key(user_id)
    
    # 1. Semantic search
    q_emb = rag.get_embedding(q, api_key, task_type="retrieval_query")
    vector_results = db.vector_search(user_id, q_emb, top_k=6)
    
    # 2. Keyword search (FTS)
    keyword_results = db.keyword_search(user_id, q)
    
    # Combine results
    seen = set()
    combined = []
    
    for r in vector_results:
        seen.add(r["chunk_id"])
        combined.append({
            "chunk_id": r["chunk_id"],
            "document_id": r["document_id"],
            "filename": r["filename"],
            "location": r["location"],
            "text": r["text"],
            "match_type": "semantic",
            "score": r["score"]
        })
        
    for r in keyword_results:
        if r["chunk_id"] not in seen:
            seen.add(r["chunk_id"])
            combined.append({
                "chunk_id": r["chunk_id"],
                "document_id": r["document_id"],
                "filename": r["filename"],
                "location": r["location"],
                "text": r["text"],
                "match_type": "keyword",
                "score": 0.6 # default match weight
            })
            
    # Sort combined by score
    combined.sort(key=lambda x: x["score"], reverse=True)
    return combined

@app.post("/api/chat")
def chat_with_docs(query_data: ChatQuery, user_id: int = Depends(get_current_user_id)):
    api_key = get_user_api_key(user_id)
    result = rag.answer_query(user_id, query_data.query, api_key)
    return result

@app.post("/api/chat/study-tool")
def study_tool(req: StudyToolRequest, user_id: int = Depends(get_current_user_id)):
    api_key = get_user_api_key(user_id)
    result = rag.run_study_tool(user_id, req.tool_type, req.document_id, api_key)
    return {"result": result}

@app.get("/api/skills")
def get_student_skills(user_id: int = Depends(get_current_user_id)):
    skills = db.get_skills(user_id)
    if not skills:
        # Return default student skill sets if they haven't uploaded resume yet
        # for illustrative premium UI
        return [
            {"skill_name": "Python", "category": "Programming", "level": 80, "evidence": "Pre-filled placeholder skill profile. Upload a resume to detect real levels."},
            {"skill_name": "Data Structures", "category": "Computer Science", "level": 75, "evidence": "Pre-filled placeholder skill profile."},
            {"skill_name": "SQL", "category": "Databases", "level": 60, "evidence": "Pre-filled placeholder skill profile."},
            {"skill_name": "HTML/CSS", "category": "Web Development", "level": 70, "evidence": "Pre-filled placeholder skill profile."},
            {"skill_name": "Java", "category": "Programming", "level": 50, "evidence": "Pre-filled placeholder skill profile."}
        ]
    return skills

@app.post("/api/skills/clear")
def clear_skills(user_id: int = Depends(get_current_user_id)):
    db.clear_skills(user_id)
    return {"status": "success"}

@app.get("/api/jobs")
def get_matched_jobs(user_id: int = Depends(get_current_user_id)):
    skills = db.get_skills(user_id)
    target_role = db.get_setting(user_id, "target_role") or "Frontend Developer"
    # Calculate matches
    matches = jobs.calculate_job_matches(skills, target_role)
    return matches

@app.get("/api/jobs/gap")
def get_job_gap(user_id: int = Depends(get_current_user_id)):
    skills = db.get_skills(user_id)
    target_role = db.get_setting(user_id, "target_role") or "Frontend Developer"
    gap_data = jobs.get_skill_gaps_and_recommendations(target_role, skills)
    return gap_data

# Mount frontend files (MUST be mounted at the end so it doesn't mask API routes)
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    @app.get("/")
    def read_root():
        return {"message": "Life Graph AI API. Create 'frontend' directory to serve the frontend web page."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
