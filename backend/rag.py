import json
import re
import google.generativeai as genai
from backend import db

def get_embedding(text: str, api_key: str = None, task_type: str = "retrieval_document") -> list[float]:
    """Generates text embedding using Google Gemini API or a deterministic fallback if API key is not present."""
    if not api_key:
        # Fallback deterministic vector calculation based on word hashes
        v = [0.0] * 768
        for word in text.lower().split():
            h = hash(word) % 768
            v[h] += 1.0
        # Normalize
        norm = sum(x*x for x in v) ** 0.5
        if norm > 0:
            v = [x / norm for x in v]
        return v
    
    try:
        genai.configure(api_key=api_key)
        # Use embedding-004 model
        result = genai.embed_content(
            model="models/text-embedding-004",
            contents=text,
            task_type=task_type
        )
        # For multiple inputs, it returns list of embeddings, for single text it returns dict with 'embedding'
        if isinstance(result, dict) and "embedding" in result:
            return result["embedding"]
        elif isinstance(result, list):
            return result
        return result.get("embedding", [0.0] * 768)
    except Exception as e:
        print(f"Error generating embedding via Gemini API: {e}")
        # Return empty list or fallback
        return [0.0] * 768

def chunk_document_pages(pages: list[dict], chunk_size: int = 1000, overlap: int = 150) -> list[dict]:
    """Chunks text extracted page-by-page from a file into overlapping blocks, preserving location metadata."""
    chunks = []
    chunk_idx = 0
    for page in pages:
        text = page["text"]
        loc = page["location"]
        if not text:
            continue
            
        if len(text) <= chunk_size:
            chunks.append({
                "chunk_index": chunk_idx,
                "location": loc,
                "text": text
            })
            chunk_idx += 1
        else:
            # Overlapping window split
            start = 0
            while start < len(text):
                end = start + chunk_size
                chunk_text = text[start:end]
                # Avoid orphan tiny chunks
                if len(chunk_text) < 100 and start > 0:
                    break
                chunks.append({
                    "chunk_index": chunk_idx,
                    "location": loc,
                    "text": chunk_text
                })
                chunk_idx += 1
                start += chunk_size - overlap
    return chunks

def extract_skills_from_text(text: str, api_key: str = None) -> list[dict]:
    """Asks Gemini to analyze a document's text and extract a structured JSON list of student skills."""
    if not text.strip():
        return []
        
    if not api_key:
        # Mock/Basic fallback parser when API key is missing
        # We can extract common tech keywords
        tech_keywords = {
            "Python": "Programming", "Java": "Programming", "C++": "Programming", "JavaScript": "Programming",
            "TypeScript": "Programming", "Go": "Programming", "Rust": "Programming", "Ruby": "Programming",
            "HTML": "Web Development", "CSS": "Web Development", "React": "Web Development", "Angular": "Web Development",
            "SQL": "Databases", "PostgreSQL": "Databases", "MongoDB": "Databases", "MySQL": "Databases",
            "Git": "Tools", "Docker": "Tools", "AWS": "Cloud", "Kubernetes": "Tools", "Linux": "Operating Systems",
            "Machine Learning": "AI/Data Science", "Data Structures": "Computer Science", "Algorithms": "Computer Science",
            "DBMS": "Computer Science", "Computer Networks": "Computer Science"
        }
        extracted = []
        for kw, cat in tech_keywords.items():
            pattern = rf"\b{re.escape(kw)}\b"
            if re.search(pattern, text, re.IGNORECASE):
                extracted.append({
                    "skill_name": kw,
                    "category": cat,
                    "level": 60, # baseline guess
                    "evidence": f"Found reference to '{kw}' in uploaded profile documents."
                })
        return extracted

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("models/gemini-2.5-flash")
        
        prompt = f"""
        Analyze the following student resume/profile text. Extract all technical and professional skills mentioned.
        For each skill, determine:
        1. Name (e.g. Python, SQL, Git, React)
        2. Category (e.g. Programming, Databases, Tools, Web Development, Computer Science, Design)
        3. Proficiency Level (0 to 100, estimate based on experience, projects, or certifications listed)
        4. Evidence (a short snippet/justification of why they have this skill, referencing a project, certificate, or work experience in the text)

        Your output MUST be a valid JSON array of objects with keys: "skill_name", "category", "level", "evidence".
        Do not output any introductory or concluding text, only the raw JSON.

        Student Text:
        ---
        {text}
        ---
        """
        
        response = model.generate_content(prompt)
        content = response.text.strip()
        
        # Clean markdown code blocks if present
        if content.startswith("```"):
            # strip ```json or ``` and trailing ```
            content = re.sub(r"^```(?:json)?\n", "", content)
            content = re.sub(r"\n```$", "", content)
            content = content.strip()
            
        skills = json.loads(content)
        if isinstance(skills, list):
            return skills
        return []
    except Exception as e:
        print(f"Error extracting skills: {e}")
        return []

