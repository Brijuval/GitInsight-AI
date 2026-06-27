import os
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from gitinsight.scanner import RepoScanner
from gitinsight.indexer import CodeIndexer
from gitinsight.agents.orchestrator import MultiAgentOrchestrator
from gitinsight.agents.actions import CodebaseActions

app = FastAPI(
    title="GitInsight: Autonomous Engineering Agent",
    description="AI-powered Codebase Intelligence Platform & Staff Engineer Agent",
    version="1.0.0"
)

# Enable CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global in-memory state to track the currently scanned directory path
# Defaults to scanning its own project directory
current_state = {
    "repo_path": ".",
    "api_key": os.environ.get("GEMINI_API_KEY", "")
}

# --- Request/Response Schemas ---

class ScanRequest(BaseModel):
    path: str
    api_key: Optional[str] = None

class ChatRequest(BaseModel):
    query: str
    api_key: Optional[str] = None

class ChangeImpactRequest(BaseModel):
    file_path: str
    api_key: Optional[str] = None

class FeaturePlanRequest(BaseModel):
    feature: str
    api_key: Optional[str] = None

class ArchitectureRequest(BaseModel):
    request: str
    api_key: Optional[str] = None

class PRReviewRequest(BaseModel):
    diff: str
    api_key: Optional[str] = None

# --- API Endpoints ---

