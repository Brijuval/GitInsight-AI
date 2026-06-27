import os
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from google.genai.errors import APIError

# Gemini pricing constants for Gemini 2.5 Flash / Gemini 2.0 Flash
PRICE_PER_M_INPUT = 0.075   # $0.075 per 1 Million tokens
PRICE_PER_M_OUTPUT = 0.300  # $0.30 per 1 Million tokens

class FileSummary(BaseModel):
    purpose: str = Field(description="A concise 1-2 sentence explanation of what this file does in the system.")
    exports: List[str] = Field(description="A list of major classes, functions, modules, or API endpoints exported by this file.")
    dependencies: List[str] = Field(description="A list of external, third-party libraries or internal local imports used in this file.")

def compute_hash(content: str) -> str:
    """Compute MD5 hash of file content to detect modifications."""
    return hashlib.md5(content.encode('utf-8', errors='ignore')).hexdigest()

class CodeIndexer:
    def __init__(self, root_dir_path: str, api_key: Optional[str] = None):
        self.root_dir = Path(root_dir_path).resolve()
        self.cache_dir = self.root_dir / ".gitinsight"
        self.cache_file = self.cache_dir / "cache.json"
        
        # Load API Key: precedence UI Input > .env / Env var
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.client = None
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
            
        self.cache_data = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        """Load cache file or initialize new cache skeleton."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Check for basic fields
                    if "files" not in data:
                        data["files"] = {}
                    if "stats" not in data:
                        data["stats"] = {
                            "total_prompt_tokens": 0,
                            "total_candidate_tokens": 0,
                            "total_estimated_cost": 0.0,
                            "files_cached_count": 0
                        }
                    return data
            except Exception:
                pass
                
        return {
            "files": {},
            "stats": {
                "total_prompt_tokens": 0,
                "total_candidate_tokens": 0,
                "total_estimated_cost": 0.0,
                "files_cached_count": 0
            }
        }

    def save_cache(self):
        """Persist cache JSON to disk."""
        self.cache_dir.mkdir(exist_ok=True)
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache_data, f, indent=2)

    def calculate_cost(self, prompt_tokens: int, candidate_tokens: int) -> float:
        """Calculate USD cost of API calls based on token usage."""
        input_cost = (prompt_tokens / 1_000_000) * PRICE_PER_M_INPUT
        output_cost = (candidate_tokens / 1_000_000) * PRICE_PER_M_OUTPUT
        return input_cost + output_cost

    def index_file(self, rel_path: str, content: str) -> Dict[str, Any]:
        """Summarize a single file using Gemini structured outputs."""
        file_hash = compute_hash(content)
        
        # Check cache hit
        cached = self.cache_data["files"].get(rel_path)
        if cached and cached.get("hash") == file_hash:
            return cached

        # If cache miss, index using Gemini (or fallback if no client)
        if not self.client:
            # Fallback mock summary for offline or missing API Key mode
            filename = Path(rel_path).name
            mock_summary = {
                "hash": file_hash,
                "purpose": f"Local code file '{filename}' scanned successfully. Add GEMINI_API_KEY to generate an AI summary.",
                "exports": [f"(Inferred) {filename}"],
                "dependencies": [],
                "tokens_used": {"prompt": 0, "candidates": 0, "cost": 0.0},
                "indexed_by_ai": False
            }
            self.cache_data["files"][rel_path] = mock_summary
            return mock_summary

        # call Gemini
        system_instruction = (
            "You are an expert code analyst. Analyze the provided file content and extract its purpose, "
            "exported code interfaces (classes, functions, major constants, or route endpoints), "
            "and external or internal libraries imported. Respond strictly in the requested JSON structure."
        )
        
        prompt = f"Analyze the following code from file '{rel_path}':\n\n```\n{content}\n```"
        
        try:
            # Using Gemini 2.5 Flash for fast, cost-effective code analysis
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=FileSummary,
                    system_instruction=system_instruction,
                    temperature=0.1
                )
            )
            
            # Parse structured JSON response
            result_data = json.loads(response.text)
            
            # Fetch token usage metrics
            prompt_tokens = 0
            candidate_tokens = 0
            cost = 0.0
            
            if response.usage_metadata:
                prompt_tokens = response.usage_metadata.prompt_token_count
                candidate_tokens = response.usage_metadata.candidates_token_count
                cost = self.calculate_cost(prompt_tokens, candidate_tokens)
                
                # Accumulate global stats
                self.cache_data["stats"]["total_prompt_tokens"] += prompt_tokens
                self.cache_data["stats"]["total_candidate_tokens"] += candidate_tokens
                self.cache_data["stats"]["total_estimated_cost"] += cost
            
            summary = {
                "hash": file_hash,
                "purpose": result_data.get("purpose", ""),
                "exports": result_data.get("exports", []),
                "dependencies": result_data.get("dependencies", []),
                "tokens_used": {
                    "prompt": prompt_tokens,
                    "candidates": candidate_tokens,
                    "cost": cost
                },
                "indexed_by_ai": True
            }
            
            # Cache the summary
            self.cache_data["files"][rel_path] = summary
            return summary
            
        except Exception as e:
            # Gracefully handle API errors and return temporary summary
            print(f"Error indexing {rel_path} with Gemini: {str(e)}")
            return {
                "hash": file_hash,
                "purpose": f"Error during AI analysis: {str(e)}",
                "exports": [],
                "dependencies": [],
                "tokens_used": {"prompt": 0, "candidates": 0, "cost": 0.0},
                "indexed_by_ai": False
            }

    def index_repository(self, scanned_repo_data: Dict[str, Any], progress_callback=None) -> Dict[str, Any]:
        """Index all files in the scanned data, updating the cache."""
        files_map = scanned_repo_data["files"]
        indexed_count = 0
        cached_count = 0
        total_files = len(files_map)
        
        for idx, (rel_path, meta) in enumerate(files_map.items()):
            # Read current content to index
            full_path = self.root_dir / rel_path
            content = ""
            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except Exception:
                pass
                
            # Perform indexing
            summary = self.index_file(rel_path, content)
            
            if summary.get("indexed_by_ai", False) and summary.get("tokens_used", {}).get("prompt", 0) > 0:
                indexed_count += 1
            else:
                cached_count += 1
                
            # Report progress if callback is provided
            if progress_callback:
                progress_callback(idx + 1, total_files, rel_path)
                
        # Update cache counts
        self.cache_data["stats"]["files_cached_count"] = cached_count
        self.save_cache()
        
        # Merge AI summaries back into scanned repo files data
        for rel_path, meta in files_map.items():
            cached_sum = self.cache_data["files"].get(rel_path)
            if cached_sum:
                meta["purpose"] = cached_sum["purpose"]
                meta["exports"] = cached_sum["exports"]
                meta["dependencies"] = cached_sum["dependencies"]
                meta["indexed_by_ai"] = cached_sum.get("indexed_by_ai", False)
                meta["cost"] = cached_sum.get("tokens_used", {}).get("cost", 0.0)
                
        # Include cost stats in output
        scanned_repo_data["stats"] = self.cache_data["stats"]
        scanned_repo_data["stats"]["files_indexed_new_count"] = indexed_count
        scanned_repo_data["stats"]["files_total_count"] = total_files
        
        return scanned_repo_data
