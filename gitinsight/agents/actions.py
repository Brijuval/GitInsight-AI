import os
import json
import networkx as nx
from pathlib import Path
from typing import Dict, List, Any, Optional
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from gitinsight.scanner import RepoScanner

class FeaturePlanSchema(BaseModel):
    files_to_modify: List[str] = Field(description="Existing codebase files that must be modified.")
    new_files: List[str] = Field(description="New files that should be created.")
    steps: List[str] = Field(description="Sequential step-by-step implementation tasks.")
    explanation: str = Field(description="A brief explanation of the technical approach, architecture, and design decisions.")

class PRReviewSchema(BaseModel):
    risks: List[str] = Field(description="Potential breaking changes, architectural inconsistencies, or runtime risks.")
    security: List[str] = Field(description="Security concerns like missing sanitization, secret exposure, or vulnerable logic.")
    improvements: List[str] = Field(description="Clean code suggestions, performance improvements, or style compliance.")
    review_text: str = Field(description="A written summary of the code changes, overall health rating, and suggestions.")


class CodebaseActions:
    def __init__(self, root_dir_path: str, api_key: Optional[str] = None):
        self.root_dir = Path(root_dir_path).resolve()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        
        self.client = None
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)

    def analyze_change_impact(self, modified_file: str) -> Dict[str, Any]:
        """Perform deterministic dependency-graph analysis to find affected files, and assess risk using Gemini."""
        # 1. Scan repo to get dependencies
        scanner = RepoScanner(str(self.root_dir))
        scan_data = scanner.scan()
        
        dependencies = scan_data.get("dependencies", [])
        files_meta = scan_data.get("files", {})
        
        # Standardize path
        modified_file = modified_file.replace("\\", "/").strip("/")
        
        # 2. Build networkx graph
        # In scanner: source imports targets. This means source depends on targets.
        # If a target changes, the source is affected.
        # Therefore, we draw directed edges: target -> source.
        G = nx.DiGraph()
        
        # Add all files as nodes
        for f in files_meta.keys():
            G.add_node(f)
            
        for dep in dependencies:
            source = dep["source"]
            for target in dep["targets"]:
                G.add_edge(target, source)
                
        if not G.has_node(modified_file):
            return {
                "file": modified_file,
                "affected_files": [],
                "risk_level": "Low",
                "reasoning": f"The file '{modified_file}' was not found in the scanned codebase or has no dependencies."
            }
            
        # 3. Find affected files (descendants in target -> source graph)
        affected = list(nx.descendants(G, modified_file))
        
        # Find direct consumers for clarification
        direct_consumers = [edge[1] for edge in G.out_edges(modified_file)]
        
        # If no files affected, risk is Low
        if not affected:
            return {
                "file": modified_file,
                "affected_files": [],
                "risk_level": "Low",
                "reasoning": f"No other files in the codebase import '{modified_file}'. You can modify it safely."
            }
            
        # 4. Use Gemini to write the reasoning & risk
        if not self.client:
            # Fallback reasoning
            return {
                "file": modified_file,
                "affected_files": affected,
                "risk_level": "High" if len(affected) > 3 else "Medium",
                "reasoning": (
                    f"Offline Mode: Detemined that {len(affected)} files import '{modified_file}' directly or indirectly. "
                    f"Direct consumers: {direct_consumers}. Add GEMINI_API_KEY for a detailed risk report."
                )
            }
            
        # Compile short context of what the affected files do from cache
        file_contexts = []
        cache_path = self.root_dir / ".gitinsight" / "cache.json"
        cache_files = {}
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_files = json.load(f).get("files", {})
            except Exception:
                pass
                
        for aff in affected[:10]:  # Limit context size
            purpose = cache_files.get(aff, {}).get("purpose", "Unknown purpose")
            file_contexts.append(f"- `{aff}`: {purpose}")
            
        context_str = "\n".join(file_contexts)
        
        prompt = (
            f"You are a Staff Software Engineer analyzing code risk.\n"
            f"A developer wants to modify the file `{modified_file}`.\n"
            f"Our AST dependency analysis shows that the following files import `{modified_file}` and may break:\n"
            f"{context_str}\n\n"
            f"Please assess the Risk Level (choose exactly: High, Medium, or Low) and write a detailed engineering explanation "
            f"covering what features these affected files control and what precautions the developer should take before modifying `{modified_file}`."
        )
        
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2
                )
            )
            
            # Simple text parsing for risk level
            text = response.text
            risk = "Medium"
            if "high" in text.lower()[:200]:
                risk = "High"
            elif "low" in text.lower()[:200]:
                risk = "Low"
                
            return {
                "file": modified_file,
                "affected_files": affected,
                "risk_level": risk,
                "reasoning": text
            }
        except Exception as e:
            return {
                "file": modified_file,
                "affected_files": affected,
                "risk_level": "High",
                "reasoning": f"Error running risk evaluation: {str(e)}"
            }

    def generate_onboarding_roadmap(self) -> str:
        """Create a custom '30-Minute Tour' and '2-Hour Deep Dive' roadmap for the repository."""
        # 1. Read files and cache
        cache_path = self.root_dir / ".gitinsight" / "cache.json"
        if not cache_path.exists():
            return "Please scan the repository first to index the codebase."
            
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            files = cache_data.get("files", {})
        except Exception as e:
            return f"Error loading index: {str(e)}"
            
        if not files:
            return "No files indexed. Please scan a non-empty repository."
            
        # 2. Compile file index summaries for the prompt
        code_overview = []
        for rel_path, meta in list(files.items())[:25]:  # Limit to top 25 files to fit in prompts cleanly
            code_overview.append(f"- File: `{rel_path}`\n  Purpose: {meta.get('purpose')}\n  Exports: {meta.get('exports')}")
            
        overview_str = "\n".join(code_overview)
        
        if not self.client:
            return (
                "### Onboarding Roadmap (Offline Mode)\n\n"
                "**30-Minute Tour:**\n"
                "1. Read `README.md` (if available) to understand project goals.\n"
                "2. Look at the root-level configuration files.\n"
                "3. Scan the core scripts or modules in the folder.\n\n"
                "**2-Hour Deep Dive:**\n"
                "1. Study the relationship between modules.\n"
                "2. Inspect specific classes and method exports.\n\n"
                "*Add a GEMINI_API_KEY to generate a bespoke roadmap matching this exact repository.*"
            )
            
        prompt = (
            f"You are a Senior Principal Engineer onboarding a new developer to this repository.\n"
            f"Here is a summary of the files in the codebase:\n\n"
            f"{overview_str}\n\n"
            f"Please generate a structured, highly specific onboarding roadmap matching this codebase. "
            f"Include two distinct sections:\n"
            f"1. **30-Minute Tour**: A step-by-step walkthrough of entry points, configurations, routing, "
            f"and authentication. Tell them exactly which files to read first and in what order.\n"
            f"2. **2-Hour Deep Dive**: Explain the architecture pattern, data models, logic separation (services, utils), "
            f"and deployment/testing setups. Highlight where the core algorithms or operations reside."
        )
        
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2
                )
            )
            return response.text
        except Exception as e:
            return f"Error generating onboarding roadmap: {str(e)}"

    def plan_feature_implementation(self, feature_description: str) -> Dict[str, Any]:
        """Generate a structured plan of files to modify, new files to write, and step-by-step edits."""
        # 1. Load cache files
        cache_path = self.root_dir / ".gitinsight" / "cache.json"
        files_context = ""
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_files = json.load(f).get("files", {})
                
                # Format files context
                context_list = []
                for path, meta in list(cache_files.items())[:30]:
                    context_list.append(f"File: `{path}`\nPurpose: {meta.get('purpose')}\nExports: {meta.get('exports')}")
                files_context = "\n\n".join(context_list)
            except Exception:
                pass
                
        if not self.client:
            return {
                "files_to_modify": ["main.py"],
                "new_files": ["new_module.py"],
                "steps": [
                    "Create new_module.py and define the core features.",
                    "Import new_module in main.py.",
                    "Set up the API endpoint or CLI interface."
                ],
                "explanation": "Offline Mode: Add GEMINI_API_KEY to generate a detailed implementation plan."
            }

        # Using module-level FeaturePlanSchema


        prompt = (
            f"You are an AI Software Architect.\n"
            f"Here is a summary of the current codebase files:\n\n"
            f"{files_context}\n\n"
            f"The user wants to implement this new feature: \"{feature_description}\".\n\n"
            f"Based on the files available, design an implementation plan. Identify which existing files need "
            f"to be edited, which new files should be created, and write an actionable step-by-step instruction checklist."
        )

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=FeaturePlanSchema,
                    temperature=0.2
                )
            )
            return json.loads(response.text)
        except Exception as e:
            return {
                "files_to_modify": [],
                "new_files": [],
                "steps": [],
                "explanation": f"Error generating feature plan: {str(e)}"
            }

    def analyze_architecture_evolution(self, request: str) -> str:
        """Suggest architectural migration steps, code cleanups, or refactoring designs."""
        cache_path = self.root_dir / ".gitinsight" / "cache.json"
        files_context = ""
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_files = json.load(f).get("files", {})
                
                # Format files context
                context_list = []
                for path, meta in list(cache_files.items())[:30]:
                    context_list.append(f"File: `{path}`\nPurpose: {meta.get('purpose')}\nDependencies: {meta.get('dependencies')}")
                files_context = "\n\n".join(context_list)
            except Exception:
                pass
                
        if not self.client:
            return (
                "### Architecture Evolution (Offline Mode)\n\n"
                "Please add a `GEMINI_API_KEY` to run the Architecture Evolution agent on this codebase. "
                "The agent can help plan migrations (e.g., monolith to microservices, framework upgrades, database switches) "
                "by analyzing imports and folder structures."
            )
            
        prompt = (
            f"You are a Principal Software Architect.\n"
            f"Here is a summary of the current codebase:\n\n"
            f"{files_context}\n\n"
            f"The user has the following refactoring/evolution request: \"{request}\".\n\n"
            f"Please analyze the codebase layout and provide a detailed Architectural Evolution Report. "
            f"Outline the current architecture state, the proposed target architecture, "
            f"the list of decoupled services or modular boundaries, and a step-by-step migration sequence."
        )
        
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2
                )
            )
            return response.text
        except Exception as e:
            return f"Error analyzing architecture evolution: {str(e)}"

    def review_pull_request(self, diff_content: str) -> Dict[str, Any]:
        """Perform automated code review on a git diff, identifying security, risk, and refactoring items."""
        if not self.client:
            return {
                "risks": ["Breaking API changes may occur (Offline evaluation)."],
                "security": ["Input validation check skipped in offline mode."],
                "improvements": ["Refactor complex conditionals."],
                "review_text": "Offline Mode: Please add a GEMINI_API_KEY to run the Pull Request Review Agent."
            }

        # Using module-level PRReviewSchema


        prompt = (
            f"You are an Elite Code Reviewer.\n"
            f"Review the following Pull Request Git Diff:\n\n"
            f"```diff\n{diff_content}\n```\n\n"
            f"Analyze the diff thoroughly and identify potential risks, security vulnerabilities, "
            f"code style improvements, and write a summary review."
        )

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=PRReviewSchema,
                    temperature=0.1
                )
            )
            return json.loads(response.text)
        except Exception as e:
            return {
                "risks": [],
                "security": [],
                "improvements": [],
                "review_text": f"Error running PR review: {str(e)}"
            }
