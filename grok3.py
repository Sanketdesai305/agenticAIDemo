import os
import subprocess
import re
import logging
import json
from typing import Optional, Tuple, List
import requests
import shutil
import stat
from openai import OpenAI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration class for managing settings
class Config:
    def __init__(self):
        self.github_token = input("Please enter your GitHub token: ")
        self.github_username = input("Please enter your GitHub username: ")
        self.repo_name = input("Please enter the repository name to create: ")
        self.base_dir = os.path.abspath(os.path.join(os.getcwd(), os.pardir))
        self.project_dir = os.getcwd()  # Use current working directory
        self.llm_client = OpenAI(
            base_url="http://localhost:1234/v1",
            api_key="lm-studio"
        )

# Project type detection and management
class ProjectManager:
    IMPORTANT_FILES = [
        'package.json', 'requirements.txt', 'setup.py', 'pyproject.toml',
        'pom.xml', '.csproj', '.sln', 'build.gradle', 'go.mod'
    ]

    @staticmethod
    def identify_project_type(project_dir: str) -> Tuple[str, List[Tuple[str, str]]]:
        """Identify project type based on key configuration files."""
        top_level_files = os.listdir(project_dir)
        existing_configs = []

        for file in top_level_files:
            if file in ProjectManager.IMPORTANT_FILES or file.endswith(('.csproj', '.sln', '.go')):
                file_path = os.path.join(project_dir, file)
                if os.path.isfile(file_path):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        existing_configs.append((file, content))
                    except Exception as e:
                        logger.error(f"Error reading {file_path}: {e}")

        # Determine project type
        if any(f.endswith('.csproj') or f.endswith('.sln') for f in top_level_files):
            return "dotnet", existing_configs
        elif 'package.json' in top_level_files:
            return "nodejs", existing_configs
        elif any(f in ['requirements.txt', 'setup.py'] for f in top_level_files):
            return "python", existing_configs
        elif any(f in ['pom.xml', 'build.gradle'] for f in top_level_files):
            return "java", existing_configs
        elif any(f == 'go.mod' or f.endswith('.go') for f in top_level_files):
            return "go", existing_configs
        return "unknown", existing_configs

    @staticmethod
    def get_build_command(project_type: str, project_files: List[Tuple[str, str]]) -> Optional[List[str]]:
        """Determine the appropriate build command for the project type."""
        if project_type == "nodejs":
            return ["npm", "run", "build"]
        elif project_type == "python":
            return ["python", "setup.py", "install"]
        elif project_type == "dotnet":
            return ["dotnet", "build"]
        elif project_type == "java":
            if any(file == "pom.xml" for file, _ in project_files):
                logger.info("Detected Java Maven project")
                return ["mvn", "clean", "install"]
            elif any(file == "build.gradle" for file, _ in project_files):
                logger.info("Detected Java Gradle project")
                return ["gradle", "build"]
            logger.error("Java project detected, but no pom.xml or build.gradle found")
            return None
        elif project_type == "go":
            logger.info("Detected Go project")
            return ["go", "build", "./..."]
        logger.error("Unknown project type")
        return None

