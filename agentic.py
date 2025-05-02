import os
import subprocess
import re
from openai import OpenAI
import requests
import shutil
import stat

# === 1. ASK FOR GITHUB TOKEN, USERNAME, REPO NAME ===
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

import re

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

def create_github_actions_workflow(project_type, java_distribution='adoptopenjdk'):
    # Workflow template with placeholders
    workflow_template = f"""
name: CI/CD Pipeline

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup .NET SDK
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '8.0.x'

      - name: Restore dependencies
        run: dotnet restore

      - name: Build
        run: dotnet build --configuration Release --no-restore

      - name: Test
        run: dotnet test --no-build --verbosity normal

      - name: Publish
        run: dotnet publish -c Release -o ./publish

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: dotnet-artifacts
          path: ./publish/
          if-no-files-found: error
"""
    
    # Write the dynamic workflow to the .github/workflows directory
    workflow_file_path = '.github/workflows/ci.yml'
    
    # Ensure the .github and workflows directories exist
    os.makedirs(os.path.dirname(workflow_file_path), exist_ok=True)
    
    try:
        with open(workflow_file_path, 'w') as f:
            f.write(workflow_template)
        print(f"✅ GitHub Actions workflow created for {project_type} project with {java_distribution} Java distribution.")
    except Exception as e:
        print(f"❌ Error creating workflow: {e}")




# --- MAIN FLOW ---

project_type, project_files = identify_project_type()

# ✨ Add this snippet right here for validation
for filename, content in project_files:
    if filename == "pom.xml" and re.search(r"<groupId>.*?</groupId>", content):
        print("✅ Confirmed Maven pom.xml by regex match.")
    if filename == "go.mod" and re.search(r"module\s+[^\s]+", content):
        print("✅ Confirmed Go module by regex match.")
# Build commands for different project types
# Determine build command
build_command = None

if project_type == "nodejs":
    build_command = ["npm", "run", "build"]
elif project_type == "python":
    build_command = ["python", "setup.py", "install"]
elif project_type == "dotnet":
    build_command = ["dotnet", "build"]
elif project_type == "java":
    # Further check if Maven or Gradle
    if any(file == "pom.xml" for file, _ in project_files):
        print("☕ Detected Java Maven project.")
        build_command = ["mvn", "clean", "install"]
    elif any(file == "build.gradle" for file, _ in project_files):
        print("☕ Detected Java Gradle project.")
        build_command = ["gradle", "build"]
    else:
        print("❌ Java project detected, but no pom.xml or build.gradle found.")
        exit(1)
elif project_type == "go":
    print("🐹 Detected Go project.")
    build_command = ["go", "build", "./..."]
else:
    print("❌ Unknown project type. Cannot determine build command.")
    exit(1)



# Print the build command to the console
print(f"🔵 Building the {project_type} project...")
print(f"🔧 Executing build command: {' '.join(build_command)}")
build_success = False
attempt = 0
MAX_ATTEMPTS = 10  # Try maximum 3 times to auto-fix and build
# Run the build command
while not build_success and attempt < MAX_ATTEMPTS:
    attempt += 1
    print(f"\n🔄 Build attempt {attempt} of {MAX_ATTEMPTS}...\n")
    returncode, stdout, stderr = run_build_command(build_command)
    print("STDOUT:\n", stdout)
    print("STDERR:\n", stderr)

    if returncode == 0:
        print("✅ Build succeeded! No errors to fix.")
        build_success = True
        break
    else:
        print("❌ Build failed. Trying to auto-fix...")

    error_message = stderr.strip() or stdout.strip()

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
    continue

if build_success:
    create_github_actions_workflow(project_type, java_distribution='adoptopenjdk')
    create_repo()  # Call the function to create the repo
    push_to_github()  # Call the function to commit the code to GitHub
    # Call the function to create the workflow based on the project type
else:
    print("❌ Build failed after maximum retry attempts. Aborting.")
    exit(1)