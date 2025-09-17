// Final fully working QuestionExplanations component
import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { CONSTANTS } from "../utils/constants";

export default function QuestionExplanations() {
  const BASELINE_URL = process.env.REACT_APP_BASELINE_URL;
  const [selectedCategory, setSelectedCategory] = useState("");
  const [selectedSubject, setSelectedSubject] = useState("");
  const [selectedTopic, setSelectedTopic] = useState("");
  const [subjects, setSubjects] = useState([]);
  const [topics, setTopics] = useState([]);
  const [questionCount, setQuestionCount] = useState(50);
  const [loading, setLoading] = useState(false);
  const [currentQuestionProgress, setCurrentQuestionProgress] = useState("");
  const [generatedQuestionsExplanation, setgeneratedQuestionsExplanation] = useState([]);
  const [taskId, setTaskId] = useState(() => localStorage.getItem("activeTaskId") || null);
  const [globalGeneration, setGlobalGeneration] = useState(false);
  const [generationMode, setGenerationMode] = useState(() => localStorage.getItem("activeGenerationMode") || "topic");
  const [uiDisabled, setUiDisabled] = useState(false);

  const loadingRef = useRef(loading);
  const navigate = useNavigate();
  useEffect(() => { loadingRef.current = loading; }, [loading]);

  const cancelActiveTask = async () => {
    const activeTaskId = localStorage.getItem("activeTaskId");
    if (activeTaskId) {
      try {
        await fetch(`${BASELINE_URL}/cancel-task/${activeTaskId}`, { method: "POST" });
      } catch (error) {
        console.error("Failed to cancel active task:", error);
      }
      localStorage.removeItem("activeTaskId");
      setTaskId(null);
    }
  };


  const fetchSubjects = async (categoryId) => {
    try {
      const res = await fetch(`${BASELINE_URL}/fetch-subjects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ categoryId }),
      });
      const data = await res.json();
      if (data?.data) {
        setSubjects(data.data.map(item => ({ id: item.id, name: item.subjectName, categoryId: item.categoryId })));
      }
    } catch (err) {
      console.error("Failed to fetch subjects:", err);
    }
  };

  const fetchTopics = async (subjectId) => {
    try {
      const res = await fetch(`${BASELINE_URL}/fetch-topics`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subjectId }),
      });
      const data = await res.json();
      if (data?.status === "success") {
        setTopics(data.data.map(item => ({ id: item.id, name: item.topicName, subjectId: item.subjectId })));
      }
    } catch (err) {
      console.error("Failed to fetch topics:", err);
    }
  };

  useEffect(() => {
    if (selectedCategory) {
      fetchSubjects(selectedCategory);
    } else {
      setSubjects([]);
    }
  }, [selectedCategory]);

  useEffect(() => {
    if (selectedSubject) {
      fetchTopics(selectedSubject);
    } else {
      setTopics([]);
    }
  }, [selectedSubject]);

  const generateQuestions = async () => {
    if (!selectedSubject || !selectedCategory || (generationMode === "topic" && !selectedTopic)) {
      alert("Please select category, subject" + (generationMode === "topic" ? ", and topic" : "") + " first.");
      return;
    }
    localStorage.setItem("activeCategoryId", selectedCategory);
    localStorage.setItem("activeSubjectId", selectedSubject);
    localStorage.setItem("activeTopicId", selectedTopic);
    localStorage.setItem("activeGenerationMode", generationMode);

    const subjectObj = subjects.find((s) => String(s.id) === selectedSubject);
    const topicObj = topics.find((t) => String(t.id) === selectedTopic);

    if (!subjectObj || (generationMode === "topic" && !topicObj)) {
      alert("Invalid subject or topic selection.");
      return;
    }

    setLoading(true);
    setUiDisabled(true)
    setGlobalGeneration(generationMode === "allTopics");
    setgeneratedQuestionsExplanation([]);
    setCurrentQuestionProgress("\u23F3 Starting generation task...");

    try {
      if (generationMode === "allTopics") {
        const countRes = await fetch(`${BASELINE_URL}/get-all-topic-question-count`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ categoryId: selectedCategory, subjectName: subjectObj.name }),
        });
        const countData = await countRes.json();
        setQuestionCount(countData?.count || 0);
        localStorage.setItem("activeTaskTotalCount", String(countData?.count || 0));
      } else {
        localStorage.setItem("activeTopicId", selectedTopic);
        localStorage.setItem("activeTopicName", topicObj.name);
      }

      const endpoint = generationMode === "topic" ? "/generate-category-questions" : "/generate-all-topic-descriptions";
      const body = generationMode === "topic"
        ? { categoryId: selectedCategory, subjectName: subjectObj.name, topicName: topicObj.name }
        : { categoryId: selectedCategory, subjectName: subjectObj.name };

      const response = await fetch(`${BASELINE_URL}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const result = await response.json();
      if (!result.taskId) throw new Error("Failed to initiate task.");

      const newTaskId = result.taskId;
      localStorage.setItem("activeTaskId", newTaskId);
      setTaskId(newTaskId);
      resumePolling(newTaskId);
    } catch (err) {
      console.error("Failed to start generation:", err);
      alert("\u274C Could not start question generation.");
      setLoading(false);
      setUiDisabled(false)
    }
  };

  const resumePolling = (taskIdToResume) => {
    setLoading(true);
    setUiDisabled(true)
    setGlobalGeneration(generationMode === "allTopics");
    setCurrentQuestionProgress("\uD83D\uDD04 Resuming task...");
    const pollInterval = setInterval(async () => {
      try {
        const res = await fetch(`${BASELINE_URL}/task-status/${taskIdToResume}`);
        const data = await res.json();

        if (data.status === "error") {
          clearInterval(pollInterval);
          alert(`\u274C Task failed: ${data.error}`);
          localStorage.removeItem("activeTaskId");
          setTaskId(null);
          setLoading(false);
          setUiDisabled(false)
          return;
        }

        if (data.status === "completed" || data.status === "cancelled") {
          clearInterval(pollInterval);
          setgeneratedQuestionsExplanation(data.results || []);
          setCurrentQuestionProgress(data.status === "completed"
            ? "\u2705 All questions generated successfully!"
            : "\u26A0\uFE0F Task was cancelled.");
          localStorage.removeItem("activeTaskId");
          setTaskId(null);
          setUiDisabled(false)
          setLoading(false);
          return;
        }

        setgeneratedQuestionsExplanation(data.results || []);
        setQuestionCount(parseInt(localStorage.getItem("activeTaskTotalCount") || "0"));
        setCurrentQuestionProgress(`\u2699\uFE0F Processed ${data.progress} questions...`);
      } catch (err) {
        clearInterval(pollInterval);
        alert("\u274C Failed to resume task.");
        localStorage.removeItem("activeTaskId");
        setTaskId(null);
        setLoading(false);
        setUiDisabled(false)
      }
    }, 1500);
  };

  useEffect(() => {
    const savedTaskId = localStorage.getItem("activeTaskId");
    const savedMode = localStorage.getItem("activeGenerationMode");
    const savedCategoryId = localStorage.getItem("activeCategoryId");
    const savedSubjectId = localStorage.getItem("activeSubjectId");
    const savedTopicId = localStorage.getItem("activeTopicId");

    if (savedCategoryId) setSelectedCategory(savedCategoryId);
    if (savedMode) setGenerationMode(savedMode);
    if (savedSubjectId) localStorage.setItem("__restore_subject", savedSubjectId);
    if (savedTopicId) localStorage.setItem("__restore_topic", savedTopicId);
    if (savedTaskId) localStorage.setItem("__resume_task", savedTaskId);
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem("__restore_subject");
    if (subjects.length && saved && subjects.find(s => String(s.id) === saved)) {
      setSelectedSubject(saved);
      localStorage.removeItem("__restore_subject");
    }
  }, [subjects]);

  useEffect(() => {
    const savedTopicId = localStorage.getItem("__restore_topic");
    const resumeTaskId = localStorage.getItem("__resume_task");
    const mode = localStorage.getItem("activeGenerationMode");

    if (topics.length && savedTopicId && topics.find(t => String(t.id) === savedTopicId)) {
      setSelectedTopic(savedTopicId);
      localStorage.removeItem("__restore_topic");

      if (resumeTaskId && mode === "topic") {
        setLoading(true);                     // ✅ critical for disabling UI
        setGlobalGeneration(false);          // ✅ ensures topic mode reflects
        setGenerationMode("topic");          // ✅ reinforce mode
        setCurrentQuestionProgress("⏳ Resuming task...");
        resumePolling(resumeTaskId);
        localStorage.removeItem("__resume_task");
      }
    }
  }, [topics]);



  useEffect(() => {
    const resumeTaskId = localStorage.getItem("__resume_task");
    const mode = localStorage.getItem("activeGenerationMode");

    if (resumeTaskId && mode === "allTopics") {
      setGenerationMode("allTopics");
      setGlobalGeneration(true);
      setLoading(true);
      setCurrentQuestionProgress("\uD83D\uDD04 Resuming task...");
      resumePolling(resumeTaskId);
      localStorage.removeItem("__resume_task");
    }



  }, [subjects]);


  useEffect(() => {
    if (!selectedCategory || !selectedSubject || !selectedTopic) return;

    const fetchQuestionCount = async () => {
      setLoading(true);
      try {
        const subjectObj = subjects.find((s) => String(s.id) === selectedSubject);
        const topicObj = topics.find((t) => String(t.id) === selectedTopic);
        const response = await fetch(`${BASELINE_URL}/get-remaining-question-count`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            categoryId: selectedCategory,
            subjectName: subjectObj.name,
            topicName: topicObj.name,
          }),
        });
        const data = await response.json();
        setQuestionCount(data?.count || 0);
        localStorage.setItem("activeTaskTotalCount", String(data?.count || 0));
      } catch (error) {
        console.error("Error fetching question count:", error);
      } finally {
        setLoading(false);
      }
    };
    fetchQuestionCount();
  }, [selectedTopic]);

  useEffect(() => {
    const resumeTaskId = localStorage.getItem("__resume_task");
    const savedMode = localStorage.getItem("activeGenerationMode");

    if (
      resumeTaskId &&
      savedMode === "topic" &&
      selectedCategory &&
      selectedSubject &&
      selectedTopic
    ) {
      setLoading(true);
      setGlobalGeneration(false);
      setCurrentQuestionProgress("⏳ Resuming task...");
      resumePolling(resumeTaskId);
      localStorage.removeItem("__resume_task");
    }
  }, [selectedCategory, selectedSubject, selectedTopic]);


  const handleStopGeneration = async () => {
    await cancelActiveTask();
    setLoading(false);
    setUiDisabled(false);
    setCurrentQuestionProgress("⚠️ Generation stopped by user.");
    setGlobalGeneration(false);
  };


  return (
    <div className="p-2 sm:p-4 md:p-6 bg-gray-100 min-h-screen">
      <div className="flex flex-col xs:flex-row justify-between items-center mb-4 gap-3">
        <h1 className="text-xl sm:text-2xl font-bold">Question Explanation</h1>
        <div className="flex flex-wrap justify-center xs:justify-end space-x-6 w-full xs:w-auto">
          <button onClick={() => navigate("/")} disabled={loading || globalGeneration || uiDisabled} className="bg-[#2a2f62] text-white px-3 py-2 rounded hover:bg-blue-900 text-xs sm:text-sm">View Questions</button>
          <button onClick={() => navigate("/generate")} disabled={loading || globalGeneration || uiDisabled} className="bg-[#2a2f62] text-white px-3 py-2 rounded hover:bg-blue-900 text-xs sm:text-sm">Question Generation</button>
        </div>
      </div>

      <div className="bg-white p-4 shadow rounded mb-6">
        <h2 className="font-semibold mb-4 text-sm sm:text-base">Generate New Question Explanations</h2>
        <div className="space-y-4 mb-6">
          <select value={selectedCategory} onChange={(e) => setSelectedCategory(e.target.value)} disabled={loading || globalGeneration || uiDisabled} className="border border-gray-300 p-2 rounded w-full text-sm">
            <option value="">Select Category</option>
            {CONSTANTS.CATEGORIES.map((cat) => (
              <option key={cat.id} value={cat.id}>{cat.name}</option>
            ))}
          </select>

          <select value={selectedSubject} onChange={(e) => setSelectedSubject(e.target.value)} disabled={!selectedCategory || loading || globalGeneration || uiDisabled} className="border border-gray-300 p-2 rounded w-full text-sm">
            <option value="">Select Subject</option>
            {subjects.map((sub) => (
              <option key={sub.id} value={sub.id}>{sub.name}</option>
            ))}
          </select>

          {generationMode === "topic" && (
            <select value={selectedTopic} onChange={(e) => setSelectedTopic(e.target.value)} disabled={!selectedSubject || loading || globalGeneration || uiDisabled} className="border border-gray-300 p-2 rounded w-full text-sm">
              <option value="">Select Topic</option>
              {topics.map((topic) => (
                <option key={topic.id} value={topic.id}>{topic.name}</option>
              ))}
            </select>
          )}

          <div className="flex items-center space-x-4 text-sm">
            <label className="flex items-center space-x-1">
              <input type="radio" value="topic" checked={generationMode === "topic"} onChange={() => setGenerationMode("topic")} disabled={loading || globalGeneration || uiDisabled} />
              <span>Generate by Topic</span>
            </label>
            <label className="flex items-center space-x-1">
              <input type="radio" value="allTopics" checked={generationMode === "allTopics"} onChange={() => { setGenerationMode("allTopics"); setSelectedTopic(""); }} disabled={loading || globalGeneration || uiDisabled} />
              <span>Generate All Topics (Subject)</span>
            </label>
          </div>

          <button onClick={generateQuestions} disabled={(generationMode === "topic" && !selectedTopic) || loading || globalGeneration || uiDisabled} className="bg-[#2a2f62] text-white px-4 py-2 rounded hover:bg-blue-900 text-sm w-full">
            {loading || uiDisabled
              ? generationMode === "allTopics"
                ? "Generating All Topics..."
                : "Generating..."
              : "Generate Questions"}
          </button>
        </div>

        {taskId && (loading || uiDisabled) && (
          <div className="mb-4">
            <button
              onClick={handleStopGeneration}
              className="bg-red-600 text-white px-4 py-2 rounded hover:bg-red-800 text-sm w-full"
            >
              ⛔ Stop Generation
            </button>
          </div>
        )}

        {currentQuestionProgress && (
          <div className="mb-6 p-3 bg-gray-50 border border-gray-200 rounded text-sm text-blue-800 font-medium">
            {currentQuestionProgress}
          </div>
        )}

        {generatedQuestionsExplanation.length > 0 && (
          <div className="mt-6">
            <h3 className="font-semibold mb-3 text-sm sm:text-base">
              Generated Questions ({generatedQuestionsExplanation.length}/{questionCount})
            </h3>
            <div className="overflow-auto max-h-96">
              {generatedQuestionsExplanation.map((q) => (
                <div key={q.questionId || q.id} className="border-b border-gray-200 py-4">
                  <div className="font-medium mb-2">{q.questionId}. {q.question}</div>
                  <div className="space-y-1 ml-4 text-sm">
                    {q.options?.map((opt, i) => (
                      <div key={i} className={opt === q.correctAnswer ? "text-green-600 font-medium" : ""}>
                        {opt} {opt === q.correctAnswer && "\u2713"}
                      </div>
                    ))}
                  </div>
                  <div className="mt-2 text-sm text-gray-600">
                    <strong>Explanation:</strong> {q.explanation}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
