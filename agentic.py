from openai import OpenAI
import subprocess
import os
import re

# --- LLM CLIENT ---
client = OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="lm-studio",  # Dummy key
)

# --- HELPER FUNCTIONS ---

def run_npm_build():
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
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
    # Updated regex to handle errors like: C:\path\to\file.js:1
    match = re.search(r'([a-zA-Z0-9_\-\\/.]+(?:\.js|\.jsx|\.ts|\.tsx)):(\d+)', error_message)
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

def replace_line_in_file(filepath, line_number, corrected_code):
    try:
        # Ensure the file path is absolute and properly formatted
        filepath = os.path.abspath(filepath)
        print(f"🔵 Trying to modify: {filepath}")

        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if 1 <= line_number <= len(lines):
            print(f"🔵 Original Line {line_number}: {lines[line_number - 1].strip()}")
            lines[line_number - 1] = corrected_code + '\n'

            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            print(f"\n✅ Successfully updated line {line_number} in {filepath}!")
        else:
            print(f"❌ Line number {line_number} out of range for file {filepath}")
    except Exception as e:
        print(f"❌ Error replacing line in {filepath}: {e}")

# --- MAIN FLOW ---
# --- MAIN FLOW ---
while True:
    stdout, stderr = run_npm_build()
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

    # --- SINGLE PROMPT: Ask for corrected code ONLY ---
    prompt = f"""
I tried running `npm run build` but it failed with this error:

{error_message}

Please provide the corrected code for the broken line wrapped inside triple backticks like this
"""

    response = client.completions.create(
        model="mistral-7b-instruct-v0.1",
        prompt=prompt,
        max_tokens=500
    )

    corrected_code = extract_code_from_response(response.choices[0].text.strip())
    print("\n--- Extracted Corrected Code ---\n", corrected_code)

    # Replace the line in the file with the corrected code
    replace_line_in_file(filepath, line_number, corrected_code)

    print("\n🔁 Retrying build after applying fix...\n")
