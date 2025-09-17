import json
import os
import asyncio
import logging
import uuid
import httpx
from quart import Quart, request, jsonify
import json
from openai import OpenAI
from dotenv import load_dotenv
from quart_cors import cors
from q_generation_func import (
    extract_pdf_text,
    sliding_window_chunks,
    is_clinically_relevant,
    generate_mcqs_with_assistant,
    deduplicate_mcqs,
    mcqs_to_excel
)
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader
from io import BytesIO
import sys
import aiomysql
import pymysql

sys.stdout.reconfigure(encoding='utf-8')

# Load env and configure logging
load_dotenv()
logging.basicConfig(level=logging.INFO)

# OpenAI Configuration
API_KEY = os.getenv("OPENAI_API_KEY")
EX_ASSISTANT_ID = os.getenv("EX_ASSISTANT_ID")
GEN_ASSISTANT_ID = os.getenv("GEN_ASSISTANT_ID")

# MySQL Configuration
MYSQL_HOST = os.getenv("MYSQL_HOST", "tramway.proxy.rlwy.net")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "51549"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "railway")

if not API_KEY or not EX_ASSISTANT_ID or not GEN_ASSISTANT_ID:
    raise ValueError("Missing OpenAI credentials.")

if not MYSQL_PASSWORD:
    raise ValueError("Missing MySQL credentials.")

client = OpenAI(api_key=API_KEY)
app = Quart(__name__)
app = cors(app, allow_origin="*")

task_status = {}
running_tasks = {}

# Database connection pool
db_pool = None


async def init_db_pool():
    """Initialize database connection pool"""
    global db_pool
    try:
        db_pool = await aiomysql.create_pool(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            db=MYSQL_DATABASE,
            charset='utf8mb4',
            autocommit=True,
            maxsize=20,
            minsize=1,
            connect_timeout=30,
        )
        print(f"✅ Database pool initialized successfully")
        print(f"🔗 Connected to: {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")

        # Test the connection
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1")
                result = await cursor.fetchone()
                print(f"🔍 Connection test result: {result}")

    except Exception as e:
        print(f"❌ Failed to initialize database pool: {e}")
        print(f"🔍 Connection details: {MYSQL_HOST}:{MYSQL_PORT} as {MYSQL_USER}")
        raise


async def execute_query(query, params=None):
    """Execute database query and return results in PHP-like format"""
    global db_pool
    if not db_pool:
        await init_db_pool()

    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            try:
                await cursor.execute(query, params or ())

                if query.strip().upper().startswith('SELECT'):
                    result = await cursor.fetchall()
                    # Convert to list of dicts to match PHP response format
                    return {"data": [dict(row) for row in result]}
                else:
                    # For INSERT, UPDATE, DELETE operations
                    return {"affected_rows": cursor.rowcount}

            except Exception as e:
                print(f"❌ Database query failed: {e}")
                print(f"🔍 Query: {query}")
                print(f"🔍 Params: {params}")
                return {"error": str(e)}


@app.route("/get-remaining-question-count", methods=["POST"])
async def get_remaining_question_count():
    data = await request.get_json()
    category_id = int(data.get("categoryId"))
    subject_name = data.get("subjectName")
    topic_name = data.get("topicName")

    print(category_id, subject_name, topic_name)

    # Get subject ID
    query_subject = "SELECT id FROM subject WHERE categoryId = %s AND subjectName = %s"
    subject_resp = await execute_query(query_subject, (category_id, subject_name))
    subject_data = subject_resp.get("data", [])
    if not subject_data:
        return jsonify({"count": 0})
    subject_id = subject_data[0]["id"]

    # Get topic ID
    query_topic = "SELECT id FROM topics WHERE subjectId = %s AND topicName = %s"
    topic_resp = await execute_query(query_topic, (subject_id, topic_name))
    topic_data = topic_resp.get("data", [])
    if not topic_data:
        return jsonify({"count": 0})
    topic_id = topic_data[0]["id"]

    # Get question IDs
    query_ids = "SELECT questionId FROM topicQueRel WHERE topicId = %s"
    ids_resp = await execute_query(query_ids, (topic_id,))
    question_data = ids_resp.get("data", [])
    question_ids = [str(row["questionId"]) for row in question_data]
    if not question_ids:
        return jsonify({"count": 0})

    # Count questions with NULL description
    ids_placeholders = ",".join(["%s"] * len(question_ids))
    query_count = f"SELECT COUNT(*) AS count FROM tblquestion WHERE questionId IN ({ids_placeholders}) AND (description IS NULL OR TRIM(description) = '')"

    count_resp = await execute_query(query_count, question_ids)
    count_data = count_resp.get("data", [])
    count = count_data[0]["count"] if count_data else 0

    print("Count:", count)
    return jsonify({"count": count})


