import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import LessonViewer from './pages/LessonViewer';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import DashboardPage from './pages/DashboardPage';
import CoursePage from './pages/CoursePage';
import StudentProgressPage from './pages/StudentProgressPage';

function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="/login/" element={<LoginPage />} />
                <Route path="/register/" element={<RegisterPage />} />
                <Route path="/dashboard/" element={<DashboardPage />} />
                <Route path="/lesson/:lessonId/" element={<LessonViewer />} />
                <Route path="/" element={<Navigate to="/login/" />} />
                <Route path="/courses/:courseId/" element={<CoursePage />} />
                <Route path="/courses/:courseId/students/:studentId/" element={<StudentProgressPage />} />
            </Routes>
        </BrowserRouter>
    );
}

export default App;
