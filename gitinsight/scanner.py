import os
import re
import ast
from pathlib import Path
from typing import Dict, List, Set, Any, Tuple

# List of directory names to ignore
DEFAULT_IGNORED_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", ".env",
    "__pycache__", ".gitinsight", ".pytest_cache", ".idea", 
    ".vscode", "dist", "build", "target", "out", "venv-coc",
    "eggs", "parts", "bin", "develop-eggs", "sdist", "var",
    "htmlcov", ".tox", ".noscript", ".github"
}

# List of extensions to ignore (binaries, images, etc.)
DEFAULT_IGNORED_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".zip", ".tar", ".gz", ".rar", ".7z", ".pdf", ".mp4", ".mp3",
    ".wav", ".avi", ".mov", ".db", ".sqlite", ".pyc", ".woff",
    ".woff2", ".ttf", ".eot", ".exe", ".dll", ".so", ".dylib"
}

# Mapping of file extensions to programming languages
EXTENSION_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "React JS",
    ".ts": "TypeScript",
    ".tsx": "React TS",
    ".html": "HTML",
    ".css": "CSS",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
    ".txt": "Text",
    ".sh": "Shell Script",
    ".bat": "Batch Script",
    ".ps1": "PowerShell Script"
}

def is_ignored(path: Path, root_dir: Path) -> bool:
    """Check if the path or any of its parent directories/extensions should be ignored."""
    try:
        # Resolve relative to root_dir to check parents properly
        rel_path = path.relative_to(root_dir)
    except ValueError:
        rel_path = path

    # Check components
    for part in rel_path.parts:
        if part in DEFAULT_IGNORED_DIRS:
            return True
        if part.startswith('.'):
            # Ignore hidden files/dirs, except standard config files if needed
            # We allow files like .env.example or configuration files if they are in the root
            if part not in (".env.example", ".gitignore", ".env"):
                return True

    # Check extension
    if path.is_file() and path.suffix.lower() in DEFAULT_IGNORED_EXTS:
        return True

    return False