@app.route("/generate-category-questions", methods=["POST"])
async def generate_category_questions():
    try:
        data = await request.get_json()
        category_id = int(data.get("categoryId"))
        subject_name = data.get("subjectName")
        topic_name = data.get("topicName")

        print(f"[INIT TASK] categoryId={category_id}, subject={subject_name}, topic={topic_name}", flush=True)

        task_id = str(uuid.uuid4())
        task_status[task_id] = {"status": "started", "progress": 0, "results": [], "error": None}

        task = asyncio.create_task(process_question_generation(task_id, category_id, subject_name, topic_name))
        running_tasks[task_id] = task

        return jsonify({"status": "started", "taskId": task_id})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/task-status/<task_id>", methods=["GET"])
async def task_status_check(task_id):
    task = task_status.get(task_id)
    if not task:
        return jsonify({"status": "not_found"}), 404
    return jsonify(task)


@app.route("/cancel-task/<task_id>", methods=["POST", "GET"])
async def cancel_task(task_id):
    task = running_tasks.get(task_id)
    if task and not task.done():
        task.cancel()
        print(f"[CANCEL] Task {task_id} was cancelled by user.", flush=True)
    task_status[task_id]["status"] = "cancelled"
    task_status[task_id]["error"] = "Cancelled by user."
    running_tasks.pop(task_id, None)
    return "", 200


# Configurable timeout constants
SETUP_TIMEOUT = 10
DB_TIMEOUT = 10
MAX_WAIT_SECONDS = 120


async def safe_to_thread(func, *args, timeout=SETUP_TIMEOUT, **kwargs):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args, **kwargs),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        print("⚠️ Timeout in to_thread call, skipping...")
        return None


async def process_question_generation(task_id, category_id, subject_name, topic_name):
    try:
        # Get subject ID
        query_subject = "SELECT id FROM subject WHERE categoryId = %s AND subjectName = %s"
        subject = await execute_query(query_subject, (category_id, subject_name))
        if not subject.get("data"):
            raise Exception("Subject not found")
        subject_id = subject.get("data", [])[0]["id"]

        # Get topic ID
        query_topic = "SELECT id FROM topics WHERE subjectId = %s AND topicName = %s"
        topic = await execute_query(query_topic, (subject_id, topic_name))
        if not topic.get("data"):
            raise Exception("Topic not found")
        topic_id = topic.get("data", [])[0]["id"]

        # Get question IDs
        query_ids = "SELECT questionId FROM topicQueRel WHERE topicId = %s"
        ids_resp = await execute_query(query_ids, (topic_id,))
        question_data = ids_resp.get("data", [])
        if not isinstance(question_data, list) or not question_data:
            raise Exception("No questions found")
        question_ids = [str(row["questionId"]) for row in question_data]

        # Get questions
        ids_placeholders = ",".join(["%s"] * len(question_ids))
        query_questions = f"SELECT questionId, question, description FROM tblquestion WHERE questionId IN ({ids_placeholders}) AND (description IS NULL OR TRIM(description) = '')"

        questions_resp = await execute_query(query_questions, question_ids)
        questions = questions_resp.get("data", [])

        if not questions:
            task_status[task_id] = {
                "status": "completed",
                "progress": 0,
                "results": [],
                "error": "All questions already explained."
            }
            return

        # Get options
        query_options = f"SELECT questionId, questionImageText, isCorrectAnswer FROM tblquestionoption WHERE questionId IN ({ids_placeholders})"
        options_resp = await execute_query(query_options, question_ids)
        options = options_resp.get("data", [])

        label_map = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

        for idx, q in enumerate(questions, start=1):
            try:
                if task_id not in running_tasks:
                    raise asyncio.CancelledError()

                await asyncio.sleep(0)  # yield control

                q_opts = [opt for opt in options if opt["questionId"] == q["questionId"]]
                correct = next((opt for opt in q_opts if opt["isCorrectAnswer"] == "1"), None)

                labeled_opts = []
                correct_label = ""
                for i, opt in enumerate(q_opts):
                    label = label_map[i]
                    labeled_opts.append(f"{label}. {opt['questionImageText']}")
                    if opt["isCorrectAnswer"] == "1":
                        correct_label = label

                prompt = (
                        f"Question: {q['question']}\nOptions:\n" +
                        "\n".join(labeled_opts) +
                        f"\nCorrect Answer: {correct_label}\n\nExplain why the correct option is right."
                )

                thread = await safe_to_thread(
                    client.beta.threads.create,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=SETUP_TIMEOUT
                )
                if thread is None:
                    raise Exception("Failed to create thread")

                run = await safe_to_thread(
                    client.beta.threads.runs.create,
                    thread_id=thread.id,
                    assistant_id=EX_ASSISTANT_ID,
                    timeout=SETUP_TIMEOUT
                )
                if run is None:
                    raise Exception("Failed to start run")

                for wait_count in range(MAX_WAIT_SECONDS):
                    if task_id not in running_tasks:
                        print(f"[MCQ TASK] {task_id} - Detected cancellation during wait.")
                        raise asyncio.CancelledError()

                    run = await safe_to_thread(
                        client.beta.threads.runs.retrieve,
                        thread_id=thread.id,
                        run_id=run.id,
                        timeout=SETUP_TIMEOUT
                    )
                    if run is None:
                        continue  # skip this loop if timeout

                    if run.status == "completed":
                        break

                    await asyncio.sleep(1)
                else:
                    raise Exception(f"Timeout waiting for assistant response on question {idx}")

                messages = await safe_to_thread(
                    client.beta.threads.messages.list,
                    thread_id=thread.id,
                    timeout=SETUP_TIMEOUT
                )
                if messages is None or not messages.data:
                    raise Exception("Failed to retrieve messages")

                explanation = messages.data[0].content[0].text.value
                try:
                    explanation_json = json.loads(explanation)
                    final_explanation = explanation_json.get("explanation", explanation)
                except Exception:
                    final_explanation = explanation

                update_query = "UPDATE tblquestion SET description = %s WHERE questionId = %s"
                response = await execute_query(update_query, (final_explanation, int(q['questionId'])))

                if response.get("error"):
                    raise Exception("DB update failed")

                task_status[task_id]["results"].append({
                    "index": idx,
                    "questionId": q["questionId"],
                    "question": q.get("question", ""),
                    "options": [opt.get("questionImageText", "") for opt in q_opts],
                    "correctAnswer": correct["questionImageText"] if correct else None,
                    "explanation": final_explanation
                })

                task_status[task_id]["progress"] = idx

            except asyncio.CancelledError:
                print(f"❌ [ABORTED] Task {task_id} cancelled during question {idx}.")
                raise

            except Exception as inner_e:
                print(f"🔥 [ERROR] Question {idx} failed {inner_e}")
                task_status[task_id]["results"].append({
                    "index": idx,
                    "questionId": q["questionId"],
                    "error": str(inner_e)
                })

        task_status[task_id]["status"] = "completed"
        print(f"🏁 [TASK COMPLETE] All questions processed.")

    except Exception as outer_e:
        print(f"[TASK ERROR] {outer_e}")
        task_status[task_id] = {
            "status": "failed",
            "error": str(outer_e)
        }


