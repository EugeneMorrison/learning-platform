import { useState } from 'react';
import { createBrowserRouter, RouterProvider, Navigate, Outlet } from 'react-router-dom';
import AppHeader from './components/AppHeader';
import { LessonBarContext, SetLessonBarContext } from './lib/lessonBar';
import LessonViewer from './pages/LessonViewer';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import DashboardPage from './pages/DashboardPage';
import CoursePage from './pages/CoursePage';
import StudentProgressPage from './pages/StudentProgressPage';
import LessonEditor from './pages/LessonEditor';
import EnrollPage from './pages/EnrollPage';

// The lesson page's data for the app header (lib/lessonBar.js). Its own
// component, so a change re-renders the header but not the page (children).
function LessonBarProvider({ children }) {
    const [lessonBar, setLessonBar] = useState(null);
    return (
        <SetLessonBarContext.Provider value={setLessonBar}>
            <LessonBarContext.Provider value={lessonBar}>
                {children}
            </LessonBarContext.Provider>
        </SetLessonBarContext.Provider>
    );
}

// The header on every page, the page below it.
function Layout() {
    return (
        <LessonBarProvider>
            <AppHeader />
            <Outlet />
        </LessonBarProvider>
    );
}

// A data router (not <BrowserRouter>): the lesson editor's useBlocker needs one.
const router = createBrowserRouter([
    {
        element: <Layout />,
        children: [
            { path: '/login/', element: <LoginPage /> },
            { path: '/register/', element: <RegisterPage /> },
            { path: '/dashboard/', element: <DashboardPage /> },
            { path: '/enroll/:courseId/', element: <EnrollPage /> },
            { path: '/lesson/:lessonId/edit/', element: <LessonEditor /> },
            { path: '/lesson/:lessonId/', element: <LessonViewer /> },
            { path: '/', element: <Navigate to="/login/" /> },
            { path: '/courses/:courseId/', element: <CoursePage /> },
            { path: '/courses/:courseId/students/:studentId/', element: <StudentProgressPage /> },
            // Unknown path: the header and an empty page, as <Routes> did
            // (not the data router's own 404 screen).
            { path: '*', element: null },
        ],
    },
]);

function App() {
    return <RouterProvider router={router} />;
}

export default App;