@app.post("/api/scan")
def scan_repository(request: ScanRequest):
    """Scan and index the repository at the specified path."""
    repo_path = request.path.strip()
    
    # Standardize empty path to current directory
    if not repo_path:
        repo_path = "."
        
    import subprocess
    import shutil
    import stat
    
    def remove_readonly(func, path, excinfo):
        os.chmod(path, stat.S_IWRITE)
        func(path)
        
    is_git_url = repo_path.startswith("http://") or repo_path.startswith("https://") or repo_path.startswith("git@")
    
    if is_git_url:
        # Create a workspace folder for cloned repositories
        clones_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloned_repos")
        if not os.path.exists(clones_dir):
            os.makedirs(clones_dir)
            
        # Generate target directory name based on repo url
        repo_name = repo_path.split("/")[-1].replace(".git", "")
        # Sanitize folder name to be letters and numbers only
        repo_name = "".join([c for c in repo_name if c.isalnum() or c in ("-", "_")])
        target_dir = os.path.join(clones_dir, repo_name)
        
        # Clean up old clones to prevent disk clutter
        for item in os.listdir(clones_dir):
            item_path = os.path.join(clones_dir, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path, onerror=remove_readonly)
            except Exception:
                pass
                
        # If folder still exists (e.g. deletion was locked or failed), reuse it directly
        if os.path.exists(target_dir) and os.path.isdir(target_dir):
            repo_path = target_dir
        else:
            # Programmatic git clone
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", repo_path, target_dir],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                # Override repo_path to our cloned repository folder
                repo_path = target_dir
            except subprocess.CalledProcessError as err:
                error_msg = err.stderr.decode("utf-8", errors="ignore")
                raise HTTPException(
                    status_code=400, 
                    detail=f"Failed to clone remote repository. Check URL validity. Git Error: {error_msg}"
                )

    else:
        if not os.path.exists(repo_path) or not os.path.isdir(repo_path):
            raise HTTPException(status_code=400, detail=f"Directory path '{repo_path}' does not exist or is not a folder.")
        
    current_state["repo_path"] = repo_path

    if request.api_key:
        current_state["api_key"] = request.api_key.strip()
        
    try:
        # 1. Run codebase scanner (structure & imports)
        scanner = RepoScanner(repo_path)
        scan_data = scanner.scan()
        
        # 2. Run indexer (Gemini summarizations & cache.json)
        indexer = CodeIndexer(repo_path, api_key=current_state["api_key"])
        final_data = indexer.index_repository(scan_data)
        
        return {
            "status": "success",
            "message": f"Successfully scanned and indexed {len(final_data['files'])} files.",
            "repo_name": os.path.basename(os.path.abspath(repo_path)) or "root",
            "repo_path": os.path.abspath(repo_path),
            "stats": final_data["stats"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")

@app.get("/api/tree")
def get_directory_tree():
    """Retrieve the nested directory tree structure for the sidebar."""
    repo_path = current_state["repo_path"]
    try:
        scanner = RepoScanner(repo_path)
        result = scanner.scan()
        return result["tree"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch directory tree: {str(e)}")

@app.get("/api/graph")
def get_dependency_graph():
    """Retrieve nodes and edges for rendering the dependency graph visualizer."""
    repo_path = current_state["repo_path"]
    try:
        from gitinsight.tools import RepoTools
        tools = RepoTools(repo_path)
        return tools.get_dependency_graph()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compile dependency graph: {str(e)}")

@app.get("/api/file")
def get_file_details(path: str = Query(..., description="Relative path of file inside repository")):
    """Get the source code content and cached AI metadata of a file."""
    repo_path = current_state["repo_path"]
    
    # Resolve absolute path to verify it remains within repository (security)
    abs_repo = os.path.abspath(repo_path)
    abs_file = os.path.abspath(os.path.join(repo_path, path))
    
    if not abs_file.startswith(abs_repo):
        raise HTTPException(status_code=403, detail="Access denied. Path is outside repository.")
        
    if not os.path.exists(abs_file) or not os.path.isfile(abs_file):
        raise HTTPException(status_code=404, detail=f"File '{path}' not found.")
        
    try:
        # Load content
        with open(abs_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        # Get AI summary from cache
        from gitinsight.tools import RepoTools
        tools = RepoTools(repo_path)
        summary = tools.get_file_summary(path)
        
        return {
            "path": path,
            "name": os.path.basename(path),
            "content": content,
            "metadata": summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")

@app.post("/api/chat")
def chat_with_agent(request: ChatRequest):
    """Query the multi-agent orchestration loop."""
    repo_path = current_state["repo_path"]
    api_key = request.api_key or current_state["api_key"]
    
    try:
        orchestrator = MultiAgentOrchestrator(repo_path, api_key=api_key)
        return orchestrator.run_query(request.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

# --- Agent Action Endpoints ---

@app.post("/api/action/change-impact")
def analyze_change_impact(request: ChangeImpactRequest):
    """Find affected files and evaluate change risks for a modification."""
    repo_path = current_state["repo_path"]
    api_key = request.api_key or current_state["api_key"]
    
    try:
        actions = CodebaseActions(repo_path, api_key=api_key)
        return actions.analyze_change_impact(request.file_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Change impact analysis failed: {str(e)}")

@app.get("/api/action/onboarding")
def get_onboarding_roadmap(api_key: Optional[str] = None):
    """Generate the 30-minute tour and 2-hour deep dive onboarding roadmap."""
    repo_path = current_state["repo_path"]
    active_key = api_key or current_state["api_key"]
    
    try:
        actions = CodebaseActions(repo_path, api_key=active_key)
        roadmap = actions.generate_onboarding_roadmap()
        return {"roadmap": roadmap}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Onboarding generation failed: {str(e)}")

@app.post("/api/action/feature-plan")
def plan_feature_implementation(request: FeaturePlanRequest):
    """Plan files to edit, create, and step-by-step implementations for a new feature."""
    repo_path = current_state["repo_path"]
    api_key = request.api_key or current_state["api_key"]
    
    try:
        actions = CodebaseActions(repo_path, api_key=api_key)
        plan = actions.plan_feature_implementation(request.feature)
        return plan
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Feature planning failed: {str(e)}")

@app.post("/api/action/architecture")
def analyze_architecture_evolution(request: ArchitectureRequest):
    """Analyze imports and structure to suggest modular/microservices migrations."""
    repo_path = current_state["repo_path"]
    api_key = request.api_key or current_state["api_key"]
    
    try:
        actions = CodebaseActions(repo_path, api_key=api_key)
        evolution_report = actions.analyze_architecture_evolution(request.request)
        return {"report": evolution_report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Architecture analysis failed: {str(e)}")

@app.post("/api/action/pr-review")
def review_pull_request(request: PRReviewRequest):
    """Automate Pull Request review on a pasted git diff."""
    repo_path = current_state["repo_path"]
    api_key = request.api_key or current_state["api_key"]
    
    try:
        actions = CodebaseActions(repo_path, api_key=api_key)
        review = actions.review_pull_request(request.diff)
        return review
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PR review failed: {str(e)}")

# --- Serve Static UI Files ---

# Create static folder if it doesn't exist
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

# Serve the static UI files at root (e.g. index.html)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
