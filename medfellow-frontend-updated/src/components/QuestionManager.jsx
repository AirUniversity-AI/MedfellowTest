import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { CONSTANTS } from '../utils/constants';


export default function QuestionManager() {
  const BASELINE_URL = process.env.REACT_APP_BASELINE_URL

  const [selectedCategory, setSelectedCategory] = useState("");
  const [selectedSubject, setSelectedSubject] = useState("");
  const [selectedTopic, setSelectedTopic] = useState("");
  const [subjects, setSubjects] = useState([]);
  const [topics, setTopics] = useState([]);
  const [showTable, setShowTable] = useState(false);
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [entriesPerPage, setEntriesPerPage] = useState(50);
  const navigate = useNavigate();


  // Hardcoded data



  useEffect(() => {
    // Reset when category changes
    setSelectedSubject("");
    setSelectedTopic("");
    setTopics([]);
    setShowTable(false);
    setQuestions([]);

    if (selectedCategory) {
      // Set loading state for UI feedback
      setLoading(true);

      // Simulate API delay
      fetch(`${BASELINE_URL}/fetch-subjects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ categoryId: selectedCategory }),
      })
        .then((res) => res.json())
        .then((data) => {
          // console.log("Data is ",data)
          setSubjects(
            (data.data || []).map((item) => ({
              id: item.id,
              name: item.subjectName,
              categoryId: item.categoryId,

            }))
          );

          setLoading(false);
        })
        .catch((err) => {
          console.error("Failed to fetch subjects:", err);
          setSubjects([]);
          setLoading(false);
        });
    }
  }, [selectedCategory]);

  useEffect(() => {
    // Reset topic when subject changes
    setSelectedTopic("");
    setShowTable(false);
    setQuestions([]);

    if (selectedSubject) {
      // Set loading state for UI feedback
      setLoading(true);

      // Simulate API delay
      fetch(`${BASELINE_URL}/fetch-topics`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subjectId: selectedSubject }),
      })
        .then((res) => res.json())
        .then((data) => {
          if (data?.status === "success") {
            
            const formatted = (data.data || []).map((item) => ({
              id: item.id,
              name: item.topicName,
              subjectId: item.subjectId,
              
            }));
            setTopics(formatted);
          } else {
            setTopics([]);
          }
          setLoading(false);
        })
        .catch((err) => {
          console.error("Failed to fetch topics:", err);
          setTopics([]);
          setLoading(false);
        });
    }
  }, [selectedSubject]);

  const handleSubmit = () => {
    if (!selectedTopic) return;

    setLoading(true);
    fetch(`${BASELINE_URL}/fetch-questions-by-topic`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topicId: selectedTopic }),
    })
      .then((res) => res.json())
      .then((data) => {
        setQuestions(data.data || []);
        setShowTable(true);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to fetch questions:", err);
        setQuestions([]);
        setLoading(false);
      });
  };

  // Filter questions based on search term
  const filteredQuestions = questions.filter(
    (question) =>
      question.question?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      question.explanation?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (question.questionId?.toString() || "").includes(searchTerm)
  );

  // Limit questions based on entriesPerPage unless "All" is selected
  const displayQuestions =
    entriesPerPage === "All"
      ? filteredQuestions
      : filteredQuestions.slice(0, parseInt(entriesPerPage));

  return (
    <div className="p-2 sm:p-4 md:p-6 bg-gray-100 min-h-screen">
      {/* Header with title and buttons */}
      <div className="flex flex-col xs:flex-row justify-between items-center mb-4 gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold">Questions</h1>
        </div>

        {/* Header Buttons */}
        <div className="flex flex-wrap justify-center xs:justify-end space-x-6 w-full xs:w-auto">
          <button
            onClick={() => navigate("/explanations")}
            className="bg-[#2a2f62] text-white px-2 sm:px-3 py-1 sm:py-2 rounded hover:bg-blue-900 flex items-center text-xs sm:text-sm"
          >
            Question Explanation
          </button>

          <button
            onClick={() => navigate("/delete")}
            className="bg-[#2a2f62] text-white px-2 sm:px-3 py-1 sm:py-2 rounded hover:bg-blue-900 flex items-center text-xs sm:text-sm"
          >
            Delete Explanation
          </button>

          
          <button
            onClick={() => navigate("/generate")}
            className="bg-[#2a2f62] text-white px-2 sm:px-3 py-1 sm:py-2 rounded hover:bg-blue-900 text-xs sm:text-sm"
          >
            Question Generation
          </button>
        </div>
      </div>

      <div className="bg-white p-2 sm:p-4 shadow rounded mb-4 sm:mb-6">
        <h2 className="font-semibold mb-3 sm:mb-4 text-sm sm:text-base">
          All Questions
        </h2>

        {/* Filters */}
        <div className="flex flex-col gap-2 sm:gap-3 md:gap-4 mb-3 sm:mb-4">
          <div className="w-full">
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              className="border border-gray-300 p-1 sm:p-2 rounded w-full text-xs sm:text-sm"
            >
              <option value="">Select Category</option>
              {CONSTANTS.CATEGORIES.map((cat) => (
                <option key={cat.id} value={cat.id}>
                  {cat.name}
                </option>
              ))}
            </select>
          </div>

          <div className="w-full">
            <select
              value={selectedSubject}
              onChange={(e) => setSelectedSubject(e.target.value)}
              disabled={!selectedCategory || loading}
              className={`border border-gray-300 p-1 sm:p-2 rounded w-full text-xs sm:text-sm ${(!selectedCategory || loading) && "bg-gray-100"
                }`}
            >
              <option value="">Select Subject</option>
              {subjects.map((sub) => (
                <option key={sub.id} value={sub.id}>
                  {sub.name}
                </option>
              ))}
            </select>
          </div>

          <div className="w-full">
            <select
              value={selectedTopic}
              onChange={(e) => setSelectedTopic(e.target.value)}
              disabled={!selectedSubject || loading}
              className={`border border-gray-300 p-1 sm:p-2 rounded w-full text-xs sm:text-sm ${(!selectedSubject || loading) && "bg-gray-100"
                }`}
            >
              <option value="">Select Topic</option>
              {topics.map((topic) => (
                <option key={topic.id} value={topic.id}>
                  {topic.name}
                </option>
              ))}
            </select>
          </div>

          {selectedTopic && (
            <div className="w-full sm:w-auto">
              <button
                onClick={handleSubmit}
                disabled={loading}
                className={`bg-[#2a2f62] text-white px-3 sm:px-4 py-1 sm:py-2 rounded hover:bg-blue-900 text-xs sm:text-sm w-full sm:w-auto ${loading ? "opacity-50 cursor-not-allowed" : ""
                  }`}
              >
                Submit
              </button>
            </div>
          )}
        </div>

        {/* Search and entries per page */}
        {showTable && (
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-3 sm:mb-4 gap-2 sm:gap-0">
            <div className="flex items-center space-x-1 sm:space-x-2 text-xs sm:text-sm">
              <span>Show</span>
              <select
                className="border border-gray-300 p-1 rounded text-xs sm:text-sm"
                value={entriesPerPage}
                onChange={(e) => setEntriesPerPage(e.target.value)}
              >
                <option value="50">50</option>
                <option value="100">100</option>
                <option value="All">All</option>
              </select>
              <span>entries</span>
            </div>
            <div className="relative w-full sm:w-auto">
              <input
                type="text"
                placeholder="Search..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="border border-gray-300 p-1 sm:p-2 rounded w-full text-xs sm:text-sm"
              />
            </div>
          </div>
        )}

        {/* Questions Table */}
        {loading ? (
          <div className="text-center py-4 sm:py-8 text-sm">Loading...</div>
        ) : showTable ? (
          <div className="overflow-x-auto -mx-2 sm:mx-0">
            <table className="min-w-full table-auto text-left text-xs sm:text-sm">
              <thead className="bg-[#2a2f62] text-white">
                <tr>
                  <th className="p-1 sm:p-2 md:p-3 w-12 sm:w-16">ID</th>
                  <th className="p-1 sm:p-2 md:p-3">Question</th>
                  <th className="p-1 sm:p-2 md:p-3">Explanation</th>
                </tr>
              </thead>
              <tbody>
                {displayQuestions.length > 0 ? (
                  displayQuestions.map((q) => (
                    <tr
                      key={q.questionId}
                      className="border-t hover:bg-gray-50"
                    >
                      <td className="p-1 sm:p-2 md:p-3">{q.questionId}</td>
                      <td className="p-1 sm:p-2 md:p-3">
                        <div className="break-words">{q.question}</div>
                      </td>
                      <td className="p-1 sm:p-2 md:p-3">
                        <div className="break-words">{q.description}</div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="3" className="text-center p-4">
                      No questions match your search criteria.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : (
          selectedTopic &&
          !loading && (
            <p className="text-center py-4 sm:py-8 text-gray-500 text-xs sm:text-sm">
              No questions found for the selected filters.
            </p>
          )
        )}
      </div>
    </div>
  );
}
