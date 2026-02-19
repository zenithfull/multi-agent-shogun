
import os
import sys
import argparse
import subprocess
import glob
import yaml
from google import genai
from google.genai import types
from ddgs import DDGS
try:
    from anthropic import AnthropicBedrock
    import botocore.exceptions
except ImportError:
    AnthropicBedrock = None

# Bedrock Tool Schemas
BEDROCK_TOOLS = [
    {
        "name": "web_search",
        "description": "Searches the web using DuckDuckGo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."}
            },
            "required": ["query"]
        }
    },
    {
        "name": "read_file",
        "description": "Reads a file from the filesystem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "The absolute path to the file."}
            },
            "required": ["filepath"]
        }
    },
    {
        "name": "write_file",
        "description": "Writes content to a file. Creates the file if it doesn't exist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "The absolute path to the file."},
                "content": {"type": "string", "description": "The content to write."}
            },
            "required": ["filepath", "content"]
        }
    },
    {
        "name": "list_directory",
        "description": "Lists files in the specified directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The directory path. Defaults to '.'."}
            },
            "required": []
        }
    },
    {
        "name": "execute_shell_command",
        "description": "Executes a shell command and returns the output.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute."}
            },
            "required": ["command"]
        }
    },
    {
        "name": "grep_search",
        "description": "Searches for a pattern in files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "The search pattern."},
                "path": {"type": "string", "description": "The path to search in. Defaults to '.'."}
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "delegate_to_karo",
        "description": "Delegates a command to Karo. ONLY use this when you are Shogun.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command_yaml": {"type": "string", "description": "The YAML content for the command."}
            },
            "required": ["command_yaml"]
        }
    },
    {
        "name": "notify_agent",
        "description": "Sends a message to another agent's terminal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "The target agent ID (e.g. 'shogun', 'karo')."},
                "message": {"type": "string", "description": "The message/instruction to send."}
            },
            "required": ["agent_id", "message"]
        }
    }
]

# Tool Definitions

def web_search(query: str) -> str:
    """Searches the web using DuckDuckGo."""
    try:
        results = DDGS().text(query, max_results=5)
        return str(results)
    except Exception as e:
        return f"Error searching web: {e}"

def read_file(filepath: str) -> str:
    """Reads a file from the filesystem."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

def write_file(filepath: str, content: str) -> str:
    """Writes content to a file. Creates the file if it doesn't exist."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote to {filepath}"
    except Exception as e:
        return f"Error writing file: {e}"

def list_directory(path: str = ".") -> str:
    """Lists files in the specified directory."""
    try:
        files = os.listdir(path)
        return "\n".join(files)
    except Exception as e:
        return f"Error listing directory: {e}"

def execute_shell_command(command: str) -> str:
    """Executes a shell command and returns the output."""
    try:
        # Use a timeout to prevent hanging
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
        output = result.stdout
        if result.stderr:
            output += "\nSTDERR:\n" + result.stderr
        return output
    except subprocess.TimeoutExpired:
        return "Error: Command timed out."
    except Exception as e:
        return f"Error executing command: {e}"

def grep_search(pattern: str, path: str = ".") -> str:
    """Searches for a pattern in files using grep (via shell) or python fallback."""
    # Using python fallback for cross-platform compatibility if simple
    try:
        # Simple recursive search
        matches = []
        for root, _, files in os.walk(path):
            for file in files:
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        for i, line in enumerate(f, 1):
                            if pattern in line:
                                matches.append(f"{filepath}:{i}: {line.strip()}")
                except:
                    pass
        return "\n".join(matches[:100]) # Limit results
    except Exception as e:
        return f"Error searching: {e}"