@app.route("/fetch-questions-by-topic", methods=["POST"])
async def fetch_questions_by_topic():
    try:
        data = await request.get_json()
        topic_id = data.get("topicId")
        print("Topic id is", topic_id)

        if not topic_id:
            return jsonify({"error": "Missing topicId"}), 400

        # Step 1: Fetch question IDs linked to the topic
        query_ids = "SELECT questionId FROM topicQueRel WHERE topicId = %s"
        response_ids = await execute_query(query_ids, (topic_id,))

        if response_ids.get("error"):
            return jsonify({"error": "Failed to fetch question IDs"}), 500

        id_data = response_ids
        print("Raw topic-question ID data:", id_data)

        # ✅ Correct extraction of questionId values from response
        rows = id_data.get("data", [])
        question_ids = [row["questionId"] for row in rows if row.get("questionId")]
        print("Extracted question IDs:", question_ids)

        if not question_ids:
            return jsonify([])

        # Step 2: Build query for full questions
        ids_placeholders = ",".join(["%s"] * len(question_ids))
        query_questions = f"SELECT * FROM tblquestion WHERE questionId IN ({ids_placeholders})"
        print("Final question query:", query_questions)

        response_questions = await execute_query(query_questions, question_ids)

        if response_questions.get("error"):
            return jsonify({"error": "Failed to fetch questions"}), 500

        questions = response_questions
        print("Fetched questions:", questions)

        return jsonify(questions)

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fetch-subjects", methods=["POST"])
async def fetch_subjects():
    try:
        data = await request.get_json()
        category_id = data.get("categoryId")

        if not category_id:
            return jsonify({"error": "Missing categoryId"}), 400

        # Prepare the SQL query
        sql_query = "SELECT * FROM subject WHERE categoryId = %s"

        # Make database query
        response = await execute_query(sql_query, (category_id,))

        if response.get("error"):
            return jsonify({"error": "Failed to query external DB"}), 500

        # Return the response in the same format as before
        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/fetch-topics", methods=["POST"])
async def fetch_topics():
    try:
        data = await request.get_json()
        subject_id = data.get("subjectId")

        if not subject_id:
            return jsonify({"error": "Missing subjectId"}), 400

        sql_query = "SELECT * FROM topics WHERE subjectId = %s"

        response = await execute_query(sql_query, (subject_id,))

        if response.get("error"):
            return jsonify({"error": "Failed to query external DB"}), 500

        # Return response in the same format as before
        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
async def health():
    try:
        # Test database connection
        test_query = "SELECT 1 as test"
        result = await execute_query(test_query)

        if result.get("data") and result["data"][0]["test"] == 1:
            return jsonify({
                "status": "healthy",
                "database": "connected",
                "host": MYSQL_HOST,
                "database": MYSQL_DATABASE
            }), 200
        else:
            return jsonify({"status": "unhealthy", "database": "disconnected"}), 500

    except Exception as e:
        return jsonify({"status": "unhealthy", "database": "error", "error": str(e)}), 500


mcq_tasks = {}

# ==================================== QUESTION GENERATION
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Cloudinary Config
cloudinary.config(
    cloud_name="dgxolaza9",
    api_key="163384472599539",
    api_secret="V6r9rqUvsenV9VBM1SBKEZep2sM",
    secure=True
)


