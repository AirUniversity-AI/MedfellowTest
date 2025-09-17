import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import QuestionManager from "./components/QuestionManager";
import QuestionGeneration from "./components/QuestionGeneration";
import QuestionExplanations from "./components/QuestionExplanations";
import DeleteDescription from "./components/DeleteDescription";

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<QuestionManager />} />
        <Route path="/explanations" element={<QuestionExplanations />} />
        <Route path="/generate" element={<QuestionGeneration />} />
        <Route path="/delete" element={<DeleteDescription />} />
      </Routes>
    </Router>
  );
}

export default App;
