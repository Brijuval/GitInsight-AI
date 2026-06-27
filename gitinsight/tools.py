import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

class RepoTools:
    def __init__(self, root_dir_path: str):
        self.root_dir = Path(root_dir_path).resolve()
        
    def list_dir(self, sub_path: str = "") -> List[Dict[str, Any]]:
        """List files and folders in a subdirectory, relative to the repository root."""
        target_dir = (self.root_dir / sub_path).resolve()
        
        # Security: Prevent traversing outside the repo root
        if not str(target_dir).startswith(str(self.root_dir)):
            target_dir = self.root_dir
            
        if not target_dir.exists() or not target_dir.is_dir():
            return []
            
        contents = []
        # Import list of ignored dirs to skip
        from gitinsight.scanner import is_ignored
        
        for item in target_dir.iterdir():
            if is_ignored(item, self.root_dir):
                continue
                
            rel_path = item.relative_to(self.root_dir).as_posix()
            contents.append({
                "name": item.name,
                "path": rel_path,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None
            })
            
        # Sort directories first, then alphabetically
        contents.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
        return contents

    def view_file_content(self, file_path: str) -> str:
        """Read the full content of a specific file inside the repository."""
        target_file = (self.root_dir / file_path).resolve()
        
        # Security check
        if not str(target_file).startswith(str(self.root_dir)):
            return "Error: Access Denied. Cannot read files outside repository."
            
        if not target_file.exists() or not target_file.is_file():
            return f"Error: File '{file_path}' does not exist."
            
        try:
            with open(target_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            return content
        except Exception as e:
            return f"Error reading file: {str(e)}"

    def search_code(self, query: str) -> List[Dict[str, Any]]:
        """Search for a text query inside all scanned files, returning matching lines and files."""
        results = []
        query_lower = query.lower()
        
        # We can read from our scanner's list of files using cache.json
        cache_path = self.root_dir / ".gitinsight" / "cache.json"
        if not cache_path.exists():
            return []
            
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            files = cache_data.get("files", {})
        except Exception:
            return []
            
        for rel_path in files.keys():
            full_path = self.root_dir / rel_path
            if not full_path.exists() or not full_path.is_file():
                continue
                
            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                    
                matches = []
                for line_idx, line in enumerate(lines):
                    if query_lower in line.lower():
                        matches.append({
                            "line_number": line_idx + 1,
                            "content": line.strip()
                        })
                        if len(matches) >= 10:  # Cap matches per file to keep response small
                            break
                            
                if matches:
                    results.append({
                        "file": rel_path,
                        "matches": matches
                    })
            except Exception:
                pass
                
        return results

    def get_dependency_graph(self) -> Dict[str, Any]:
        """Retrieve the import dependency graph nodes and edges from the cache."""
        cache_path = self.root_dir / ".gitinsight" / "cache.json"
        if not cache_path.exists():
            return {"nodes": [], "edges": []}
            
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                
            # Scan repo files directly for dependencies using the scanner to make sure it's up to date
            from gitinsight.scanner import RepoScanner
            scan_data = RepoScanner(str(self.root_dir)).scan()
            
            nodes = []
            edges = []
            
            for path, meta in scan_data.get("files", {}).items():
                nodes.append({
                    "id": path,
                    "label": path.split('/')[-1],
                    "group": path.split('/')[0] if '/' in path else "root",
                    "title": meta.get("purpose", "")
                })
                
            for dep in scan_data.get("dependencies", []):
                source = dep["source"]
                for target in dep["targets"]:
                    edges.append({
                        "from": source,
                        "to": target
                    })
                    
            return {"nodes": nodes, "edges": edges}
        except Exception as e:
            return {"error": str(e)}

    def get_file_summary(self, file_path: str) -> Dict[str, Any]:
        """Get the cached AI summary, exports, and dependencies for a file."""
        cache_path = self.root_dir / ".gitinsight" / "cache.json"
        if not cache_path.exists():
            return {"error": "Index cache does not exist. Scan the repository first."}
            
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                
            file_meta = cache_data.get("files", {}).get(file_path)
            if file_meta:
                return {
                    "path": file_path,
                    "purpose": file_meta.get("purpose", ""),
                    "exports": file_meta.get("exports", []),
                    "dependencies": file_meta.get("dependencies", [])
                }
        except Exception as e:
            pass
            
        return {"error": f"Metadata for file '{file_path}' not found."}
