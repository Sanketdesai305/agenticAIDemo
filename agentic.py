import zipfile
import os
import tempfile
import json
import subprocess
import re
from openai import OpenAI
import requests
import shutil
import stat

# === 1. ASK FOR GITHUB TOKEN, USERNAME, REPO NAME ===
zip_path = input("📦 Enter path to zip file: ").strip()
if not os.path.isfile(zip_path) or not zip_path.endswith(".zip"):
    print("❌ Invalid zip path.")
    exit(1)
GITHUB_TOKEN = input("Please enter your GitHub token: ")
GITHUB_USERNAME = input("Please enter your GitHub username: ")
REPO_NAME = input("Please enter the repository name to create: ")

# Automatically get the base directory (parent directory of the script's location)
BASE_DIR = os.path.abspath(os.path.join(os.getcwd(), os.pardir))  # Get parent directory
PROJECT_DIR = os.path.join(BASE_DIR, "project_folder")  # Assuming the project folder is named "project_folder"

# Initialize LLM Client
client = OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="lm-studio",  # Dummy API key, replace with real one
)

# --- HELPER FUNCTIONS ---
def unzip_folder(zip_path, extract_to):
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)
    print(f"✅ Extracted zip to: {extract_to}")

def build_file_tree(folder, depth=2):
    tree = {}
    for root, dirs, files in os.walk(folder):
        level = root.replace(folder, "").count(os.sep)
        if level > depth:
            continue
        rel_root = os.path.relpath(root, folder)
        tree[rel_root] = files[:10]
    return tree