@app.route('/start-generate-mcqs', methods=['POST'])
async def start_generate_mcqs():
    try:
        form_files = await request.files
        pdf = form_files.get('pdf')

        if not pdf:
            return jsonify({'error': 'No PDF uploaded'}), 400

        task_id = str(uuid.uuid4())
        mcq_tasks[task_id] = {
            'status': 'queued',
            'progress': 'Queued',
            'download_url': None,
            'error': None
        }

        filename = secure_filename(pdf.filename)
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{task_id}_{filename}")
        file_bytes = pdf.read()
        file_buffer = BytesIO(file_bytes)

        # ✅ Launch the async task and store it for cancellation support
        task = asyncio.create_task(save_and_process(file_buffer, task_id, pdf_path, filename))

        mcqs_running_tasks[task_id] = task

        # Important: wrap the task with cleanup
        async def wrapped_task():
            try:
                await task
            except asyncio.CancelledError:
                print(f"[CANCELLED] Task {task_id} was cancelled.", flush=True)
                mcq_tasks[task_id]['status'] = 'cancelled'
                mcq_tasks[task_id]['error'] = 'Task was cancelled by user.'
            except Exception as e:
                print(f"[ERROR] Task {task_id} failed with error: {str(e)}", flush=True)
                mcq_tasks[task_id]['status'] = 'error'
                mcq_tasks[task_id]['error'] = str(e)
            finally:
                # Always clean up from the running task registry
                mcqs_running_tasks.pop(task_id, None)
                print(f"[CLEANUP] Task {task_id} removed from running tasks.", flush=True)

        # Run the wrapped task
        asyncio.create_task(wrapped_task())

        return jsonify({'task_id': task_id}), 202

    except Exception as outer_e:
        print(f"[STARTUP ERROR] Failed to launch MCQ task: {str(outer_e)}", flush=True)
        return jsonify({'error': str(outer_e)}), 500


async def save_and_process(file_buffer: BytesIO, task_id, pdf_path, filename):
    try:
        # Save PDF file to the designated path
        with open(pdf_path, 'wb') as f:
            f.write(file_buffer.read())

        # Proceed with MCQ generation
        await process_mcqs_task(task_id, pdf_path, filename)

    except Exception as e:
        mcq_tasks[task_id]['status'] = 'error'
        mcq_tasks[task_id]['error'] = str(e)
        print(f"[MCQ TASK] {task_id} - ERROR: {str(e)}")


mcqs_running_tasks = {}


@app.route("/cancel-mcq-task/<task_id>", methods=["POST", "GET"])
async def cancel_mcq_task(task_id):
    print("CANCEL MCQ IS CALLED")
    task = mcqs_running_tasks.get(task_id)
    if task and not task.done():
        task.cancel()
        print(f"[CANCEL] Task {task_id} was cancelled by user.", flush=True)
    mcq_tasks[task_id]["status"] = "cancelled"
    mcq_tasks[task_id]["error"] = "Cancelled by user."
    mcqs_running_tasks.pop(task_id, None)
    return "", 200


@app.route('/mcq-status/<task_id>', methods=['GET'])
async def get_mcq_status(task_id):
    task_info = mcq_tasks.get(task_id)
    if not task_info:
        return jsonify({'error': 'Invalid task ID'}), 404
    return jsonify(task_info)