def extract_python_imports(content: str) -> List[str]:
    """Parse Python code using AST to find all import and from-import statements."""
    imports = []
    try:
        root = ast.parse(content)
        for node in ast.walk(root):
            if isinstance(node, ast.Import):
                for name in node.names:
                    imports.append(name.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
    except SyntaxError:
        # Fall back to regex if file has syntax errors
        imports.extend(extract_js_imports(content))  # regex is generic
    return list(set(imports))

def extract_js_imports(content: str) -> List[str]:
    """Parse JS/TS files using regex to locate import and require statements."""
    imports = []
    
    # ES6 imports: import foo from 'bar' or import 'bar'
    es6_pattern = re.compile(r'(?:import\s+(?:[\w\s{},*]*\s+from\s+)?[\'"]([^\'"]+)[\'"])')
    # CommonJS require: const foo = require('bar')
    require_pattern = re.compile(r'require\([\'"]([^\'"]+)[\'"]\)')
    # Dynamic imports: import('bar')
    dynamic_pattern = re.compile(r'import\([\'"]([^\'"]+)[\'"]\)')

    for match in es6_pattern.finditer(content):
        imports.append(match.group(1))
    for match in require_pattern.finditer(content):
        imports.append(match.group(1))
    for match in dynamic_pattern.finditer(content):
        imports.append(match.group(1))

    return list(set(imports))

def resolve_import_path(current_file_path: Path, import_str: str, root_dir: Path, all_files: Set[Path]) -> str:
    """Resolve an import string to a relative path in the repo, returning empty string if it's external."""
    # Strip leading/trailing quotes and clean up
    import_str = import_str.strip()
    
    # Handle Python imports (e.g. "gitinsight.scanner" or ".scanner")
    if current_file_path.suffix == ".py":
        # Check relative imports
        if import_str.startswith('.'):
            # Check how many dots
            dots = len(import_str) - len(import_str.lstrip('.'))
            module_parts = import_str.lstrip('.').split('.')
            
            parent = current_file_path.parent
            for _ in range(dots - 1):
                if parent != root_dir:
                    parent = parent.parent
            
            # Form potential paths
            path_attempt = parent.joinpath(*module_parts)
        else:
            # Absolute python import relative to root or system paths
            parts = import_str.split('.')
            path_attempt = root_dir.joinpath(*parts)

        # Try to resolve to file or folder init
        for ext in ['.py', '/__init__.py']:
            resolved = path_attempt.with_name(path_attempt.name + ext) if not ext.startswith('/') else path_attempt.joinpath('__init__.py')
            if resolved.exists() and resolved.is_file():
                try:
                    return str(resolved.relative_to(root_dir).as_posix())
                except ValueError:
                    pass
        
        # Check standard file directory match
        resolved = path_attempt.with_suffix('.py')
        if resolved.exists() and resolved.is_file():
            try:
                return str(resolved.relative_to(root_dir).as_posix())
            except ValueError:
                pass

    # Handle JS/TS imports (e.g. "./utils", "../components/Button")
    elif current_file_path.suffix in [".js", ".jsx", ".ts", ".tsx"]:
        if import_str.startswith('.'):
            # Relative import
            path_attempt = current_file_path.parent.joinpath(import_str).resolve()
        else:
            # Absolute module import (often external library, but check if relative to root)
            path_attempt = root_dir.joinpath(import_str).resolve()

        # Try mapping to files with extensions
        for ext in ['.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.tsx', '/index.js', '/index.jsx']:
            resolved = path_attempt.with_name(path_attempt.name + ext) if not ext.startswith('/') else path_attempt.joinpath(ext.lstrip('/'))
            if resolved.exists() and resolved.is_file():
                try:
                    return str(resolved.relative_to(root_dir).as_posix())
                except ValueError:
                    pass
                
    return ""  # Cannot resolve, likely third-party library or system module

def get_file_info(file_path: Path, root_dir: Path) -> Dict[str, Any]:
    """Retrieve file metadata: size, line count, language."""
    stat = file_path.stat()
    rel_path = file_path.relative_to(root_dir).as_posix()
    
    # Estimate line count
    lines = 0
    content = ""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            lines = content.count('\n') + 1
    except Exception:
        pass
        
    ext = file_path.suffix.lower()
    language = EXTENSION_MAP.get(ext, "Unknown")
    
    return {
        "path": rel_path,
        "name": file_path.name,
        "size": stat.st_size,
        "lines": lines,
        "language": language,
        "content": content
    }

class RepoScanner:
    def __init__(self, root_dir_path: str):
        self.root_dir = Path(root_dir_path).resolve()
        
    def scan(self) -> Dict[str, Any]:
        """Perform recursive traversal of repository and return dependency structure."""
        if not self.root_dir.exists() or not self.root_dir.is_dir():
            raise FileNotFoundError(f"Path {self.root_dir} is not a valid directory.")
            
        all_files_paths: List[Path] = []
        all_files_set: Set[Path] = set()
        
        # Traverse repository
        for root, dirs, files in os.walk(self.root_dir):
            root_path = Path(root)
            
            # Prune directories in place to prevent os.walk from entering ignored paths
            dirs[:] = [d for d in dirs if not is_ignored(root_path / d, self.root_dir)]
            
            for file in files:
                file_path = root_path / file
                if not is_ignored(file_path, self.root_dir):
                    all_files_paths.append(file_path)
                    all_files_set.add(file_path)
                    
        # Extract metadata and raw imports
        file_metadata_map: Dict[str, Dict[str, Any]] = {}
        for fp in all_files_paths:
            info = get_file_info(fp, self.root_dir)
            file_metadata_map[info["path"]] = info
            
        # Build dependency graph
        dependencies: List[Dict[str, Any]] = []
        for rel_path, info in file_metadata_map.items():
            content = info.pop("content")  # Remove content from metadata to keep JSON small
            suffix = Path(rel_path).suffix.lower()
            imports = []
            
            if suffix == ".py":
                imports = extract_python_imports(content)
            elif suffix in [".js", ".jsx", ".ts", ".tsx"]:
                imports = extract_js_imports(content)
                
            resolved_deps = []
            for imp in imports:
                resolved = resolve_import_path(self.root_dir / rel_path, imp, self.root_dir, all_files_set)
                if resolved and resolved != rel_path:
                    resolved_deps.append(resolved)
                    
            if resolved_deps:
                dependencies.append({
                    "source": rel_path,
                    "targets": list(set(resolved_deps))
                })
                
        # Build directory tree node-link structure
        tree = self._build_tree(file_metadata_map)
        
        return {
            "root_path": self.root_dir.as_posix(),
            "files": file_metadata_map,
            "dependencies": dependencies,
            "tree": tree
        }
        
    def _build_tree(self, file_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Convert a flat list of files into a nested tree structure for folder tree view."""
        tree = {"name": self.root_dir.name, "type": "directory", "path": "", "children": []}
        
        for rel_path in sorted(file_map.keys()):
            parts = rel_path.split('/')
            current = tree
            
            for i, part in enumerate(parts):
                is_file = (i == len(parts) - 1)
                path_so_far = "/".join(parts[:i+1])
                
                # Check if children already has this part
                found = None
                for child in current["children"]:
                    if child["name"] == part:
                        found = child
                        break
                        
                if not found:
                    new_node = {
                        "name": part,
                        "path": path_so_far,
                        "type": "file" if is_file else "directory"
                    }
                    if not is_file:
                        new_node["children"] = []
                    else:
                        metadata = file_map[rel_path]
                        new_node["size"] = metadata["size"]
                        new_node["lines"] = metadata["lines"]
                        new_node["language"] = metadata["language"]
                        
                    current["children"].append(new_node)
                    found = new_node
                    
                current = found
                
        # Sort children: directories first, then alphabetically
        self._sort_tree(tree)
        return tree

    def _sort_tree(self, node: Dict[str, Any]):
        if "children" in node:
            # Sort directories first, then files
            node["children"].sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
            for child in node["children"]:
                self._sort_tree(child)
