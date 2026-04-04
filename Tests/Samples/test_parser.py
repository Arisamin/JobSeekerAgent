import os
import json

def run_parser_test(sample_file):
    print(f"--- RUNNING TEST ON: {sample_file} ---")
    
    # 1. Load your Identity & Requirements
    with open('MY_CONTEXT.md', 'r') as f:
        context = f.read()
    with open('JOB_HUNTER_PERSONA.md', 'r') as f:
        persona = f.read()
        
    # 2. Load the Sample Job Description
    with open(sample_file, 'r', encoding='utf-8') as f:
        job_description = f.read()

    # 3. Construct the "Test Prompt"
    test_prompt = f"""
    SYSTEM INSTRUCTIONS:
    {persona}

    USER CONTEXT (Ariel Samin):
    {context}

    JOB DESCRIPTION TO ANALYZE:
    {job_description}
    """
    
    # 4. Output for your Paid Copilot
    print("\n[INSTRUCTION] Copy the text below and paste it into your Copilot Chat to verify the logic:")
    print("-" * 30)
    print(test_prompt)

if __name__ == "__main__":
    # Test the positive case first
    run_parser_test('Tests/Samples/positive_match.txt')