async def process_mcqs_task(task_id, pdf_path, filename):
    try:
        mcq_tasks[task_id]['status'] = 'processing'
        mcq_tasks[task_id]['progress'] = 'Extracting text...'
        print(f"[MCQ TASK] {task_id} - {mcq_tasks[task_id]['progress']}")
        await asyncio.sleep(0)  # Ensure async context

        # Extract text from PDF (blocking operation offloaded to a thread)
        full_text = await asyncio.to_thread(extract_pdf_text, pdf_path)
        await asyncio.sleep(0)

        # Chunk the extracted text
        chunks = await asyncio.to_thread(sliding_window_chunks, full_text, 1200, 600)
        await asyncio.sleep(0)

        # Check if the content is clinically relevant
        is_relevant = await asyncio.to_thread(is_clinically_relevant, client, chunks[0])
        if not is_relevant:
            mcq_tasks[task_id]['status'] = 'error'
            mcq_tasks[task_id]['error'] = 'PDF is not clinically relevant'
            return

        all_mcqs = []
        for i, chunk in enumerate(chunks[:4]):
            if task_id not in mcqs_running_tasks:
                print(f"[MCQ TASK] {task_id} - Detected cancellation before chunk {i + 1}.", flush=True)
                raise asyncio.CancelledError()
            mcq_tasks[task_id]['progress'] = f'Processing chunk {i + 1} of {len(chunks)}...'
            print(f"[MCQ TASK] {task_id} - {mcq_tasks[task_id]['progress']}")
            await asyncio.sleep(0)

            # Generate MCQs for each chunk (offload OpenAI interaction)
            mcqs = await asyncio.to_thread(generate_mcqs_with_assistant, client, GEN_ASSISTANT_ID, task_id,
                                           mcqs_running_tasks, chunk)
            all_mcqs.extend(mcqs)

        # Deduplicate the generated MCQs
        mcq_tasks[task_id]['progress'] = 'Exporting MCQs to Excel...'
        print(f"[MCQ TASK] {task_id} - {mcq_tasks[task_id]['progress']}")
        await asyncio.sleep(0)

        final_mcqs = await asyncio.to_thread(deduplicate_mcqs, all_mcqs)
        temp_excel_path = os.path.join("/tmp", filename.replace('.pdf', '_mcqs.xlsx'))

        # Export MCQs to Excel
        await asyncio.to_thread(mcqs_to_excel, final_mcqs, temp_excel_path)

        mcq_tasks[task_id]['progress'] = 'Uploading to Cloudinary...'
        print(f"[MCQ TASK] {task_id} - {mcq_tasks[task_id]['progress']}")
        await asyncio.sleep(0)

        # Upload the Excel file to Cloudinary
        upload_result = await asyncio.to_thread(
            cloudinary.uploader.upload,
            temp_excel_path,
            resource_type="raw",
            folder="mcqs_outputs",
            public_id=filename.replace('.pdf', '_mcqs'),
            use_filename=True,
            unique_filename=False,
            overwrite=True
        )

        mcq_tasks[task_id]['status'] = 'completed'
        mcq_tasks[task_id]['progress'] = '✅ Generation complete.'
        mcq_tasks[task_id]['download_url'] = upload_result.get('secure_url')
        print(f"[MCQ TASK] {task_id} - Task completed.")

    except Exception as e:
        mcq_tasks[task_id]['status'] = 'error'
        mcq_tasks[task_id]['error'] = str(e)
        print(f"[MCQ TASK] {task_id} - ERROR: {str(e)}")


@app.route("/delete-description", methods=["POST"])
async def delete_question_description():
    try:
        data = await request.get_json()
        question_id = int(data.get("questionId"))

        if not question_id:
            return jsonify({"status": "error", "message": "Missing questionId"}), 400

        # Step 1: Check if description exists
        check_query = "SELECT description FROM tblquestion WHERE questionId = %s"
        check_response = await execute_query(check_query, (question_id,))
        check_data = check_response.get("data", [])

        if not check_data or not check_data[0].get("description"):
            return jsonify({"status": "no", "message": "No description to remove."})

        # Step 2: Nullify the description
        nullify_query = "UPDATE tblquestion SET description = NULL WHERE questionId = %s"
        update_response = await execute_query(nullify_query, (question_id,))

        if not update_response.get("error"):
            return jsonify({"status": "success", "message": f"Description removed for questionId={question_id}"})
        else:
            return jsonify({"status": "error", "message": "DB update failed"}), 500

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/generate-missing-descriptions", methods=["POST"])
async def generate_missing_descriptions():
    try:
        print("HIT /generate-missing-descriptions", flush=True)

        task_id = str(uuid.uuid4())
        task_status[task_id] = {
            "status": "queued",
            "progress": "Queued",
            "results": [],
            "error": None
        }

        task = asyncio.create_task(process_all_questions_without_description(task_id))
        running_tasks[task_id] = task

        async def wrapped_task():
            try:
                await task
            except asyncio.CancelledError:
                print(f"[CANCELLED] Task {task_id}", flush=True)
                task_status[task_id]["status"] = "cancelled"
                task_status[task_id]["error"] = "Cancelled by user."
            except Exception as e:
                print(f"[ERROR] Task {task_id} failed: {str(e)}", flush=True)
                task_status[task_id]["status"] = "failed"
                task_status[task_id]["error"] = str(e)
            finally:
                print(f"[CLEANUP] Task {task_id} removed from registry.", flush=True)
                running_tasks.pop(task_id, None)

        asyncio.create_task(wrapped_task())

        return jsonify({"status": "started", "taskId": task_id})
    except Exception as e:
        print(f"[ROUTE ERROR] Failed to launch task: {str(e)}", flush=True)
        return jsonify({"status": "error", "error": str(e)}), 500


def batchify(iterable, size=50):
    from itertools import islice
    iterable = iter(iterable)
    while True:
        batch = list(islice(iterable, size))
        if not batch:
            break
        yield batch


@app.route("/get_all_question_count", methods=["GET"])
async def get_all_question_count():
    query = "SELECT COUNT(*) AS count FROM tblquestion WHERE description IS NULL"
    resp = await execute_query(query)
    return jsonify(resp)


