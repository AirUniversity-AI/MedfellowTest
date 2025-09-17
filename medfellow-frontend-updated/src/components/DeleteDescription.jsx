import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CONSTANTS } from "../utils/constants";

export default function DeleteDescription() {
  const BASELINE_URL = process.env.REACT_APP_BASELINE_URL;
  const navigate = useNavigate();

  const [mode, setMode] = useState("id");
  const [questionId, setQuestionId] = useState("");

  const [categoryId, setCategoryId] = useState("");
  const [subjects, setSubjects] = useState([]);
  const [subjectId, setSubjectId] = useState("");
  const [subjectName, setSubjectName] = useState("");

  const [topics, setTopics] = useState([]);
  const [topicId, setTopicId] = useState("");
  const [topicName, setTopicName] = useState("");

  const [statusMessage, setStatusMessage] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!categoryId) return;
    setSubjects([]);
    setSubjectId("");
    setSubjectName("");
    setTopics([]);
    setTopicId("");
    setTopicName("");

    fetch(`${BASELINE_URL}/fetch-subjects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ categoryId: parseInt(categoryId) }),
    })
      .then((res) => res.json())
      .then((data) => setSubjects(data.data || []));
  }, [categoryId]);

  useEffect(() => {
    if (!subjectId) return;
    const subject = subjects.find((s) => s.id == subjectId);
    setSubjectName(subject?.subjectName || "");

    setTopics([]);
    setTopicId("");
    setTopicName("");

    fetch(`${BASELINE_URL}/fetch-topics`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subjectId: parseInt(subjectId) }),
    })
      .then((res) => res.json())
      .then((data) => setTopics(data.data || []));
  }, [subjectId]);

  useEffect(() => {
    const topic = topics.find((t) => t.id == topicId);
    setTopicName(topic?.topicName || "");
  }, [topicId]);

  const handleDeleteById = async () => {
    if (!questionId) return alert("Please enter a Question ID.");
    setLoading(true);
    setStatusMessage("Deleting explanation for the question...");

    try {
      const res = await fetch(`${BASELINE_URL}/delete-description`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ questionId: parseInt(questionId) }),
      });
      const result = await res.json();
      setStatusMessage(getMessage(result));
    } catch (e) {
      setStatusMessage("❌ Failed to delete. Try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteByTopic = async () => {
    if (!categoryId || !subjectName || !topicName) {
      return alert("Please complete all selections.");
    }

    setLoading(true);
    setStatusMessage("Deleting all explanations under selected topic...");

    try {
      const res = await fetch(`${BASELINE_URL}/delete-question-descriptions-by-topic`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          categoryId: parseInt(categoryId),
          subjectName,
          topicName,
        }),
      });

      const result = await res.json();
      setStatusMessage(getMessage(result));
    } catch (e) {
      setStatusMessage("❌ Request failed.");
    } finally {
      setLoading(false);
    }
  };

  const getMessage = (res) => {
    if (res.status === "success") return `✅ ${res.message}`;
    if (res.status === "no") return `⚠️ ${res.message}`;
    return `❌ ${res.message || "Unknown error"}`;
  };

  return (
    <div className="p-4 bg-gray-100 min-h-screen">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold">Delete Explanation</h1>
        <div className="flex gap-3">
          <button onClick={() => navigate("/")} className="bg-[#2a2f62] text-white px-3 py-1 rounded hover:bg-blue-900 text-sm">
            View Questions
          </button>
          <button onClick={() => navigate("/generate")} className="bg-[#2a2f62] text-white px-3 py-1 rounded hover:bg-blue-900 text-sm">
            Question Generation
          </button>
        </div>
      </div>

      <div className="bg-white p-4 shadow rounded">
        <div className="flex gap-4 mb-4">
          <button onClick={() => setMode("id")} className={`px-4 py-2 rounded ${mode === "id" ? "bg-blue-900 text-white" : "bg-gray-200"}`}>
            Delete by ID
          </button>
          <button onClick={() => setMode("topic")} className={`px-4 py-2 rounded ${mode === "topic" ? "bg-blue-900 text-white" : "bg-gray-200"}`}>
            Delete by Topic
          </button>
        </div>

        {mode === "id" ? (
          <div className="space-y-4">
            <input
              type="number"
              value={questionId}
              onChange={(e) => setQuestionId(e.target.value)}
              className="border p-2 rounded w-full"
              placeholder="Enter Question ID"
            />
            <button onClick={handleDeleteById} disabled={loading} className="bg-[#2a2f62] text-white px-4 py-2 w-full rounded hover:bg-blue-900">
              {loading ? "Processing..." : "Delete Description"}
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)} className="border p-2 rounded w-full">
              <option value="">Select Category</option>
              {CONSTANTS.CATEGORIES.map((cat) => (
                <option key={cat.id} value={cat.id}>{cat.name}</option>
              ))}
            </select>

            <select value={subjectId} onChange={(e) => setSubjectId(e.target.value)} className="border p-2 rounded w-full">
              <option value="">Select Subject</option>
              {subjects.map((subj) => (
                <option key={subj.id} value={subj.id}>{subj.subjectName}</option>
              ))}
            </select>

            <select value={topicId} onChange={(e) => setTopicId(e.target.value)} className="border p-2 rounded w-full">
              <option value="">Select Topic</option>
              {topics.map((top) => (
                <option key={top.id} value={top.id}>{top.topicName}</option>
              ))}
            </select>

            <button onClick={handleDeleteByTopic} disabled={loading} className="bg-[#2a2f62] text-white px-4 py-2 w-full rounded hover:bg-blue-900">
              {loading ? "Processing..." : "Delete All Descriptions"}
            </button>
          </div>
        )}

        {statusMessage && (
          <div className="mt-4 p-3 bg-gray-50 border border-gray-300 rounded text-sm text-gray-700">
            {statusMessage}
          </div>
        )}
      </div>
    </div>
  );
}