def read_key_files(folder, filenames=("package.json", "requirements.txt", "setup.py", "pyproject.toml", "Makefile")):
    contents = {}
    for root, _, files in os.walk(folder):
        for name in files:
            if name in filenames:
                path = os.path.join(root, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        contents[name] = f.read()[:2000]
                except:
                    pass
    return contents

def ask_llm_to_identify_project(file_tree, key_file_contents, project_dir):
    prompt = f"""
You are a helpful assistant. I extracted a project zip folder. Here's what I found:

📁 File Tree (partial):
{json.dumps(file_tree, indent=2)}

📄 Key Files:
{json.dumps(key_file_contents, indent=2)}

Based on "File Tree" and "Key Files", answer the following two questions **clearly and concisely in the exact same format shown below**:

### Example Format:
1. Project type: Node.js
2. Build command: ```npm run build```

Now, provide your answer below in the same format:ELI10
"""

    response = client.completions.create(
        model="mistral-7b-instruct-v0.1",
        prompt=prompt,
        max_tokens=400
    )

    llm_response = response.choices[0].text.strip()
    print("\n🤖 LLM Analysis:\n", llm_response)

    # Extract project_type and build_command using regex
    project_type_match = re.search(r"Project type:\s*(.+)", llm_response)
    build_command_match = re.search(r"Build command:\s*```(.+?)```", llm_response, re.DOTALL)

    if not project_type_match or not build_command_match:
        raise ValueError("⚠️ Could not extract project type or build command from LLM response.")

    project_type = project_type_match.group(1).strip()
    build_command = build_command_match.group(1).strip().split()

    return project_type, build_command
# Function to run the build command
def run_build_command(build_command):
    try:
        result = subprocess.run(
            build_command,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            shell=True
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)

def extract_file_and_line(error_message):
    # Pattern 1: C# style - e.g., C:\path\file.cs(42,13)
    match = re.search(r'([A-Za-z]:\\[^\(:]+\.cs)\((\d+),\d+\)', error_message)
    if match:
        filepath = match.group(1)
        line_number = int(match.group(2))
        return filepath, line_number

    # Pattern 2: General style - e.g., /path/file.js:42 or file.py:23
    match = re.search(r'([a-zA-Z0-9_\-\\/.]+(?:\.js|\.jsx|\.ts|\.tsx|\.py|\.cs|\.java|\.go)):(\d+)', error_message)
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
    important_files = ['package.json', 'requirements.txt', 'setup.py', 'pyproject.toml', 'pom.xml', '.csproj', '.sln', 'build.gradle', 'go.mod']

    existing_configs = []

    # Scan for important files
    for file in top_level_files:
        if file in important_files or file.endswith(('.csproj', '.sln', '.go')):
            file_path = os.path.join(script_directory, file)
            if os.path.isfile(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        existing_configs.append((file, content))
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")

    # Match project type
    dotnet_files = [f for f in top_level_files if f.endswith('.csproj') or f.endswith('.sln')]
    nodejs_files = [f for f in top_level_files if f == 'package.json']
    python_files = [f for f in top_level_files if f in ['requirements.txt', 'setup.py']]
    java_files = [f for f in top_level_files if f in ['pom.xml', 'build.gradle']]
    go_files = [f for f in top_level_files if f == 'go.mod' or f.endswith('.go')]

    if dotnet_files:
        return "dotnet", existing_configs
    elif nodejs_files:
        return "nodejs", existing_configs
    elif python_files:
        return "python", existing_configs
    elif java_files:
        return "java", existing_configs
    elif go_files:
        return "go", existing_configs
    else:
        return "unknown", existing_configs


# === 2. CREATE GITHUB REPO ===
def create_repo():
    url = "https://api.github.com/user/repos"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = {"name": REPO_NAME, "private": False}
    
    try:
        r = requests.post(url, headers=headers, json=data)
        if r.status_code == 201:
            print(f"✅ Repo '{REPO_NAME}' created")
        elif r.status_code == 422:
            print("⚠️ Repo already exists, continuing...")
        else:
            print(f"❌ Failed to create repo: {r.text}")
    except Exception as e:
        print(f"❌ Error during repo creation: {e}")


def remove_git_directory():
    git_dir = ".git"
    
    if os.path.exists(git_dir):
        # Change file permissions to ensure it's writable
        for root, dirs, files in os.walk(git_dir):
            for file in files:
                file_path = os.path.join(root, file)
                # Make the file writable by changing permissions
                os.chmod(file_path, stat.S_IWRITE)
        
        # Try to remove the .git directory
        try:
            shutil.rmtree(git_dir)
            print(f"✅ Successfully removed the .git directory!")
        except PermissionError as e:
            print(f"❌ Permission error while removing .git: {e}")
        except Exception as e:
            print(f"❌ Error removing .git: {e}")
    else:
        print(f"❌ .git directory not found!")

def push_to_github():
    PROJECT_DIR = os.getcwd()  # Get the current working directory where the script is located
    
    remove_git_directory()  # First, clean up any existing .git directory

    if os.path.isdir(PROJECT_DIR):  # Ensure the directory exists
        os.chdir(PROJECT_DIR)  # Change to the current directory where the script is located
        subprocess.run(["git", "init"])  # Initialize the Git repository
        subprocess.run(["git", "remote", "add", "origin", f"https://{GITHUB_USERNAME}:{GITHUB_TOKEN}@github.com/{GITHUB_USERNAME}/{REPO_NAME}.git"])  # Add remote
        subprocess.run(["git", "checkout", "-b", "main"])  # Create and switch to 'main' branch
        subprocess.run(["git", "add", "."])  # Add all files to staging
        subprocess.run(["git", "commit", "-m", "initial commit"])  # Commit the files
        subprocess.run(["git", "push", "-u", "origin", "main"])  # Push the changes to GitHub
        print("🚀 Code pushed to GitHub!")
    else:
        print(f"❌ Project directory '{PROJECT_DIR}' not found!")

# Function definition

def create_github_actions_workflow(project_type, java_distribution):
    prompt = f"""
Generate a GitHub Actions CI/CD workflow in YAML format for a {project_type} project.

Requirements:
- Trigger on push and pull_request to the main branch.
- Include build, test, and artifact upload steps.
- For Java, use distribution '{java_distribution}' and Java version 17.
- For .NET, use SDK version 8.0.
- For Python, use version 3.11.
- For Node.js, use version 14.
- For Go, use version 1.21.

Wrap the generated YAML inside triple backticks:ELI10
"""
    try:
        response = client.completions.create(
            model="mistral-7b-instruct-v0.1",
            prompt=prompt,
            max_tokens=1000,
        )

        corrected_code1 = extract_code_from_response(response.choices[0].text.strip())
        print("🔧 Writing the following content to ci.yml:\n", corrected_code1)
        workflow_file_path = '.github/workflows/ci.yml'
        os.makedirs(os.path.dirname(workflow_file_path), exist_ok=True)

        with open(workflow_file_path, 'w') as f:
            f.write(corrected_code1)

        print(f"✅ Workflow created for '{project_type}' using LLM.")

    except Exception as e:
        print(f"❌ Error generating workflow: {e}")



# --- MAIN FLOW ---

with tempfile.TemporaryDirectory() as temp_dir:
    unzip_folder(zip_path, temp_dir)
    tree = build_file_tree(temp_dir)
    key_files = read_key_files(temp_dir)
    project_type, build_command = ask_llm_to_identify_project(tree, key_files, temp_dir)


print(f"🔵 Building the {project_type} project...")
print(f"🔧 Suggested build command: {' '.join(build_command)}")

# Ask once for build command to use
user_input = input("❓ Do you want to run this build command? (yes/no): ").strip().lower()

if user_input in ["yes", "y"]:
    chosen_command = build_command
else:
    custom_command = input("⌨️ Enter your custom build command: ").strip()
    if not custom_command:
        print("❌ No command provided. Exiting.")
        exit(1)
    chosen_command = custom_command.split()

# Initialize build variables
build_success = False
attempt = 0
MAX_ATTEMPTS = 10

# Start the build + fix loop
while not build_success and attempt < MAX_ATTEMPTS:
    attempt += 1
    print(f"\n🔄 Build attempt {attempt} of {MAX_ATTEMPTS}...\n")
    print(f"🏗️ Running: {' '.join(chosen_command)}")

    returncode, stdout, stderr = run_build_command(chosen_command)
    print("STDOUT:\n", stdout)
    print("STDERR:\n", stderr)

    if returncode == 0:
        print("✅ Build succeeded! No errors to fix.")
        build_success = True
        break

    print("❌ Build failed. Trying to auto-fix...")

    error_message = stderr.strip() or stdout.strip()
    filepath, line_number = extract_file_and_line(error_message)

    if filepath and line_number:
        filepath = os.path.normpath(filepath)
        print(f"\n🛠 Detected error in file: {filepath} at line {line_number}")
    else:
        print("\n⚠️ Could not detect file path and line number. Exiting.")
        exit(1)

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"❌ Failed to read file {filepath}: {e}")
        break

    context_snippet = "".join(lines)

    # Prompt the LLM for a fix
    prompt = f"""
I tried running `{' '.join(chosen_command)}` but it failed with this error:

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

    user_approval = input("\n❓ Do you want to replace the original file with the corrected code? (yes/no): ").strip().lower()
    if user_approval in ["yes", "y"]:
        replace_lines_in_file(filepath, corrected_code)
        print("✅ Code updated successfully. Retrying build...\n")
    else:
        print("🚫 Skipping code replacement. Will generate a new fix next attempt.\n")

# Final block
if build_success:
    create_github_actions_workflow(project_type, java_distribution='adoptopenjdk')
    create_repo()
    push_to_github()
else:
    print("❌ Build failed after maximum retry attempts. Aborting.")
    exit(1)