async def process_all_questions_without_description(task_id):
    print("HIT generate-missing-descriptions route")
    try:
        print(f"[TASK START] Global explanation generation task started: {task_id}")

        print("Fetching all questions with NULL descriptions...")
        query = "SELECT questionId FROM tblquestion WHERE description IS NULL"
        response = await execute_query(query)
        question_ids = [int(row["questionId"]) for row in response.get("data", [])]

        if not question_ids:
            print("No questions found with NULL description. Exiting.")
            task_status[task_id] = {
                "status": "completed",
                "progress": 0,
                "results": [],
                "error": "All questions already have explanations."
            }
            return

        print(f"{len(question_ids)} question(s) to process.")
        label_map = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

        idx = 0
        for batch_ids in batchify(question_ids, size=50):
            ids_placeholders = ",".join(["%s"] * len(batch_ids))

            query_q = f"SELECT questionId, question FROM tblquestion WHERE questionId IN ({ids_placeholders})"
            response_questions = await execute_query(query_q, batch_ids)
            questions = response_questions.get("data", [])

            query_opts = f"SELECT questionId, questionImageText, isCorrectAnswer FROM tblquestionoption WHERE questionId IN ({ids_placeholders})"
            response_options = await execute_query(query_opts, batch_ids)
            options = response_options.get("data", [])

            for q in questions:
                idx += 1
                try:
                    if task_id not in running_tasks:
                        raise asyncio.CancelledError()

                    await asyncio.sleep(0)

                    q_opts = [opt for opt in options if opt["questionId"] == q["questionId"]]
                    correct = next((opt for opt in q_opts if opt["isCorrectAnswer"] == "1"), None)

                    if not q_opts:
                        raise Exception("No options found.")

                    labeled_opts = []
                    correct_label = ""
                    for i, opt in enumerate(q_opts):
                        label = label_map[i]
                        labeled_opts.append(f"{label}. {opt['questionImageText']}")
                        if opt["isCorrectAnswer"] == "1":
                            correct_label = label

                    prompt = (
                            f"Question: {q['question']}\nOptions:\n" +
                            "\n".join(labeled_opts) +
                            f"\nCorrect Answer: {correct_label}\n\nExplain why the correct option is right."
                    )

                    thread = await safe_to_thread(
                        client.beta.threads.create,
                        messages=[{"role": "user", "content": prompt}],
                        timeout=SETUP_TIMEOUT
                    )
                    if thread is None:
                        raise Exception("Failed to create thread")

                    run = await safe_to_thread(
                        client.beta.threads.runs.create,
                        thread_id=thread.id,
                        assistant_id=EX_ASSISTANT_ID,
                        timeout=SETUP_TIMEOUT
                    )
                    if run is None:
                        raise Exception("Failed to start run")

                    for _ in range(MAX_WAIT_SECONDS):
                        if task_id not in running_tasks:
                            raise asyncio.CancelledError()

                        run = await safe_to_thread(
                            client.beta.threads.runs.retrieve,
                            thread_id=thread.id,
                            run_id=run.id,
                            timeout=SETUP_TIMEOUT
                        )
                        if run and run.status == "completed":
                            break
                        await asyncio.sleep(1)
                    else:
                        raise Exception("Assistant timeout")

                    messages = await safe_to_thread(
                        client.beta.threads.messages.list,
                        thread_id=thread.id,
                        timeout=SETUP_TIMEOUT
                    )
                    if not messages or not messages.data:
                        raise Exception("No assistant message returned")

                    explanation = messages.data[0].content[0].text.value
                    try:
                        explanation_json = json.loads(explanation)
                        final_explanation = explanation_json.get("explanation", explanation)
                    except Exception:
                        final_explanation = explanation

                    update_query = "UPDATE tblquestion SET description = %s WHERE questionId = %s"
                    update_response = await execute_query(update_query, (final_explanation, int(q['questionId'])))

                    if update_response.get("error"):
                        raise Exception("DB update failed")

                    task_status[task_id]["results"].append({
                        "index": idx,
                        "questionId": q["questionId"],
                        "question": q["question"],
                        "options": [opt["questionImageText"] for opt in q_opts],
                        "correctAnswer": correct["questionImageText"] if correct else None,
                        "explanation": final_explanation
                    })
                    task_status[task_id]["progress"] = idx

                except asyncio.CancelledError:
                    print(f"[CANCELLED] Task {task_id} during question {idx}")
                    raise
                except Exception as e:
                    print(f"[ERROR] Question {idx} (ID={q['questionId']}) failed {e}")
                    task_status[task_id]["results"].append({
                        "index": idx,
                        "questionId": q["questionId"],
                        "error": str(e)
                    })

        task_status[task_id]["status"] = "completed"
        print(f"[TASK DONE] Task {task_id} finished processing {idx} questions.")

    except Exception as outer_e:
        print(f"[FATAL TASK ERROR] Task {task_id} {outer_e}")
        task_status[task_id] = {
            "status": "failed",
            "error": str(outer_e)
        }