# GitHub operations
class GitHubManager:
    def __init__(self, config: Config):
        self.config = config

    def create_repo(self) -> bool:
        """Create a new GitHub repository."""
        url = "https://api.github.com/user/repos"
        headers = {"Authorization": f"token {self.config.github_token}"}
        data = {"name": self.config.repo_name, "private": False}

        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 201:
                logger.info(f"Repository '{self.config.repo_name}' created successfully")
                return True
            elif response.status_code == 422:
                logger.warning("Repository already exists, continuing")
                return True
            else:
                logger.error(f"Failed to create repository: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error during repository creation: {e}")
            return False

    def remove_git_directory(self) -> bool:
        """Remove existing .git directory."""
        git_dir = os.path.join(self.config.project_dir, ".git")
        if not os.path.exists(git_dir):
            logger.info(".git directory not found")
            return True

        try:
            for root, dirs, files in os.walk(git_dir):
                for file in files:
                    os.chmod(os.path.join(root, file), stat.S_IWRITE)
            shutil.rmtree(git_dir)
            logger.info("Successfully removed .git directory")
            return True
        except Exception as e:
            logger.error(f"Error removing .git directory: {e}")
            return False

    def push_to_github(self) -> bool:
        """Initialize git repository and push to GitHub."""
        try:
            os.chdir(self.config.project_dir)
            commands = [
                ["git", "init"],
                ["git", "remote", "add", "origin", 
                 f"https://{self.config.github_username}:{self.config.github_token}@github.com/{self.config.github_username}/{self.config.repo_name}.git"],
                ["git", "checkout", "-b", "main"],
                ["git", "add", "."],
                ["git", "commit", "-m", "initial commit"],
                ["git", "push", "-u", "origin", "main"]
            ]

            for cmd in commands:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    logger.error(f"Git command failed: {' '.join(cmd)}\n{result.stderr}")
                    return False
            logger.info("Successfully pushed code to GitHub")
            return True
        except Exception as e:
            logger.error(f"Error pushing to GitHub: {e}")
            return False