def delegate_to_karo(command_yaml: str) -> str:
    """Delegates a command to Karo by writing to queue/shogun_to_karo.yaml and sending notification via tmux.
    
    Args:
        command_yaml: The YAML content for the command.
    
    Returns:
        Success or error message.
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        queue_path = os.path.join(project_root, 'queue', 'shogun_to_karo.yaml')
        
        # Step 1: Write the command YAML
        os.makedirs(os.path.dirname(queue_path), exist_ok=True)
        with open(queue_path, 'w', encoding='utf-8') as f:
            f.write(command_yaml)
        
        # Step 2: Direct tmux send-keys to Karo's pane
        try:
            result = subprocess.run(
                ['tmux', 'display-message', '-p', '-t', 'multiagent:agents.0', '#{pane_id}'],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0:
                nudge_msg = 'queue/shogun_to_karo.yaml を読んで、指示を実行せよ。'
                subprocess.run(
                    ['tmux', 'send-keys', '-t', 'multiagent:agents.0', nudge_msg, 'Enter'],
                    capture_output=True, text=True, timeout=3
                )
                return "家老への委譲完了。YAMLを書き込み、家老のターミナルに指示を送信した。"
            else:
                return "YAMLを書き込んだが、家老のtmuxペインが見つからなかった。"
        except Exception:
            return "YAMLを書き込んだが、tmux送信に失敗した。"
    except Exception as e:
        return f"委譲エラー: {e}"

def notify_agent(agent_id: str, message: str) -> str:
    """Sends a message to another agent's terminal via tmux send-keys.
    
    Use this to notify any agent: shogun, karo, ashigaru (ashigaru1-7), or gunshi.
    The message will be typed into the agent's terminal as input.
    
    Args:
        agent_id: The target agent ID (e.g. 'shogun', 'karo', 'ashigaru1', 'gunshi').
        message: The message/instruction to send to the agent.
    
    Returns:
        Success or error message.
    """
    try:
        # Search across both tmux sessions: 'multiagent' and 'shogun'
        for session in ['multiagent', 'shogun']:
            result = subprocess.run(
                ['tmux', 'list-panes', '-s', '-t', session, '-F', 
                 '#{session_name}:#{window_name}.#{pane_index} #{@agent_id}'],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode != 0:
                continue
            
            for line in result.stdout.strip().split('\n'):
                parts = line.strip().split(' ', 1)
                if len(parts) == 2 and parts[1] == agent_id:
                    pane_target = parts[0]
                    subprocess.run(
                        ['tmux', 'send-keys', '-t', pane_target, message, 'Enter'],
                        capture_output=True, text=True, timeout=3
                    )
                    return f"{agent_id} にメッセージを送信した。"
        
        return f"エラー: agent_id '{agent_id}' のペインが見つからない"
    except Exception as e:
        return f"通知エラー: {e}"

# Configuration Loading

def load_instructions(role):
    """Loads the instruction file for the given role."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    instruction_path = os.path.join(project_root, 'instructions', f'{role}.md')

    if os.path.exists(instruction_path):
        try:
            with open(instruction_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"Warning: Failed to load instructions for {role}: {e}")
            return ""
    else:
        return ""

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'models.yaml')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Warning: Config file not found at {config_path}. Using defaults.")
        return {}

def get_model_config(role, config):
    if not config:
        return "gemini", "gemini-2.0-flash", "GEMINI_API_KEY"
    
    roles = config.get('roles', {})
    role_config = roles.get(role, {})
    provider = role_config.get('provider', 'gemini')
    model_name = role_config.get('model', 'gemini-2.0-flash')
    
    providers = config.get('providers', {})
    provider_config = providers.get(provider, {})
    api_key_env = provider_config.get('api_key_env', 'GEMINI_API_KEY')
    
    return provider, model_name, api_key_env

# Main REPL