@app.route("/delete-question-descriptions-by-topic", methods=["POST"])
async def delete_question_descriptions_by_topic():
    try:
        data = await request.get_json()
        category_id = int(data.get("categoryId"))
        subject_name = data.get("subjectName")
        topic_name = data.get("topicName")

        # Step 1: Resolve subjectId
        query_subject = "SELECT id FROM subject WHERE categoryId = %s AND subjectName = %s"
        res_sub = await execute_query(query_subject, (category_id, subject_name))
        subject_data = res_sub.get("data", [])
        if not subject_data:
            return jsonify({"status": "error", "message": "Subject not found"}), 404
        subject_id = subject_data[0]["id"]

        # Step 2: Resolve topicId
        query_topic = "SELECT id FROM topics WHERE subjectId = %s AND topicName = %s"
        res_topic = await execute_query(query_topic, (subject_id, topic_name))
        topic_data = res_topic.get("data", [])
        if not topic_data:
            return jsonify({"status": "error", "message": "Topic not found"}), 404
        topic_id = topic_data[0]["id"]

        # Step 3: Get relevant questionIds
        query_qids = "SELECT questionId FROM topicQueRel WHERE topicId = %s"
        res_qids = await execute_query(query_qids, (topic_id,))
        qid_data = res_qids.get("data", [])
        if not qid_data:
            return jsonify({"status": "error", "message": "No questions linked to this topic"}), 404
        question_ids = [str(row["questionId"]) for row in qid_data]

        # Step 4: Delete descriptions
        ids_placeholders = ",".join(["%s"] * len(question_ids))
        update_query = f"UPDATE tblquestion SET description = NULL WHERE questionId IN ({ids_placeholders})"
        res_update = await execute_query(update_query, question_ids)

        if not res_update.get("error"):
            return jsonify(
                {"status": "success", "message": f"Descriptions removed from {len(question_ids)} questions."})
        else:
            return jsonify({"status": "error", "message": "Failed to update descriptions"}), 500

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/get-all-topic-question-count", methods=["POST"])
async def get_all_topic_question_count():
    try:
        data = await request.get_json()
        category_id = int(data.get("categoryId"))
        subject_name = data.get("subjectName")

        # Step 1: Get subject ID
        query_subject = "SELECT id FROM subject WHERE categoryId = %s AND subjectName = %s"
        res_sub = await execute_query(query_subject, (category_id, subject_name))
        subject_data = res_sub.get("data", [])
        if not subject_data:
            raise Exception("Subject not found")

        subject_id = subject_data[0]["id"]

        # Step 2: Count all questions with NULL description in all topics
        query_count = """
            SELECT COUNT(*) as total FROM tblquestion q 
            JOIN topicQueRel rel ON rel.questionId = q.questionId 
            JOIN topics t ON t.id = rel.topicId 
            WHERE t.subjectId = %s AND 
            (q.description IS NULL OR TRIM(q.description) = '')
        """
        res_count = await execute_query(query_count, (subject_id,))
        count_data = res_count.get("data", [])
        total = count_data[0]["total"] if count_data else 0

        return jsonify({"status": "success", "count": total})

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