def answer_query(user_id: int, query: str, api_key: str = None) -> dict:
    """Retrieves matching chunks and answers the user query using RAG."""
    # 1. Generate query embedding
    q_emb = get_embedding(query, api_key, task_type="retrieval_query")
    
    # 2. Retrieve top-k semantic chunks
    semantic_results = db.vector_search(user_id, q_emb, top_k=5)
    
    # 3. Retrieve keyword chunks as well (hybrid search)
    # Extract keywords (simple split for simplicity)
    keywords = [w.strip(",.?!\"'") for w in query.split() if len(w) > 3]
    keyword_results = []
    for kw in keywords[:3]:  # search up to 3 keywords
        keyword_results.extend(db.keyword_search(user_id, kw))
        
    # Deduplicate and combine (prioritize semantic search)
    seen_ids = set()
    combined_results = []
    
    for c in semantic_results:
        if c["chunk_id"] not in seen_ids:
            seen_ids.add(c["chunk_id"])
            combined_results.append(c)
            
    for c in keyword_results:
        if c["chunk_id"] not in seen_ids:
            seen_ids.add(c["chunk_id"])
            # Give a default score for keyword matches
            c["score"] = 0.5
            combined_results.append(c)
            
    # Sort again by score
    combined_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    top_results = combined_results[:5]
    
    # Check match quality
    # If no results or all scores are extremely low, we say we couldn't find the info
    max_score = top_results[0]["score"] if top_results else 0.0
    
    # Threshold check: If we have an API key and the best match is very weak (< 0.25),
    # we should check if there's any textual relevance. Otherwise fallback.
    # Note: When API key is missing (mock embeddings), scores are based on simple hash matching
    # which might have different values. We'll be a bit more lenient.
    
    sources = []
    context_str = ""
    for r in top_results:
        sources.append({
            "filename": r["filename"],
            "location": r["location"],
            "text": r["text"][:150] + "..."
        })
        context_str += f"\n---\n[Document: {r['filename']}, Location: {r['location']}]\n{r['text']}\n"

    # If no matching content at all
    if not top_results:
        return {
            "answer": "I couldn't find any documents related to your query. Please upload study materials to search or chat about them.",
            "sources": []
        }

    # If we have context, send to Gemini
    if not api_key:
        # Fallback mock answer if no API key
        # Return a message telling them we found the documents, but need an API key to answer.
        matched_filenames = list(set([r["filename"] for r in top_results]))
        doc_list_str = ", ".join(matched_filenames)
        return {
            "answer": f"I found relevant details in your documents ({doc_list_str}), but I need a Gemini API Key to synthesize an answer. Please enter your Gemini API Key in the Settings tab to enable full AI study answers!",
            "sources": sources
        }

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("models/gemini-2.5-flash")
        
        system_prompt = """
        You are "Life Graph AI", a student's personal study assistant.
        Answer the student's question based strictly on the retrieved document context. 
        Follow these rules:
        1. Rely ONLY on the clear facts directly mentioned in the Context. Do not assume or extrapolate.
        2. If the context does not contain the information needed to answer the question, respond EXACTLY with:
           "I couldn't find that information in your uploaded documents."
           Do not try to explain why, just return that exact sentence.
        3. Keep your answers concise, structured, and student-friendly. Use bullet points and bold formatting where appropriate.
        """
        
        prompt = f"""
        {system_prompt}
        
        Context:
        {context_str}
        
        Question:
        {query}
        
        Answer:
        """
        
        response = model.generate_content(prompt)
        answer = response.text.strip()
        
        # Check if model returned a blank or failed to answer
        if not answer:
            answer = "I couldn't find that information in your uploaded documents."
            
        return {
            "answer": answer,
            "sources": sources
        }
    except Exception as e:
        print(f"Error calling RAG LLM: {e}")
        return {
            "answer": f"Error communicating with Gemini: {str(e)}",
            "sources": []
        }

def run_study_tool(user_id: int, tool_type: str, doc_id: int, api_key: str = None) -> str:
    """Runs a study tool: quiz generation, document summary, or concept explanation."""
    doc = db.get_document(user_id, doc_id)
    if not doc:
        return "Document not found."
        
    doc_text = doc["content"]
    if not doc_text.strip():
        return "Document is empty."
        
    # Truncate text if extremely long to fit prompt limits
    max_chars = 30000
    if len(doc_text) > max_chars:
        doc_text = doc_text[:max_chars] + "\n[Text truncated due to size...]"
        
    if not api_key:
        return "A Gemini API Key is required to use study tools. Please configure your key in the Settings tab."
        
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("models/gemini-2.5-flash")
        
        if tool_type == "quiz":
            prompt = f"""
            Create a practice quiz for a student based on the following course material.
            Generate exactly 5 multiple choice questions.
            For each question:
            - Provide the question text.
            - Provide 4 options (A, B, C, D).
            - State the correct option and a brief explanation referencing the text.
            
            Format the quiz beautifully in markdown.
            
            Material:
            ---
            {doc_text}
            """
        elif tool_type == "summary":
            prompt = f"""
            Provide a comprehensive summary of the following document.
            Highlight the key concepts, main topics, and important definitions.
            Use bullet points and bold headers to make it easy for a student to study.
            
            Material:
            ---
            {doc_text}
            """
        elif tool_type == "explain":
            prompt = f"""
            Extract the 5 most complex terms or concepts from this document and explain them in extremely simple terms (e.g. "Explain like I'm 5").
            Use analogies where possible.
            
            Material:
            ---
            {doc_text}
            """
        else:
            return "Unknown study tool type."
            
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Error running study tool: {e}")
        return f"Error executing study tool: {str(e)}"