# Build and fix operations
class BuildManager:
    def __init__(self, config: Config):
        self.config = config

    @staticmethod
    def run_build_command(build_command: List[str]) -> Tuple[int, str, str]:
        """Execute a build command and capture output."""
        try:
            result = subprocess.run(
                build_command,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
                shell=isinstance(build_command, str)
            )
            return result.returncode, result.stdout, result.stderr
        except Exception as e:
            return 1, "", str(e)

    @staticmethod
    def extract_file_and_line(error_message: str) -> Tuple[Optional[str], Optional[int]]:
        """Extract file path and line number from error message."""
        # C#/.NET style
        match = re.search(r'([A-Za-z]:\\[^\(:]+\.cs)\((\d+),\d+\)', error_message)
        if match:
            return match.group(1), int(match.group(2))

        # JS/TS/Python/etc.
        match = re.search(r'([a-zA-Z0-9_\-\\/.]+(?:\.js|\.jsx|\.ts|\.tsx|\.py|\.cs|\.java|\.go)):(\d+)', error_message)
        if match:
            return match.group(1), int(match.group(2))

        return None, None

    @staticmethod
    def extract_code_from_response(response_text: str) -> str:
        """Extract code block from LLM response."""
        match = re.search(r'```(?:\w+)?\n(.*?)\n```', response_text, re.DOTALL)
        return match.group(1).strip() if match else response_text.strip()

    @staticmethod
    def replace_file_content(filepath: str, corrected_code: str) -> bool:
        """Replace entire file content with corrected code."""
        try:
            filepath = os.path.abspath(filepath)
            logger.info(f"Modifying file: {filepath}")
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(corrected_code)
            logger.info(f"Successfully updated file: {filepath}")
            return True
        except Exception as e:
            logger.error(f"Error replacing file content: {e}")
            return False

    def create_github_actions_workflow(self, project_type: str, java_distribution: str = 'adoptopenjdk') -> bool:
        """Create GitHub Actions workflow based on project type."""
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
"""

    # Add steps for each project type
    if project_type == "dotnet":
        workflow_template += """
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
    elif project_type == "nodejs":
        workflow_template += """
      - name: Setup Node.js
        uses: actions/setup-node@v2
        with:
          node-version: '14'  # Replace with your desired Node.js version
      - name: Install dependencies
        run: npm install
      - name: Build
        run: npm run build
      - name: Test
        run: npm test
      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          name: nodejs-artifacts
          path: ./dist  # Adjust to your build output path
          if-no-files-found: error
"""
    elif project_type == "python":
        workflow_template += """
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Run Tests
        run: pytest
"""
    elif project_type == "java":
        workflow_template += f"""
      - name: Set up JDK
        uses: actions/setup-java@v4
        with:
          distribution: '{java_distribution}'
          java-version: '17'
      - name: Build with Maven
        run: mvn -B package --file pom.xml
"""
    elif project_type == "go":
        workflow_template += """
      - name: Set up Go
        uses: actions/setup-go@v4
        with:
          go-version: '1.21'
      - name: Build
        run: go build ./...
      - name: Test
        run: go test ./...
"""
    else:
        print(f"❌ Unsupported project type: {project_type}")
        return

        workflow_path = os.path.join(self.config.project_dir, '.github', 'workflows', 'main.yml')
        os.makedirs(os.path.dirname(workflow_path), exist_ok=True)

        try:
            with open(workflow_path, 'w', encoding='utf-8') as f:
                f.write(workflow_template.strip() + '\n')
            logger.info(f"GitHub Actions workflow created at {workflow_path}")
            return True
        except Exception as e:
            logger.error(f"Error creating workflow: {e}")
            return False

    def build_and_fix(self, project_type: str, build_command: List[str]) -> bool:
        """Attempt to build the project and fix errors automatically."""
        MAX_ATTEMPTS = 10
        attempt = 0

        while attempt < MAX_ATTEMPTS:
            attempt += 1
            logger.info(f"Build attempt {attempt} of {MAX_ATTEMPTS}")
            returncode, stdout, stderr = self.run_build_command(build_command)
            logger.debug(f"STDOUT:\n{stdout}")
            logger.debug(f"STDERR:\n{stderr}")

            if returncode == 0:
                logger.info("Build succeeded")
                return True

            logger.warning("Build failed, attempting to fix")
            error_message = stderr.strip() or stdout.strip()
            filepath, line_number = self.extract_file_and_line(error_message)

            if not filepath or not line_number:
                logger.error("Could not detect file path and line number")
                return False

            filepath = os.path.normpath(filepath)
            logger.info(f"Detected error in file: {filepath} at line {line_number}")

            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    context_snippet = f.read()
            except Exception as e:
                logger.error(f"Failed to read file {filepath}: {e}")
                return False

            prompt = f"""
I tried running `{' '.join(build_command)}` but it failed with this error:

{error_message}

Here is the entire code in the file:

{context_snippet}

Please provide the corrected code wrapped inside triple backticks:
"""

            try:
                response = self.config.llm_client.completions.create(
                    model="mistral-7b-instruct-v0.1",
                    prompt=prompt,
                    max_tokens=1000
                )
                corrected_code = self.extract_code_from_response(response.choices[0].text.strip())
                logger.debug(f"Corrected code:\n{corrected_code}")

                if self.replace_file_content(filepath, corrected_code):
                    logger.info("Retrying build after applying fix")
                    continue
            except Exception as e:
                logger.error(f"Error getting LLM response: {e}")
                return False

        logger.error("Build failed after maximum retry attempts")
        return False

def main():
    config = Config()
    github_manager = GitHubManager(config)
    build_manager = BuildManager(config)

    # Identify project type
    project_type, project_files = ProjectManager.identify_project_type(config.project_dir)
    logger.info(f"Detected project type: {project_type}")

    # Validate project configuration
    for filename, content in project_files:
        if filename == "pom.xml" and re.search(r"<groupId>.*?</groupId>", content):
            logger.info("Confirmed Maven pom.xml")
        if filename == "go.mod" and re.search(r"module\s+[^\s]+", content):
            logger.info("Confirmed Go module")

    # Get build command
    build_command = ProjectManager.get_build_command(project_type, project_files)
    if not build_command:
        logger.error("Failed to determine build command")
        return

    logger.info(f"Executing build command: {' '.join(build_command)}")

    # Build and fix
    if build_manager.build_and_fix(project_type, build_command):
        # Create workflow and push to GitHub
        if (build_manager.create_github_actions_workflow(project_type) and 
            github_manager.create_repo() and 
            github_manager.remove_git_directory() and 
            github_manager.push_to_github()):
            logger.info("Pipeline completed successfully")
        else:
            logger.error("Failed to complete GitHub operations")
    else:
        logger.error("Build process failed")

if __name__ == "__main__":
    main()