async def process_all_topics_for_subject(task_id: str, category_id: int, subject_name: str):
    count = 0
    try:
        print(
            f"\n🚀 [START] Task {task_id} - Processing all topics for subject '{subject_name}' (categoryId={category_id})")

        # === Subject ID ===
        query_subject = "SELECT id FROM subject WHERE categoryId = %s AND subjectName = %s"
        res_sub = await execute_query(query_subject, (category_id, subject_name))
        subject_data = res_sub.get("data", [])
        if not subject_data:
            raise Exception("Subject not found")
        subject_id = subject_data[0]["id"]
        print(f"✅ Found subject ID: {subject_id}")

        # === Topics ===
        query_topics = "SELECT id, topicName FROM topics WHERE subjectId = %s"
        res_topics = await execute_query(query_topics, (subject_id,))
        topics_data = res_topics.get("data", [])
        if not topics_data:
            raise Exception("No topics found")
        print(f"📚 Found {len(topics_data)} topic(s) under subject '{subject_name}'")

        label_map = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        task_status[task_id] = {"status": "running", "progress": 0, "results": [], "error": None}
        global_index = 0

        for topic in topics_data:
            topic_id = topic["id"]
            topic_name = topic["topicName"]
            print(f"\n▶️ [TOPIC] Starting topic '{topic_name}' (id={topic_id})")

            # === Questions with NULL description ===
            query_qids = """
                SELECT q.questionId, q.question FROM tblquestion q 
                JOIN topicQueRel rel ON rel.questionId = q.questionId 
                WHERE rel.topicId = %s AND 
                (q.description IS NULL OR TRIM(q.description) = '')
            """
            res_qs = await execute_query(query_qids, (topic_id,))
            qs_data = res_qs.get("data", [])
            print(f"🧠 Found {len(qs_data)} question(s) needing explanation in topic '{topic_name}'")

            if not qs_data:
                continue

            question_ids = [str(q["questionId"]) for q in qs_data]
            ids_placeholders = ",".join(["%s"] * len(question_ids))

            # === Options ===
            query_opts = f"SELECT questionId, questionImageText, isCorrectAnswer FROM tblquestionoption WHERE questionId IN ({ids_placeholders})"
            res_opts = await execute_query(query_opts, question_ids)
            opts_data = res_opts.get("data", [])

            for q in qs_data:
                try:
                    global_index += 1
                    qid = q["questionId"]
                    print(f"\n📝 [QUESTION {global_index}] Processing QID={qid}")

                    if task_id not in running_tasks:
                        raise asyncio.CancelledError()

                    await asyncio.sleep(0)

                    q_opts = [opt for opt in opts_data if opt["questionId"] == qid]
                    correct = next((opt for opt in q_opts if opt["isCorrectAnswer"] == "1"), None)

                    if not q_opts or not correct:
                        raise Exception("Missing options or correct answer")

                    labeled_opts = []
                    correct_label = ""
                    for i, opt in enumerate(q_opts):
                        label = label_map[i]
                        labeled_opts.append(f"{label}. {opt['questionImageText']}")
                        if opt["isCorrectAnswer"] == "1":
                            correct_label = label

                    print(f"Question: {q['question']}\nOptions:\n" +
                          "\n".join(labeled_opts) +
                          f"\nCorrect Answer: {correct_label}\n\nExplain why the correct option is right.")
                    prompt = (
                            f"Remove any RefusalContentBlock text and then answer which of the following definitions correctly matches the concept according to general public health principles\nQuestion: {q['question']}\nOptions:\n" +
                            "\n".join(labeled_opts) +
                            f"\nCorrect Answer: {correct_label}\n\nExplain why the correct option is right."
                    )

                    print(f"🤖 Generating explanation using Assistant API...")

                    thread = await safe_to_thread(
                        client.beta.threads.create,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    run = await safe_to_thread(
                        client.beta.threads.runs.create,
                        thread_id=thread.id,
                        assistant_id=EX_ASSISTANT_ID
                    )

                    for wait in range(MAX_WAIT_SECONDS):
                        if task_id not in running_tasks:
                            raise asyncio.CancelledError()
                        run = await safe_to_thread(
                            client.beta.threads.runs.retrieve,
                            thread_id=thread.id,
                            run_id=run.id
                        )
                        if run and run.status == "completed":
                            break
                        await asyncio.sleep(1)
                    else:
                        raise Exception("Timeout waiting for Assistant")

                    messages = await safe_to_thread(
                        client.beta.threads.messages.list,
                        thread_id=thread.id
                    )

                    first_message = messages.data[0]
                    first_block = first_message.content[0]

                    if hasattr(first_block, "text"):
                        explanation = first_block.text.value
                        try:
                            parsed = json.loads(explanation)
                            final_explanation = parsed.get("explanation", explanation)
                        except Exception:
                            final_explanation = explanation
                    else:
                        print(
                            f"⚠️ [WARNING] OpenAI returned a non-text block ({type(first_block).__name__}) for QID={qid}")
                        final_explanation = f"[OpenAI refused to answer because of privacy issues. Block type: {type(first_block).__name__}]"

                    if "RefusalContentBlock" not in final_explanation:
                        update_query = "UPDATE tblquestion SET description = %s WHERE questionId = %s"
                        update_res = await execute_query(update_query, (final_explanation, int(qid)))
                        if update_res.get("error"):
                            raise Exception("DB update failed")
                        print(f"✅ Explanation stored in DB for QID={qid}")
                    else:
                        print(f"🚫 Skipping DB update for QID={qid} due to OpenAI refusal.")

                    task_status[task_id]["results"].append({
                        "index": global_index,
                        "topic": topic_name,
                        "questionId": qid,
                        "question": q["question"],
                        "options": [opt["questionImageText"] for opt in q_opts],
                        "correctAnswer": correct["questionImageText"],
                        "explanation": final_explanation
                    })
                    task_status[task_id]["progress"] = global_index

                except asyncio.CancelledError:
                    print(
                        f"❌ [CANCELLED] Task {task_id} cancelled during topic '{topic_name}' at question {global_index}")
                    raise
                except Exception as e:
                    print(f"🔥 [ERROR] Question {q['questionId']} failed: {str(e)}")
                    task_status[task_id]["results"].append({
                        "index": global_index,
                        "topic": topic_name,
                        "questionId": q["questionId"],
                        "error": str(e)
                    })

        task_status[task_id]["status"] = "completed"
        print(f"\n🏁 [DONE] Task {task_id} completed. Total questions processed: {global_index}")

    except Exception as fatal:
        print(f"💥 [FATAL ERROR] Task {task_id} failed: {str(fatal)}")
        task_status[task_id] = {
            "status": "failed",
            "error": str(fatal)
        }


@app.route("/generate-all-topic-descriptions", methods=["POST"])
async def generate_all_topic_descriptions():
    try:
        data = await request.get_json()
        category_id = int(data.get("categoryId"))
        subject_name = data.get("subjectName")

        task_id = str(uuid.uuid4())
        task_status[task_id] = {
            "status": "queued",
            "progress": 0,
            "results": [],
            "error": None
        }

        task = asyncio.create_task(process_all_topics_for_subject(task_id, category_id, subject_name))
        running_tasks[task_id] = task

        return jsonify({"status": "started", "taskId": task_id})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# Initialize database pool on startup
@app.before_serving
async def startup():
    await init_db_pool()


# Clean up database pool on shutdown
@app.after_serving
async def shutdown():
    global db_pool
    if db_pool:
        db_pool.close()
        await db_pool.wait_closed()


# === ASGI ENTRYPOINT ===
if __name__ == "__main__":
    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    config = Config()
    asyncio.run(serve(app, config))