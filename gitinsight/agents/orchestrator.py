import os
import json
from typing import Dict, List, Any, Optional
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel, Field

from gitinsight.tools import RepoTools
from gitinsight.indexer import PRICE_PER_M_INPUT, PRICE_PER_M_OUTPUT

# Define Pydantic schema for Planner output
class Task(BaseModel):
    task_description: str = Field(description="Description of what to look for or analyze.")
    tool_to_use: str = Field(description="Name of the tool to use: list_dir, view_file_content, search_code, get_dependency_graph, or get_file_summary.")
    target_argument: str = Field(description="The path, search query, or empty string to pass to the tool.")

class InvestigationPlan(BaseModel):
    rationale: str = Field(description="Brief explanation of why this plan was chosen to answer the query.")
    steps: List[Task] = Field(description="List of step-by-step tasks to perform in order.")

class MultiAgentOrchestrator:
    def __init__(self, root_dir_path: str, api_key: Optional[str] = None):
        self.root_dir = root_dir_path
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.tools = RepoTools(root_dir_path)
        
        self.client = None
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)

    def run_query(self, user_query: str) -> Dict[str, Any]:
        """Execute the multi-agent orchestration loop: Plan -> Investigate -> Answer."""
        logs = []
        
        # If API key is missing, return a graceful dry-run response
        if not self.client:
            logs.append({"agent": "System", "action": "Fallback", "message": "GEMINI_API_KEY is missing. Operating in offline/mock mode."})
            return {
                "answer": (
                    "### Offline Mode (Mock Response)\n\n"
                    "It looks like no `GEMINI_API_KEY` was provided. Here is a simulated response:\n"
                    f"You asked: **\"{user_query}\"**\n\n"
                    "To enable the full multi-agent search (Planner, Investigator, Answerer) and query your code, "
                    "please add your Gemini API Key in the top-right settings panel or in a `.env` file."
                ),
                "plan": {
                    "rationale": "Mock planner generated offline tasks.",
                    "steps": [
                        {"task_description": "Search code for relevant keywords", "tool_to_use": "search_code", "target_argument": user_query},
                        {"task_description": "Inspect repository layout", "tool_to_use": "list_dir", "target_argument": ""}
                    ]
                },
                "tool_calls": [
                    {"tool": "search_code", "argument": user_query, "result": "Mock results (Set API Key)"}
                ],
                "logs": logs
            }

        # --- STEP 1: PLANNER AGENT ---
        logs.append({"agent": "Planner", "action": "Formulating Plan", "message": "Analyzing request to devise search strategy..."})
        try:
            planner_instruction = (
                "You are a Software Engineering Planner. Analyze the user's codebase query and break it down "
                "into a logical sequence of investigation tasks. You have tools: list_dir, view_file_content, "
                "search_code, get_dependency_graph, and get_file_summary. Output your plan strictly matching the schema."
            )
            
            planner_prompt = (
                f"User Query: \"{user_query}\"\n\n"
                "Create a step-by-step investigation plan. Limit the plan to a maximum of 4 logical steps. "
                "Specify which tool and argument (e.g., file path or search term) to use for each step."
            )
            
            planner_response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=planner_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=InvestigationPlan,
                    system_instruction=planner_instruction,
                    temperature=0.1
                )
            )
            
            plan_data = json.loads(planner_response.text)
            logs.append({"agent": "Planner", "action": "Plan Generated", "message": plan_data.get("rationale", "")})
        except Exception as e:
            # Fallback plan if planner fails
            plan_data = {
                "rationale": f"Standard search fallback due to planning exception: {str(e)}",
                "steps": [
                    {"task_description": "Search code for keywords", "tool_to_use": "search_code", "target_argument": user_query}
                ]
            }
            logs.append({"agent": "Planner", "action": "Error / Fallback", "message": str(e)})

        # --- STEP 2: INVESTIGATOR AGENT ---
        logs.append({"agent": "Investigator", "action": "Executing Tools", "message": "Interacting with codebase tools to gather context..."})
        tool_calls_executed = []
        investigation_context = []
        
        # Define local functions for Gemini tool-use
        # We define them inline or bind them so the SDK can serialize them
        def list_directory(sub_path: str = "") -> str:
            res = self.tools.list_dir(sub_path)
            return json.dumps(res)

        def view_file(file_path: str) -> str:
            res = self.tools.view_file_content(file_path)
            # Truncate content if it's exceptionally large to avoid context overload
            if len(res) > 50000:
                res = res[:50000] + "\n\n... [Content Truncated due to size] ..."
            return res

        def search_repo(query: str) -> str:
            res = self.tools.search_code(query)
            return json.dumps(res)

        def get_imports() -> str:
            res = self.tools.get_dependency_graph()
            return json.dumps(res)

        def get_summary(file_path: str) -> str:
            res = self.tools.get_file_summary(file_path)
            return json.dumps(res)

        # Create a mapping for execution
        tool_mapping = {
            "list_dir": list_directory,
            "view_file_content": view_file,
            "search_code": search_repo,
            "get_dependency_graph": get_imports,
            "get_file_summary": get_summary
        }

        # Instead of generic autonomous chat, we execute the planned steps explicitly.
        # This gives us exact control and logs, while still letting Gemini read the inputs.
        for idx, step in enumerate(plan_data.get("steps", [])):
            tool_name = step["tool_to_use"]
            arg = step["target_argument"]
            desc = step["task_description"]
            
            logs.append({"agent": "Investigator", "action": "Running Tool", "message": f"Step {idx+1}: {desc} (using {tool_name} with '{arg}')"})
            
            tool_func = tool_mapping.get(tool_name)
            if tool_func:
                try:
                    # Run the tool
                    if tool_name in ["get_dependency_graph"]:
                        result_str = tool_func()
                    else:
                        result_str = tool_func(arg)
                        
                    tool_calls_executed.append({
                        "tool": tool_name,
                        "argument": arg,
                        "result_summary": result_str[:200] + "..." if len(result_str) > 200 else result_str
                    })
                    
                    investigation_context.append(
                        f"Task: {desc}\nTool Run: {tool_name}({arg})\nResult:\n{result_str}\n"
                    )
                except Exception as err:
                    logs.append({"agent": "Investigator", "action": "Tool Error", "message": f"Failed running {tool_name}: {str(err)}"})
            else:
                logs.append({"agent": "Investigator", "action": "Tool Skip", "message": f"Unknown tool: {tool_name}"})

        # --- STEP 3: ANSWER AGENT ---
        logs.append({"agent": "Answerer", "action": "Synthesizing Answer", "message": "Reviewing code findings and writing final response..."})
        try:
            answerer_instruction = (
                "You are an Elite Staff AI Engineer. Take the user's query, review the compiled repository code context "
                "gathered by the Investigator, and write a thorough, detailed, and clear markdown answer. "
                "Explain the code logic, quote relevant snippets if needed, and reference file paths using markdown links. "
                "Ensure your tone is professional, authoritative, and direct."
            )
            
            context_payload = "\n===\n".join(investigation_context)
            answer_prompt = (
                f"User Query: \"{user_query}\"\n\n"
                f"Planned Steps & Findings:\n{context_payload}\n\n"
                "Formulate a complete, comprehensive explanation based on these findings. "
                "Highlight paths, files, and classes using standard backticks and links."
            )
            
            # Use Gemini 2.5 Flash for writing the answer
            answer_response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=answer_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=answerer_instruction,
                    temperature=0.2
                )
            )
            
            final_answer = answer_response.text
            logs.append({"agent": "Answerer", "action": "Completed", "message": "Answer synthesized successfully."})
            
            # Capture usage stats if available
            if answer_response.usage_metadata:
                p_tokens = answer_response.usage_metadata.prompt_token_count
                c_tokens = answer_response.usage_metadata.candidates_token_count
                
                # Estimate cost for this run
                cost = (p_tokens / 1_000_000) * PRICE_PER_M_INPUT + (c_tokens / 1_000_000) * PRICE_PER_M_OUTPUT
                logs.append({
                    "agent": "System", 
                    "action": "Token Meter", 
                    "message": f"Query Cost: ${cost:.5f} (Input: {p_tokens} tokens, Output: {c_tokens} tokens)"
                })
                
        except Exception as e:
            final_answer = f"Error generating final response: {str(e)}\n\nHere is what was found:\n\n" + "\n".join(investigation_context)
            logs.append({"agent": "Answerer", "action": "Error", "message": str(e)})
            
        return {
            "answer": final_answer,
            "plan": plan_data,
            "tool_calls": tool_calls_executed,
            "logs": logs
        }
