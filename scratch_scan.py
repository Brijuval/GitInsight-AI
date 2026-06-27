import json
import os
from gitinsight.scanner import RepoScanner
from gitinsight.indexer import CodeIndexer

def main():
    print("Step 1: Scanning directory structure...")
    scanner = RepoScanner(".")
    scan_results = scanner.scan()
    
    print(f"Scanned {len(scan_results['files'])} files.")
    
    print("\nStep 2: Initializing indexer (mock mode if no key)...")
    # Even if API Key is not set, this will execute in dry-run mode
    indexer = CodeIndexer(".", api_key=os.environ.get("GEMINI_API_KEY"))
    
    print("Step 3: Indexing files...")
    indexed_results = indexer.index_repository(scan_results)
    
    print("\nStats after indexing:")
    stats = indexed_results["stats"]
    print(json.dumps(stats, indent=2))
    
    print("\nSample Indexed File Details:")
    sample_file = "gitinsight/scanner.py"
    if sample_file in indexed_results["files"]:
        meta = indexed_results["files"][sample_file]
        print(f"File: {sample_file}")
        print(f" - Purpose: {meta.get('purpose')}")
        print(f" - Exports: {meta.get('exports')}")
        print(f" - Dependencies: {meta.get('dependencies')}")
        print(f" - Indexed by AI? {meta.get('indexed_by_ai')}")
        
    print("\nVerifying cache.json existence:")
    cache_path = os.path.join(".gitinsight", "cache.json")
    if os.path.exists(cache_path):
        print(f" [SUCCESS] Cache file exists at {cache_path}")
    else:
        print(" [FAILURE] Cache file was not created.")

if __name__ == '__main__':
    main()
