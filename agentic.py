import os
import subprocess
import re
from openai import OpenAI

# Initialize LLM Client
client = OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="lm-studio",  # Dummy API key, replace with real one
)

# --- HELPER FUNCTIONS ---

def run_build_command(build_command):
    try:
        result = subprocess.run(
            build_command,
            cwd=os.getcwd(),
            check=False,
            capture_output=True,
            text=True,
            shell=True
        )
        return result.stdout, result.stderr
    except Exception as e:
        return "", str(e)

def extract_file_and_line(error_message):
    match = re.search(r'([a-zA-Z0-9_\-\\/.]+(?:\.js|\.jsx|\.ts|\.tsx|\.py|\.cs|\.java)):(\d+)', error_message)
    if match:
        filepath = match.group(1)
        line_number = int(match.group(2))
        return filepath, line_number
    return None, None

def extract_code_from_response(response_text):
    match = re.search(r'```(?:\w+)?\n(.*?)```', response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    else:
        return response_text.strip()

def replace_lines_in_file(filepath, corrected_code):
    try:
        # Ensure the file path is absolute and properly formatted
        filepath = os.path.abspath(filepath)
        print(f"🔵 Trying to modify: {filepath}")

        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Replace the entire file content with the corrected code
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(corrected_code)

        print(f"\n✅ Successfully updated the file {filepath}!")
    except Exception as e:
        print(f"❌ Error replacing lines in {filepath}: {e}")

def identify_project_type():
    script_directory = os.path.dirname(os.path.abspath(__file__))
    top_level_files = os.listdir(script_directory)
    important_files = ['package.json', 'requirements.txt', 'setup.py', 'pyproject.toml', 'pom.xml', '.csproj', '.sln']
    existing_configs = []

    # Check for important config files
    for file in important_files:
        file_path = os.path.join(script_directory, file)
        if os.path.isfile(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    existing_configs.append((file, content))
            except Exception as e:
                print(f"Error reading {file_path}: {e}")

    # Look for .NET or JavaScript-related files
    dotnet_files = [f for f in top_level_files if f.endswith('.csproj') or f.endswith('.sln')]
    nodejs_files = [f for f in top_level_files if f == 'package.json']
    python_files = [f for f in top_level_files if f == 'requirements.txt' or f == 'setup.py']

    if dotnet_files:
        return "dotnet", dotnet_files
    elif nodejs_files:
        return "nodejs", nodejs_files
    elif python_files:
        return "python", python_files
    else:
        return "unknown", []

# --- MAIN FLOW ---

project_type, project_files = identify_project_type()

# Build commands for different project types
if project_type == "nodejs":
    build_command = ["npm", "run", "build"]
elif project_type == "python":
    build_command = ["python", "setup.py", "install"]
elif project_type == "dotnet":
    build_command = ["dotnet", "build"]
else:
    print("❌ Unknown project type or no recognizable build configuration.")
    exit(1)

# Print the build command to the console
print(f"🔧 Executing build command: {' '.join(build_command)}")
# Run the build command
while True:
    stdout, stderr = run_build_command(build_command)
    print("STDOUT:\n", stdout)
    print("STDERR:\n", stderr)

    error_message = stderr.strip()

    if not error_message:
        print("✅ Build succeeded! No errors to fix.")
        break  # Exit the loop when build is successful

    filepath, line_number = extract_file_and_line(error_message)
    if filepath and line_number:
        # Ensure filepath is absolute and doesn't get duplicated
        filepath = os.path.normpath(filepath)  # Normalize path to avoid duplication
        print(f"\n🛠 Detected error in file: {filepath} at line {line_number}")
    else:
        print("\n⚠️ Could not detect file path and line number. Exiting.")
        exit(1)

    # Read the entire file to provide context to the AI model
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Failed to read file {filepath}: {e}")
        break

    context_snippet = "".join(lines)  # Entire file as context

    # --- SINGLE PROMPT: Ask for corrected code based on entire file context ---
    prompt = f"""
I tried running `{build_command[0]} {build_command[1]}` but it failed with this error:

{error_message}

Here is the entire code in the file:
{context_snippet}

Please provide the corrected code wrapped inside triple backticks like this:
"""

    response = client.completions.create(
        model="mistral-7b-instruct-v0.1",
        prompt=prompt,
        max_tokens=1000
    )

    corrected_code = extract_code_from_response(response.choices[0].text.strip())
    print("\n--- Extracted Corrected Code ---\n", corrected_code)

    # Replace the entire file content with the corrected code
    replace_lines_in_file(filepath, corrected_code)

    print("\n🔁 Retrying build after applying fix...\n")

    # Re-run the build after applying the fix
    stdout, stderr = run_build_command(build_command)
    error_message = stderr.strip()

    if not error_message:
        print("✅ Build succeeded after fix!")
        break  # Exit the loop when build is successful
    else:
        print("❌ Build still failed after fix.")
        break  # Exit the loop after one retry
