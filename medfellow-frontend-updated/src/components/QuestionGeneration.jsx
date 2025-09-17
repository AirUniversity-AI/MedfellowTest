import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

export default function GenerateMCQs() {
  const BASELINE_URL = process.env.REACT_APP_BASELINE_URL
  const [pdfFile, setPdfFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [taskId, setTaskId] = useState(() => localStorage.getItem("activeTaskId") || null);
  const [progress, setProgress] = useState("");
  const [downloadUrl, setDownloadUrl] = useState(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();


  const loadingRef = useRef(loading); // Keep track of the loading state synchronously
  
    // Sync loading state with ref
    useEffect(() => {
      loadingRef.current = loading;
    }, [loading]);

  useEffect(() => {
    const handleBeforeUnload = (e) => {
      console.log("Befor eload is called")
      if (localStorage.getItem("activeTaskId") || loadingRef.current) {
        e.preventDefault();
        e.returnValue = "A task is still running. Are you sure you want to leave?";
      }
    };
    // Send cancel request when page is unloading (refresh or close)
    const handleUnload = () => {
      const taskId = localStorage.getItem("activeTaskId");
      if (taskId) {
        console.log("Task has been send successfully")
        navigator.sendBeacon(`${BASELINE_URL}/cancel-mcq-task/${taskId}`);
        localStorage.removeItem("activeTaskId");  // Clean up the task ID
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    window.addEventListener("unload", handleUnload);

    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
      window.removeEventListener("unload", handleUnload);
    };
  }, []);


  const handlePdfChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (file.type !== "application/pdf") {
      alert("❌ Only PDF files are allowed.");
      e.target.value = null;
      setPdfFile(null);
      return;
    }

    setPdfFile(file);
    setProgress("");
    setDownloadUrl(null);
    setError("");
  };

  const startGeneration = async () => {
    if (!pdfFile) {
      alert("Please upload a PDF file.");
      return;
    }

    setLoading(true);
    setProgress("📤 Uploading file...");
    setDownloadUrl(null);
    setError("");

    const formData = new FormData();
    formData.append("pdf", pdfFile);

    try {
      const res = await fetch(`${BASELINE_URL}/start-generate-mcqs`, {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to start generation.");

      const newTaskId = data.task_id;
      localStorage.setItem("activeTaskId", newTaskId);
      setTaskId(newTaskId);

      // 🔄 Start polling immediately, not later
      setProgress("🛰 Starting generation...");
      resumePolling(newTaskId);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };



  const resumePolling = (taskIdToResume) => {
    setLoading(true);
    let lastProgress = "";

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${BASELINE_URL}/mcq-status/${taskIdToResume}`);
        const data = await res.json();

        if (data.error) {
          clearInterval(interval);
          setError(data.error);
          localStorage.removeItem("activeTaskId");
          setTaskId(null);
          setLoading(false);
          return;
        }

        // 🔄 Only update if progress changed (avoids flicker)
        if (data.progress && data.progress !== lastProgress) {
          console.log("📡 Updating progress:", data.progress);
          lastProgress = data.progress;
          setProgress(data.progress);
        }

        if (data.status === "completed") {
          clearInterval(interval);
          setDownloadUrl(data.download_url);
          setProgress("✅ Generation complete.");
          localStorage.removeItem("activeTaskId");
          setTaskId(null);
          setLoading(false);
        } else if (data.status === "error") {
          clearInterval(interval);
          setError(data.error);
          setLoading(false);
          setTaskId(null);
          localStorage.removeItem("activeTaskId");
        }
      } catch (err) {
        clearInterval(interval);
        setError("Failed to fetch task status.");
        setLoading(false);
        localStorage.removeItem("activeTaskId");
        setTaskId(null);
      }
    }, 1000);
  };




  return (
    <div className="p-4 bg-gray-100 min-h-screen">
      <div className="flex flex-col sm:flex-row justify-between items-center mb-4 gap-3">
        <h1 className="text-2xl font-bold">Question Generation</h1>
        <div className="flex space-x-4">
          <button disabled={loading} onClick={() => navigate("/")} className="bg-[#2a2f62] text-white px-3 py-2 rounded hover:bg-blue-900 text-sm">View Questions</button>
          <button disabled={loading} onClick={() => navigate("/explanations")} className="bg-[#2a2f62] text-white px-3 py-2 rounded hover:bg-blue-900 text-sm">Question Explanations</button>
        </div>
      </div>

      <div className="bg-white p-6 shadow rounded">
        <h2 className="font-semibold mb-4 text-base">Generate from PDF</h2>
        <div className="space-y-4 mb-6">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Upload PDF File</label>
            <input
              type="file"
              accept="application/pdf"
              onChange={handlePdfChange}
              className="block w-full text-sm border p-2 rounded"
              disabled={loading}
            />
          </div>

          <button
            onClick={startGeneration}
            disabled={!pdfFile || loading}
            className={`bg-[#2a2f62] text-white px-4 py-2 rounded hover:bg-blue-900 text-sm w-full ${!pdfFile || loading ? "opacity-50 cursor-not-allowed" : ""}`}
          >
            {loading ? "Processing..." : "Generate Questions"}
          </button>
        </div>

        {progress && (
          <div className="mb-4 p-3 bg-gray-50 border border-gray-200 rounded text-blue-800 text-sm font-medium">
            {progress}
          </div>
        )}

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-300 rounded text-red-800 text-sm font-medium">
            {error}
          </div>
        )}

        {downloadUrl && (
          <div className="mt-4 p-3 bg-green-50 border border-green-300 rounded text-green-800 text-sm font-medium">
            ✅ Download your MCQs: {" "}
            <a href={downloadUrl} target="_blank" rel="noopener noreferrer" className="underline text-blue-700">
              Click here
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
