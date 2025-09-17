import os
import fitz  # PyMuPDF
import pandas as pd
import json
import time

# Extract text from PDF
def extract_pdf_text(file_path):
    doc = fitz.open(file_path)
    full_text = ""
    for page in doc:
        text = page.get_text()
        if text.strip():
            full_text += text.strip() + " "
    return full_text

# Sliding window text chunking
def sliding_window_chunks(text, window_size=1200, step_size=600):
    words = text.split()
    return [" ".join(words[i:i + window_size]) for i in range(0, len(words) - window_size + 1, step_size)]

# Remove duplicate questions
def deduplicate_mcqs(mcq_list):
    seen = set()
    unique_mcqs = []
    for block in mcq_list:
        topic = block.get("topic") or block.get("temat")
        questions = []
        for q in block.get("questions", []):
            if q["question"] not in seen:
                seen.add(q["question"])
                questions.append(q)
        if questions:
            unique_mcqs.append({"temat": topic, "questions": questions})
    return unique_mcqs

# Save to Excel
def mcqs_to_excel(mcq_list, output_path):
    rows = []
    for mcq_block in mcq_list:
        topic = mcq_block.get("topic") or mcq_block.get("temat", "")
        for question_data in mcq_block.get("questions", []):
            rows.append({
                "Temat": topic,
                "Pytanie": question_data.get("question", ""),
                "Opcja A": question_data.get("options", {}).get("A", ""),
                "Opcja B": question_data.get("options", {}).get("B", ""),
                "Opcja C": question_data.get("options", {}).get("C", ""),
                "Opcja D": question_data.get("options", {}).get("D", ""),
                "Poprawna Odpowiedź": question_data.get("answer", ""),
                "Wyjaśnienie": question_data.get("explanation", "")
            })
    df = pd.DataFrame(rows)
    df.to_excel(output_path, index=False)

# Parse assistant response
def parse_assistant_response(response_dict):
    try:
        raw_json = response_dict.get("response")
        if not raw_json:
            raise ValueError("No 'response' key found in function response.")
        return json.loads(raw_json)
    except Exception as e:
        print(f"❌ Failed to parse assistant response: {e}")
        return None

def extract_title_from_text(text):
    # Very naive: use the first Markdown heading
    for line in text.split("\n"):
        if line.strip().startswith("#"):
            return line.strip().replace("#", "").strip()
    return "Unknown Topic"

import asyncio
# Generate MCQs using Assistant
def generate_mcqs_with_assistant(client,assistant_id ,task_id, mcqs_running_tasks, text, min_required=1, max_attempts=3):
    for attempt in range(max_attempts):
        if task_id not in mcqs_running_tasks:
                print(f"[MCQ TASK] {task_id} - Detected cancellation before chunk {i + 1}.", flush=True)
                raise asyncio.CancelledError()
        try:
            thread = client.beta.threads.create()
            client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=text
            )
            run = client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=assistant_id
            )

            max_tries = 20  # 🔁 Will check status up to 20 times (adjust as needed)
            tries = 0

            while tries < max_tries:
                if task_id not in mcqs_running_tasks:
                    print(f"[MCQ TASK] {task_id} - Detected cancellation during run polling.", flush=True)
                    raise asyncio.CancelledError()
                run_status = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

                if run_status.status == "completed":
                    break
                elif run_status.status in ["failed", "cancelled", "expired"]:
                    raise RuntimeError(f"Run failed with status: {run_status.status}")

                tries += 1
                time.sleep(2)

            if tries >= max_tries:
                raise TimeoutError("Exceeded max retries. Run status did not complete in expected time.")

            messages = client.beta.threads.messages.list(thread_id=thread.id)

            for msg in messages.data:
                for block in msg.content:
                    if hasattr(block, "text") and hasattr(block.text, "value"):
                        try:
                            parsed_quiz = json.loads(block.text.value)
                            if parsed_quiz and parsed_quiz.get("questions"):
                                if "topic" not in parsed_quiz or not parsed_quiz["topic"]:
                                    parsed_quiz["topic"] = extract_title_from_text(text)  # or use fallback below
                                    # parsed_quiz["topic"] = "Unknown Topic"  # fallback if no heading extraction logic
                                print("Questions: ", parsed_quiz)
                                return [parsed_quiz]

                        except Exception as e:
                            print(f"⚠️ Failed to parse text block as JSON: {e}")
        except Exception as e:
            print(f"❌ GPT Assistant Error on attempt {attempt + 1}: {e}")
        time.sleep(2)

    return []

def is_clinically_relevant(client, text):
    prompt = (
        "Determine whether the following text is clinically relevant. "
        "Reply only with YES or NO.\n\n"
        f"Text:\n{text[:1500]}"
    )

    print("📝 Prompt sent for clinical relevance check:")
    print("⏳ Waiting for model response...")

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a strict clinical relevance checker."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0,
    )

    answer = response.choices[0].message.content.strip().upper()

    print(f"✅ Model responded with: {answer}")
    return answer == "YES"