def main():
    parser = argparse.ArgumentParser(description="Gemini CLI Wrapper for Multi-Agent Shogun (google-genai SDK)")
    parser.add_argument('--role', help='Agent role (shogun, karo, etc.)', default='shogun')
    parser.add_argument('--model', help='Model name override')
    parser.add_argument('--dangerously-skip-permissions', action='store_true', help='Ignored (compatibility)')
    
    args, unknown = parser.parse_known_args()
    
    config = load_config()
    instructions = load_instructions(args.role)
    provider, model_name, api_key_env = get_model_config(args.role, config)
    
    if args.model:
        model_name = args.model # CLI override wins

    api_key = os.environ.get(api_key_env)
    if not api_key:
        print(f"Error: {api_key_env} not found in environment variables.")
        sys.exit(1)
    api_key = api_key.strip()

    # Map of available tool functions
    TOOL_FUNCTIONS = {
        'read_file': read_file,
        'write_file': write_file,
        'list_directory': list_directory,
        'execute_shell_command': execute_shell_command,
        'grep_search': grep_search,
        'web_search': web_search,
        'delegate_to_karo': delegate_to_karo,
        'notify_agent': notify_agent,
    }

    if provider == 'gemini':
        client = genai.Client(api_key=api_key)
        
        # Role-based tool selection
        shogun_only = {'delegate_to_karo'}  # Only Shogun delegates to Karo
        
        if args.role == 'shogun':
            # Shogun: delegate_to_karo, no notify_agent (delegates via dedicated function)
            role_tools = {k: v for k, v in TOOL_FUNCTIONS.items() if k != 'notify_agent'}
        else:
            # Karo, Ashigaru, Gunshi — all can use notify_agent for communication
            role_tools = {k: v for k, v in TOOL_FUNCTIONS.items() if k not in shogun_only}
        
        all_tools = list(role_tools.values())

        # Role-based system prompt
        if args.role == 'shogun':
            base_instruction = f"""You are an AI agent with role: {args.role}.
You are the Shogun (将軍) — a commander who delegates work to subordinates.

=== CRITICAL RULES (HIGHEST PRIORITY — MUST FOLLOW BEFORE ALL ELSE) ===

RULE 1 — DELEGATION IS YOUR PRIMARY JOB:
When the user gives ANY work request (research, create, analyze, write, investigate, compare, etc.),
you MUST call the `delegate_to_karo` function IMMEDIATELY.
DO NOT answer it yourself. DO NOT ask clarifying questions. Just delegate.

Examples of requests that REQUIRE delegation:
- 「〇〇調べて」→ delegate_to_karo
- 「〇〇作って」→ delegate_to_karo
- 「比較表を作成せよ」→ delegate_to_karo
- 「〇〇分析して」→ delegate_to_karo

RULE 2 — HOW TO CALL delegate_to_karo:
Pass a YAML string with this format:
- id: cmd_001
  timestamp: "2026-02-17T12:00:00+09:00"
  purpose: "Task description"
  acceptance_criteria:
    - "Criterion 1"
  command: |
    Detailed instructions
  project: ProjectName
  priority: medium
  status: pending

RULE 3 — For quick factual searches (stock price, weather), use `web_search` directly.
RULE 4 — You MUST call tool functions. Never just talk about doing something.
RULE 5 — After a tool returns its result, provide a COMPLETE response summarizing what was done.

=== END CRITICAL RULES ===

Below are your detailed role instructions for reference:
{instructions}"""
        elif args.role == 'karo':
            # Karo: manager who executes tasks and can distribute subtasks to ashigaru
            base_instruction = f"""You are an AI agent with role: {args.role}.
You are the Karo (家老) — a senior manager. You execute tasks from Shogun and can distribute subtasks to Ashigaru.

=== CRITICAL RULES ===

RULE 1 — EXECUTE TASKS: Read the YAML file (queue/shogun_to_karo.yaml), understand the task, and work on it.

RULE 2 — DISTRIBUTE SUBTASKS TO ASHIGARU:
When you need to distribute work to ashigaru agents, use the `notify_agent` function:
  notify_agent(agent_id='ashigaru1', message='YAMLファイルを読んで実行せよ: queue/tasks/ashigaru1.yaml')
Available agents: ashigaru1, ashigaru2, ashigaru3, ashigaru4, ashigaru5, ashigaru6, ashigaru7, gunshi

IMPORTANT: You MUST use `notify_agent` to send tasks. Do NOT use `execute_shell_command` with inbox_write.sh.

RULE 3 — First write the subtask YAML with `write_file`, then call `notify_agent` for each ashigaru.

RULE 4 — After completing work, write results and update dashboard.md.

RULE 5 — REPORT BACK TO SHOGUN (MANDATORY):
After all tasks are complete (including ashigaru subtasks), report results to Shogun:
  notify_agent(agent_id='shogun', message='タスク完了。結果をまとめて報告いたします。...')
Include a summary of what was accomplished.

=== END CRITICAL RULES ===

Below are your detailed role instructions for reference:
{instructions}"""
        else:
            # Ashigaru, Gunshi: workers who execute tasks and report back
            base_instruction = f"""You are an AI agent with role: {args.role}.
You are a worker agent who EXECUTES tasks directly and REPORTS results back to Karo.

=== CRITICAL RULES ===

RULE 1 — EXECUTE TASKS DIRECTLY:
When you receive a task or instruction, execute it yourself using the available tools.
- Use `read_file` to read files
- Use `write_file` to write results  
- Use `web_search` to search the web
- Use `execute_shell_command` to run commands
- Use `grep_search` to search in files

RULE 2 — When instructed to read a YAML file, read it, understand the task, and execute it.

RULE 3 — REPORT BACK TO KARO (MANDATORY):
After completing your task, you MUST call `notify_agent` to report results to Karo:
  notify_agent(agent_id='karo', message='タスク完了。結果はreports/に書き込みました。')
Always include a summary of what you accomplished in the message.

=== END CRITICAL RULES ===

Below are your detailed role instructions for reference:
{instructions}"""

        generate_content_config = types.GenerateContentConfig(
            tools=all_tools,
            system_instruction=base_instruction,
            # Disable automatic function calling — we handle it manually for better response control
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )

        print(f"Gemini CLI ({model_name}) initialized for role: {args.role}")
        print("Ready for input...")
        
        # Start chat
        chat = client.chats.create(model=model_name, config=generate_content_config)

        while True:
            try:
                user_input = input()
                if not user_input:
                    break
                    
                response = chat.send_message(user_input)
                
                # Manual function calling loop
                while True:
                    # Check if the response contains function calls
                    function_calls = []
                    if response.candidates:
                        for candidate in response.candidates:
                            if candidate.content and candidate.content.parts:
                                for part in candidate.content.parts:
                                    if part.function_call:
                                        function_calls.append(part.function_call)
                    
                    if not function_calls:
                        # No more function calls — print text response and break
                        if response.text:
                            print(response.text)
                        break
                    
                    # Execute each function call and collect results
                    function_responses = []
                    for fc in function_calls:
                        func_name = fc.name
                        func_args = dict(fc.args) if fc.args else {}
                        
                        print(f"[Tool] {func_name}({', '.join(f'{k}={repr(v)[:50]}' for k,v in func_args.items())})", file=sys.stderr)
                        
                        if func_name in TOOL_FUNCTIONS:
                            try:
                                result = TOOL_FUNCTIONS[func_name](**func_args)
                            except Exception as e:
                                result = f"Error executing {func_name}: {e}"
                        else:
                            result = f"Unknown function: {func_name}"
                        
                        print(f"[Tool] {func_name} → done ({len(str(result))} chars)", file=sys.stderr)
                        
                        function_responses.append(
                            types.Part.from_function_response(
                                name=func_name,
                                response={"result": str(result)}
                            )
                        )
                    
                    # Send function results back to the model
                    response = chat.send_message(function_responses)

            except EOFError:
                break
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"Error: {e}")

    elif provider == 'bedrock':
        if not AnthropicBedrock:
            print("Error: anthropic[bedrock] not installed. Please install it to use Bedrock provider.")
            sys.exit(1)
            
        region = config.get('providers', {}).get('bedrock', {}).get('region_name', 'us-west-2')
        client = AnthropicBedrock(aws_region=region)
        
        # Prepare system prompt (same logic as Gemini)
        if args.role == 'shogun':
            base_instruction = f"""You are an AI agent with role: {args.role}.
You are the Shogun (将軍) — a commander who delegates work to subordinates.

=== CRITICAL RULES (HIGHEST PRIORITY — MUST FOLLOW BEFORE ALL ELSE) ===

RULE 1 — DELEGATION IS YOUR PRIMARY JOB:
When the user gives ANY work request (research, create, analyze, write, investigate, compare, etc.),
you MUST call the `delegate_to_karo` function IMMEDIATELY.
DO NOT answer it yourself. DO NOT ask clarifying questions. Just delegate.

Examples of requests that REQUIRE delegation:
- 「〇〇調べて」→ delegate_to_karo
- 「〇〇作って」→ delegate_to_karo
- 「比較表を作成せよ」→ delegate_to_karo
- 「〇〇分析して」→ delegate_to_karo

RULE 2 — HOW TO CALL delegate_to_karo:
Pass a YAML string with this format:
- id: cmd_001
  timestamp: "2026-02-17T12:00:00+09:00"
  purpose: "Task description"
  acceptance_criteria:
    - "Criterion 1"
  command: |
    Detailed instructions
  project: ProjectName
  priority: medium
  status: pending

RULE 3 — For quick factual searches (stock price, weather), use `web_search` directly.
RULE 4 — You MUST call tool functions. Never just talk about doing something.
RULE 5 — After a tool returns its result, provide a COMPLETE response summarizing what was done.

=== END CRITICAL RULES ===

Below are your detailed role instructions for reference:
{instructions}"""
        elif args.role == 'karo':
            base_instruction = f"""You are an AI agent with role: {args.role}.
You are the Karo (家老) — a senior manager. You execute tasks from Shogun and can distribute subtasks to Ashigaru.

=== CRITICAL RULES ===

RULE 1 — EXECUTE TASKS: Read the YAML file (queue/shogun_to_karo.yaml), understand the task, and work on it.

RULE 2 — DISTRIBUTE SUBTASKS TO ASHIGARU:
When you need to distribute work to ashigaru agents, use the `notify_agent` function:
  notify_agent(agent_id='ashigaru1', message='YAMLファイルを読んで実行せよ: queue/tasks/ashigaru1.yaml')
Available agents: ashigaru1, ashigaru2, ashigaru3, ashigaru4, ashigaru5, ashigaru6, ashigaru7, gunshi

IMPORTANT: You MUST use `notify_agent` to send tasks. Do NOT use `execute_shell_command` with inbox_write.sh.

RULE 3 — First write the subtask YAML with `write_file`, then call `notify_agent` for each ashigaru.

RULE 4 — After completing work, write results and update dashboard.md.

RULE 5 — REPORT BACK TO SHOGUN (MANDATORY):
After all tasks are complete (including ashigaru subtasks), report results to Shogun:
  notify_agent(agent_id='shogun', message='タスク完了。結果をまとめて報告いたします。...')
Include a summary of what was accomplished.

=== END CRITICAL RULES ===

Below are your detailed role instructions for reference:
{instructions}"""
        else:
            base_instruction = f"""You are an AI agent with role: {args.role}.
You are a worker agent who EXECUTES tasks directly and REPORTS results back to Karo.

=== CRITICAL RULES ===

RULE 1 — EXECUTE TASKS DIRECTLY:
When you receive a task or instruction, execute it yourself using the available tools.
- Use `read_file` to read files
- Use `write_file` to write results  
- Use `web_search` to search the web
- Use `execute_shell_command` to run commands
- Use `grep_search` to search in files

RULE 2 — When instructed to read a YAML file, read it, understand the task, and execute it.

RULE 3 — REPORT BACK TO KARO (MANDATORY):
After completing your task, you MUST call `notify_agent` to report results to Karo:
  notify_agent(agent_id='karo', message='タスク完了。結果はreports/に書き込みました。')
Always include a summary of what you accomplished in the message.

=== END CRITICAL RULES ===

Below are your detailed role instructions for reference:
{instructions}"""

        print(f"Bedrock CLI ({model_name}) initialized for role: {args.role}")
        print("Ready for input...")

        # Shogun-specific tool filter for Bedrock
        if args.role == 'shogun':
            available_tools = [t for t in BEDROCK_TOOLS if t['name'] != 'notify_agent']
        else:
            shogun_only_tools = {'delegate_to_karo'}
            available_tools = [t for t in BEDROCK_TOOLS if t['name'] not in shogun_only_tools]

        messages = []

        while True:
            try:
                user_input = input()
                if not user_input:
                    break
                
                messages.append({"role": "user", "content": user_input})
                
                while True:
                    try:
                        response = client.messages.create(
                            model=model_name,
                            max_tokens=4096,
                            system=base_instruction,
                            messages=messages,
                            tools=available_tools
                        )
                    except botocore.exceptions.ClientError as e:
                        print(f"AWS Error: {e}")
                        break
                    except Exception as e:
                        print(f"Error calling Bedrock: {e}")
                        break

                    # Check stop reason
                    if response.stop_reason == 'tool_use':
                        # Append assistant's response (including tool use) to history
                        messages.append({"role": "assistant", "content": response.content})
                        
                        tool_results = []
                        for block in response.content:
                            if block.type == 'tool_use':
                                func_name = block.name
                                func_args = block.input
                                tool_use_id = block.id
                                
                                print(f"[Tool] {func_name}({', '.join(f'{k}={repr(v)[:50]}' for k,v in func_args.items())})", file=sys.stderr)
                                
                                if func_name in TOOL_FUNCTIONS:
                                    try:
                                        result = TOOL_FUNCTIONS[func_name](**func_args)
                                    except Exception as e:
                                        result = f"Error executing {func_name}: {e}"
                                else:
                                    result = f"Unknown function: {func_name}"
                                
                                print(f"[Tool] {func_name} → done ({len(str(result))} chars)", file=sys.stderr)
                                
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": tool_use_id,
                                    "content": str(result)
                                })
                        
                        # Append tool results as a single user message
                        if tool_results:
                            messages.append({"role": "user", "content": tool_results})
                            # Loop continues to send tool results back to model
                    else:
                        # Final response
                        text_content = ""
                        for block in response.content:
                            if block.type == 'text':
                                text_content += block.text
                        
                        print(text_content)
                        messages.append({"role": "assistant", "content": response.content})
                        break
                        
            except EOFError:
                break
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"Error: {e}")

    else:
        print(f"Error: Provider {provider} not supported.")
        sys.exit(1)

if __name__ == '__main__':
    main()

